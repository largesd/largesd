"""
Asynchronous Job Queue for LSD §9 Snapshot Generation
Provides background processing for debate snapshots with progress tracking.
"""

import json
import uuid
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, Optional, List, Any, Callable
from contextlib import contextmanager


class JobStatus(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Job:
    """Represents an async job."""
    job_id: str
    job_type: str
    parameters: Dict[str, Any]
    runtime_profile_id: Optional[str]
    status: JobStatus
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    progress: int = 0  # 0-100
    result: Optional[Dict] = None
    error: Optional[str] = None


class JobQueue:
    """
    SQLite-backed job queue for async snapshot generation.
    """
    
    def __init__(self, db):
        self.db = db
        self._init_tables()
    
    def _init_tables(self):
        """Initialize job queue tables."""
        conn = self.db._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                job_type TEXT NOT NULL,
                parameters TEXT NOT NULL,
                runtime_profile_id TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                progress INTEGER DEFAULT 0,
                result TEXT,
                error TEXT
            )
        """)
        db_url = getattr(self.db, "_db_url", "") or ""
        if db_url.startswith("postgresql://"):
            cursor.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS runtime_profile_id TEXT")
        else:
            ensure_column = getattr(self.db, "_ensure_column", None)
            if callable(ensure_column):
                ensure_column(cursor, "jobs", "runtime_profile_id", "TEXT")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_status_runtime_created "
            "ON jobs(status, runtime_profile_id, created_at DESC)"
        )
        conn.commit()
        conn.close()
    
    def create_job(
        self,
        job_type: str,
        parameters: Dict[str, Any],
        runtime_profile_id: Optional[str] = None,
    ) -> str:
        """Create a new job and return its ID."""
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        job = Job(
            job_id=job_id,
            job_type=job_type,
            parameters=parameters,
            runtime_profile_id=runtime_profile_id,
            status=JobStatus.QUEUED,
            created_at=datetime.utcnow().isoformat()
        )
        
        conn = self.db._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO jobs (
                   job_id, job_type, parameters, runtime_profile_id, status, created_at, progress
               ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (job.job_id, job.job_type, json.dumps(job.parameters),
             job.runtime_profile_id, job.status.value, job.created_at, job.progress)
        )
        conn.commit()
        conn.close()
        
        return job_id
    
    def get_job(self, job_id: str) -> Optional[Job]:
        """Get job by ID."""
        conn = self.db._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        return self._row_to_job(row)
    
    def update_progress(self, job_id: str, progress: int):
        """Update job progress (0-100)."""
        conn = self.db._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE jobs SET progress = ? WHERE job_id = ?",
            (max(0, min(100, progress)), job_id)
        )
        conn.commit()
        conn.close()
    
    def start_job(self, job_id: str, runtime_profile_id: Optional[str] = None) -> bool:
        """Atomically claim a queued job for execution."""
        conn = self.db._get_connection()
        cursor = conn.cursor()
        query = (
            "UPDATE jobs SET status = ?, started_at = ? "
            "WHERE job_id = ? AND status = ?"
        )
        params: List[Any] = [
            JobStatus.RUNNING.value,
            datetime.utcnow().isoformat(),
            job_id,
            JobStatus.QUEUED.value,
        ]
        if runtime_profile_id is not None:
            query += " AND runtime_profile_id = ?"
            params.append(runtime_profile_id)
        cursor.execute(query, tuple(params))
        claimed = cursor.rowcount == 1
        conn.commit()
        conn.close()
        return claimed
    
    def complete_job(self, job_id: str, result: Dict[str, Any]):
        """Mark job as completed with result."""
        conn = self.db._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE jobs SET status = ?, completed_at = ?, result = ?, progress = 100
               WHERE job_id = ?""",
            (JobStatus.COMPLETED.value, datetime.utcnow().isoformat(),
             json.dumps(result), job_id)
        )
        conn.commit()
        conn.close()
    
    def fail_job(self, job_id: str, error: str):
        """Mark job as failed with error message."""
        conn = self.db._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """UPDATE jobs SET status = ?, completed_at = ?, error = ?
               WHERE job_id = ?""",
            (JobStatus.FAILED.value, datetime.utcnow().isoformat(), error, job_id)
        )
        conn.commit()
        conn.close()
    
    def list_jobs(
        self,
        limit: int = 100,
        status: Optional[JobStatus] = None,
        runtime_profile_id: Optional[str] = None,
    ) -> List[Job]:
        """List recent jobs, optionally filtered by status and runtime profile."""
        conn = self.db._get_connection()
        cursor = conn.cursor()
        query = "SELECT * FROM jobs"
        clauses: List[str] = []
        params: List[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value if isinstance(status, JobStatus) else status)
        if runtime_profile_id is not None:
            clauses.append("runtime_profile_id = ?")
            params.append(runtime_profile_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        conn.close()
        
        return [self._row_to_job(row) for row in rows]
    
    def _row_to_job(self, row) -> Job:
        """Convert DB row to Job object."""
        parameters = json.loads(row['parameters'])
        runtime_profile_id = None
        try:
            runtime_profile_id = row['runtime_profile_id']
        except (KeyError, IndexError, TypeError):
            runtime_profile_id = None
        if runtime_profile_id is None:
            runtime_profile_id = parameters.get('runtime_profile_id')

        return Job(
            job_id=row['job_id'],
            job_type=row['job_type'],
            parameters=parameters,
            runtime_profile_id=runtime_profile_id,
            status=JobStatus(row['status']),
            created_at=row['created_at'],
            started_at=row['started_at'],
            completed_at=row['completed_at'],
            progress=row['progress'],
            result=json.loads(row['result']) if row['result'] else None,
            error=row['error']
        )
    
    def to_public_dict(self, job: Job) -> Dict[str, Any]:
        """Convert job to public API response."""
        return {
            "job_id": job.job_id,
            "job_type": job.job_type,
            "status": job.status.value,
            "progress": job.progress,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "result": job.result,
            "error": job.error
        }


class JobWorker:
    """
    Background worker for processing jobs.
    """
    
    def __init__(self, job_queue: JobQueue, runtime_profile_id: Optional[str] = None):
        self.job_queue = job_queue
        self.runtime_profile_id = runtime_profile_id
        self.handlers: Dict[str, Callable] = {}
        self._shutdown = threading.Event()
        self._thread: Optional[threading.Thread] = None
    
    def register_handler(self, job_type: str, handler: Callable):
        """Register a handler function for a job type."""
        self.handlers[job_type] = handler
    
    def start(self):
        """Start the worker thread."""
        if self._thread is None or not self._thread.is_alive():
            self._shutdown.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
    
    def stop(self):
        """Stop the worker thread."""
        self._shutdown.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
    
    def _run(self):
        """Main worker loop."""
        while not self._shutdown.is_set():
            jobs = self.job_queue.list_jobs(
                limit=50,
                status=JobStatus.QUEUED,
                runtime_profile_id=self.runtime_profile_id,
            )
            
            for job in jobs:
                if self._shutdown.is_set():
                    break
                
                handler = self.handlers.get(job.job_type)
                if handler:
                    self._process_job(job, handler)
            
            time.sleep(1)
    
    def _process_job(self, job: Job, handler: Callable):
        """Process a single job."""
        if not self.job_queue.start_job(
            job.job_id,
            runtime_profile_id=self.runtime_profile_id,
        ):
            return
        
        try:
            result = handler(job.job_id, job.parameters, self.job_queue)
            self.job_queue.complete_job(job.job_id, result)
        except Exception as e:
            self.job_queue.fail_job(job.job_id, str(e))
