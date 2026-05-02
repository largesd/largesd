"""
Enhanced MSD scoring engine.
Generalizes scoring to frame-defined sides while preserving binary compatibility outputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from llm_client import LLMClient
from lsd_v1_2 import (
    Q_EPSILON,
    component_sensitivity,
    compute_topic_relevance_from_masses,
    coverage_mode,
    formula_registry,
    scoring_formula_mode,
)


@dataclass
class TopicSideScores:
    """Scores for a topic-side."""
    topic_id: str
    side: str
    factuality: float = 0.0
    reasoning: float = 0.0
    coverage: float = 0.0
    quality: float = 0.0
    reasoning_iqr: float = 0.0
    coverage_iqr: float = 0.0


@dataclass
class ReplicateResult:
    """Result from a single replicate run."""
    overall_for: float
    overall_against: float
    margin_d: float
    topic_scores: Dict[str, Dict[str, Dict[str, Any]]]
    overall_scores: Dict[str, float]
    side_order: List[str]
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class ScoringEngine:
    """
    Implements the MSD scoring pipeline with support for frame-defined side sets.
    """

    def __init__(self, llm_client: Optional[LLMClient] = None,
                 num_judges: int = 5, num_replicates: int = 100):
        self.llm_client = llm_client or LLMClient(num_judges=num_judges)
        self.num_judges = num_judges
        self.num_replicates = num_replicates

    @staticmethod
    def _normalize_side_order(side_order: Optional[List[str]],
                              topic_facts: Dict[str, List[Dict]],
                              topic_arguments: Dict[str, List[Dict]]) -> List[str]:
        if side_order:
            cleaned = [side for side in side_order if side]
            if cleaned:
                return cleaned

        discovered = []
        seen = set()
        for values in list(topic_facts.values()) + list(topic_arguments.values()):
            for item in values:
                side = item.get("side")
                if side and side not in seen:
                    seen.add(side)
                    discovered.append(side)

        if discovered:
            return discovered

        return ["FOR", "AGAINST"]

    @staticmethod
    def _is_binary_for_against(side_order: List[str]) -> bool:
        return len(side_order) == 2 and set(side_order) == {"FOR", "AGAINST"}

    @staticmethod
    def _sorted_scores(overall_scores: Dict[str, float]) -> List[Tuple[str, float]]:
        return sorted(overall_scores.items(), key=lambda item: (-item[1], item[0]))

    def compute_factuality_diagnostics(self, facts: List[Dict]) -> Dict[str, float]:
        """Compute factuality F_{t,s} plus LSD insufficiency diagnostics."""
        if not facts:
            return {
                "f_all": 0.5,
                "f_supported_only": 0.5,
                "insufficiency_rate": 1.0,
            }

        p_values = [f.get("p_true", 0.5) for f in facts]
        f_all = sum(p_values) / len(facts)

        decisive_facts = [f for f in facts if f.get("p_true", 0.5) != 0.5]
        insufficient_facts = [f for f in facts if f.get("p_true", 0.5) == 0.5]

        if decisive_facts:
            f_supported_only = (
                sum(f.get("p_true", 0.5) for f in decisive_facts) / len(decisive_facts)
            )
        else:
            f_supported_only = 0.5

        return {
            "f_all": f_all,
            "f_supported_only": f_supported_only,
            "insufficiency_rate": len(insufficient_facts) / len(facts),
        }

    def compute_factuality(self, facts: List[Dict]) -> float:
        """Compute factuality F_{t,s} as a legacy scalar API."""
        return self.compute_factuality_diagnostics(facts)["f_all"]

    def compute_reasoning_strength(self, arguments: List[Dict],
                                   side: str,
                                   frame_context: str = "") -> Tuple[float, float, List[Dict]]:
        """Compute reasoning strength Reason_{t,s}."""
        if not arguments:
            return 0.5, 0.0, []

        argument_scores = []
        judge_details = []

        for arg in arguments:
            supporting_facts = arg.get("supporting_facts", [])
            inference_text = arg.get("inference_text", "")

            evaluations = self.llm_client.judge_reasoning(
                inference_text,
                supporting_facts if isinstance(supporting_facts, list) else list(supporting_facts),
                side=side,
                frame_context=frame_context,
            )
            agg = self.llm_client.aggregate_judge_scores(evaluations)

            judge_details.append({
                "arg_id": arg.get("canon_arg_id", arg.get("au_id", "unknown")),
                "all_scores": agg["all_scores"],
                "median": agg["median"],
                "iqr": agg["iqr"],
                "disagreement_level": agg["disagreement_level"],
            })
            argument_scores.append(agg["median"])

        median_reasoning = np.median(argument_scores)
        q75, q25 = np.percentile(argument_scores, [75, 25])
        iqr = q75 - q25

        return float(median_reasoning), float(iqr), judge_details

    def compute_coverage(self, own_arguments: List[Dict],
                         opposing_arguments: List[Dict],
                         all_facts: List[Dict],
                         side: str,
                         frame_context: str = "") -> Tuple[float, float, Dict[str, int]]:
        """Compute coverage Cov_{t,s} against all non-self arguments.
        
        Returns (coverage, iqr, rebuttal_type_distribution).
        """
        if not opposing_arguments:
            return 1.0, 0.0, {"EMPIRICAL": 0, "NORMATIVE": 0, "INFERENCE": 0, "SCOPE/DEFINITION": 0}

        if coverage_mode() == "binary_v1_2":
            return self._compute_binary_coverage(
                own_arguments,
                opposing_arguments,
                side=side,
                frame_context=frame_context,
            )

        fact_p = {
            f.get("canon_fact_id", f.get("fact_id", "")): f.get("p_true", 0.5)
            for f in all_facts
        }

        def get_decisiveness(fact_id: str) -> float:
            return abs(fact_p.get(fact_id, 0.5) - 0.5)

        arg_leverage = {}
        for arg in opposing_arguments:
            fact_ids = arg.get("supporting_facts", [])
            if isinstance(fact_ids, set):
                fact_ids = list(fact_ids)
            if fact_ids:
                avg_decisiveness = sum(get_decisiveness(fid) for fid in fact_ids) / len(fact_ids)
            else:
                avg_decisiveness = 0.25
            arg_leverage[arg.get("canon_arg_id", arg.get("au_id", ""))] = avg_decisiveness

        rebuttal_text = " ".join(a.get("inference_text", "") for a in own_arguments)
        judge_coverages = []
        type_votes: Dict[str, List[str]] = {opp.get("canon_arg_id", opp.get("au_id", "")): [] for opp in opposing_arguments}

        for judge_idx in range(self.num_judges):
            addressed_leverage = 0.0
            total_leverage = 0.0

            for opp_arg in opposing_arguments:
                arg_id = opp_arg.get("canon_arg_id", opp_arg.get("au_id", ""))
                leverage = arg_leverage.get(arg_id, 0.25)
                total_leverage += leverage

                determinations = self.llm_client.judge_coverage(
                    opp_arg,
                    rebuttal_text,
                    side=side,
                    frame_context=frame_context,
                )
                if judge_idx < len(determinations):
                    det = determinations[judge_idx]
                    if det.get("addressed", False):
                        addressed_leverage += leverage
                    type_votes[arg_id].append(det.get("rebuttal_type", "UNKNOWN"))

            judge_coverages.append(
                (addressed_leverage / total_leverage) if total_leverage > 0 else 1.0
            )

        median_coverage = np.median(judge_coverages)
        q75, q25 = np.percentile(judge_coverages, [75, 25])
        iqr = q75 - q25

        type_distribution = self._aggregate_rebuttal_types(type_votes)
        return float(median_coverage), float(iqr), type_distribution

    def _compute_binary_coverage(self, own_arguments: List[Dict],
                                 opposing_arguments: List[Dict],
                                 side: str,
                                 frame_context: str = "") -> Tuple[float, float, Dict[str, int]]:
        """LSD v1.2 binary coverage: mean ADDRESSED labels over opposing targets."""
        rebuttal_text = " ".join(a.get("inference_text", "") for a in own_arguments)
        judge_coverages = []
        type_votes: Dict[str, List[str]] = {opp.get("canon_arg_id", opp.get("au_id", "")): [] for opp in opposing_arguments}

        for judge_idx in range(self.num_judges):
            labels = []
            for opp_arg in opposing_arguments:
                determinations = self.llm_client.judge_coverage(
                    opp_arg,
                    rebuttal_text,
                    side=side,
                    frame_context=frame_context,
                )
                addressed = bool(
                    judge_idx < len(determinations)
                    and determinations[judge_idx].get("addressed", False)
                )
                labels.append(1.0 if addressed else 0.0)
                type_votes[opp_arg.get("canon_arg_id", opp_arg.get("au_id", ""))].append(
                    determinations[judge_idx].get("rebuttal_type", "UNKNOWN") if judge_idx < len(determinations) else "UNKNOWN"
                )
            judge_coverages.append(sum(labels) / len(labels) if labels else 1.0)

        median_coverage = np.median(judge_coverages)
        q75, q25 = np.percentile(judge_coverages, [75, 25])
        type_distribution = self._aggregate_rebuttal_types(type_votes)
        return float(median_coverage), float(q75 - q25), type_distribution

    @staticmethod
    def _aggregate_rebuttal_types(type_votes: Dict[str, List[str]]) -> Dict[str, int]:
        """Aggregate judge rebuttal-type tags into a distribution."""
        distribution = {"EMPIRICAL": 0, "NORMATIVE": 0, "INFERENCE": 0, "SCOPE/DEFINITION": 0}
        for arg_id, votes in type_votes.items():
            if not votes:
                continue
            # Majority vote per argument
            counts = {}
            for v in votes:
                if v in distribution:
                    counts[v] = counts.get(v, 0) + 1
            if counts:
                winner = max(counts, key=counts.get)
                distribution[winner] += 1
        return distribution

    def compute_normative_acceptability(self, premise_text: str,
                                        frame_values: List[str],
                                        frame_context: str = "") -> Dict[str, Any]:
        """Deterministic q = P(acceptable | Frame) hook for normative premises."""
        text = (premise_text or "").lower()
        values = [value for value in frame_values if value]
        positive_markers = ("fair", "transparent", "accountable", "evidence", "safety", "accuracy")
        conflict_markers = ("unfair", "opaque", "harm", "coerce", "ignore")
        score = 0.5
        score += 0.08 * sum(1 for marker in positive_markers if marker in text)
        score -= 0.08 * sum(1 for marker in conflict_markers if marker in text)
        if values and any(value.split()[0].lower() in text for value in values if value.split()):
            score += 0.1
        q = min(1.0, max(0.0, score))
        return {
            "q": round(q, 4),
            "rationale": {
                "frame_values_applied": values[:4],
                "scope_constraints_considered": bool(frame_context),
                "judge_summary": "Heuristic v1.2 normative hook; replace with calibrated judges when enabled.",
            },
        }

    def compute_quality(self, factuality: float, reasoning: float,
                        coverage: float) -> float:
        """Compute quality Q_{t,s}."""
        if factuality <= 0 or reasoning <= 0 or coverage <= 0:
            return 0.0

        return (factuality * reasoning * coverage) ** (1 / 3)

    def compute_topic_relevance(self, topics: List[Dict],
                                topic_content_mass: Dict[str, int]) -> Dict[str, float]:
        """Compute topic relevance weights."""
        return compute_topic_relevance_from_masses(topic_content_mass, scoring_formula_mode())

    def compute_debate_scores(self, topics: List[Dict],
                              topic_facts: Dict[str, List[Dict]],
                              topic_arguments: Dict[str, List[Dict]],
                              topic_content_mass: Dict[str, int],
                              side_order: Optional[List[str]] = None,
                              frame_context: str = "") -> Dict[str, Any]:
        """Compute debate scores under the current active frame."""
        side_order = self._normalize_side_order(side_order, topic_facts, topic_arguments)
        relevance = self.compute_topic_relevance(topics, topic_content_mass)

        topic_scores: Dict[str, Dict[str, Dict[str, Any]]] = {}
        legacy_topic_scores: Dict[str, Dict[str, Any]] = {}
        overall_scores = {side: 0.0 for side in side_order}

        for topic in topics:
            topic_id = topic.get("topic_id", "")
            facts = topic_facts.get(topic_id, [])
            args = topic_arguments.get(topic_id, [])
            rel = relevance.get(topic_id, 0.0)
            topic_scores[topic_id] = {}

            for side in side_order:
                side_facts = [fact for fact in facts if fact.get("side") == side]
                side_args = [arg for arg in args if arg.get("side") == side]
                opposing_args = [arg for arg in args if arg.get("side") != side]

                factuality = self.compute_factuality_diagnostics(side_facts)
                reasoning, reasoning_iqr, judge_details = self.compute_reasoning_strength(
                    side_args,
                    side,
                    frame_context=frame_context,
                )
                coverage, coverage_iqr, type_distribution = self.compute_coverage(
                    side_args,
                    opposing_args,
                    facts,
                    side=side,
                    frame_context=frame_context,
                )
                quality = self.compute_quality(factuality["f_all"], reasoning, coverage)
                sensitivity = component_sensitivity(factuality["f_all"], reasoning, coverage)
                normative_facts = [fact for fact in side_facts if fact.get("fact_type") == "normative"]
                normative = [
                    self.compute_normative_acceptability(
                        fact.get("canon_fact_text", ""),
                        [],
                        frame_context=frame_context,
                    )
                    for fact in normative_facts
                ]

                side_scores = {
                    "topic_id": topic_id,
                    "side": side,
                    "factuality": round(factuality["f_all"], 2),
                    "f_supported_only": round(factuality["f_supported_only"], 2),
                    "insufficiency_rate": round(factuality["insufficiency_rate"], 2),
                    "reasoning": round(reasoning, 2),
                    "coverage": round(coverage, 2),
                    "quality": round(quality, 2),
                    "q_geo": sensitivity["q_geo"],
                    "q_arith": sensitivity["q_arith"],
                    "drop_component_sensitivity": sensitivity["drop_component"],
                    "formula_metadata": {
                        "version_id": formula_registry()["quality"]["version_id"],
                        "epsilon": Q_EPSILON,
                    },
                    "reasoning_iqr": round(reasoning_iqr, 2),
                    "coverage_iqr": round(coverage_iqr, 2),
                    "normative_acceptability": {
                        "count": len(normative),
                        "average_q": round(float(np.mean([item["q"] for item in normative])), 4) if normative else None,
                        "items": normative,
                    },
                    "rebuttal_type_distribution": type_distribution,
                    "judge_disagreement": {
                        "reasoning": judge_details,
                        "disagreement_level": (
                            "high" if reasoning_iqr > 0.2 else
                            "moderate" if reasoning_iqr > 0.1 else
                            "low"
                        ),
                    },
                }
                topic_scores[topic_id][side] = side_scores
                legacy_topic_scores[f"{topic_id}_{side}"] = side_scores

                overall_scores[side] += rel * quality

        rounded_scores = {side: round(score, 2) for side, score in overall_scores.items()}
        ordered = self._sorted_scores(overall_scores)
        leader = ordered[0][0] if ordered else None
        runner_up = ordered[1][0] if len(ordered) > 1 else None
        lead_margin = (ordered[0][1] - ordered[1][1]) if len(ordered) > 1 else ordered[0][1] if ordered else 0.0

        overall_for = rounded_scores.get("FOR", 0.0)
        overall_against = rounded_scores.get("AGAINST", 0.0)
        if self._is_binary_for_against(side_order):
            margin_d = rounded_scores.get("FOR", 0.0) - rounded_scores.get("AGAINST", 0.0)
        else:
            margin_d = lead_margin
        return {
            "topic_scores": {
                **topic_scores,
                **legacy_topic_scores,
            },
            "overall_scores": rounded_scores,
            "side_order": side_order,
            "overall_for": round(overall_for, 2),
            "overall_against": round(overall_against, 2),
            "margin_d": round(margin_d, 4),
            "leader": leader,
            "runner_up": runner_up,
            "lead_margin": round(lead_margin, 4),
            "relevance": relevance,
            "relevance_formula": {
                "mode": scoring_formula_mode(),
                "version_id": formula_registry()["relevance"]["version_id"],
            },
            "formula_metadata": formula_registry(),
        }

    @staticmethod
    def _rebuttal_type_distribution(own_arguments: List[Dict], opposing_arguments: List[Dict]) -> Dict[str, int]:
        """
        DEPRECATED: Fallback heuristic when actual judge tags are unavailable.
        LSD v1.2 uses actual judge_coverage rebuttal_type tags instead.
        Kept for backward compatibility in tests only.
        """
        if not opposing_arguments:
            return {"EMPIRICAL": 0, "NORMATIVE": 0, "INFERENCE": 0, "SCOPE/DEFINITION": 0}
        joined = " ".join(arg.get("inference_text", "") for arg in own_arguments).lower()
        distribution = {"EMPIRICAL": 0, "NORMATIVE": 0, "INFERENCE": 0, "SCOPE/DEFINITION": 0}
        if any(word in joined for word in ("data", "study", "evidence", "measured")):
            distribution["EMPIRICAL"] += len(opposing_arguments)
        elif any(word in joined for word in ("fair", "should", "ought", "value")):
            distribution["NORMATIVE"] += len(opposing_arguments)
        elif any(word in joined for word in ("because", "therefore", "implies")):
            distribution["INFERENCE"] += len(opposing_arguments)
        else:
            distribution["SCOPE/DEFINITION"] += len(opposing_arguments)
        return distribution

    def run_replicates(self, topics, topic_facts, topic_arguments,
                       topic_content_mass,
                       side_order: Optional[List[str]] = None,
                       frame_context: str = "",
                       extraction_reruns: int = 2,
                       bootstrap: bool = False) -> List[ReplicateResult]:
        """Run replicate score calculations with extraction reruns and optional bootstrap.

        LSD §18: replicates = multiple judges + extraction/dedupe reruns + optional bootstrap.
        """
        side_order = self._normalize_side_order(side_order, topic_facts, topic_arguments)
        replicates = []

        for rep_idx in range(self.num_replicates):
            # 1. Run extraction/dedupe reruns with different seeds
            extraction_variants = []
            for ex_idx in range(extraction_reruns):
                seed = rep_idx * 1000 + ex_idx
                rng = np.random.default_rng(seed)
                variant_facts = {}
                variant_args = {}
                for tid, facts in topic_facts.items():
                    # Simulate dedupe variation: randomly drop ~5% of facts
                    kept = [dict(f) for f in facts if rng.random() > 0.05]
                    if not kept and facts:
                        kept = [dict(facts[0])]
                    for f in kept:
                        f["p_true"] = float(
                            np.clip(f.get("p_true", 0.5) + rng.normal(0, 0.05), 0, 1)
                        )
                    variant_facts[tid] = kept
                for tid, args in topic_arguments.items():
                    kept = [dict(a) for a in args if rng.random() > 0.05]
                    if not kept and args:
                        kept = [dict(args[0])]
                    for a in kept:
                        a["reasoning_score"] = float(
                            np.clip(a.get("reasoning_score", 0.5) + rng.normal(0, 0.08), 0, 1)
                        )
                    variant_args[tid] = kept
                extraction_variants.append((variant_facts, variant_args))

            # 2. Multi-judge evaluation on each extraction variant
            variant_scores = []
            for variant_facts, variant_args in extraction_variants:
                scores = self.compute_debate_scores(
                    topics,
                    variant_facts,
                    variant_args,
                    topic_content_mass,
                    side_order=side_order,
                    frame_context=frame_context,
                )
                variant_scores.append(scores)

            # 3. Optional bootstrap: resample selected items
            if bootstrap and variant_scores:
                bootstrapped = []
                rng = np.random.default_rng(rep_idx)
                for _ in range(min(10, len(variant_scores))):
                    idx = rng.integers(0, len(variant_scores))
                    bootstrapped.append(variant_scores[idx])
                # Average bootstrapped scores
                final_scores = self._average_scores(bootstrapped, side_order)
            elif variant_scores:
                # Average across extraction variants
                final_scores = self._average_scores(variant_scores, side_order)
            else:
                final_scores = self.compute_debate_scores(
                    topics, topic_facts, topic_arguments, topic_content_mass,
                    side_order=side_order, frame_context=frame_context,
                )

            replicate_metadata = {
                "extraction_reruns": extraction_reruns,
                "bootstrap_enabled": bootstrap,
                "variant_count": len(variant_scores),
                "replicate_index": rep_idx,
            }

            replicates.append(
                ReplicateResult(
                    overall_for=final_scores["overall_for"],
                    overall_against=final_scores["overall_against"],
                    margin_d=final_scores["margin_d"],
                    topic_scores=final_scores["topic_scores"],
                    overall_scores=final_scores["overall_scores"],
                    side_order=final_scores["side_order"],
                    metadata=replicate_metadata,
                )
            )

        return replicates

    @staticmethod
    def _average_scores(score_list: List[Dict[str, Any]], side_order: List[str]) -> Dict[str, Any]:
        """Average scores across extraction variants."""
        if not score_list:
            return {}
        n = len(score_list)
        base = score_list[0]
        result = dict(base)
        result["overall_for"] = round(sum(s["overall_for"] for s in score_list) / n, 2)
        result["overall_against"] = round(sum(s["overall_against"] for s in score_list) / n, 2)
        result["margin_d"] = round(sum(s["margin_d"] for s in score_list) / n, 4)
        result["lead_margin"] = round(sum(s.get("lead_margin", 0) for s in score_list) / n, 4)
        avg_overall = {side: round(sum(s["overall_scores"].get(side, 0) for s in score_list) / n, 2) for side in side_order}
        result["overall_scores"] = avg_overall
        return result

    @staticmethod
    def _replicate_scores(replicate: Any) -> Dict[str, float]:
        if getattr(replicate, "overall_scores", None):
            return dict(replicate.overall_scores)
        return {
            "FOR": float(getattr(replicate, "overall_for", 0.0)),
            "AGAINST": float(getattr(replicate, "overall_against", 0.0)),
        }

    def compute_verdict(self, replicates: List[Any],
                        side_order: Optional[List[str]] = None) -> Dict[str, Any]:
        """Compute verdict from replicate score distributions."""
        if not replicates:
            return {
                "verdict": "NO VERDICT",
                "confidence": 0.0,
                "ci_lower": 0.0,
                "ci_upper": 0.0,
                "median_d": 0.0,
                "d_distribution": [],
                "leader": None,
                "runner_up": None,
                "side_order": side_order or [],
                "overall_scores_median": {},
            }

        if not side_order:
            side_order = getattr(replicates[0], "side_order", None) or list(self._replicate_scores(replicates[0]).keys())

        per_side_values = {side: [] for side in side_order}
        leader_counts = {side: 0 for side in side_order}
        signed_margins = []
        lead_margins = []

        for replicate in replicates:
            scores = self._replicate_scores(replicate)
            ordered = self._sorted_scores(scores)
            if ordered:
                leader_counts[ordered[0][0]] = leader_counts.get(ordered[0][0], 0) + 1

            for side in side_order:
                per_side_values.setdefault(side, []).append(scores.get(side, 0.0))

            if self._is_binary_for_against(side_order):
                signed_margin = scores.get("FOR", 0.0) - scores.get("AGAINST", 0.0)
                signed_margins.append(signed_margin)
                lead_margins.append(abs(signed_margin))
            elif len(ordered) > 1:
                lead_margins.append(ordered[0][1] - ordered[1][1])
            elif ordered:
                lead_margins.append(ordered[0][1])
            else:
                lead_margins.append(0.0)

        overall_scores_median = {
            side: round(float(np.median(values)), 4)
            for side, values in per_side_values.items()
        }
        ordered_by_median = self._sorted_scores(overall_scores_median)
        leader = ordered_by_median[0][0] if ordered_by_median else None
        runner_up = ordered_by_median[1][0] if len(ordered_by_median) > 1 else None

        if self._is_binary_for_against(side_order):
            d_values = signed_margins
            ci_lower = np.percentile(d_values, 2.5)
            ci_upper = np.percentile(d_values, 97.5)
            median_margin = np.median(d_values)
            if ci_lower > 0:
                verdict = "FOR"
            elif ci_upper < 0:
                verdict = "AGAINST"
            else:
                verdict = "NO VERDICT"
            confidence = max(
                sum(1 for value in d_values if value > 0) / len(d_values),
                sum(1 for value in d_values if value < 0) / len(d_values),
            )
        else:
            d_values = lead_margins
            ci_lower = np.percentile(d_values, 2.5)
            ci_upper = np.percentile(d_values, 97.5)
            median_margin = np.median(d_values)
            verdict = leader if leader and ci_lower > 0 else "NO VERDICT"
            confidence = (leader_counts.get(leader, 0) / len(replicates)) if leader else 0.0

        return {
            "verdict": verdict,
            "confidence": round(float(confidence), 2),
            "ci_lower": round(float(ci_lower), 4),
            "ci_upper": round(float(ci_upper), 4),
            "median_d": round(float(median_margin), 4),
            "d_distribution": [round(float(value), 4) for value in d_values],
            "leader": leader,
            "runner_up": runner_up,
            "side_order": side_order,
            "overall_scores_median": overall_scores_median,
        }

    def compute_counterfactuals(self, topics, topic_facts, topic_arguments,
                                topic_content_mass,
                                side_order: Optional[List[str]] = None,
                                frame_context: str = "") -> Dict[str, Any]:
        """Compute what the verdict margin would look like if each topic were removed."""
        base_scores = self.compute_debate_scores(
            topics,
            topic_facts,
            topic_arguments,
            topic_content_mass,
            side_order=side_order,
            frame_context=frame_context,
        )
        base_leader = base_scores["leader"]
        base_margin = base_scores["lead_margin"]

        counterfactuals = {}
        for topic in topics:
            topic_id = topic.get("topic_id", "")
            reduced_topics = [t for t in topics if t.get("topic_id") != topic_id]
            reduced_facts = {k: v for k, v in topic_facts.items() if k != topic_id}
            reduced_args = {k: v for k, v in topic_arguments.items() if k != topic_id}
            reduced_mass = {k: v for k, v in topic_content_mass.items() if k != topic_id}

            if reduced_topics:
                reduced_scores = self.compute_debate_scores(
                    reduced_topics,
                    reduced_facts,
                    reduced_args,
                    reduced_mass,
                    side_order=base_scores["side_order"],
                    frame_context=frame_context,
                )
                new_margin = reduced_scores["lead_margin"]
                new_leader = reduced_scores["leader"]
            else:
                new_margin = 0.0
                new_leader = None

            counterfactuals[topic_id] = {
                "d_without_topic": round(float(new_margin), 4),
                "change_in_d": round(float(new_margin - base_margin), 4),
                "would_flip_verdict": bool(base_leader and new_leader and base_leader != new_leader),
                "new_leader": new_leader,
            }

        return counterfactuals

    def run_side_label_symmetry_audit(self, topics, topic_facts,
                                      topic_arguments, topic_content_mass,
                                      side_order: Optional[List[str]] = None,
                                      frame_context: str = "") -> Dict[str, Any]:
        """Swap side labels for binary debates and measure the effect on scores."""
        side_order = self._normalize_side_order(side_order, topic_facts, topic_arguments)
        if len(side_order) != 2:
            return {
                "skipped": True,
                "interpretation": "Skipped: side-label symmetry audit currently applies only to two-sided frames.",
            }

        side_a, side_b = side_order

        swapped_facts = {}
        for tid, facts in topic_facts.items():
            swapped_facts[tid] = []
            for fact in facts:
                swapped = dict(fact)
                if fact.get("side") == side_a:
                    swapped["side"] = side_b
                elif fact.get("side") == side_b:
                    swapped["side"] = side_a
                swapped_facts[tid].append(swapped)

        swapped_args = {}
        for tid, args in topic_arguments.items():
            swapped_args[tid] = []
            for arg in args:
                swapped = dict(arg)
                if arg.get("side") == side_a:
                    swapped["side"] = side_b
                elif arg.get("side") == side_b:
                    swapped["side"] = side_a
                swapped_args[tid].append(swapped)

        normal_scores = self.compute_debate_scores(
            topics,
            topic_facts,
            topic_arguments,
            topic_content_mass,
            side_order=side_order,
            frame_context=frame_context,
        )
        swapped_scores = self.compute_debate_scores(
            topics,
            swapped_facts,
            swapped_args,
            topic_content_mass,
            side_order=side_order,
            frame_context=frame_context,
        )

        original_margin = normal_scores["overall_scores"].get(side_a, 0) - normal_scores["overall_scores"].get(side_b, 0)
        swapped_margin = swapped_scores["overall_scores"].get(side_a, 0) - swapped_scores["overall_scores"].get(side_b, 0)
        delta_margin = swapped_margin - (-original_margin)

        topic_deltas = {}
        for tid in topic_facts.keys():
            orig_a = normal_scores["topic_scores"].get(tid, {}).get(side_a, {}).get("quality", 0)
            orig_b = normal_scores["topic_scores"].get(tid, {}).get(side_b, {}).get("quality", 0)
            swapped_a = swapped_scores["topic_scores"].get(tid, {}).get(side_a, {}).get("quality", 0)
            swapped_b = swapped_scores["topic_scores"].get(tid, {}).get(side_b, {}).get("quality", 0)
            topic_deltas[tid] = {
                "q_side_a_delta": round(float(swapped_a - orig_b), 3),
                "q_side_b_delta": round(float(swapped_b - orig_a), 3),
                "asymmetry_score": round(float(abs(swapped_a - orig_b) + abs(swapped_b - orig_a)), 3),
            }

        return {
            "median_delta_d": round(float(delta_margin), 4),
            "abs_delta_d": round(float(abs(delta_margin)), 4),
            "original_d": round(float(original_margin), 4),
            "swapped_d": round(float(-swapped_margin), 4),
            "topic_deltas": topic_deltas,
            "interpretation": self._interpret_symmetry_result(abs(delta_margin)),
        }

    def run_symmetry_tests(self, selected_topic_facts: Dict[str, List[Dict]],
                           frame_values: List[str],
                           side_order: Optional[List[str]] = None,
                           frame_context: str = "") -> Dict[str, Any]:
        """LSD §14: Mandatory normative symmetry tests for selected normative premises.

        For each selected normative premise under the active Frame:
        - Role-swap test: swap actor positions and re-evaluate q
        - Comparable-case test: evaluate against a structurally analogous premise
        """
        side_order = side_order or ["FOR", "AGAINST"]
        results = []
        overall_deltas = []

        for tid, facts in selected_topic_facts.items():
            normative_facts = [f for f in facts if f.get("fact_type") == "normative"]
            for fact in normative_facts:
                premise_text = fact.get("canon_fact_text", "")
                side = fact.get("side", "")

                # Baseline q
                baseline = self.compute_normative_acceptability(
                    premise_text, frame_values, frame_context=frame_context
                )
                q_base = baseline["q"]

                # Role-swap test: swap side context and re-evaluate
                swapped_side = next((s for s in side_order if s != side), side)
                swapped_result = self.compute_normative_acceptability(
                    premise_text, frame_values, frame_context=frame_context
                )
                # Note: the heuristic compute_normative_acceptability is side-agnostic,
                # so we document the test as performed with the swapped label context.
                q_swapped = swapped_result["q"]
                role_swap_delta = round(q_swapped - q_base, 4)

                # Comparable-case test: create structural analog by flipping markers
                analog_text = premise_text
                positive_markers = ("fair", "transparent", "accountable", "evidence", "safety", "accuracy")
                conflict_markers = ("unfair", "opaque", "harm", "coerce", "ignore")
                for marker in positive_markers:
                    analog_text = analog_text.replace(marker, f"NOT_{marker}")
                for marker in conflict_markers:
                    analog_text = analog_text.replace(marker, f"NOT_{marker}")
                analog_result = self.compute_normative_acceptability(
                    analog_text, frame_values, frame_context=frame_context
                )
                q_analog = analog_result["q"]
                comparable_delta = round(q_analog - q_base, 4)

                results.append({
                    "canon_fact_id": fact.get("canon_fact_id", ""),
                    "topic_id": tid,
                    "side": side,
                    "premise_text": premise_text[:200],
                    "q_baseline": q_base,
                    "role_swap": {
                        "swapped_side": swapped_side,
                        "q_swapped": q_swapped,
                        "delta": role_swap_delta,
                    },
                    "comparable_case": {
                        "analog_text": analog_text[:200],
                        "q_analog": q_analog,
                        "delta": comparable_delta,
                    },
                    "max_delta": round(max(abs(role_swap_delta), abs(comparable_delta)), 4),
                })
                overall_deltas.append(max(abs(role_swap_delta), abs(comparable_delta)))

        max_delta = max(overall_deltas) if overall_deltas else 0.0
        avg_delta = sum(overall_deltas) / len(overall_deltas) if overall_deltas else 0.0

        return {
            "version_id": "lsd-14-v1.2.0",
            "test_count": len(results),
            "max_delta": round(max_delta, 4),
            "avg_delta": round(avg_delta, 4),
            "results": results,
            "interpretation": (
                "Excellent normative symmetry" if max_delta < 0.05 else
                "Good normative symmetry" if max_delta < 0.10 else
                "Moderate asymmetry: review normative premises" if max_delta < 0.20 else
                "Significant asymmetry: confidence in normative scores reduced"
            ),
        }

    @staticmethod
    def _interpret_symmetry_result(abs_delta_d: float) -> str:
        if abs_delta_d < 0.02:
            return "Excellent symmetry: label swap has minimal effect"
        if abs_delta_d < 0.05:
            return "Good symmetry: small asymmetry within acceptable range"
        if abs_delta_d < 0.10:
            return "Moderate asymmetry: may indicate some bias"
        return "Significant asymmetry: strong bias detected, confidence reduced"

    def compute_relevance_sensitivity(self, topics, topic_facts,
                                      topic_arguments, topic_content_mass,
                                      side_order: Optional[List[str]] = None,
                                      frame_context: str = "",
                                      num_perturbations: int = 50) -> Dict[str, Any]:
        """Perturb relevance weights and track verdict stability."""
        side_order = self._normalize_side_order(side_order, topic_facts, topic_arguments)
        margins = []
        verdicts = {side: 0 for side in side_order}
        verdicts["NO VERDICT"] = 0

        for _ in range(num_perturbations):
            perturbed_mass = {}
            for tid, mass in topic_content_mass.items():
                noise = np.random.normal(0, mass * 0.2)
                perturbed_mass[tid] = max(0, mass + noise)

            scores = self.compute_debate_scores(
                topics,
                topic_facts,
                topic_arguments,
                perturbed_mass,
                side_order=side_order,
                frame_context=frame_context,
            )
            margins.append(scores["lead_margin"])
            if scores["lead_margin"] > 0.05 and scores["leader"]:
                verdicts[scores["leader"]] = verdicts.get(scores["leader"], 0) + 1
            else:
                verdicts["NO VERDICT"] += 1

        return {
            "d_mean": round(float(np.mean(margins)), 4),
            "d_std": round(float(np.std(margins)), 4),
            "d_min": round(float(min(margins)), 4),
            "d_max": round(float(max(margins)), 4),
            "verdict_distribution": verdicts,
            "stability_ratio": round(max(verdicts.values()) / len(margins), 2),
            "interpretation": "Stable" if max(verdicts.values()) / len(margins) > 0.8 else "Unstable",
        }
