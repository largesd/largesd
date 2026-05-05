"""
"What Evidence Would Change This" Analysis

Per MSD §15:
- Identify arguments with highest leverage (based on d_k and Lev_a)
- List their most decisive supporting FACT nodes (high |p-0.5|)
- For uncertain facts (p near 0.5), suggest evidence that would shift p
- Provide short update triggers: "If FACT X is confirmed/refuted, argument Y changes"
"""

from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
import numpy as np


@dataclass
class EvidenceTarget:
    """A specific evidence target that could change the verdict"""
    target_id: str
    target_type: str  # "fact", "argument", "topic"
    
    # Identification
    title: str
    description: str
    side: str
    
    # Current state
    current_state: str
    current_p: float  # For facts
    
    # Impact analysis
    leverage_score: float  # How much this affects the outcome
    impact_on_margin: float  # Estimated change to D if flipped
    
    # Evidence guidance
    evidence_needed: str  # What evidence would shift this
    evidence_type: str  # "empirical", "statistical", "logical", "expert"
    
    # Update trigger
    update_trigger: str  # "If FACT X is confirmed/refuted..."
    
    # Related items
    related_facts: List[str] = field(default_factory=list)
    related_arguments: List[str] = field(default_factory=list)


@dataclass
class VerdictSensitivity:
    """Analysis of what could change the verdict"""
    verdict: str
    confidence: float
    margin_d: float
    
    # Critical thresholds
    margin_needed_for_flip: float  # How much D needs to change
    
    # Targets
    high_impact_targets: List[EvidenceTarget] = field(default_factory=list)
    medium_impact_targets: List[EvidenceTarget] = field(default_factory=list)
    
    # Summary
    summary: str = ""
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            "verdict": self.verdict,
            "confidence": round(self.confidence, 3),
            "margin_d": round(self.margin_d, 4),
            "margin_needed_for_flip": round(self.margin_needed_for_flip, 4),
            "summary": self.summary,
            "high_impact_targets": [
                {
                    "target_id": t.target_id,
                    "type": t.target_type,
                    "title": t.title,
                    "side": t.side,
                    "current_p": t.current_p,
                    "leverage_score": round(t.leverage_score, 3),
                    "impact_on_margin": round(t.impact_on_margin, 4),
                    "evidence_needed": t.evidence_needed,
                    "evidence_type": t.evidence_type,
                    "update_trigger": t.update_trigger
                }
                for t in self.high_impact_targets
            ],
            "medium_impact_targets": [
                {
                    "target_id": t.target_id,
                    "type": t.target_type,
                    "title": t.title,
                    "side": t.side,
                    "current_p": t.current_p,
                    "leverage_score": round(t.leverage_score, 3),
                    "impact_on_margin": round(t.impact_on_margin, 4),
                    "evidence_needed": t.evidence_needed,
                    "evidence_type": t.evidence_type,
                    "update_trigger": t.update_trigger
                }
                for t in self.medium_impact_targets
            ]
        }


