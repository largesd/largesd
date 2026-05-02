"""
Template adapters from fact-checker.md.

EXPLAINABILITY HELPERS ONLY.

These classes improve operationalization, audit trails, and diagnostic
output. They DO NOT participate in adjudication and MUST NOT move
p-values away from the evidence-policy decision.

If an analyzer detects misinformation patterns, that information is
logged in the audit trail and may refine operationalization text.
It does not override a SUPPORTED/REFUTED/INSUFFICIENT verdict.
"""

import re
from urllib.parse import urlparse
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum


class ClaimType(Enum):
    STATISTICAL = "statistical"
    CAUSAL = "causal"
    TEMPORAL = "temporal"
    COMPARATIVE = "comparative"
    ATTRIBUTION = "attribution"
    DEFINITIONAL = "definitional"
    GENERAL = "general"


@dataclass
class ClaimAnalysis:
    claim_type: ClaimType
    entities: List[str]
    temporal_refs: List[str]
    statistical_refs: List[str]


class ClaimTypeDetector:
    PATTERNS = {
        ClaimType.STATISTICAL: [
            r'\d+(?:\.\d+)?%\s+of\s+[\w\s]+',
            r'\$[\d,]+\s+[\w\s]+',
            r'\d+\s+(million|billion|thousand)\s+[\w\s]+',
            r'(increased|decreased|grew|fell|rose|dropped)\s+by\s+\d+(?:\.\d+)?%',
        ],
        ClaimType.CAUSAL: [
            r'\bcaused\b', r'\bleads to\b', r'\bresults in\b',
            r'\bdue to\b', r'\bbecause of\b',
        ],
        ClaimType.TEMPORAL: [
            r'\bin \d{4}\b', r'\bsince \d{4}\b',
            r'\bfrom \d{4} to \d{4}\b',
            r'\b(as of|currently|now|recently|last year)\b',
        ],
        ClaimType.COMPARATIVE: [
            r'\bmore than\b', r'\bless than\b', r'\bhigher\b',
            r'\blower\b', r'\bcompared to\b', r'\bversus\b',
        ],
        ClaimType.ATTRIBUTION: [
            r'\baccording to\b', r'\bsaid that\b',
            r'\breported that\b', r'\bfound that\b',
        ],
    }

    @classmethod
    def detect(cls, claim_text: str) -> ClaimAnalysis:
        lowered = claim_text.lower()
        claim_type = ClaimType.GENERAL
        max_hits = 0
        for ctype, patterns in cls.PATTERNS.items():
            hits = sum(1 for p in patterns if re.search(p, lowered))
            if hits > max_hits:
                max_hits = hits
                claim_type = ctype

        entities = list(set(re.findall(r'\b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*\b', claim_text)))[:10]
        temporal_refs = re.findall(r'\b(?:in|since|from|until|before|after)\s+\d{4}\b', claim_text, re.I)
        statistical_refs = re.findall(r'\d+(?:\.\d+)?%', claim_text)

        return ClaimAnalysis(
            claim_type=claim_type,
            entities=entities,
            temporal_refs=temporal_refs,
            statistical_refs=statistical_refs,
        )


class SourceCredibilityAnalyzer:
    """
    Domain-level credibility heuristic for audit trails.
    DOES NOT affect tier assignment or adjudication.
    """

    HIGH_AUTHORITY_DOMAINS = {".edu", ".gov", ".org"}
    PEER_REVIEWED_MARKERS = ["doi", "pmid", "arxiv", "journal", "peer-reviewed"]

    @classmethod
    def assess(cls, source_url: str, excerpt: str) -> Tuple[float, bool]:
        domain = urlparse(source_url).netloc.lower()
        score = 0.5
        is_primary = False

        if any(domain.endswith(d) for d in cls.HIGH_AUTHORITY_DOMAINS):
            score = 0.85
        if any(m in source_url.lower() or m in excerpt.lower() for m in cls.PEER_REVIEWED_MARKERS):
            score = min(1.0, score + 0.1)
            is_primary = True
        return round(score, 2), is_primary


class MisinformationScanner:
    """
    Pattern scanner for operationalization enrichment.
    Flags do not change verdicts; they may trigger additional
    operationalization text (e.g., "check for omitted base rate").
    """

    EMOTIONAL_TRIGGERS = [
        r"\bshocking\b", r"\boutrageous\b", r"\bunbelievable\b",
        r"\bthey don't want you to know\b", r"\bwake up\b",
        r"\bmainstream media won't report\b",
    ]
    STAT_MANIPULATION = [
        r"\d+%\s+of\s+people\s+say",
        r"study\s+(proves|shows)\s+.*\d+%",
    ]

    @classmethod
    def scan(cls, claim_text: str) -> Dict[str, Any]:
        lowered = claim_text.lower()
        flags = []
        for p in cls.EMOTIONAL_TRIGGERS:
            if re.search(p, lowered):
                flags.append("emotional_manipulation")
        for p in cls.STAT_MANIPULATION:
            if re.search(p, lowered):
                flags.append("potential_statistical_manipulation")
        return {
            "misinformation_risk": "HIGH" if len(flags) >= 2 else "MEDIUM" if flags else "LOW",
            "flags": flags,
        }


class ConsensusAnalyzer:
    """
    Helper for describing source agreement in operationalization.
    DOES NOT compute p-values.
    """

    @staticmethod
    def analyze(confirms: int, contradicts: int) -> Tuple[str, float]:
        active = confirms + contradicts
        if active == 0:
            return "DISPUTED", 0.0
        ratio = max(confirms / active, contradicts / active)
        if ratio >= 0.8:
            return "STRONG", round(ratio, 2)
        elif ratio >= 0.6:
            return "MODERATE", round(ratio, 2)
        elif ratio >= 0.5:
            return "WEAK", round(ratio, 2)
        else:
            return "DISPUTED", round(ratio, 2)
