"""
LSD §5 Frame Registry - Normative Transparency Layer
Implements the Frame Registry dossier (§5.1) for declaring epistemic and ethical commitments.
"""

import hashlib
import json
from dataclasses import dataclass, asdict
from typing import Dict, Optional, Any
from datetime import datetime


@dataclass
class Frame:
    """
    LSD §5.1 Frame Dossier
    Declares the normative framework governing debate conclusions.
    """
    frame_id: str
    version: str
    statement: str  # 1) What is being decided and what is at stake?
    scope: str      # 2) Scope and limits
    grounding_rationale: str  # 3) Grounding/rationale
    inclusion_justification: str  # 4) Inclusion of factors
    exclusion_note: str  # 5) Exclusion note
    known_tensions: list  # 6) Known tensions
    prioritized_values: list  # 7) Prioritized values
    created_at: str
    
    def compute_content_hash(self) -> str:
        """Compute tamper-evident hash of frame content."""
        content = f"{self.statement}|{self.scope}|{self.grounding_rationale}|{self.inclusion_justification}|{self.exclusion_note}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def to_dossier(self) -> Dict[str, Any]:
        """Return public dossier for transparency."""
        return {
            "frame_id": self.frame_id,
            "version": self.version,
            "content_hash": self.compute_content_hash(),
            "dossier": {
                "statement": self.statement,
                "scope": self.scope,
                "grounding_rationale": self.grounding_rationale,
                "inclusion_justification": self.inclusion_justification,
                "exclusion_note": self.exclusion_note,
                "known_tensions": self.known_tensions,
                "prioritized_values": self.prioritized_values
            },
            "created_at": self.created_at
        }


class FrameRegistry:
    """
    Registry for active and historical frames.
    """
    
    def __init__(self):
        self.frames: Dict[str, Frame] = {}
        self.active_frame_id: Optional[str] = None
    
    @classmethod
    def load_default(cls) -> 'FrameRegistry':
        """Load the default LSD v1.2 frame."""
        registry = cls()
        
        # LSD §5.1 Default Frame for Epistemic Debate
        default_frame = Frame(
            frame_id="lsd_v1_2_default",
            version="1.2.0",
            statement=(
                "The decision aims to determine the most epistemically supported conclusion "
                "on a proposition, based on evidence from a diverse set of claimants. "
                "Stake includes: accuracy of belief formation, fair representation of evidence, "
                "and transparency of reasoning to enable audit and appeal."
            ),
            scope=(
                "Applies to structured debates with evidence-bearing claims. "
                "Limits: does not resolve moral questions without empirical premises; "
                "does not guarantee truth—only calibrated confidence based on available evidence."
            ),
            grounding_rationale=(
                "Grounded in deliberative epistemology: well-functioning debate systems "
                "aggregate distributed knowledge, and transparency mechanisms (e.g., dossiers, "
                "snapshots) enable accountability and improvement."
            ),
            inclusion_justification=(
                "Factors included: claimant reliability estimates, evidence quality tiers, "
                "social coherence, dissent signals, source transparency. "
                "Rationale: each factor tracks a distinct epistemic virtue (accuracy, support, "
                "diversity, integrity)."
            ),
            exclusion_note=(
                "Factors excluded: claimant identity when uncorrelated with track record, "
                "emotional valence without evidentiary basis, majority opinion without "
                "quality weighting. Rationale: these factors correlate with bias more than "
                "accuracy in the target domain."
            ),
            known_tensions=[
                "Speed vs thoroughness: faster debates may miss nuanced evidence",
                "Popularity vs quality: widely-shared claims may not be most reliable",
                "Coherence vs diversity: consensus may reflect echo chambers",
                "Transparency vs privacy: full source disclosure may risk harm"
            ],
            prioritized_values=[
                "Epistemic accuracy (calibrated confidence over time)",
                "Procedural fairness (equal opportunity for evidence submission)",
                "Transparency (auditability of reasoning)",
                "Accountability (attribution of claims to sources)"
            ],
            created_at=datetime.utcnow().isoformat()
        )
        
        registry.frames[default_frame.frame_id] = default_frame
        registry.active_frame_id = default_frame.frame_id
        
        return registry
    
    def get_active_frame(self) -> Optional[Frame]:
        """Get the currently active frame."""
        if self.active_frame_id and self.active_frame_id in self.frames:
            return self.frames[self.active_frame_id]
        return None
    
    def get_snapshot_metadata(self) -> Dict[str, Any]:
        """Get frame metadata for snapshot (§9.4.1)."""
        frame = self.get_active_frame()
        if not frame:
            return {}
        
        return {
            "frame_id": frame.frame_id,
            "frame_version": frame.version,
            "frame_hash": frame.compute_content_hash()
        }
    
    def get_public_dossier(self) -> Optional[Dict[str, Any]]:
        """Get the public dossier for the active frame."""
        frame = self.get_active_frame()
        if not frame:
            return None
        return frame.to_dossier()


# Global singleton
_public_registry: Optional[FrameRegistry] = None


def get_public_frame_registry() -> FrameRegistry:
    """Get the global frame registry singleton."""
    global _public_registry
    if _public_registry is None:
        _public_registry = FrameRegistry.load_default()
    return _public_registry