class EvidenceTargetAnalyzer:
    """
    Analyzes what evidence would change the debate verdict.
    
    Per MSD §15:
    - For most influential topics/arguments, identify arguments with highest leverage
    - List their most decisive supporting FACT nodes
    - For uncertain facts, suggest evidence that would shift p
    - Provide update triggers
    """
    
    def __init__(self, database):
        """Initialize with database connection"""
        self.db = database
    
    def analyze_evidence_targets(self, debate_id: str, 
                                  snapshot_id: Optional[str] = None) -> VerdictSensitivity:
        """
        Analyze what evidence would change the current verdict.
        
        Args:
            debate_id: The debate to analyze
            snapshot_id: Specific snapshot (uses latest if None)
        
        Returns:
            VerdictSensitivity with evidence targets
        """
        # Load snapshot data
        if snapshot_id:
            snapshot = self._load_snapshot(snapshot_id)
        else:
            snapshot = self._load_latest_snapshot(debate_id)
        
        if not snapshot:
            raise ValueError(f"No snapshot found for debate {debate_id}")
        
        # Get current state
        verdict = snapshot.get('verdict', 'NO VERDICT')
        confidence = snapshot.get('confidence', 0.0)
        margin_d = snapshot.get('margin_d', 0.0)
        
        # Get topic scores
        topic_scores = self._load_topic_scores(snapshot.get('snapshot_id', ''))
        
        # Get canonical facts and arguments
        facts = self._load_canonical_facts(debate_id)
        arguments = self._load_canonical_arguments(debate_id)
        
        # Calculate decisiveness for each fact using LSD_FactCheck_v1_5_1 ternary semantics
        # SUPPORTED (p=1.0) and REFUTED (p=0.0) are fully decisive;
        # INSUFFICIENT (p=0.5) is indecisive.
        fact_decisiveness = {}
        for fact in facts:
            status = fact.get('v15_status')
            if not status:
                d = fact.get("fact_check_diagnostics", {})
                status = d.get("v15_status") if isinstance(d, dict) else None
            if status in ("SUPPORTED", "REFUTED"):
                d = 1.0
            else:
                d = 0.0
            fact_decisiveness[fact.get('canon_fact_id', '')] = d
        
        # Calculate argument leverage (MSD §10.3)
        argument_leverage = {}
        for arg in arguments:
            arg_id = arg.get('canon_arg_id', '')
            side = arg.get('side', '')
            
            # Get supporting facts
            supporting = arg.get('supporting_facts', [])
            if isinstance(supporting, str):
                supporting = [supporting]
            
            # Calculate average decisiveness
            if supporting:
                avg_decisiveness = sum(
                    fact_decisiveness.get(fid, 0) for fid in supporting
                ) / len(supporting)
            else:
                avg_decisiveness = 0.25  # Default
            
            argument_leverage[arg_id] = {
                'leverage': avg_decisiveness,
                'side': side,
                'supporting_facts': supporting,
                'inference': arg.get('inference_text', '')
            }
        
        # Find high-leverage targets
        all_targets = []
        
        # 1. Uncertain (INSUFFICIENT) facts with high potential impact
        for fact in facts:
            p = fact.get('p_true', 0.5)
            status = fact.get('v15_status')
            if not status:
                d = fact.get("fact_check_diagnostics", {})
                status = d.get("v15_status") if isinstance(d, dict) else None
            is_insufficient = status == "INSUFFICIENT" or status is None
            
            if is_insufficient:
                # Find arguments that depend on this fact
                dependent_args = [
                    arg for arg in arguments
                    if fact.get('canon_fact_id', '') in arg.get('supporting_facts', [])
                ]
                
                if dependent_args:
                    # Calculate potential impact if this fact were confirmed/refuted
                    potential_impact = len(dependent_args) * 0.1  # Simplified
                    
                    reason = fact.get('v15_insufficiency_reason') or "undetermined"
                    target = EvidenceTarget(
                        target_id=fact.get('canon_fact_id', ''),
                        target_type="fact",
                        title=f"Fact: {fact.get('canon_fact_text', '')[:80]}...",
                        description=fact.get('canon_fact_text', ''),
                        side=fact.get('side', ''),
                        current_state=f"INSUFFICIENT (reason: {reason})",
                        current_p=p,
                        leverage_score=1.0,  # INSUFFICIENT = high potential if resolved
                        impact_on_margin=potential_impact,
                        evidence_needed=self._suggest_evidence_for_fact(fact),
                        evidence_type=self._classify_evidence_type(fact),
                        update_trigger=self._generate_update_trigger(fact, dependent_args),
                        related_arguments=[a.get('canon_arg_id', '') for a in dependent_args]
                    )
                    all_targets.append(target)
        
        # 2. High-leverage arguments
        for arg in arguments:
            arg_id = arg.get('canon_arg_id', '')
            leverage_info = argument_leverage.get(arg_id, {})
            lev_score = leverage_info.get('leverage', 0)
            
            # High leverage arguments are decisive
            if lev_score > 0.3:
                # Find the most decisive supporting fact
                supporting = leverage_info.get('supporting_facts', [])
                decisive_facts = [
                    f for f in facts
                    if f.get('canon_fact_id', '') in supporting
                ]
                
                target = EvidenceTarget(
                    target_id=arg_id,
                    target_type="argument",
                    title=f"Argument: {arg.get('inference_text', '')[:80]}...",
                    description=arg.get('inference_text', ''),
                    side=arg.get('side', ''),
                    current_state=f"Decisive (leverage={lev_score:.2f})",
                    current_p=0.5,
                    leverage_score=lev_score,
                    impact_on_margin=lev_score * 0.15,  # Simplified estimation
                    evidence_needed=self._suggest_evidence_for_argument(arg, decisive_facts),
                    evidence_type="logical" if not decisive_facts else "empirical",
                    update_trigger=f"If key supporting facts of this argument are refuted, "
                                   f"the argument's leverage would decrease significantly.",
                    related_facts=[f.get('canon_fact_id', '') for f in decisive_facts]
                )
                all_targets.append(target)
        
        # 3. Topic-level targets
        for ts in topic_scores:
            topic_id = ts.get('topic_id', '')
            side = ts.get('side', '')
            quality = ts.get('quality', 0)
            
            # Topics with low quality but high potential
            if 0.3 < quality < 0.6:
                target = EvidenceTarget(
                    target_id=topic_id,
                    target_type="topic",
                    title=f"Topic: {topic_id} ({side})",
                    description=f"Topic-side with moderate quality that could swing",
                    side=side,
                    current_state=f"Moderate quality (Q={quality:.2f})",
                    current_p=0.5,
                    leverage_score=0.5,
                    impact_on_margin=quality * 0.1,
                    evidence_needed=f"Stronger factual support or better reasoning in {topic_id}",
                    evidence_type="mixed",
                    update_trigger=f"If evidence quality in this topic improves significantly, "
                                   f"the overall verdict could shift."
                )
                all_targets.append(target)
        
        # Sort by impact
        all_targets.sort(key=lambda t: t.impact_on_margin, reverse=True)
        
        # Split into high/medium impact
        high_impact = [t for t in all_targets if t.impact_on_margin > 0.05]
        medium_impact = [t for t in all_targets if 0.02 <= t.impact_on_margin <= 0.05]
        
        # Limit to top targets
        high_impact = high_impact[:5]
        medium_impact = medium_impact[:5]
        
        # Calculate margin needed for flip
        if verdict == "FOR":
            margin_needed = margin_d  # Need to reduce D to near 0
        elif verdict == "AGAINST":
            margin_needed = -margin_d  # Need to increase D to near 0
        else:
            margin_needed = 0.05  # Need to establish clear separation
        
        # Generate summary
        summary = self._generate_summary(verdict, confidence, high_impact)
        
        return VerdictSensitivity(
            verdict=verdict,
            confidence=confidence,
            margin_d=margin_d,
            margin_needed_for_flip=margin_needed,
            high_impact_targets=high_impact,
            medium_impact_targets=medium_impact,
            summary=summary
        )
    
    def _load_snapshot(self, snapshot_id: str) -> Optional[Dict]:
        """Load snapshot from database"""
        conn = self.db._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM snapshots WHERE snapshot_id = ?", (snapshot_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    
    def _load_latest_snapshot(self, debate_id: str) -> Optional[Dict]:
        """Load latest snapshot for debate"""
        conn = self.db._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM snapshots WHERE debate_id = ? ORDER BY timestamp DESC LIMIT 1",
            (debate_id,)
        )
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    
    def _load_topic_scores(self, snapshot_id: str) -> List[Dict]:
        """Load topic scores from snapshot"""
        snapshot = self._load_snapshot(snapshot_id)
        if not snapshot:
            return []
        
        topic_scores_str = snapshot.get('topic_scores', '{}')
        if isinstance(topic_scores_str, str):
            import json
            try:
                topic_scores = json.loads(topic_scores_str)
            except:
                return []
        else:
            topic_scores = topic_scores_str
        
        # Convert to list
        result = []
        for key, scores in topic_scores.items():
            if isinstance(scores, dict):
                result.append(scores)
        return result
    
    def _load_canonical_facts(self, debate_id: str) -> List[Dict]:
        """Load canonical facts for debate"""
        conn = self.db._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM canonical_facts WHERE debate_id = ?",
            (debate_id,)
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def _load_canonical_arguments(self, debate_id: str) -> List[Dict]:
        """Load canonical arguments for debate"""
        conn = self.db._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM canonical_arguments WHERE debate_id = ?",
            (debate_id,)
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def _suggest_evidence_for_fact(self, fact: Dict) -> str:
        """Suggest what evidence would verify/refute a fact"""
        fact_text = fact.get('canon_fact_text', '').lower()
        
        # Pattern-based suggestions
        if any(word in fact_text for word in ['study', 'research', 'survey', 'percent', '%']):
            return "Peer-reviewed empirical study with robust methodology and sample size"
        
        if any(word in fact_text for word in ['cost', 'price', 'economic', 'gdp', 'revenue']):
            return "Official economic data, financial reports, or government statistics"
        
        if any(word in fact_text for word in ['law', 'legal', 'regulation', 'court', 'jurisdiction']):
            return "Legal documentation, court rulings, or official regulatory texts"
        
        if any(word in fact_text for word in ['history', 'historical', 'in 19', 'in 20']):
            return "Historical records, archival documents, or expert historical analysis"
        
        if any(word in fact_text for word in ['expert', 'scientist', 'researcher']):
            return "Expert testimony from qualified authorities in the relevant field"
        
        return "Empirical evidence from credible sources that directly addresses this claim"
    
    def _classify_evidence_type(self, fact: Dict) -> str:
        """Classify the type of evidence needed"""
        fact_text = fact.get('canon_fact_text', '').lower()
        
        if any(word in fact_text for word in ['study', 'data', 'percent', 'statistics']):
            return "empirical"
        elif any(word in fact_text for word in ['logic', 'therefore', 'implies', 'entails']):
            return "logical"
        elif any(word in fact_text for word in ['expert', 'authority', 'according to']):
            return "expert"
        else:
            return "mixed"
    
    def _suggest_evidence_for_argument(self, argument: Dict, 
                                        decisive_facts: List[Dict]) -> str:
        """Suggest evidence needed to support/refute an argument"""
        inference = argument.get('inference_text', '').lower()
        
        if decisive_facts:
            # Argument depends on facts
            fact_summary = "; ".join([
                f.get('canon_fact_text', '')[:50] + "..."
                for f in decisive_facts[:2]
            ])
            return f"Verification of supporting facts: {fact_summary}"
        else:
            return "Logical analysis of the inference structure and its validity"
    
    def _generate_update_trigger(self, fact: Dict, 
                                  dependent_args: List[Dict]) -> str:
        """Generate the 'If FACT X is confirmed/refuted...' trigger"""
        fact_id = fact.get('canon_fact_id', '')
        status = fact.get('v15_status')
        if not status:
            d = fact.get("fact_check_diagnostics", {})
            status = d.get("v15_status") if isinstance(d, dict) else None
        
        arg_count = len(dependent_args)
        
        if status == "REFUTED":
            return (f"If FACT {fact_id[:20]}... is confirmed (SUPPORTED) with strong evidence, "
                    f"it would strengthen {arg_count} dependent argument(s), "
                    f"potentially shifting the topic quality score.")
        elif status == "SUPPORTED":
            return (f"If FACT {fact_id[:20]}... is refuted (REFUTED) with strong evidence, "
                    f"it would weaken {arg_count} dependent argument(s), "
                    f"potentially shifting the topic quality score.")
        else:
            return (f"If FACT {fact_id[:20]}... is resolved to SUPPORTED or REFUTED with strong evidence, "
                    f"it would affect {arg_count} dependent argument(s), "
                    f"potentially shifting the topic quality score.")
    
    def _generate_summary(self, verdict: str, confidence: float, 
                          targets: List[EvidenceTarget]) -> str:
        """Generate human-readable summary"""
        if not targets:
            return (f"The current verdict ({verdict}) appears stable with {confidence:.0%} confidence. "
                    "No high-impact evidence targets identified.")
        
        top_target = targets[0]
        
        summary = (f"Current verdict: {verdict} with {confidence:.0%} confidence. "
                   f"The outcome is most sensitive to: {top_target.title}. ")
        
        if top_target.target_type == "fact":
            summary += ("If this fact were resolved with decisive evidence, "
                       "the verdict could change.")
        elif top_target.target_type == "argument":
            summary += ("If the key supporting facts of this argument are challenged, "
                       "the balance could shift.")
        
        return summary


def get_evidence_targets(debate_engine, debate_id: str, 
                         snapshot_id: Optional[str] = None) -> Dict:
    """
    Convenience function to get evidence targets for a debate.
    
    Usage:
        targets = get_evidence_targets(debate_engine, "debate_abc123")
    """
    analyzer = EvidenceTargetAnalyzer(debate_engine.db)
    result = analyzer.analyze_evidence_targets(debate_id, snapshot_id)
    return result.to_dict()
