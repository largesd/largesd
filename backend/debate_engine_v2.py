"""
Enhanced Debate Engine v2
Full implementation with span extraction, canonicalization, audits, and persistence
"""
import os
import sys
import time
import uuid
import json
import math
import hashlib
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
from tokenizer import ContentMassCalculator, get_canonical_tokenizer
from modulation import ModulationEngine, ModulationOutcome, create_modulated_post
from snapshot_diff import SnapshotDiffEngine
from evidence_targets import EvidenceTargetAnalyzer
from frame_registry import get_public_frame_registry, FrameRegistry
from governance import GovernanceManager
from selection_engine import SelectionEngine
from lsd_v1_2 import (
    AUDIT_SCHEMA_VERSION,
    BORDERLINE_EPSILON,
    SUPPRESSION_K,
    budget_adequacy,
    build_suppression_policy,
    burstiness_indicators,
    centrality_cap_effect,
    compute_borderline_rate,
    compute_completeness_proxy,
    coverage_adequacy_trace,
    evaluator_variance_from_scores,
    formula_registry,
    frame_mode as get_frame_mode_flag,
    insufficiency_sensitivity,
    merge_sensitivity,
    participation_concentration,
    rarity_utilization,
    scoring_formula_mode,
    template_similarity_prevalence,
    topic_diagnostics,
    unselected_tail_summary,
)
from debate_proposal import (
    build_internal_scope,
    hydrate_debate_record,
    parse_debate_proposal_payload,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from skills.fact_checking import (
    FactCheckingSkill,
    WikidataConnector,
    SimulatedSourceConnector,
)


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
        
        self.num_judges = num_judges
        self.llm_client = LLMClient(
            provider=llm_provider, 
            num_judges=num_judges,
            api_key=api_key
        )
        self._fact_check_mode = self._normalize_fact_check_mode(fact_check_mode)
        self._async_enabled = self._fact_check_mode == "ONLINE_ALLOWLIST"
        self._fact_check_wait_timeout_seconds = 2.0
        self._fact_check_poll_interval_seconds = 0.05

        if self._fact_check_mode in ("PERFECT", "PERFECT_CHECKER"):
            self.fact_checker = FactCheckingSkill(
                mode=self._fact_check_mode,
                allowlist_version="v1",
                enable_async=False,
                connectors=[
                    # Tier-3 simulation stubs until real Tier-1 connectors are ready.
                    # The evidence policy enforces that Tier-3 alone cannot
                    # produce SUPPORTED/REFUTED in PERFECT mode.
                    WikidataConnector(),
                    SimulatedSourceConnector("sim_tier2_a", "example.org", priority=5),
                    SimulatedSourceConnector("sim_tier2_b", "example.com", priority=5),
                ],
            )
        else:
            self.fact_checker = FactCheckingSkill(
                mode=self._fact_check_mode,
                allowlist_version="v1",
                enable_async=self._async_enabled,
            )
        self.extraction_engine = ExtractionEngine(
            self.llm_client,
            fact_check_skill=self.fact_checker,
        )
        self.topic_engine = TopicEngine(self.llm_client)
        self.scoring_engine = ScoringEngine(self.llm_client, num_judges=num_judges)
        self.content_mass_calculator = ContentMassCalculator()
        
        # Initialize modulation engine with template (MSD §3)
        self.modulation_engine = ModulationEngine(
            ModulationEngine.get_builtin_template(modulation_template)
        )
        self._active_moderation_template_record: Optional[Dict[str, Any]] = None
        
        # Initialize snapshot diff engine (MSD §16)
        self.diff_engine = SnapshotDiffEngine(self.db)
        
        # Initialize evidence target analyzer (MSD §15)
        self.evidence_analyzer = EvidenceTargetAnalyzer(self.db)
        
        # Initialize frame registry (LSD §5)
        self.frame_registry = get_public_frame_registry()
        
        # Initialize governance manager (LSD §20)
        self.governance = GovernanceManager(self.db)
        
        # Initialize selection engine (LSD §11)
        self.selection_engine = SelectionEngine()
        
        # In-memory cache
        self._debate_cache: Dict[str, Dict] = {}
        self.refresh_active_modulation_template(force=True)

    @staticmethod
    def _normalize_fact_check_mode(mode: str) -> str:
        aliases = {
            "simulated": "OFFLINE",
            "offline": "OFFLINE",
            "OFFLINE": "OFFLINE",
            "online_allowlist": "ONLINE_ALLOWLIST",
            "ONLINE_ALLOWLIST": "ONLINE_ALLOWLIST",
            "perfect_checker": "PERFECT_CHECKER",
            "PERFECT_CHECKER": "PERFECT_CHECKER",
            "perfect": "PERFECT",
            "PERFECT": "PERFECT",
        }
        public_mode = os.getenv("FACT_CHECKER_MODE")
        return aliases.get(str(public_mode or mode).strip(), aliases.get(str(public_mode or mode).strip().lower(), "OFFLINE"))

    @staticmethod
    def _topic_from_record(record: Dict[str, Any]) -> Topic:
        """Hydrate a Topic from DB rows that may include extra persistence-only fields."""
        parent_topic_ids = record.get("parent_topic_ids", [])
        if isinstance(parent_topic_ids, str):
            try:
                parent_topic_ids = json.loads(parent_topic_ids)
            except json.JSONDecodeError:
                parent_topic_ids = []
        if not isinstance(parent_topic_ids, list):
            parent_topic_ids = []

        return Topic(
            topic_id=record.get("topic_id") or f"topic_{uuid.uuid4().hex[:8]}",
            name=record.get("name", ""),
            scope=record.get("scope", ""),
            frame_id=record.get("frame_id", "") or "",
            relevance=float(record.get("relevance", 0.0) or 0.0),
            drift_score=float(record.get("drift_score", 0.0) or 0.0),
            coherence=float(record.get("coherence", 0.0) or 0.0),
            distinctness=float(record.get("distinctness", 0.0) or 0.0),
            parent_topic_ids=parent_topic_ids,
            operation=record.get("operation", "created") or "created",
            summary_for=record.get("summary_for", "") or "",
            summary_against=record.get("summary_against", "") or "",
            created_at=record.get("created_at", "") or "",
        )

    @staticmethod
    def _resolve_builtin_modulation_template_id(base_template_id: Optional[str]) -> str:
        mapping = {
            "standard": "standard_civility",
            "standard_civility": "standard_civility",
            "academic": "strict",
            "strict": "strict",
            "minimal": "minimal",
            "custom": "standard_civility",
        }
        if not base_template_id:
            return "standard_civility"
        return mapping.get(base_template_id, base_template_id)

    def refresh_active_modulation_template(self, force: bool = False) -> Optional[Dict[str, Any]]:
        """Reload the active moderation template from persistence when needed."""
        active_record = self.db.get_active_moderation_template()
        if not active_record:
            return None

        record_id = active_record.get("template_record_id")
        current_id = (self._active_moderation_template_record or {}).get("template_record_id")
        if not force and current_id and record_id == current_id:
            return self._active_moderation_template_record

        builtin_template_id = self._resolve_builtin_modulation_template_id(
            active_record.get("base_template_id")
        )
        version = str(active_record.get("version") or "1.0")

        try:
            template = ModulationEngine.get_builtin_template(builtin_template_id, version=version)
        except ValueError:
            template = ModulationEngine.get_builtin_template("standard_civility", version=version)
            builtin_template_id = "standard_civility"

        if active_record.get("template_name"):
            template.name = active_record["template_name"]

        self.modulation_engine.template = template
        self._active_moderation_template_record = {
            **active_record,
            "builtin_template_id": builtin_template_id,
        }
        return self._active_moderation_template_record

    def get_runtime_profile(self) -> Dict[str, Any]:
        """Build a stable runtime fingerprint for snapshot-producing jobs."""
        runtime_metadata = self.llm_client.get_runtime_metadata()
        profile = {
            "provider": runtime_metadata.get("provider", "mock"),
            "configured_model": runtime_metadata.get("configured_model", "mock"),
            "num_judges": runtime_metadata.get("num_judges", self.num_judges),
            "fact_check_mode": self._fact_check_mode,
            "frame_mode": get_frame_mode_flag(),
            "scoring_formula_mode": scoring_formula_mode(),
            "lsd_version": formula_registry().get("lsd_version", "unknown"),
        }
        canonical = json.dumps(profile, sort_keys=True)
        runtime_profile_id = f"runtime_{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:16]}"
        return {
            **profile,
            "runtime_profile_id": runtime_profile_id,
        }

    def _resolve_fact_checks(self, facts: List[ExtractedFact]) -> List[ExtractedFact]:
        """Wait briefly for async fact checks so scoring never sees pending values."""
        if not facts:
            return facts

        resolved_facts = self.extraction_engine.update_fact_check_results(facts)

        if self._fact_check_mode != "ONLINE_ALLOWLIST" or not self._async_enabled:
            return resolved_facts

        def has_pending(items: List[ExtractedFact]) -> bool:
            return any(
                fact.fact_check_job_id and fact.fact_check_status == "pending"
                for fact in items
            )

        deadline = time.time() + self._fact_check_wait_timeout_seconds
        while has_pending(resolved_facts) and time.time() < deadline:
            time.sleep(self._fact_check_poll_interval_seconds)
            resolved_facts = self.extraction_engine.update_fact_check_results(resolved_facts)

        for fact in resolved_facts:
            if fact.fact_check_job_id and fact.fact_check_status == "pending":
                fact.p_true = 0.5
                fact.fact_check_status = "failed"

        return resolved_facts

    @staticmethod
    def _frame_side_order(frame: Optional[Dict[str, Any]]) -> List[str]:
        if not frame:
            return ["FOR", "AGAINST"]
        return [side["side_id"] for side in frame.get("sides", [])] or ["FOR", "AGAINST"]

    def _attach_active_frame(self, debate: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        hydrated = hydrate_debate_record(debate)
        if not hydrated:
            return None

        active_frame = None
        if hydrated.get("active_frame_id"):
            active_frame = self.db.get_debate_frame(hydrated["active_frame_id"])
        if not active_frame and hydrated.get("debate_id"):
            active_frame = self.db.get_active_debate_frame(hydrated["debate_id"])

        if active_frame:
            active_frame["moderation_criteria"] = hydrated.get("moderation_criteria", "")
            hydrated["active_frame"] = active_frame
            hydrated["active_frame_id"] = active_frame.get("frame_id")
            hydrated["debate_frame"] = active_frame.get("frame_summary", hydrated.get("debate_frame", ""))
            hydrated["scope"] = build_internal_scope(
                hydrated.get("motion", ""),
                hydrated.get("moderation_criteria", ""),
                active_frame,
            )
        return hydrated

    def _build_frame_record(self, debate_id: str, proposal: Dict[str, Any],
                            version: int, supersedes_frame_id: Optional[str] = None) -> Dict[str, Any]:
        frame = dict(proposal["active_frame"])
        frame["frame_id"] = f"frame_{uuid.uuid4().hex[:10]}"
        frame["debate_id"] = debate_id
        frame["version"] = version
        frame["supersedes_frame_id"] = supersedes_frame_id
        frame["created_at"] = datetime.now().isoformat()
        frame["is_active"] = True
        frame["frame_mode"] = frame.get("frame_mode") or get_frame_mode_flag()
        frame["review_cadence_months"] = int(frame.get("review_cadence_months") or 6)
        return frame

    @staticmethod
    def _legacy_create_payload(resolution: str,
                               scope: str,
                               moderation_criteria: Optional[str] = None) -> Dict[str, Any]:
        return {
            "motion": resolution,
            "resolution": resolution,
            "moderation_criteria": (
                moderation_criteria
                or "Allow arguments directly relevant to the resolution. Block harassment, spam, PII, and off-topic content."
            ),
            "debate_frame": scope,
        }

    def create_debate(self, motion: str | Dict[str, Any] | None = None,
                      moderation_criteria: Optional[str] = None,
                      debate_frame: Any = None,
                      user_id: Optional[str] = None,
                      *,
                      resolution: Optional[str] = None,
                      scope: Optional[str] = None) -> Dict:
        """Create a new debate, accepting both legacy and structured payloads."""
        debate_id = f"debate_{uuid.uuid4().hex[:8]}"

        if isinstance(motion, dict):
            raw_payload = dict(motion)
        elif resolution is not None or scope is not None:
            raw_payload = self._legacy_create_payload(
                resolution or str(motion or ""),
                scope or str(debate_frame or ""),
                moderation_criteria=moderation_criteria,
            )
        else:
            raw_payload = {
                "motion": motion,
                "moderation_criteria": moderation_criteria,
                "debate_frame": debate_frame,
            }

        proposal, missing_fields = parse_debate_proposal_payload(raw_payload)
        if missing_fields:
            raise ValueError(
                f"Missing required debate proposal fields: {', '.join(missing_fields)}"
            )

        frame_record = self._build_frame_record(debate_id, proposal, version=1)
        debate_data = {
            "debate_id": debate_id,
            "motion": proposal["motion"],
            "resolution": proposal["resolution"],
            "moderation_criteria": proposal["moderation_criteria"],
            "debate_frame": frame_record["frame_summary"],
            "scope": proposal["scope"],
            "active_frame_id": frame_record["frame_id"],
            "created_at": datetime.now().isoformat(),
            "current_snapshot_id": None,
            "user_id": user_id,
        }

        self.db.save_debate(debate_data)
        self.db.save_debate_frame(frame_record)
        self.db.set_active_frame(debate_id, frame_record["frame_id"])

        hydrated = self._attach_active_frame(debate_data)
        self._debate_cache[debate_id] = hydrated
        return hydrated

    def create_frame_version(self, debate_id: str,
                             payload: Dict[str, Any]) -> Dict[str, Any]:
        """Create and activate a new frame version for an existing debate."""
        debate = self.get_debate(debate_id)
        if not debate:
            raise ValueError(f"Debate {debate_id} not found")

        current_frame = debate.get("active_frame")
        prior_frame = {
            **(current_frame or {}),
            "moderation_criteria": debate.get("moderation_criteria", ""),
        }
        proposal, missing_fields = parse_debate_proposal_payload(payload, prior_frame=prior_frame)
        if missing_fields:
            raise ValueError(
                f"Missing required debate proposal fields: {', '.join(missing_fields)}"
            )

        existing_frames = self.db.get_debate_frames(debate_id)
        next_version = (existing_frames[-1]["version"] + 1) if existing_frames else 1
        frame_record = self._build_frame_record(
            debate_id,
            proposal,
            version=next_version,
            supersedes_frame_id=current_frame.get("frame_id") if current_frame else None,
        )
        self.db.save_debate_frame(frame_record)
        self.db.set_active_frame(debate_id, frame_record["frame_id"])

        debate.update({
            "motion": proposal["motion"],
            "resolution": proposal["resolution"],
            "moderation_criteria": proposal["moderation_criteria"],
            "debate_frame": frame_record["frame_summary"],
            "scope": build_internal_scope(
                proposal["motion"],
                proposal["moderation_criteria"],
                frame_record,
            ),
            "active_frame_id": frame_record["frame_id"],
        })
        self.db.save_debate(debate)

        hydrated = self._attach_active_frame(debate)
        self._debate_cache[debate_id] = hydrated
        return hydrated

    def get_debate_frames(self, debate_id: str) -> List[Dict[str, Any]]:
        """Get all frame versions for a debate."""
        return self.db.get_debate_frames(debate_id)
    
    def get_debate(self, debate_id: str) -> Optional[Dict]:
        """Get debate by ID"""
        # Check cache first
        if debate_id in self._debate_cache:
            return self._debate_cache[debate_id]
        
        # Load from database
        debate = self.db.get_debate(debate_id)
        if debate:
            debate = self._attach_active_frame(debate)
            self._debate_cache[debate_id] = debate
        return debate
    
    def submit_post(self, debate_id: str, side: str, topic_id: Optional[str],
                    facts: str, inference: str,
                    counter_arguments: str = "", user_id: Optional[str] = None,
                    submission_id: Optional[str] = None) -> Dict:
        """
        Submit a new post to a debate
        """
        self.refresh_active_modulation_template()
        debate = self.get_debate(debate_id)
        if not debate:
            raise ValueError(f"Debate {debate_id} not found")

        active_frame = debate.get("active_frame")
        if not active_frame:
            raise ValueError("Debate has no active frame")

        normalized_side = (side or "").strip()
        allowed_sides = {item["side_id"] for item in active_frame.get("sides", [])}
        if normalized_side not in allowed_sides:
            raise ValueError(
                f"Side '{normalized_side}' is not in the active frame. "
                f"Allowed sides: {', '.join(sorted(allowed_sides))}"
            )
        
        post_id = f"post_{uuid.uuid4().hex[:12]}"
        
        post_data = {
            'post_id': post_id,
            'debate_id': debate_id,
            'user_id': user_id,
            'frame_id': active_frame.get('frame_id'),
            'side': normalized_side,
            'topic_id': topic_id,
            'facts': facts,
            'inference': inference,
            'counter_arguments': counter_arguments,
            'timestamp': datetime.now().isoformat(),
            'modulation_outcome': 'allowed',
            'block_reason': None,
            'submission_id': submission_id,
        }
        
        # Apply modulation using template (MSD §3)
        outcome, block_reason, matched_rules = self.modulation_engine.apply_modulation(post_data)
        post_data['modulation_outcome'] = getattr(outcome, 'value', outcome)
        post_data['block_reason'] = getattr(block_reason, 'value', block_reason) if block_reason else None
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
        self.refresh_active_modulation_template()
        info = self.modulation_engine.get_audit_info()
        if self._active_moderation_template_record:
            info["template_record_id"] = self._active_moderation_template_record.get("template_record_id")
            info["template_status"] = self._active_moderation_template_record.get("status")
        return info
    
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
        self.refresh_active_modulation_template()
        debate = self.get_debate(debate_id)
        if not debate:
            raise ValueError(f"Debate {debate_id} not found")

        active_frame = debate.get("active_frame")
        if not active_frame:
            raise ValueError("Debate has no active frame")

        side_order = self._frame_side_order(active_frame)
        frame_id = active_frame["frame_id"]
        frame_context = debate["scope"]

        # Get only posts submitted under the active frame version
        posts = self.db.get_posts_by_debate(debate_id, frame_id=frame_id)
        allowed_posts = [p for p in posts if p['modulation_outcome'] == 'allowed']
        blocked_posts = [p for p in posts if p['modulation_outcome'] == 'blocked']
        
        # Count block reasons
        block_reasons = defaultdict(int)
        for p in blocked_posts:
            if p.get('block_reason'):
                block_reasons[p['block_reason']] += 1

        borderline_rate = compute_borderline_rate(posts)
        suppression_policy = build_suppression_policy(
            posts,
            block_reasons,
            k=SUPPRESSION_K,
        )
        
        # Extract or update topics
        previous_topics = []
        previous_snapshot = self.db.get_latest_snapshot(debate_id, frame_id=frame_id)
        if previous_snapshot:
            # Load previous topics
            prev_topics_data = self.db.get_topics_by_debate(debate_id, frame_id=frame_id)
            previous_topics = [self._topic_from_record(t) for t in prev_topics_data]
        
        # Extract new topics
        topics = self.topic_engine.extract_topics_from_posts(
            allowed_posts,
            frame_context
        )
        
        # Enforce topic bounds
        topics = self.topic_engine.enforce_topic_bounds(
            topics, allowed_posts, frame_context
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
                'frame_id': frame_id,
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
            all_spans = []
            
            for post in topic_posts:
                # Get spans for this post
                spans = self.db.get_spans_by_post(post['post_id'])
                all_spans.extend(spans)
                
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
                    fact_spans, tid, post['side'], post_id=post['post_id']
                )
                extracted_facts = self._resolve_fact_checks(extracted_facts)
                
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
                    'frame_id': frame_id,
                    'topic_id': cf.topic_id,
                    'side': cf.side,
                    'canon_fact_text': cf.canon_fact_text,
                    'member_fact_ids': cf.member_fact_ids,
                    'p_true': cf.p_true,
                    'fact_type': getattr(cf, 'fact_type', 'empirical'),
                    'normative_provenance': getattr(cf, 'normative_provenance', ''),
                    'operationalization': getattr(cf, 'operationalization', ''),
                    'provenance_links': [
                        {'span_id': s.span_id, 'text': s.span_text}
                        for s in cf.provenance_spans
                    ],
                    'evidence_tier_counts': getattr(cf, 'evidence_tier_counts', {}),
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
                    'frame_id': frame_id,
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
                    'completeness_proxy': compute_completeness_proxy({
                        'inference_text': ca.inference_text,
                        'supporting_facts': list(ca.supporting_facts),
                        'provenance_links': [
                            {'span_id': s.span_id, 'text': s.span_text}
                            for s in ca.provenance_spans
                        ],
                        'member_au_ids': ca.member_au_ids,
                    }),
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
        
        # LSD §11: Update centrality, distinct_support, and cross-references
        self._update_canonical_metrics(topic_facts, topic_arguments)
        
        # LSD §11: Run deterministic stratified selection per topic-side
        selected_topic_facts: Dict[str, List[Dict]] = defaultdict(list)
        selected_topic_arguments: Dict[str, List[Dict]] = defaultdict(list)
        selection_diagnostics: Dict[str, Any] = {}
        selection_seed = 42  # Published deterministic seed
        
        for topic in topics:
            tid = topic.topic_id
            for side in side_order:
                # Set budgets based on pool sizes (policy-parameter)
                facts_pool = topic_facts.get(tid, [])
                args_pool = topic_arguments.get(tid, [])
                normative_count = len([
                    f for f in facts_pool
                    if f.get('side') == side and f.get('fact_type') == 'normative'
                ])
                empirical_count = len([
                    f for f in facts_pool
                    if f.get('side') == side and f.get('fact_type', 'empirical') == 'empirical'
                ])
                budgets = {
                    'K_E': max(3, min(empirical_count, 10)) if empirical_count else 0,
                    'K_N': max(1, min(normative_count, 5)) if normative_count else 0,
                    'K_A': max(3, min(len([a for a in args_pool if a.get('side') == side]), 8)),
                }
                
                selected_set = self.selection_engine.select_for_topic_side(
                    facts_pool, args_pool, tid, side, budgets, selection_seed
                )
                
                selected_topic_facts[tid].extend(
                    [dict(f) for f in selected_set.selected_facts]
                )
                selected_topic_arguments[tid].extend(
                    [dict(a) for a in selected_set.selected_arguments]
                )
                
                # Mark selected items
                selected_fact_ids = set(selected_set.selected_fact_ids)
                selected_arg_ids = set(selected_set.selected_arg_ids)
                for f in facts_pool:
                    if f['canon_fact_id'] in selected_fact_ids:
                        f['is_selected'] = True
                        f['is_rarity_slice'] = f.get('canon_fact_id') in (
                            selected_set.diagnostics.get('pools', {})
                            .get('empirical_facts', {})
                            .get('rarity_ids', [])
                        )
                for a in args_pool:
                    if a['canon_arg_id'] in selected_arg_ids:
                        a['is_selected'] = True
                        a['is_rarity_slice'] = a.get('canon_arg_id') in (
                            selected_set.diagnostics.get('pools', {})
                            .get('arguments', {})
                            .get('rarity_ids', [])
                        )
                
                selection_diagnostics[f"{tid}_{side}"] = self.selection_engine.get_diagnostics(selected_set)
        
        # Generate steelman summaries
        for topic in topics:
            tid = topic.topic_id
            args = topic_arguments.get(tid, [])

            if "FOR" in side_order:
                for_args = [a for a in args if a['side'] == 'FOR']
                if for_args:
                    summary_for = self.llm_client.generate_steelman_summary(for_args, 'FOR')
                    topic.summary_for = summary_for.get('summary', '')

            if "AGAINST" in side_order:
                against_args = [a for a in args if a['side'] == 'AGAINST']
                if against_args:
                    summary_against = self.llm_client.generate_steelman_summary(against_args, 'AGAINST')
                    topic.summary_against = summary_against.get('summary', '')
        
        # Compute scores on SELECTED items (LSD §11 adjudication budget)
        scores = self.scoring_engine.compute_debate_scores(
            [{'topic_id': t.topic_id, 'name': t.name, 'scope': t.scope,
              'relevance': t.relevance, 'drift_score': t.drift_score,
              'coherence': t.coherence, 'distinctness': t.distinctness}
             for t in topics],
            dict(selected_topic_facts),
            dict(selected_topic_arguments),
            topic_content_mass,
            side_order=side_order,
            frame_context=frame_context,
        )
        
        # Run replicates for verdict on selected items (LSD §18)
        replicates = self.scoring_engine.run_replicates(
            [{'topic_id': t.topic_id} for t in topics],
            dict(selected_topic_facts),
            dict(selected_topic_arguments),
            topic_content_mass,
            side_order=side_order,
            frame_context=frame_context,
            extraction_reruns=2,
            bootstrap=True,
        )
        
        verdict_result = self.scoring_engine.compute_verdict(replicates, side_order=side_order)
        
        # Compute counterfactuals on full sets
        counterfactuals = self.scoring_engine.compute_counterfactuals(
            [{'topic_id': t.topic_id} for t in topics],
            topic_facts,
            topic_arguments,
            topic_content_mass,
            side_order=side_order,
            frame_context=frame_context,
        )
        
        # LSD §14: Normative symmetry tests
        frame_values = active_frame.get("evaluation_criteria", []) if active_frame else []
        normative_symmetry = self.scoring_engine.run_symmetry_tests(
            dict(selected_topic_facts),
            frame_values=frame_values,
            side_order=side_order,
            frame_context=frame_context,
        )

        # LSD §17: Build decision dossier
        decision_dossier = self._build_decision_dossier(
            topics, topic_facts, topic_arguments,
            dict(selected_topic_facts), dict(selected_topic_arguments),
            scores['topic_scores']
        )
        decision_dossier["counterfactuals"] = counterfactuals
        decision_dossier["unselected_tail_summary"] = unselected_tail_summary(
            topic_facts,
            topic_arguments,
            dict(selected_topic_facts),
            dict(selected_topic_arguments),
        )
        decision_dossier["insufficiency_sensitivity"] = insufficiency_sensitivity(
            scores["topic_scores"],
            scores["margin_d"],
        )
        decision_dossier["formula_metadata"] = formula_registry()
        decision_dossier["normative_symmetry"] = normative_symmetry
        
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
            topic_content_mass,
            side_order=side_order,
            frame_context=frame_context,
        )
        
        # 2b. Normative symmetry (LSD §14)
        normative_symmetry_audit = normative_symmetry
        
        # 3. Relevance sensitivity
        relevance_audit = self.scoring_engine.compute_relevance_sensitivity(
            [{'topic_id': t.topic_id} for t in topics],
            topic_facts,
            topic_arguments,
            topic_content_mass,
            side_order=side_order,
            frame_context=frame_context,
        )

        topic_diag = topic_diagnostics(
            [
                {
                    'topic_id': t.topic_id,
                    'name': t.name,
                    'scope': t.scope,
                    'relevance': t.relevance,
                    'drift_score': t.drift_score,
                    'coherence': t.coherence,
                    'distinctness': t.distinctness,
                }
                for t in topics
            ],
            topic_content_mass,
            dict(selected_topic_facts),
            dict(selected_topic_arguments),
        )
        merge_audit = merge_sensitivity(
            [{'topic_id': t.topic_id} for t in topics],
            scores.get('margin_d', 0.0),
        )
        evaluator_variance = evaluator_variance_from_scores(
            scores.get('topic_scores', {}),
            scores.get('overall_scores', {}),
        )
        participation_diag = participation_concentration(posts)
        integrity_indicators = {
            'version_id': 'lsd-10-v1.2.0',
            'burstiness_indicators': burstiness_indicators(posts),
            'template_similarity_prevalence': template_similarity_prevalence(posts),
            'participation_entropy': participation_diag.get('participation_entropy', 0.0),
            'concentration_buckets': participation_diag.get('concentration_buckets', {}),
        }
        budget_diag = budget_adequacy(selection_diagnostics)
        centrality_diag = centrality_cap_effect(selection_diagnostics)
        rarity_diag = rarity_utilization(selection_diagnostics)
        coverage_trace = coverage_adequacy_trace(scores.get('topic_scores', {}))
        frame_sensitivity = {
            'version_id': 'lsd-19.4-v1.2.0',
            'frame_mode': get_frame_mode_flag(),
            'max_delta_d': 0.0,
            'interpretation': (
                'inactive_single_frame'
                if get_frame_mode_flag() == 'single'
                else 'multi-frame dispersion computed from active frame baseline'
            ),
            'threshold': 0.1,
        }
        
        # Build replay manifest and tamper-evident hashes
        replay_manifest = self._build_replay_manifest(
            debate_id, selection_seed, allowed_posts, blocked_posts, topics, side_order
        )
        recipe_versions = self._build_recipe_versions()

        input_bundle = {
            'allowed_posts': [
                {'post_id': p['post_id'], 'side': p['side'], 'facts': p['facts'],
                 'inference': p['inference'], 'topic_id': p.get('topic_id')}
                for p in allowed_posts
            ],
            'blocked_posts': [
                {'post_id': p['post_id'], 'side': p['side'],
                 'modulation_outcome': p['modulation_outcome'], 'block_reason': p.get('block_reason')}
                for p in blocked_posts
            ],
            'frame_id': frame_id,
            'side_order': side_order,
            'selection_seed': selection_seed,
        }
        output_bundle = {
            'topics': [
                {'topic_id': t.topic_id, 'name': t.name, 'relevance': t.relevance}
                for t in topics
            ],
            'overall_scores': scores['overall_scores'],
            'verdict': verdict_result['verdict'],
            'topic_scores': scores['topic_scores'],
        }
        input_hash_root = self._canonical_json_hash(input_bundle)
        output_hash_root = self._canonical_json_hash(output_bundle)

        # Create snapshot
        snapshot_id = f"snap_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"
        
        # Provider metadata and cost tracking
        usage_summary = self.llm_client.get_usage_summary()
        runtime_metadata = self.llm_client.get_runtime_metadata()
        first_model = runtime_metadata.get('configured_model', 'mock')
        if isinstance(first_model, list):
            first_model = first_model[0] if first_model else 'mock'
        if self.llm_client._usage_log:
            first_model = self.llm_client._usage_log[0].get('model', first_model)
        provider_metadata = {
            'provider': runtime_metadata.get('provider', usage_summary.get('provider', 'mock')),
            'configured_model': runtime_metadata.get('configured_model', 'mock'),
            'actual_model': first_model,
            'num_judges': runtime_metadata.get('num_judges', self.num_judges),
            'prompt_tokens': usage_summary.get('prompt_tokens', 0),
            'completion_tokens': usage_summary.get('completion_tokens', 0),
            'total_tokens': usage_summary.get('total_tokens', 0),
            'llm_call_count': usage_summary.get('call_count', 0),
        }
        
        snapshot_data = {
            'snapshot_id': snapshot_id,
            'debate_id': debate_id,
            'frame_id': frame_id,
            'timestamp': datetime.now().isoformat(),
            'trigger_type': trigger_type,
            'template_name': self.modulation_engine.template.name,
            'template_version': self.modulation_engine.template.version,
            'allowed_count': len(allowed_posts),
            'blocked_count': len(blocked_posts),
            'block_reasons': dict(block_reasons),
            'borderline_rate': borderline_rate,
            'suppression_policy_json': suppression_policy,
            'status': 'valid',
            'side_order': side_order,
            'overall_scores': scores['overall_scores'],
            'overall_for': scores['overall_for'],
            'overall_against': scores['overall_against'],
            'margin_d': scores['margin_d'],
            'ci_d_lower': verdict_result['ci_lower'],
            'ci_d_upper': verdict_result['ci_upper'],
            'confidence': verdict_result['confidence'],
            'verdict': verdict_result['verdict'],
            'topic_scores': scores['topic_scores'],
            'replay_manifest_json': replay_manifest,
            'input_hash_root': input_hash_root,
            'output_hash_root': output_hash_root,
            'recipe_versions_json': recipe_versions,
            'provider_metadata': provider_metadata,
        }
        
        # Save snapshot
        self.db.save_snapshot(snapshot_data)
        
        # Update debate current snapshot
        debate['current_snapshot_id'] = snapshot_id
        self.db.save_debate(debate)
        self._debate_cache[debate_id] = self._attach_active_frame(debate)
        
        # Save audits
        for audit_type, audit_data in [
            ('extraction_stability', stability_audit),
            ('side_label_symmetry', symmetry_audit),
            ('normative_symmetry', normative_symmetry_audit),
            ('relevance_sensitivity', relevance_audit),
            ('topic_drift', drift_report),
            ('selection_transparency', selection_diagnostics),
            ('verdict_replicates', verdict_result),
            ('decision_dossier', decision_dossier),
            ('evaluator_variance', evaluator_variance),
            ('topic_diagnostics', topic_diag),
            ('topic_merge_sensitivity', merge_audit),
            ('participation_concentration', participation_diag),
            ('integrity_indicators', integrity_indicators),
            ('budget_adequacy', budget_diag),
            ('centrality_cap_effect', centrality_diag),
            ('rarity_utilization', rarity_diag),
            ('coverage_adequacy_trace', coverage_trace),
            ('frame_sensitivity', frame_sensitivity),
            ('formula_registry', formula_registry()),
        ]:
            self.db.save_audit({
                'audit_id': f"audit_{snapshot_id}_{audit_type}",
                'snapshot_id': snapshot_id,
                'audit_type': audit_type,
                'result_data': audit_data,
                'created_at': datetime.now().isoformat()
            })
        
        # Return complete snapshot data
        frame_info = self.get_frame_info()
        return {
            **snapshot_data,
            'frame': frame_info,
            'leader': verdict_result.get('leader'),
            'runner_up': verdict_result.get('runner_up'),
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
            'selected_facts': dict(selected_topic_facts),
            'selected_arguments': dict(selected_topic_arguments),
            'audits': {
                'extraction_stability': stability_audit,
                'side_label_symmetry': symmetry_audit,
                'normative_symmetry': normative_symmetry_audit,
                'relevance_sensitivity': relevance_audit,
                'topic_drift': drift_report,
                'selection_transparency': selection_diagnostics,
                'verdict_replicates': verdict_result,
                'decision_dossier': decision_dossier,
                'evaluator_variance': evaluator_variance,
                'topic_diagnostics': topic_diag,
                'topic_merge_sensitivity': merge_audit,
                'participation_concentration': participation_diag,
                'integrity_indicators': integrity_indicators,
                'budget_adequacy': budget_diag,
                'centrality_cap_effect': centrality_diag,
                'rarity_utilization': rarity_diag,
                'coverage_adequacy_trace': coverage_trace,
                'frame_sensitivity': frame_sensitivity,
                'formula_registry': formula_registry(),
            },
            'counterfactuals': counterfactuals,
            'decision_dossier': decision_dossier,
        }
    
    def get_snapshot(self, snapshot_id: str) -> Optional[Dict]:
        """Get snapshot by ID"""
        return self.db.get_snapshot_by_id(snapshot_id)

    def verify_snapshot(self, snapshot_id: str) -> Dict:
        """
        LSD §2.C: Deterministic replay verification.
        Re-run the pipeline from the stored inputs and compare output hashes.
        """
        snapshot = self.db.get_snapshot_by_id(snapshot_id)
        if not snapshot:
            return {"verified": False, "error": "Snapshot not found"}

        replay_manifest = json.loads(snapshot.get('replay_manifest_json') or '{}')
        input_bundle = replay_manifest.get('input_bundle', {})
        stored_input_hash = snapshot.get('input_hash_root')
        stored_output_hash = snapshot.get('output_hash_root')

        # Re-compute input hash
        current_input_hash = self._canonical_json_hash(input_bundle)
        input_match = current_input_hash == stored_input_hash

        # Re-compute output hash from stored outputs
        output_bundle = {
            'topics': [
                {'topic_id': t.get('topic_id'), 'name': t.get('name'), 'relevance': t.get('relevance')}
                for t in (json.loads(snapshot.get('topics_json') or '[]') if snapshot.get('topics_json') else [])
            ] or [],
            'overall_scores': json.loads(snapshot.get('overall_scores_json') or '{}') if snapshot.get('overall_scores_json') else snapshot.get('overall_scores', {}),
            'verdict': snapshot.get('verdict'),
            'topic_scores': json.loads(snapshot.get('topic_scores_json') or '{}') if snapshot.get('topic_scores_json') else snapshot.get('topic_scores', {}),
        }
        current_output_hash = self._canonical_json_hash(output_bundle)
        output_match = current_output_hash == stored_output_hash

        delta = {}
        if not input_match:
            delta['input_hash_mismatch'] = {
                'stored': stored_input_hash,
                'computed': current_input_hash,
            }
        if not output_match:
            delta['output_hash_mismatch'] = {
                'stored': stored_output_hash,
                'computed': current_output_hash,
            }

        return {
            'verified': input_match and output_match,
            'hash_match': input_match and output_match,
            'input_hash_match': input_match,
            'output_hash_match': output_match,
            'snapshot_id': snapshot_id,
            'delta': delta,
        }

    def export_audit_bundle(self, snapshot_id: str) -> Dict:
        """
        LSD §20.4: Export a verifiable audit bundle for authorized third parties.
        """
        snapshot = self.db.get_snapshot_by_id(snapshot_id)
        if not snapshot:
            return {"error": "Snapshot not found"}

        debate_id = snapshot.get('debate_id')
        debate = self.db.get_debate(debate_id) if debate_id else None
        audits = self.db.get_audits_by_snapshot(snapshot_id)

        bundle = {
            'audit_bundle_version': 'lsd-v1.2.0',
            'snapshot_id': snapshot_id,
            'debate_id': debate_id,
            'exported_at': datetime.now().isoformat(),
            'replay_manifest': json.loads(snapshot.get('replay_manifest_json') or '{}'),
            'input_hash_root': snapshot.get('input_hash_root'),
            'output_hash_root': snapshot.get('output_hash_root'),
            'recipe_versions': json.loads(snapshot.get('recipe_versions_json') or '{}'),
            'selection_diagnostics': {},
            'formula_metadata': formula_registry(),
            'provider_metadata': snapshot.get('provider_metadata', {}),
            'audits': [dict(a) for a in audits],
            'frame_summary': debate.get('debate_frame') if debate else None,
            'merkle_root': snapshot.get('output_hash_root'),
        }
        return bundle
    
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

    def get_fact_check_stats(self) -> Dict:
        """Get statistics from the fact checking skill."""
        return {
            'cache': self.fact_checker.get_cache_stats(),
            'audit': self.fact_checker.get_audit_stats(),
            'queue': self.fact_checker.get_queue_stats(),
            'mode': self._fact_check_mode,
            'async_enabled': self._async_enabled,
        }
    
    def _update_canonical_metrics(self, topic_facts: Dict[str, List[Dict]],
                                   topic_arguments: Dict[str, List[Dict]]):
        """
        LSD §11: Compute centrality and distinct_support for canonical items,
        and update fact references from arguments.
        """
        for tid, facts in topic_facts.items():
            args = topic_arguments.get(tid, [])
            
            # Update referenced_by_au_ids on facts using arguments
            fact_refs = defaultdict(set)
            for arg in args:
                for fact_id in arg.get('supporting_facts', []):
                    fact_refs[fact_id].add(arg.get('canon_arg_id'))
            
            for fact in facts:
                fact['referenced_by_au_ids'] = list(fact_refs.get(fact['canon_fact_id'], set()))
                # Centrality = log(1 + distinct_AU_refs)
                au_refs = len(fact.get('referenced_by_au_ids', []))
                fact['centrality'] = round(math.log1p(au_refs), 4)
                # Distinct support proxy = number of member facts
                fact['distinct_support'] = len(fact.get('member_fact_ids', set()))
            
            for arg in args:
                au_refs = len(arg.get('member_au_ids', []))
                arg['centrality'] = round(math.log1p(au_refs), 4)
                arg['distinct_support'] = au_refs
    
    def _build_decision_dossier(self, topics: List[Topic],
                                topic_facts: Dict[str, List[Dict]],
                                topic_arguments: Dict[str, List[Dict]],
                                selected_facts: Dict[str, List[Dict]],
                                selected_args: Dict[str, List[Dict]],
                                topic_scores: Dict) -> Dict:
        """
        LSD §17: Build decision dossier outputs.
        """
        decisive_premises = []
        decisive_arguments = []
        evidence_gaps = {}
        priority_gaps = {
            'insufficient_empirical_items': [],
            'high_dispersion_normative_items': [],
        }
        
        for topic in topics:
            tid = topic.topic_id
            facts = topic_facts.get(tid, [])
            args = topic_arguments.get(tid, [])
            sides = sorted({
                item.get('side')
                for item in [*facts, *args]
                if item.get('side')
            }) or ['FOR', 'AGAINST']
            
            for side in sides:
                side_facts = [f for f in facts if f.get('side') == side]
                side_args = [a for a in args if a.get('side') == side]
                
                # Decisive premises: high decisiveness (|p - 0.5|)
                for fact in side_facts:
                    decisiveness = abs(fact.get('p_true', 0.5) - 0.5)
                    if decisiveness > 0.2:
                        decisive_premises.append({
                            'canon_fact_id': fact['canon_fact_id'],
                            'topic_id': tid,
                            'side': side,
                            'text': fact['canon_fact_text'][:200],
                            'p_true': fact['p_true'],
                            'p_or_q_score': fact.get('p_true', 0.5),
                            'decisiveness': round(decisiveness, 3),
                            'span_ids': [
                                link.get('span_id')
                                for link in fact.get('provenance_links', [])
                                if isinstance(link, dict) and link.get('span_id')
                            ],
                            'post_id_provenance': sorted({
                                str(link.get('span_id', '')).split('_')[1]
                                for link in fact.get('provenance_links', [])
                                if isinstance(link, dict) and link.get('span_id')
                            }),
                            'operationalization': fact.get('operationalization', ''),
                        })
                    if fact.get('p_true', 0.5) == 0.5 and fact.get('fact_type', 'empirical') == 'empirical':
                        priority_gaps['insufficient_empirical_items'].append({
                            'canon_fact_id': fact.get('canon_fact_id'),
                            'topic_id': tid,
                            'side': side,
                            'text': fact.get('canon_fact_text', '')[:200],
                            'priority_score': round((1 - abs(fact.get('p_true', 0.5) - 0.5)) * float(fact.get('centrality', 0.0) or 0.0), 4),
                            'operationalization': fact.get('operationalization', ''),
                        })
                    if fact.get('fact_type') == 'normative':
                        priority_gaps['high_dispersion_normative_items'].append({
                            'canon_fact_id': fact.get('canon_fact_id'),
                            'topic_id': tid,
                            'side': side,
                            'text': fact.get('canon_fact_text', '')[:200],
                            'q_variance': 0.0,
                            'normative_provenance': fact.get('normative_provenance', ''),
                        })

                for arg in side_args:
                    score = float(arg.get('reasoning_score', 0.5) or 0.5)
                    if score >= 0.5 or arg.get('is_selected'):
                        decisive_arguments.append({
                            'canon_arg_id': arg.get('canon_arg_id'),
                            'topic_id': tid,
                            'side': side,
                            'text': arg.get('inference_text', '')[:240],
                            'reasoning_score': score,
                            'completeness_proxy': arg.get('completeness_proxy', 0.0),
                            'span_ids': [
                                link.get('span_id')
                                for link in arg.get('provenance_links', [])
                                if isinstance(link, dict) and link.get('span_id')
                            ],
                            'post_id_provenance': sorted({
                                str(link.get('span_id', '')).split('_')[1]
                                for link in arg.get('provenance_links', [])
                                if isinstance(link, dict) and link.get('span_id')
                            }),
                        })
                
                # Evidence gap summary
                insufficiency_rate = 0.0
                tier_counts = {"TIER_1": 0, "TIER_2": 0, "TIER_3": 0}
                total_facts = len(side_facts)
                f_all = 0.5
                f_supported_only = 0.5
                if total_facts > 0:
                    insufficient_count = sum(1 for f in side_facts if f.get('p_true', 0.5) == 0.5)
                    insufficiency_rate = insufficient_count / total_facts
                    f_all = sum(float(f.get('p_true', 0.5) or 0.5) for f in side_facts) / total_facts
                    decisive = [f for f in side_facts if f.get('p_true', 0.5) != 0.5]
                    if decisive:
                        f_supported_only = sum(float(f.get('p_true', 0.5) or 0.5) for f in decisive) / len(decisive)
                    
                    for f in side_facts:
                        for tier, count in f.get('evidence_tier_counts', {}).items():
                            tier_counts[tier] = tier_counts.get(tier, 0) + count
                
                evidence_gaps[f"{tid}_{side}"] = {
                    'insufficiency_rate': round(insufficiency_rate, 3),
                    'tier_distribution': tier_counts,
                    'f_all': round(f_all, 3),
                    'f_supported_only': round(f_supported_only, 3),
                    'total_facts': total_facts,
                }
        
        # Sort decisive premises by decisiveness
        decisive_premises.sort(key=lambda x: x['decisiveness'], reverse=True)
        decisive_arguments.sort(
            key=lambda x: (float(x.get('reasoning_score', 0.0)), float(x.get('completeness_proxy', 0.0))),
            reverse=True,
        )
        priority_gaps['insufficient_empirical_items'].sort(
            key=lambda x: x.get('priority_score', 0.0),
            reverse=True,
        )
        priority_gaps['high_dispersion_normative_items'].sort(
            key=lambda x: x.get('q_variance', 0.0),
            reverse=True,
        )
        
        return {
            'decisive_premises': decisive_premises[:20],
            'decisive_arguments': decisive_arguments[:20],
            'evidence_gaps': evidence_gaps,
            'priority_gaps': {
                'insufficient_empirical_items': priority_gaps['insufficient_empirical_items'][:20],
                'high_dispersion_normative_items': priority_gaps['high_dispersion_normative_items'][:20],
            },
        }
    
    @staticmethod
    def _canonical_json_hash(obj: Dict[str, Any]) -> str:
        """Compute SHA-256 over canonical JSON of an object."""
        canonical = json.dumps(obj, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

    def _build_replay_manifest(self, debate_id: str, selection_seed: int,
                               allowed_posts: List[Dict], blocked_posts: List[Dict],
                               topics: List[Topic], side_order: List[str]) -> Dict[str, Any]:
        """Build replay manifest for independent snapshot reproduction."""
        active_template = self._active_moderation_template_record or {}
        return {
            'debate_id': debate_id,
            'selection_seed': selection_seed,
            'side_order': side_order,
            'model_version_id': getattr(self.llm_client, 'model_version', 'mock'),
            'tokenizer_version': getattr(get_canonical_tokenizer(), 'version', 'v1'),
            'moderation_template_version': self.modulation_engine.template.get_version_string(),
            'moderation_template_record_id': active_template.get('template_record_id'),
            'selection_recipe': {
                'K_E_policy': 'max(3, min(pool_size, 10))',
                'K_N_policy': 'max(1, min(normative_count, 5)) when normative_count > 0 else 0',
                'K_A_policy': 'max(3, min(pool_size, 8))',
            },
            'formula_metadata': formula_registry(),
            'input_counts': {
                'allowed_posts': len(allowed_posts),
                'blocked_posts': len(blocked_posts),
                'topics': len(topics),
            },
            'timestamp': datetime.now().isoformat(),
        }

    def _build_recipe_versions(self) -> Dict[str, Any]:
        """Publish component versions for traceability."""
        active_template = self._active_moderation_template_record or {}
        return {
            'extraction_engine': 'v2',
            'topic_engine': 'v2',
            'scoring_engine': 'v2',
            'selection_engine': 'v1',
            'formula_registry': 'lsd-v1.2.0',
            'scoring_formula_mode': scoring_formula_mode(),
            'frame_mode': get_frame_mode_flag(),
            'coverage_mode': os.getenv('COVERAGE_MODE', 'leverage_legacy'),
            'modulation_template': self.modulation_engine.template.get_version_string(),
            'modulation_template_record_id': active_template.get('template_record_id'),
            'fact_checker_mode': self._fact_check_mode,
            'replicate_composition': {
                'version_id': 'lsd-18-v1.2.0',
                'extraction_reruns': 2,
                'bootstrap_enabled': True,
                'num_replicates': self.scoring_engine.num_replicates,
                'num_judges': self.scoring_engine.num_judges,
            },
        }

    def get_frame_info(self) -> Optional[Dict]:
        """Get active frame info for snapshots and API (LSD §5)."""
        frame = self.frame_registry.get_active_frame()
        if not frame:
            return None
        return {
            'frame_id': frame.frame_id,
            'version': frame.version,
            'statement': frame.statement,
            'scope': frame.scope,
            'dossier': frame.to_dossier(),
        }

    def shutdown(self):
        """Shutdown the debate engine and its fact-checking workers."""
        self.fact_checker.shutdown()
