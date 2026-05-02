"""
LSD v1.2 formula constants and diagnostic helpers.

This module keeps the v1.2 math and public policy parameters in one place so
API payloads, tests, reports, and UI badges can point at the same definitions.
"""

from __future__ import annotations

import json
import math
import os
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from statistics import median
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


LSD_VERSION = "1.2.0"
AUDIT_SCHEMA_VERSION = "v1.2.0"

MODERATION_DIAGNOSTICS_VERSION = "lsd-3-v1.2.0"
MODERATION_THRESHOLD = 0.50
BORDERLINE_EPSILON = 0.05
SUPPRESSION_K = 5

SELECTION_FORMULA_VERSION = "lsd-11-v1.2.0"
CENTRALITY_FORMULA = "centrality_i = log(1 + refs_i), capped at P95 within pool"
RARITY_RHO = 0.20
LOW_CENTRALITY_QUANTILE = 0.60
TOP_K_CENTRALITY = 10
SELECTION_WEIGHTS = {"w1": 1.0, "w2": 0.1, "w3": 1.0}

RELEVANCE_FORMULA_VERSION = "lsd-12-v1.2.0"
Q_FORMULA_VERSION = "lsd-16-v1.2.0"
Q_EPSILON = 0.01

FACT_CHECK_POLICY_VERSION = "lsd-13-policy-v1.2.0"
FACT_CHECK_THRESHOLDS = {
    "threshold_support": 0.70,
    "threshold_contradiction": 0.70,
}


def feature_flag(name: str, default: str, allowed: Sequence[str]) -> str:
    """Read a feature flag and fall back safely when the value is unknown."""
    value = (os.getenv(name) or default).strip()
    return value if value in allowed else default


def fact_checker_mode() -> str:
    """Return the public v1.2 fact-checker mode."""
    return feature_flag(
        "FACT_CHECKER_MODE",
        os.getenv("FACT_CHECK_MODE", "simulated").lower(),
        ("simulated", "perfect_checker", "perfect", "online_allowlist", "OFFLINE", "ONLINE_ALLOWLIST"),
    )


def scoring_formula_mode() -> str:
    return feature_flag(
        "SCORING_FORMULA_MODE",
        "legacy_linear",
        ("legacy_linear", "v1_2_sqrt", "v1_2_log"),
    )


def frame_mode() -> str:
    return feature_flag("FRAME_MODE", "single", ("single", "multi"))


def coverage_mode() -> str:
    return feature_flag("COVERAGE_MODE", "leverage_legacy", ("leverage_legacy", "binary_v1_2"))


def formula_registry() -> Dict[str, Any]:
    """Publish every public formula used by the v1.2 compatibility layer."""
    return {
        "lsd_version": LSD_VERSION,
        "moderation": {
            "version_id": MODERATION_DIAGNOSTICS_VERSION,
            "borderline_rate": (
                "count(score in [threshold - epsilon, threshold + epsilon]) / total_posts"
            ),
            "threshold": MODERATION_THRESHOLD,
            "epsilon": BORDERLINE_EPSILON,
            "small_count_suppression_k": SUPPRESSION_K,
        },
        "selection": selection_formula_metadata(),
        "relevance": {
            "version_id": RELEVANCE_FORMULA_VERSION,
            "legacy_linear": "Rel_t = SelMass_t / sum_u SelMass_u",
            "v1_2_sqrt": "Rel_t = sqrt(SelMass_t) / sum_u sqrt(SelMass_u)",
            "v1_2_log": "Rel'_t = log(1 + SelMass_t) / sum_u log(1 + SelMass_u)",
            "active_mode": scoring_formula_mode(),
        },
        "quality": {
            "version_id": Q_FORMULA_VERSION,
            "Q_geo": "Q = (prod_k max(C_k, epsilon))^(1/m)",
            "Q_arith": "Q_arith = mean(C_k)",
            "epsilon": Q_EPSILON,
        },
        "fact_check": {
            "version_id": FACT_CHECK_POLICY_VERSION,
            "thresholds": FACT_CHECK_THRESHOLDS,
            "perfect_checker": "SUPPORTED -> p=1.0, REFUTED -> p=0.0, INSUFFICIENT -> p=0.5",
        },
        "feature_flags": {
            "FACT_CHECKER_MODE": fact_checker_mode(),
            "SCORING_FORMULA_MODE": scoring_formula_mode(),
            "FRAME_MODE": frame_mode(),
            "COVERAGE_MODE": coverage_mode(),
        },
    }


