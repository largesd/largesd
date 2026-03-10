"""
Claim normalization for stable identity
Implements Section 5 of the Fact Checking Skill Specification
"""
import hashlib
import re
import unicodedata


class ClaimNormalizer:
    """
    Normalizes claim text to create stable identities for caching.
    
    Rules (in order):
    1. Trim leading/trailing whitespace
    2. Convert internal whitespace runs to single ASCII space
    3. Lowercase all alphabetic characters
    4. Standardize Unicode quotes/dashes to ASCII equivalents
    5. Normalize Unicode to NFC, then NFKC
    6. Number normalization:
       - Remove thousands separators (1,000,000 -> 1000000)
       - Normalize percentages: "3.5 percent" -> "3.5%"
       - Normalize decimal points to "."
    7. Preserve units exactly (unless unit-normalization policy exists)
    8. Do NOT remove stopwords
    9. Do NOT stem, lemmatize, or paraphrase
    """
    
    # Unicode replacements for standardization
    UNICODE_REPLACEMENTS = [
        # Double quotes
        ('\u201c', '"'), ('\u201d', '"'), ('\u201f', '"'),
        ('\u00ab', '"'), ('\u00bb', '"'),  # Guillemets
        # Single quotes
        ('\u2018', "'"), ('\u2019', "'"), ('\u201a', "'"), 
        ('\u201b', "'"), ('`', "'"), ('\u00b4', "'"),
        # Dashes
        ('\u2014', '-'), ('\u2013', '-'), ('\u2212', '-'),
        ('\u2010', '-'), ('\u2011', '-'), ('\u2012', '-'),
        # Ellipsis
        ('\u2026', '...'),
        # Other punctuation
        ('\u00a0', ' '),  # Non-breaking space
    ]
    
    @classmethod
    def normalize(cls, claim_text: str) -> str:
        """
        Normalize claim text per specification.
        
        Args:
            claim_text: Raw claim text
            
        Returns:
            Normalized claim text
        """
        text = claim_text
        
        # 1. Trim leading/trailing whitespace
        text = text.strip()
        
        # 2. Normalize internal whitespace to single ASCII space
        text = re.sub(r'\s+', ' ', text)
        
        # 3. Lowercase all alphabetic characters
        text = text.lower()
        
        # 4. Standardize Unicode quotes and dashes to ASCII
        for old, new in cls.UNICODE_REPLACEMENTS:
            text = text.replace(old, new)
        
        # 5. Unicode normalization: NFC then NFKC
        text = unicodedata.normalize('NFC', text)
        text = unicodedata.normalize('NFKC', text)
        
        # 6. Number normalization
        text = cls._normalize_numbers(text)
        
        return text.strip()
    
    @classmethod
    def _normalize_numbers(cls, text: str) -> str:
        """
        Normalize numbers in text:
        - Remove thousands separators (1,000,000 -> 1000000)
        - Normalize percentages: "3.5 percent" -> "3.5%"
        - Normalize decimal points to "."
        """
        # Normalize percentages: "3.5 percent" or "3.5 per cent" -> "3.5%"
        text = re.sub(r'(\d+\.?\d*)\s*percent\b', r'\1%', text)
        text = re.sub(r'(\d+\.?\d*)\s*per\s+cent\b', r'\1%', text)
        
        # Handle thousands separators iteratively
        # Pattern: digit, comma, exactly 3 digits
        prev_text = None
        while prev_text != text:
            prev_text = text
            text = re.sub(r'(\d),(\d{3})', r'\1\2', text)
        
        return text
    
    @classmethod
    def compute_hash(cls, normalized_claim: str) -> str:
        """
        Compute SHA256 hash of normalized claim.
        
        Args:
            normalized_claim: Already normalized claim text
            
        Returns:
            Hexadecimal hash string
        """
        return hashlib.sha256(normalized_claim.encode('utf-8')).hexdigest()
    
    @classmethod
    def normalize_and_hash(cls, claim_text: str) -> tuple:
        """
        Normalize claim and compute hash in one operation.
        
        Args:
            claim_text: Raw claim text
            
        Returns:
            Tuple of (normalized_text, hash)
        """
        normalized = cls.normalize(claim_text)
        claim_hash = cls.compute_hash(normalized)
        return normalized, claim_hash


def normalize_claim(claim_text: str) -> str:
    """Convenience function for normalizing a claim"""
    return ClaimNormalizer.normalize(claim_text)


def compute_claim_hash(normalized_claim: str) -> str:
    """Convenience function for computing claim hash"""
    return ClaimNormalizer.compute_hash(normalized_claim)
