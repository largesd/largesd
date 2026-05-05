"""
OpenRouter Provider for the Debate System

OpenRouter provides unified access to multiple LLM models
via an OpenAI-compatible API.
"""
import os
from typing import Optional
from backend.llm_client import LLMProvider, LLMResponse


class OpenRouterProvider(LLMProvider):
    """OpenRouter API provider - unified access to multiple models"""
    
    def __init__(self, 
                 api_key: Optional[str] = None, 
                 model: Optional[str] = None,
                 site_url: Optional[str] = None,
                 site_name: Optional[str] = None,
                 timeout_seconds: Optional[int] = None):
        """
        Initialize OpenRouter provider.
        
        Args:
            api_key: OpenRouter API key (or set OPENROUTER_API_KEY env var)
            model: Model string (e.g., "anthropic/claude-3.5-sonnet", "openai/gpt-4o").
                   Reads from OPENROUTER_MODEL env var if not provided.
            site_url: Your site URL (for OpenRouter rankings)
            site_name: Your site name (for OpenRouter rankings)
            timeout_seconds: Request timeout. Reads from OPENROUTER_TIMEOUT_SECONDS env var.
        """
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.model = model or os.getenv("OPENROUTER_MODEL")
        self.site_url = site_url or os.getenv("SITE_URL", "")
        self.site_name = site_name or os.getenv("SITE_NAME", "Debate System")
        self.timeout_seconds = timeout_seconds or int(os.getenv("OPENROUTER_TIMEOUT_SECONDS", "60"))
        
        if not self.api_key:
            raise ValueError(
                "OpenRouter API key required. Set OPENROUTER_API_KEY env var "
                "or pass api_key parameter."
            )
        if not self.model:
            raise ValueError(
                "OpenRouter model required. Set OPENROUTER_MODEL env var "
                "or pass model parameter."
            )
        
        try:
            import openai
            # OpenRouter uses OpenAI client with different base URL
            self.client = openai.OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=self.api_key,
                default_headers={
                    "HTTP-Referer": self.site_url,
                    "X-Title": self.site_name
                }
            )
        except ImportError:
            raise ImportError("OpenAI package not installed. Run: pip install openai")
    
    def generate(self, prompt: str, temperature: float = 0.7,
                 max_tokens: int = 500) -> LLMResponse:
        """Generate completion via OpenRouter"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
                extra_headers={  # OpenRouter-specific
                    "HTTP-Referer": self.site_url,
                    "X-Title": self.site_name
                }
            )
            
            return LLMResponse(
                content=response.choices[0].message.content,
                model=response.model or self.model,  # OpenRouter may return actual model used
                usage={
                    "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                    "completion_tokens": response.usage.completion_tokens if response.usage else 0
                },
                finish_reason=response.choices[0].finish_reason
            )
            
        except Exception as e:
            # Fail loudly when provider=openrouter; never silently fall back to mock.
            allow_fallback = os.getenv("ALLOW_MOCK_FALLBACK", "false").lower() in ("1", "true", "yes")
            if allow_fallback:
                print(f"OpenRouter API error: {e}. ALLOW_MOCK_FALLBACK=true, falling back to mock.")
                from llm_client import MockLLMProvider
                return MockLLMProvider().generate(prompt, temperature, max_tokens)
            raise RuntimeError(f"OpenRouter API call failed: {e}") from e
    
    def get_model_pricing(self) -> dict:
        """Get pricing info for current model (requires OpenRouter account)"""
        # This would require calling OpenRouter's API
        # For now, return placeholder
        return {
            "model": self.model,
            "prompt_price_per_1k": "varies",
            "completion_price_per_1k": "varies",
            "note": "See https://openrouter.ai/models for pricing"
        }


class MultiModelJudgeProvider(LLMProvider):
    """
    Multi-model provider for true judge diversity.
    
    Instead of using temperature variation on one model,
    this uses different models for each "judge" to get
n    truly independent evaluations.
    
    Example models (via OpenRouter):
    - "anthropic/claude-3.5-sonnet"
    - "openai/gpt-4o"
    - "google/gemini-pro-1.5"
    - "meta-llama/llama-3.1-70b-instruct"
    """
    
    DEFAULT_JUDGE_MODELS = [
        "anthropic/claude-3.5-sonnet",
        "openai/gpt-4o-mini",
        "google/gemini-flash-1.5",
        "meta-llama/llama-3.1-70b-instruct",
        "mistralai/mistral-large"
    ]
    
    def __init__(self,
                 api_key: Optional[str] = None,
                 judge_models: Optional[list] = None,
                 site_url: Optional[str] = None,
                 site_name: Optional[str] = None):
        """
        Initialize multi-model judge provider.
        
        Args:
            api_key: OpenRouter API key
            judge_models: List of model strings, one per judge
            site_url: Your site URL
            site_name: Your site name
        """
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.judge_models = judge_models or self.DEFAULT_JUDGE_MODELS
        self.site_url = site_url or os.getenv("SITE_URL", "")
        self.site_name = site_name or os.getenv("SITE_NAME", "Debate System")
        
        # Initialize a provider for each judge model
        self.judges = [
            OpenRouterProvider(
                api_key=self.api_key,
                model=model,
                site_url=self.site_url,
                site_name=self.site_name
            )
            for model in self.judge_models
        ]
        
        self.current_judge_index = 0
    
    def generate(self, prompt: str, temperature: float = 0.7,
                 max_tokens: int = 500) -> LLMResponse:
        """
        Generate using round-robin across judge models.
        This ensures different models evaluate different arguments.
        """
        judge = self.judges[self.current_judge_index]
        self.current_judge_index = (self.current_judge_index + 1) % len(self.judges)
        
        return judge.generate(prompt, temperature, max_tokens)
    
    def get_judge_info(self) -> list:
        """Get information about configured judges"""
        return [
            {
                "judge_id": i,
                "model": model,
                "provider": "openrouter"
            }
            for i, model in enumerate(self.judge_models)
        ]


def create_llm_client_with_openrouter(
    api_key: Optional[str] = None,
    model: str = "anthropic/claude-3.5-sonnet",
    num_judges: int = 5,
    multi_model: bool = False
):
    """
    Create an LLMClient configured for OpenRouter.
    
    Args:
        api_key: OpenRouter API key (or set OPENROUTER_API_KEY env var)
        model: Model to use (ignored if multi_model=True)
        num_judges: Number of judges (only used for aggregation count)
        multi_model: If True, uses different models for each judge
    
    Returns:
        Configured LLMClient
    """
    from llm_client import LLMClient
    
    api_key = api_key or os.getenv("OPENROUTER_API_KEY")
    
    if not api_key:
        raise ValueError(
            "OpenRouter API key required. Get one at https://openrouter.ai/keys "
            "and set OPENROUTER_API_KEY environment variable."
        )
    
    if multi_model:
        provider = MultiModelJudgeProvider(api_key=api_key)
    else:
        provider = OpenRouterProvider(api_key=api_key, model=model)
    
    # Create client with provider
    client = LLMClient.__new__(LLMClient)
    client.num_judges = num_judges
    client.provider = provider
    
    return client


# Example usage:
if __name__ == "__main__":
    # Test OpenRouter connection
    import os
    
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("Set OPENROUTER_API_KEY environment variable to test")
        exit(1)
    
    # Single model
    provider = OpenRouterProvider(api_key=api_key)
    response = provider.generate("Say hello", temperature=0.7)
    print(f"Response: {response.content}")
    print(f"Model used: {response.model}")
