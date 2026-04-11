"""
LSD §8.1, §10, §11 - Selection Transparency
Implements AU completeness proxy, centrality capping, rarity slice, and integrity signals.
"""

import json
import math
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from collections import defaultdict
from datetime import datetime


@dataclass
class AUCompletenessResult:
    """Assessment of Argument Unit completeness."""
    au_id: str
    conclusion_present: bool
    premises_present: bool
    provenance_present: bool
    inference_present: bool
    completeness_score: float  # 0-1
    gaps: List[str]


@dataclass
class IntegritySignal:
    """Detected integrity signal."""
    signal_type: str  # 'burst', 'template_similarity', 'participation_entropy'
    severity: str     # 'low', 'medium', 'high'
    description: str
    affected_items: List[str]
    metrics: Dict[str, float]


class SelectionTransparencyAnalyzer:
    """
    Analyzes selection process for transparency and manipulation detection.
    """
    
    def __init__(self, db):
        self.db = db
        self._init_tables()
    
    def _init_tables(self):
        """Initialize selection transparency tables."""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS selection_diagnostics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                debate_id TEXT NOT NULL,
                diagnostic_type TEXT NOT NULL,
                diagnostic_data TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.db.commit()
    
    def au_completeness_score(
        self,
        argument_units: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        LSD §8.1 AU Completeness Proxy
        
        Evaluates whether argument units are complete and usable:
        1. Conclusion: clear claim
        2. Premises: supporting reasons
        3. Provenance: source attribution
        4. Inference: reasoning chain
        """
        results = []
        total_score = 0
        
        for au in argument_units:
            au_id = au.get('id', 'unknown')
            gaps = []
            
            # Check conclusion (LSD §8.1.1)
            conclusion = au.get('conclusion', '')
            conclusion_present = bool(conclusion and len(conclusion) > 10)
            if not conclusion_present:
                gaps.append('missing_conclusion')
            
            # Check premises (LSD §8.1.2)
            premises = au.get('premises', [])
            premises_present = bool(premises and len(premises) > 0)
            if not premises_present:
                gaps.append('missing_premises')
            
            # Check provenance (LSD §8.1.3)
            source_id = au.get('source_id', '')
            source_type = au.get('source_type', '')
            provenance_present = bool(source_id and source_type)
            if not provenance_present:
                gaps.append('missing_provenance')
            
            # Check inference (LSD §8.1.4)
            inference_chain = au.get('inference_chain', '')
            inference_present = bool(inference_chain and len(inference_chain) > 5)
            if not inference_present:
                gaps.append('missing_inference')
            
            # Calculate completeness score
            criteria_met = sum([
                conclusion_present,
                premises_present,
                provenance_present,
                inference_present
            ])
            completeness = criteria_met / 4.0
            total_score += completeness
            
            result = AUCompletenessResult(
                au_id=au_id,
                conclusion_present=conclusion_present,
                premises_present=premises_present,
                provenance_present=provenance_present,
                inference_present=inference_present,
                completeness_score=round(completeness, 3),
                gaps=gaps
            )
            results.append(result)
        
        avg_completeness = total_score / len(argument_units) if argument_units else 0
        
        # Categorize by completeness tier
        tier_a = sum(1 for r in results if r.completeness_score == 1.0)
        tier_b = sum(1 for r in results if 0.75 <= r.completeness_score < 1.0)
        tier_c = sum(1 for r in results if 0.5 <= r.completeness_score < 0.75)
        tier_d = sum(1 for r in results if r.completeness_score < 0.5)
        
        return {
            'average_completeness': round(avg_completeness, 3),
            'total_argument_units': len(argument_units),
            'tier_distribution': {
                'A_complete': tier_a,
                'B_minor_gaps': tier_b,
                'C_partial': tier_c,
                'D_incomplete': tier_d
            },
            'unit_scores': [
                {
                    'au_id': r.au_id,
                    'completeness': r.completeness_score,
                    'gaps': r.gaps
                }
                for r in results
            ]
        }
    
    def compute_centrality_with_capping(
        self,
        item_refs: Dict[str, List[str]],
        cap_percentile: float = 95.0
    ) -> Dict[str, Any]:
        """
        LSD §10 Centrality with Capping
        
        Measures how central each item is in the reference network.
        Uses log-transform to reduce dominance, with P95 capping
        to prevent amplification attacks.
        """
        if not item_refs:
            return {'centrality_scores': {}, 'capping_applied': False}
        
        # Raw centrality = number of distinct references
        raw_scores = {
            item: len(refs) for item, refs in item_refs.items()
        }
        
        # Log-transform to reduce dominant-item skew (LSD §10.2)
        log_scores = {
            item: math.log1p(score) for item, score in raw_scores.items()
        }
        
        # Calculate P95 cap (LSD §10.3)
        sorted_scores = sorted(log_scores.values())
        n = len(sorted_scores)
        cap_index = int(n * cap_percentile / 100)
        cap_value = sorted_scores[min(cap_index, n - 1)] if n > 0 else 1.0
        
        # Apply capping
        capped_scores = {}
        capping_applied = False
        for item, score in log_scores.items():
            if score > cap_value:
                capped_scores[item] = round(cap_value, 3)
                capping_applied = True
            else:
                capped_scores[item] = round(score, 3)
        
        # Identify anti-amplification candidates
        high_raw_low_capped = [
            item for item, raw in raw_scores.items()
            if raw > cap_value * 2 and log_scores[item] > cap_value * 0.8
        ]
        
        return {
            'centrality_scores': capped_scores,
            'capping_applied': capping_applied,
            'cap_value': round(cap_value, 3),
            'cap_percentile': cap_percentile,
            'anti_amplification_candidates': high_raw_low_capped[:5],
            'methodology': {
                'raw_measure': 'distinct_references',
                'transform': 'log1p',
                'capping': f'P{int(cap_percentile)}'
            }
        }
    
    def rarity_slice_diagnostics(
        self,
        items: List[Dict[str, Any]],
        rarity_threshold: float = 0.20
    ) -> Dict[str, Any]:
        """
        LSD §11 Rarity Slice
        
        Tracks utilization of rare items (ρ=0.20 threshold).
        High utilization of rare items indicates diverse sourcing.
        """
        if not items:
            return {'utilization_rate': 0, 'rare_items_used': 0}
        
        # Identify rare items (bottom 20% by reference count)
        ref_counts = [
            (item.get('id', str(i)), len(item.get('refs', [])))
            for i, item in enumerate(items)
        ]
        ref_counts.sort(key=lambda x: x[1])
        
        n = len(ref_counts)
        rarity_cutoff = int(n * rarity_threshold)
        rare_items = set(item_id for item_id, _ in ref_counts[:rarity_cutoff])
        
        # Count utilized rare items
        utilized_rare = sum(
            1 for item in items
            if item.get('id') in rare_items and item.get('utilized', False)
        )
        
        utilization_rate = utilized_rare / rarity_cutoff if rarity_cutoff > 0 else 0
        
        return {
            'rarity_threshold': rarity_threshold,
            'total_items': n,
            'rare_items': rarity_cutoff,
            'rare_items_used': utilized_rare,
            'utilization_rate': round(utilization_rate, 3),
            'interpretation': (
                'High diversity' if utilization_rate > 0.5 else
                'Moderate diversity' if utilization_rate > 0.3 else
                'Low diversity - potential echo chamber risk'
            ),
            'sample_rare_ids': list(rare_items)[:5]
        }
    
    def compute_integrity_signals(
        self,
        claimants: List[Dict[str, Any]],
        posts: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        LSD §9.4.2 & §10.4 - Integrity Signals
        
        Detects manipulation patterns:
        1. Burst detection (§9.4.2): unusual submission timing
        2. Template similarity (§10.4): copy-paste campaigns
        3. Participation entropy: concentration of contributions
        """
        signals = []
        
        # 1. Burst detection - posts per hour
        if posts:
            timestamps = sorted([
                datetime.fromisoformat(p['timestamp'].replace('Z', '+00:00'))
                for p in posts if 'timestamp' in p
            ])
            
            if len(timestamps) > 1:
                time_span = (timestamps[-1] - timestamps[0]).total_seconds() / 3600
                if time_span > 0:
                    posts_per_hour = len(timestamps) / time_span
                    
                    if posts_per_hour > 10:
                        signals.append(IntegritySignal(
                            signal_type='burst',
                            severity='high' if posts_per_hour > 30 else 'medium',
                            description=f'Unusual posting rate: {posts_per_hour:.1f} posts/hour',
                            affected_items=[p.get('id', str(i)) for i, p in enumerate(posts[-10:])],
                            metrics={'posts_per_hour': posts_per_hour, 'threshold': 10}
                        ))
        
        # 2. Template similarity detection
        if posts:
            content_samples = [
                p.get('content', '')[:100] for p in posts
                if len(p.get('content', '')) > 50
            ]
            
            # Simple Jaccard similarity on word sets
            similar_pairs = []
            for i, c1 in enumerate(content_samples[:50]):
                words1 = set(c1.lower().split())
                for j, c2 in enumerate(content_samples[i+1:min(i+20, len(content_samples))]):
                    words2 = set(c2.lower().split())
                    if words1 and words2:
                        intersection = len(words1 & words2)
                        union = len(words1 | words2)
                        similarity = intersection / union if union > 0 else 0
                        
                        if similarity > 0.8:
                            similar_pairs.append((i, i+1+j, similarity))
            
            if len(similar_pairs) > 5:
                signals.append(IntegritySignal(
                    signal_type='template_similarity',
                    severity='high' if len(similar_pairs) > 10 else 'medium',
                    description=f'Detected {len(similar_pairs)} similar post pairs (possible template campaign)',
                    affected_items=[str(p[0]) for p in similar_pairs[:10]],
                    metrics={'similar_pairs': len(similar_pairs), 'threshold': 0.8}
                ))
        
        # 3. Participation entropy
        if claimants:
            # Count posts per claimant
            claimant_posts = defaultdict(int)
            for post in posts:
                claimant_id = post.get('claimant_id', 'unknown')
                claimant_posts[claimant_id] += 1
            
            # Calculate Shannon entropy
            total_posts = len(posts)
            if total_posts > 0:
                probs = [count / total_posts for count in claimant_posts.values()]
                entropy = -sum(p * math.log2(p) for p in probs if p > 0)
                max_entropy = math.log2(len(claimants)) if claimants else 1
                normalized_entropy = entropy / max_entropy if max_entropy > 0 else 0
                
                if normalized_entropy < 0.3:
                    signals.append(IntegritySignal(
                        signal_type='participation_entropy',
                        severity='medium',
                        description=f'Low participation diversity: {normalized_entropy:.2f} entropy',
                        affected_items=list(claimant_posts.keys())[:5],
                        metrics={
                            'shannon_entropy': round(entropy, 3),
                            'normalized_entropy': round(normalized_entropy, 3),
                            'dominant_claimant_share': round(max(probs), 3)
                        }
                    ))
        
        return {
            'signals_detected': len(signals),
            'overall_risk': (
                'high' if any(s.severity == 'high' for s in signals) else
                'medium' if any(s.severity == 'medium' for s in signals) else
                'low'
            ),
            'signals': [
                {
                    'type': s.signal_type,
                    'severity': s.severity,
                    'description': s.description,
                    'affected_count': len(s.affected_items),
                    'metrics': s.metrics
                }
                for s in signals
            ],
            'recommendation': (
                'Investigate high-severity signals before finalizing debate' 
                if any(s.severity == 'high' for s in signals) else
                'Monitor medium signals for pattern development'
                if signals else
                'No integrity concerns detected'
            )
        }
    
    def get_selection_transparency_report(
        self,
        debate_id: str,
        argument_units: List[Dict[str, Any]],
        item_refs: Dict[str, List[str]],
        items: List[Dict[str, Any]],
        claimants: List[Dict[str, Any]],
        posts: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Generate complete selection transparency report.
        """
        return {
            'debate_id': debate_id,
            'au_completeness': self.au_completeness_score(argument_units),
            'centrality_analysis': self.compute_centrality_with_capping(item_refs),
            'rarity_utilization': self.rarity_slice_diagnostics(items),
            'integrity_signals': self.compute_integrity_signals(claimants, posts),
            'summary': {
                'selection_quality': 'high' if self.au_completeness_score(argument_units)['average_completeness'] > 0.8 else 'medium',
                'diversity_indicator': self.rarity_slice_diagnostics(items)['interpretation'],
                'integrity_status': self.compute_integrity_signals(claimants, posts)['overall_risk']
            }
        }