def selection_formula_metadata() -> Dict[str, Any]:
    return {
        "version_id": SELECTION_FORMULA_VERSION,
        "centrality": CENTRALITY_FORMULA,
        "centrality_cap_percentile": 95,
        "rarity_rho": RARITY_RHO,
        "low_centrality_quantile": LOW_CENTRALITY_QUANTILE,
        "selection_score": "S_i = w1 * centrality_i_capped + w2 * log(1 + distinct_support_i_internal) + w3 * AU_quality_proxy_i",
        "weights": dict(SELECTION_WEIGHTS),
        "top_k_centrality": TOP_K_CENTRALITY,
    }


def compute_selection_score(centrality_capped: float, distinct_support: int, quality_proxy: float) -> float:
    """Deterministic v1.2 selection score used by formula tests and selection code."""
    return (
        SELECTION_WEIGHTS["w1"] * float(centrality_capped)
        + SELECTION_WEIGHTS["w2"] * math.log1p(max(0, int(distinct_support)))
        + SELECTION_WEIGHTS["w3"] * float(quality_proxy)
    )


def compute_q_geomean(components: Sequence[float], epsilon: float = Q_EPSILON) -> float:
    safe = [max(float(value), epsilon) for value in components]
    if not safe:
        return 0.0
    product = 1.0
    for value in safe:
        product *= value
    return product ** (1.0 / len(safe))


def compute_q_arith(components: Sequence[float]) -> float:
    values = [float(value) for value in components]
    return sum(values) / len(values) if values else 0.0


def compute_topic_relevance_from_masses(topic_content_mass: Mapping[str, float], mode: Optional[str] = None) -> Dict[str, float]:
    """Compute relevance weights for legacy and v1.2 formula modes."""
    mode = mode or scoring_formula_mode()
    transformed: Dict[str, float] = {}
    for topic_id, raw_mass in topic_content_mass.items():
        mass = max(0.0, float(raw_mass or 0.0))
        if mode == "v1_2_sqrt":
            transformed[topic_id] = math.sqrt(mass)
        elif mode == "v1_2_log":
            transformed[topic_id] = math.log1p(mass)
        else:
            transformed[topic_id] = mass

    denom = sum(transformed.values())
    if denom <= 0:
        n = max(len(transformed), 1)
        return {topic_id: 1.0 / n for topic_id in transformed}
    return {topic_id: value / denom for topic_id, value in transformed.items()}


