"""
Multi-layer cache for fact checking results
Implements memory → Redis → Database cache hierarchy
"""
import json
import sqlite3
import threading
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
import os

from .models import FactCheckResult, FactCheckStatus, FactCheckVerdict, CacheResult, EvidenceRecord


@dataclass
class CacheEntry:
    """Internal cache entry with metadata"""
    result: FactCheckResult
    cached_at: datetime
    expires_at: datetime


class MemoryCache:
    """In-memory LRU cache for hot results"""
    
    def __init__(self, max_size: int = 1000):
        self._cache: Dict[str, CacheEntry] = {}
        self._max_size = max_size
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
    
    def get(self, key: str) -> Optional[FactCheckResult]:
        """Get result from memory cache"""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None
            
            # Check expiration
            if datetime.now() > entry.expires_at:
                del self._cache[key]
                self._misses += 1
                return None
            
            self._hits += 1
            return entry.result
    
    def set(self, key: str, result: FactCheckResult, ttl_seconds: int):
        """Store result in memory cache"""
        with self._lock:
            # Evict oldest if at capacity (simple FIFO)
            if len(self._cache) >= self._max_size:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
            
            now = datetime.now()
            self._cache[key] = CacheEntry(
                result=result,
                cached_at=now,
                expires_at=now + timedelta(seconds=ttl_seconds)
            )
    
    def invalidate(self, key: str):
        """Remove entry from cache"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with self._lock:
            total = self._hits + self._misses
            hit_rate = self._hits / total if total > 0 else 0.0
            return {
                'size': len(self._cache),
                'max_size': self._max_size,
                'hits': self._hits,
                'misses': self._misses,
                'hit_rate': round(hit_rate, 4),
            }


class SQLiteCache:
    """Persistent SQLite cache for durability"""
    
    def __init__(self, db_path: str = ".fact_check_cache.db"):
        self._db_path = db_path
        self._lock = threading.RLock()
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema"""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS fact_check_cache (
                    cache_key TEXT PRIMARY KEY,
                    claim_hash TEXT NOT NULL,
                    fact_mode TEXT NOT NULL,
                    allowlist_version TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    cached_at TIMESTAMP NOT NULL,
                    expires_at TIMESTAMP NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_claim_hash 
                ON fact_check_cache(claim_hash)
            """)
            conn.commit()
    
    def _result_to_dict(self, result: FactCheckResult) -> Dict:
        """Convert result to JSON-serializable dict"""
        return {
            'claim_text': result.claim_text,
            'normalized_claim_text': result.normalized_claim_text,
            'claim_hash': result.claim_hash,
            'fact_mode': result.fact_mode,
            'allowlist_version': result.allowlist_version,
            'status': result.status.value,
            'verdict': result.verdict.value,
            'factuality_score': result.factuality_score,
            'confidence': result.confidence,
            'confidence_explanation': result.confidence_explanation,
            'evidence': [
                {
                    'source_url': e.source_url,
                    'source_id': e.source_id,
                    'source_version': e.source_version,
                    'source_title': e.source_title,
                    'snippet': e.snippet,
                    'content_hash': e.content_hash,
                    'retrieved_at': e.retrieved_at.isoformat(),
                    'relevance_score': e.relevance_score,
                    'support_score': e.support_score,
                    'contradiction_score': e.contradiction_score,
                    'selected_rank': e.selected_rank,
                }
                for e in result.evidence
            ],
            'created_at': result.created_at.isoformat(),
            'invalidated_at': result.invalidated_at.isoformat() if result.invalidated_at else None,
            'invalidation_reason': result.invalidation_reason,
            'source_count_considered': result.source_count_considered,
            'source_count_retained': result.source_count_retained,
            'algorithm_version': result.algorithm_version,
            'processing_duration_ms': result.processing_duration_ms,
            'contains_pii': result.contains_pii,
        }
    
    def _dict_to_result(self, data: Dict) -> FactCheckResult:
        """Convert dict back to FactCheckResult"""
        evidence = [
            EvidenceRecord(
                source_url=e['source_url'],
                source_id=e['source_id'],
                source_version=e.get('source_version'),
                source_title=e['source_title'],
                snippet=e['snippet'],
                content_hash=e['content_hash'],
                retrieved_at=datetime.fromisoformat(e['retrieved_at']),
                relevance_score=e['relevance_score'],
                support_score=e['support_score'],
                contradiction_score=e['contradiction_score'],
                selected_rank=e['selected_rank'],
            )
            for e in data.get('evidence', [])
        ]
        
        return FactCheckResult(
            claim_text=data['claim_text'],
            normalized_claim_text=data['normalized_claim_text'],
            claim_hash=data['claim_hash'],
            fact_mode=data['fact_mode'],
            allowlist_version=data['allowlist_version'],
            status=FactCheckStatus(data['status']),
            verdict=FactCheckVerdict(data['verdict']),
            factuality_score=data['factuality_score'],
            confidence=data['confidence'],
            confidence_explanation=data.get('confidence_explanation'),
            evidence=evidence,
            created_at=datetime.fromisoformat(data['created_at']),
            invalidated_at=datetime.fromisoformat(data['invalidated_at']) if data.get('invalidated_at') else None,
            invalidation_reason=data.get('invalidation_reason'),
            source_count_considered=data.get('source_count_considered', 0),
            source_count_retained=data.get('source_count_retained', 0),
            algorithm_version=data.get('algorithm_version', 'fc-1.0'),
            processing_duration_ms=data.get('processing_duration_ms', 0),
            contains_pii=data.get('contains_pii', False),
        )
    
    def get(self, key: str) -> Optional[FactCheckResult]:
        """Get result from SQLite cache"""
        with self._lock:
            try:
                with sqlite3.connect(self._db_path) as conn:
                    cursor = conn.execute(
                        "SELECT result_json, expires_at FROM fact_check_cache WHERE cache_key = ?",
                        (key,)
                    )
                    row = cursor.fetchone()
                    
                    if row is None:
                        return None
                    
                    result_json, expires_at_str = row
                    expires_at = datetime.fromisoformat(expires_at_str)
                    
                    # Check expiration
                    if datetime.now() > expires_at:
                        conn.execute("DELETE FROM fact_check_cache WHERE cache_key = ?", (key,))
                        conn.commit()
                        return None
                    
                    data = json.loads(result_json)
                    return self._dict_to_result(data)
                    
            except Exception as e:
                # Log error but don't crash - treat as cache miss
                print(f"SQLite cache error: {e}")
                return None
    
    def set(self, key: str, result: FactCheckResult, ttl_seconds: int):
        """Store result in SQLite cache"""
        with self._lock:
            try:
                now = datetime.now()
                expires_at = now + timedelta(seconds=ttl_seconds)
                
                data = self._result_to_dict(result)
                result_json = json.dumps(data)
                
                with sqlite3.connect(self._db_path) as conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO fact_check_cache 
                        (cache_key, claim_hash, fact_mode, allowlist_version, result_json, cached_at, expires_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            key,
                            result.claim_hash,
                            result.fact_mode,
                            result.allowlist_version,
                            result_json,
                            now.isoformat(),
                            expires_at.isoformat(),
                        )
                    )
                    conn.commit()
                    
            except Exception as e:
                # Log error but don't crash
                print(f"SQLite cache write error: {e}")
    
    def invalidate(self, key: str):
        """Remove entry from cache"""
        with self._lock:
            try:
                with sqlite3.connect(self._db_path) as conn:
                    conn.execute("DELETE FROM fact_check_cache WHERE cache_key = ?", (key,))
                    conn.commit()
            except Exception as e:
                print(f"SQLite cache invalidate error: {e}")
    
    def invalidate_by_claim_hash(self, claim_hash: str):
        """Invalidate all entries for a claim hash"""
        with self._lock:
            try:
                with sqlite3.connect(self._db_path) as conn:
                    conn.execute(
                        "DELETE FROM fact_check_cache WHERE claim_hash = ?",
                        (claim_hash,)
                    )
                    conn.commit()
            except Exception as e:
                print(f"SQLite cache invalidate error: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with self._lock:
            try:
                with sqlite3.connect(self._db_path) as conn:
                    cursor = conn.execute("SELECT COUNT(*) FROM fact_check_cache")
                    count = cursor.fetchone()[0]
                    return {'size': count, 'db_path': self._db_path}
            except Exception as e:
                return {'size': 0, 'error': str(e)}


class MultiLayerCache:
    """
    Multi-layer cache: Memory → SQLite
    (Redis can be added as middle layer if needed)
    """
    
    def __init__(self, ttl_seconds: int = 86400 * 30, 
                 memory_max_size: int = 1000,
                 db_path: str = ".fact_check_cache.db"):
        self._memory = MemoryCache(max_size=memory_max_size)
        self._sqlite = SQLiteCache(db_path=db_path)
        self._ttl_seconds = ttl_seconds
    
    def build_key(self, claim_hash: str, fact_mode: str, allowlist_version: str) -> str:
        """Build cache key from components"""
        return f"{claim_hash}:{fact_mode}:{allowlist_version}"
    
    def get(self, key: str) -> tuple[Optional[FactCheckResult], Optional[CacheResult]]:
        """
        Get result from cache, trying layers in order.
        
        Returns:
            Tuple of (result, cache_layer) or (None, None) if not found
        """
        # Try memory first
        result = self._memory.get(key)
        if result is not None:
            return result, CacheResult.HIT_MEMORY
        
        # Try SQLite
        result = self._sqlite.get(key)
        if result is not None:
            # Promote to memory cache
            self._memory.set(key, result, self._ttl_seconds)
            return result, CacheResult.HIT_DB
        
        return None, None
    
    def set(self, key: str, result: FactCheckResult):
        """Store result in all cache layers"""
        self._memory.set(key, result, self._ttl_seconds)
        self._sqlite.set(key, result, self._ttl_seconds)
    
    def invalidate(self, key: str):
        """Invalidate entry across all layers"""
        self._memory.invalidate(key)
        self._sqlite.invalidate(key)
    
    def invalidate_by_claim(self, claim_hash: str, fact_mode: str, allowlist_version: str):
        """Invalidate specific claim entry"""
        key = self.build_key(claim_hash, fact_mode, allowlist_version)
        self.invalidate(key)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics from all layers"""
        return {
            'memory': self._memory.get_stats(),
            'sqlite': self._sqlite.get_stats(),
            'ttl_seconds': self._ttl_seconds,
        }
