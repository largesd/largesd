"""
LSD §11 Selection-Transparency Layer

Deterministic stratified selection for canonical facts and arguments in the
Blind LLM-Adjudicated Debate System.

Responsibilities
----------------
- Compute centrality = log(1 + distinct_AU_refs) per canonical item.
- Cap centrality at P95 within each (topic, side, type) pool.
- Score items with a simple, monotone, published function.
- Reserve a rarity slice (ρ) for low-centrality items.
- Publish selection recipes and diagnostics.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Tuple
import hashlib
import math
from datetime import datetime

import numpy as np


@dataclass
class SelectionRecipe:
    """
    Immutable, publishable record of the selection parameters used for a run.
    """
    seed: int
    rho: float = 0.20
    low_centrality_quantile: float = 0.60
    centrality_cap_percentile: float = 95.0
    version: str = "lsd-11-v1.2"
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    score_formula: str = "centrality_capped + 0.1 * distinct_support + quality_proxy"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SelectedSet:
    """
    Result of a selection run with full provenance and diagnostics.
    """
    recipe: SelectionRecipe
    topic_id: str
    side: str
    selected_facts: List[Dict[str, Any]] = field(default_factory=list)
    selected_arguments: List[Dict[str, Any]] = field(default_factory=list)
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    @property
    def selected_fact_ids(self) -> List[str]:
        return [SelectionEngine._canon_id(f) for f in self.selected_facts]

    @property
    def selected_arg_ids(self) -> List[str]:
        return [SelectionEngine._canon_id(a) for a in self.selected_arguments]


class SelectionEngine:
    """
    Deterministic selection engine implementing LSD §11.

    Works with dictionary-like canonical facts and arguments, but also
    tolerates dataclass instances via generic field access helpers.
    """

    def __init__(
        self,
        rho: float = 0.20,
        low_centrality_quantile: float = 0.60,
        centrality_cap_percentile: float = 95.0,
    ):
        self.rho = float(rho)
        self.low_centrality_quantile = float(low_centrality_quantile)
        self.centrality_cap_percentile = float(centrality_cap_percentile)

    # --------------------------------------------------------------------- #
    #  Field-access helpers (dicts or objects)
    # --------------------------------------------------------------------- #
    @staticmethod
    def _get_field(item: Any, key: str, default: Any = None) -> Any:
        if isinstance(item, dict):
            return item.get(key, default)
        return getattr(item, key, default)

    @classmethod
    def _canon_id(cls, item: Any) -> str:
        return cls._get_field(item, "canon_fact_id") or cls._get_field(item, "canon_arg_id")

    @classmethod
    def _au_refs(cls, item: Any) -> int:
        """Distinct AU references used for raw centrality."""
        refs = cls._get_field(item, "referenced_by_au_ids") or cls._get_field(item, "member_au_ids")
        if refs is None:
            return 0
        return len(refs)

    @classmethod
    def _distinct_support(cls, item: Any) -> int:
        return int(cls._get_field(item, "distinct_support", 0))

    @classmethod
    def _quality_proxy(cls, item: Any) -> float:
        """
        Quality proxy:
        - Arguments -> reasoning_score
        - Facts     -> p_true
        - Fallback  -> 1.0
        """
        if cls._get_field(item, "reasoning_score") is not None:
            return float(cls._get_field(item, "reasoning_score"))
        if cls._get_field(item, "p_true") is not None:
            return float(cls._get_field(item, "p_true"))
        return 1.0

    @classmethod
    def _raw_centrality(cls, item: Any) -> float:
        """log(1 + distinct_AU_refs) per LSD §11.3."""
        return math.log1p(cls._au_refs(item))

    # --------------------------------------------------------------------- #
    #  Scoring & hashing
    # --------------------------------------------------------------------- #
    @classmethod
    def _compute_score(cls, item: Any, centrality_map: Dict[str, float]) -> float:
        """
        Published selection score.

        S(canon_id) = centrality_capped
                    + 0.1 * distinct_support
                    + quality_proxy

        All terms are monotone; the function is simple and fully auditable.
        """
        cid = cls._canon_id(item)
        cent = centrality_map.get(cid, 0.0)
        sup = cls._distinct_support(item)
        qual = cls._quality_proxy(item)
        return cent + 0.1 * sup + qual

    @staticmethod
    def _hash_tiebreak(seed: int, canon_id: str) -> int:
        """
        Deterministic tie-break via stable hash(seed, canon_id).
        Uses SHA-256 to guarantee cross-platform stability.
        """
        digest = hashlib.sha256(f"{seed}:{canon_id}".encode("utf-8")).hexdigest()
        return int(digest, 16)

    # --------------------------------------------------------------------- #
    #  Centrality
    # --------------------------------------------------------------------- #
    @classmethod
    def _compute_centrality(
        cls, items: List[Any], type_label: str, cap_percentile: float = 95.0
    ) -> Tuple[Dict[str, float], Dict[str, Any]]:
        """
        Compute raw centrality and cap at the given percentile.

        Returns
        -------
        centrality_map : dict
            canon_id -> capped centrality
        meta : dict
            Diagnostics about the pool and cap applied.
        """
        raw_cents: List[float] = []
        centrality_map: Dict[str, float] = {}

        for item in items:
            cid = cls._canon_id(item)
            raw = cls._raw_centrality(item)
            centrality_map[cid] = raw
            raw_cents.append(raw)

        cap_value: Optional[float] = None
        if raw_cents:
            cap_value = float(np.percentile(raw_cents, cap_percentile))
            for cid in centrality_map:
                if centrality_map[cid] > cap_value:
                    centrality_map[cid] = cap_value

        meta = {
            "type_label": type_label,
            "pool_size": len(items),
            "p95_cap": cap_value,
            "raw_centrality_mean": float(np.mean(raw_cents)) if raw_cents else 0.0,
            "raw_centrality_max": max(raw_cents) if raw_cents else 0.0,
        }
        return centrality_map, meta

    # --------------------------------------------------------------------- #
    #  Selection slices
    # --------------------------------------------------------------------- #
    @classmethod
    def _select_majority(
        cls, items: List[Any], budget: int, centrality_map: Dict[str, float], seed: int
    ) -> List[Any]:
        """
        MAJORITY slice: select top `budget` items by score from the full pool.
        Ties broken deterministically by hash(seed, canon_id).
        """
        if budget <= 0 or not items:
            return []

        scored = []
        for item in items:
            cid = cls._canon_id(item)
            score = cls._compute_score(item, centrality_map)
            tiebreak = cls._hash_tiebreak(seed, cid)
            scored.append((score, tiebreak, item))

        # Descending by score, then descending by deterministic tie-break
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [item for _, _, item in scored[:budget]]

    @classmethod
    def _select_rarity(
        cls,
        items: List[Any],
        budget: int,
        centrality_map: Dict[str, float],
        seed: int,
        low_centrality_quantile: float = 0.60,
    ) -> List[Any]:
        """
        RARITY slice: select top `budget` items from the low-centrality subset.

        Low-centrality is defined as the bottom `low_centrality_quantile`
        (default 60 %) by capped centrality within the pool.
        Ties broken deterministically by hash(seed, canon_id).
        """
        if budget <= 0 or not items:
            return []

        cent_values = [centrality_map.get(cls._canon_id(item), 0.0) for item in items]
        threshold = float(np.quantile(cent_values, low_centrality_quantile)) if cent_values else 0.0

        low_cent_items = [
            item for item in items
            if centrality_map.get(cls._canon_id(item), 0.0) <= threshold
        ]

        if not low_cent_items:
            return []

        scored = []
        for item in low_cent_items:
            cid = cls._canon_id(item)
            score = cls._compute_score(item, centrality_map)
            tiebreak = cls._hash_tiebreak(seed, cid)
            scored.append((score, tiebreak, item))

        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return [item for _, _, item in scored[:budget]]

    # --------------------------------------------------------------------- #
    #  Public API
    # --------------------------------------------------------------------- #
    def select_for_topic_side(
        self,
        facts: List[Any],
        arguments: List[Any],
        topic_id: str,
        side: str,
        budgets: Dict[str, int],
        seed: int,
    ) -> SelectedSet:
        """
        Run deterministic stratified selection for a single (topic, side).

        Parameters
        ----------
        facts : list
            Canonical fact objects/dicts. Expected keys include
            ``canon_fact_id``, ``topic_id``, ``side``, ``p_true``,
            ``referenced_by_au_ids``, ``distinct_support``.
            Facts may optionally carry ``fact_type`` ("empirical" or
            "normative"); items without this field are treated as empirical.
        arguments : list
            Canonical argument objects/dicts. Expected keys include
            ``canon_arg_id``, ``topic_id``, ``side``, ``reasoning_score``,
            ``member_au_ids``, ``distinct_support``.
        topic_id : str
        side : str
        budgets : dict
            Mapping with keys ``K_E``, ``K_N``, ``K_A``.
        seed : int
            Deterministic seed for tie-breaking and any downstream hashing.

        Returns
        -------
        SelectedSet
        """
        recipe = SelectionRecipe(
            seed=seed,
            rho=self.rho,
            low_centrality_quantile=self.low_centrality_quantile,
            centrality_cap_percentile=self.centrality_cap_percentile,
        )

        # Filter to the requested topic-side
        facts_pool = [
            f for f in facts
            if self._get_field(f, "topic_id") == topic_id and self._get_field(f, "side") == side
        ]
        args_pool = [
            a for a in arguments
            if self._get_field(a, "topic_id") == topic_id and self._get_field(a, "side") == side
        ]

        # Split facts by type (empirical vs normative)
        empirical_facts = [
            f for f in facts_pool
            if self._get_field(f, "fact_type", "empirical") == "empirical"
        ]
        normative_facts = [
            f for f in facts_pool
            if self._get_field(f, "fact_type") == "normative"
        ]

        k_e = int(budgets.get("K_E", 0))
        k_n = int(budgets.get("K_N", 0))
        k_a = int(budgets.get("K_A", 0))

        diagnostics: Dict[str, Any] = {
            "topic_id": topic_id,
            "side": side,
            "recipe": recipe.to_dict(),
            "pools": {},
        }

        selected_facts: List[Any] = []
        selected_args: List[Any] = []

        # ---------------------------------------------------------------------
        # Empirical facts (K_E)
        # ---------------------------------------------------------------------
        if k_e > 0 and empirical_facts:
            cent_map, meta = self._compute_centrality(
                empirical_facts, "empirical_fact", self.centrality_cap_percentile
            )
            meta["budget"] = k_e
            meta["pre_mass"] = sum(self._raw_centrality(item) for item in empirical_facts)

            maj_budget = int(math.floor(k_e * (1 - recipe.rho)))
            rare_budget = k_e - maj_budget

            maj = self._select_majority(empirical_facts, maj_budget, cent_map, seed)
            maj_ids = {self._canon_id(m) for m in maj}

            remaining = [item for item in empirical_facts if self._canon_id(item) not in maj_ids]
            rare = self._select_rarity(
                remaining, rare_budget, cent_map, seed, recipe.low_centrality_quantile
            )

            selected_facts.extend(maj)
            selected_facts.extend(rare)

            sel_mass = sum(self._raw_centrality(item) for item in maj + rare)
            meta.update({
                "sel_mass": sel_mass,
                "mass_ratio": sel_mass / meta["pre_mass"] if meta["pre_mass"] > 0 else 0.0,
                "selected_count": len(maj) + len(rare),
                "majority_count": len(maj),
                "rarity_count": len(rare),
                "majority_ids": [self._canon_id(m) for m in maj],
                "rarity_ids": [self._canon_id(r) for r in rare],
            })
            diagnostics["pools"]["empirical_facts"] = meta

        # ---------------------------------------------------------------------
        # Normative facts (K_N)
        # ---------------------------------------------------------------------
        if k_n > 0 and normative_facts:
            cent_map, meta = self._compute_centrality(
                normative_facts, "normative_fact", self.centrality_cap_percentile
            )
            meta["budget"] = k_n
            meta["pre_mass"] = sum(self._raw_centrality(item) for item in normative_facts)

            maj_budget = int(math.floor(k_n * (1 - recipe.rho)))
            rare_budget = k_n - maj_budget

            maj = self._select_majority(normative_facts, maj_budget, cent_map, seed)
            maj_ids = {self._canon_id(m) for m in maj}

            remaining = [item for item in normative_facts if self._canon_id(item) not in maj_ids]
            rare = self._select_rarity(
                remaining, rare_budget, cent_map, seed, recipe.low_centrality_quantile
            )

            selected_facts.extend(maj)
            selected_facts.extend(rare)

            sel_mass = sum(self._raw_centrality(item) for item in maj + rare)
            meta.update({
                "sel_mass": sel_mass,
                "mass_ratio": sel_mass / meta["pre_mass"] if meta["pre_mass"] > 0 else 0.0,
                "selected_count": len(maj) + len(rare),
                "majority_count": len(maj),
                "rarity_count": len(rare),
                "majority_ids": [self._canon_id(m) for m in maj],
                "rarity_ids": [self._canon_id(r) for r in rare],
            })
            diagnostics["pools"]["normative_facts"] = meta

        # ---------------------------------------------------------------------
        # Canonical arguments (K_A)
        # ---------------------------------------------------------------------
        if k_a > 0 and args_pool:
            cent_map, meta = self._compute_centrality(
                args_pool, "canonical_argument", self.centrality_cap_percentile
            )
            meta["budget"] = k_a
            meta["pre_mass"] = sum(self._raw_centrality(item) for item in args_pool)

            maj_budget = int(math.floor(k_a * (1 - recipe.rho)))
            rare_budget = k_a - maj_budget

            maj = self._select_majority(args_pool, maj_budget, cent_map, seed)
            maj_ids = {self._canon_id(m) for m in maj}

            remaining = [item for item in args_pool if self._canon_id(item) not in maj_ids]
            rare = self._select_rarity(
                remaining, rare_budget, cent_map, seed, recipe.low_centrality_quantile
            )

            selected_args.extend(maj)
            selected_args.extend(rare)

            sel_mass = sum(self._raw_centrality(item) for item in maj + rare)
            meta.update({
                "sel_mass": sel_mass,
                "mass_ratio": sel_mass / meta["pre_mass"] if meta["pre_mass"] > 0 else 0.0,
                "selected_count": len(maj) + len(rare),
                "majority_count": len(maj),
                "rarity_count": len(rare),
                "majority_ids": [self._canon_id(m) for m in maj],
                "rarity_ids": [self._canon_id(r) for r in rare],
            })
            diagnostics["pools"]["arguments"] = meta

        return SelectedSet(
            recipe=recipe,
            topic_id=topic_id,
            side=side,
            selected_facts=selected_facts,
            selected_arguments=selected_args,
            diagnostics=diagnostics,
        )

    def get_diagnostics(self, selected_set: SelectedSet) -> Dict[str, Any]:
        """
        Return a human-readable diagnostics report for a ``SelectedSet``.

        The report includes:
        - recipe parameters,
        - per-pool size, budget, and actual selection counts,
        - centrality statistics and P95 cap,
        - PreMass vs SelMass ratios (budget truncation transparency).
        """
        pools = selected_set.diagnostics.get("pools", {})

        report: Dict[str, Any] = {
            "selection_recipe": selected_set.recipe.to_dict(),
            "topic_id": selected_set.topic_id,
            "side": selected_set.side,
            "summary": {
                "total_facts_selected": len(selected_set.selected_facts),
                "total_arguments_selected": len(selected_set.selected_arguments),
            },
            "pool_diagnostics": {},
        }

        for pool_name, meta in pools.items():
            report["pool_diagnostics"][pool_name] = {
                "pool_size": meta.get("pool_size", 0),
                "budget": meta.get("budget", 0),
                "selected": meta.get("selected_count", 0),
                "majority_slice": meta.get("majority_count", 0),
                "rarity_slice": meta.get("rarity_count", 0),
                "centrality_p95_cap": round(meta.get("p95_cap", 0.0), 4),
                "centrality_mean": round(meta.get("raw_centrality_mean", 0.0), 4),
                "pre_mass": round(meta.get("pre_mass", 0.0), 4),
                "sel_mass": round(meta.get("sel_mass", 0.0), 4),
                "mass_ratio": round(meta.get("mass_ratio", 0.0), 4),
            }

        return report
