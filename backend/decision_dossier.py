"""
LSD §17 Decision Dossier - Decision Provenance and Counterfactuals
Implements transparency into how a debate conclusion was reached.
"""

import json
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from collections import defaultdict
import math


@dataclass
class CounterfactualAnalysis:
    """Result of a counterfactual analysis."""
    topic_id: str
    original_score: float
    counterfactual_score: float
    delta: float
    flip_risk: str  # 'none', 'low', 'medium', 'high'
    reasoning: str


class DecisionDossierAnalyzer:
    """
    Analyzes and documents decision provenance.
    """
    
    def __init__(self, db):
        self.db = db
        self._init_tables()
    
    def _init_tables(self):
        """Initialize decision dossier tables."""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS topic_counterfactuals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                debate_id TEXT NOT NULL,
                topic_id TEXT NOT NULL,
                original_score REAL,
                counterfactual_score REAL,
                delta REAL,
                flip_risk TEXT,
                reasoning TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(debate_id, topic_id)
            )
        """)
        self.db.commit()
    
    def compute_topic_counterfactuals(
        self,
        debate_id: str,
        topics: List[Dict[str, Any]],
        aggregated_score: float
    ) -> List[CounterfactualAnalysis]:
        """
        LSD §17.1: "What if this topic were removed?"
        
        Analyzes the impact of removing each topic from the debate.
        """
        results = []
        
        for topic in topics:
            topic_id = topic.get('id', str(topic.get('topic', 'unknown')))
            topic_weight = topic.get('weight', 1.0)
            topic_reliability = topic.get('reliability', 0.5)
            
            # Calculate original contribution
            original_contribution = topic_weight * (topic_reliability - 0.5)
            
            # Counterfactual: redistribute weight to remaining topics
            remaining_topics = [t for t in topics if t.get('id') != topic_id]
            remaining_weight = sum(t.get('weight', 1.0) for t in remaining_topics)
            
            if remaining_weight > 0:
                # Proportional redistribution
                redistributed = 0
                for rt in remaining_topics:
                    rt_weight = rt.get('weight', 1.0)
                    rt_reliability = rt.get('reliability', 0.5)
                    proportion = rt_weight / remaining_weight
                    redistributed += proportion * rt_reliability * topic_weight
                
                counterfactual_score = aggregated_score - original_contribution + redistributed
            else:
                counterfactual_score = 0.5  # Neutral if no topics remain
            
            delta = aggregated_score - counterfactual_score
            
            # Assess flip risk
            if abs(aggregated_score - 0.5) < 0.1:
                flip_risk = 'high' if abs(delta) > 0.05 else 'medium' if abs(delta) > 0.02 else 'low'
            else:
                same_direction = (aggregated_score - 0.5) * (counterfactual_score - 0.5) > 0
                flip_risk = 'none' if same_direction else 'high' if abs(delta) > 0.1 else 'medium'
            
            reasoning = (
                f"Topic contributes {original_contribution:.3f} to aggregated score. "
                f"Without it, score shifts by {delta:.3f} to {counterfactual_score:.3f}."
            )
            
            analysis = CounterfactualAnalysis(
                topic_id=topic_id,
                original_score=aggregated_score,
                counterfactual_score=counterfactual_score,
                delta=delta,
                flip_risk=flip_risk,
                reasoning=reasoning
            )
            results.append(analysis)
            
            # Store in DB
            self.db.execute(
                """INSERT OR REPLACE INTO topic_counterfactuals
                   (debate_id, topic_id, original_score, counterfactual_score, delta, flip_risk, reasoning)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (debate_id, topic_id, aggregated_score, counterfactual_score, delta, flip_risk, reasoning)
            )
        
        self.db.commit()
        return results
    
    def compute_decisive_facts(
        self,
        facts: List[Dict[str, Any]],
        top_n: int = 10
    ) -> List[Dict[str, Any]]:
        """
        LSD §17.2: Identify decisive facts—those with high potential to change the conclusion.
        
        A fact is decisive if:
        1. It has high leverage (would significantly shift conclusion if changed)
        2. It has uncertainty (could plausibly be different)
        """
        scored_facts = []
        
        for fact in facts:
            p_true = fact.get('p_true', 0.5)
            weight = fact.get('weight', 1.0)
            
            # Leverage: how much would conclusion change if this fact flipped?
            # Facts near 0.5 have low leverage; facts near 0 or 1 have high leverage
            leverage = abs(p_true - 0.5) * 2  # 0-1 scale
            
            # Uncertainty: how uncertain is this fact?
            # Using distance from certainty (0 or 1)
            uncertainty = 1.0 - abs(p_true - 0.5) * 2  # 0-1 scale
            
            # Decisiveness = leverage × uncertainty
            # High when: (a) fact matters, AND (b) we're not sure about it
            decisiveness = leverage * uncertainty * weight
            
            scored_facts.append({
                'fact_id': fact.get('id', 'unknown'),
                'statement': fact.get('statement', ''),
                'p_true': p_true,
                'weight': weight,
                'leverage': round(leverage, 3),
                'uncertainty': round(uncertainty, 3),
                'decisiveness': round(decisiveness, 3)
            })
        
        # Sort by decisiveness, highest first
        scored_facts.sort(key=lambda x: x['decisiveness'], reverse=True)
        
        return scored_facts[:top_n]
    
    def generate_evidence_gap_summary(
        self,
        debate_id: str,
        topics: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        LSD §17.3: Evidence gap summary—what information would change the conclusion?
        """
        tier_distribution = defaultdict(int)
        insufficient_topics = []
        
        for topic in topics:
            tier = topic.get('tier', 'D')
            tier_distribution[tier] += 1
            
            reliability = topic.get('reliability', 0.5)
            evidence_count = topic.get('evidence_count', 0)
            
            # Identify under-supported topics
            if reliability < 0.6 and evidence_count < 3:
                insufficient_topics.append({
                    'topic_id': topic.get('id', 'unknown'),
                    'reliability': reliability,
                    'evidence_count': evidence_count,
                    'gap': 'low_reliability_low_evidence'
                })
            elif reliability < 0.6:
                insufficient_topics.append({
                    'topic_id': topic.get('id', 'unknown'),
                    'reliability': reliability,
                    'evidence_count': evidence_count,
                    'gap': 'low_reliability'
                })
            elif evidence_count < 2:
                insufficient_topics.append({
                    'topic_id': topic.get('id', 'unknown'),
                    'reliability': reliability,
                    'evidence_count': evidence_count,
                    'gap': 'low_evidence'
                })
        
        total_topics = len(topics)
        insufficient_count = len(insufficient_topics)
        
        return {
            'debate_id': debate_id,
            'total_topics': total_topics,
            'insufficient_topics': insufficient_count,
            'insufficiency_rate': round(insufficient_count / total_topics, 3) if total_topics > 0 else 0,
            'tier_distribution': dict(tier_distribution),
            'high_priority_gaps': insufficient_topics[:5],
            'recommendation': (
                f"{insufficient_count} of {total_topics} topics need additional evidence. "
                f"Focus on topics with reliability < 0.6 or fewer than 2 supporting claims."
            )
        }
    
    def get_decision_dossier(
        self,
        debate_id: str,
        conclusion: Dict[str, Any],
        topics: List[Dict[str, Any]],
        facts: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Generate complete decision dossier for a debate.
        """
        aggregated_score = conclusion.get('p_true', 0.5)
        
        # Compute counterfactuals
        counterfactuals = self.compute_topic_counterfactuals(debate_id, topics, aggregated_score)
        
        # Compute decisive facts
        decisive_facts = self.compute_decisive_facts(facts)
        
        # Generate evidence gap summary
        gap_summary = self.generate_evidence_gap_summary(debate_id, topics)
        
        # Identify top contributors
        topic_contributions = []
        for topic in topics:
            weight = topic.get('weight', 1.0)
            reliability = topic.get('reliability', 0.5)
            contribution = weight * abs(reliability - 0.5)
            topic_contributions.append({
                'topic_id': topic.get('id', 'unknown'),
                'contribution': round(contribution, 3)
            })
        topic_contributions.sort(key=lambda x: x['contribution'], reverse=True)
        
        return {
            'debate_id': debate_id,
            'conclusion': conclusion,
            'decision_logic': {
                'aggregated_score': aggregated_score,
                'aggregation_method': 'weighted_reliability_pooling',
                'confidence': conclusion.get('confidence', 0.5)
            },
            'top_contributors': topic_contributions[:5],
            'counterfactuals': [
                {
                    'topic_id': c.topic_id,
                    'delta': round(c.delta, 4),
                    'flip_risk': c.flip_risk,
                    'reasoning': c.reasoning
                }
                for c in counterfactuals
            ],
            'decisive_facts': decisive_facts,
            'evidence_gaps': gap_summary,
            'appeal_guidance': {
                'grounds_for_appeal': [
                    'New evidence on decisive facts',
                    'Demonstrated bias in top-contributing sources',
                    'Procedural irregularity in topic aggregation',
                    'Counterfactual analysis shows conclusion instability'
                ],
                'submission_deadline': '30 days from snapshot',
                'required_format': 'Structured claim with evidence tier and source transparency'
            }
        }
