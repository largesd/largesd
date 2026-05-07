"""
Phase 4 real connector layer for the LSD Fact-Checking System v1.5.

Implements five connector types per 04_ROADMAP.md:
1. Wikidata entity/static fact connector
2. BLS official statistics connector
3. Crossref scientific metadata connector
4. Tier 2 curated source connector
5. Tier 3 search/discovery connector

Rules:
- All connectors return EvidenceItem objects only.
- Connectors do not produce final verdicts.
- Absence in Wikidata -> no evidence (synthesis engine emits INSUFFICIENT).
- Tier 3 evidence cannot alone support/refute.
- Source independence group IDs are populated for cross-verification.
- Live connector tests are skippable in CI when credentials are unavailable.
- Synthesis engine behavior is unchanged.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from .v15_models import (
    AtomicSubclaim,
    ClaimType,
    DeterministicComparisonResult,
    Direction,
    DirectionMethod,
    EvidenceItem,
    ResolvedValue,
    RetrievalPath,
    SourceType,
    ValueType,
)

# ---------------------------------------------------------------------------
# Protocol / base class
# ---------------------------------------------------------------------------


class EvidenceConnector(Protocol):
    """Protocol for v1.5 evidence connectors."""

    @property
    def connector_id(self) -> str: ...

    @property
    def connector_version(self) -> str: ...

    def retrieve(self, subclaim: AtomicSubclaim) -> list[EvidenceItem]: ...


class BaseEvidenceConnector(ABC):
    """Abstract base providing common helper methods for v1.5 connectors."""

    @property
    @abstractmethod
    def connector_id(self) -> str: ...

    @property
    @abstractmethod
    def connector_version(self) -> str: ...

    @abstractmethod
    def retrieve(self, subclaim: AtomicSubclaim) -> list[EvidenceItem]: ...

    def _now_iso(self) -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def _query_hash(self, query_text: str) -> str:
        return hashlib.sha256(query_text.encode("utf-8")).hexdigest()[:32]

    def _make_item(
        self,
        subclaim: AtomicSubclaim,
        source_type: SourceType,
        source_tier: int,
        retrieval_path: RetrievalPath,
        source_url: str,
        source_title: str,
        source_authority: str,
        quote_or_span: str,
        direction: Direction,
        direction_confidence: float,
        direction_method: DirectionMethod,
        relevance_score: float,
        group_id: str | None = None,
        claimed_value: ResolvedValue | None = None,
        source_value: ResolvedValue | None = None,
        deterministic_comparison_result: DeterministicComparisonResult = DeterministicComparisonResult.NOT_RUN,
    ) -> EvidenceItem:
        raw = f"{self.connector_id}:{subclaim.subclaim_id}:{quote_or_span}"
        return EvidenceItem(
            subclaim_id=subclaim.subclaim_id,
            source_type=source_type,
            source_tier=source_tier,
            retrieval_path=retrieval_path,
            source_url=source_url,
            source_title=source_title,
            source_authority=source_authority,
            quote_or_span=quote_or_span[:1000],
            relevance_score=relevance_score,
            direction=direction,
            direction_confidence=direction_confidence,
            direction_method=direction_method,
            retrieval_timestamp=self._now_iso(),
            connector_version=self.connector_version,
            connector_query_hash=self._query_hash(subclaim.text),
            raw_response_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32],
            source_independence_group_id=group_id,
            claimed_value=claimed_value,
            source_value=source_value,
            deterministic_comparison_result=deterministic_comparison_result,
        )


# ---------------------------------------------------------------------------
# 1. Wikidata entity/static fact connector
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _WikidataEntity:
    qid: str
    canonical_name: str
    aliases: tuple[str, ...] = ()
    inception_year: int | None = None
    headquarters: str | None = None
    location: str | None = None
    birth_year: int | None = None
    death_year: int | None = None
    office_terms: tuple = ()


@dataclass(frozen=True)
class _OfficeTerm:
    role: str
    jurisdiction: str
    start_year: int
    end_year: int | None = None


DEFAULT_WIKIDATA_ENTITIES = (
    _WikidataEntity(
        qid="Q24283660",
        canonical_name="openai",
        aliases=("open ai",),
        inception_year=2015,
        headquarters="san francisco",
    ),
    _WikidataEntity(
        qid="Q172",
        canonical_name="toronto",
        location="ontario",
    ),
    _WikidataEntity(
        qid="Q937",
        canonical_name="albert einstein",
        aliases=("einstein",),
        birth_year=1879,
        death_year=1955,
    ),
    _WikidataEntity(
        qid="Q309972",
        canonical_name="justin trudeau",
        office_terms=(
            _OfficeTerm(
                role="prime minister", jurisdiction="canada", start_year=2015, end_year=2025
            ),
        ),
    ),
)


class WikidataEntityConnector(BaseEvidenceConnector):
    """
    Wikidata-backed connector for static entity facts.

    Returns EvidenceItem objects with deterministic comparison for narrow
    claim families (inception, headquarters, location, birth, death, office).
    Absence in the local snapshot yields no evidence; the synthesis engine
    then routes to INSUFFICIENT per Rule I.
    """

    def __init__(self, entities: Iterable[_WikidataEntity] | None = None):
        snapshots = list(entities) if entities is not None else list(DEFAULT_WIKIDATA_ENTITIES)
        self._entities = snapshots
        self._alias_index: dict[str, list[_WikidataEntity]] = {}
        for entity in snapshots:
            alias_set = {entity.canonical_name.lower(), *(a.lower() for a in entity.aliases)}
            for alias in alias_set:
                self._alias_index.setdefault(alias, []).append(entity)

    @property
    def connector_id(self) -> str:
        return "wikidata_entity_v15"

    @property
    def connector_version(self) -> str:
        return "v1.5.0"

    def _resolve_entity(self, alias: str) -> _WikidataEntity | None:
        matches = self._alias_index.get(alias.strip().lower(), [])
        if len(matches) != 1:
            return None
        return matches[0]

    def retrieve(self, subclaim: AtomicSubclaim) -> list[EvidenceItem]:
        parsed = self._parse_claim(subclaim.text)
        if parsed is None:
            return []

        entity = self._resolve_entity(parsed["entity"])
        if entity is None:
            return []

        result = parsed["resolver"](entity, parsed)
        if result is None:
            return []

        direction, excerpt, claimed_val, source_val, comparison = result
        group_id = f"wikidata:{entity.qid}"
        item = self._make_item(
            subclaim=subclaim,
            source_type=SourceType.WIKIDATA,
            source_tier=2,  # Wikidata with structured reference path treated as Tier 2 per 03_PIPELINE.md
            retrieval_path=RetrievalPath.DIRECT_CONNECTOR,
            source_url=f"https://www.wikidata.org/wiki/{entity.qid}",
            source_title=f"Wikidata entity data for {entity.canonical_name.title()}",
            source_authority="Wikidata Foundation",
            quote_or_span=excerpt,
            direction=direction,
            direction_confidence=1.0,
            direction_method=DirectionMethod.DETERMINISTIC_STRUCTURED,
            relevance_score=1.0,
            group_id=group_id,
            claimed_value=claimed_val,
            source_value=source_val,
            deterministic_comparison_result=comparison,
        )
        return [item]

    # ------------------------------------------------------------------
    # Parsers
    # ------------------------------------------------------------------

    def _parse_claim(self, claim: str) -> dict[str, Any] | None:
        for handler in (
            self._parse_inception,
            self._parse_headquarters,
            self._parse_location,
            self._parse_birth,
            self._parse_death,
            self._parse_life_status,
            self._parse_office,
        ):
            parsed = handler(claim)
            if parsed is not None:
                return parsed
        return None

    @staticmethod
    def _parse_inception(claim: str) -> dict[str, Any] | None:
        m = re.match(r"^(?P<entity>.+?) was founded in (?P<year>\d{4})\.?$", claim)
        if not m:
            return None
        return {
            "entity": m.group("entity").strip(),
            "year": int(m.group("year")),
            "resolver": WikidataEntityConnector._resolve_inception,
        }

    @staticmethod
    def _parse_headquarters(claim: str) -> dict[str, Any] | None:
        m = re.match(r"^(?P<entity>.+?) is headquartered in (?P<place>.+?)\.?$", claim)
        if not m:
            return None
        return {
            "entity": m.group("entity").strip(),
            "place": m.group("place").strip(),
            "resolver": WikidataEntityConnector._resolve_headquarters,
        }

    @staticmethod
    def _parse_location(claim: str) -> dict[str, Any] | None:
        m = re.match(r"^(?P<entity>.+?) is (?:located )?in (?P<place>.+?)\.?$", claim)
        if not m:
            return None
        return {
            "entity": m.group("entity").strip(),
            "place": m.group("place").strip(),
            "resolver": WikidataEntityConnector._resolve_location,
        }

    @staticmethod
    def _parse_birth(claim: str) -> dict[str, Any] | None:
        m = re.match(r"^(?P<entity>.+?) was born in (?P<year>\d{4})\.?$", claim)
        if not m:
            return None
        return {
            "entity": m.group("entity").strip(),
            "year": int(m.group("year")),
            "resolver": WikidataEntityConnector._resolve_birth,
        }

    @staticmethod
    def _parse_death(claim: str) -> dict[str, Any] | None:
        m = re.match(r"^(?P<entity>.+?) died in (?P<year>\d{4})\.?$", claim)
        if not m:
            return None
        return {
            "entity": m.group("entity").strip(),
            "year": int(m.group("year")),
            "resolver": WikidataEntityConnector._resolve_death,
        }

    @staticmethod
    def _parse_life_status(claim: str) -> dict[str, Any] | None:
        m = re.match(r"^(?P<entity>.+?) (?:is|was) (?P<status>alive|dead)\.?$", claim)
        if not m:
            return None
        return {
            "entity": m.group("entity").strip(),
            "status": m.group("status").strip(),
            "resolver": WikidataEntityConnector._resolve_life_status,
        }

    @staticmethod
    def _parse_office(claim: str) -> dict[str, Any] | None:
        m = re.match(
            r"^(?P<entity>.+?) (?:is|was) (?:the )?(?P<role>prime minister|president|mayor|governor|ceo|chief executive officer) of (?P<jurisdiction>.+?)(?: in (?P<year>\d{4}))?\.?$",
            claim,
        )
        if not m or m.group("year") is None:
            return None
        return {
            "entity": m.group("entity").strip(),
            "role": m.group("role").strip(),
            "jurisdiction": m.group("jurisdiction").strip(),
            "year": int(m.group("year")),
            "resolver": WikidataEntityConnector._resolve_office,
        }

    # ------------------------------------------------------------------
    # Resolvers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_inception(entity: _WikidataEntity, parsed: dict[str, Any]):
        if entity.inception_year is None:
            return None
        claimed = parsed["year"]
        match = entity.inception_year == claimed
        direction = Direction.SUPPORTS if match else Direction.REFUTES
        excerpt = f"Wikidata inception year for {entity.canonical_name.title()} is {entity.inception_year}."
        claimed_val = ResolvedValue(value=claimed, value_type=ValueType.NUMBER, unit="year")
        source_val = ResolvedValue(
            value=entity.inception_year, value_type=ValueType.NUMBER, unit="year"
        )
        comparison = (
            DeterministicComparisonResult.MATCH if match else DeterministicComparisonResult.MISMATCH
        )
        return direction, excerpt, claimed_val, source_val, comparison

    @staticmethod
    def _resolve_headquarters(entity: _WikidataEntity, parsed: dict[str, Any]):
        if not entity.headquarters:
            return None
        claimed_place = str(parsed["place"]).lower()
        match = entity.headquarters.lower() == claimed_place
        direction = Direction.SUPPORTS if match else Direction.REFUTES
        excerpt = f"Wikidata headquarters location for {entity.canonical_name.title()} is {entity.headquarters.title()}."
        claimed_val = ResolvedValue(value=claimed_place, value_type=ValueType.TEXT)
        source_val = ResolvedValue(value=entity.headquarters.lower(), value_type=ValueType.TEXT)
        comparison = (
            DeterministicComparisonResult.MATCH if match else DeterministicComparisonResult.MISMATCH
        )
        return direction, excerpt, claimed_val, source_val, comparison

    @staticmethod
    def _resolve_location(entity: _WikidataEntity, parsed: dict[str, Any]):
        if not entity.location:
            return None
        claimed_place = str(parsed["place"]).lower()
        match = entity.location.lower() == claimed_place
        direction = Direction.SUPPORTS if match else Direction.REFUTES
        excerpt = f"Wikidata administrative location for {entity.canonical_name.title()} is {entity.location.title()}."
        claimed_val = ResolvedValue(value=claimed_place, value_type=ValueType.TEXT)
        source_val = ResolvedValue(value=entity.location.lower(), value_type=ValueType.TEXT)
        comparison = (
            DeterministicComparisonResult.MATCH if match else DeterministicComparisonResult.MISMATCH
        )
        return direction, excerpt, claimed_val, source_val, comparison

    @staticmethod
    def _resolve_birth(entity: _WikidataEntity, parsed: dict[str, Any]):
        if entity.birth_year is None:
            return None
        claimed = parsed["year"]
        match = entity.birth_year == claimed
        direction = Direction.SUPPORTS if match else Direction.REFUTES
        excerpt = f"Wikidata birth year for {entity.canonical_name.title()} is {entity.birth_year}."
        claimed_val = ResolvedValue(value=claimed, value_type=ValueType.NUMBER, unit="year")
        source_val = ResolvedValue(
            value=entity.birth_year, value_type=ValueType.NUMBER, unit="year"
        )
        comparison = (
            DeterministicComparisonResult.MATCH if match else DeterministicComparisonResult.MISMATCH
        )
        return direction, excerpt, claimed_val, source_val, comparison

    @staticmethod
    def _resolve_death(entity: _WikidataEntity, parsed: dict[str, Any]):
        if entity.death_year is None:
            return None
        claimed = parsed["year"]
        match = entity.death_year == claimed
        direction = Direction.SUPPORTS if match else Direction.REFUTES
        excerpt = f"Wikidata death year for {entity.canonical_name.title()} is {entity.death_year}."
        claimed_val = ResolvedValue(value=claimed, value_type=ValueType.NUMBER, unit="year")
        source_val = ResolvedValue(
            value=entity.death_year, value_type=ValueType.NUMBER, unit="year"
        )
        comparison = (
            DeterministicComparisonResult.MATCH if match else DeterministicComparisonResult.MISMATCH
        )
        return direction, excerpt, claimed_val, source_val, comparison

    @staticmethod
    def _resolve_life_status(entity: _WikidataEntity, parsed: dict[str, Any]):
        claimed_status = str(parsed["status"]).lower()
        actual_status = "dead" if entity.death_year is not None else "alive"
        match = claimed_status == actual_status
        direction = Direction.SUPPORTS if match else Direction.REFUTES
        excerpt = f"Wikidata life status for {entity.canonical_name.title()} is {actual_status}."
        claimed_val = ResolvedValue(value=claimed_status, value_type=ValueType.TEXT)
        source_val = ResolvedValue(value=actual_status, value_type=ValueType.TEXT)
        comparison = (
            DeterministicComparisonResult.MATCH if match else DeterministicComparisonResult.MISMATCH
        )
        return direction, excerpt, claimed_val, source_val, comparison

    @staticmethod
    def _resolve_office(entity: _WikidataEntity, parsed: dict[str, Any]):
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
        match = matching_term.start_year <= year <= end_year
        direction = Direction.SUPPORTS if match else Direction.REFUTES
        excerpt = (
            f"Wikidata office term for {entity.canonical_name.title()} as {matching_term.role.title()} "
            f"of {matching_term.jurisdiction.title()} spans {matching_term.start_year}-{matching_term.end_year or 'present'}."
        )
        claimed_val = ResolvedValue(value=year, value_type=ValueType.NUMBER, unit="year")
        source_val = ResolvedValue(
            value=matching_term.start_year,
            value_type=ValueType.NUMBER,
            unit="year",
            lower_bound=float(matching_term.start_year),
            upper_bound=float(end_year),
        )
        comparison = (
            DeterministicComparisonResult.MATCH if match else DeterministicComparisonResult.MISMATCH
        )
        return direction, excerpt, claimed_val, source_val, comparison


# ---------------------------------------------------------------------------
# 2. BLS official statistics connector
# ---------------------------------------------------------------------------


class BLSStatisticsConnector(BaseEvidenceConnector):
    """
    U.S. Bureau of Labor Statistics API connector for employment and
    inflation statistics.

    Requires BLS_API_KEY environment variable for live queries.
    Without a key the connector returns empty evidence (no failure).
    """

    BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

    # Small fixture of well-known series IDs for deterministic offline behaviour
    _SERIES_FIXTURES: dict[str, dict[str, Any]] = {
        "unemployment rate": {"series_id": "LNS14000000", "unit": "percent"},
        "cpi": {"series_id": "CUUR0000SA0", "unit": "index"},
        "nonfarm payroll": {"series_id": "CES0000000001", "unit": "thousands"},
    }

    def __init__(self, api_key: str | None = None, timeout_seconds: float = 10.0):
        self._api_key = api_key or os.environ.get("BLS_API_KEY", "")
        self._timeout = timeout_seconds

    @property
    def connector_id(self) -> str:
        return "bls_statistics_v15"

    @property
    def connector_version(self) -> str:
        return "v1.5.0"

    def _bls_api_enabled(self) -> bool:
        return bool(self._api_key)

    def retrieve(self, subclaim: AtomicSubclaim) -> list[EvidenceItem]:
        # Heuristic: look for numeric-statistical claims about US labour / price data
        text_lower = subclaim.text.lower()

        matched_series: str | None = None
        for keyword, _meta in self._SERIES_FIXTURES.items():
            if keyword in text_lower:
                matched_series = keyword
                break

        if matched_series is None:
            return []

        # If live API is available, attempt it; otherwise return fixture-backed
        # evidence so the connector is still testable offline.
        if self._bls_api_enabled():
            try:
                return self._query_live_api(subclaim, matched_series)
            except Exception:
                # Connector failure should not crash pipeline;
                # returning no evidence lets synthesis emit connector_failure
                # if the caller sets connector_failure_subclaim_ids.
                return []

        # Offline fixture path: return a placeholder Tier 1 item with NEUTRAL
        # direction so it does not falsely resolve claims in offline mode.
        return self._offline_placeholder(subclaim, matched_series)

    @staticmethod
    def _extract_claimed_value(text: str) -> ResolvedValue | None:
        """Extract a numeric claimed value from subclaim text."""
        import re

        m = re.search(r"(\d+(?:\.\d+)?)\s*(percent|%)?", text.lower())
        if not m:
            return None
        val = float(m.group(1))
        unit = "percent" if m.group(2) else "index"
        return ResolvedValue(value=val, value_type=ValueType.NUMBER, unit=unit)

    @staticmethod
    def _compare_values(
        claimed: ResolvedValue | None, source: ResolvedValue
    ) -> DeterministicComparisonResult:
        if claimed is None or claimed.value is None or source.value is None:
            return DeterministicComparisonResult.NOT_COMPARABLE
        try:
            match = float(claimed.value) == float(source.value)
            return (
                DeterministicComparisonResult.MATCH
                if match
                else DeterministicComparisonResult.MISMATCH
            )
        except Exception:
            return DeterministicComparisonResult.NOT_COMPARABLE

    def _query_live_api(self, subclaim: AtomicSubclaim, series_keyword: str) -> list[EvidenceItem]:
        meta = self._SERIES_FIXTURES[series_keyword]
        series_id = meta["series_id"]

        payload = {
            "seriesid": [series_id],
            "startyear": str(datetime.now().year - 2),
            "endyear": str(datetime.now().year),
            "registrationkey": self._api_key,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.BLS_API_URL,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        series_list = result.get("Results", {}).get("series", [])
        if not series_list:
            return []

        latest = None
        for s in series_list:
            for dp in s.get("data", []):
                if latest is None or dp.get("year", "0") > latest.get("year", "0"):
                    latest = dp
                elif dp.get("year") == latest.get("year") and dp.get("period", "M00") > latest.get(
                    "period", "M00"
                ):
                    latest = dp

        if latest is None:
            return []

        value = float(latest["value"])
        source_val = ResolvedValue(value=value, value_type=ValueType.NUMBER, unit=meta["unit"])
        claimed_val = self._extract_claimed_value(subclaim.text)
        comparison = self._compare_values(claimed_val, source_val)
        direction = (
            Direction.SUPPORTS
            if comparison == DeterministicComparisonResult.MATCH
            else Direction.REFUTES
            if comparison == DeterministicComparisonResult.MISMATCH
            else Direction.NEUTRAL
        )
        item = self._make_item(
            subclaim=subclaim,
            source_type=SourceType.OFFICIAL_STAT,
            source_tier=1,
            retrieval_path=RetrievalPath.DIRECT_CONNECTOR,
            source_url="https://www.bls.gov",
            source_title=f"BLS Series {series_id}",
            source_authority="U.S. Bureau of Labor Statistics",
            quote_or_span=f"BLS {series_id} {latest.get('year')} {latest.get('period')}: {value}",
            direction=direction,
            direction_confidence=1.0,
            direction_method=DirectionMethod.DETERMINISTIC_STRUCTURED,
            relevance_score=0.9,
            group_id=f"bls:{series_id}",
            claimed_value=claimed_val,
            source_value=source_val,
            deterministic_comparison_result=comparison,
        )
        return [item]

    def _offline_placeholder(
        self, subclaim: AtomicSubclaim, series_keyword: str
    ) -> list[EvidenceItem]:
        meta = self._SERIES_FIXTURES[series_keyword]
        series_id = meta["series_id"]
        # Build a canonical, deterministic payload so raw_response_hash is stable across runs.
        # The payload must include every field that affects the hash.
        placeholder_payload = json.dumps(
            {
                "connector_id": self.connector_id,
                "connector_version": self.connector_version,
                "series_keyword": series_keyword,
                "series_id": series_id,
                "subclaim_id": subclaim.subclaim_id,
                "claim_text": subclaim.text,
                "status": "offline_placeholder",
                "reason": "BLS_API_KEY unavailable",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        raw_response_hash = hashlib.sha256(placeholder_payload.encode("utf-8")).hexdigest()[:32]
        item = EvidenceItem(
            subclaim_id=subclaim.subclaim_id,
            source_type=SourceType.OFFICIAL_STAT,
            source_tier=1,
            retrieval_path=RetrievalPath.OFFLINE_PLACEHOLDER,
            source_url="https://www.bls.gov",
            source_title=f"BLS Series {series_id} (offline placeholder)",
            source_authority="U.S. Bureau of Labor Statistics",
            quote_or_span=f"Offline placeholder for BLS series {series_id}. Live API requires BLS_API_KEY.",
            relevance_score=0.5,
            direction=Direction.NEUTRAL,
            direction_confidence=1.0,
            direction_method=DirectionMethod.DETERMINISTIC_STRUCTURED,
            retrieval_timestamp=self._now_iso(),
            connector_version=self.connector_version,
            connector_query_hash=self._query_hash(subclaim.text),
            raw_response_hash=raw_response_hash,
            source_independence_group_id=f"bls:{series_id}",
        )
        return [item]


# ---------------------------------------------------------------------------
# 3. Crossref scientific metadata connector
# ---------------------------------------------------------------------------


class CrossrefConnector(BaseEvidenceConnector):
    """
    Crossref REST API connector for DOI-based scientific metadata.

    No API key is required for low-volume polite use (mailto header).
    Returns Tier 1 evidence when a DOI is resolved; Tier 2 for query matches.
    """

    CROSSREF_WORKS_URL = "https://api.crossref.org/works"

    def __init__(self, timeout_seconds: float = 10.0, email: str | None = None):
        self._timeout = timeout_seconds
        self._email = email or os.environ.get("CROSSREF_EMAIL", "")

    @property
    def connector_id(self) -> str:
        return "crossref_v15"

    @property
    def connector_version(self) -> str:
        return "v1.5.0"

    def retrieve(self, subclaim: AtomicSubclaim) -> list[EvidenceItem]:
        text_lower = subclaim.text.lower()

        # Heuristic 1: explicit DOI in claim text
        doi_match = re.search(r"10\.\d{4,}/[^\s]+", subclaim.text)
        if doi_match:
            doi = doi_match.group(0).rstrip(".,;")
            return self._query_doi(subclaim, doi, tier=1)

        # Heuristic 2: scientific claim about a study — query Crossref
        if subclaim.claim_type == ClaimType.SCIENTIFIC:
            return self._query_search(subclaim, text_lower)

        return []

    def _query_doi(self, subclaim: AtomicSubclaim, doi: str, tier: int) -> list[EvidenceItem]:
        if not self._email:
            # Without polite header, still attempt but may be rate-limited
            pass

        url = f"{self.CROSSREF_WORKS_URL}/{doi}"
        headers = {}
        if self._email:
            headers["User-Agent"] = f"LSD-FactCheck/1.5 (mailto:{self._email})"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return []
            return []
        except Exception:
            return []

        message = data.get("message", {})
        title = " ".join(message.get("title", ["Unknown"]))
        authors = message.get("author", [])
        author_str = ", ".join(f"{a.get('family', '')}" for a in authors[:3])
        published = message.get("published-print") or message.get("published-online")
        year = None
        if published and published.get("date-parts"):
            year = published["date-parts"][0][0] if published["date-parts"][0] else None

        excerpt = f"Crossref DOI {doi}: {title}. Authors: {author_str}."
        if year:
            excerpt += f" Year: {year}."

        item = self._make_item(
            subclaim=subclaim,
            source_type=SourceType.SCIENTIFIC_DB,
            source_tier=tier,
            retrieval_path=RetrievalPath.DIRECT_CONNECTOR,
            source_url=message.get("URL", f"https://doi.org/{doi}"),
            source_title=title,
            source_authority="Crossref",
            quote_or_span=excerpt,
            direction=Direction.NEUTRAL,
            direction_confidence=1.0,
            direction_method=DirectionMethod.DETERMINISTIC_STRUCTURED,
            relevance_score=0.9,
            group_id=f"crossref:{doi}",
            source_value=ResolvedValue(value=year, value_type=ValueType.NUMBER, unit="year")
            if year
            else None,
        )
        return [item]

    def _query_search(self, subclaim: AtomicSubclaim, query: str) -> list[EvidenceItem]:
        if not self._email:
            return []
        qs = urllib.parse.urlencode({"query": query, "rows": "3"})
        url = f"{self.CROSSREF_WORKS_URL}?{qs}"
        headers = {"User-Agent": f"LSD-FactCheck/1.5 (mailto:{self._email})"}
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return []

        items: list[EvidenceItem] = []
        for work in data.get("message", {}).get("items", [])[:3]:
            doi = work.get("DOI", "")
            title = " ".join(work.get("title", ["Unknown"]))
            excerpt = f"Crossref search result: {title}. DOI: {doi}."
            items.append(
                self._make_item(
                    subclaim=subclaim,
                    source_type=SourceType.SCIENTIFIC_DB,
                    source_tier=2,
                    retrieval_path=RetrievalPath.DIRECT_CONNECTOR,
                    source_url=work.get("URL", f"https://doi.org/{doi}"),
                    source_title=title,
                    source_authority="Crossref",
                    quote_or_span=excerpt,
                    direction=Direction.NEUTRAL,
                    direction_confidence=1.0,
                    direction_method=DirectionMethod.DETERMINISTIC_STRUCTURED,
                    relevance_score=0.7,
                    group_id=f"crossref:{doi}" if doi else "crossref:search",
                )
            )
        return items


# ---------------------------------------------------------------------------
# 4. Tier 2 curated source connector
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _CuratedDocument:
    doc_id: str
    title: str
    url: str
    excerpt: str
    authority: str
    date: str | None = None


DEFAULT_CURATED_DOCUMENTS = (
    _CuratedDocument(
        doc_id="wiki_openai",
        title="OpenAI — Wikipedia",
        url="https://en.wikipedia.org/wiki/OpenAI",
        excerpt="OpenAI is an American artificial intelligence research organization founded in December 2015.",
        authority="Wikipedia Foundation",
    ),
    _CuratedDocument(
        doc_id="wiki_toronto",
        title="Toronto — Wikipedia",
        url="https://en.wikipedia.org/wiki/Toronto",
        excerpt="Toronto is the capital city of the Canadian province of Ontario.",
        authority="Wikipedia Foundation",
    ),
    _CuratedDocument(
        doc_id="wiki_einstein",
        title="Albert Einstein — Wikipedia",
        url="https://en.wikipedia.org/wiki/Albert_Einstein",
        excerpt="Albert Einstein was born in the German Empire on 14 March 1879.",
        authority="Wikipedia Foundation",
    ),
)


class CuratedRAGConnector(BaseEvidenceConnector):
    """
    Tier 2 curated source connector backed by a small allowlisted document set.

    In production this would be backed by a vector DB with cross-encoder
    re-ranking. For Phase 4 we use deterministic keyword matching against
    a bundled fixture so tests remain reproducible without network access.
    """

    def __init__(self, documents: Iterable[_CuratedDocument] | None = None):
        self._docs = list(documents) if documents is not None else list(DEFAULT_CURATED_DOCUMENTS)

    @property
    def connector_id(self) -> str:
        return "curated_rag_v15"

    @property
    def connector_version(self) -> str:
        return "v1.5.0"

    def retrieve(self, subclaim: AtomicSubclaim) -> list[EvidenceItem]:
        text_lower = subclaim.text.lower()
        items: list[EvidenceItem] = []
        for doc in self._docs:
            score = self._relevance(doc, text_lower)
            if score < 0.3:
                continue
            # Deterministic direction via simple keyword heuristics
            direction, confidence = self._classify_direction(doc, text_lower)
            items.append(
                self._make_item(
                    subclaim=subclaim,
                    source_type=SourceType.WIKIPEDIA,
                    source_tier=2,
                    retrieval_path=RetrievalPath.RAG_RETRIEVAL,
                    source_url=doc.url,
                    source_title=doc.title,
                    source_authority=doc.authority,
                    quote_or_span=doc.excerpt,
                    direction=direction,
                    direction_confidence=confidence,
                    direction_method=DirectionMethod.DETERMINISTIC_STRUCTURED,  # deterministic keyword matching
                    relevance_score=score,
                    group_id=f"curated:{doc.doc_id}",
                )
            )
        # Max 10 documents per subclaim per policy
        return items[:10]

    def _relevance(self, doc: _CuratedDocument, query_lower: str) -> float:
        words = set(query_lower.split())
        doc_words = set(doc.excerpt.lower().split())
        if not words:
            return 0.0
        overlap = len(words & doc_words) / len(words)
        # Boost exact title match
        title_words = set(doc.title.lower().split())
        if words & title_words:
            overlap = min(1.0, overlap + 0.3)
        return round(overlap, 2)

    def _classify_direction(
        self, doc: _CuratedDocument, query_lower: str
    ) -> tuple[Direction, float]:
        # Very conservative: only SUPPORTS if strong keyword overlap,
        # otherwise NEUTRAL/UNCLEAR so Tier 2 cross-verification is required.
        score = self._relevance(doc, query_lower)
        if score >= 0.7:
            return Direction.SUPPORTS, 0.85
        if score >= 0.5:
            return Direction.NEUTRAL, 0.7
        return Direction.UNCLEAR, 0.5


# ---------------------------------------------------------------------------
# 5. Tier 3 search/discovery connector
# ---------------------------------------------------------------------------


class BraveSearchConnector(BaseEvidenceConnector):
    """
    Tier 3 search/discovery connector using the Brave Search API.

    Returns Tier 3 evidence only.  Tier 3 evidence cannot alone support or
    refute a claim (synthesis Rule H).

    Without BRAVE_API_KEY the connector returns empty evidence so CI
    pipelines skip it cleanly.
    """

    BRAVE_API_URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, api_key: str | None = None, timeout_seconds: float = 10.0):
        self._api_key = api_key or os.environ.get("BRAVE_API_KEY", "")
        self._timeout = timeout_seconds

    @property
    def connector_id(self) -> str:
        return "brave_search_v15"

    @property
    def connector_version(self) -> str:
        return "v1.5.0"

    def retrieve(self, subclaim: AtomicSubclaim) -> list[EvidenceItem]:
        if not self._api_key:
            # No key -> no evidence.  This is a clean skip, not a failure.
            return []

        try:
            return self._query_api(subclaim)
        except Exception:
            # Connector failures are surfaced by the caller via
            # connector_failure_subclaim_ids if desired.
            return []

    def _query_api(self, subclaim: AtomicSubclaim) -> list[EvidenceItem]:
        qs = urllib.parse.urlencode({"q": subclaim.text, "count": "5"})
        url = f"{self.BRAVE_API_URL}?{qs}"
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": self._api_key,
            },
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        items: list[EvidenceItem] = []
        for idx, result in enumerate(data.get("web", {}).get("results", [])[:5]):
            title = result.get("title", "")
            snippet = result.get("description", "")
            page_url = result.get("url", "")
            items.append(
                self._make_item(
                    subclaim=subclaim,
                    source_type=SourceType.WEB,
                    source_tier=3,
                    retrieval_path=RetrievalPath.LIVE_SEARCH_DISCOVERY,
                    source_url=page_url,
                    source_title=title,
                    source_authority="Brave Search",
                    quote_or_span=snippet,
                    direction=Direction.NEUTRAL,
                    direction_confidence=0.5,
                    direction_method=DirectionMethod.LLM_CLASSIFIER,
                    relevance_score=0.4,
                    group_id=f"brave:{idx}",
                )
            )
        return items


# ---------------------------------------------------------------------------
# Connector registry / factory
# ---------------------------------------------------------------------------


class ConnectorRegistry:
    """Convenience registry for instantiating the Phase 4 connector set."""

    @staticmethod
    def default_connectors() -> list[BaseEvidenceConnector]:
        return [
            WikidataEntityConnector(),
            BLSStatisticsConnector(),
            CrossrefConnector(),
            CuratedRAGConnector(),
            BraveSearchConnector(),
        ]

    @staticmethod
    def offline_connectors() -> list[BaseEvidenceConnector]:
        """Connectors that work without API keys or network access."""
        return [
            WikidataEntityConnector(),
            CuratedRAGConnector(),
        ]
