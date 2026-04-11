"""
PII Detection and Redaction
Prevents leakage of personal information to external sources
"""
import re
import hashlib
from typing import List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class PIIDetectionResult:
    """Result of PII detection"""
    contains_pii: bool
    detected_types: List[str]
    redacted_text: str
    pii_spans: List[Tuple[int, int, str]]  # start, end, type


class PIIDetector:
    """
    Detects and redacts personally identifiable information.
    
    Detected PII types:
    - Email addresses
    - Phone numbers
    - Social Security Numbers
    - Credit card numbers
    - IP addresses
    """
    
    # Regex patterns for PII detection
    PATTERNS = {
        'email': re.compile(
            r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
            re.IGNORECASE
        ),
        'phone': re.compile(
            r'\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b'
        ),
        'ssn': re.compile(
            r'\b\d{3}[-.\s]?\d{2}[-.\s]?\d{4}\b'
        ),
        'credit_card': re.compile(
            r'\b(?:\d{4}[-.\s]?){3}\d{4}\b'
        ),
        'ip_address': re.compile(
            r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
        ),
    }
    
    @classmethod
    def detect(cls, text: str) -> PIIDetectionResult:
        """
        Detect PII in text and return redacted version.
        
        Args:
            text: Input text to scan
            
        Returns:
            PIIDetectionResult with detection info and redacted text
        """
        detected_types = []
        pii_spans = []
        redacted = text
        
        # Find all PII occurrences
        for pii_type, pattern in cls.PATTERNS.items():
            for match in pattern.finditer(text):
                detected_types.append(pii_type)
                pii_spans.append((match.start(), match.end(), pii_type))
        
        # Sort spans by start position (reverse for safe replacement)
        pii_spans.sort(key=lambda x: x[0], reverse=True)
        
        # Redact by replacing with hash
        for start, end, pii_type in pii_spans:
            original = text[start:end]
            # Create a short hash for redaction
            redaction_hash = hashlib.sha256(original.encode()).hexdigest()[:8]
            redacted = redacted[:start] + f"[{pii_type.upper()}_{redaction_hash}]" + redacted[end:]
        
        # Remove duplicates while keeping a deterministic order for testing and downstream use
        detected_types = sorted(set(detected_types))
        
        return PIIDetectionResult(
            contains_pii=len(detected_types) > 0,
            detected_types=detected_types,
            redacted_text=redacted,
            pii_spans=pii_spans
        )
    
    @classmethod
    def sanitize_for_external_query(cls, text: str) -> str:
        """
        Sanitize text for use in external search queries.
        Removes all detected PII entirely rather than replacing.
        
        Args:
            text: Input text
            
        Returns:
            Sanitized text safe for external queries
        """
        result = text
        spans_to_remove = []
        
        # Collect all PII spans
        for pii_type, pattern in cls.PATTERNS.items():
            for match in pattern.finditer(text):
                spans_to_remove.append((match.start(), match.end()))
        
        # Sort by start position (reverse for safe removal)
        spans_to_remove.sort(key=lambda x: x[0], reverse=True)
        
        # Remove PII spans
        for start, end in spans_to_remove:
            result = result[:start] + result[end:]
        
        # Clean up extra whitespace
        result = ' '.join(result.split())
        
        return result.strip()
    
    @classmethod
    def hash_for_audit_log(cls, text: str) -> str:
        """
        Hash text for storage in audit logs when it contains PII.
        
        Args:
            text: Text that may contain PII
            
        Returns:
            SHA256 hash of text
        """
        return hashlib.sha256(text.encode()).hexdigest()


def detect_pii(text: str) -> PIIDetectionResult:
    """Convenience function for PII detection"""
    return PIIDetector.detect(text)


def sanitize_for_query(text: str) -> str:
    """Convenience function for sanitizing external queries"""
    return PIIDetector.sanitize_for_external_query(text)
