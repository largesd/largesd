"""
LLM Backend for claim decomposition (Gap 5).

Provides a standard interface for LLM-assisted decomposition with
a deterministic fallback when the LLM fails or is disabled.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Protocol

from .decomposition import CanonicalPremise, validate_decomposition
from .v15_models import (
    AtomicSubclaim,
    ClaimExpression,
    ClaimType,
    NodeType,
    PremiseDecomposition,
    Side,
)


class LLMBackend(Protocol):
    """Protocol for LLM decomposition backends."""

    def decompose_claim(
        self, claim_text: str, claim_type: ClaimType
    ) -> PremiseDecomposition | None:
        """Return a PremiseDecomposition or None if the LLM cannot decompose."""
        ...


class SimpleLLMBackend:
    """
    Simple LLM backend that prompts an LLM client to decompose claims.

    Expects the client to have a ``complete(prompt: str, **kwargs) -> str`` method
    that returns raw text (ideally JSON).
    """

    def __init__(self, client: Any, model: str = "gpt-4"):
        self.client = client
        self.model = model

    def decompose_claim(
        self, claim_text: str, claim_type: ClaimType
    ) -> PremiseDecomposition | None:
        prompt = f"""Decompose this claim into atomic subclaims.

Claim: "{claim_text}"
Claim type: {claim_type.value}

Return a JSON object with:
- subclaims: list of {{"id": "sc_...", "text": "...", "node_type": "ATOMIC|AND|OR"}}
- relationships: how subclaims combine (AND, OR, IF_THEN)

If the claim is already atomic, return a single subclaim."""

        try:
            response = self.client.complete(prompt, model=self.model)
            parsed = json.loads(response)
            return self._parsed_to_decomposition(parsed, claim_text, claim_type, prompt)
        except Exception:
            return None

    def _parsed_to_decomposition(
        self, parsed: dict[str, Any], claim_text: str, claim_type: ClaimType, prompt: str
    ) -> PremiseDecomposition | None:
        premise_id = f"premise_{uuid.uuid4().hex[:12]}"
        subclaims_data = parsed.get("subclaims", [])
        if not subclaims_data:
            return None

        atomic_subclaims: list[AtomicSubclaim] = []
        subclaim_map: dict[str, str] = {}

        for sc in subclaims_data:
            sid = sc.get("id") or f"sc_{uuid.uuid4().hex[:12]}"
            subclaim_map[sc.get("text", "")] = sid
            atomic_subclaims.append(
                AtomicSubclaim(
                    subclaim_id=sid,
                    parent_premise_id=premise_id,
                    text=sc.get("text", ""),
                    claim_type=claim_type,
                )
            )

        # Build root expression from relationships
        relationships = parsed.get("relationships", "ATOMIC")
        if len(atomic_subclaims) == 1:
            root = ClaimExpression(
                node_type=NodeType.ATOMIC, subclaim_id=atomic_subclaims[0].subclaim_id
            )
        elif relationships == "OR":
            root = ClaimExpression(
                node_type=NodeType.OR,
                children=[
                    ClaimExpression(node_type=NodeType.ATOMIC, subclaim_id=sc.subclaim_id)
                    for sc in atomic_subclaims
                ],
            )
        elif relationships == "IF_THEN":
            if len(atomic_subclaims) >= 2:
                root = ClaimExpression(
                    node_type=NodeType.IF_THEN,
                    children=[
                        ClaimExpression(
                            node_type=NodeType.ATOMIC, subclaim_id=atomic_subclaims[0].subclaim_id
                        ),
                        ClaimExpression(
                            node_type=NodeType.ATOMIC, subclaim_id=atomic_subclaims[1].subclaim_id
                        ),
                    ],
                )
            else:
                root = ClaimExpression(
                    node_type=NodeType.ATOMIC, subclaim_id=atomic_subclaims[0].subclaim_id
                )
        else:
            # Default AND
            root = ClaimExpression(
                node_type=NodeType.AND,
                children=[
                    ClaimExpression(node_type=NodeType.ATOMIC, subclaim_id=sc.subclaim_id)
                    for sc in atomic_subclaims
                ],
            )

        prompt_hash = hashlib.sha256((prompt + self.model).encode("utf-8")).hexdigest()[:16]

        decomposition = PremiseDecomposition(
            premise_id=premise_id,
            snapshot_id="llm_decomposition",
            original_text=claim_text,
            topic_id="unknown",
            side=Side.FOR,
            root_claim_expression=root,
            atomic_subclaims=atomic_subclaims,
            decomposition_prompt_hash=prompt_hash,
            decomposition_model_metadata={
                "model": self.model,
                "backend": "SimpleLLMBackend",
            },
        )

        # Validate
        premise = CanonicalPremise(
            premise_id=premise_id,
            snapshot_id="llm_decomposition",
            original_text=claim_text,
            topic_id="unknown",
            side=Side.FOR,
            claim_type=claim_type,
        )
        decomposition.validation_result = validate_decomposition(decomposition, premise)
        return decomposition
