"""
Extraction and Canonicalization Engine
Handles span extraction, fact/argument canonicalization with traceability

Updated to integrate with Fact Checking Skill for P(true) values
"""
import uuid
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime
import json

from backend.llm_client import LLMClient

# Import from new fact checking skill
from skills.fact_checking import RequestContext, V15FactCheckingSkill


@dataclass
class ExtractedSpan:
    """A span extracted from a post"""
    span_id: str
    post_id: str
    start_offset: int
    end_offset: int
    span_text: str
    topic_id: Optional[str]
    side: str
    span_type: str  # "fact" or "inference"


@dataclass
class ExtractedFact:
    """A fact extracted from spans"""
    fact_id: str
    fact_text: str
    topic_id: str
    side: str
    provenance_spans: List[ExtractedSpan] = field(default_factory=list)
    p_true: float = 0.5
    fact_check_job_id: Optional[str] = None  # For async fact checking
    fact_check_status: str = "pending"  # pending, completed, failed
    fact_type: str = "empirical"  # empirical, normative, definitional
    normative_provenance: str = ""
    operationalization: str = ""
    evidence_tier_counts: Dict[str, int] = field(default_factory=dict)
    fact_check_diagnostics: Dict[str, object] = field(default_factory=dict)
    # LSD_FactCheck_v1_5_1 first-class ternary fields
    v15_status: Optional[str] = None  # SUPPORTED, REFUTED, INSUFFICIENT
    v15_p: float = 0.5
    v15_insufficiency_reason: Optional[str] = None
    v15_human_review_flags: List[str] = field(default_factory=list)
    v15_best_evidence_tier: Optional[int] = None


@dataclass
class ExtractedArgument:
    """
    An argument unit extracted from spans.
    
    Per MSD §6.1: Each AU_FACT and AU_INFERENCE must have 
    at least one provenance span (hard rule).
    """
    au_id: str
    topic_id: str
    side: str
    fact_spans: List[ExtractedSpan] = field(default_factory=list)
    inference_span: Optional[ExtractedSpan] = None
    
    # Span references for traceability (MSD §6.1)
    au_facts: List[str] = field(default_factory=list)  # fact texts
    au_facts_span_refs: List[List[str]] = field(default_factory=list)  # [[span_id, ...], ...]
    au_inference: str = ""
    au_inference_span_refs: List[str] = field(default_factory=list)  # [span_id, ...]
    
    def validate_provenance(self) -> Tuple[bool, List[str]]:
        """
        Validate that all facts and inference have provenance spans.
        Returns (is_valid, list of errors).
        """
        errors = []
        
        # Validate each fact has at least one span ref
        for i, refs in enumerate(self.au_facts_span_refs):
            if not refs:
                errors.append(f"AU_FACT[{i}] '{self.au_facts[i][:50]}...' has no provenance span")
        
        # Validate inference has at least one span ref
        if not self.au_inference_span_refs:
            errors.append(f"AU_INFERENCE '{self.au_inference[:50]}...' has no provenance span")
        
        return len(errors) == 0, errors


@dataclass
class CanonicalFact:
    """Canonical (deduplicated) fact"""
    canon_fact_id: str
    topic_id: str
    side: str
    canon_fact_text: str
    member_fact_ids: List[str]
    provenance_spans: List[ExtractedSpan] = field(default_factory=list)
    p_true: float = 0.5
    fact_type: str = "empirical"
    normative_provenance: str = ""
    operationalization: str = ""
    evidence_tier_counts: Dict[str, int] = field(default_factory=dict)
    fact_check_diagnostics: Dict[str, object] = field(default_factory=dict)
    # LSD_FactCheck_v1_5_1 first-class ternary fields
    v15_status: Optional[str] = None
    v15_p: float = 0.5
    v15_insufficiency_reason: Optional[str] = None
    v15_human_review_flags: List[str] = field(default_factory=list)
    v15_best_evidence_tier: Optional[int] = None


@dataclass
class CanonicalArgument:
    """Canonical (deduplicated) argument"""
    canon_arg_id: str
    topic_id: str
    side: str
    inference_text: str
    supporting_facts: List[str]  # canon_fact_ids
    member_au_ids: List[str]
    provenance_spans: List[ExtractedSpan] = field(default_factory=list)


