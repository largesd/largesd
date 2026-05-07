"""
Source Reputation Registry for v1.5.

Maintains allowlist of domains/publications qualifying as Tier 2.
Promotion requires: (a) registry match AND (b) independence verification AND (c) policy approval.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class ReputationEntry:
    domain: str
    publication_name: str
    tier: int  # promoted tier
    approved_by: str
    approval_date: str


class SourceReputationRegistry:
    """Allowlist of Tier 3 sources that can be promoted to Tier 2."""

    def __init__(self, entries: list[ReputationEntry] | None = None):
        self._entries = entries or []
        self._domain_index = {e.domain: e for e in self._entries}

    def is_promoted(self, domain: str) -> bool:
        return domain in self._domain_index

    def get_promoted_tier(self, domain: str) -> int | None:
        entry = self._domain_index.get(domain)
        return entry.tier if entry else None

    def promote(self, domain: str, publication_name: str, approved_by: str) -> ReputationEntry:
        entry = ReputationEntry(
            domain=domain,
            publication_name=publication_name,
            tier=2,
            approved_by=approved_by,
            approval_date=datetime.now().isoformat(),
        )
        self._entries.append(entry)
        self._domain_index[domain] = entry
        return entry
