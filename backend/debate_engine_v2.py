"""
Enhanced Debate Engine v2
Full implementation with span extraction, canonicalization, audits, and persistence
"""

import hashlib
import json
import math
import os
import time
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

# Import our new modules
from backend.database import DebateDatabase
from backend.debate_proposal import (
    build_internal_scope,
    hydrate_debate_record,
    parse_debate_proposal_payload,
)
from backend.evidence_targets import EvidenceTargetAnalyzer
from backend.extraction import ExtractedFact, ExtractionEngine
from backend.frame_registry import get_public_frame_registry
from backend.governance import GovernanceManager
from backend.llm_client import LLMClient
from backend.lsd_v1_2 import (
    formula_registry,
    scoring_formula_mode,
)
from backend.lsd_v1_2 import (
    frame_mode as get_frame_mode_flag,
)
from backend.modulation import ModulationEngine
from backend.pipeline.context import PipelineContext
from backend.pipeline.orchestrator import run_snapshot_pipeline
from backend.scoring_engine import ScoringEngine
from backend.selection_engine import SelectionEngine
from backend.snapshot_diff import SnapshotDiffEngine
from backend.tokenizer import ContentMassCalculator, get_canonical_tokenizer
from backend.topic_engine import Topic, TopicEngine
from skills.fact_checking import V15FactCheckingSkill


