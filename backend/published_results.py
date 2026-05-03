"""
Published Results Builder

Queries the SQLite database and assembles a consolidated JSON bundle
that matches the shapes returned by the v3 API endpoints.

This bundle is what gets published to GitHub as consolidated_results.json.
"""
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from database import DebateDatabase
from lsd_v1_2 import AUDIT_SCHEMA_VERSION, formula_registry


def _coerce_json(raw: Any, fallback: Any = None) -> Any:
    """Parse a JSON string or return the fallback."""
    if raw is None:
        return fallback
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return fallback


class PublishedResultsBuilder:
    """
    Build a consolidated results bundle from the database for a given debate.
    """

    def __init__(self, db_path: str = "data/debate_system.db", engine: Optional[Any] = None):
        self.db = DebateDatabase(db_path)
        self.engine = engine

    def build_bundle(
        self,
        debate_id: str,
        commit_message: Optional[str] = None,
        published_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Build the full consolidated results bundle.

        Args:
            debate_id: The debate to export.
            commit_message: Optional commit message to embed in metadata.
            published_at: ISO timestamp; defaults to now.

        Returns:
            Dict matching the consolidated JSON schema.
        """
        debate = self.db.get_debate(debate_id)
        if not debate:
            raise ValueError(f"Debate not found: {debate_id}")

        snapshot = self.db.get_latest_snapshot(debate_id)
        frame = self.db.get_active_debate_frame(debate_id)
        topics = self.db.get_topics_by_debate(debate_id)
        posts = self.db.get_posts_by_debate(debate_id)

        # Build sections
        snapshot_data = self._build_snapshot(snapshot)
        topics_data = self._build_topics(topics, snapshot)
        topic_details = self._build_topic_details(debate_id, topics)
        verdict_data = self._build_verdict(snapshot, topics)
        audits_data = self._build_audits(debate_id, snapshot)
        decision_dossier = self._build_decision_dossier(snapshot)
        history_data = self._build_snapshot_history(debate_id)
        diff_data = self._build_snapshot_diff(debate_id)
        evidence_data = self._build_evidence_targets(debate_id, snapshot)
        modulation_data = self._build_modulation(snapshot)

        bundle = {
            "published_at": published_at or datetime.utcnow().isoformat() + "Z",
            "commit_message": commit_message or f"Published results for {debate_id}",
            "debate": {
                "debate_id": debate["debate_id"],
                "resolution": debate.get("resolution", ""),
                "scope": debate.get("scope", ""),
                "motion": debate.get("motion", ""),
                "created_at": debate.get("created_at", ""),
                "current_snapshot_id": debate.get("current_snapshot_id"),
                "active_frame_id": debate.get("active_frame_id"),
            },
            "frame": self._build_frame(frame),
            "snapshot": snapshot_data,
            "topics": topics_data,
            "topic_details": topic_details,
            "verdict": verdict_data,
            "audits": audits_data,
            "decision_dossier": decision_dossier,
            "evidence_targets": evidence_data,
            "snapshot_history": history_data,
            "snapshot_diff": diff_data,
            "modulation": modulation_data,
            "frame_petitions": self.db.get_frame_petitions(debate_id=debate_id),
            "posts": [
                {
                    "post_id": p["post_id"],
                    "side": p["side"],
                    "topic_id": p.get("topic_id"),
                    "modulation_outcome": p.get("modulation_outcome", ""),
                    "block_reason": p.get("block_reason"),
                    "timestamp": p["timestamp"],
                }
                for p in posts
            ],
        }
        return bundle

    def write_bundle(
        self,
        debate_id: str,
        output_path: str,
        commit_message: Optional[str] = None,
        published_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build and write the bundle to a local file."""
        bundle = self.build_bundle(debate_id, commit_message, published_at)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(bundle, f, indent=2, sort_keys=True)
        return bundle

    # ------------------------------------------------------------------
    # Internal builders
    # ------------------------------------------------------------------

    def _build_snapshot(self, snapshot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not snapshot:
            return {
                "snapshot_id": None,
                "timestamp": None,
                "trigger_type": None,
                "template_name": None,
                "template_version": None,
                "allowed_count": 0,
                "blocked_count": 0,
                "block_reasons": {},
                "side_order": [],
                "overall_scores": {},
                "overall_for": None,
                "overall_against": None,
                "margin_d": None,
                "ci_d": None,
                "confidence": None,
                "verdict": "NO VERDICT",
                "topic_scores": {},
                "borderline_rate": 0.0,
                "suppression_policy": {"k": 5, "affected_buckets": [], "affected_bucket_count": 0},
                "status": "valid",
            }
        return {
            "snapshot_id": snapshot["snapshot_id"],
            "timestamp": snapshot["timestamp"],
            "trigger_type": snapshot.get("trigger_type", ""),
            "template_name": snapshot.get("template_name", ""),
            "template_version": snapshot.get("template_version", ""),
            "allowed_count": snapshot.get("allowed_count", 0),
            "blocked_count": snapshot.get("blocked_count", 0),
            "block_reasons": _coerce_json(snapshot.get("block_reasons"), {}),
            "side_order": _coerce_json(snapshot.get("side_order"), []),
            "overall_scores": _coerce_json(snapshot.get("overall_scores"), {}),
            "overall_for": snapshot.get("overall_for"),
            "overall_against": snapshot.get("overall_against"),
            "margin_d": snapshot.get("margin_d"),
            "ci_d": [
                snapshot.get("ci_d_lower", -0.1),
                snapshot.get("ci_d_upper", 0.1),
            ],
            "confidence": snapshot.get("confidence"),
            "verdict": snapshot.get("verdict", "NO VERDICT"),
            "topic_scores": _coerce_json(snapshot.get("topic_scores"), {}),
            "borderline_rate": snapshot.get("borderline_rate", 0.0) or 0.0,
            "suppression_policy": _coerce_json(snapshot.get("suppression_policy_json"), {}),
            "status": snapshot.get("status", "valid"),
        }

    def _build_frame(self, frame: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not frame:
            return None
        return {
            "frame_id": frame.get("frame_id"),
            "version": frame.get("version"),
            "stage": frame.get("stage"),
            "label": frame.get("label", ""),
            "motion": frame.get("motion", ""),
            "frame_summary": frame.get("frame_summary", ""),
            "sides": _coerce_json(frame.get("sides"), []),
            "evaluation_criteria": _coerce_json(frame.get("evaluation_criteria"), []),
            "definitions": _coerce_json(frame.get("definitions"), {}),
            "scope_constraints": _coerce_json(frame.get("scope_constraints"), []),
            "notes": frame.get("notes", ""),
            "frame_mode": frame.get("frame_mode", "single"),
            "review_date": frame.get("review_date"),
            "review_cadence_months": frame.get("review_cadence_months", 6),
            "emergency_override_reason": frame.get("emergency_override_reason"),
            "emergency_override_by": frame.get("emergency_override_by"),
            "governance_decision_id": frame.get("governance_decision_id"),
            "created_at": frame.get("created_at", ""),
            "is_active": bool(frame.get("is_active", 1)),
        }

    def _build_topics(
        self, topics: List[Dict[str, Any]], snapshot: Optional[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        topic_scores = _coerce_json(snapshot.get("topic_scores") if snapshot else None, {})
        result = []
        for t in topics:
            tid = t["topic_id"]
            result.append({
                "topic_id": tid,
                "name": t.get("name", ""),
                "scope": t.get("scope", ""),
                "relevance": t.get("relevance", 0.0),
                "drift_score": t.get("drift_score", 0.0),
                "coherence": t.get("coherence", 0.0),
                "distinctness": t.get("distinctness", 0.0),
                "summary_for": t.get("summary_for", ""),
                "summary_against": t.get("summary_against", ""),
                "operation": t.get("operation", "created"),
                "parent_topic_ids": _coerce_json(t.get("parent_topic_ids"), []),
                "scores": {
                    "FOR": topic_scores.get(f"{tid}_FOR", {}),
                    "AGAINST": topic_scores.get(f"{tid}_AGAINST", {}),
                },
            })
        return result

    def _build_topic_details(
        self, debate_id: str, topics: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        details = {}
        for t in topics:
            tid = t["topic_id"]
            facts = self.db.get_canonical_facts_by_topic(tid)
            arguments = self.db.get_canonical_arguments_by_topic(tid)
            details[tid] = {
                "topic_id": tid,
                "name": t.get("name", ""),
                "scope": t.get("scope", ""),
                "relevance": t.get("relevance", 0.0),
                "drift_score": t.get("drift_score", 0.0),
                "coherence": t.get("coherence", 0.0),
                "distinctness": t.get("distinctness", 0.0),
                "summary_for": t.get("summary_for", ""),
                "summary_against": t.get("summary_against", ""),
                "operation": t.get("operation", "created"),
                "parent_topic_ids": _coerce_json(t.get("parent_topic_ids"), []),
                "facts": [
                    {
                        "canon_fact_id": f["canon_fact_id"],
                        "canon_fact_text": f.get("canon_fact_text", ""),
                        "side": f.get("side", ""),
                        "p_true": f.get("p_true", 0.5),
                        "fact_type": f.get("fact_type", "empirical"),
                        "operationalization": f.get("operationalization", ""),
                        "normative_provenance": f.get("normative_provenance", ""),
                        "evidence_tier_counts": _coerce_json(f.get("evidence_tier_counts_json"), {}),
                        "member_count": len(_coerce_json(f.get("member_fact_ids"), [])),
                    }
                    for f in facts
                ],
                "arguments": [
                    {
                        "canon_arg_id": a["canon_arg_id"],
                        "side": a.get("side", ""),
                        "inference_text": a.get("inference_text", ""),
                        "supporting_facts": _coerce_json(a.get("supporting_facts"), []),
                        "member_count": len(_coerce_json(a.get("member_au_ids"), [])),
                        "reasoning_score": a.get("reasoning_score", 0.5),
                        "completeness_proxy": a.get("completeness_proxy", 0.0),
                    }
                    for a in arguments
                ],
            }
        return details

    def _build_verdict(
        self, snapshot: Optional[Dict[str, Any]], topics: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        if not snapshot:
            return {
                "snapshot_id": None,
                "overall_for": None,
                "overall_against": None,
                "margin_d": None,
                "ci_d": None,
                "confidence": None,
                "verdict": "NO VERDICT",
                "topic_contributions": [],
            }

        topic_scores = _coerce_json(snapshot.get("topic_scores"), {})
        contributions = []
        for t in topics:
            tid = t["topic_id"]
            q_for = topic_scores.get(f"{tid}_FOR", {}).get("quality", topic_scores.get(f"{tid}_FOR", {}).get("q", 0.0))
            q_against = topic_scores.get(f"{tid}_AGAINST", {}).get("quality", topic_scores.get(f"{tid}_AGAINST", {}).get("q", 0.0))
            contrib = (q_for - q_against) * t.get("relevance", 0.0)
            contributions.append({
                "topic_id": tid,
                "name": t.get("name", ""),
                "relevance": t.get("relevance", 0.0),
                "q_for": q_for,
                "q_against": q_against,
                "contribution_to_d": round(contrib, 4),
            })

        return {
            "snapshot_id": snapshot["snapshot_id"],
            "overall_for": snapshot.get("overall_for"),
            "overall_against": snapshot.get("overall_against"),
            "margin_d": snapshot.get("margin_d"),
            "ci_d": [
                snapshot.get("ci_d_lower", -0.1),
                snapshot.get("ci_d_upper", 0.1),
            ],
            "confidence": snapshot.get("confidence"),
            "verdict": snapshot.get("verdict", "NO VERDICT"),
            "topic_contributions": contributions,
            "d_distribution": _coerce_json(snapshot.get("d_distribution"), []),
            "replicate_composition_metadata": {},
            "formula_metadata": formula_registry(),
        }

    def _build_audits(
        self, debate_id: str, snapshot: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        if not snapshot:
            return {
                "snapshot_id": None,
                "timestamp": None,
                "verdict": "NO VERDICT",
                "confidence": 0.0,
                "topic_geometry": [],
                "extraction_stability": {
                    "fact_overlap": {},
                    "argument_overlap": {},
                    "mismatches": [],
                    "num_runs": 0,
                    "stability_score": 0,
                },
                "evaluator_disagreement": {
                    "reasoning_iqr_median": 0.0,
                    "coverage_iqr_median": 0.0,
                    "overall_iqr": 0.0,
                },
                "label_symmetry": {
                    "median_delta_d": 0,
                    "abs_delta_d": 0,
                    "original_d": 0,
                    "swapped_d": 0,
                    "topic_deltas": {},
                    "interpretation": "",
                },
                "relevance_sensitivity": {},
                "audit_schema_version": AUDIT_SCHEMA_VERSION,
            }

        audit_rows = self.db.get_audits_by_snapshot(snapshot["snapshot_id"])
        audits_dict: Dict[str, Any] = {}
        for row in audit_rows:
            atype = row.get("audit_type", "unknown")
            audits_dict[atype] = _coerce_json(row.get("result_data"), {})

        topics = self.db.get_topics_by_debate(debate_id)
        topic_geometry = []
        for t in topics:
            topic_geometry.append({
                "topic_id": t["topic_id"],
                "name": t.get("name", ""),
                "content_mass": t.get("relevance", 0.0),
                "drift_score": t.get("drift_score", 0.0),
                "coherence": t.get("coherence", 0.0),
                "distinctness": t.get("distinctness", 0.0),
                "operation": t.get("operation", "created"),
                "parent_topic_ids": _coerce_json(t.get("parent_topic_ids"), []),
            })

        return {
            "snapshot_id": snapshot["snapshot_id"],
            "audit_schema_version": AUDIT_SCHEMA_VERSION,
            "timestamp": snapshot["timestamp"],
            "verdict": snapshot.get("verdict", "NO VERDICT"),
            "confidence": snapshot.get("confidence", 0.0),
            "topic_geometry": topic_geometry,
            "extraction_stability": audits_dict.get("extraction_stability", {
                "fact_overlap": {},
                "argument_overlap": {},
                "mismatches": [],
                "num_runs": 0,
                "stability_score": 0,
            }),
            "evaluator_disagreement": audits_dict.get("evaluator_variance", audits_dict.get("evaluator_disagreement", {
                "reasoning_iqr_median": 0.0,
                "coverage_iqr_median": 0.0,
                "overall_iqr": 0.0,
            })),
            "label_symmetry": audits_dict.get("side_label_symmetry", audits_dict.get("label_symmetry", {
                "median_delta_d": 0,
                "abs_delta_d": 0,
                "original_d": 0,
                "swapped_d": 0,
                "topic_deltas": {},
                "interpretation": "",
            })),
            "relevance_sensitivity": audits_dict.get("relevance_sensitivity", {}),
            "topic_dominance": audits_dict.get("topic_diagnostics", {}).get("dominance", {}),
            "topic_concentration": {
                "micro_topic_rate": audits_dict.get("topic_diagnostics", {}).get("micro_topic_rate", 0.0),
                "mass_distribution_quantiles": audits_dict.get("topic_diagnostics", {}).get("mass_distribution_quantiles", {}),
                "gini_coefficient": audits_dict.get("topic_diagnostics", {}).get("gini_coefficient", 0.0),
            },
            "frame_sensitivity": audits_dict.get("frame_sensitivity", {}),
            "integrity_indicators": audits_dict.get("integrity_indicators", {}),
            "participation_concentration": audits_dict.get("participation_concentration", {}),
            "budget_adequacy": audits_dict.get("budget_adequacy", {}),
            "centrality_cap_effect": audits_dict.get("centrality_cap_effect", {}),
            "rarity_utilization": audits_dict.get("rarity_utilization", {}),
            "merge_sensitivity": audits_dict.get("topic_merge_sensitivity", {}),
            "coverage_adequacy_trace": audits_dict.get("coverage_adequacy_trace", {}),
            "selection_transparency": audits_dict.get("selection_transparency", {}),
            "formula_registry": audits_dict.get("formula_registry", formula_registry()),
        }

    def _build_decision_dossier(self, snapshot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not snapshot:
            return {}
        audit_rows = self.db.get_audits_by_snapshot(snapshot["snapshot_id"])
        for row in audit_rows:
            if row.get("audit_type") == "decision_dossier":
                dossier = _coerce_json(row.get("result_data"), {})
                return {
                    "snapshot_id": snapshot["snapshot_id"],
                    "verdict": snapshot.get("verdict", "NO VERDICT"),
                    "confidence": snapshot.get("confidence", 0.0),
                    **dossier,
                }
        return {
            "snapshot_id": snapshot["snapshot_id"],
            "verdict": snapshot.get("verdict", "NO VERDICT"),
            "confidence": snapshot.get("confidence", 0.0),
            "evidence_gaps": {},
            "selection_diagnostics": {},
        }

    def _build_snapshot_history(self, debate_id: str) -> Dict[str, Any]:
        snapshots = self.db.get_snapshots_by_debate(debate_id)
        return {
            "debate_id": debate_id,
            "snapshot_count": len(snapshots),
            "snapshots": [
                {
                    "snapshot_id": s["snapshot_id"],
                    "timestamp": s["timestamp"],
                    "trigger_type": s.get("trigger_type", ""),
                    "verdict": s.get("verdict", "NO VERDICT"),
                    "confidence": s.get("confidence", 0.0),
                }
                for s in snapshots
            ],
        }

    def _build_snapshot_diff(self, debate_id: str) -> Optional[Dict[str, Any]]:
        snapshots = self.db.get_snapshots_by_debate(debate_id)
        if len(snapshots) < 2:
            return None

        latest = snapshots[0]["snapshot_id"]
        previous = snapshots[1]["snapshot_id"]

        if self.engine:
            try:
                return self.engine.diff_snapshots(previous, latest)
            except Exception as e:
                return {
                    "latest_snapshot_id": latest,
                    "previous_snapshot_id": previous,
                    "note": f"Engine diff failed: {e}",
                }

        return {
            "latest_snapshot_id": latest,
            "previous_snapshot_id": previous,
            "note": "Snapshot diff requires DebateEngineV2 instance",
        }

    def _build_evidence_targets(
        self, debate_id: str, snapshot: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        snapshot_id = snapshot["snapshot_id"] if snapshot else None

        if self.engine and snapshot_id:
            try:
                return self.engine.get_evidence_targets(debate_id, snapshot_id)
            except Exception as e:
                return {
                    "debate_id": debate_id,
                    "snapshot_id": snapshot_id,
                    "note": f"Evidence target analysis failed: {e}",
                }

        return {
            "debate_id": debate_id,
            "snapshot_id": snapshot_id,
            "note": "Evidence targets require DebateEngineV2 instance",
        }

    def _build_modulation(self, snapshot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not snapshot:
            return {
                "template_name": None,
                "template_version": None,
                "allowed_count": 0,
            "blocked_count": 0,
            "borderline_rate": 0.0,
            "suppression_policy": {"k": 5, "affected_buckets": [], "affected_bucket_count": 0},
        }
        return {
            "template_name": snapshot.get("template_name", ""),
            "template_version": snapshot.get("template_version", ""),
            "allowed_count": snapshot.get("allowed_count", 0),
            "blocked_count": snapshot.get("blocked_count", 0),
            "borderline_rate": snapshot.get("borderline_rate", 0.0) or 0.0,
            "suppression_policy": _coerce_json(snapshot.get("suppression_policy_json"), {}),
        }
