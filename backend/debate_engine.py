"""
Debate Engine - Main orchestration module
Handles debate creation, post processing, snapshot generation

Updated to integrate with async Fact Checking Skill
"""
import uuid
import time
from datetime import datetime
from typing import List, Dict, Optional

from models import (
    Debate, Post, Topic, CanonicalFact, CanonicalArgument, Snapshot,
    Side, ModulationOutcome, BlockReason, TopicSideScores
)
from extraction import ExtractionEngine
from scoring import ScoringEngine

# Import new fact checking skill
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from skills.fact_checking import FactCheckingSkill, RequestContext


class DebateEngine:
    """
    Main engine for the Blind LLM-Adjudicated Debate System
    
    Integrates with Fact Checking Skill for P(true) values.
    Supports both sync and async fact checking modes.
    """
    
    def __init__(self, fact_check_mode: str = "OFFLINE", 
                 enable_async_fact_check: bool = True):
        """
        Initialize debate engine.
        
        Args:
            fact_check_mode: "OFFLINE" or "ONLINE_ALLOWLIST"
            enable_async_fact_check: Whether to use async fact checking
        """
        # Initialize fact checking skill
        self.fact_checker = FactCheckingSkill(
            mode=fact_check_mode,
            allowlist_version="v1",
            enable_async=enable_async_fact_check,
            async_worker_count=3
        )
        
        # Initialize extraction engine with fact checker
        self.extraction_engine = ExtractionEngine(
            fact_check_skill=self.fact_checker
        )
        
        self.scoring_engine = ScoringEngine(num_judges=5, num_replicates=100)
        self.debates: Dict[str, Debate] = {}
        
        self._fact_check_mode = fact_check_mode
        self._async_enabled = enable_async_fact_check
    
    def create_debate(self, resolution: str, scope: str, user_id: Optional[str] = None) -> Debate:
        """Create a new debate"""
        debate_id = f"debate_{uuid.uuid4().hex[:8]}"
        debate = Debate(
            debate_id=debate_id,
            resolution=resolution,
            scope=scope,
            created_at=datetime.now(),
            user_id=user_id
        )
        self.debates[debate_id] = debate
        return debate
    
    def get_debate(self, debate_id: str) -> Optional[Debate]:
        """Get debate by ID"""
        return self.debates.get(debate_id)
    
    def submit_post(self, debate_id: str, side: str, topic_id: str,
                    facts: str, inference: str, 
                    counter_arguments: str = "",
                    user_id: Optional[str] = None) -> Post:
        """
        Submit a new post to a debate
        """
        debate = self.get_debate(debate_id)
        if not debate:
            raise ValueError(f"Debate {debate_id} not found")
        
        post = Post(
            post_id=f"post_{uuid.uuid4().hex[:12]}",
            side=Side.FOR if side.upper() == "FOR" else Side.AGAINST,
            topic_id=topic_id,
            facts=facts,
            inference=inference,
            counter_arguments=counter_arguments,
            timestamp=datetime.now()
        )
        
        # Apply modulation
        post = self._apply_modulation(post)
        
        debate.pending_posts.append(post)
        return post
    
    def _apply_modulation(self, post: Post) -> Post:
        """
        Apply moderation rules to a post
        """
        combined_text = f"{post.facts} {post.inference}".lower()
        
        # Check for blocked content (simplified)
        blocked_keywords = [
            "harass", "attack", "kill", "die", "stupid", "idiot"
        ]
        
        for keyword in blocked_keywords:
            if keyword in combined_text:
                post.modulation_outcome = ModulationOutcome.BLOCKED
                post.block_reason = BlockReason.HARASSMENT
                return post
        
        # Check for PII patterns (simplified)
        import re
        if re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', combined_text):
            post.modulation_outcome = ModulationOutcome.BLOCKED
            post.block_reason = BlockReason.PII
            return post
        
        # Check length
        if len(combined_text) < 20:
            post.modulation_outcome = ModulationOutcome.BLOCKED
            post.block_reason = BlockReason.SPAM
            return post
        
        # Check off-topic (must contain debate-related keywords)
        debate_keywords = ["ai", "artificial", "intelligence", "ban", "safety", 
                          "regulation", "risk", "development", "technology"]
        if not any(kw in combined_text for kw in debate_keywords):
            post.modulation_outcome = ModulationOutcome.BLOCKED
            post.block_reason = BlockReason.OFF_TOPIC
            return post
        
        post.modulation_outcome = ModulationOutcome.ALLOWED
        return post
    
    def _extract_facts(self, post: Post, topic_id: str) -> List[CanonicalFact]:
        """
        Extract and fact-check atomic facts from a post.
        Uses the extraction engine which integrates with fact checking skill.
        """
        # Use extraction engine to extract spans
        fact_spans, _ = self.extraction_engine.extract_spans_from_post(
            post.post_id,
            post.facts,
            post.inference,
            post.side.value,
            topic_id
        )
        
        # Extract facts with fact checking
        extracted_facts = self.extraction_engine.extract_facts_from_spans(
            fact_spans,
            topic_id,
            post.side.value,
            post.post_id
        )
        
        # If async mode, give workers a moment to process (in production, this would be longer)
        if self._async_enabled and self._fact_check_mode == "ONLINE_ALLOWLIST":
            # Small delay to allow some fact checks to complete
            # In production, this would be replaced with proper polling/waiting
            time.sleep(0.1)
            
            # Update with any completed results
            extracted_facts = self.extraction_engine.update_fact_check_results(extracted_facts)
        
        # Convert to CanonicalFacts
        canonical_facts = []
        for i, ef in enumerate(extracted_facts):
            cf = CanonicalFact(
                canon_fact_id=f"F{post.post_id}_{i}",
                canon_fact_text=ef.fact_text[:200],
                member_fact_ids={ef.fact_id},
                merged_provenance_links=[],
                referenced_by_au_ids=set(),
                p_true=ef.p_true  # This now comes from fact checker
            )
            canonical_facts.append(cf)
        
        # If no facts extracted, create from facts text directly
        if not canonical_facts:
            fact_texts = [f.strip() for f in post.facts.split('\n') if f.strip()]
            fact_texts = [f.lstrip('•-* ') for f in fact_texts]
            
            for i, fact_text in enumerate(fact_texts):
                # Fact-check this claim
                try:
                    request_context = RequestContext(post_id=post.post_id)
                    check_result = self.fact_checker.check_fact(
                        fact_text, 
                        request_context=request_context,
                        wait_for_async=True  # Wait for async to complete
                    )
                    p_true = check_result.factuality_score
                except Exception:
                    p_true = 0.5  # Default on error
                
                cf = CanonicalFact(
                    canon_fact_id=f"F{post.post_id}_{i}",
                    canon_fact_text=fact_text[:200],
                    member_fact_ids={f"F{post.post_id}_{i}"},
                    merged_provenance_links=[],
                    referenced_by_au_ids=set(),
                    p_true=p_true
                )
                canonical_facts.append(cf)
        
        return canonical_facts
    
    def _extract_arguments(self, post: Post, facts: List[CanonicalFact]) -> List[CanonicalArgument]:
        """
        Extract canonical arguments from a post
        """
        arguments = []
        
        arg_id = f"A{post.post_id}"
        
        # Create argument with supporting facts
        arg = CanonicalArgument(
            canon_arg_id=arg_id,
            topic_id=post.topic_id,
            side=post.side,
            supporting_facts={f.canon_fact_id for f in facts},
            inference_text=post.inference[:300],
            member_au_ids={arg_id},
            merged_provenance=[],
            reasoning_score=0.6 + (0.2 if post.counter_arguments else 0),  # Bonus for addressing counters
            reasoning_iqr=0.15
        )
        arguments.append(arg)
        
        return arguments
    
    def _create_default_topics(self) -> List[Topic]:
        """Create default topics for AI ban debate"""
        return [
            Topic(
                topic_id="t1",
                name="Safety & misuse risk",
                scope="Whether banning AI reduces harms like misinformation, weaponization, or catastrophic misuse, versus mitigation via governance.",
                relevance=0.34,
                drift_score=0.12,
                coherence=0.71,
                distinctness=0.68,
                summary_for="Arg A1: advanced AI increases the probability of high-impact misuse; a precautionary ban reduces exposure while verification regimes mature. Arg A2: current mitigation tools are not reliably deployable at scale; limiting development buys time.",
                summary_against="Arg A3: bans push development underground and reduce safety research transparency; regulated openness improves safety outcomes. Arg A4: targeted controls (model evals, deployment limits) reduce harms without eliminating beneficial uses."
            ),
            Topic(
                topic_id="t2",
                name="Economic & social impact",
                scope="Effects on jobs, inequality, productivity, and access to opportunity under a ban vs regulated deployment.",
                relevance=0.28,
                drift_score=0.09,
                coherence=0.65,
                distinctness=0.73
            ),
            Topic(
                topic_id="t3",
                name="Enforceability & geopolitics",
                scope="Feasibility of enforcing a ban globally and the strategic consequences if some actors comply and others do not.",
                relevance=0.22,
                drift_score=0.15,
                coherence=0.62,
                distinctness=0.70
            ),
            Topic(
                topic_id="t4",
                name="Rights, freedom & innovation",
                scope="Whether banning AI violates rights (speech, research) and stifles beneficial innovation, versus moral duties to prevent harm.",
                relevance=0.16,
                drift_score=0.07,
                coherence=0.69,
                distinctness=0.75
            )
        ]
    
    def generate_snapshot(self, debate_id: str, 
                          trigger_type: str = "activity") -> Snapshot:
        """
        Generate a new snapshot with scoring
        """
        debate = self.get_debate(debate_id)
        if not debate:
            raise ValueError(f"Debate {debate_id} not found")
        
        # Process pending posts
        all_posts = debate.pending_posts.copy()
        
        # If no posts yet, create sample data for demo
        if not all_posts and not debate.current_snapshot:
            all_posts = self._create_sample_posts()
        
        # Separate allowed and blocked
        allowed_posts = [p for p in all_posts if p.modulation_outcome == ModulationOutcome.ALLOWED]
        blocked_posts = [p for p in all_posts if p.modulation_outcome == ModulationOutcome.BLOCKED]
        
        # Count block reasons
        block_reasons = {}
        for p in blocked_posts:
            if p.block_reason:
                block_reasons[p.block_reason] = block_reasons.get(p.block_reason, 0) + 1
        
        # Group posts by topic
        posts_by_topic: Dict[str, List[Post]] = {}
        for post in allowed_posts:
            if post.topic_id not in posts_by_topic:
                posts_by_topic[post.topic_id] = []
            posts_by_topic[post.topic_id].append(post)
        
        # Extract facts and arguments per topic
        topic_facts: Dict[str, List[CanonicalFact]] = {}
        topic_arguments: Dict[str, List[CanonicalArgument]] = {}
        topic_content_mass: Dict[str, int] = {}
        
        # Get or create topics
        if debate.current_snapshot:
            topics = debate.current_snapshot.topics
        else:
            topics = self._create_default_topics()
        
        for topic in topics:
            tid = topic.topic_id
            posts = posts_by_topic.get(tid, [])
            
            facts = []
            args = []
            content_mass = 0
            
            for post in posts:
                post_facts = self._extract_facts(post, tid)
                post_args = self._extract_arguments(post, post_facts)
                
                facts.extend(post_facts)
                args.extend(post_args)
                content_mass += len(post.facts) + len(post.inference)
            
            # Add sample data if empty
            if not facts:
                facts, args = self._create_sample_topic_data(tid)
                content_mass = 500
            
            topic_facts[tid] = facts
            topic_arguments[tid] = args
            topic_content_mass[tid] = content_mass
        
        # Compute scores
        scores = self.scoring_engine.compute_debate_scores(
            topics, topic_facts, topic_arguments, topic_content_mass
        )
        
        # Run replicates for verdict
        replicates = self.scoring_engine.run_replicates(
            topics, topic_facts, topic_arguments, topic_content_mass
        )
        
        verdict_result = self.scoring_engine.compute_verdict(replicates)
        
        # Compute counterfactuals
        counterfactuals = self.scoring_engine.compute_counterfactuals(
            topics, topic_facts, topic_arguments, topic_content_mass
        )
        
        # Create snapshot
        snapshot_id = f"snap_{datetime.now().strftime('%Y-%m-%dT%H%MZ')}_{len(debate.snapshots):04d}"
        
        snapshot = Snapshot(
            snapshot_id=snapshot_id,
            timestamp=datetime.now(),
            trigger_type=trigger_type,
            template_name="Standard Civility + PII Guard v3",
            template_version="3.2.1",
            posts=allowed_posts,
            allowed_count=len(allowed_posts),
            blocked_count=len(blocked_posts),
            block_reasons=block_reasons,
            topics=topics,
            canonical_facts=topic_facts,
            canonical_arguments=topic_arguments,
            topic_scores=scores["topic_scores"],
            overall_for=scores["overall_for"],
            overall_against=scores["overall_against"],
            margin_d=scores["margin_d"],
            ci_d_lower=verdict_result["ci_lower"],
            ci_d_upper=verdict_result["ci_upper"],
            confidence=verdict_result["confidence"],
            verdict=verdict_result["verdict"]
        )
        
        # Update debate
        debate.current_snapshot = snapshot
        debate.snapshots.append(snapshot)
        debate.pending_posts = []  # Clear pending
        
        return snapshot
    
    def _create_sample_posts(self) -> List[Post]:
        """Create sample posts for initial demo"""
        return [
            Post(
                post_id="post_0xA7",
                side=Side.FOR,
                topic_id="t1",
                facts="Advanced AI capabilities can lower the cost of generating convincing misinformation at scale.\nSome AI systems can be adapted to assist in harmful applications if safeguards are bypassed.",
                inference="A precautionary ban reduces exposure to large-scale misuse while safety governance matures.",
                counter_arguments="",
                timestamp=datetime.now(),
                modulation_outcome=ModulationOutcome.ALLOWED
            ),
            Post(
                post_id="post_0xB1",
                side=Side.FOR,
                topic_id="t1",
                facts="Current safety evaluation methods do not fully predict rare high-impact failures.",
                inference="Mitigation methods are insufficiently reliable; slowing deployment buys time for alignment and evaluation.",
                counter_arguments="",
                timestamp=datetime.now(),
                modulation_outcome=ModulationOutcome.ALLOWED
            ),
            Post(
                post_id="post_0xC3",
                side=Side.AGAINST,
                topic_id="t1",
                facts="Bans can shift development to less transparent environments with weaker safety practices.\nDeployment-time controls can reduce misuse even when models exist.\nSafety research benefits from access to capable models and open testing.",
                inference="Bans push development underground, reducing transparency and worsening safety outcomes.",
                counter_arguments="A1",
                timestamp=datetime.now(),
                modulation_outcome=ModulationOutcome.ALLOWED
            ),
        ]
    
    def _create_sample_topic_data(self, topic_id: str) -> tuple:
        """Create sample facts and arguments for a topic"""
        if topic_id == "t1":
            facts = [
                CanonicalFact(
                    canon_fact_id="F1",
                    canon_fact_text="Advanced AI capabilities can lower the cost of generating convincing misinformation at scale.",
                    member_fact_ids={"F1"},
                    merged_provenance_links=[],
                    referenced_by_au_ids={"A1"},
                    p_true=0.78
                ),
                CanonicalFact(
                    canon_fact_id="F2",
                    canon_fact_text="Some AI systems can be adapted to assist in harmful applications if safeguards are bypassed.",
                    member_fact_ids={"F2"},
                    merged_provenance_links=[],
                    referenced_by_au_ids={"A1"},
                    p_true=0.71
                ),
                CanonicalFact(
                    canon_fact_id="F3",
                    canon_fact_text="Current safety evaluation methods do not fully predict rare high-impact failures.",
                    member_fact_ids={"F3"},
                    merged_provenance_links=[],
                    referenced_by_au_ids={"A2"},
                    p_true=0.58
                ),
                CanonicalFact(
                    canon_fact_id="F4",
                    canon_fact_text="Bans can shift development to less transparent environments with weaker safety practices.",
                    member_fact_ids={"F4"},
                    merged_provenance_links=[],
                    referenced_by_au_ids={"A3"},
                    p_true=0.62
                ),
                CanonicalFact(
                    canon_fact_id="F5",
                    canon_fact_text="Deployment-time controls can reduce misuse even when models exist.",
                    member_fact_ids={"F5"},
                    merged_provenance_links=[],
                    referenced_by_au_ids={"A4"},
                    p_true=0.66
                ),
                CanonicalFact(
                    canon_fact_id="F6",
                    canon_fact_text="Safety research benefits from access to capable models and open testing.",
                    member_fact_ids={"F6"},
                    merged_provenance_links=[],
                    referenced_by_au_ids={"A4"},
                    p_true=0.74
                ),
            ]
            
            args = [
                CanonicalArgument(
                    canon_arg_id="A1",
                    topic_id="t1",
                    side=Side.FOR,
                    supporting_facts={"F1", "F2"},
                    inference_text="Precautionary ban reduces exposure to large-scale misuse while safety governance matures.",
                    member_au_ids={"A1"},
                    merged_provenance=[],
                    reasoning_score=0.64,
                    reasoning_iqr=0.21
                ),
                CanonicalArgument(
                    canon_arg_id="A2",
                    topic_id="t1",
                    side=Side.FOR,
                    supporting_facts={"F3"},
                    inference_text="Mitigation methods are insufficiently reliable; slowing deployment buys time for alignment and evaluation.",
                    member_au_ids={"A2"},
                    merged_provenance=[],
                    reasoning_score=0.58,
                    reasoning_iqr=0.26
                ),
                CanonicalArgument(
                    canon_arg_id="A3",
                    topic_id="t1",
                    side=Side.AGAINST,
                    supporting_facts={"F4"},
                    inference_text="Bans push development underground, reducing transparency and worsening safety outcomes.",
                    member_au_ids={"A3"},
                    merged_provenance=[],
                    reasoning_score=0.61,
                    reasoning_iqr=0.18
                ),
                CanonicalArgument(
                    canon_arg_id="A4",
                    topic_id="t1",
                    side=Side.AGAINST,
                    supporting_facts={"F5", "F6"},
                    inference_text="Targeted regulation outperforms bans by preserving benefits and supporting safety research.",
                    member_au_ids={"A4"},
                    merged_provenance=[],
                    reasoning_score=0.70,
                    reasoning_iqr=0.16
                ),
            ]
            return facts, args
        
        # Default empty for other topics
        return [], []
    
    def get_fact_check_stats(self) -> Dict:
        """Get statistics from the fact checking skill"""
        return {
            'cache': self.fact_checker.get_cache_stats(),
            'audit': self.fact_checker.get_audit_stats(),
            'queue': self.fact_checker.get_queue_stats(),
            'mode': self._fact_check_mode,
            'async_enabled': self._async_enabled,
        }
    
    def shutdown(self):
        """Shutdown the debate engine and its components"""
        self.fact_checker.shutdown()
