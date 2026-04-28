import math
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from lsd_v1_2 import (
    Q_EPSILON,
    compute_q_arith,
    compute_q_geomean,
    compute_selection_score,
    compute_topic_relevance_from_masses,
    formula_registry,
)
from selection_engine import SelectionEngine, SELECTION_WEIGHTS
from scoring_engine import ScoringEngine
from skills.fact_checking import FactCheckingSkill


def test_selection_score_decomposition_fixture():
    centrality = 2.0
    distinct_support = 3
    quality_proxy = 0.75
    expected = (
        SELECTION_WEIGHTS["w1"] * centrality
        + SELECTION_WEIGHTS["w2"] * math.log1p(distinct_support)
        + SELECTION_WEIGHTS["w3"] * quality_proxy
    )
    assert compute_selection_score(centrality, distinct_support, quality_proxy) == expected


def test_centrality_cap_fixture():
    items = [
        {"canon_fact_id": f"cf_{idx}", "referenced_by_au_ids": list(range(refs))}
        for idx, refs in enumerate([0, 1, 2, 3, 100])
    ]
    centrality, meta = SelectionEngine._compute_centrality(items, "fixture", 95.0)
    assert meta["items_affected_by_cap"] == 1
    assert centrality["cf_4"] == meta["p95_cap"]
    assert meta["raw_centrality_max"] > meta["p95_cap"]


def test_relevance_sqrt_and_log_fixtures():
    masses = {"t1": 1.0, "t2": 4.0}
    sqrt_rel = compute_topic_relevance_from_masses(masses, "v1_2_sqrt")
    assert round(sqrt_rel["t1"], 6) == round(1 / 3, 6)
    assert round(sqrt_rel["t2"], 6) == round(2 / 3, 6)

    log_rel = compute_topic_relevance_from_masses(masses, "v1_2_log")
    denom = math.log1p(1.0) + math.log1p(4.0)
    assert round(log_rel["t1"], 6) == round(math.log1p(1.0) / denom, 6)
    assert round(log_rel["t2"], 6) == round(math.log1p(4.0) / denom, 6)


def test_q_geomean_arith_and_drop_component_fixture():
    components = [0.8, 0.6, 0.4]
    assert round(compute_q_geomean(components), 6) == round((0.8 * 0.6 * 0.4) ** (1 / 3), 6)
    assert compute_q_arith(components) == sum(components) / 3
    assert round(compute_q_geomean([0.0, 0.6, 0.4]), 6) == round((Q_EPSILON * 0.6 * 0.4) ** (1 / 3), 6)


def test_verdict_distribution_confidence_fixture():
    engine = ScoringEngine(num_judges=1, num_replicates=0)
    replicates = [
        type("R", (), {"overall_scores": {"FOR": 0.7, "AGAINST": 0.4}, "side_order": ["FOR", "AGAINST"]})(),
        type("R", (), {"overall_scores": {"FOR": 0.6, "AGAINST": 0.5}, "side_order": ["FOR", "AGAINST"]})(),
        type("R", (), {"overall_scores": {"FOR": 0.2, "AGAINST": 0.5}, "side_order": ["FOR", "AGAINST"]})(),
    ]
    verdict = engine.compute_verdict(replicates, side_order=["FOR", "AGAINST"])
    assert verdict["d_distribution"] == [0.3, 0.1, -0.3]
    assert verdict["confidence"] == 0.67


def test_perfect_checker_discrete_outputs():
    checker = FactCheckingSkill(mode="perfect_checker", enable_async=False)
    assert checker.check_fact("Known supported claim").factuality_score == 1.0
    assert checker.check_fact("Known refuted false claim").factuality_score == 0.0
    assert checker.check_fact("Known insufficient unavailable claim").factuality_score == 0.5


def test_formula_registry_exposes_feature_flags_and_versions():
    registry = formula_registry()
    assert registry["lsd_version"] == "1.2.0"
    assert registry["selection"]["version_id"] == "lsd-11-v1.2.0"
    assert "FACT_CHECKER_MODE" in registry["feature_flags"]


def test_api_route_contracts_are_registered():
    os.environ["DEBATE_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "contracts.db")
    from app_v3 import app

    routes = {rule.rule for rule in app.url_map.iter_rules()}
    expected = {
        "/api/debate/snapshot",
        "/api/debate/topics",
        "/api/debate/verdict",
        "/api/debate/audits",
        "/api/debate/decision-dossier",
        "/api/governance/frames",
        "/api/governance/frame-cadence",
        "/api/governance/emergency-override",
        "/api/admin/snapshots/<snapshot_id>/mark-incident",
        "/api/debate/<debate_id>/frame-petitions",
        "/api/admin/frame-petitions/<petition_id>/accept",
        "/api/admin/frame-petitions/<petition_id>/reject",
        "/api/debate/<debate_id>/incidents",
    }
    assert expected.issubset(routes)
