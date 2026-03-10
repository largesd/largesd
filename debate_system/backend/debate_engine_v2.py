"""
Enhanced Debate Engine v2
Full implementation with span extraction, canonicalization, audits, and persistence
"""
import uuid
import json
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Any
from collections import defaultdict

# Import our new modules
from database import DebateDatabase
from llm_client import LLMClient
from extraction import ExtractionEngine, ExtractedSpan, ExtractedFact, ExtractedArgument
from extraction import CanonicalFact as ExCanonicalFact, CanonicalArgument as ExCanonicalArgument
from topic_engine import TopicEngine, Topic
from scoring_engine import ScoringEngine, TopicSideScores
from fact_checker import FactChecker
from tokenizer import ContentMassCalculator, get_canonical_tokenizer
from modulation import ModulationEngine, ModulationOutcome, create_modulated_post
from snapshot_diff import SnapshotDiffEngine
from evidence_targets import EvidenceTargetAnalyzer


class DebateEngineV2:
    """
    Enhanced debate engine with full MSD specification compliance
    """
    
    def __init__(self, db_path: str = "data/debate_system.db",
                 fact_check_mode: str = "OFFLINE",
                 llm_provider: str = "mock",
                 num_judges: int = 5,
                 modulation_template: str = "standard_civility",
                 openrouter_api_key: Optional[str] = None):
        
        # Initialize components
        self.db = DebateDatabase(db_path)
        
        # Determine API key to use
        api_key = None
        if llm_provider.startswith("openrouter"):
            api_key = openrouter_api_key or os.getenv("OPENROUTER_API_KEY")
            if not api_key:
                raise ValueError(
                    f"OpenRouter provider selected but no API key found. "
                    f"Set OPENROUTER_API_KEY environment variable or pass openrouter_api_key."
                )
        
        self.llm_client = LLMClient(
            provider=llm_provider, 
            num_judges=num_judges,
            api_key=api_key
        )
        self.extraction_engine = ExtractionEngine(self.llm_client)
        self.topic_engine = TopicEngine(self.llm_client)
        self.scoring_engine = ScoringEngine(self.llm_client, num_judges=num_judges)
        self.fact_checker = FactChecker(mode=fact_check_mode)
        self.content_mass_calculator = ContentMassCalculator()
        
        # Initialize modulation engine with template (MSD §3)
        self.modulation_engine = ModulationEngine(
            ModulationEngine.get_builtin_template(modulation_template)
        )
        
        # Initialize snapshot diff engine (MSD §16)
        self.diff_engine = SnapshotDiffEngine(self.db)
        
        # Initialize evidence target analyzer (MSD §15)
        self.evidence_analyzer = EvidenceTargetAnalyzer(self.db)
        
        # In-memory cache
        self._debate_cache: Dict[str, Dict] = {}
    
    def create_debate(self, resolution: str, scope: str) -> Dict:
        """Create a new debate"""
        debate_id = f"debate_{uuid.uuid4().hex[:8]}"
        
        debate_data = {
            'debate_id': debate_id,
            'resolution': resolution,
            'scope': scope,
            'created_at': datetime.now().isoformat(),
            'current_snapshot_id': None
        }
        
        # Save to database
        self.db.save_debate(debate_data)
        
        # Cache
        self._debate_cache[debate_id] = debate_data
        
        return debate_data
    
    def get_debate(self, debate_id: str) -> Optional[Dict]:
        """Get debate by ID"""
        # Check cache first
        if debate_id in self._debate_cache:
            return self._debate_cache[debate_id]
        
        # Load from database
        debate = self.db.get_debate(debate_id)
        if debate:
            self._debate_cache[debate_id] = debate
        return debate
    
    def submit_post(self, debate_id: str, side: str, topic_id: Optional[str],
                    facts: str, inference: str,
                    counter_arguments: str = "") -> Dict:
        """
        Submit a new post to a debate
        """
        debate = self.get_debate(debate_id)
        if not debate:
            raise ValueError(f"Debate {debate_id} not found")
        
        post_id = f"post_{uuid.uuid4().hex[:12]}"
        
        post_data = {
            'post_id': post_id,
            'debate_id': debate_id,
            'side': side.upper(),
            'topic_id': topic_id,
            'facts': facts,
            'inference': inference,
            'counter_arguments': counter_arguments,
            'timestamp': datetime.now().isoformat(),
            'modulation_outcome': 'allowed',
            'block_reason': None
        }
        
        # Apply modulation using template (MSD §3)
        outcome, block_reason, matched_rules = self.modulation_engine.apply_modulation(post_data)
        post_data['modulation_outcome'] = outcome.value
        post_data['block_reason'] = block_reason.value if block_reason else None
        post_data['modulation_matched_rules'] = matched_rules
        post_data['modulation_template'] = self.modulation_engine.template.get_version_string()
        
        # Save post
        self.db.save_post(post_data)
        
        # If allowed, extract spans
        if post_data['modulation_outcome'] == 'allowed':
            self._extract_and_save_spans(post_data)
        
        return post_data
    
    def get_modulation_info(self) -> Dict:
        """Get current modulation template info for audit (MSD §3)"""
        return self.modulation_engine.get_audit_info()
    
    def _extract_and_save_spans(self, post_data: Dict):
        """Extract and save spans for an allowed post"""
        # Extract spans using LLM
        fact_spans, inference_span = self.extraction_engine.extract_spans_from_post(
            post_data['post_id'],
            post_data['facts'],
            post_data['inference'],
            post_data['side'],
            post_data.get('topic_id')
        )
        
        # Save spans to database with token counts (MSD §11)
        tokenizer = get_canonical_tokenizer()
        
        for span in fact_spans:
            token_count = tokenizer.count_tokens(span.span_text)
            self.db.save_span({
                'span_id': span.span_id,
                'post_id': span.post_id,
                'start_offset': span.start_offset,
                'end_offset': span.end_offset,
                'span_text': span.span_text,
                'topic_id': span.topic_id,
                'side': span.side,
                'span_type': span.span_type,
                'token_count': token_count
            })
        
        if inference_span:
            token_count = tokenizer.count_tokens(inference_span.span_text)
            self.db.save_span({
                'span_id': inference_span.span_id,
                'post_id': inference_span.post_id,
                'start_offset': inference_span.start_offset,
                'end_offset': inference_span.end_offset,
                'span_text': inference_span.span_text,
                'topic_id': inference_span.topic_id,
                'side': inference_span.side,
                'span_type': inference_span.span_type,
                'token_count': token_count
            })
    
    def generate_snapshot(self, debate_id: str,
                          trigger_type: str = "activity") -> Dict:
        """
        Generate a new snapshot with full processing pipeline
        """
        debate = self.get_debate(debate_id)
        if not debate:
            raise ValueError(f"Debate {debate_id} not found")
        
        # Get all posts for this debate
        posts = self.db.get_posts_by_debate(debate_id)
        allowed_posts = [p for p in posts if p['modulation_outcome'] == 'allowed']
        blocked_posts = [p for p in posts if p['modulation_outcome'] == 'blocked']
        
        # Count block reasons
        block_reasons = defaultdict(int)
        for p in blocked_posts:
            if p.get('block_reason'):
                block_reasons[p['block_reason']] += 1
        
        # Extract or update topics
        previous_topics = []
        previous_snapshot = self.db.get_latest_snapshot(debate_id)
        if previous_snapshot:
            # Load previous topics
            prev_topics_data = self.db.get_topics_by_debate(debate_id)
            previous_topics = [Topic(**t) for t in prev_topics_data]
        
        # Extract new topics
        topics = self.topic_engine.extract_topics_from_posts(
            allowed_posts,
            debate['resolution']
        )
        
        # Enforce topic bounds
        topics = self.topic_engine.enforce_topic_bounds(
            topics, allowed_posts, debate['resolution']
        )
        
        # Compute topic drift
        drift_report = self.topic_engine.compute_topic_drift(topics, previous_topics)
        
        # Assign posts to topics
        post_assignments = self.topic_engine.assign_posts_to_topics(allowed_posts, topics)
        
        # Update topic IDs on posts
        for topic_id, post_ids in post_assignments.items():
            for post_id in post_ids:
                # Update post topic_id in database
                # (This would need a database update method)
                pass
        
        # Save topics
        for topic in topics:
            topic_data = {
                'topic_id': topic.topic_id,
                'debate_id': debate_id,
                'name': topic.name,
                'scope': topic.scope,
                'relevance': topic.relevance,
                'drift_score': topic.drift_score,
                'coherence': topic.coherence,
                'distinctness': topic.distinctness,
                'parent_topic_ids': topic.parent_topic_ids,
                'operation': topic.operation,
                'summary_for': topic.summary_for,
                'summary_against': topic.summary_against,
                'created_at': datetime.now().isoformat()
            }
            self.db.save_topic(topic_data)
        
        # Process facts and arguments per topic
        topic_facts: Dict[str, List[Dict]] = {}
        topic_arguments: Dict[str, List[Dict]] = {}
        topic_content_mass: Dict[str, int] = {}
        
        for topic in topics:
            tid = topic.topic_id
            topic_posts = [p for p in allowed_posts if p.get('topic_id') == tid or 
                          p['post_id'] in post_assignments.get(tid, [])]
            
            # Extract facts and arguments
            all_extracted_facts = []
            all_argument_units = []
            
            for post in topic_posts:
                # Get spans for this post
                spans = self.db.get_spans_by_post(post['post_id'])
                
                fact_spans = [
                    ExtractedSpan(
                        span_id=s['span_id'],
                        post_id=s['post_id'],
                        start_offset=s['start_offset'],
                        end_offset=s['end_offset'],
                        span_text=s['span_text'],
                        topic_id=s.get('topic_id'),
                        side=s['side'],
                        span_type=s['span_type']
                    )
                    for s in spans if s['span_type'] == 'fact'
                ]
                
                inf_spans = [
                    ExtractedSpan(
                        span_id=s['span_id'],
                        post_id=s['post_id'],
                        start_offset=s['start_offset'],
                        end_offset=s['end_offset'],
                        span_text=s['span_text'],
                        topic_id=s.get('topic_id'),
                        side=s['side'],
                        span_type=s['span_type']
                    )
                    for s in spans if s['span_type'] == 'inference'
                ]
                
                inference_span = inf_spans[0] if inf_spans else None
                
                # Extract facts from spans
                extracted_facts = self.extraction_engine.extract_facts_from_spans(
                    fact_spans, tid, post['side']
                )
                
                # Fact-check each fact
                for fact in extracted_facts:
                    check_result = self.fact_checker.check_fact(fact.fact_text)
                    fact.p_true = check_result.factuality_score
                
                all_extracted_facts.extend(extracted_facts)
                
                # Create argument units
                if inference_span:
                    aus = self.extraction_engine.create_argument_units(
                        fact_spans, inference_span, extracted_facts, tid, post['side']
                    )
                    all_argument_units.extend(aus)
            
            # Canonicalize facts
            canonical_facts = self.extraction_engine.canonicalize_facts(
                all_extracted_facts, topic.scope
            )
            
            # Save canonical facts
            topic_facts[tid] = []
            for cf in canonical_facts:
                fact_data = {
                    'canon_fact_id': cf.canon_fact_id,
                    'debate_id': debate_id,
                    'topic_id': cf.topic_id,
                    'side': cf.side,
                    'canon_fact_text': cf.canon_fact_text,
                    'member_fact_ids': cf.member_fact_ids,
                    'p_true': cf.p_true,
                    'provenance_links': [
                        {'span_id': s.span_id, 'text': s.span_text}
                        for s in cf.provenance_spans
                    ],
                    'referenced_by_au_ids': [],
                    'created_at': datetime.now().isoformat()
                }
                self.db.save_canonical_fact(fact_data)
                topic_facts[tid].append(fact_data)
            
            # Canonicalize arguments
            canonical_args = self.extraction_engine.canonicalize_arguments(
                all_argument_units, canonical_facts, topic.scope
            )
            
            # Save canonical arguments
            topic_arguments[tid] = []
            for ca in canonical_args:
                arg_data = {
                    'canon_arg_id': ca.canon_arg_id,
                    'debate_id': debate_id,
                    'topic_id': ca.topic_id,
                    'side': ca.side,
                    'inference_text': ca.inference_text,
                    'supporting_facts': list(ca.supporting_facts),
                    'member_au_ids': ca.member_au_ids,
                    'provenance_links': [
                        {'span_id': s.span_id, 'text': s.span_text}
                        for s in ca.provenance_spans
                    ],
                    'reasoning_score': 0.5,  # Will be computed by scoring
                    'reasoning_iqr': 0.0,
                    'created_at': datetime.now().isoformat()
                }
                self.db.save_canonical_argument(arg_data)
                topic_arguments[tid].append(arg_data)
            
            # Compute content mass per MSD §11
            # Mass_t = token count of spans contributing to canonical FACT/ARGUMENT nodes
            spans_lookup = {s['span_id']: s for s in all_spans}
            content_mass = self.content_mass_calculator.calculate_topic_mass(
                topic_facts[tid],
                topic_arguments[tid],
                spans_lookup
            )
            topic_content_mass[tid] = content_mass
        
        # Generate steelman summaries
        for topic in topics:
            tid = topic.topic_id
            args = topic_arguments.get(tid, [])
            
            for_args = [a for a in args if a['side'] == 'FOR']
            against_args = [a for a in args if a['side'] == 'AGAINST']
            
            if for_args:
                summary_for = self.llm_client.generate_steelman_summary(for_args, 'FOR')
                topic.summary_for = summary_for.get('summary', '')
            
            if against_args:
                summary_against = self.llm_client.generate_steelman_summary(against_args, 'AGAINST')
                topic.summary_against = summary_against.get('summary', '')
        
        # Compute scores
        scores = self.scoring_engine.compute_debate_scores(
            [{'topic_id': t.topic_id, 'name': t.name, 'scope': t.scope,
              'relevance': t.relevance, 'drift_score': t.drift_score,
              'coherence': t.coherence, 'distinctness': t.distinctness}
             for t in topics],
            topic_facts,
            topic_arguments,
            topic_content_mass
        )
        
        # Run replicates for verdict
        replicates = self.scoring_engine.run_replicates(
            [{'topic_id': t.topic_id} for t in topics],
            topic_facts,
            topic_arguments,
            topic_content_mass
        )
        
        verdict_result = self.scoring_engine.compute_verdict(replicates)
        
        # Compute counterfactuals
        counterfactuals = self.scoring_engine.compute_counterfactuals(
            [{'topic_id': t.topic_id} for t in topics],
            topic_facts,
            topic_arguments,
            topic_content_mass
        )
        
        # Run audits
        # 1. Extraction stability
        stability_audit = self.extraction_engine.compute_extraction_stability(
            allowed_posts, topic.scope if topics else ""
        )
        
        # 2. Side-label symmetry
        symmetry_audit = self.scoring_engine.run_side_label_symmetry_audit(
            [{'topic_id': t.topic_id} for t in topics],
            topic_facts,
            topic_arguments,
            topic_content_mass
        )
        
        # 3. Relevance sensitivity
        relevance_audit = self.scoring_engine.compute_relevance_sensitivity(
            [{'topic_id': t.topic_id} for t in topics],
            topic_facts,
            topic_arguments,
            topic_content_mass
        )
        
        # Create snapshot
        snapshot_id = f"snap_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"
        
        snapshot_data = {
            'snapshot_id': snapshot_id,
            'debate_id': debate_id,
            'timestamp': datetime.now().isoformat(),
            'trigger_type': trigger_type,
            'template_name': self.modulation_engine.template.name,
            'template_version': self.modulation_engine.template.version,
            'allowed_count': len(allowed_posts),
            'blocked_count': len(blocked_posts),
            'block_reasons': dict(block_reasons),
            'overall_for': scores['overall_for'],
            'overall_against': scores['overall_against'],
            'margin_d': scores['margin_d'],
            'ci_d_lower': verdict_result['ci_lower'],
            'ci_d_upper': verdict_result['ci_upper'],
            'confidence': verdict_result['confidence'],
            'verdict': verdict_result['verdict'],
            'topic_scores': scores['topic_scores']
        }
        
        # Save snapshot
        self.db.save_snapshot(snapshot_data)
        
        # Update debate current snapshot
        debate['current_snapshot_id'] = snapshot_id
        self.db.save_debate(debate)
        
        # Save audits
        for audit_type, audit_data in [
            ('extraction_stability', stability_audit),
            ('side_label_symmetry', symmetry_audit),
            ('relevance_sensitivity', relevance_audit),
            ('topic_drift', drift_report)
        ]:
            self.db.save_audit({
                'audit_id': f"audit_{snapshot_id}_{audit_type}",
                'snapshot_id': snapshot_id,
                'audit_type': audit_type,
                'result_data': audit_data,
                'created_at': datetime.now().isoformat()
            })
        
        # Return complete snapshot data
        return {
            **snapshot_data,
            'topics': [
                {
                    'topic_id': t.topic_id,
                    'name': t.name,
                    'scope': t.scope,
                    'relevance': t.relevance,
                    'drift_score': t.drift_score,
                    'coherence': t.coherence,
                    'distinctness': t.distinctness,
                    'summary_for': t.summary_for,
                    'summary_against': t.summary_against,
                    'operation': t.operation,
                    'parent_topic_ids': t.parent_topic_ids
                }
                for t in topics
            ],
            'canonical_facts': topic_facts,
            'canonical_arguments': topic_arguments,
            'audits': {
                'extraction_stability': stability_audit,
                'side_label_symmetry': symmetry_audit,
                'relevance_sensitivity': relevance_audit,
                'topic_drift': drift_report
            },
            'counterfactuals': counterfactuals
        }
    
    def get_snapshot(self, snapshot_id: str) -> Optional[Dict]:
        """Get snapshot by ID"""
        # This would need a get_snapshot_by_id method in the database
        # For now, return from latest
        return None
    
    def get_audits_for_snapshot(self, snapshot_id: str) -> Dict:
        """Get all audits for a snapshot"""
        audits = self.db.get_audits_by_snapshot(snapshot_id)
        
        result = {}
        for audit in audits:
            result[audit['audit_type']] = json.loads(audit['result_data'])
        
        return result
    
    def get_topic_lineage(self, debate_id: str) -> List[Dict]:
        """Get topic lineage across all snapshots"""
        topics = self.db.get_topics_by_debate(debate_id)
        
        # Build lineage graph
        lineage = []
        for topic in topics:
            parent_ids = json.loads(topic.get('parent_topic_ids', '[]'))
            lineage.append({
                'topic_id': topic['topic_id'],
                'name': topic['name'],
                'parent_topic_ids': parent_ids,
                'operation': topic.get('operation', 'created'),
                'drift_score': topic.get('drift_score', 0.0)
            })
        
        return lineage
    
    def diff_snapshots(self, snapshot_id_old: str, snapshot_id_new: str) -> Dict:
        """
        Compute diff between two snapshots (MSD §16).
        
        Returns detailed comparison of:
        - Posts included changes
        - Topic lineage changes
        - FACT set changes
        - ARGUMENT set changes
        - Score distributions and D distribution changes
        """
        diff = self.diff_engine.diff_snapshots(snapshot_id_old, snapshot_id_new)
        return diff.to_dict()
    
    def get_snapshot_history(self, debate_id: str) -> List[Dict]:
        """Get chronological history of snapshots for a debate"""
        return self.diff_engine.get_snapshot_history(debate_id)
    
    def compare_consecutive_snapshots(self, debate_id: str) -> Optional[Dict]:
        """
        Compare the two most recent snapshots.
        Returns None if fewer than 2 snapshots exist.
        """
        history = self.get_snapshot_history(debate_id)
        if len(history) < 2:
            return None
        
        # Get last two snapshots
        snap_new = history[-1]
        snap_old = history[-2]
        
        return self.diff_snapshots(
            snap_old['snapshot_id'],
            snap_new['snapshot_id']
        )
    
    def get_evidence_targets(self, debate_id: str, 
                             snapshot_id: Optional[str] = None) -> Dict:
        """
        Get "What evidence would change this" analysis (MSD §15).
        
        Identifies:
        - High-leverage arguments
        - Decisive supporting FACT nodes
        - Evidence needed to shift uncertain facts
        - Update triggers
        """
        result = self.evidence_analyzer.analyze_evidence_targets(
            debate_id, snapshot_id
        )
        return result.to_dict()
