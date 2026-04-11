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
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                job_type TEXT NOT NULL,
                parameters TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                progress INTEGER DEFAULT 0,
                result TEXT,
                error TEXT
            )
        """)
        self.db.commit()
    
    def create_job(self, job_type: str, parameters: Dict[str, Any]) -> str:
        """Create a new job and return its ID."""
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        job = Job(
            job_id=job_id,
            job_type=job_type,
            parameters=parameters,
            status=JobStatus.QUEUED,
            created_at=datetime.utcnow().isoformat()
        )
        
        self.db.execute(
            """INSERT INTO jobs (job_id, job_type, parameters, status, created_at, progress)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (job.job_id, job.job_type, json.dumps(job.parameters),
             job.status.value, job.created_at, job.progress)
        )
        self.db.commit()
        
        return job_id
    
    def get_job(self, job_id: str) -> Optional[Job]:
        """Get job by ID."""
        row = self.db.execute(
            "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        
        if not row:
            return None
        
        return self._row_to_job(row)
    
    def update_progress(self, job_id: str, progress: int):
        """Update job progress (0-100)."""
        self.db.execute(
            "UPDATE jobs SET progress = ? WHERE job_id = ?",
            (max(0, min(100, progress)), job_id)
        )
        self.db.commit()
    
    def start_job(self, job_id: str):
        """Mark job as running."""
        self.db.execute(
            "UPDATE jobs SET status = ?, started_at = ? WHERE job_id = ?",
            (JobStatus.RUNNING.value, datetime.utcnow().isoformat(), job_id)
        )
        self.db.commit()
    
    def complete_job(self, job_id: str, result: Dict[str, Any]):
        """Mark job as completed with result."""
        self.db.execute(
            """UPDATE jobs SET status = ?, completed_at = ?, result = ?, progress = 100
               WHERE job_id = ?""",
            (JobStatus.COMPLETED.value, datetime.utcnow().isoformat(),
             json.dumps(result), job_id)
        )
        self.db.commit()
    
    def fail_job(self, job_id: str, error: str):
        """Mark job as failed with error message."""
        self.db.execute(
            """UPDATE jobs SET status = ?, completed_at = ?, error = ?
               WHERE job_id = ?""",
            (JobStatus.FAILED.value, datetime.utcnow().isoformat(), error, job_id)
        )
        self.db.commit()
    
    def list_jobs(self, limit: int = 100) -> List[Job]:
        """List recent jobs."""
        rows = self.db.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        
        return [self._row_to_job(row) for row in rows]
    
    def _row_to_job(self, row) -> Job:
        """Convert DB row to Job object."""
        return Job(
            job_id=row['job_id'],
            job_type=row['job_type'],
            parameters=json.loads(row['parameters']),
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
    
    def __init__(self, job_queue: JobQueue):
        self.job_queue = job_queue
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
            # Find queued jobs
            jobs = [
                job for job in self.job_queue.list_jobs(limit=50)
                if job.status == JobStatus.QUEUED
            ]
            
            for job in jobs:
                if self._shutdown.is_set():
                    break
                
                handler = self.handlers.get(job.job_type)
                if handler:
                    self._process_job(job, handler)
            
            time.sleep(1)
    
    def _process_job(self, job: Job, handler: Callable):
        """Process a single job."""
        self.job_queue.start_job(job.job_id)
        
        try:
            result = handler(job.job_id, job.parameters, self.job_queue)
            self.job_queue.complete_job(job.job_id, result)
        except Exception as e:
            self.job_queue.fail_job(job.job_id, str(e))