def p95_cap(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(float(v) for v in values)
    if len(sorted_values) == 1:
        return sorted_values[0]
    index = 0.95 * (len(sorted_values) - 1)
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return sorted_values[int(index)]
    weight = index - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _safe_json(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return fallback


def _token_bucket(text: str) -> Tuple[str, int]:
    words = [word.lower() for word in (text or "").split() if word.strip()]
    if not words:
        return "empty", 0
    return " ".join(words[:8]), len(words)


def estimate_moderation_score(post: Mapping[str, Any], min_chars: int = 20, threshold: float = MODERATION_THRESHOLD) -> float:
    """Estimate a published moderation score from persisted post outcomes.

    The modulation engine is rule-based and does not persist a continuous score.
    This compatibility score is deterministic and intentionally conservative:
    blocked items are above threshold, very-short-but-allowed items sit near the
    threshold, and normal allowed items sit comfortably below threshold.
    """
    if (post.get("modulation_outcome") or "").lower() == "blocked":
        return 1.0

    text = f"{post.get('facts', '')} {post.get('inference', '')}".strip()
    length = len(text)
    if not text:
        return threshold
    if length <= min_chars + 5:
        return threshold - 0.02
    if length <= min_chars + 25:
        return threshold - 0.05
    return 0.10


def compute_borderline_rate(posts: Sequence[Mapping[str, Any]]) -> float:
    if not posts:
        return 0.0
    scores = [estimate_moderation_score(post) for post in posts]
    low = MODERATION_THRESHOLD - BORDERLINE_EPSILON
    high = MODERATION_THRESHOLD + BORDERLINE_EPSILON
    count = sum(1 for score in scores if low <= score <= high)
    return round(count / len(scores), 4)


def build_suppression_policy(
    posts: Sequence[Mapping[str, Any]],
    block_reason_counts: Mapping[str, int],
    *,
    k: int = SUPPRESSION_K,
) -> Dict[str, Any]:
    affected = []

    for reason, count in block_reason_counts.items():
        if 0 < int(count) < k:
            affected.append({"channel": "block_reason_histogram", "key": str(reason), "count": int(count)})

    contributor_counts = Counter((post.get("user_id") or "anonymous") for post in posts)
    if 0 < len(contributor_counts) < k:
        affected.append({"channel": "participation_concentration", "key": "contributors", "count": len(contributor_counts)})

    channel_counts = Counter((post.get("channel") or "public") for post in posts)
    for channel, count in channel_counts.items():
        if 0 < int(count) < k:
            affected.append({"channel": "channel_mix_proportions", "key": str(channel), "count": int(count)})

    near_duplicates = template_similarity_prevalence(posts).get("near_duplicate_count", 0)
    if 0 < near_duplicates < k:
        affected.append({"channel": "template_similarity_prevalence", "key": "near_duplicates", "count": int(near_duplicates)})

    return {
        "version_id": MODERATION_DIAGNOSTICS_VERSION,
        "k": k,
        "affected_buckets": affected,
        "affected_bucket_count": len(affected),
        "published_parameters": {
            "minimum_count_k": k,
            "borderline_epsilon": BORDERLINE_EPSILON,
            "moderation_threshold": MODERATION_THRESHOLD,
        },
    }


def participation_concentration(posts: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    counts = Counter((post.get("user_id") or "anonymous") for post in posts)
    total = sum(counts.values())
    sorted_counts = sorted(counts.values(), reverse=True)

    def share(percent: float) -> float:
        if total <= 0 or not sorted_counts:
            return 0.0
        n = max(1, math.ceil(len(sorted_counts) * percent))
        return sum(sorted_counts[:n]) / total

    entropy = 0.0
    if total > 0:
        for count in counts.values():
            p = count / total
            entropy -= p * math.log(p)

    return {
        "version_id": "lsd-2.3-v1.2.0",
        "contributor_count": len(counts),
        "post_count": total,
        "concentration_buckets": {
            "top_1pct_share": round(share(0.01), 4),
            "top_5pct_share": round(share(0.05), 4),
            "top_10pct_share": round(share(0.10), 4),
        },
        "participation_entropy": round(entropy, 4),
        "channel_mix_proportions": channel_mix(posts),
    }


def channel_mix(posts: Sequence[Mapping[str, Any]]) -> Dict[str, float]:
    total = len(posts)
    counts = Counter((post.get("channel") or "public") for post in posts)
    base = {"public": 0.0, "org": 0.0, "accredited": 0.0, "invited_expert": 0.0}
    if total <= 0:
        return base
    for channel, count in counts.items():
        base[str(channel)] = round(count / total, 4)
    return base


def template_similarity_prevalence(posts: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    buckets = Counter()
    for post in posts:
        key, length = _token_bucket(f"{post.get('facts', '')} {post.get('inference', '')}")
        if length >= 8:
            buckets[key] += 1
    near_duplicate_count = sum(count for count in buckets.values() if count > 1)
    total = len(posts)
    return {
        "version_id": "lsd-10-template-sim-v1.2.0",
        "near_duplicate_count": near_duplicate_count,
        "template_similarity_rate": round(near_duplicate_count / total, 4) if total else 0.0,
        "bucket_count": len(buckets),
    }


def burstiness_indicators(posts: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    by_hour = Counter()
    by_topic_channel = Counter()
    for post in posts:
        timestamp = str(post.get("timestamp") or "")
        hour = timestamp[:13] if len(timestamp) >= 13 else "unknown"
        topic = post.get("topic_id") or "unassigned"
        channel = post.get("channel") or "public"
        by_hour[hour] += 1
        by_topic_channel[f"{topic}:{channel}"] += 1

    counts = list(by_hour.values())
    mean = sum(counts) / len(counts) if counts else 0.0
    variance = sum((count - mean) ** 2 for count in counts) / len(counts) if counts else 0.0
    std = math.sqrt(variance)

    hourly = {}
    for hour, count in by_hour.items():
        z = (count - mean) / std if std > 0 else 0.0
        hourly[hour] = {"count": count, "z_score": round(z, 4), "spike": bool(z >= 2.0)}

    return {
        "version_id": "lsd-10-burst-v1.2.0",
        "hourly": hourly,
        "topic_channel_counts": dict(by_topic_channel),
        "spike_detected": any(item["spike"] for item in hourly.values()),
    }


def compute_completeness_proxy(argument: Mapping[str, Any]) -> float:
    """Compute AU completeness proxy from structural signals."""
    inference = str(argument.get("inference_text") or argument.get("au_inference") or "")
    supporting = _safe_json(argument.get("supporting_facts"), argument.get("supporting_facts", []))
    provenance = _safe_json(argument.get("provenance_links"), argument.get("provenance_links", []))
    member_ids = _safe_json(argument.get("member_au_ids"), argument.get("member_au_ids", []))

    has_conclusion = 1.0 if any(marker in inference.lower() for marker in ("therefore", "so ", "thus", "should", "because")) or len(inference) > 20 else 0.0
    has_premise = 1.0 if supporting else 0.0
    span_count = len(provenance) if isinstance(provenance, list) else 0
    member_count = len(member_ids) if isinstance(member_ids, list) else 0
    provenance_richness = min(1.0, (span_count + member_count) / 4.0)
    explicit_link = 1.0 if any(marker in inference.lower() for marker in ("because", "therefore", "implies", "so", "leads to")) else 0.0

    return round((has_conclusion + has_premise + provenance_richness + explicit_link) / 4.0, 4)


def mass_quantiles(values: Sequence[float]) -> Dict[str, float]:
    if not values:
        return {"p25": 0.0, "p50": 0.0, "p75": 0.0, "p90": 0.0}
    sorted_values = sorted(float(value) for value in values)

    def pick(q: float) -> float:
        index = min(len(sorted_values) - 1, max(0, int(math.ceil(q * len(sorted_values)) - 1)))
        return sorted_values[index]

    return {label: round(pick(q), 4) for label, q in (("p25", 0.25), ("p50", 0.50), ("p75", 0.75), ("p90", 0.90))}


def gini(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(max(0.0, float(v)) for v in values)
    total = sum(sorted_values)
    if total <= 0:
        return 0.0
    weighted = sum((idx + 1) * value for idx, value in enumerate(sorted_values))
    n = len(sorted_values)
    return round((2 * weighted) / (n * total) - (n + 1) / n, 4)


def topic_diagnostics(
    topics: Sequence[Mapping[str, Any]],
    topic_content_mass: Mapping[str, float],
    selected_topic_facts: Mapping[str, Sequence[Mapping[str, Any]]],
    selected_topic_args: Mapping[str, Sequence[Mapping[str, Any]]],
) -> Dict[str, Any]:
    pre_masses = {topic.get("topic_id", ""): float(topic_content_mass.get(topic.get("topic_id", ""), 0.0)) for topic in topics}
    selected_masses: Dict[str, float] = {}
    for topic in topics:
        tid = topic.get("topic_id", "")
        fact_mass = sum(float(item.get("centrality", 0.0) or 0.0) for item in selected_topic_facts.get(tid, []))
        arg_mass = sum(float(item.get("centrality", 0.0) or 0.0) for item in selected_topic_args.get(tid, []))
        selected_masses[tid] = fact_mass + arg_mass

    total_pre = sum(pre_masses.values())
    total_sel = sum(selected_masses.values())
    top_pre = sum(sorted(pre_masses.values(), reverse=True)[:3])
    top_sel = sum(sorted(selected_masses.values(), reverse=True)[:3])
    m_min = 0.01 * total_sel
    sel_values = list(selected_masses.values())

    return {
        "version_id": "lsd-6-v1.2.0",
        "dominance": {
            "top_3_canonical_mass_share": round(top_pre / total_pre, 4) if total_pre else 0.0,
            "top_3_selected_mass_share": round(top_sel / total_sel, 4) if total_sel else 0.0,
        },
        "micro_topic_rate": round(sum(1 for value in sel_values if value < m_min) / len(sel_values), 4) if sel_values else 0.0,
        "micro_topic_threshold": round(m_min, 4),
        "mass_distribution_quantiles": mass_quantiles(sel_values),
        "gini_coefficient": gini(sel_values),
        "pre_mass": pre_masses,
        "sel_mass": selected_masses,
        "pre_to_sel_ratio": {
            tid: round((selected_masses.get(tid, 0.0) / mass), 4) if mass else 0.0
            for tid, mass in pre_masses.items()
        },
        "relevance_formula_mode": scoring_formula_mode(),
    }


def merge_sensitivity(topics: Sequence[Mapping[str, Any]], base_margin_d: float) -> Dict[str, Any]:
    """Deterministic one-replicate topic-merge sensitivity placeholder."""
    ids = [str(topic.get("topic_id", "")) for topic in topics if topic.get("topic_id")]
    primary = set(ids)
    replicate = set(reversed(ids))
    union = primary | replicate
    jaccard = len(primary & replicate) / len(union) if union else 1.0
    return {
        "version_id": "lsd-6.1-merge-v1.2.0",
        "replicate_seed": 99,
        "mapping_stability": round(jaccard, 4),
        "score_deltas_per_frame": {
            "active": {
                "delta_d": 0.0,
                "baseline_d": round(float(base_margin_d), 4),
                "replicate_d": round(float(base_margin_d), 4),
            }
        },
    }


def evaluator_variance_from_scores(topic_scores: Mapping[str, Any], overall_scores: Mapping[str, float]) -> Dict[str, float]:
    reasoning = []
    coverage = []
    for value in topic_scores.values():
        if isinstance(value, Mapping) and "reasoning_iqr" in value:
            reasoning.append(float(value.get("reasoning_iqr") or 0.0))
        if isinstance(value, Mapping) and "coverage_iqr" in value:
            coverage.append(float(value.get("coverage_iqr") or 0.0))
    overall_values = list(float(v) for v in (overall_scores or {}).values())
    overall_iqr = 0.0
    if len(overall_values) >= 2:
        sorted_values = sorted(overall_values)
        q1 = sorted_values[int(0.25 * (len(sorted_values) - 1))]
        q3 = sorted_values[int(0.75 * (len(sorted_values) - 1))]
        overall_iqr = q3 - q1
    return {
        "reasoning_iqr_median": round(float(median(reasoning)), 4) if reasoning else 0.0,
        "coverage_iqr_median": round(float(median(coverage)), 4) if coverage else 0.0,
        "overall_iqr": round(float(overall_iqr), 4),
    }


def centrality_cap_effect(selection_diagnostics: Mapping[str, Any]) -> Dict[str, Any]:
    items_affected = 0
    pool_size = 0
    max_raw = 0.0
    max_cap = 0.0
    for diag in selection_diagnostics.values():
        pools = diag.get("pool_diagnostics") or diag.get("pools") or {}
        for pool in pools.values():
            pool_size += int(pool.get("pool_size", 0) or 0)
            affected = int(pool.get("items_affected_by_cap", 0) or 0)
            items_affected += affected
            max_raw = max(max_raw, float(pool.get("raw_centrality_max", pool.get("max_raw_centrality", 0.0)) or 0.0))
            max_cap = max(max_cap, float(pool.get("centrality_p95_cap", pool.get("p95_cap", 0.0)) or 0.0))
    return {
        "version_id": "lsd-19.9-v1.2.0",
        "items_affected_by_cap": items_affected,
        "max_raw_centrality": round(max_raw, 4),
        "cap_value": round(max_cap, 4),
        "fraction_of_pool_capped": round(items_affected / pool_size, 4) if pool_size else 0.0,
    }


def budget_adequacy(selection_diagnostics: Mapping[str, Any]) -> Dict[str, Any]:
    rows = {}
    for key, diag in selection_diagnostics.items():
        pools = diag.get("pool_diagnostics", {})
        mass_ratios = [
            float(pool.get("mass_ratio", 0.0) or 0.0)
            for pool in pools.values()
        ]
        rows[key] = {
            "mass_ratio": round(sum(mass_ratios) / len(mass_ratios), 4) if mass_ratios else 0.0,
            "top_k_centrality_coverage": diag.get("top_k_centrality_coverage", 0.0),
            "k": TOP_K_CENTRALITY,
        }
    return {"version_id": "lsd-11.6-v1.2.0", "topic_side": rows}


def rarity_utilization(selection_diagnostics: Mapping[str, Any]) -> Dict[str, Any]:
    rows = {}
    for key, diag in selection_diagnostics.items():
        pools = diag.get("pool_diagnostics", {})
        rarity_count = sum(int(pool.get("rarity_slice", 0) or 0) for pool in pools.values())
        selected = sum(int(pool.get("selected", 0) or 0) for pool in pools.values())
        rows[key] = {
            "rarity_count": rarity_count,
            "rarity_utilization_rate": round(rarity_count / selected, 4) if selected else 0.0,
            "rarity_avg_quality_proxy": diag.get("rarity_avg_quality_proxy", 0.0),
            "rarity_mass_contribution": diag.get("rarity_mass_contribution", 0.0),
            "majority_vs_rarity_centrality_comparison": diag.get(
                "majority_vs_rarity_centrality_comparison",
                {"majority_avg_centrality": 0.0, "rarity_avg_centrality": 0.0},
            ),
        }
    return {"version_id": "lsd-19.6-v1.2.0", "topic_side": rows}


def coverage_adequacy_trace(topic_scores: Mapping[str, Any]) -> Dict[str, Any]:
    distribution = Counter()
    for score in topic_scores.values():
        if isinstance(score, Mapping):
            for key, value in (score.get("rebuttal_type_distribution") or {}).items():
                distribution[key] += int(value)
    if not distribution:
        distribution.update({"EMPIRICAL": 0, "NORMATIVE": 0, "INFERENCE": 0, "SCOPE/DEFINITION": 0})
    return {"version_id": "lsd-15.1-v1.2.0", "rebuttal_type_distribution": dict(distribution)}


def component_sensitivity(factuality: float, reasoning: float, coverage: float) -> Dict[str, Any]:
    components = {
        "F": float(factuality),
        "Reason": float(reasoning),
        "Coverage": float(coverage),
    }
    base = compute_q_geomean(list(components.values()))
    drops = {}
    for name in components:
        remaining = [value for key, value in components.items() if key != name]
        next_q = compute_q_geomean(remaining)
        drops[f"drop_{name}"] = {
            "q": round(next_q, 4),
            "delta": round(next_q - base, 4),
        }
    return {
        "q_geo": round(base, 4),
        "q_arith": round(compute_q_arith(list(components.values())), 4),
        "drop_component": drops,
        "epsilon": Q_EPSILON,
    }


def insufficiency_sensitivity(topic_scores: Mapping[str, Any], actual_d: float) -> Dict[str, Any]:
    """Publish bounded sensitivity estimates for missing empirical evidence."""
    max_insuff = 0.0
    for score in topic_scores.values():
        if isinstance(score, Mapping):
            max_insuff = max(max_insuff, float(score.get("insufficiency_rate", 0.0) or 0.0))
    swing = round(0.1 * max_insuff, 4)
    return {
        "version_id": "lsd-13.1-v1.2.0",
        "D_if_insufficient_true": round(float(actual_d) + swing, 4),
        "D_if_insufficient_false": round(float(actual_d) - swing, 4),
        "delta_D_true": swing,
        "delta_D_false": -swing,
    }


def unselected_tail_summary(
    topic_facts: Mapping[str, Sequence[Mapping[str, Any]]],
    topic_arguments: Mapping[str, Sequence[Mapping[str, Any]]],
    selected_facts: Mapping[str, Sequence[Mapping[str, Any]]],
    selected_args: Mapping[str, Sequence[Mapping[str, Any]]],
) -> Dict[str, Any]:
    selected_fact_ids = {item.get("canon_fact_id") for items in selected_facts.values() for item in items}
    selected_arg_ids = {item.get("canon_arg_id") for items in selected_args.values() for item in items}
    result = {}
    topic_ids = sorted(set(topic_facts.keys()) | set(topic_arguments.keys()))
    for tid in topic_ids:
        rows = []
        for fact in topic_facts.get(tid, []):
            if fact.get("canon_fact_id") not in selected_fact_ids:
                rows.append({
                    "id": fact.get("canon_fact_id"),
                    "type": "fact",
                    "side": fact.get("side"),
                    "text": fact.get("canon_fact_text", "")[:180],
                    "centrality": float(fact.get("centrality", 0.0) or 0.0),
                    "reason_for_exclusion": "budget cap",
                })
        for arg in topic_arguments.get(tid, []):
            if arg.get("canon_arg_id") not in selected_arg_ids:
                rows.append({
                    "id": arg.get("canon_arg_id"),
                    "type": "argument",
                    "side": arg.get("side"),
                    "text": arg.get("inference_text", "")[:180],
                    "centrality": float(arg.get("centrality", 0.0) or 0.0),
                    "reason_for_exclusion": "budget cap or rarity slice not picked",
                })
        rows.sort(key=lambda item: item["centrality"], reverse=True)
        result[tid] = {"count": len(rows), "top_unselected": rows[:3]}
    return {"version_id": "lsd-20-tail-v1.2.0", "topics": result}


def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"
