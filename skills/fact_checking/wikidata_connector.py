"""
Narrow Wikidata-backed Tier-1 connector for the frozen v1 claim family.

This connector is intentionally conservative:
- only a small property whitelist is supported
- entity matching must be exact against the configured snapshot/backend
- weak, ambiguous, or unsupported claims return no result

The default backend is a tiny bundled snapshot so the connector remains
deterministic and testable in offline environments. The interface is designed
so a broader live backend can be swapped in later without changing the
connector contract.
"""

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from .connectors import SourceConnector
from .models import EvidenceTier, SourceConfidence, SourceResult


@dataclass(frozen=True)
class OfficeTerm:
    role: str
    jurisdiction: str
    start_year: int
    end_year: int | None


@dataclass(frozen=True)
class EntitySnapshot:
    qid: str
    canonical_name: str
    aliases: list[str] = field(default_factory=list)
    inception_year: int | None = None
    headquarters: str | None = None
    location: str | None = None
    birth_year: int | None = None
    death_year: int | None = None
    office_terms: list[OfficeTerm] = field(default_factory=list)


class SnapshotWikidataBackend:
    """Small deterministic snapshot used for tests and offline runtime safety."""

    def __init__(self, entities: Iterable[EntitySnapshot] | None = None):
        snapshots = list(entities) if entities is not None else list(DEFAULT_ENTITY_SNAPSHOTS)
        self._entities = snapshots
        self._alias_index: dict[str, list[EntitySnapshot]] = {}

        for entity in snapshots:
            alias_set = {
                entity.canonical_name.lower(),
                *(alias.lower() for alias in entity.aliases),
            }
            for alias in alias_set:
                self._alias_index.setdefault(alias, []).append(entity)

    def resolve(self, alias: str) -> EntitySnapshot | None:
        matches = self._alias_index.get(alias.strip().lower(), [])
        if len(matches) != 1:
            return None
        return matches[0]


DEFAULT_ENTITY_SNAPSHOTS = (
    EntitySnapshot(
        qid="Q24283660",
        canonical_name="openai",
        aliases=["open ai"],
        inception_year=2015,
        headquarters="san francisco",
    ),
    EntitySnapshot(
        qid="Q172",
        canonical_name="toronto",
        location="ontario",
    ),
    EntitySnapshot(
        qid="Q937",
        canonical_name="albert einstein",
        aliases=["einstein"],
        birth_year=1879,
        death_year=1955,
    ),
    EntitySnapshot(
        qid="Q309972",
        canonical_name="justin trudeau",
        office_terms=[
            OfficeTerm(
                role="prime minister",
                jurisdiction="canada",
                start_year=2015,
                end_year=2025,
            )
        ],
    ),
)


