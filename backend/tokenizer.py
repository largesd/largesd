"""
Canonical Tokenizer for the Debate System

Per MSD §5: Spans use "char or token offsets in canonical tokenizer".
This module provides a consistent tokenization approach for:
- Span offset calculation
- Content mass computation (MSD §11)
- Traceability preservation
"""

import re


class CanonicalTokenizer:
    """
    Canonical tokenizer for consistent text segmentation.

    Rules (MSD §5):
    - Whitespace splits tokens
    - Punctuation attaches to preceding word
    - Preserves offset mappings for traceability
    """

    def __init__(self):
        # Simple whitespace-based tokenization with offset tracking
        self.token_pattern = re.compile(r"\S+")

    def tokenize(self, text: str) -> list[tuple[str, int, int]]:
        """
        Tokenize text and return tokens with character offsets.

        Returns: List of (token_text, start_offset, end_offset)
        """
        tokens = []
        for match in self.token_pattern.finditer(text):
            tokens.append((match.group(), match.start(), match.end()))
        return tokens

    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        return len(self.tokenize(text))

    def get_token_offsets(self, text: str) -> list[tuple[int, int]]:
        """Get just the character offsets for each token."""
        return [(start, end) for _, start, end in self.tokenize(text)]

    def char_offset_to_token_index(self, text: str, char_offset: int) -> int:
        """
        Convert a character offset to the token index that contains it.
        Returns -1 if offset is out of bounds.
        """
        tokens = self.tokenize(text)
        for i, (_, start, end) in enumerate(tokens):
            if start <= char_offset < end:
                return i
            if char_offset < start:
                return i  # Return next token if between tokens
        return len(tokens) if char_offset >= len(text) else -1


class ContentMassCalculator:
    """
    Calculates content mass per MSD §11:

    Mass_t = total token count of spans that contributed to
             canonical FACT nodes and/or canonical ARGUMENT inference spans

    Rel_t = Mass_t / Σ_t Mass_t
    """

    def __init__(self, tokenizer: CanonicalTokenizer = None):
        self.tokenizer = tokenizer or CanonicalTokenizer()

    def calculate_span_mass(self, span_text: str) -> int:
        """Calculate token mass of a single span."""
        return self.tokenizer.count_tokens(span_text)

    def calculate_topic_mass(
        self, canonical_facts: list[dict], canonical_arguments: list[dict], spans_lookup: dict
    ) -> int:
        """
        Calculate total content mass for a topic.

        Per MSD §11: Only count spans that contributed to:
        - Canonical FACT nodes (member facts)
        - Canonical ARGUMENT inference spans

        Args:
            canonical_facts: List of canonical fact dicts with 'provenance_links'
            canonical_arguments: List of canonical argument dicts with 'provenance_links'
            spans_lookup: Dict mapping span_id to span data

        Returns:
            Total token count (Mass_t)
        """
        counted_span_ids = set()
        total_tokens = 0

        # Count spans from canonical FACT nodes
        for fact in canonical_facts:
            provenance = fact.get("provenance_links", [])
            for link in provenance:
                span_id = link.get("span_id") if isinstance(link, dict) else link
                if span_id and span_id not in counted_span_ids:
                    counted_span_ids.add(span_id)
                    span_text = self._get_span_text(span_id, spans_lookup)
                    if span_text:
                        total_tokens += self.calculate_span_mass(span_text)

        # Count spans from canonical ARGUMENT inference spans
        for arg in canonical_arguments:
            provenance = arg.get("provenance_links", [])
            for link in provenance:
                span_id = link.get("span_id") if isinstance(link, dict) else link
                if span_id and span_id not in counted_span_ids:
                    counted_span_ids.add(span_id)
                    span_text = self._get_span_text(span_id, spans_lookup)
                    if span_text:
                        total_tokens += self.calculate_span_mass(span_text)

        return total_tokens

    def _get_span_text(self, span_id: str, spans_lookup: dict) -> str:
        """Get span text from lookup."""
        span = spans_lookup.get(span_id)
        if span:
            return span.get("span_text", "")
        return None

    def calculate_relevance_weights(self, topic_masses: dict) -> dict:
        """
        Calculate relevance weights per MSD §11.

        Rel_t = Mass_t / Σ_t Mass_t
        Constraint: Σ_t Rel_t = 1

        Args:
            topic_masses: {topic_id: mass}

        Returns:
            {topic_id: relevance_weight}
        """
        total_mass = sum(topic_masses.values())

        if total_mass == 0:
            # Equal distribution if no mass
            n = len(topic_masses)
            return {tid: 1.0 / n for tid in topic_masses} if n > 0 else {}

        return {topic_id: mass / total_mass for topic_id, mass in topic_masses.items()}


# Global tokenizer instance for consistency
_canonical_tokenizer = None


def get_canonical_tokenizer() -> CanonicalTokenizer:
    """Get the global canonical tokenizer instance."""
    global _canonical_tokenizer
    if _canonical_tokenizer is None:
        _canonical_tokenizer = CanonicalTokenizer()
    return _canonical_tokenizer
