"""
Enhanced MSD Scoring Engine
Implements all formulas with real multi-judge evaluation and audits
"""
import numpy as np
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime

from llm_client import LLMClient


@dataclass
class TopicSideScores:
    """Scores for a topic-side"""
    topic_id: str
    side: str
    factuality: float = 0.0
    reasoning: float = 0.0
    coverage: float = 0.0
    quality: float = 0.0
    reasoning_iqr: float = 0.0
    coverage_iqr: float = 0.0


@dataclass
class ReplicateResult:
    """Result from a single replicate run"""
    overall_for: float
    overall_against: float
    margin_d: float
    topic_scores: Dict[str, TopicSideScores]


class ScoringEngine:
    """
    Implements the complete MSD scoring pipeline with real multi-judge evaluation
    """
    
    def __init__(self, llm_client: Optional[LLMClient] = None,
                 num_judges: int = 5, num_replicates: int = 100):
        self.llm_client = llm_client or LLMClient(num_judges=num_judges)
        self.num_judges = num_judges
        self.num_replicates = num_replicates
    
    def compute_factuality(self, facts: List[Dict]) -> float:
        """
        Compute Factuality F_{t,s}
        F_{t,s} = (1 / K_{t,s}) * Σ_k p_{t,s,k}
        """
        if not facts:
            return 0.5
        
        return sum(f.get('p_true', 0.5) for f in facts) / len(facts)
    
    def compute_reasoning_strength(self, arguments: List[Dict],
                                   side: str) -> Tuple[float, float, List[Dict]]:
        """
        Compute Reasoning Strength Reason_{t,s} (MSD §10.2)
        Uses LLM-based multi-judge evaluation with robust aggregation
        
        Per argument: Reason_{t,s,a} = median_j(Reason_{t,s,a,j})
        Per topic-side: Reason_{t,s} = median_a(Reason_{t,s,a})
        
        Returns: (median_reasoning, iqr, judge_details)
        """
        if not arguments:
            return 0.5, 0.0, []
        
        argument_scores = []
        judge_details = []  # For audit trail (MSD §14.B)
        
        for arg in arguments:
            # Get multi-judge evaluation
            supporting_facts = arg.get('supporting_facts', [])
            inference_text = arg.get('inference_text', '')
            
            evaluations = self.llm_client.judge_reasoning(
                inference_text,
                supporting_facts if isinstance(supporting_facts, list) else list(supporting_facts)
            )
            
            # Aggregate with robust statistics
            agg = self.llm_client.aggregate_judge_scores(evaluations)
            
            judge_details.append({
                'arg_id': arg.get('canon_arg_id', 'unknown'),
                'all_scores': agg['all_scores'],
                'median': agg['median'],
                'iqr': agg['iqr'],
                'disagreement_level': agg['disagreement_level']
            })
            
            argument_scores.append(agg['median'])
        
        # Aggregate across arguments (MSD §10.2)
        median_reasoning = np.median(argument_scores)
        q75, q25 = np.percentile(argument_scores, [75, 25])
        iqr = q75 - q25
        
        return float(median_reasoning), float(iqr), judge_details
    
    def compute_coverage(self, own_arguments: List[Dict],
                        opposing_arguments: List[Dict],
                        all_facts: List[Dict]) -> Tuple[float, float]:
        """
        Compute Coverage Cov_{t,s}
        Multi-judge evaluation of whether opposing arguments are addressed
        """
        if not opposing_arguments:
            return 1.0, 0.0
        
        # Create fact lookup for decisiveness
        fact_p = {f.get('canon_fact_id', f.get('fact_id', '')): f.get('p_true', 0.5) 
                  for f in all_facts}
        
        # Compute decisiveness for each fact
        def get_decisiveness(fact_id):
            p = fact_p.get(fact_id, 0.5)
            return abs(p - 0.5)
        
        # Compute leverage for each opposing argument
        arg_leverage = {}
        for arg in opposing_arguments:
            fact_ids = arg.get('supporting_facts', [])
            if fact_ids:
                if isinstance(fact_ids, set):
                    fact_ids = list(fact_ids)
                avg_decisiveness = sum(get_decisiveness(fid) for fid in fact_ids) / len(fact_ids)
            else:
                avg_decisiveness = 0.25
            arg_leverage[arg.get('canon_arg_id', arg.get('au_id', ''))] = avg_decisiveness
        
        # Multi-judge coverage evaluation
        judge_coverages = []
        
        for judge_idx in range(self.num_judges):
            addressed_leverage = 0.0
            total_leverage = 0.0
            
            for opp_arg in opposing_arguments:
                arg_id = opp_arg.get('canon_arg_id', opp_arg.get('au_id', ''))
                leverage = arg_leverage.get(arg_id, 0.25)
                total_leverage += leverage
                
                # Build rebuttal text from own arguments
                rebuttal_text = " ".join([
                    a.get('inference_text', '') for a in own_arguments
                ])
                
                # Judge whether this opposing argument is addressed
                determinations = self.llm_client.judge_coverage(opp_arg, rebuttal_text)
                
                if judge_idx < len(determinations):
                    determination = determinations[judge_idx]
                    if determination.get('addressed', False):
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
        """
        if factuality <= 0 or reasoning <= 0 or coverage <= 0:
            return 0.0
        
        return (factuality * reasoning * coverage) ** (1/3)
    
    def compute_topic_relevance(self, topics: List[Dict],
                                topic_content_mass: Dict[str, int]) -> Dict[str, float]:
        """
        Compute Topic Relevance Rel_t
        Rel_t = Mass_t / Σ_t Mass_t
        """
        total_mass = sum(topic_content_mass.values())
        
        if total_mass == 0:
            n = len(topics)
            return {t.get('topic_id', ''): 1.0/n for t in topics}
        
        return {
            topic_id: mass / total_mass
            for topic_id, mass in topic_content_mass.items()
        }
    
    def compute_debate_scores(self, topics: List[Dict],
                              topic_facts: Dict[str, List[Dict]],
                              topic_arguments: Dict[str, List[Dict]],
                              topic_content_mass: Dict[str, int]) -> Dict:
        """
        Compute complete debate scores
        """
        # Compute topic relevance
        relevance = self.compute_topic_relevance(topics, topic_content_mass)
        
        topic_scores = {}
        overall_for = 0.0
        overall_against = 0.0
        
        for topic in topics:
            topic_id = topic.get('topic_id', '')
            facts = topic_facts.get(topic_id, [])
            args = topic_arguments.get(topic_id, [])
            
            # Split by side
            for_facts = [f for f in facts if f.get('side') == 'FOR']
            against_facts = [f for f in facts if f.get('side') == 'AGAINST']
            
            for_args = [a for a in args if a.get('side') == 'FOR']
            against_args = [a for a in args if a.get('side') == 'AGAINST']
            
            # Compute FOR scores
            f_for = self.compute_factuality(for_facts)
            reason_for, reason_iqr_for, judge_details_for = self.compute_reasoning_strength(for_args, 'FOR')
            cov_for, cov_iqr_for = self.compute_coverage(for_args, against_args, facts)
            q_for = self.compute_quality(f_for, reason_for, cov_for)
            
            # Compute AGAINST scores
            f_against = self.compute_factuality(against_facts)
            reason_against, reason_iqr_against, judge_details_against = self.compute_reasoning_strength(against_args, 'AGAINST')
            cov_against, cov_iqr_against = self.compute_coverage(against_args, for_args, facts)
            q_against = self.compute_quality(f_against, reason_against, cov_against)
            
            # Store scores with judge disagreement details (MSD §14.B)
            topic_scores[f"{topic_id}_FOR"] = {
                'topic_id': topic_id,
                'side': 'FOR',
                'factuality': round(f_for, 2),
                'reasoning': round(reason_for, 2),
                'coverage': round(cov_for, 2),
                'quality': round(q_for, 2),
                'reasoning_iqr': round(reason_iqr_for, 2),
                'coverage_iqr': round(cov_iqr_for, 2),
                'judge_disagreement': {
                    'reasoning': judge_details_for,
                    'disagreement_level': 'high' if reason_iqr_for > 0.2 else 'moderate' if reason_iqr_for > 0.1 else 'low'
                }
            }
            
            topic_scores[f"{topic_id}_AGAINST"] = {
                'topic_id': topic_id,
                'side': 'AGAINST',
                'factuality': round(f_against, 2),
                'reasoning': round(reason_against, 2),
                'coverage': round(cov_against, 2),
                'quality': round(q_against, 2),
                'reasoning_iqr': round(reason_iqr_against, 2),
                'coverage_iqr': round(cov_iqr_against, 2),
                'judge_disagreement': {
                    'reasoning': judge_details_against,
                    'disagreement_level': 'high' if reason_iqr_against > 0.2 else 'moderate' if reason_iqr_against > 0.1 else 'low'
                }
            }
            
            # Weight by relevance
            rel = relevance.get(topic_id, 0.25)
            overall_for += rel * q_for
            overall_against += rel * q_against
        
        margin_d = overall_for - overall_against
        
        return {
            'topic_scores': topic_scores,
            'overall_for': round(overall_for, 2),
            'overall_against': round(overall_against, 2),
            'margin_d': round(margin_d, 4),
            'relevance': relevance
        }
    
    def run_replicates(self, topics, topic_facts, topic_arguments,
                       topic_content_mass) -> List[ReplicateResult]:
        """Run multiple replicates with variation"""
        replicates = []
        
        for _ in range(self.num_replicates):
            # Add noise to simulate instability
            noisy_facts = {}
            for tid, facts in topic_facts.items():
                noisy_facts[tid] = []
                for f in facts:
                    noisy_p = np.clip(f.get('p_true', 0.5) + np.random.normal(0, 0.05), 0, 1)
                    noisy_f = dict(f)
                    noisy_f['p_true'] = noisy_p
                    noisy_facts[tid].append(noisy_f)
            
            # Add noise to argument reasoning
            noisy_args = {}
            for tid, args in topic_arguments.items():
                noisy_args[tid] = []
                for a in args:
                    noisy_reasoning = np.clip(
                        a.get('reasoning_score', 0.5) + np.random.normal(0, 0.08), 0, 1
                    )
                    noisy_a = dict(a)
                    noisy_a['reasoning_score'] = noisy_reasoning
                    noisy_args[tid].append(noisy_a)
            
            scores = self.compute_debate_scores(topics, noisy_facts, noisy_args, topic_content_mass)
            
            replicates.append(ReplicateResult(
                overall_for=scores['overall_for'],
                overall_against=scores['overall_against'],
                margin_d=scores['margin_d'],
                topic_scores=scores['topic_scores']
            ))
        
        return replicates
    
    def compute_verdict(self, replicates: List[ReplicateResult]) -> Dict:
        """
        Compute verdict based on replicate distribution
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
            'verdict': verdict,
            'confidence': round(confidence, 2),
            'ci_lower': round(ci_lower, 4),
            'ci_upper': round(ci_upper, 4),
            'median_d': round(median_d, 4),
            'd_distribution': d_values
        }
    
    def compute_counterfactuals(self, topics, topic_facts, topic_arguments,
                                topic_content_mass) -> Dict[str, float]:
        """Compute what D would be if each topic were removed"""
        base_scores = self.compute_debate_scores(
            topics, topic_facts, topic_arguments, topic_content_mass
        )
        base_d = base_scores['margin_d']
        
        counterfactuals = {}
        
        for topic in topics:
            topic_id = topic.get('topic_id', '')
            
            # Create version without this topic
            reduced_topics = [t for t in topics if t.get('topic_id') != topic_id]
            reduced_facts = {k: v for k, v in topic_facts.items() if k != topic_id}
            reduced_args = {k: v for k, v in topic_arguments.items() if k != topic_id}
            reduced_mass = {k: v for k, v in topic_content_mass.items() if k != topic_id}
            
            if reduced_topics:
                scores = self.compute_debate_scores(
                    reduced_topics, reduced_facts, reduced_args, reduced_mass
                )
                new_d = scores['margin_d']
            else:
                new_d = 0.0
            
            counterfactuals[topic_id] = {
                'd_without_topic': round(new_d, 4),
                'change_in_d': round(new_d - base_d, 4),
                'would_flip_verdict': (base_d > 0 and new_d < 0) or (base_d < 0 and new_d > 0)
            }
        
        return counterfactuals
    
    def run_side_label_symmetry_audit(self, topics, topic_facts,
                                      topic_arguments, topic_content_mass) -> Dict:
        """
        Run pipeline with FOR/AGAINST labels swapped
        Returns distribution change in D and per-topic Q
        """
        # Swap sides
        swapped_facts = {}
        for tid, facts in topic_facts.items():
            swapped_facts[tid] = []
            for f in facts:
                swapped_f = dict(f)
                swapped_f['side'] = 'AGAINST' if f.get('side') == 'FOR' else 'FOR'
                swapped_facts[tid].append(swapped_f)
        
        swapped_args = {}
        for tid, args in topic_arguments.items():
            swapped_args[tid] = []
            for a in args:
                swapped_a = dict(a)
                swapped_a['side'] = 'AGAINST' if a.get('side') == 'FOR' else 'FOR'
                swapped_args[tid].append(swapped_a)
        
        # Run scoring with swapped labels
        swapped_scores = self.compute_debate_scores(
            topics, swapped_facts, swapped_args, topic_content_mass
        )
        
        # Normal scoring
        normal_scores = self.compute_debate_scores(
            topics, topic_facts, topic_arguments, topic_content_mass
        )
        
        # Compute delta D
        delta_d = swapped_scores['margin_d'] - (-normal_scores['margin_d'])
        
        # Compute per-topic Q changes
        topic_deltas = {}
        for tid in topic_facts.keys():
            for_key = f"{tid}_FOR"
            against_key = f"{tid}_AGAINST"
            
            # Original Q values
            orig_for_q = normal_scores['topic_scores'].get(for_key, {}).get('quality', 0)
            orig_against_q = normal_scores['topic_scores'].get(against_key, {}).get('quality', 0)
            
            # Swapped Q values (now FOR was AGAINST and vice versa)
            swapped_for_q = swapped_scores['topic_scores'].get(for_key, {}).get('quality', 0)
            swapped_against_q = swapped_scores['topic_scores'].get(against_key, {}).get('quality', 0)
            
            # After swap, what was FOR should score like original AGAINST
            topic_deltas[tid] = {
                'q_for_delta': round(swapped_for_q - orig_against_q, 3),
                'q_against_delta': round(swapped_against_q - orig_for_q, 3),
                'asymmetry_score': round(abs(swapped_for_q - orig_against_q) + 
                                        abs(swapped_against_q - orig_for_q), 3)
            }
        
        return {
            'median_delta_d': round(delta_d, 4),
            'abs_delta_d': round(abs(delta_d), 4),
            'original_d': round(normal_scores['margin_d'], 4),
            'swapped_d': round(-swapped_scores['margin_d'], 4),
            'topic_deltas': topic_deltas,
            'interpretation': self._interpret_symmetry_result(abs(delta_d))
        }
    
    def _interpret_symmetry_result(self, abs_delta_d: float) -> str:
        """Interpret symmetry audit result"""
        if abs_delta_d < 0.02:
            return "Excellent symmetry: label swap has minimal effect"
        elif abs_delta_d < 0.05:
            return "Good symmetry: small asymmetry within acceptable range"
        elif abs_delta_d < 0.10:
            return "Moderate asymmetry: may indicate some bias"
        else:
            return "Significant asymmetry: strong bias detected, confidence reduced"
    
    def compute_relevance_sensitivity(self, topics, topic_facts,
                                      topic_arguments, topic_content_mass,
                                      num_perturbations: int = 50) -> Dict:
        """
        Perturb topic relevance weights via resampling
        Returns D distribution under perturbations
        """
        d_values = []
        
        for _ in range(num_perturbations):
            # Perturb content mass
            perturbed_mass = {}
            for tid, mass in topic_content_mass.items():
                # Add noise to mass
                noise = np.random.normal(0, mass * 0.2)  # 20% std dev
                perturbed_mass[tid] = max(0, mass + noise)
            
            # Recompute scores
            scores = self.compute_debate_scores(
                topics, topic_facts, topic_arguments, perturbed_mass
            )
            d_values.append(scores['margin_d'])
        
        # Compute stability metrics
        verdicts = {'FOR': 0, 'AGAINST': 0, 'NO VERDICT': 0}
        for d in d_values:
            if d > 0.05:
                verdicts['FOR'] += 1
            elif d < -0.05:
                verdicts['AGAINST'] += 1
            else:
                verdicts['NO VERDICT'] += 1
        
        return {
            'd_mean': round(np.mean(d_values), 4),
            'd_std': round(np.std(d_values), 4),
            'd_min': round(min(d_values), 4),
            'd_max': round(max(d_values), 4),
            'verdict_distribution': verdicts,
            'stability_ratio': round(max(verdicts.values()) / len(d_values), 2),
            'interpretation': 'Stable' if max(verdicts.values()) / len(d_values) > 0.8 else 'Unstable'
        }