class WikidataConnector(SourceConnector):
    """
    Property-whitelisted structured connector for narrow public-entity claims.
    """

    def __init__(self, backend: SnapshotWikidataBackend | None = None):
        self._backend = backend or SnapshotWikidataBackend()

    @property
    def source_id(self) -> str:
        return "wikidata"

    @property
    def tier(self) -> EvidenceTier:
        return EvidenceTier.TIER_1

    def query(self, normalized_claim: str, claim_hash: str) -> SourceResult | None:
        parser = (
            self._parse_inception_claim,
            self._parse_headquarters_claim,
            self._parse_location_claim,
            self._parse_birth_claim,
            self._parse_death_claim,
            self._parse_life_status_claim,
            self._parse_office_claim,
        )

        parsed = None
        for handler in parser:
            parsed = handler(normalized_claim)
            if parsed is not None:
                break

        if parsed is None:
            return None

        entity = self._backend.resolve(parsed["entity"])
        if entity is None:
            return None

        verdict = parsed["resolver"](entity, parsed)
        if verdict is None:
            return None

        confidence, excerpt = verdict
        return SourceResult(
            source_id=self.source_id,
            source_url=f"https://www.wikidata.org/wiki/{entity.qid}",
            source_title=f"Wikidata entity data for {entity.canonical_name.title()}",
            confidence=confidence,
            excerpt=excerpt,
            content_hash=hashlib.sha256(f"{entity.qid}:{normalized_claim}".encode()).hexdigest()[
                :32
            ],
            retrieved_at=datetime.now(),
            tier=self.tier,
        )

    @staticmethod
    def _parse_inception_claim(claim: str) -> dict[str, object] | None:
        match = re.match(r"^(?P<entity>.+?) was founded in (?P<year>\d{4})\.?$", claim)
        if not match:
            return None
        return {
            "entity": match.group("entity").strip(),
            "year": int(match.group("year")),
            "resolver": WikidataConnector._resolve_inception_claim,
        }

    @staticmethod
    def _parse_headquarters_claim(claim: str) -> dict[str, object] | None:
        match = re.match(r"^(?P<entity>.+?) is headquartered in (?P<place>.+?)\.?$", claim)
        if not match:
            return None
        return {
            "entity": match.group("entity").strip(),
            "place": match.group("place").strip(),
            "resolver": WikidataConnector._resolve_headquarters_claim,
        }

    @staticmethod
    def _parse_location_claim(claim: str) -> dict[str, object] | None:
        match = re.match(r"^(?P<entity>.+?) is (?:located )?in (?P<place>.+?)\.?$", claim)
        if not match:
            return None
        return {
            "entity": match.group("entity").strip(),
            "place": match.group("place").strip(),
            "resolver": WikidataConnector._resolve_location_claim,
        }

    @staticmethod
    def _parse_birth_claim(claim: str) -> dict[str, object] | None:
        match = re.match(r"^(?P<entity>.+?) was born in (?P<year>\d{4})\.?$", claim)
        if not match:
            return None
        return {
            "entity": match.group("entity").strip(),
            "year": int(match.group("year")),
            "resolver": WikidataConnector._resolve_birth_claim,
        }

    @staticmethod
    def _parse_death_claim(claim: str) -> dict[str, object] | None:
        match = re.match(r"^(?P<entity>.+?) died in (?P<year>\d{4})\.?$", claim)
        if not match:
            return None
        return {
            "entity": match.group("entity").strip(),
            "year": int(match.group("year")),
            "resolver": WikidataConnector._resolve_death_claim,
        }

    @staticmethod
    def _parse_life_status_claim(claim: str) -> dict[str, object] | None:
        match = re.match(r"^(?P<entity>.+?) (?:is|was) (?P<status>alive|dead)\.?$", claim)
        if not match:
            return None
        return {
            "entity": match.group("entity").strip(),
            "status": match.group("status").strip(),
            "resolver": WikidataConnector._resolve_life_status_claim,
        }

    @staticmethod
    def _parse_office_claim(claim: str) -> dict[str, object] | None:
        match = re.match(
            r"^(?P<entity>.+?) (?:is|was) (?:the )?(?P<role>prime minister|president|mayor|governor|ceo|chief executive officer) of (?P<jurisdiction>.+?)(?: in (?P<year>\d{4}))?\.?$",
            claim,
        )
        if not match or match.group("year") is None:
            return None
        return {
            "entity": match.group("entity").strip(),
            "role": match.group("role").strip(),
            "jurisdiction": match.group("jurisdiction").strip(),
            "year": int(match.group("year")),
            "resolver": WikidataConnector._resolve_office_claim,
        }

    @staticmethod
    def _resolve_inception_claim(entity: EntitySnapshot, parsed: dict[str, object]):
        if entity.inception_year is None:
            return None
        claimed_year = parsed["year"]
        confidence = (
            SourceConfidence.CONFIRMS
            if entity.inception_year == claimed_year
            else SourceConfidence.CONTRADICTS
        )
        return (
            confidence,
            f"Wikidata inception year for {entity.canonical_name.title()} is {entity.inception_year}.",
        )

    @staticmethod
    def _resolve_headquarters_claim(entity: EntitySnapshot, parsed: dict[str, object]):
        if not entity.headquarters:
            return None
        claimed_place = str(parsed["place"]).lower()
        confidence = (
            SourceConfidence.CONFIRMS
            if entity.headquarters.lower() == claimed_place
            else SourceConfidence.CONTRADICTS
        )
        return (
            confidence,
            f"Wikidata headquarters location for {entity.canonical_name.title()} is {entity.headquarters.title()}.",
        )

    @staticmethod
    def _resolve_location_claim(entity: EntitySnapshot, parsed: dict[str, object]):
        if not entity.location:
            return None
        claimed_place = str(parsed["place"]).lower()
        confidence = (
            SourceConfidence.CONFIRMS
            if entity.location.lower() == claimed_place
            else SourceConfidence.CONTRADICTS
        )
        return (
            confidence,
            f"Wikidata administrative location for {entity.canonical_name.title()} is {entity.location.title()}.",
        )

    @staticmethod
    def _resolve_birth_claim(entity: EntitySnapshot, parsed: dict[str, object]):
        if entity.birth_year is None:
            return None
        claimed_year = parsed["year"]
        confidence = (
            SourceConfidence.CONFIRMS
            if entity.birth_year == claimed_year
            else SourceConfidence.CONTRADICTS
        )
        return (
            confidence,
            f"Wikidata birth year for {entity.canonical_name.title()} is {entity.birth_year}.",
        )

    @staticmethod
    def _resolve_death_claim(entity: EntitySnapshot, parsed: dict[str, object]):
        if entity.death_year is None:
            return None
        claimed_year = parsed["year"]
        confidence = (
            SourceConfidence.CONFIRMS
            if entity.death_year == claimed_year
            else SourceConfidence.CONTRADICTS
        )
        return (
            confidence,
            f"Wikidata death year for {entity.canonical_name.title()} is {entity.death_year}.",
        )

    @staticmethod
    def _resolve_life_status_claim(entity: EntitySnapshot, parsed: dict[str, object]):
        claimed_status = str(parsed["status"]).lower()
        actual_status = "dead" if entity.death_year is not None else "alive"
        confidence = (
            SourceConfidence.CONFIRMS
            if claimed_status == actual_status
            else SourceConfidence.CONTRADICTS
        )
        return (
            confidence,
            f"Wikidata life status for {entity.canonical_name.title()} is {actual_status}.",
        )

    @staticmethod
    def _resolve_office_claim(entity: EntitySnapshot, parsed: dict[str, object]):
        if not entity.office_terms:
            return None

        role = str(parsed["role"]).lower()
        jurisdiction = str(parsed["jurisdiction"]).lower()
        year = int(parsed["year"])

        matching_term = None
        for term in entity.office_terms:
            if term.role.lower() != role or term.jurisdiction.lower() != jurisdiction:
                continue
            matching_term = term
            break

        if matching_term is None:
            return None

        end_year = matching_term.end_year or datetime.now().year
        confidence = (
            SourceConfidence.CONFIRMS
            if matching_term.start_year <= year <= end_year
            else SourceConfidence.CONTRADICTS
        )
        return (
            confidence,
            (
                f"Wikidata office term for {entity.canonical_name.title()} as {matching_term.role.title()} "
                f"of {matching_term.jurisdiction.title()} spans {matching_term.start_year}-{matching_term.end_year or 'present'}."
            ),
        )
