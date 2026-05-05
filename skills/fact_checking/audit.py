"""
Audit logging for fact checking operations
Implements immutable, queryable audit logs
"""
import json
import sqlite3
import threading
import uuid
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, asdict

from .models import FactCheckResult, RequestContext
from .pii import PIIDetector


@dataclass
class AuditLogEntry:
    """Single audit log entry"""
    entry_id: str
    timestamp: datetime
    claim_hash: str
    claim_text: str  # May be hashed if contains PII
    normalized_claim_text: str  # May be hashed if contains PII
    fact_mode: str
    allowlist_version: str
    cache_result: Optional[str]
    evidence_candidates_count: int
    evidence_retained_count: int
    verdict: str
    factuality_score: float
    confidence: float
    algorithm_version: str
    processing_duration_ms: int
    request_id: str
    post_id: Optional[str]
    point_id: Optional[str]
    counterpoint_id: Optional[str]
    submission_id: Optional[str]
    contains_pii: bool
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'entry_id': self.entry_id,
            'timestamp': self.timestamp.isoformat(),
            'claim_hash': self.claim_hash,
            'claim_text': self.claim_text,
            'normalized_claim_text': self.normalized_claim_text,
            'fact_mode': self.fact_mode,
            'allowlist_version': self.allowlist_version,
            'cache_result': self.cache_result,
            'evidence_candidates_count': self.evidence_candidates_count,
            'evidence_retained_count': self.evidence_retained_count,
            'verdict': self.verdict,
            'factuality_score': self.factuality_score,
            'confidence': self.confidence,
            'algorithm_version': self.algorithm_version,
            'processing_duration_ms': self.processing_duration_ms,
            'request_id': self.request_id,
            'post_id': self.post_id,
            'point_id': self.point_id,
            'counterpoint_id': self.counterpoint_id,
            'submission_id': self.submission_id,
            'contains_pii': self.contains_pii,
            'error_message': self.error_message,
        }


