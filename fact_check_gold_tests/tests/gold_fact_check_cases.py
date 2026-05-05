"""Gold corpus for fact-check adjudication regression tests.

These cases are intentionally deterministic. The expected verdict is measured
against the fixture evidence in ``source_specs``, not against the live web. This
lets connector and policy changes be compared against the same fixed cases.
"""

from __future__ import annotations

from typing import Any, Dict, List

GoldCase = Dict[str, Any]

GOLD_FACT_CHECK_CASES: List[GoldCase] = [
    {
        "id": "S001",
        "claim": "At standard atmospheric pressure, pure water boils at 100 degrees Celsius.",
        "expected_verdict": "SUPPORTED",
        "expected_score": 1.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "supported",
            "scoped"
        ],
        "notes": "Scope limits the claim to standard pressure and pure water.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            }
        ]
    },
    {
        "id": "S002",
        "claim": "Earth orbits the Sun.",
        "expected_verdict": "SUPPORTED",
        "expected_score": 1.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "supported"
        ],
        "notes": "Simple stable astronomy fact.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            }
        ]
    },
    {
        "id": "S003",
        "claim": "The chemical formula for carbon dioxide is CO2.",
        "expected_verdict": "SUPPORTED",
        "expected_score": 1.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "supported",
            "definitional"
        ],
        "notes": "Stable chemical formula claim.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            }
        ]
    },
    {
        "id": "S004",
        "claim": "Canada has ten provinces.",
        "expected_verdict": "SUPPORTED",
        "expected_score": 1.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "supported",
            "geographic"
        ],
        "notes": "Stable administrative geography claim.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            }
        ]
    },
    {
        "id": "S005",
        "claim": "Tokyo is the capital city of Japan.",
        "expected_verdict": "SUPPORTED",
        "expected_score": 1.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "supported",
            "geographic"
        ],
        "notes": "Stable capital-city claim.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            }
        ]
    },
    {
        "id": "S006",
        "claim": "HTTP status code 404 means Not Found.",
        "expected_verdict": "SUPPORTED",
        "expected_score": 1.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "supported",
            "technical",
            "definitional"
        ],
        "notes": "Stable protocol definition.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            }
        ]
    },
    {
        "id": "S007",
        "claim": "A right triangle satisfies the Pythagorean theorem.",
        "expected_verdict": "SUPPORTED",
        "expected_score": 1.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "supported",
            "mathematical",
            "scoped"
        ],
        "notes": "Scoped to right triangles.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            }
        ]
    },
    {
        "id": "S008",
        "claim": "Solid-state drives can store data using NAND flash memory.",
        "expected_verdict": "SUPPORTED",
        "expected_score": 1.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "supported",
            "technical"
        ],
        "notes": "Technical hardware claim with fixture evidence.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            }
        ]
    },
    {
        "id": "S009",
        "claim": "Vancouver is in British Columbia, Canada.",
        "expected_verdict": "SUPPORTED",
        "expected_score": 1.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "supported",
            "geographic"
        ],
        "notes": "Stable location claim.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            }
        ]
    },
    {
        "id": "S010",
        "claim": "A byte is commonly defined as eight bits.",
        "expected_verdict": "SUPPORTED",
        "expected_score": 1.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "supported",
            "technical",
            "scoped"
        ],
        "notes": "Includes 'commonly' to avoid historical edge cases.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            }
        ]
    },
    {
        "id": "S011",
        "claim": "The SI unit of electric current is the ampere.",
        "expected_verdict": "SUPPORTED",
        "expected_score": 1.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "supported",
            "definitional"
        ],
        "notes": "Stable SI-unit definition.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            }
        ]
    },
    {
        "id": "S012",
        "claim": "HTML is a markup language used to structure web pages.",
        "expected_verdict": "SUPPORTED",
        "expected_score": 1.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "supported",
            "technical",
            "definitional"
        ],
        "notes": "Stable web technology definition.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            }
        ]
    },
    {
        "id": "S013",
        "claim": "The Moon is a natural satellite of Earth.",
        "expected_verdict": "SUPPORTED",
        "expected_score": 1.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "supported",
            "astronomy"
        ],
        "notes": "Stable astronomy fact.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            }
        ]
    },
    {
        "id": "S014",
        "claim": "The Pacific Ocean borders British Columbia.",
        "expected_verdict": "SUPPORTED",
        "expected_score": 1.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "supported",
            "geographic"
        ],
        "notes": "Stable geography claim.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            }
        ]
    },
    {
        "id": "S015",
        "claim": "In base ten, the number 101 is one hundred one.",
        "expected_verdict": "SUPPORTED",
        "expected_score": 1.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "supported",
            "mathematical",
            "scoped"
        ],
        "notes": "Base is explicitly scoped.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            }
        ]
    },
    {
        "id": "R001",
        "claim": "Earth is the fourth planet from the Sun.",
        "expected_verdict": "REFUTED",
        "expected_score": 0.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "refuted"
        ],
        "notes": "Contradicts stable planetary order.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    },
    {
        "id": "R002",
        "claim": "Canada has fifty-two states.",
        "expected_verdict": "REFUTED",
        "expected_score": 0.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "refuted",
            "geographic"
        ],
        "notes": "Confuses Canada with U.S.-style state count.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    },
    {
        "id": "R003",
        "claim": "The chemical formula for water is CO3.",
        "expected_verdict": "REFUTED",
        "expected_score": 0.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "refuted",
            "definitional"
        ],
        "notes": "Incorrect chemical formula.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    },
    {
        "id": "R004",
        "claim": "Vancouver is the capital city of Canada.",
        "expected_verdict": "REFUTED",
        "expected_score": 0.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "refuted",
            "geographic"
        ],
        "notes": "Wrong capital-city claim.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    },
    {
        "id": "R005",
        "claim": "NAND flash storage requires spinning mechanical platters to retain data.",
        "expected_verdict": "REFUTED",
        "expected_score": 0.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "refuted",
            "technical"
        ],
        "notes": "Incorrect hardware mechanism.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    },
    {
        "id": "R006",
        "claim": "HTTP status code 200 means Not Found.",
        "expected_verdict": "REFUTED",
        "expected_score": 0.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "refuted",
            "technical",
            "definitional"
        ],
        "notes": "Incorrect protocol mapping.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    },
    {
        "id": "R007",
        "claim": "A byte is commonly defined as ten bits.",
        "expected_verdict": "REFUTED",
        "expected_score": 0.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "refuted",
            "technical",
            "scoped"
        ],
        "notes": "Common modern definition is not ten bits.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    },
    {
        "id": "R008",
        "claim": "Mount Everest is in the Andes mountain range.",
        "expected_verdict": "REFUTED",
        "expected_score": 0.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "refuted",
            "geographic"
        ],
        "notes": "Incorrect mountain range.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    },
    {
        "id": "R009",
        "claim": "HTML is primarily a relational database query language.",
        "expected_verdict": "REFUTED",
        "expected_score": 0.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "refuted",
            "technical",
            "definitional"
        ],
        "notes": "Confuses HTML with SQL-like purpose.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    },
    {
        "id": "R010",
        "claim": "The SI unit of electric current is the volt.",
        "expected_verdict": "REFUTED",
        "expected_score": 0.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "refuted",
            "definitional"
        ],
        "notes": "Volt is electric potential difference, not current.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    },
    {
        "id": "R011",
        "claim": "At standard atmospheric pressure, pure water boils at 25 degrees Celsius.",
        "expected_verdict": "REFUTED",
        "expected_score": 0.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "refuted",
            "scoped"
        ],
        "notes": "Scope is clear enough to refute.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    },
    {
        "id": "R012",
        "claim": "Tokyo is the capital city of South Korea.",
        "expected_verdict": "REFUTED",
        "expected_score": 0.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "refuted",
            "geographic"
        ],
        "notes": "Wrong country/capital relation.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    },
    {
        "id": "R013",
        "claim": "The Moon orbits Mars.",
        "expected_verdict": "REFUTED",
        "expected_score": 0.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "refuted",
            "astronomy"
        ],
        "notes": "Incorrect orbital relation.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    },
    {
        "id": "R014",
        "claim": "Python lists are immutable sequences.",
        "expected_verdict": "REFUTED",
        "expected_score": 0.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "refuted",
            "technical",
            "definitional"
        ],
        "notes": "Python lists are mutable; tuples are immutable.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    },
    {
        "id": "R015",
        "claim": "Carbon dioxide is written chemically as O2.",
        "expected_verdict": "REFUTED",
        "expected_score": 0.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "refuted",
            "definitional"
        ],
        "notes": "Incorrect formula; O2 is oxygen molecule.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    },
    {
        "id": "I001",
        "claim": "The new campus policy significantly improved student morale.",
        "expected_verdict": "INSUFFICIENT",
        "expected_score": 0.5,
        "source_types": [
            "NO_RELEVANT_SOURCE"
        ],
        "edge_cases": [
            "insufficient",
            "subjective",
            "vague"
        ],
        "notes": "Requires survey definition and evidence not supplied.",
        "source_specs": [
            {
                "source_id": "silent_1",
                "tier": "TIER_1",
                "confidence": "SILENT",
                "excerpt": "Fixture source is silent for this claim."
            }
        ]
    },
    {
        "id": "I002",
        "claim": "This debate system is unbiased in every possible scenario.",
        "expected_verdict": "INSUFFICIENT",
        "expected_score": 0.5,
        "source_types": [
            "NO_RELEVANT_SOURCE"
        ],
        "edge_cases": [
            "insufficient",
            "absolute",
            "audit_required"
        ],
        "notes": "Universal fairness claim needs a formal audit and scope.",
        "source_specs": [
            {
                "source_id": "silent_1",
                "tier": "TIER_1",
                "confidence": "SILENT",
                "excerpt": "Fixture source is silent for this claim."
            }
        ]
    },
    {
        "id": "I003",
        "claim": "A private company roadmap shows that the product will launch next quarter.",
        "expected_verdict": "INSUFFICIENT",
        "expected_score": 0.5,
        "source_types": [
            "NO_RELEVANT_SOURCE"
        ],
        "edge_cases": [
            "insufficient",
            "future",
            "private_source"
        ],
        "notes": "Future/private roadmap claim cannot be resolved by public fixture sources.",
        "source_specs": [
            {
                "source_id": "silent_1",
                "tier": "TIER_1",
                "confidence": "SILENT",
                "excerpt": "Fixture source is silent for this claim."
            }
        ]
    },
    {
        "id": "I004",
        "claim": "Most engineers prefer VHDL over Verilog.",
        "expected_verdict": "INSUFFICIENT",
        "expected_score": 0.5,
        "source_types": [
            "TIER_2_SECONDARY"
        ],
        "edge_cases": [
            "insufficient",
            "survey_required",
            "vague_population"
        ],
        "notes": "Requires scoped population and reliable survey data.",
        "source_specs": [
            {
                "source_id": "secondary_1",
                "tier": "TIER_2",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "secondary_2",
                "tier": "TIER_2",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            }
        ]
    },
    {
        "id": "I005",
        "claim": "The uploaded README proves the entire project is production-ready.",
        "expected_verdict": "INSUFFICIENT",
        "expected_score": 0.5,
        "source_types": [
            "NO_RELEVANT_SOURCE"
        ],
        "edge_cases": [
            "insufficient",
            "scope_overreach"
        ],
        "notes": "A README alone cannot establish production readiness.",
        "source_specs": [
            {
                "source_id": "silent_1",
                "tier": "TIER_1",
                "confidence": "SILENT",
                "excerpt": "Fixture source is silent for this claim."
            }
        ]
    },
    {
        "id": "I006",
        "claim": "A single anonymous forum post proves that the claim is false.",
        "expected_verdict": "INSUFFICIENT",
        "expected_score": 0.5,
        "source_types": [
            "TIER_3_CONTEXTUAL"
        ],
        "edge_cases": [
            "insufficient",
            "weak_source"
        ],
        "notes": "Low-authority source should not settle the verdict.",
        "source_specs": [
            {
                "source_id": "forum_1",
                "tier": "TIER_3",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    },
    {
        "id": "I007",
        "claim": "Two equally authoritative sources disagree about the reported number.",
        "expected_verdict": "INSUFFICIENT",
        "expected_score": 0.5,
        "source_types": [
            "CONFLICTING_TIER_1"
        ],
        "edge_cases": [
            "insufficient",
            "conflict"
        ],
        "notes": "Tier-1 disagreement should not be forced into a verdict.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    },
    {
        "id": "I008",
        "claim": "The statement is accurate because everyone knows it is true.",
        "expected_verdict": "INSUFFICIENT",
        "expected_score": 0.5,
        "source_types": [
            "NO_RELEVANT_SOURCE"
        ],
        "edge_cases": [
            "insufficient",
            "appeal_to_common_knowledge"
        ],
        "notes": "No source evidence is provided.",
        "source_specs": [
            {
                "source_id": "silent_1",
                "tier": "TIER_1",
                "confidence": "SILENT",
                "excerpt": "Fixture source is silent for this claim."
            }
        ]
    },
    {
        "id": "I009",
        "claim": "The policy caused a 35% improvement, but no baseline or metric is specified.",
        "expected_verdict": "INSUFFICIENT",
        "expected_score": 0.5,
        "source_types": [
            "NO_RELEVANT_SOURCE"
        ],
        "edge_cases": [
            "insufficient",
            "statistical",
            "missing_denominator"
        ],
        "notes": "Statistical claim lacks operationalization.",
        "source_specs": [
            {
                "source_id": "silent_1",
                "tier": "TIER_1",
                "confidence": "SILENT",
                "excerpt": "Fixture source is silent for this claim."
            }
        ]
    },
    {
        "id": "I010",
        "claim": "The best programming language for all engineering projects is Python.",
        "expected_verdict": "INSUFFICIENT",
        "expected_score": 0.5,
        "source_types": [
            "NO_RELEVANT_SOURCE"
        ],
        "edge_cases": [
            "insufficient",
            "normative",
            "absolute"
        ],
        "notes": "Normative superlative cannot be fact-checked directly.",
        "source_specs": [
            {
                "source_id": "silent_1",
                "tier": "TIER_1",
                "confidence": "SILENT",
                "excerpt": "Fixture source is silent for this claim."
            }
        ]
    },
    {
        "id": "I011",
        "claim": "The source confirms the claim, but it is only a low-authority blog mirror.",
        "expected_verdict": "INSUFFICIENT",
        "expected_score": 0.5,
        "source_types": [
            "TIER_3_CONTEXTUAL"
        ],
        "edge_cases": [
            "insufficient",
            "weak_source"
        ],
        "notes": "Strict policy should not resolve from weak source alone.",
        "source_specs": [
            {
                "source_id": "blog_1",
                "tier": "TIER_3",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            }
        ]
    },
    {
        "id": "I012",
        "claim": "The claim is true in one jurisdiction but the jurisdiction is not specified.",
        "expected_verdict": "INSUFFICIENT",
        "expected_score": 0.5,
        "source_types": [
            "NO_RELEVANT_SOURCE"
        ],
        "edge_cases": [
            "insufficient",
            "scoped",
            "missing_jurisdiction"
        ],
        "notes": "Scope ambiguity should block adjudication.",
        "source_specs": [
            {
                "source_id": "silent_1",
                "tier": "TIER_1",
                "confidence": "SILENT",
                "excerpt": "Fixture source is silent for this claim."
            }
        ]
    },
    {
        "id": "I013",
        "claim": "The number changed recently and the claim gives no date.",
        "expected_verdict": "INSUFFICIENT",
        "expected_score": 0.5,
        "source_types": [
            "NO_RELEVANT_SOURCE"
        ],
        "edge_cases": [
            "insufficient",
            "temporal",
            "missing_date"
        ],
        "notes": "Temporal claims need as-of date or fresh evidence.",
        "source_specs": [
            {
                "source_id": "silent_1",
                "tier": "TIER_1",
                "confidence": "SILENT",
                "excerpt": "Fixture source is silent for this claim."
            }
        ]
    },
    {
        "id": "I014",
        "claim": "A compound claim contains one supported subclaim and one unresolved subclaim.",
        "expected_verdict": "INSUFFICIENT",
        "expected_score": 0.5,
        "source_types": [
            "PARTIAL_EVIDENCE"
        ],
        "edge_cases": [
            "insufficient",
            "compound",
            "partial_support"
        ],
        "notes": "Partial support is not enough to mark whole compound true.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Evidence confirms only one subclaim, not the full compound."
            },
            {
                "source_id": "silent_1",
                "tier": "TIER_1",
                "confidence": "SILENT",
                "excerpt": "No source for remaining subclaim."
            }
        ]
    },
    {
        "id": "T001",
        "claim": "As of 2006, Pluto was reclassified as a dwarf planet by the International Astronomical Union.",
        "expected_verdict": "SUPPORTED",
        "expected_score": 1.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "supported",
            "temporal"
        ],
        "notes": "As-of date is explicit.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            }
        ]
    },
    {
        "id": "T002",
        "claim": "In 2021, the Tokyo 2020 Summer Olympics were held.",
        "expected_verdict": "SUPPORTED",
        "expected_score": 1.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "supported",
            "temporal"
        ],
        "notes": "Name-year and actual event year are distinguished.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            }
        ]
    },
    {
        "id": "T003",
        "claim": "In 2020, the Tokyo 2020 Summer Olympics were held as scheduled in Tokyo.",
        "expected_verdict": "REFUTED",
        "expected_score": 0.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "refuted",
            "temporal"
        ],
        "notes": "Temporal trap: event branding differs from actual date.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    },
    {
        "id": "T004",
        "claim": "As of January 1, 1990, Germany was still divided into East Germany and West Germany.",
        "expected_verdict": "SUPPORTED",
        "expected_score": 1.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "supported",
            "temporal",
            "scoped"
        ],
        "notes": "Date-specific geopolitical claim.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            }
        ]
    },
    {
        "id": "T005",
        "claim": "As of December 31, 1990, Germany was still divided into East Germany and West Germany.",
        "expected_verdict": "REFUTED",
        "expected_score": 0.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "refuted",
            "temporal",
            "scoped"
        ],
        "notes": "Date-specific claim after reunification.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    },
    {
        "id": "T006",
        "claim": "As of 1969, humans had landed on the Moon.",
        "expected_verdict": "SUPPORTED",
        "expected_score": 1.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "supported",
            "temporal"
        ],
        "notes": "Past event with year.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            }
        ]
    },
    {
        "id": "T007",
        "claim": "As of 1968, humans had landed on the Moon.",
        "expected_verdict": "REFUTED",
        "expected_score": 0.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "refuted",
            "temporal"
        ],
        "notes": "Past event with year before first landing.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    },
    {
        "id": "T008",
        "claim": "The current Prime Minister is the longest-serving leader, with no country or date specified.",
        "expected_verdict": "INSUFFICIENT",
        "expected_score": 0.5,
        "source_types": [
            "NO_RELEVANT_SOURCE"
        ],
        "edge_cases": [
            "insufficient",
            "temporal",
            "missing_scope"
        ],
        "notes": "Current-holder claim lacks jurisdiction and as-of date.",
        "source_specs": [
            {
                "source_id": "silent_1",
                "tier": "TIER_1",
                "confidence": "SILENT",
                "excerpt": "Fixture source is silent for this claim."
            }
        ]
    },
    {
        "id": "T009",
        "claim": "The newest version is faster than the old version.",
        "expected_verdict": "INSUFFICIENT",
        "expected_score": 0.5,
        "source_types": [
            "NO_RELEVANT_SOURCE"
        ],
        "edge_cases": [
            "insufficient",
            "temporal",
            "comparative",
            "missing_version"
        ],
        "notes": "Requires version identifiers and benchmark definition.",
        "source_specs": [
            {
                "source_id": "silent_1",
                "tier": "TIER_1",
                "confidence": "SILENT",
                "excerpt": "Fixture source is silent for this claim."
            }
        ]
    },
    {
        "id": "T010",
        "claim": "As of 2015, Python 3.5 supported async and await syntax.",
        "expected_verdict": "SUPPORTED",
        "expected_score": 1.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "supported",
            "temporal",
            "technical"
        ],
        "notes": "Version/date-specific technical claim.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            }
        ]
    },
    {
        "id": "C001",
        "claim": "For right triangles only, the square of the hypotenuse equals the sum of the squares of the legs.",
        "expected_verdict": "SUPPORTED",
        "expected_score": 1.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "supported",
            "scoped",
            "mathematical"
        ],
        "notes": "Mathematical scope is explicit.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            }
        ]
    },
    {
        "id": "C002",
        "claim": "For all triangles, the square of one side equals the sum of the squares of the other two sides.",
        "expected_verdict": "REFUTED",
        "expected_score": 0.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "refuted",
            "scoped",
            "mathematical",
            "overgeneralization"
        ],
        "notes": "Overgeneralizes right-triangle theorem.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    },
    {
        "id": "C003",
        "claim": "Under normal Earth sea-level conditions, liquid water can freeze at about 0 degrees Celsius.",
        "expected_verdict": "SUPPORTED",
        "expected_score": 1.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "supported",
            "scoped"
        ],
        "notes": "Scope prevents pressure/impurity edge cases.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            }
        ]
    },
    {
        "id": "C004",
        "claim": "In every environment, water freezes at exactly 0 degrees Celsius.",
        "expected_verdict": "REFUTED",
        "expected_score": 0.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "refuted",
            "scoped",
            "absolute",
            "overgeneralization"
        ],
        "notes": "Absolute ignores pressure and impurities.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    },
    {
        "id": "C005",
        "claim": "For a PYNQ-Z2 board, the FPGA/SoC is a Xilinx Zynq-7000 family device.",
        "expected_verdict": "SUPPORTED",
        "expected_score": 1.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "supported",
            "scoped",
            "technical"
        ],
        "notes": "Board-specific technical claim.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            }
        ]
    },
    {
        "id": "C006",
        "claim": "For every FPGA development board, the FPGA/SoC is a Xilinx Zynq-7000 device.",
        "expected_verdict": "REFUTED",
        "expected_score": 0.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "refuted",
            "scoped",
            "overgeneralization",
            "technical"
        ],
        "notes": "Overgeneralizes one board family to all FPGA boards.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    },
    {
        "id": "C007",
        "claim": "In Python, tuples are mutable collections.",
        "expected_verdict": "REFUTED",
        "expected_score": 0.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "refuted",
            "scoped",
            "technical"
        ],
        "notes": "Language-specific claim is false.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    },
    {
        "id": "C008",
        "claim": "In Python, lists are mutable collections.",
        "expected_verdict": "SUPPORTED",
        "expected_score": 1.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "supported",
            "scoped",
            "technical"
        ],
        "notes": "Language-specific claim is true under fixture evidence.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            }
        ]
    },
    {
        "id": "C009",
        "claim": "The law allows this in Canada, but the claim gives no province, statute, or date.",
        "expected_verdict": "INSUFFICIENT",
        "expected_score": 0.5,
        "source_types": [
            "NO_RELEVANT_SOURCE"
        ],
        "edge_cases": [
            "insufficient",
            "scoped",
            "legal",
            "missing_jurisdiction"
        ],
        "notes": "Legal claims need jurisdiction/date/specific law.",
        "source_specs": [
            {
                "source_id": "silent_1",
                "tier": "TIER_1",
                "confidence": "SILENT",
                "excerpt": "Fixture source is silent for this claim."
            }
        ]
    },
    {
        "id": "M001",
        "claim": "Earth orbits the Sun, and the Moon orbits Earth.",
        "expected_verdict": "SUPPORTED",
        "expected_score": 1.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "supported",
            "compound"
        ],
        "notes": "Both subclaims are supported by fixture evidence.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            }
        ]
    },
    {
        "id": "M002",
        "claim": "Canada has ten provinces, and Toronto is the capital city of Canada.",
        "expected_verdict": "REFUTED",
        "expected_score": 0.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "refuted",
            "compound",
            "mixed_truth"
        ],
        "notes": "One subclaim is false, so the full conjunction is false.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    },
    {
        "id": "M003",
        "claim": "Python is a programming language, and HTML is primarily a database query language.",
        "expected_verdict": "REFUTED",
        "expected_score": 0.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "refuted",
            "compound",
            "mixed_truth",
            "technical"
        ],
        "notes": "Second subclaim is false.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    },
    {
        "id": "M004",
        "claim": "The project has tests, documentation, and full production security approval.",
        "expected_verdict": "INSUFFICIENT",
        "expected_score": 0.5,
        "source_types": [
            "PARTIAL_EVIDENCE"
        ],
        "edge_cases": [
            "insufficient",
            "compound",
            "partial_support"
        ],
        "notes": "Some components may be supported, but security approval is unresolved.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Evidence confirms tests and documentation only."
            },
            {
                "source_id": "silent_1",
                "tier": "TIER_1",
                "confidence": "SILENT",
                "excerpt": "No source for security approval."
            }
        ]
    },
    {
        "id": "M005",
        "claim": "The source says the policy passed, but another equally authoritative source says it failed.",
        "expected_verdict": "INSUFFICIENT",
        "expected_score": 0.5,
        "source_types": [
            "CONFLICTING_TIER_1"
        ],
        "edge_cases": [
            "insufficient",
            "compound",
            "conflict"
        ],
        "notes": "Conflicting authoritative evidence should not resolve.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    },
    {
        "id": "M006",
        "claim": "The device is waterproof and has a battery life over 40 hours.",
        "expected_verdict": "INSUFFICIENT",
        "expected_score": 0.5,
        "source_types": [
            "NO_RELEVANT_SOURCE"
        ],
        "edge_cases": [
            "insufficient",
            "compound",
            "missing_metric"
        ],
        "notes": "Requires product-specific sources and test conditions.",
        "source_specs": [
            {
                "source_id": "silent_1",
                "tier": "TIER_1",
                "confidence": "SILENT",
                "excerpt": "Fixture source is silent for this claim."
            }
        ]
    },
    {
        "id": "M007",
        "claim": "At sea level water boils near 100 degrees Celsius, and at the same pressure it freezes near 0 degrees Celsius.",
        "expected_verdict": "SUPPORTED",
        "expected_score": 1.0,
        "source_types": [
            "TIER_1_PRIMARY"
        ],
        "edge_cases": [
            "supported",
            "compound",
            "scoped"
        ],
        "notes": "Both scoped subclaims are supported.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            }
        ]
    },
    {
        "id": "M008",
        "claim": "A byte is eight bits, and a kilobyte is always exactly 1000 bytes in every context.",
        "expected_verdict": "INSUFFICIENT",
        "expected_score": 0.5,
        "source_types": [
            "CONFLICTING_TIER_1"
        ],
        "edge_cases": [
            "insufficient",
            "compound",
            "scoped",
            "definition_conflict"
        ],
        "notes": "Second subclaim depends on SI/binary context.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    },
    {
        "id": "M009",
        "claim": "The claim cites two sources, one confirms it and one directly contradicts it.",
        "expected_verdict": "INSUFFICIENT",
        "expected_score": 0.5,
        "source_types": [
            "CONFLICTING_TIER_1"
        ],
        "edge_cases": [
            "insufficient",
            "compound",
            "conflict"
        ],
        "notes": "Direct source conflict must remain insufficient.",
        "source_specs": [
            {
                "source_id": "primary_1",
                "tier": "TIER_1",
                "confidence": "CONFIRMS",
                "excerpt": "Fixture evidence confirms the claim."
            },
            {
                "source_id": "primary_2",
                "tier": "TIER_1",
                "confidence": "CONTRADICTS",
                "excerpt": "Fixture evidence contradicts the claim."
            }
        ]
    }
]