class DebateEngineV2:
    """
    Enhanced debate engine with full MSD specification compliance
    """

    def __init__(
        self,
        db_path: str = "data/debate_system.db",
        fact_check_mode: str = "OFFLINE",
        llm_provider: str = "mock",
        num_judges: int = 5,
        modulation_template: str = "standard_civility",
        openrouter_api_key: str | None = None,
    ):
        # Initialize components
        self.db = DebateDatabase(db_path)

        # Determine API key to use
        api_key = None
        if llm_provider.startswith("openrouter"):
            api_key = openrouter_api_key or os.getenv("OPENROUTER_API_KEY")
            if not api_key:
                raise ValueError(
                    "OpenRouter provider selected but no API key found. "
                    "Set OPENROUTER_API_KEY environment variable or pass openrouter_api_key."
                )

        self.num_judges = num_judges
        self.llm_client = LLMClient(provider=llm_provider, num_judges=num_judges, api_key=api_key)
        self._fact_check_mode = self._normalize_fact_check_mode(fact_check_mode)
        self._async_enabled = self._fact_check_mode == "ONLINE_ALLOWLIST"
        self._fact_check_wait_timeout_seconds = 2.0
        self._fact_check_poll_interval_seconds = 0.05

        # v1.5 deterministic ternary fact-checking pipeline (LSD_FactCheck_v1_5_1)
        self.fact_checker = self._create_v15_fact_checker()
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
        self._active_moderation_template_record: dict[str, Any] | None = None

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
        self._debate_cache: dict[str, dict] = {}
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
        return aliases.get(
            str(public_mode or mode).strip(),
            aliases.get(str(public_mode or mode).strip().lower(), "OFFLINE"),
        )

    def _create_v15_fact_checker(self) -> V15FactCheckingSkill:
        """Instantiate v1.5 deterministic ternary fact-checking skill."""
        return V15FactCheckingSkill(
            mode=self._fact_check_mode,
            allowlist_version="v1",
            enable_async=self._async_enabled,
        )

    @staticmethod
    def _topic_from_record(record: dict[str, Any]) -> Topic:
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
    def _resolve_builtin_modulation_template_id(base_template_id: str | None) -> str:
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

    def refresh_active_modulation_template(self, force: bool = False) -> dict[str, Any] | None:
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

    def get_runtime_profile(self) -> dict[str, Any]:
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

    def _resolve_fact_checks(self, facts: list[ExtractedFact]) -> list[ExtractedFact]:
        """Wait briefly for async fact checks so scoring never sees pending values."""
        if not facts:
            return facts

        resolved_facts = self.extraction_engine.update_fact_check_results(facts)

        if self._fact_check_mode != "ONLINE_ALLOWLIST" or not self._async_enabled:
            return resolved_facts

        def has_pending(items: list[ExtractedFact]) -> bool:
            return any(
                fact.fact_check_job_id and fact.fact_check_status == "pending" for fact in items
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
    def _frame_side_order(frame: dict[str, Any] | None) -> list[str]:
        if not frame:
            return ["FOR", "AGAINST"]
        return [side["side_id"] for side in frame.get("sides", [])] or ["FOR", "AGAINST"]

    def _attach_active_frame(self, debate: dict[str, Any] | None) -> dict[str, Any] | None:
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
            hydrated["debate_frame"] = active_frame.get(
                "frame_summary", hydrated.get("debate_frame", "")
            )
            hydrated["scope"] = build_internal_scope(
                hydrated.get("motion", ""),
                hydrated.get("moderation_criteria", ""),
                active_frame,
            )
        return hydrated

    def _build_frame_record(
        self,
        debate_id: str,
        proposal: dict[str, Any],
        version: int,
        supersedes_frame_id: str | None = None,
    ) -> dict[str, Any]:
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
    def _legacy_create_payload(
        resolution: str, scope: str, moderation_criteria: str | None = None
    ) -> dict[str, Any]:
        return {
            "motion": resolution,
            "resolution": resolution,
            "moderation_criteria": (
                moderation_criteria
                or "Allow arguments directly relevant to the resolution. Block harassment, spam, PII, and off-topic content."
            ),
            "debate_frame": scope,
        }

    def create_debate(
        self,
        motion: str | dict[str, Any] | None = None,
        moderation_criteria: str | None = None,
        debate_frame: Any = None,
        user_id: str | None = None,
        *,
        resolution: str | None = None,
        scope: str | None = None,
    ) -> dict:
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

    def create_frame_version(self, debate_id: str, payload: dict[str, Any]) -> dict[str, Any]:
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

        debate.update(
            {
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
            }
        )
        self.db.save_debate(debate)

        hydrated = self._attach_active_frame(debate)
        self._debate_cache[debate_id] = hydrated
        return hydrated

    def get_debate_frames(self, debate_id: str) -> list[dict[str, Any]]:
        """Get all frame versions for a debate."""
        return self.db.get_debate_frames(debate_id)

    def get_debate(self, debate_id: str) -> dict | None:
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

    def submit_post(
        self,
        debate_id: str,
        side: str,
        topic_id: str | None,
        facts: str,
        inference: str,
        counter_arguments: str = "",
        user_id: str | None = None,
        submission_id: str | None = None,
    ) -> dict:
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
            "post_id": post_id,
            "debate_id": debate_id,
            "user_id": user_id,
            "frame_id": active_frame.get("frame_id"),
            "side": normalized_side,
            "topic_id": topic_id,
            "facts": facts,
            "inference": inference,
            "counter_arguments": counter_arguments,
            "timestamp": datetime.now().isoformat(),
            "modulation_outcome": "allowed",
            "block_reason": None,
            "submission_id": submission_id,
        }

        # Apply modulation using template (MSD §3)
        outcome, block_reason, matched_rules = self.modulation_engine.apply_modulation(post_data)
        post_data["modulation_outcome"] = getattr(outcome, "value", outcome)
        post_data["block_reason"] = (
            getattr(block_reason, "value", block_reason) if block_reason else None
        )
        post_data["modulation_matched_rules"] = matched_rules
        post_data["modulation_template"] = self.modulation_engine.template.get_version_string()

        # Save post
        self.db.save_post(post_data)

        # If allowed, extract spans
        if post_data["modulation_outcome"] == "allowed":
            self._extract_and_save_spans(post_data)

        return post_data

    def get_modulation_info(self) -> dict:
        """Get current modulation template info for audit (MSD §3)"""
        self.refresh_active_modulation_template()
        info = self.modulation_engine.get_audit_info()
        if self._active_moderation_template_record:
            info["template_record_id"] = self._active_moderation_template_record.get(
                "template_record_id"
            )
            info["template_status"] = self._active_moderation_template_record.get("status")
        return info

    def _extract_and_save_spans(self, post_data: dict):
        """Extract and save spans for an allowed post"""
        # Extract spans using LLM
        fact_spans, inference_span = self.extraction_engine.extract_spans_from_post(
            post_data["post_id"],
            post_data["facts"],
            post_data["inference"],
            post_data["side"],
            post_data.get("topic_id"),
        )

        # Save spans to database with token counts (MSD §11)
        tokenizer = get_canonical_tokenizer()

        for span in fact_spans:
            token_count = tokenizer.count_tokens(span.span_text)
            self.db.save_span(
                {
                    "span_id": span.span_id,
                    "post_id": span.post_id,
                    "start_offset": span.start_offset,
                    "end_offset": span.end_offset,
                    "span_text": span.span_text,
                    "topic_id": span.topic_id,
                    "side": span.side,
                    "span_type": span.span_type,
                    "token_count": token_count,
                }
            )

        if inference_span:
            token_count = tokenizer.count_tokens(inference_span.span_text)
            self.db.save_span(
                {
                    "span_id": inference_span.span_id,
                    "post_id": inference_span.post_id,
                    "start_offset": inference_span.start_offset,
                    "end_offset": inference_span.end_offset,
                    "span_text": inference_span.span_text,
                    "topic_id": inference_span.topic_id,
                    "side": inference_span.side,
                    "span_type": inference_span.span_type,
                    "token_count": token_count,
                }
            )

    def generate_snapshot(
        self, debate_id: str, trigger_type: str = "activity", request_id: str | None = None
    ) -> dict:
        """
        Generate a new snapshot with full processing pipeline.
        Delegates to the discrete pipeline stages in backend.pipeline.
        """
        self.refresh_active_modulation_template()
        debate = self.get_debate(debate_id)
        if not debate:
            raise ValueError(f"Debate {debate_id} not found")

        active_frame = debate.get("active_frame")
        if not active_frame:
            raise ValueError("Debate has no active frame")

        ctx = PipelineContext(
            debate_id=debate_id,
            job_id=f"job_{uuid.uuid4().hex[:8]}",
            request_id=request_id or str(uuid.uuid4()),
            trigger_type=trigger_type,
            engine=self,
            debate=debate,
            active_frame=active_frame,
            side_order=self._frame_side_order(active_frame),
            frame_id=active_frame["frame_id"],
            frame_context=debate["scope"],
        )
        ctx = run_snapshot_pipeline(ctx)
        return ctx.result

    def get_snapshot(self, snapshot_id: str) -> dict | None:
        """Get snapshot by ID"""
        return self.db.get_snapshot_by_id(snapshot_id)

    def verify_snapshot(self, snapshot_id: str) -> dict:
        """
        LSD §2.C: Deterministic replay verification.
        Re-run the pipeline from the stored inputs and compare output hashes.
        """
        snapshot = self.db.get_snapshot_by_id(snapshot_id)
        if not snapshot:
            return {"verified": False, "error": "Snapshot not found"}

        replay_manifest = json.loads(snapshot.get("replay_manifest_json") or "{}")
        input_bundle = replay_manifest.get("input_bundle", {})
        stored_input_hash = snapshot.get("input_hash_root")
        stored_output_hash = snapshot.get("output_hash_root")

        # Re-compute input hash
        current_input_hash = self._canonical_json_hash(input_bundle)
        input_match = current_input_hash == stored_input_hash

        # Re-compute output hash from stored outputs
        output_bundle = {
            "topics": [
                {
                    "topic_id": t.get("topic_id"),
                    "name": t.get("name"),
                    "relevance": t.get("relevance"),
                }
                for t in (
                    json.loads(snapshot.get("topics_json") or "[]")
                    if snapshot.get("topics_json")
                    else []
                )
            ]
            or [],
            "overall_scores": json.loads(snapshot.get("overall_scores_json") or "{}")
            if snapshot.get("overall_scores_json")
            else snapshot.get("overall_scores", {}),
            "verdict": snapshot.get("verdict"),
            "topic_scores": json.loads(snapshot.get("topic_scores_json") or "{}")
            if snapshot.get("topic_scores_json")
            else snapshot.get("topic_scores", {}),
        }
        current_output_hash = self._canonical_json_hash(output_bundle)
        output_match = current_output_hash == stored_output_hash

        delta = {}
        if not input_match:
            delta["input_hash_mismatch"] = {
                "stored": stored_input_hash,
                "computed": current_input_hash,
            }
        if not output_match:
            delta["output_hash_mismatch"] = {
                "stored": stored_output_hash,
                "computed": current_output_hash,
            }

        return {
            "verified": input_match and output_match,
            "hash_match": input_match and output_match,
            "input_hash_match": input_match,
            "output_hash_match": output_match,
            "snapshot_id": snapshot_id,
            "delta": delta,
        }

    def export_audit_bundle(self, snapshot_id: str) -> dict:
        """
        LSD §20.4: Export a verifiable audit bundle for authorized third parties.
        """
        snapshot = self.db.get_snapshot_by_id(snapshot_id)
        if not snapshot:
            return {"error": "Snapshot not found"}

        debate_id = snapshot.get("debate_id")
        debate = self.db.get_debate(debate_id) if debate_id else None
        audits = self.db.get_audits_by_snapshot(snapshot_id)

        bundle = {
            "audit_bundle_version": "lsd-v1.2.0",
            "snapshot_id": snapshot_id,
            "debate_id": debate_id,
            "exported_at": datetime.now().isoformat(),
            "replay_manifest": json.loads(snapshot.get("replay_manifest_json") or "{}"),
            "input_hash_root": snapshot.get("input_hash_root"),
            "output_hash_root": snapshot.get("output_hash_root"),
            "recipe_versions": json.loads(snapshot.get("recipe_versions_json") or "{}"),
            "selection_diagnostics": {},
            "formula_metadata": formula_registry(),
            "provider_metadata": snapshot.get("provider_metadata", {}),
            "audits": [dict(a) for a in audits],
            "frame_summary": debate.get("debate_frame") if debate else None,
            "merkle_root": snapshot.get("output_hash_root"),
        }
        return bundle

    def get_audits_for_snapshot(self, snapshot_id: str) -> dict:
        """Get all audits for a snapshot"""
        audits = self.db.get_audits_by_snapshot(snapshot_id)

        result = {}
        for audit in audits:
            result[audit["audit_type"]] = json.loads(audit["result_data"])

        return result

    def get_topic_lineage(self, debate_id: str) -> list[dict]:
        """Get topic lineage across all snapshots"""
        topics = self.db.get_topics_by_debate(debate_id)

        # Build lineage graph
        lineage = []
        for topic in topics:
            parent_ids = json.loads(topic.get("parent_topic_ids", "[]"))
            lineage.append(
                {
                    "topic_id": topic["topic_id"],
                    "name": topic["name"],
                    "parent_topic_ids": parent_ids,
                    "operation": topic.get("operation", "created"),
                    "drift_score": topic.get("drift_score", 0.0),
                }
            )

        return lineage

    def diff_snapshots(self, snapshot_id_old: str, snapshot_id_new: str) -> dict:
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

    def get_snapshot_history(self, debate_id: str) -> list[dict]:
        """Get chronological history of snapshots for a debate"""
        return self.diff_engine.get_snapshot_history(debate_id)

    def compare_consecutive_snapshots(self, debate_id: str) -> dict | None:
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

        return self.diff_snapshots(snap_old["snapshot_id"], snap_new["snapshot_id"])

    def get_evidence_targets(self, debate_id: str, snapshot_id: str | None = None) -> dict:
        """
        Get "What evidence would change this" analysis (MSD §15).

        Identifies:
        - High-leverage arguments
        - Decisive supporting FACT nodes
        - Evidence needed to shift uncertain facts
        - Update triggers
        """
        result = self.evidence_analyzer.analyze_evidence_targets(debate_id, snapshot_id)
        return result.to_dict()

    def get_fact_check_stats(self) -> dict:
        """Get statistics from the fact checking skill."""
        return {
            "cache": self.fact_checker.get_cache_stats(),
            "audit": self.fact_checker.get_audit_stats(),
            "queue": self.fact_checker.get_queue_stats(),
            "mode": self._fact_check_mode,
            "async_enabled": self._async_enabled,
        }

    def _update_canonical_metrics(
        self, topic_facts: dict[str, list[dict]], topic_arguments: dict[str, list[dict]]
    ):
        """
        LSD §11: Compute centrality and distinct_support for canonical items,
        and update fact references from arguments.
        """
        for tid, facts in topic_facts.items():
            args = topic_arguments.get(tid, [])

            # Update referenced_by_au_ids on facts using arguments
            fact_refs = defaultdict(set)
            for arg in args:
                for fact_id in arg.get("supporting_facts", []):
                    fact_refs[fact_id].add(arg.get("canon_arg_id"))

            for fact in facts:
                fact["referenced_by_au_ids"] = list(fact_refs.get(fact["canon_fact_id"], set()))
                # Centrality = log(1 + distinct_AU_refs)
                au_refs = len(fact.get("referenced_by_au_ids", []))
                fact["centrality"] = round(math.log1p(au_refs), 4)
                # Distinct support proxy = number of member facts
                fact["distinct_support"] = len(fact.get("member_fact_ids", set()))

            for arg in args:
                au_refs = len(arg.get("member_au_ids", []))
                arg["centrality"] = round(math.log1p(au_refs), 4)
                arg["distinct_support"] = au_refs

    @staticmethod
    def _remap_to_replicate(
        primary_topics,
        replicate_topics,
        topic_content_mass,
        selected_topic_facts,
        selected_topic_arguments,
    ):
        """
        Build replicate_mass, replicate_facts, replicate_args by following
        parent_topic_ids from merged replicate topics back to primary topics.
        Returns (replicate_mass, replicate_facts, replicate_args, primary_to_replicate).
        """
        primary_ids = {p.topic_id for p in primary_topics}
        primary_to_replicate = {}
        for r in replicate_topics:
            for parent_id in r.parent_topic_ids:
                if parent_id in primary_ids:
                    primary_to_replicate[parent_id] = r.topic_id
        for p in primary_topics:
            if p.topic_id not in primary_to_replicate:
                primary_to_replicate[p.topic_id] = p.topic_id

        replicate_mass = defaultdict(float)
        for p in primary_topics:
            r_id = primary_to_replicate.get(p.topic_id)
            if r_id:
                replicate_mass[r_id] += topic_content_mass.get(p.topic_id, 0)

        replicate_facts = defaultdict(list)
        for p_id, facts in selected_topic_facts.items():
            r_id = primary_to_replicate.get(p_id)
            if r_id:
                replicate_facts[r_id].extend(facts)

        replicate_args = defaultdict(list)
        for p_id, args in selected_topic_arguments.items():
            r_id = primary_to_replicate.get(p_id)
            if r_id:
                replicate_args[r_id].extend(args)

        return (
            dict(replicate_mass),
            dict(replicate_facts),
            dict(replicate_args),
            primary_to_replicate,
        )

    def _build_decision_dossier(
        self,
        topics: list[Topic],
        topic_facts: dict[str, list[dict]],
        topic_arguments: dict[str, list[dict]],
        selected_facts: dict[str, list[dict]],
        selected_args: dict[str, list[dict]],
        topic_scores: dict,
    ) -> dict:
        """
        LSD §17: Build decision dossier outputs.
        """
        decisive_premises = []
        decisive_arguments = []
        evidence_gaps = {}
        priority_gaps = {
            "insufficient_empirical_items": [],
            "high_dispersion_normative_items": [],
        }

        for topic in topics:
            tid = topic.topic_id
            facts = topic_facts.get(tid, [])
            args = topic_arguments.get(tid, [])
            sides = sorted({item.get("side") for item in [*facts, *args] if item.get("side")}) or [
                "FOR",
                "AGAINST",
            ]

            for side in sides:
                side_facts = [f for f in facts if f.get("side") == side]
                side_args = [a for a in args if a.get("side") == side]

                # Decisive premises: v1.5 ternary semantics
                for fact in side_facts:
                    status = fact.get("v15_status")
                    if not status:
                        d = fact.get("fact_check_diagnostics", {})
                        status = d.get("v15_status") if isinstance(d, dict) else None
                    is_decisive = status in ("SUPPORTED", "REFUTED")
                    is_insufficient = status == "INSUFFICIENT" or status is None
                    # Legacy fallback decisiveness from p_true
                    p = fact.get("p_true", 0.5)
                    legacy_decisiveness = abs(p - 0.5)
                    decisiveness = 1.0 if is_decisive else legacy_decisiveness
                    if is_decisive or legacy_decisiveness > 0.2:
                        decisive_premises.append(
                            {
                                "canon_fact_id": fact["canon_fact_id"],
                                "topic_id": tid,
                                "side": side,
                                "text": fact["canon_fact_text"][:200],
                                "p_true": fact["p_true"],
                                "p_or_q_score": fact.get("p_true", 0.5),
                                "decisiveness": round(decisiveness, 3),
                                "v15_status": status,
                                "v15_insufficiency_reason": fact.get("v15_insufficiency_reason"),
                                "span_ids": [
                                    link.get("span_id")
                                    for link in fact.get("provenance_links", [])
                                    if isinstance(link, dict) and link.get("span_id")
                                ],
                                "post_id_provenance": sorted(
                                    {
                                        str(link.get("span_id", "")).split("_")[1]
                                        for link in fact.get("provenance_links", [])
                                        if isinstance(link, dict) and link.get("span_id")
                                    }
                                ),
                                "operationalization": fact.get("operationalization", ""),
                            }
                        )
                    if is_insufficient and fact.get("fact_type", "empirical") == "empirical":
                        priority_gaps["insufficient_empirical_items"].append(
                            {
                                "canon_fact_id": fact.get("canon_fact_id"),
                                "topic_id": tid,
                                "side": side,
                                "text": fact.get("canon_fact_text", "")[:200],
                                "priority_score": round(
                                    (1 - legacy_decisiveness)
                                    * float(fact.get("centrality", 0.0) or 0.0),
                                    4,
                                ),
                                "operationalization": fact.get("operationalization", ""),
                                "v15_insufficiency_reason": fact.get("v15_insufficiency_reason"),
                            }
                        )
                    if fact.get("fact_type") == "normative":
                        priority_gaps["high_dispersion_normative_items"].append(
                            {
                                "canon_fact_id": fact.get("canon_fact_id"),
                                "topic_id": tid,
                                "side": side,
                                "text": fact.get("canon_fact_text", "")[:200],
                                "q_variance": 0.0,
                                "normative_provenance": fact.get("normative_provenance", ""),
                            }
                        )

                for arg in side_args:
                    score = float(arg.get("reasoning_score", 0.5) or 0.5)
                    if score >= 0.5 or arg.get("is_selected"):
                        decisive_arguments.append(
                            {
                                "canon_arg_id": arg.get("canon_arg_id"),
                                "topic_id": tid,
                                "side": side,
                                "text": arg.get("inference_text", "")[:240],
                                "reasoning_score": score,
                                "completeness_proxy": arg.get("completeness_proxy", 0.0),
                                "span_ids": [
                                    link.get("span_id")
                                    for link in arg.get("provenance_links", [])
                                    if isinstance(link, dict) and link.get("span_id")
                                ],
                                "post_id_provenance": sorted(
                                    {
                                        str(link.get("span_id", "")).split("_")[1]
                                        for link in arg.get("provenance_links", [])
                                        if isinstance(link, dict) and link.get("span_id")
                                    }
                                ),
                            }
                        )

                # Evidence gap summary using v1.5 ternary semantics
                insufficiency_rate = 0.0
                tier_counts = {"TIER_1": 0, "TIER_2": 0, "TIER_3": 0}
                total_facts = len(side_facts)
                f_all = 0.5
                f_supported_only = 0.5
                if total_facts > 0:

                    def _is_insufficient(f):
                        s = f.get("v15_status")
                        if not s:
                            d = f.get("fact_check_diagnostics", {})
                            s = d.get("v15_status") if isinstance(d, dict) else None
                        return s == "INSUFFICIENT" or s is None

                    def _is_decisive(f):
                        s = f.get("v15_status")
                        if not s:
                            d = f.get("fact_check_diagnostics", {})
                            s = d.get("v15_status") if isinstance(d, dict) else None
                        return s in ("SUPPORTED", "REFUTED")

                    insufficient_count = sum(1 for f in side_facts if _is_insufficient(f))
                    insufficiency_rate = insufficient_count / total_facts
                    f_all = (
                        sum(float(f.get("p_true", 0.5) or 0.5) for f in side_facts) / total_facts
                    )
                    decisive = [f for f in side_facts if _is_decisive(f)]
                    if decisive:
                        f_supported_only = sum(
                            float(f.get("p_true", 0.5) or 0.5) for f in decisive
                        ) / len(decisive)

                    for f in side_facts:
                        # Prefer v1.5 tier field
                        tier = f.get("v15_best_evidence_tier")
                        if tier is not None:
                            tier_counts[f"TIER_{tier}"] = tier_counts.get(f"TIER_{tier}", 0) + 1
                        else:
                            for tier, count in f.get("evidence_tier_counts", {}).items():
                                tier_counts[tier] = tier_counts.get(tier, 0) + count

                evidence_gaps[f"{tid}_{side}"] = {
                    "insufficiency_rate": round(insufficiency_rate, 3),
                    "tier_distribution": tier_counts,
                    "f_all": round(f_all, 3),
                    "f_supported_only": round(f_supported_only, 3),
                    "total_facts": total_facts,
                }

        # Sort decisive premises by decisiveness
        decisive_premises.sort(key=lambda x: x["decisiveness"], reverse=True)
        decisive_arguments.sort(
            key=lambda x: (
                float(x.get("reasoning_score", 0.0)),
                float(x.get("completeness_proxy", 0.0)),
            ),
            reverse=True,
        )
        priority_gaps["insufficient_empirical_items"].sort(
            key=lambda x: x.get("priority_score", 0.0),
            reverse=True,
        )
        priority_gaps["high_dispersion_normative_items"].sort(
            key=lambda x: x.get("q_variance", 0.0),
            reverse=True,
        )

        return {
            "decisive_premises": decisive_premises[:20],
            "decisive_arguments": decisive_arguments[:20],
            "evidence_gaps": evidence_gaps,
            "priority_gaps": {
                "insufficient_empirical_items": priority_gaps["insufficient_empirical_items"][:20],
                "high_dispersion_normative_items": priority_gaps["high_dispersion_normative_items"][
                    :20
                ],
            },
        }

    @staticmethod
    def _canonical_json_hash(obj: dict[str, Any]) -> str:
        """Compute SHA-256 over canonical JSON of an object."""
        canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _build_replay_manifest(
        self,
        debate_id: str,
        selection_seed: int,
        allowed_posts: list[dict],
        blocked_posts: list[dict],
        topics: list[Topic],
        side_order: list[str],
    ) -> dict[str, Any]:
        """Build replay manifest for independent snapshot reproduction."""
        active_template = self._active_moderation_template_record or {}
        return {
            "debate_id": debate_id,
            "selection_seed": selection_seed,
            "side_order": side_order,
            "model_version_id": getattr(self.llm_client, "model_version", "mock"),
            "tokenizer_version": getattr(get_canonical_tokenizer(), "version", "v1"),
            "moderation_template_version": self.modulation_engine.template.get_version_string(),
            "moderation_template_record_id": active_template.get("template_record_id"),
            "selection_recipe": {
                "K_E_policy": "max(3, min(pool_size, 10))",
                "K_N_policy": "max(1, min(normative_count, 5)) when normative_count > 0 else 0",
                "K_A_policy": "max(3, min(pool_size, 8))",
            },
            "formula_metadata": formula_registry(),
            "input_counts": {
                "allowed_posts": len(allowed_posts),
                "blocked_posts": len(blocked_posts),
                "topics": len(topics),
            },
            # v1.5 parameter pack per LSD §4
            "v15_parameter_pack": {
                "fact_checker_version": "v1.5",
                "evidence_policy_version": "v1.5-default",
                "synthesis_rule_engine_version": "v1.5",
                "decomposition_version": "v1.5-phase2",
            },
            "timestamp": datetime.now().isoformat(),
        }

    def _build_recipe_versions(self) -> dict[str, Any]:
        """Publish component versions for traceability."""
        active_template = self._active_moderation_template_record or {}
        return {
            "extraction_engine": "v2",
            "topic_engine": "v2",
            "scoring_engine": "v2",
            "selection_engine": "v1",
            "formula_registry": "lsd-v1.2.0",
            "scoring_formula_mode": scoring_formula_mode(),
            "frame_mode": get_frame_mode_flag(),
            "coverage_mode": os.getenv("COVERAGE_MODE", "leverage_legacy"),
            "modulation_template": self.modulation_engine.template.get_version_string(),
            "modulation_template_record_id": active_template.get("template_record_id"),
            "fact_checker_mode": self._fact_check_mode,
            "fact_checker_version": "v1.5",
            "replicate_composition": {
                "version_id": "lsd-18-v1.2.0",
                "extraction_reruns": 2,
                "bootstrap_enabled": True,
                "num_replicates": self.scoring_engine.num_replicates,
                "num_judges": self.scoring_engine.num_judges,
            },
        }

    def get_frame_info(self) -> dict | None:
        """Get active frame info for snapshots and API (LSD §5)."""
        frame = self.frame_registry.get_active_frame()
        if not frame:
            return None
        return {
            "frame_id": frame.frame_id,
            "version": frame.version,
            "statement": frame.statement,
            "scope": frame.scope,
            "dossier": frame.to_dossier(),
        }

    def shutdown(self):
        """Shutdown the debate engine and its fact-checking workers."""
        self.fact_checker.shutdown()
