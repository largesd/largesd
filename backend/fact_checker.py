"""
Fact Checking Skill Implementation
Based on the Fact Checking Agentic Skill Design Specification
"""
import hashlib
import re
import unicodedata
from typing import Optional, Dict, List
from datetime import datetime
import time
import random

from models import (
    FactCheckResult, EvidenceRecord, FactCheckVerdict, FactCheckStatus
)


class FactChecker:
    """
    Deterministic fact-checking with support for OFFLINE and ONLINE_ALLOWLIST modes.
    """
    
    # Configuration thresholds (versioned)
    CONFIG = {
        "algorithm_version": "fc-1.0",
        "support_threshold": 0.70,
        "contradiction_threshold": 0.70,
        "mixed_threshold": 0.40,
        "confidence_penalty_threshold": 0.30,
        "max_claim_length": 500,
        "max_evidence_age_days": 365,
        "retrieval_top_k": 10,
        "evidence_keep_n": 3,
    }
    
    def __init__(self, mode: str = "OFFLINE", allowlist_version: str = "v1"):
        """
        Initialize fact checker.
        
        Args:
            mode: "OFFLINE" or "ONLINE_ALLOWLIST"
            allowlist_version: version string for allowlist
        """
        self.mode = mode
        self.allowlist_version = allowlist_version
        self._cache: Dict[str, FactCheckResult] = {}
    
    def normalize_claim(self, claim_text: str) -> str:
        """
        Normalize claim text per specification.
        
        Rules:
        - trim leading/trailing whitespace
        - convert internal whitespace runs to single ASCII space
        - lowercase all alphabetic characters
        - standardize Unicode quotes/dashes to ASCII
        - normalize Unicode to NFC, then NFKC
        - convert numbers: remove thousands separators, normalize decimals
        - preserve units exactly
        - do not remove stopwords or stem/lemmatize
        """
        # Trim
        text = claim_text.strip()
        
        # Normalize internal whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Lowercase
        text = text.lower()
        
        # Standardize Unicode quotes and dashes to ASCII
        # Use unicode escape sequences to avoid encoding issues
        replacements = [
            ('\u201c', '"'), ('\u201d', '"'), ('\u201f', '"'),  # Double quotes
            ('\u2018', "'"), ('\u2019', "'"), ('\u201a', "'"), ('\u201b', "'"), ('`', "'"),  # Single quotes
            ('\u2014', '-'), ('\u2013', '-'), ('\u2212', '-'),  # Dashes
            ('\u2026', '...'),  # Ellipsis
        ]
        for old, new in replacements:
            text = text.replace(old, new)
        
        # Unicode normalization: NFC then NFKC
        text = unicodedata.normalize('NFC', text)
        text = unicodedata.normalize('NFKC', text)
        
        # Number normalization
        # Remove thousands separators (1,000,000 -> 1000000)
        text = re.sub(r'(\d),(\d{3})', r'\1\2', text)
        
        # Normalize percentages: 3.5 percent -> 3.5%
        text = re.sub(r'(\d+\.?\d*)\s*percent\b', r'\1%', text)
        
        # Normalize decimal points (already standard)
        text = text.replace(',', '')  # Remove any remaining commas in numbers
        
        return text.strip()
    
    def compute_claim_hash(self, normalized_claim: str) -> str:
        """Compute SHA256 hash of normalized claim"""
        return hashlib.sha256(normalized_claim.encode('utf-8')).hexdigest()
    
    def build_cache_key(self, claim_hash: str) -> str:
        """Build cache key from claim hash, mode, and allowlist version"""
        return f"{claim_hash}:{self.mode}:{self.allowlist_version}"
    
    def check_cache(self, cache_key: str) -> Optional[FactCheckResult]:
        """Check if result exists in cache"""
        if cache_key in self._cache:
            result = self._cache[cache_key]
            result.cache_result = "HIT_MEMORY"
            return result
        return None
    
    def store_cache(self, cache_key: str, result: FactCheckResult):
        """Store result in cache"""
        self._cache[cache_key] = result
    
    def check_offline(self, claim_text: str, normalized_claim: str, 
                      claim_hash: str) -> FactCheckResult:
        """
        OFFLINE mode: No live source lookup.
        Returns neutral result with factuality_score = 0.5, confidence = 0.0
        """
        return FactCheckResult(
            claim_text=claim_text,
            normalized_claim_text=normalized_claim,
            claim_hash=claim_hash,
            fact_mode="OFFLINE",
            allowlist_version=self.allowlist_version,
            status=FactCheckStatus.UNVERIFIED_OFFLINE,
            verdict=FactCheckVerdict.UNVERIFIED,
            factuality_score=0.5,
            confidence=0.0,
            confidence_explanation="OFFLINE mode: no source lookup performed",
            evidence=[],
            algorithm_version=self.CONFIG["algorithm_version"],
            cache_result="MISS"
        )
    
    def check_online_allowlist(self, claim_text: str, normalized_claim: str,
                               claim_hash: str) -> FactCheckResult:
        """
        ONLINE_ALLOWLIST mode: Query approved sources.
        For prototype, simulates deterministic fact-checking.
        """
        start_time = time.time()
        
        # In a real implementation, this would:
        # 1. Query approved sources in allowlist_version
        # 2. Rank evidence deterministically
        # 3. Compute support/contradiction scores
        # 4. Apply thresholds to determine verdict
        
        # For prototype: simulate based on claim hash for determinism
        hash_int = int(claim_hash[:8], 16)
        
        # Simulate factuality score based on hash (for demo consistency)
        # Use a deterministic pseudo-random based on hash
        simulated_score = ((hash_int % 100) / 100.0 * 0.6) + 0.2  # Range 0.2-0.8
        
        # Add some variation based on claim content keywords
        if any(kw in normalized_claim.lower() for kw in ['can', 'will', 'proven', 'documented']):
            simulated_score = min(1.0, simulated_score + 0.1)
        if any(kw in normalized_claim.lower() for kw in ['might', 'possibly', 'uncertain', 'unclear']):
            simulated_score = max(0.0, simulated_score - 0.1)
        
        # Determine verdict based on thresholds
        support = simulated_score
        contradiction = 1.0 - simulated_score
        
        if support > self.CONFIG["support_threshold"] and contradiction < 0.3:
            verdict = FactCheckVerdict.SUPPORTED
            confidence = 0.7 + (support - 0.7) * 0.5
        elif contradiction > self.CONFIG["contradiction_threshold"] and support < 0.3:
            verdict = FactCheckVerdict.CONTRADICTED
            confidence = 0.7 + (contradiction - 0.7) * 0.5
        elif support > 0.4 and contradiction > 0.4:
            verdict = FactCheckVerdict.MIXED
            confidence = 0.5
        else:
            verdict = FactCheckVerdict.INSUFFICIENT_EVIDENCE
            confidence = 0.3
        
        # Check for near-threshold confidence penalty
        if abs(support - contradiction) < self.CONFIG["confidence_penalty_threshold"]:
            confidence *= 0.75
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Create simulated evidence
        evidence = []
        if verdict != FactCheckVerdict.INSUFFICIENT_EVIDENCE:
            evidence = [
                EvidenceRecord(
                    source_url="https://example.com/source1",
                    source_id="src_001",
                    source_version="v1",
                    source_title="Reference Document",
                    snippet=f"Evidence related to: {normalized_claim[:50]}...",
                    content_hash=hashlib.sha256(b"content").hexdigest()[:16],
                    retrieved_at=datetime.now(),
                    relevance_score=0.85,
                    support_score=support,
                    contradiction_score=contradiction,
                    selected_rank=1
                )
            ]
        
        return FactCheckResult(
            claim_text=claim_text,
            normalized_claim_text=normalized_claim,
            claim_hash=claim_hash,
            fact_mode="ONLINE_ALLOWLIST",
            allowlist_version=self.allowlist_version,
            status=FactCheckStatus.CHECKED,
            verdict=verdict,
            factuality_score=round(simulated_score, 2),
            confidence=round(confidence, 2),
            confidence_explanation=f"Support: {support:.2f}, Contradiction: {contradiction:.2f}",
            evidence=evidence,
            source_count_considered=3,
            source_count_retained=len(evidence),
            algorithm_version=self.CONFIG["algorithm_version"],
            processing_duration_ms=duration_ms,
            cache_result="MISS"
        )
    
    def check_fact(self, claim_text: str, 
                   temporal_context: Optional[Dict] = None) -> FactCheckResult:
        """
        Check a factual claim.
        
        Args:
            claim_text: The claim to check
            temporal_context: Optional temporal context for time-sensitive claims
        
        Returns:
            FactCheckResult with factuality_score (P(true)), confidence, etc.
        """
        # Validate input
        if len(claim_text) > self.CONFIG["max_claim_length"]:
            claim_text = claim_text[:self.CONFIG["max_claim_length"]]
        
        # Normalize and hash
        normalized = self.normalize_claim(claim_text)
        claim_hash = self.compute_claim_hash(normalized)
        
        # Check cache
        cache_key = self.build_cache_key(claim_hash)
        cached = self.check_cache(cache_key)
        if cached:
            return cached
        
        # Perform fact check based on mode
        if self.mode == "OFFLINE":
            result = self.check_offline(claim_text, normalized, claim_hash)
        else:  # ONLINE_ALLOWLIST
            result = self.check_online_allowlist(claim_text, normalized, claim_hash)
        
        # Store in cache
        self.store_cache(cache_key, result)
        
        return result
    
    def invalidate_cache(self, claim_hash: str, reason: str):
        """Explicitly invalidate a cached fact check"""
        cache_key = self.build_cache_key(claim_hash)
        if cache_key in self._cache:
            result = self._cache[cache_key]
            result.invalidated_at = datetime.now()
            result.invalidation_reason = reason
            result.status = FactCheckStatus.STALE
            del self._cache[cache_key]
    
    def get_cache_stats(self) -> Dict:
        """Get cache statistics"""
        return {
            "size": len(self._cache),
            "mode": self.mode,
            "allowlist_version": self.allowlist_version
        }
