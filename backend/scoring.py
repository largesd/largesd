"""
MSD (Medium Scale Discussion) Scoring Engine
Implements all formulas from the specification
"""
import numpy as np
from typing import List, Dict, Tuple
from dataclasses import dataclass

from backend.models import (
    CanonicalFact, CanonicalArgument, TopicSideScores, Side, Topic
)


@dataclass
class ReplicateResult:
    """Result from a single replicate run"""
    overall_for: float
    overall_against: float
    margin_d: float
    topic_scores: Dict[str, TopicSideScores]


class ScoringEngine:
    """
    Implements the complete MSD scoring pipeline:
    - Factuality (F)
    - Reasoning Strength (Reason)
    - Coverage (Cov)
    - Quality (Q)
    - Overall Score
    - Margin (D)
    - Verdict via Statistical Separability
    """
    
    def __init__(self, num_judges: int = 5, num_replicates: int = 100):
        self.num_judges = num_judges
        self.num_replicates = num_replicates
    
    def compute_factuality(self, facts: List[CanonicalFact]) -> float:
        """
        Compute Factuality F_{t,s}
        
        F_{t,s} = (1 / K_{t,s}) * Σ_k p_{t,s,k}
        
        where K is count of canonical FACT nodes
        and p is P(fact true) for each fact
        """
        if not facts:
            return 0.5  # Neutral if no facts
        
        return sum(f.p_true for f in facts) / len(facts)
    
    def compute_reasoning_strength(self, arguments: List[CanonicalArgument],
                                   side: Side) -> Tuple[float, float]:
        """
        Compute Reasoning Strength Reason_{t,s}
        
        Per argument: Reason_{t,s,a} = median_j(Reason_{t,s,a,j})
        Per topic-side: Reason_{t,s} = median_a(Reason_{t,s,a})
        
        Returns: (median_reasoning, iqr)
        """
        if not arguments:
            return 0.5, 0.0  # Neutral if no arguments
        
        scores = [arg.reasoning_score for arg in arguments]
        median_score = np.median(scores)
        
        # Compute IQR
        q75, q25 = np.percentile(scores, [75, 25])
        iqr = q75 - q25
        
        return float(median_score), float(iqr)
    
    def compute_coverage(self, 
                         own_arguments: List[CanonicalArgument],
                         opposing_arguments: List[CanonicalArgument],
                         all_facts: List[CanonicalFact]) -> Tuple[float, float]:
        """
        Compute Coverage Cov_{t,s}
        
        Coverage measures how well a side addresses opposing arguments.
        
        Steps:
        1. Compute fact decisiveness: d_k = |p_k - 0.5|
        2. Compute argument leverage: Lev_a = (1/|S_a|) * Σ d_k for k in S_a
        3. For each opposing argument: mark as Addressed or Ignored
        4. Cov = Σ(addressed Lev) / Σ(all Lev)
        
        Returns: (coverage, iqr)
        """
        if not opposing_arguments:
            return 1.0, 0.0  # Full coverage if no opposing arguments
        
        # Create fact lookup
        fact_p = {f.canon_fact_id: f.p_true for f in all_facts}
        
        # Compute decisiveness for each fact
        def get_decisiveness(fact_id):
            p = fact_p.get(fact_id, 0.5)
            return abs(p - 0.5)
        
        # Compute leverage for each opposing argument
        arg_leverage = {}
        for arg in opposing_arguments:
            fact_ids = arg.supporting_facts
            if fact_ids:
                avg_decisiveness = sum(get_decisiveness(fid) for fid in fact_ids) / len(fact_ids)
            else:
                avg_decisiveness = 0.25  # Default moderate decisiveness
            arg_leverage[arg.canon_arg_id] = avg_decisiveness
        
        # Simulate judge coverage decisions
        # In real implementation, judges would label each opposing arg
        # For prototype: simulate based on argument structure
        judge_coverages = []
        
        for _ in range(self.num_judges):
            addressed_leverage = 0.0
            total_leverage = 0.0
            
            for arg in opposing_arguments:
                leverage = arg_leverage[arg.canon_arg_id]
                total_leverage += leverage
                
                # Simulate whether this judge thinks it's addressed
                # Higher leverage arguments are more likely to be addressed
                # by well-structured rebuttals
                addressed_prob = min(0.9, 0.3 + leverage * 0.8)
                
                # Add some noise for judge variation
                addressed_prob += np.random.normal(0, 0.1)
                
                if np.random.random() < addressed_prob:
                    addressed_leverage += leverage
            
            if total_leverage > 0:
                judge_coverages.append(addressed_leverage / total_leverage)
            else:
                judge_coverages.append(1.0)
        
        median_coverage = np.median(judge_coverages)
        q75, q25 = np.percentile(judge_coverages, [75, 25])
        iqr = q75 - q25
        
        return float(median_coverage), float(iqr)
    
    def compute_quality(self, factuality: float, reasoning: float, 
                       coverage: float) -> float:
        """
        Compute Quality Q_{t,s}
        
        Q_{t,s} = (F_{t,s} * Reason_{t,s} * Cov_{t,s})^(1/3)
        
        Geometric mean enforces balance - if any component is 0, Q is 0.
        """
        if factuality <= 0 or reasoning <= 0 or coverage <= 0:
            return 0.0
        
        return (factuality * reasoning * coverage) ** (1/3)
    
    def compute_topic_relevance(self, topics: List[Topic],
                                topic_content_mass: Dict[str, int]) -> Dict[str, float]:
        """
        Compute Topic Relevance Rel_t
        
        Rel_t = Mass_t / Σ_t Mass_t
        
        Mass_t = total token count of claim-producing spans in topic t
        """
        total_mass = sum(topic_content_mass.values())
        
        if total_mass == 0:
            # Equal distribution if no content
            n = len(topics)
            return {t.topic_id: 1.0/n for t in topics}
        
        return {
            topic_id: mass / total_mass
            for topic_id, mass in topic_content_mass.items()
        }
    
    def compute_debate_scores(self,
                              topics: List[Topic],
                              topic_facts: Dict[str, List[CanonicalFact]],
                              topic_arguments: Dict[str, List[CanonicalArgument]],
                              topic_content_mass: Dict[str, int]) -> Dict:
        """
        Compute complete debate scores
        
        Returns dictionary with:
        - topic_scores: per-topic scores for each side
        - overall_for: weighted sum of FOR qualities
        - overall_against: weighted sum of AGAINST qualities
        - margin_d: difference (FOR - AGAINST)
        """
        # Compute topic relevance
        relevance = self.compute_topic_relevance(topics, topic_content_mass)
        
        topic_scores = {}
        overall_for = 0.0
        overall_against = 0.0
        
        for topic in topics:
            topic_id = topic.topic_id
            facts = topic_facts.get(topic_id, [])
            args = topic_arguments.get(topic_id, [])
            
            # Split by side
            for_facts = [f for f in facts if f.p_true > 0]  # All facts in this context
            against_facts = facts  # In real impl, would be side-specific
            
            for_args = [a for a in args if a.side == Side.FOR]
            against_args = [a for a in args if a.side == Side.AGAINST]
            
            # Compute FOR scores
            f_for = self.compute_factuality(for_facts[:len(for_facts)//2 + 1] if for_facts else [])
            reason_for, reason_iqr_for = self.compute_reasoning_strength(for_args, Side.FOR)
            cov_for, cov_iqr_for = self.compute_coverage(for_args, against_args, facts)
            q_for = self.compute_quality(f_for, reason_for, cov_for)
            
            # Compute AGAINST scores
            f_against = self.compute_factuality(against_facts[len(against_facts)//2:] if against_facts else [])
            reason_against, reason_iqr_against = self.compute_reasoning_strength(against_args, Side.AGAINST)
            cov_against, cov_iqr_against = self.compute_coverage(against_args, for_args, facts)
            q_against = self.compute_quality(f_against, reason_against, cov_against)
            
            # Store scores
            topic_scores[f"{topic_id}_FOR"] = TopicSideScores(
                topic_id=topic_id,
                side=Side.FOR,
                factuality=round(f_for, 2),
                reasoning=round(reason_for, 2),
                coverage=round(cov_for, 2),
                quality=round(q_for, 2),
                reasoning_iqr=round(reason_iqr_for, 2),
                coverage_iqr=round(cov_iqr_for, 2)
            )
            
            topic_scores[f"{topic_id}_AGAINST"] = TopicSideScores(
                topic_id=topic_id,
                side=Side.AGAINST,
                factuality=round(f_against, 2),
                reasoning=round(reason_against, 2),
                coverage=round(cov_against, 2),
                quality=round(q_against, 2),
                reasoning_iqr=round(reason_iqr_against, 2),
                coverage_iqr=round(cov_iqr_against, 2)
            )
            
            # Weight by relevance
            rel = relevance.get(topic_id, 0.25)
            overall_for += rel * q_for
            overall_against += rel * q_against
        
        margin_d = overall_for - overall_against
        
        return {
            "topic_scores": topic_scores,
            "overall_for": round(overall_for, 2),
            "overall_against": round(overall_against, 2),
            "margin_d": round(margin_d, 4),
            "relevance": relevance
        }
    
    def run_replicates(self, topics, topic_facts, topic_arguments, 
                       topic_content_mass) -> List[ReplicateResult]:
        """
        Run multiple replicates with variation to compute confidence interval
        """
        replicates = []
        
        for _ in range(self.num_replicates):
            # Add noise to simulate judge variation and extraction instability
            noisy_facts = {}
            for tid, facts in topic_facts.items():
                noisy_facts[tid] = []
                for f in facts:
                    # Add small noise to p_true
                    noisy_p = np.clip(f.p_true + np.random.normal(0, 0.05), 0, 1)
                    noisy_f = CanonicalFact(
                        canon_fact_id=f.canon_fact_id,
                        canon_fact_text=f.canon_fact_text,
                        member_fact_ids=f.member_fact_ids,
                        merged_provenance_links=f.merged_provenance_links,
                        referenced_by_au_ids=f.referenced_by_au_ids,
                        p_true=noisy_p
                    )
                    noisy_facts[tid].append(noisy_f)
            
            # Add noise to argument reasoning scores
            noisy_args = {}
            for tid, args in topic_arguments.items():
                noisy_args[tid] = []
                for a in args:
                    noisy_reasoning = np.clip(
                        a.reasoning_score + np.random.normal(0, 0.08), 0, 1
                    )
                    noisy_a = CanonicalArgument(
                        canon_arg_id=a.canon_arg_id,
                        topic_id=a.topic_id,
                        side=a.side,
                        supporting_facts=a.supporting_facts,
                        inference_text=a.inference_text,
                        member_au_ids=a.member_au_ids,
                        merged_provenance=a.merged_provenance,
                        reasoning_score=noisy_reasoning,
                        reasoning_iqr=a.reasoning_iqr
                    )
                    noisy_args[tid].append(noisy_a)
            
            scores = self.compute_debate_scores(topics, noisy_facts, noisy_args, topic_content_mass)
            
            replicates.append(ReplicateResult(
                overall_for=scores["overall_for"],
                overall_against=scores["overall_against"],
                margin_d=scores["margin_d"],
                topic_scores=scores["topic_scores"]
            ))
        
        return replicates
    
    def compute_verdict(self, replicates: List[ReplicateResult]) -> Dict:
        """
        Compute verdict based on replicate distribution
        
        D_r = Overall_FOR^(r) - Overall_AGAINST^(r)
        
        If CI(D) entirely > 0: FOR wins
        If CI(D) entirely < 0: AGAINST wins
        Else: NO VERDICT
        
        Confidence = max(#{D_r>0}/R, #{D_r<0}/R)
        """
        d_values = [r.margin_d for r in replicates]
        
        # Compute 95% confidence interval
        ci_lower = np.percentile(d_values, 2.5)
        ci_upper = np.percentile(d_values, 97.5)
        median_d = np.median(d_values)
        
        # Determine verdict
        if ci_lower > 0:
            verdict = "FOR"
        elif ci_upper < 0:
            verdict = "AGAINST"
        else:
            verdict = "NO VERDICT"
        
        # Compute confidence
        positive_count = sum(1 for d in d_values if d > 0)
        negative_count = sum(1 for d in d_values if d < 0)
        total = len(d_values)
        
        confidence = max(positive_count / total, negative_count / total)
        
        return {
            "verdict": verdict,
            "confidence": round(confidence, 2),
            "ci_lower": round(ci_lower, 4),
            "ci_upper": round(ci_upper, 4),
            "median_d": round(median_d, 4),
            "d_distribution": d_values
        }
    
    def compute_counterfactuals(self, topics, topic_facts, topic_arguments,
                                topic_content_mass) -> Dict[str, float]:
        """
        Compute what D would be if each topic were removed
        """
        base_scores = self.compute_debate_scores(
            topics, topic_facts, topic_arguments, topic_content_mass
        )
        base_d = base_scores["margin_d"]
        
        counterfactuals = {}
        
        for topic in topics:
            # Create version without this topic
            reduced_topics = [t for t in topics if t.topic_id != topic.topic_id]
            reduced_facts = {k: v for k, v in topic_facts.items() if k != topic.topic_id}
            reduced_args = {k: v for k, v in topic_arguments.items() if k != topic.topic_id}
            reduced_mass = {k: v for k, v in topic_content_mass.items() if k != topic.topic_id}
            
            if reduced_topics:
                scores = self.compute_debate_scores(
                    reduced_topics, reduced_facts, reduced_args, reduced_mass
                )
                new_d = scores["margin_d"]
            else:
                new_d = 0.0
            
            counterfactuals[topic.topic_id] = round(new_d, 4)
        
        return counterfactuals
