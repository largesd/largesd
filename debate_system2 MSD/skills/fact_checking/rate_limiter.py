"""
Rate limiting and circuit breaker for external source queries
"""
import time
import threading
from typing import Dict, Optional, Set
from dataclasses import dataclass
from collections import deque

from .models import RateLimitConfig, CircuitBreakerConfig


@dataclass
class RateLimiterState:
    """State for a rate limiter"""
    last_request_time: float
    request_count_second: int
    request_count_minute: int
    daily_count: int
    daily_reset_time: float
    queue: deque
    
    def __init__(self):
        self.last_request_time = 0.0
        self.request_count_second = 0
        self.request_count_minute = 0
        self.daily_count = 0
        self.daily_reset_time = time.time() + 86400  # 24 hours
        self.queue = deque()


class TokenBucket:
    """Token bucket rate limiter"""
    
    def __init__(self, rate: float, capacity: int):
        """
        Args:
            rate: Tokens added per second
            capacity: Maximum bucket size
        """
        self._rate = rate
        self._capacity = capacity
        self._tokens = capacity
        self._last_update = time.time()
        self._lock = threading.Lock()
    
    def consume(self, tokens: int = 1) -> bool:
        """
        Try to consume tokens from bucket.
        
        Returns:
            True if tokens were consumed, False if not enough available
        """
        with self._lock:
            now = time.time()
            elapsed = now - self._last_update
            
            # Add tokens based on elapsed time
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last_update = now
            
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False
    
    def get_wait_time(self, tokens: int = 1) -> float:
        """Get time to wait until tokens are available"""
        with self._lock:
            if self._tokens >= tokens:
                return 0.0
            needed = tokens - self._tokens
            return needed / self._rate


class CircuitBreaker:
    """Circuit breaker for failing sources"""
    
    STATE_CLOSED = "closed"      # Normal operation
    STATE_OPEN = "open"          # Failing, reject requests
    STATE_HALF_OPEN = "half_open"  # Testing if recovered
    
    def __init__(self, config: CircuitBreakerConfig):
        self._config = config
        self._state = self.STATE_CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._lock = threading.Lock()
    
    def can_execute(self) -> bool:
        """Check if request can be executed"""
        with self._lock:
            if self._state == self.STATE_CLOSED:
                return True
            
            if self._state == self.STATE_OPEN:
                # Check if timeout has elapsed
                elapsed = time.time() - self._last_failure_time
                timeout_seconds = self._config.timeout_minutes * 60
                
                if elapsed > timeout_seconds:
                    self._state = self.STATE_HALF_OPEN
                    return True
                return False
            
            return True  # HALF_OPEN
    
    def record_success(self):
        """Record successful execution"""
        with self._lock:
            self._failure_count = 0
            self._state = self.STATE_CLOSED
    
    def record_failure(self):
        """Record failed execution"""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            
            if self._failure_count >= self._config.failure_threshold:
                self._state = self.STATE_OPEN
    
    def get_state(self) -> str:
        """Get current circuit breaker state"""
        with self._lock:
            return self._state


class SourceRateLimiter:
    """
    Rate limiter for external sources.
    Handles per-source rate limiting with token buckets.
    """
    
    def __init__(self):
        self._limiters: Dict[str, TokenBucket] = {}
        self._configs: Dict[str, RateLimitConfig] = {}
        self._lock = threading.Lock()
    
    def register_source(self, source_id: str, config: RateLimitConfig):
        """Register a source with its rate limit config"""
        with self._lock:
            self._configs[source_id] = config
            self._limiters[source_id] = TokenBucket(
                rate=config.requests_per_second,
                capacity=int(config.requests_per_second * 2)  # Allow burst
            )
    
    def can_request(self, source_id: str) -> bool:
        """Check if a request can be made to the source"""
        with self._lock:
            if source_id not in self._limiters:
                # Unknown source - allow but log warning
                return True
            
            limiter = self._limiters[source_id]
            return limiter.consume(1)
    
    def get_wait_time(self, source_id: str) -> float:
        """Get time to wait before next request is allowed"""
        with self._lock:
            if source_id not in self._limiters:
                return 0.0
            return self._limiters[source_id].get_wait_time(1)


class SourceManager:
    """
    Manages rate limiting and circuit breakers for all sources.
    """
    
    def __init__(self):
        self._rate_limiter = SourceRateLimiter()
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._lock = threading.Lock()
    
    def register_source(self, source_id: str, 
                        rate_config: RateLimitConfig,
                        circuit_config: CircuitBreakerConfig):
        """Register a source with its configurations"""
        with self._lock:
            self._rate_limiter.register_source(source_id, rate_config)
            self._circuit_breakers[source_id] = CircuitBreaker(circuit_config)
    
    def can_query(self, source_id: str) -> tuple[bool, Optional[str]]:
        """
        Check if source can be queried.
        
        Returns:
            Tuple of (can_query, reason_if_not)
        """
        with self._lock:
            # Check circuit breaker
            if source_id in self._circuit_breakers:
                cb = self._circuit_breakers[source_id]
                if not cb.can_execute():
                    return False, f"circuit_breaker_{cb.get_state()}"
            
            # Check rate limit
            if not self._rate_limiter.can_request(source_id):
                wait_time = self._rate_limiter.get_wait_time(source_id)
                return False, f"rate_limited_wait_{wait_time:.2f}s"
            
            return True, None
    
    def record_success(self, source_id: str):
        """Record successful query to source"""
        with self._lock:
            if source_id in self._circuit_breakers:
                self._circuit_breakers[source_id].record_success()
    
    def record_failure(self, source_id: str):
        """Record failed query to source"""
        with self._lock:
            if source_id in self._circuit_breakers:
                self._circuit_breakers[source_id].record_failure()
    
    def get_source_status(self, source_id: str) -> Dict:
        """Get status of a source"""
        with self._lock:
            status = {}
            if source_id in self._circuit_breakers:
                status['circuit_breaker'] = self._circuit_breakers[source_id].get_state()
            return status
