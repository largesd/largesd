"""
LLM Client for multi-judge evaluation and text processing
Supports multiple providers with a unified interface
"""
import os
import json
import re
from typing import List, Dict, Optional, Callable, Any
from dataclasses import dataclass
from abc import ABC, abstractmethod
import random


@dataclass
class LLMResponse:
    """Standardized LLM response"""
    content: str
    model: str
    usage: Dict[str, int]
    finish_reason: str


class LLMProvider(ABC):
    """Abstract base class for LLM providers"""
    
    @abstractmethod
    def generate(self, prompt: str, temperature: float = 0.7, 
                 max_tokens: int = 500) -> LLMResponse:
        pass


class MockLLMProvider(LLMProvider):
    """Mock provider for testing without API keys"""
    
    def __init__(self, seed: int = 42):
        self.seed = seed
        random.seed(seed)
    
    def generate(self, prompt: str, temperature: float = 0.7,
                 max_tokens: int = 500) -> LLMResponse:
        """Generate deterministic mock response based on prompt hash"""
        # Simple mock responses based on prompt content
        # Order matters: more specific patterns first
        prompt_lower = prompt.lower()
        
        if "reasoning" in prompt_lower or "judge" in prompt_lower:
            return self._mock_reasoning_response()
        elif "coverage" in prompt_lower or "addressed" in prompt_lower:
            return self._mock_coverage_response()
        elif "span" in prompt_lower:
            # Span extraction (check before fact-check to avoid misrouting)
            return self._mock_span_extraction_response(prompt)
        elif "extract" in prompt_lower and "topic" in prompt_lower:
            return self._mock_topic_extraction_response(prompt)
        elif "fact" in prompt_lower and "check" in prompt_lower:
            return self._mock_fact_check_response(prompt)
        elif "canonicalize" in prompt_lower or "deduplicate" in prompt_lower:
            return self._mock_canonicalization_response(prompt)
        elif "summary" in prompt_lower and "steelman" in prompt_lower:
            return self._mock_summary_response(prompt)
        else:
            return self._mock_generic_response()
    
    def _mock_reasoning_response(self) -> LLMResponse:
        score = round(random.uniform(0.45, 0.85), 2)
        return LLMResponse(
            content=json.dumps({
                "reasoning_score": score,
                "explanation": f"Argument demonstrates {'strong' if score > 0.65 else 'moderate' if score > 0.5 else 'weak'} logical coherence.",
                "strengths": ["Clear premise-conclusion structure"],
                "weaknesses": [] if score > 0.65 else ["Could strengthen evidence links"]
            }),
            model="mock-reasoning-v1",
            usage={"prompt_tokens": 100, "completion_tokens": 50},
            finish_reason="stop"
        )
    
    def _mock_coverage_response(self) -> LLMResponse:
        addressed = random.choice([True, True, True, False])  # 75% addressed
        return LLMResponse(
            content=json.dumps({
                "addressed": addressed,
                "confidence": round(random.uniform(0.6, 0.9), 2),
                "explanation": f"Opposing argument is {'directly rebutted' if addressed else 'not adequately addressed'}.",
                "citation_span_id": f"span_{random.randint(1, 10)}"
            }),
            model="mock-coverage-v1",
            usage={"prompt_tokens": 150, "completion_tokens": 40},
            finish_reason="stop"
        )
    
    def _mock_topic_extraction_response(self, prompt: str) -> LLMResponse:
        # Extract some keywords from prompt for topic names
        return LLMResponse(
            content=json.dumps({
                "topics": [
                    {
                        "name": "Safety and Risk Management",
                        "scope": "Analysis of potential harms and safety measures",
                        "keywords": ["safety", "risk", "harm", "protection"],
                        "estimated_relevance": 0.35
                    },
                    {
                        "name": "Economic Impact",
                        "scope": "Economic consequences and market effects",
                        "keywords": ["economic", "jobs", "market", "cost"],
                        "estimated_relevance": 0.25
                    },
                    {
                        "name": "Regulation and Governance",
                        "scope": "Policy approaches and enforcement mechanisms",
                        "keywords": ["regulation", "policy", "governance", "ban"],
                        "estimated_relevance": 0.25
                    },
                    {
                        "name": "Innovation and Progress",
                        "scope": "Impact on technological advancement",
                        "keywords": ["innovation", "progress", "development", "research"],
                        "estimated_relevance": 0.15
                    }
                ]
            }),
            model="mock-topics-v1",
            usage={"prompt_tokens": 200, "completion_tokens": 150},
            finish_reason="stop"
        )
    
    def _mock_fact_check_response(self, prompt: str) -> LLMResponse:
        # Generate deterministic score from prompt content
        score = round(random.uniform(0.3, 0.8), 2)
        return LLMResponse(
            content=json.dumps({
                "factuality_score": score,
                "confidence": round(random.uniform(0.5, 0.9), 2),
                "verdict": "SUPPORTED" if score > 0.7 else "MIXED" if score > 0.4 else "INSUFFICIENT_EVIDENCE",
                "evidence_summary": "Based on available sources, this claim has " + 
                    ("strong support" if score > 0.7 else "mixed support" if score > 0.4 else "limited empirical backing"),
                "sources": [
                    {"title": "Research Study", "relevance": 0.85, "support": score > 0.6}
                ]
            }),
            model="mock-factcheck-v1",
            usage={"prompt_tokens": 120, "completion_tokens": 80},
            finish_reason="stop"
        )
    
    def _mock_canonicalization_response(self, prompt: str) -> LLMResponse:
        return LLMResponse(
            content=json.dumps({
                "clusters": [
                    {
                        "canonical_text": "Clustered fact text",
                        "member_ids": ["fact_1", "fact_2"],
                        "confidence": 0.85
                    }
                ],
                "merged_count": 2,
                "kept_singletons": ["fact_3"]
            }),
            model="mock-canonicalize-v1",
            usage={"prompt_tokens": 180, "completion_tokens": 60},
            finish_reason="stop"
        )
    
    def _mock_span_extraction_response(self, prompt: str) -> LLMResponse:
        return LLMResponse(
            content=json.dumps({
                "fact_spans": [
                    {"start": 0, "end": 50, "text": "Extracted fact span 1", "type": "fact"},
                    {"start": 51, "end": 120, "text": "Extracted fact span 2", "type": "fact"}
                ],
                "inference_span": {"start": 121, "end": 200, "text": "Inference text", "type": "inference"}
            }),
            model="mock-spans-v1",
            usage={"prompt_tokens": 100, "completion_tokens": 70},
            finish_reason="stop"
        )
    
    def _mock_summary_response(self, prompt: str) -> LLMResponse:
        return LLMResponse(
            content=json.dumps({
                "summary": "Steelman summary presenting the strongest version of arguments.",
                "cited_arguments": ["arg_1", "arg_2"],
                "cited_facts": ["fact_1", "fact_2"],
                "key_claims": ["Main claim 1", "Main claim 2"]
            }),
            model="mock-summary-v1",
            usage={"prompt_tokens": 250, "completion_tokens": 100},
            finish_reason="stop"
        )
    
    def _mock_generic_response(self) -> LLMResponse:
        return LLMResponse(
            content=json.dumps({"result": "success", "data": {}}),
            model="mock-generic-v1",
            usage={"prompt_tokens": 50, "completion_tokens": 20},
            finish_reason="stop"
        )


