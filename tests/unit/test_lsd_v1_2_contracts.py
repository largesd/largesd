import json
import math
import os
import sys
import tempfile

from backend.lsd_v1_2 import (
    Q_EPSILON,
    compute_q_arith,
    compute_q_geomean,
    compute_selection_score,
    compute_topic_relevance_from_masses,
    formula_registry,
)
from backend.selection_engine import SelectionEngine, SELECTION_WEIGHTS
from backend.scoring_engine import ScoringEngine
from backend.database_v3 import Database
from backend.job_queue import JobQueue, JobStatus
from backend.llm_client import LLMClient
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


def test_llm_client_runtime_metadata_uses_instantiated_provider_not_env():
    client = LLMClient(provider="mock")
    original_model = os.environ.get("OPENROUTER_MODEL")
    os.environ["OPENROUTER_MODEL"] = "env-only-model"
    try:
        client.provider_name = "openrouter"
        client.provider = type("StubProvider", (), {"model": "server-runtime-model"})()
        metadata = client.get_runtime_metadata()
        assert metadata["provider"] == "openrouter"
        assert metadata["configured_model"] == "server-runtime-model"
        assert metadata["num_judges"] == client.num_judges
    finally:
        if original_model is None:
            os.environ.pop("OPENROUTER_MODEL", None)
        else:
            os.environ["OPENROUTER_MODEL"] = original_model


def test_job_queue_claims_only_matching_runtime_profile_once():
    db = Database(os.path.join(tempfile.mkdtemp(), "jobs.db"))
    queue = JobQueue(db)

    profile_a_job = queue.create_job(
        "snapshot",
        {"debate_id": "debate_a"},
        runtime_profile_id="runtime-a",
    )
    profile_b_job = queue.create_job(
        "verify",
        {"snapshot_id": "snapshot_b"},
        runtime_profile_id="runtime-b",
    )

    queued_a = queue.list_jobs(status=JobStatus.QUEUED, runtime_profile_id="runtime-a")
    queued_b = queue.list_jobs(status=JobStatus.QUEUED, runtime_profile_id="runtime-b")

    assert [job.job_id for job in queued_a] == [profile_a_job]
    assert [job.job_id for job in queued_b] == [profile_b_job]

    assert queue.start_job(profile_a_job, runtime_profile_id="runtime-b") is False
    assert queue.start_job(profile_a_job, runtime_profile_id="runtime-a") is True
    assert queue.start_job(profile_a_job, runtime_profile_id="runtime-a") is False

    claimed_job = queue.get_job(profile_a_job)
    assert claimed_job is not None
    assert claimed_job.status == JobStatus.RUNNING
    assert claimed_job.runtime_profile_id == "runtime-a"


def test_rebuttal_types_from_judges():
    from llm_client import MockLLMProvider
    provider = MockLLMProvider(seed=42)
    response = provider._mock_coverage_response()
    data = json.loads(response.content)
    assert data["rebuttal_type"] in ("EMPIRICAL", "NORMATIVE", "INFERENCE", "SCOPE/DEFINITION")


def test_normative_symmetry_contract():
    engine = ScoringEngine(num_judges=1, num_replicates=0)
    selected_facts = {
        "t1": [
            {"canon_fact_id": "cf_1", "fact_type": "normative", "canon_fact_text": "Government should regulate AI for safety.", "side": "FOR"},
        ]
    }
    result = engine.run_symmetry_tests(selected_facts, frame_values=["safety"])
    assert result["version_id"] == "lsd-14-v1.2.0"
    assert result["test_count"] == 1
    assert "max_delta" in result
    assert "interpretation" in result


def test_v15_null_edge_cases():
    """Per LSD_FactCheck_v1_5_1 §8: empty and all-insufficient aggregation."""
    engine = ScoringEngine(num_judges=1, num_replicates=0)

    # No empirical premises → all None
    empty = engine.compute_factuality_diagnostics([])
    assert empty["f_all"] is None
    assert empty["f_supported_only"] is None
    assert empty["insufficiency_rate"] is None

    # All INSUFFICIENT → f_all=0.5, f_supported_only=None, insufficiency_rate=1.0
    all_insuff = engine.compute_factuality_diagnostics([
        {"p_true": 0.5}, {"p_true": 0.5}
    ])
    assert all_insuff["f_all"] == 0.5
    assert all_insuff["f_supported_only"] is None
    assert all_insuff["insufficiency_rate"] == 1.0

    # Mixed → standard means, f_supported_only over decisive only
    mixed = engine.compute_factuality_diagnostics([
        {"p_true": 1.0}, {"p_true": 0.0}, {"p_true": 0.5}
    ])
    assert mixed["f_all"] == 0.5
    assert mixed["f_supported_only"] == 0.5
    assert mixed["insufficiency_rate"] == 1 / 3


def test_v15_deterministic_ternary_p_values():
    """v1.5 bridge skill returns p ∈ {1.0, 0.0, 0.5}."""
    from skills.fact_checking.v15_skill import V15FactCheckingSkill
    skill = V15FactCheckingSkill(mode="OFFLINE")
    result = skill.check_fact("Test claim.")
    assert result.factuality_score in (0.0, 0.5, 1.0)
    assert result.diagnostics["v15_p"] in (0.0, 0.5, 1.0)
    assert result.diagnostics["v15_status"] in ("SUPPORTED", "REFUTED", "INSUFFICIENT")


def test_api_route_contracts_are_registered():
    os.environ["DEBATE_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "contracts.db")
    from app_v3 import app

    routes = {rule.rule for rule in app.url_map.iter_rules()}
    expected = {
        "/api/debate/snapshot",
        "/api/debate/snapshot-jobs/<job_id>",
        "/api/debate/topics",
        "/api/debate/verdict",
        "/api/debate/audits",
        "/api/debate/decision-dossier",
        "/api/debate/<debate_id>/appeals",
        "/api/debate/<debate_id>/appeals/mine",
        "/api/admin/appeals",
        "/api/admin/appeals/<appeal_id>/resolve",
        "/api/admin/snapshots/<snapshot_id>/verify",
        "/api/audit/export/<snapshot_id>",
        "/api/governance/frame-cadence",
        "/api/governance/emergency-override",
        "/api/admin/snapshots/<snapshot_id>/mark-incident",
        "/api/debate/<debate_id>/frame-petitions",
        "/api/admin/frame-petitions/<petition_id>/accept",
        "/api/admin/frame-petitions/<petition_id>/reject",
        "/api/debate/<debate_id>/incidents",
        "/api/governance/judge-pool/composition",
        "/api/governance/judge-pool/rotation-policy",
        "/api/governance/judge-pool/calibration-protocol",
        "/api/governance/judge-pool/conflict-of-interest",
    }
    assert expected.issubset(routes)
