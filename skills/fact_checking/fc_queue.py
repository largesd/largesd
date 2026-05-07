"""
Async queue and workers for fact checking.

Each FactCheckingSkill instance owns its own queue. That keeps connectors,
cache interactions, and worker shutdown behavior isolated across runtimes.
"""

import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from .models import FactCheckJob, FactCheckResult


@dataclass
class QueueStats:
    """Statistics for the job queue"""

    queued: int
    processing: int
    completed: int
    failed: int
    total_processed: int


class FactCheckQueue:
    """
    Async queue for fact checking jobs.

    Allows debate scoring to proceed without waiting for external API calls.
    Jobs are processed by background workers.
    """

    def __init__(self, max_size: int = 1000, label: str | None = None):
        self._max_size = max_size
        self._label = label or f"fcq-{uuid.uuid4().hex[:8]}"
        self._queue: deque[FactCheckJob] = deque()
        self._jobs: dict[str, FactCheckJob] = {}  # All jobs by ID
        self._processing: set[str] = set()  # Currently processing job IDs
        self._completed: deque[FactCheckJob] = deque(maxlen=1000)  # Completed jobs
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._shutdown = False
        self._workers: list[threading.Thread] = []
        self._processor: Callable[[FactCheckJob], FactCheckResult] | None = None

    def set_processor(self, processor: Callable[[FactCheckJob], FactCheckResult]):
        """Set the function that processes jobs"""
        self._processor = processor

    def submit(
        self,
        claim_text: str,
        normalized_claim: str,
        claim_hash: str,
        fact_mode: str,
        allowlist_version: str,
        temporal_context,
        request_context,
        contains_pii: bool = False,
    ) -> FactCheckJob:
        """
        Submit a job to the queue.

        Returns:
            The submitted job (with PENDING status)
        """
        with self._lock:
            if len(self._queue) >= self._max_size:
                raise QueueFullError(f"Queue is full (max {self._max_size})")

            job = FactCheckJob(
                job_id=str(uuid.uuid4()),
                claim_text=claim_text,
                normalized_claim=normalized_claim,
                claim_hash=claim_hash,
                fact_mode=fact_mode,
                allowlist_version=allowlist_version,
                temporal_context=temporal_context,
                request_context=request_context,
                contains_pii=contains_pii,
                status="queued",
            )

            self._queue.append(job)
            self._jobs[job.job_id] = job
            self._condition.notify()

            return job

    def get_job(self, job_id: str) -> FactCheckJob | None:
        """Get job by ID"""
        with self._lock:
            return self._jobs.get(job_id)

    def get_result(self, job_id: str) -> FactCheckResult | None:
        """Get result for a completed job"""
        with self._lock:
            job = self._jobs.get(job_id)
            if job and job.status == "completed":
                return job.result
            return None

    def get_pending_result(
        self, claim_hash: str, fact_mode: str, allowlist_version: str
    ) -> FactCheckJob | None:
        """
        Check if there's already a pending job for this claim.
        Used for deduplication.
        """
        with self._lock:
            for job in self._jobs.values():
                if (
                    job.claim_hash == claim_hash
                    and job.fact_mode == fact_mode
                    and job.allowlist_version == allowlist_version
                    and job.status in ("queued", "processing")
                ):
                    return job
            return None

    def _process_next(self) -> bool:
        """
        Process the next job in the queue.

        Returns:
            True if a job was processed, False if queue is empty
        """
        with self._lock:
            if self._shutdown:
                return False

            if not self._queue:
                return False

            job = self._queue.popleft()
            job.status = "processing"
            job.started_at = datetime.now()
            self._processing.add(job.job_id)

        # Process outside lock
        try:
            if self._processor:
                result = self._processor(job)
                job.result = result
                job.status = "completed"
            else:
                raise RuntimeError("No processor configured")

        except Exception as e:
            job.status = "failed"
            job.error_message = str(e)

        finally:
            with self._lock:
                job.completed_at = datetime.now()
                self._processing.discard(job.job_id)
                self._completed.append(job)

        return True

    def start_workers(self, num_workers: int = 3):
        """Start background worker threads"""
        with self._lock:
            if self._workers:
                return  # Already started

            self._shutdown = False

            for i in range(num_workers):
                worker = threading.Thread(
                    target=self._worker_loop, name=f"FactCheckWorker-{self._label}-{i}", daemon=True
                )
                worker.start()
                self._workers.append(worker)

    def _worker_loop(self):
        """Main loop for worker threads"""
        while True:
            with self._lock:
                if self._shutdown:
                    return

                if not self._queue:
                    self._condition.wait(timeout=1.0)
                    continue

            # Process a job
            processed = self._process_next()

            if not processed:
                time.sleep(0.1)  # Brief pause if nothing to do

    def shutdown(self, wait: bool = True, timeout: float = 30.0):
        """Shutdown the queue and workers"""
        with self._lock:
            self._shutdown = True
            self._condition.notify_all()

        if wait:
            for worker in self._workers:
                worker.join(timeout=timeout / len(self._workers))

        self._workers = []

    def get_stats(self) -> QueueStats:
        """Get queue statistics"""
        with self._lock:
            return QueueStats(
                queued=len(self._queue),
                processing=len(self._processing),
                completed=len(self._completed),
                failed=sum(1 for j in self._completed if j.status == "failed"),
                total_processed=len(self._completed),
            )


class QueueFullError(Exception):
    """Raised when queue is full"""

    pass


def get_global_queue(max_size: int = 1000) -> FactCheckQueue:
    """
    Backward-compatible constructor.

    The global singleton queue was removed; each call now returns a fresh queue.
    """
    return FactCheckQueue(max_size=max_size)


def reset_global_queue():
    """Backward-compatible no-op after removal of the singleton queue."""
    return None