class AuditLogger:
    """
    Immutable audit logger for fact checking operations.
    
    Stores logs in SQLite for queryability.
    All entries are append-only.
    """
    
    def __init__(self, db_path: str = ".fact_check_audit.db"):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()
    
    def _connect(self):
        """Open a SQLite connection with a sensible timeout."""
        return sqlite3.connect(self._db_path, timeout=10.0)

    def _init_db(self):
        """Initialize database schema"""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    entry_id TEXT PRIMARY KEY,
                    timestamp TIMESTAMP NOT NULL,
                    claim_hash TEXT NOT NULL,
                    claim_text TEXT NOT NULL,
                    normalized_claim_text TEXT NOT NULL,
                    fact_mode TEXT NOT NULL,
                    allowlist_version TEXT NOT NULL,
                    cache_result TEXT,
                    evidence_candidates_count INTEGER,
                    evidence_retained_count INTEGER,
                    verdict TEXT NOT NULL,
                    factuality_score REAL NOT NULL,
                    confidence REAL NOT NULL,
                    algorithm_version TEXT NOT NULL,
                    processing_duration_ms INTEGER,
                    request_id TEXT NOT NULL,
                    post_id TEXT,
                    point_id TEXT,
                    counterpoint_id TEXT,
                    submission_id TEXT,
                    contains_pii BOOLEAN NOT NULL,
                    error_message TEXT,
                    full_entry_json TEXT NOT NULL
                )
            """)
            
            # Indexes for queryability
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_claim_hash 
                ON audit_log(claim_hash)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_request_id 
                ON audit_log(request_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_post_id 
                ON audit_log(post_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp 
                ON audit_log(timestamp)
            """)
            
            conn.commit()
    
    def log_check(self, 
                  result: FactCheckResult,
                  request_context: RequestContext,
                  evidence_candidates_count: int = 0,
                  error_message: Optional[str] = None) -> str:
        """
        Log a fact check operation.
        
        Args:
            result: The fact check result
            request_context: Request context for tracing
            evidence_candidates_count: Number of evidence candidates considered
            error_message: Error message if operation failed
            
        Returns:
            entry_id of the created log entry
        """
        with self._lock:
            entry_id = f"audit_{uuid.uuid4().hex}"
            
            # Hash claim text if it contains PII
            claim_text_for_log = result.claim_text
            normalized_for_log = result.normalized_claim_text
            
            if result.contains_pii:
                claim_text_for_log = PIIDetector.hash_for_audit_log(result.claim_text)
                normalized_for_log = PIIDetector.hash_for_audit_log(result.normalized_claim_text)
            
            entry = AuditLogEntry(
                entry_id=entry_id,
                timestamp=datetime.now(),
                claim_hash=result.claim_hash,
                claim_text=claim_text_for_log,
                normalized_claim_text=normalized_for_log,
                fact_mode=result.fact_mode,
                allowlist_version=result.allowlist_version,
                cache_result=result.cache_result.value if result.cache_result else None,
                evidence_candidates_count=evidence_candidates_count,
                evidence_retained_count=result.source_count_retained,
                verdict=result.verdict.value,
                factuality_score=result.factuality_score,
                confidence=result.confidence,
                algorithm_version=result.algorithm_version,
                processing_duration_ms=result.processing_duration_ms,
                request_id=request_context.request_id,
                post_id=request_context.post_id,
                point_id=request_context.point_id,
                counterpoint_id=request_context.counterpoint_id,
                submission_id=request_context.submission_id,
                contains_pii=result.contains_pii,
                error_message=error_message,
            )
            
            # Store in database
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO audit_log (
                        entry_id, timestamp, claim_hash, claim_text, normalized_claim_text,
                        fact_mode, allowlist_version, cache_result, evidence_candidates_count,
                        evidence_retained_count, verdict, factuality_score, confidence,
                        algorithm_version, processing_duration_ms, request_id, post_id,
                        point_id, counterpoint_id, submission_id, contains_pii,
                        error_message, full_entry_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.entry_id,
                        entry.timestamp.isoformat(),
                        entry.claim_hash,
                        entry.claim_text,
                        entry.normalized_claim_text,
                        entry.fact_mode,
                        entry.allowlist_version,
                        entry.cache_result,
                        entry.evidence_candidates_count,
                        entry.evidence_retained_count,
                        entry.verdict,
                        entry.factuality_score,
                        entry.confidence,
                        entry.algorithm_version,
                        entry.processing_duration_ms,
                        entry.request_id,
                        entry.post_id,
                        entry.point_id,
                        entry.counterpoint_id,
                        entry.submission_id,
                        entry.contains_pii,
                        entry.error_message,
                        json.dumps(entry.to_dict()),
                    )
                )
                conn.commit()
            
            return entry_id
    
    def query_by_claim_hash(self, claim_hash: str, 
                           limit: int = 100) -> List[Dict[str, Any]]:
        """Query audit log by claim hash"""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM audit_log 
                WHERE claim_hash = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (claim_hash, limit)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    def query_by_request_id(self, request_id: str) -> Optional[Dict[str, Any]]:
        """Query audit log by request ID"""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM audit_log WHERE request_id = ?",
                (request_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def query_by_post_id(self, post_id: str, 
                        limit: int = 100) -> List[Dict[str, Any]]:
        """Query audit log by post ID"""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM audit_log 
                WHERE post_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (post_id, limit)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get audit log statistics"""
        with self._connect() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM audit_log")
            total_entries = cursor.fetchone()[0]
            
            cursor = conn.execute(
                "SELECT COUNT(DISTINCT claim_hash) FROM audit_log"
            )
            unique_claims = cursor.fetchone()[0]
            
            cursor = conn.execute(
                """
                SELECT fact_mode, COUNT(*) as count 
                FROM audit_log 
                GROUP BY fact_mode
                """
            )
            mode_counts = {row[0]: row[1] for row in cursor.fetchall()}
            
            return {
                'total_entries': total_entries,
                'unique_claims': unique_claims,
                'mode_counts': mode_counts,
                'db_path': self._db_path,
            }