class OpenAIProvider(LLMProvider):
    """OpenAI API provider"""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model
        try:
            import openai
            self.client = openai.OpenAI(api_key=self.api_key)
        except ImportError:
            raise ImportError("OpenAI package not installed. Run: pip install openai")
    
    def generate(self, prompt: str, temperature: float = 0.7,
                 max_tokens: int = 500) -> LLMResponse:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens
            )
            return LLMResponse(
                content=response.choices[0].message.content,
                model=self.model,
                usage={
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens
                },
                finish_reason=response.choices[0].finish_reason
            )
        except Exception as e:
            # Fall back to mock on error
            print(f"OpenAI API error: {e}. Falling back to mock.")
            return MockLLMProvider().generate(prompt, temperature, max_tokens)


class LLMClient:
    """
    Unified LLM client for debate system
    Supports multiple judges and retry logic
    """
    
    def __init__(self, provider: Optional[str] = None, 
                 num_judges: int = 5,
                 api_key: Optional[str] = None):
        self.num_judges = num_judges
        
        # Initialize provider
        provider = provider or os.getenv("LLM_PROVIDER", "mock")
        
        if provider == "openai":
            self.provider = OpenAIProvider(api_key=api_key)
        elif provider == "openrouter":
            # Import here to avoid circular dependency
            from llm_client_openrouter import OpenRouterProvider
            self.provider = OpenRouterProvider(api_key=api_key)
        elif provider == "openrouter-multi":
            # Multi-model judge diversity
            from llm_client_openrouter import MultiModelJudgeProvider
            self.provider = MultiModelJudgeProvider(api_key=api_key)
        else:
            self.provider = MockLLMProvider()
    
    def generate(self, prompt: str, temperature: float = 0.7,
                 max_tokens: int = 500) -> LLMResponse:
        """Single generation"""
        return self.provider.generate(prompt, temperature, max_tokens)
    
    def generate_multiple(self, prompt: str, n: int = None,
                          temperature_range: tuple = (0.3, 0.9),
                          max_tokens: int = 500) -> List[LLMResponse]:
        """
        Generate multiple responses (for multi-judge evaluation)
        Uses different temperatures for diversity
        """
        n = n or self.num_judges
        responses = []
        
        for i in range(n):
            # Vary temperature for diversity
            t_min, t_max = temperature_range
            temp = t_min + (t_max - t_min) * (i / max(n - 1, 1))
            response = self.provider.generate(prompt, temp, max_tokens)
            responses.append(response)
        
        return responses
    
    def extract_json(self, response: LLMResponse) -> Optional[Dict]:
        """Extract JSON from response, handling common formats"""
        content = response.content.strip()
        
        # Try direct JSON parse
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        
        # Try extracting from markdown code block
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        
        # Try extracting from single backticks
        json_match = re.search(r'`(\{[\s\S]*?\})`', content)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        
        return None
    
    def judge_reasoning(self, argument_text: str, supporting_facts: List[str]) -> List[Dict]:
        """
        Multi-judge reasoning evaluation (MSD §10.2, §14.B)
        Returns list of judge evaluations with disagreement statistics
        """
        prompt = f"""Evaluate the reasoning strength of the following argument.

Supporting Facts:
{chr(10).join(f"- {f}" for f in supporting_facts)}

Inference/Conclusion:
{argument_text}

Rate the reasoning strength (0-1) based on:
1. Logical coherence (do premises support conclusion?)
2. Internal validity (are there logical fallacies?)
3. Strength of inference (how well do facts lead to conclusion?)

Respond in JSON format:
{{
    "reasoning_score": <float 0-1>,
    "explanation": "<brief explanation>",
    "strengths": ["<strength 1>", "<strength 2>"],
    "weaknesses": ["<weakness 1>"] // if any
}}
"""
        
        responses = self.generate_multiple(prompt, n=self.num_judges)
        evaluations = []
        
        for resp in responses:
            data = self.extract_json(resp)
            if data and "reasoning_score" in data:
                evaluations.append({
                    "score": data["reasoning_score"],
                    "explanation": data.get("explanation", ""),
                    "strengths": data.get("strengths", []),
                    "weaknesses": data.get("weaknesses", [])
                })
        
        return evaluations
    
    def aggregate_judge_scores(self, evaluations: List[Dict]) -> Dict:
        """
        Aggregate multi-judge scores with robust statistics (MSD §10, §14.B)
        
        Returns dict with:
        - median: robust central tendency
        - mean: average score
        - iqr: interquartile range (dispersion measure)
        - std: standard deviation
        - min/max: range
        - all_scores: individual judge scores
        """
        import numpy as np
        
        if not evaluations:
            return {
                "median": 0.5,
                "mean": 0.5,
                "iqr": 0.0,
                "std": 0.0,
                "min": 0.5,
                "max": 0.5,
                "all_scores": [],
                "count": 0
            }
        
        scores = [e["score"] for e in evaluations]
        
        # Robust statistics per MSD §10
        median = float(np.median(scores))
        q75, q25 = np.percentile(scores, [75, 25])
        iqr = float(q75 - q25)
        
        return {
            "median": median,  # Primary aggregation per MSD §10.2
            "mean": float(np.mean(scores)),
            "iqr": iqr,  # Dispersion for audit (MSD §14.B)
            "std": float(np.std(scores)),
            "min": float(np.min(scores)),
            "max": float(np.max(scores)),
            "q25": float(q25),
            "q75": float(q75),
            "all_scores": scores,
            "count": len(scores),
            "disagreement_level": "high" if iqr > 0.2 else "moderate" if iqr > 0.1 else "low"
        }
    
    def judge_coverage(self, opposing_argument: Dict, rebuttal_text: str) -> List[Dict]:
        """
        Multi-judge coverage evaluation
        Returns list of judge determinations on whether argument is addressed
        """
        prompt = f"""Determine if the following opposing argument has been adequately addressed/rebutted.

Opposing Argument:
{opposing_argument.get('inference_text', '')}

Supporting Facts of Opposing Argument:
{chr(10).join(f"- {f}" for f in opposing_argument.get('supporting_facts', []))}

Rebuttal/Counter-argument Text:
{rebuttal_text}

Has the opposing argument been addressed? Respond in JSON format:
{{
    "addressed": <true/false>,
    "confidence": <float 0-1>,
    "explanation": "<why it is or isn't addressed>",
    "citation": "<specific text from rebuttal that addresses it, if any>"
}}
"""
        
        responses = self.generate_multiple(prompt, n=self.num_judges)
        determinations = []
        
        for resp in responses:
            data = self.extract_json(resp)
            if data and "addressed" in data:
                determinations.append({
                    "addressed": data["addressed"],
                    "confidence": data.get("confidence", 0.5),
                    "explanation": data.get("explanation", ""),
                    "citation": data.get("citation", "")
                })
        
        return determinations
    
    def extract_spans(self, post_text: str, facts_text: str, inference_text: str) -> Dict:
        """Extract fact and inference spans from a post"""
        prompt = f"""Analyze this debate post and extract traceable spans.

Full Post Text:
{post_text}

Factual Claims Section:
{facts_text}

Inference Section:
{inference_text}

Extract:
1. Individual fact spans (atomic, checkable claims)
2. The inference span (conclusion drawn)

For each span, provide start/end character offsets within the full post text.

Respond in JSON format:
{{
    "fact_spans": [
        {{
            "start": <int>,
            "end": <int>,
            "text": "<exact substring>",
            "type": "fact"
        }}
    ],
    "inference_span": {{
        "start": <int>,
        "end": <int>,
        "text": "<exact substring>",
        "type": "inference"
    }}
}}
"""
        
        response = self.generate(prompt, temperature=0.3)
        return self.extract_json(response) or {"fact_spans": [], "inference_span": None}
    
    def canonicalize_facts(self, facts: List[Dict], topic_scope: str) -> Dict:
        """Cluster and canonicalize facts"""
        facts_text = chr(10).join(f"{i+1}. {f['text']}" for i, f in enumerate(facts))
        
        prompt = f"""Canonicalize these factual claims by clustering semantically equivalent facts.

Topic Scope: {topic_scope}

Facts to Canonicalize:
{facts_text}

Group similar facts into clusters. For each cluster:
1. Create a canonical (representative) version
2. List the IDs of facts in that cluster

Respond in JSON format:
{{
    "clusters": [
        {{
            "canonical_text": "<unified fact text>",
            "member_ids": ["fact_id_1", "fact_id_2"],
            "confidence": <float 0-1>
        }}
    ],
    "unclustered_ids": ["fact_id_3"] // facts that don't cluster with others
}}
"""
        
        response = self.generate(prompt, temperature=0.3)
        return self.extract_json(response) or {"clusters": [], "unclustered_ids": []}
    
    def canonicalize_arguments(self, arguments: List[Dict], topic_scope: str) -> Dict:
        """Cluster and canonicalize arguments"""
        args_text = chr(10).join(
            f"{i+1}. Inference: {a['inference']}\n   Supporting: {', '.join(a.get('supporting_facts', []))}"
            for i, a in enumerate(arguments)
        )
        
        prompt = f"""Canonicalize these arguments by clustering those with similar inferences and fact patterns.

Topic Scope: {topic_scope}

Arguments to Canonicalize:
{args_text}

Group similar arguments. For each cluster:
1. Create a canonical inference text
2. List the IDs of arguments in that cluster
3. Include union of supporting facts

Respond in JSON format:
{{
    "clusters": [
        {{
            "canonical_inference": "<unified inference text>",
            "member_ids": ["arg_id_1", "arg_id_2"],
            "supporting_facts": ["fact_id_1", "fact_id_2"],
            "confidence": <float 0-1>
        }}
    ]
}}
"""
        
        response = self.generate(prompt, temperature=0.3)
        return self.extract_json(response) or {"clusters": []}
    
    def extract_topics(self, posts_text: List[str], debate_resolution: str) -> List[Dict]:
        """Extract topics from debate posts"""
        combined_text = chr(10).join(f"Post {i+1}: {text}" for i, text in enumerate(posts_text))
        
        prompt = f"""Extract distinct debate topics from these posts about: {debate_resolution}

Posts:
{combined_text}

Identify 3-5 distinct topics that:
1. Cover the main areas of disagreement
2. Use neutral, non-evaluative framing
3. Include both sides' concerns in scope
4. Are mutually distinct

Respond in JSON format:
{{
    "topics": [
        {{
            "name": "<neutral topic name>",
            "scope": "<1-2 sentence neutral description>",
            "keywords": ["keyword1", "keyword2"],
            "estimated_relevance": <float 0-1>
        }}
    ]
}}
"""
        
        response = self.generate(prompt, temperature=0.5)
        data = self.extract_json(response)
        return data.get("topics", []) if data else []
    
    def generate_steelman_summary(self, canonical_arguments: List[Dict], side: str) -> Dict:
        """Generate steelman summary for a side"""
        args_text = chr(10).join(
            f"- {a['inference_text']}" for a in canonical_arguments
        )
        
        prompt = f"""Generate a steelman summary (strongest version) for the {side} side.

Canonical Arguments:
{args_text}

Create a concise summary that:
1. Presents the strongest version of each argument
2. Cites which arguments support which claims
3. Does not introduce new facts or inferences
4. Is neutral in tone but comprehensive

Respond in JSON format:
{{
    "summary": "<steelman summary text>",
    "cited_arguments": ["arg_id_1", "arg_id_2"],
    "key_claims": ["<claim 1>", "<claim 2>"]
}}
"""
        
        response = self.generate(prompt, temperature=0.4)
        return self.extract_json(response) or {"summary": "", "cited_arguments": []}