class ExtractionEngine:
    """
    Engine for extracting and canonicalizing debate content
    """
    
    def __init__(self, llm_client: Optional[LLMClient] = None, 
                 fact_check_skill: Optional[V15FactCheckingSkill] = None):
        self.llm_client = llm_client or LLMClient()
        self.fact_checker = fact_check_skill
        self._pending_fact_checks: Dict[str, ExtractedFact] = {}  # job_id -> fact
    
    def extract_spans_from_post(self, post_id: str, facts_text: str,
                                 inference_text: str, side: str,
                                 topic_id: Optional[str] = None) -> Tuple[List[ExtractedSpan], ExtractedSpan]:
        """
        Extract fact spans and inference span from a post
        
        Returns: (list of fact spans, inference span)
        """
        full_text = f"{facts_text}\n\n{inference_text}"
        
        # Use LLM to identify spans
        result = self.llm_client.extract_spans(full_text, facts_text, inference_text)
        
        fact_spans = []
        span_idx = 0
        
        # Create fact spans
        for span_data in result.get("fact_spans", []):
            span = ExtractedSpan(
                span_id=f"span_{post_id}_{span_idx}",
                post_id=post_id,
                start_offset=span_data.get("start", 0),
                end_offset=span_data.get("end", 0),
                span_text=span_data.get("text", ""),
                topic_id=topic_id,
                side=side,
                span_type="fact"
            )
            fact_spans.append(span)
            span_idx += 1
        
        # Create inference span
        inf_data = result.get("inference_span", {})
        inference_span = ExtractedSpan(
            span_id=f"span_{post_id}_{span_idx}",
            post_id=post_id,
            start_offset=inf_data.get("start", len(facts_text)),
            end_offset=inf_data.get("end", len(full_text)),
            span_text=inf_data.get("text", inference_text),
            topic_id=topic_id,
            side=side,
            span_type="inference"
        )
        
        return fact_spans, inference_span
    
    def extract_facts_from_spans(self, fact_spans: List[ExtractedSpan],
                                  topic_id: str, side: str,
                                  post_id: Optional[str] = None) -> List[ExtractedFact]:
        """
        Create ExtractedFact objects from fact spans and submit for fact checking.
        """
        facts = []
        for i, span in enumerate(fact_spans):
            fact_type = self._classify_fact_type(span.span_text)
            fact = ExtractedFact(
                fact_id=f"fact_{span.post_id}_{i}",
                fact_text=span.span_text,
                topic_id=topic_id,
                side=side,
                provenance_spans=[span],
                p_true=0.5,  # Default, will be updated by fact checker
                fact_check_status="pending",
                fact_type=fact_type,
                normative_provenance=(
                    f"source_post_id={post_id or span.post_id}; side={side}; topic_id={topic_id}"
                    if fact_type == "normative" else ""
                ),
                operationalization=self._build_operationalization(span.span_text, fact_type),
            )
            
            # Submit to fact checker if available
            if self.fact_checker and fact_type == "empirical":
                try:
                    request_context = RequestContext(
                        post_id=post_id or span.post_id,
                    )

                    # Only use async submission when the fact-checking skill has async enabled.
                    if hasattr(self.fact_checker, 'check_fact_async') and getattr(self.fact_checker, '_async_enabled', False):
                        job = self.fact_checker.check_fact_async(
                            claim_text=span.span_text,
                            request_context=request_context
                        )
                        fact.fact_check_job_id = job.job_id
                    else:
                        # Otherwise force a resolved result before returning to the caller.
                        if hasattr(self.fact_checker, 'check_fact'):
                            result = self.fact_checker.check_fact(
                                claim_text=span.span_text,
                                request_context=request_context
                            )
                        else:
                            result = self.fact_checker.check_fact(
                                claim_text=span.span_text,
                            )
                        fact.p_true = result.factuality_score
                        fact.fact_check_status = "completed"
                        fact.operationalization = result.operationalization or fact.operationalization
                        fact.evidence_tier_counts = getattr(result, "evidence_tier_counts", {})
                        # Merge diagnostics; v1.5 bridge skill enriches with v15_* fields
                        diagnostics = getattr(result, "diagnostics", {}) or {}
                        fact.fact_check_diagnostics = diagnostics
                        # Populate first-class v1.5 ternary fields
                        fact.v15_status = diagnostics.get("v15_status")
                        fact.v15_p = diagnostics.get("v15_p", result.factuality_score)
                        fact.v15_insufficiency_reason = diagnostics.get("v15_insufficiency_reason")
                        fact.v15_human_review_flags = diagnostics.get("v15_human_review_flags", [])
                        fact.v15_best_evidence_tier = diagnostics.get("v15_best_evidence_tier")
                        
                except Exception as e:
                    # Fact check failed, use default
                    fact.fact_check_status = "failed"
            elif fact_type != "empirical":
                fact.fact_check_status = "completed"
            
            facts.append(fact)
        
        return facts

    @staticmethod
    def _classify_fact_type(text: str) -> str:
        lowered = (text or "").lower()
        normative_markers = (
            "should", "ought", "unjust", "fair", "unfair", "priority", "right",
            "wrong", "moral", "ethical", "deserve", "must", "value",
        )
        definitional_markers = ("means", "defined as", "refers to", "definition")
        if any(marker in lowered for marker in definitional_markers):
            return "definitional"
        if any(marker in lowered for marker in normative_markers):
            return "normative"
        return "empirical"

    @staticmethod
    def _build_operationalization(text: str, fact_type: str) -> str:
        if fact_type == "normative":
            return "Assess acceptability against the active frame values and comparable cases."
        if fact_type == "definitional":
            return "Confirm whether the active frame definitions or ordinary usage support this definition."
        return f"Identify primary or reputable secondary evidence that would confirm or refute: {text[:160]}"
    
    def update_fact_check_results(self, facts: List[ExtractedFact]) -> List[ExtractedFact]:
        """
        Update facts with completed fact check results.
        Call this periodically to refresh P(true) values from async fact checks.
        """
        if not self.fact_checker:
            return facts
        
        updated_facts = []
        for fact in facts:
            if fact.fact_check_status == "pending" and fact.fact_check_job_id:
                # Check if result is available
                try:
                    result = self.fact_checker.get_job_result(fact.fact_check_job_id)
                    if result:
                        fact.p_true = result.factuality_score
                        fact.fact_check_status = "completed"
                        fact.operationalization = result.operationalization or fact.operationalization
                        fact.evidence_tier_counts = getattr(result, "evidence_tier_counts", {})
                        diagnostics = getattr(result, "diagnostics", {}) or {}
                        fact.fact_check_diagnostics = diagnostics
                        # Populate first-class v1.5 ternary fields
                        fact.v15_status = diagnostics.get("v15_status")
                        fact.v15_p = diagnostics.get("v15_p", result.factuality_score)
                        fact.v15_insufficiency_reason = diagnostics.get("v15_insufficiency_reason")
                        fact.v15_human_review_flags = diagnostics.get("v15_human_review_flags", [])
                        fact.v15_best_evidence_tier = diagnostics.get("v15_best_evidence_tier")
                except Exception:
                    pass  # Still pending or failed
            
            updated_facts.append(fact)
        
        return updated_facts
    
    def create_argument_units(self, fact_spans: List[ExtractedSpan],
                              inference_span: ExtractedSpan,
                              extracted_facts: List[ExtractedFact],
                              topic_id: str, side: str) -> List[ExtractedArgument]:
        """
        Create Argument Units from spans with full provenance tracking.
        
        MSD §6.1 Hard Rule: Every AU_FACT and AU_INFERENCE must have 
        at least one provenance span.
        
        Creates one AU per post (simplest case).
        """
        # Build span reference mapping for facts
        # Each fact should reference the span it came from
        au_facts_span_refs = []
        au_facts = []
        
        for fact in extracted_facts:
            # Get span IDs from fact's provenance
            span_refs = [span.span_id for span in fact.provenance_spans]
            
            # Hard rule enforcement: every fact MUST have provenance
            if not span_refs:
                # Create a fallback reference to the first fact span if available
                if fact_spans:
                    span_refs = [fact_spans[0].span_id]
                else:
                    raise ValueError(
                        f"Fact '{fact.fact_text[:50]}...' has no provenance spans. "
                        "MSD §6.1 hard rule violated."
                    )
            
            au_facts.append(fact.fact_text)
            au_facts_span_refs.append(span_refs)
        
        # Inference span references (hard rule enforcement)
        inference_span_refs = []
        if inference_span:
            inference_span_refs = [inference_span.span_id]
        else:
            raise ValueError(
                "AU_INFERENCE has no provenance span. MSD §6.1 hard rule violated."
            )
        
        au = ExtractedArgument(
            au_id=f"au_{inference_span.post_id}",
            topic_id=topic_id,
            side=side,
            fact_spans=fact_spans,
            inference_span=inference_span,
            au_facts=au_facts,
            au_facts_span_refs=au_facts_span_refs,
            au_inference=inference_span.span_text,
            au_inference_span_refs=inference_span_refs
        )
        
        # Validate before returning
        is_valid, errors = au.validate_provenance()
        if not is_valid:
            raise ValueError(f"ArgumentUnit provenance validation failed: {errors}")
        
        return [au]
    
    def canonicalize_facts(self, facts: List[ExtractedFact],
                           topic_scope: str) -> List[CanonicalFact]:
        """
        Canonicalize facts by clustering semantically similar ones
        """
        if not facts:
            return []
        
        # Prepare facts for LLM
        facts_data = [
            {"id": f.fact_id, "text": f.fact_text, "side": f.side, "p_true": f.p_true, "fact_type": f.fact_type}
            for f in facts
        ]
        
        # Get clusters from LLM
        result = self.llm_client.canonicalize_facts(facts_data, topic_scope)
        
        canonical_facts = []
        fact_lookup = {f.fact_id: f for f in facts}
        
        # Create canonical facts from clusters
        for i, cluster in enumerate(result.get("clusters", [])):
            member_ids = cluster.get("member_ids", [])
            member_facts = [fact_lookup.get(mid) for mid in member_ids if mid in fact_lookup]
            
            if not member_facts:
                continue
            
            # Merge provenance spans
            all_spans = []
            for mf in member_facts:
                all_spans.extend(mf.provenance_spans)
            
            # Calculate aggregate p_true from member facts
            # Use mean of P(true) values
            avg_p = sum(mf.p_true for mf in member_facts) / len(member_facts)
            fact_types = [getattr(mf, "fact_type", "empirical") for mf in member_facts]
            fact_type = "normative" if "normative" in fact_types else "definitional" if "definitional" in fact_types else "empirical"
            tier_counts: Dict[str, int] = {"TIER_1": 0, "TIER_2": 0, "TIER_3": 0}
            for mf in member_facts:
                for tier, count in getattr(mf, "evidence_tier_counts", {}).items():
                    tier_counts[tier] = tier_counts.get(tier, 0) + int(count)
            
            # Aggregate v1.5 ternary fields across cluster members
            v15_statuses = [mf.v15_status for mf in member_facts if mf.v15_status]
            if v15_statuses and all(s == v15_statuses[0] for s in v15_statuses):
                cluster_v15_status = v15_statuses[0]
            else:
                cluster_v15_status = "INSUFFICIENT"
            cluster_v15_p = round(
                sum(mf.v15_p for mf in member_facts) / len(member_facts), 2
            )
            v15_reasons = [mf.v15_insufficiency_reason for mf in member_facts if mf.v15_insufficiency_reason]
            cluster_v15_reason = v15_reasons[0] if v15_reasons else ("mixed_cluster_evidence" if len(set(v15_statuses)) > 1 else None)
            cluster_v15_flags = list(set(
                flag for mf in member_facts for flag in mf.v15_human_review_flags
            ))
            v15_tiers = [mf.v15_best_evidence_tier for mf in member_facts if mf.v15_best_evidence_tier is not None]
            cluster_v15_tier = min(v15_tiers) if v15_tiers else None

            cf = CanonicalFact(
                canon_fact_id=f"cf_{facts[0].topic_id}_{i}",
                topic_id=facts[0].topic_id,
                side=member_facts[0].side,  # All in cluster should be same side
                canon_fact_text=cluster.get("canonical_text", member_facts[0].fact_text),
                member_fact_ids=member_ids,
                provenance_spans=all_spans,
                p_true=round(avg_p, 2),
                fact_type=fact_type,
                normative_provenance="; ".join(mf.normative_provenance for mf in member_facts if mf.normative_provenance),
                operationalization=member_facts[0].operationalization,
                evidence_tier_counts=tier_counts,
                fact_check_diagnostics=member_facts[0].fact_check_diagnostics if member_facts else {},
                v15_status=cluster_v15_status,
                v15_p=cluster_v15_p,
                v15_insufficiency_reason=cluster_v15_reason,
                v15_human_review_flags=cluster_v15_flags,
                v15_best_evidence_tier=cluster_v15_tier,
            )
            canonical_facts.append(cf)
        
        # Handle unclustered facts as singletons
        clustered_ids = set()
        for cluster in result.get("clusters", []):
            clustered_ids.update(cluster.get("member_ids", []))
        
        unclustered = result.get("unclustered_ids", [])
        for uid in unclustered:
            if uid in fact_lookup and uid not in clustered_ids:
                f = fact_lookup[uid]
                cf = CanonicalFact(
                    canon_fact_id=f"cf_{f.topic_id}_u{len(canonical_facts)}",
                    topic_id=f.topic_id,
                    side=f.side,
                    canon_fact_text=f.fact_text,
                    member_fact_ids=[uid],
                    provenance_spans=f.provenance_spans,
                    p_true=f.p_true,
                    fact_type=f.fact_type,
                    normative_provenance=f.normative_provenance,
                    operationalization=f.operationalization,
                    evidence_tier_counts=getattr(f, "evidence_tier_counts", {}),
                    fact_check_diagnostics=getattr(f, "fact_check_diagnostics", {}),
                    v15_status=f.v15_status,
                    v15_p=f.v15_p,
                    v15_insufficiency_reason=f.v15_insufficiency_reason,
                    v15_human_review_flags=list(f.v15_human_review_flags),
                    v15_best_evidence_tier=f.v15_best_evidence_tier,
                )
                canonical_facts.append(cf)
        
        return canonical_facts
    
    def canonicalize_arguments(self, argument_units: List[ExtractedArgument],
                               canonical_facts: List[CanonicalFact],
                               topic_scope: str) -> List[CanonicalArgument]:
        """
        Canonicalize arguments by clustering similar inferences and fact patterns
        """
        if not argument_units:
            return []
        
        # Map facts to canonical facts for reference
        fact_to_canon = {}
        for cf in canonical_facts:
            for mf_id in cf.member_fact_ids:
                fact_to_canon[mf_id] = cf.canon_fact_id
        
        # Prepare arguments for LLM
        args_data = []
        for au in argument_units:
            # Map to canonical fact IDs
            canon_fact_ids = []
            for fact_text in au.au_facts:
                for cf in canonical_facts:
                    if fact_text == cf.canon_fact_text or fact_text in [f.fact_text for f in 
                        [ExtractedFact(fact_id="", fact_text=fact_text, topic_id="", side="", p_true=0.5)]]:
                        canon_fact_ids.append(cf.canon_fact_id)
                        break
            
            args_data.append({
                "id": au.au_id,
                "inference": au.au_inference,
                "supporting_facts": canon_fact_ids,
                "side": au.side
            })
        
        # Get clusters from LLM
        result = self.llm_client.canonicalize_arguments(args_data, topic_scope)
        
        canonical_args = []
        au_lookup = {au.au_id: au for au in argument_units}
        
        # Create canonical arguments from clusters
        for i, cluster in enumerate(result.get("clusters", [])):
            member_ids = cluster.get("member_ids", [])
            member_aus = [au_lookup.get(mid) for mid in member_ids if mid in au_lookup]
            
            if not member_aus:
                continue
            
            # Merge provenance spans
            all_spans = []
            for mau in member_aus:
                all_spans.extend(mau.fact_spans)
                if mau.inference_span:
                    all_spans.append(mau.inference_span)
            
            ca = CanonicalArgument(
                canon_arg_id=f"ca_{member_aus[0].topic_id}_{i}",
                topic_id=member_aus[0].topic_id,
                side=member_aus[0].side,
                inference_text=cluster.get("canonical_inference", member_aus[0].au_inference),
                supporting_facts=cluster.get("supporting_facts", []),
                member_au_ids=member_ids,
                provenance_spans=all_spans
            )
            canonical_args.append(ca)
        
        return canonical_args
    
    def compute_extraction_stability(self, posts: List[Dict],
                                     topic_scope: str,
                                     num_runs: int = 2) -> Dict:
        """
        Run extraction multiple times to measure stability
        
        Returns stability metrics comparing runs
        """
        all_run_facts = []
        all_run_args = []
        
        for run_idx in range(num_runs):
            run_facts = []
            run_args = []
            
            for post in posts:
                # Extract spans
                fact_spans, inf_span = self.extract_spans_from_post(
                    post['post_id'],
                    post['facts'],
                    post['inference'],
                    post['side'],
                    post.get('topic_id')
                )
                
                # Extract facts
                facts = self.extract_facts_from_spans(
                    fact_spans,
                    post.get('topic_id', 'unknown'),
                    post['side'],
                    post.get('post_id')
                )
                run_facts.extend(facts)
                
                # Create argument units
                aus = self.create_argument_units(
                    fact_spans, inf_span, facts,
                    post.get('topic_id', 'unknown'),
                    post['side']
                )
                run_args.extend(aus)
            
            # Canonicalize
            canon_facts = self.canonicalize_facts(run_facts, topic_scope)
            canon_args = self.canonicalize_arguments(run_args, canon_facts, topic_scope)
            
            all_run_facts.append(canon_facts)
            all_run_args.append(canon_args)
        
        # Compute overlap between runs
        fact_overlap = self._compute_set_overlap(
            [set(f.canon_fact_text for f in run) for run in all_run_facts]
        )
        
        arg_overlap = self._compute_set_overlap(
            [set(a.inference_text for a in run) for run in all_run_args]
        )
        
        # Find mismatches
        mismatches = self._find_mismatches(all_run_facts[0], all_run_facts[1] if len(all_run_facts) > 1 else [])
        
        return {
            "fact_overlap": fact_overlap,
            "argument_overlap": arg_overlap,
            "mismatches": mismatches,
            "num_runs": num_runs,
            "stability_score": (fact_overlap["jaccard"] + arg_overlap["jaccard"]) / 2
        }
    
    def _compute_set_overlap(self, sets: List[set]) -> Dict:
        """Compute overlap metrics between sets"""
        if len(sets) < 2:
            return {"jaccard": 1.0, "precision": 1.0, "recall": 1.0}
        
        set1, set2 = sets[0], sets[1]
        
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        
        jaccard = intersection / union if union > 0 else 0.0
        precision = intersection / len(set2) if len(set2) > 0 else 0.0
        recall = intersection / len(set1) if len(set1) > 0 else 0.0
        
        return {
            "jaccard": round(jaccard, 3),
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "intersection_size": intersection,
            "set1_size": len(set1),
            "set2_size": len(set2)
        }
    
    def _find_mismatches(self, facts1: List[CanonicalFact],
                         facts2: List[CanonicalFact]) -> List[Dict]:
        """Find important mismatches between extraction runs"""
        texts1 = {f.canon_fact_text for f in facts1}
        texts2 = {f.canon_fact_text for f in facts2}
        
        mismatches = []
        
        def _severity(f: CanonicalFact) -> str:
            # v1.5: SUPPORTED/REFUTED are fully decisive → high severity if missed
            if f.v15_status in ("SUPPORTED", "REFUTED"):
                return "high"
            # Legacy fallback: decisive p values are high severity
            if abs(f.p_true - 0.5) > 0.2:
                return "high"
            return "medium"
        
        # Facts in run 1 but not run 2
        for f in facts1:
            if f.canon_fact_text not in texts2:
                mismatches.append({
                    "type": "missing_in_run2",
                    "fact_text": f.canon_fact_text,
                    "p_true": f.p_true,
                    "v15_status": f.v15_status,
                    "severity": _severity(f)
                })
        
        # Facts in run 2 but not run 1
        for f in facts2:
            if f.canon_fact_text not in texts1:
                mismatches.append({
                    "type": "missing_in_run1",
                    "fact_text": f.canon_fact_text,
                    "p_true": f.p_true,
                    "v15_status": f.v15_status,
                    "severity": _severity(f)
                })
        
        return mismatches[:10]  # Limit to top 10
