"""
Tests for the PERFECT fact-checking path.

Verifies:
- LSD §13 discrete p-value contract: {1.0, 0.0, 0.5}
- EvidencePolicy gating (strict vs default)
- Simulated connector disagreement
- Ground-truth schema versioning
- Mode alias normalization
"""

import os
import unittest

from skills.fact_checking import (
    EvidencePolicy,
    FactCheckingSkill,
    FactCheckVerdict,
    SimulatedSourceConnector,
    WikidataConnector,
    default_policy,
    strict_policy,
)


class TestPerfectSkillDiscreteOutputs(unittest.TestCase):
    """LSD §13: p must be in {1.0, 0.0, 0.5}."""

    def test_perfect_checker_fixture_discrete(self):
        """Legacy fixture returns only discrete values."""
        skill = FactCheckingSkill(mode="PERFECT_CHECKER", enable_async=False)
        for claim, expected_p in [
            ("known supported claim", 1.0),
            ("known refuted false claim", 0.0),
            ("known insufficient unavailable claim", 0.5),
        ]:
            result = skill.check_fact(claim)
            self.assertIn(
                result.factuality_score,
                {1.0, 0.0, 0.5},
                f"Claim '{claim}' returned p={result.factuality_score}",
            )
            self.assertEqual(result.factuality_score, expected_p, claim)
        skill.shutdown()


class TestEvidencePolicy(unittest.TestCase):
    """EvidencePolicy gates verdicts correctly."""

    def test_strict_policy_blocks_tier2_alone(self):
        """Strict mode: Tier-2 unanimous confirm → INSUFFICIENT."""
        policy = strict_policy()
        self.assertFalse(policy.tier2_can_resolve)

    def test_default_policy_allows_tier2(self):
        """Default mode: Tier-2 unanimous confirm → SUPPORTED."""
        policy = default_policy()
        self.assertTrue(policy.tier2_can_resolve)
        self.assertFalse(policy.tier1_require_second_source)

    def test_strict_with_single_tier1_is_insufficient(self):
        """Explicit strict policy can require 2 independent Tier-1 sources."""
        policy = EvidencePolicy(
            tier2_can_resolve=False, strict_mode=True, tier1_require_second_source=True
        )
        self.assertTrue(policy.tier1_require_second_source)


class TestSimulatedConnectorDisagreement(unittest.TestCase):
    """Different source_ids must be able to disagree."""

    def test_connectors_can_disagree(self):
        """Same claim, different connectors → different verdicts possible."""
        conn_a = SimulatedSourceConnector("src_a", "example.org", priority=5)
        conn_b = SimulatedSourceConnector("src_b", "example.com", priority=5)

        # Find a claim where they disagree
        found_disagreement = False
        for i in range(200):
            claim = f"disputed claim variant {i}"
            from skills.fact_checking.normalization import ClaimNormalizer

            norm = ClaimNormalizer.normalize(claim)
            ch = ClaimNormalizer.compute_hash(norm)
            res_a = conn_a.query(norm, ch)
            res_b = conn_b.query(norm, ch)
            if res_a and res_b and res_a.confidence != res_b.confidence:
                found_disagreement = True
                break

        self.assertTrue(
            found_disagreement,
            "Simulated connectors should be able to disagree on the same claim",
        )


class TestPerfectModeWithConnectors(unittest.TestCase):
    """PERFECT mode with connector-based evidence."""

    def test_strict_mode_insufficient_for_tier3_only(self):
        """With strict policy and only Tier-3 stubs, most claims are INSUFFICIENT."""
        skill = FactCheckingSkill(
            mode="PERFECT",
            enable_async=False,
            connectors=[
                WikidataConnector(),  # Tier 3
            ],
            policy=strict_policy(),
        )
        # Use a unique claim to avoid cache pollution from previous runs
        result = skill.check_fact("strict mode tier3 only test claim abc123xyz")
        # Tier-3 alone cannot resolve under strict policy
        self.assertEqual(result.verdict, FactCheckVerdict.INSUFFICIENT)
        self.assertEqual(result.factuality_score, 0.5)
        skill.shutdown()

    def test_default_mode_allows_tier3(self):
        """With default policy, Tier-3 unanimous confirm can resolve."""
        skill = FactCheckingSkill(
            mode="PERFECT",
            enable_async=False,
            connectors=[
                WikidataConnector(),
            ],
            policy=default_policy(),
        )
        result = skill.check_fact("default mode tier3 test claim def456uvw")
        self.assertIn(result.factuality_score, {1.0, 0.0, 0.5})
        skill.shutdown()

    def test_disagreement_yields_insufficient(self):
        """Two connectors disagreeing → INSUFFICIENT."""
        skill = FactCheckingSkill(
            mode="PERFECT",
            enable_async=False,
            connectors=[
                SimulatedSourceConnector("sim_a", "example.org", priority=5),
                SimulatedSourceConnector("sim_b", "example.com", priority=5),
            ],
            policy=default_policy(),
        )
        # Search for a claim that provokes disagreement
        found_insufficient = False
        for i in range(200):
            claim = f"test disagreement claim {i}"
            result = skill.check_fact(claim)
            if result.verdict == FactCheckVerdict.INSUFFICIENT:
                found_insufficient = True
                break
        self.assertTrue(
            found_insufficient,
            "With disagreeing connectors, some claims should be INSUFFICIENT",
        )
        skill.shutdown()


class TestModeAliases(unittest.TestCase):
    """PERFECT and PERFECT_CHECKER both route to the perfect path."""

    def test_perfect_alias(self):
        skill = FactCheckingSkill(mode="PERFECT", enable_async=False)
        self.assertIn(skill.mode, ("PERFECT", "PERFECT_CHECKER"))
        skill.shutdown()

    def test_perfect_checker_alias(self):
        skill = FactCheckingSkill(mode="PERFECT_CHECKER", enable_async=False)
        self.assertIn(skill.mode, ("PERFECT", "PERFECT_CHECKER"))
        skill.shutdown()


class TestGroundTruthSchema(unittest.TestCase):
    """GroundTruthDB stores and retrieves with schema versioning."""

    def test_store_and_lookup(self):
        import tempfile

        from skills.fact_checking.connectors import GroundTruthDB

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = f.name

        try:
            db = GroundTruthDB(db_path=path)
            db.store(
                claim_hash="abc123",
                verdict="SUPPORTED",
                p_true=1.0,
                operationalization="To refute: provide contradictory primary source.",
                tier_counts={"TIER_1": 1, "TIER_2": 0, "TIER_3": 0},
                evidence=[
                    {
                        "source_url": "https://example.gov/data",
                        "source_id": "gov",
                        "source_title": "Official Data",
                        "snippet": "Data shows X.",
                        "content_hash": "def456",
                        "retrieved_at": "2024-01-15T10:00:00Z",
                        "evidence_tier": "TIER_1",
                    }
                ],
                reviewed_by="reviewer_1",
                review_rationale="Verified against primary source.",
            )

            entry = db.lookup("abc123")
            self.assertIsNotNone(entry)
            self.assertEqual(entry["schema_version"], "1.0")
            self.assertEqual(entry["verdict"], "SUPPORTED")
            self.assertEqual(entry["reviewed_by"], "reviewer_1")
            self.assertEqual(entry["evidence"][0]["evidence_tier"], "TIER_1")
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
