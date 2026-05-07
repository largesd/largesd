"""Unit tests for job queue row-level locking and stuck-job reclaim."""

import os
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta

from backend.database_v3 import Database
from backend.job_queue import JobQueue, JobStatus, JobWorker


class TestJobQueueAtomicClaim:
    """Tests that job claim is atomic and prevents duplicate processing."""

    def test_claim_next_job_is_atomic(self):
        """Only one worker should successfully claim a given job."""
        tmp = tempfile.mkdtemp()
        db = Database(os.path.join(tmp, "jobs.db"))
        queue = JobQueue(db)

        job_id = queue.create_job("snapshot", {"debate_id": "d1"}, runtime_profile_id="runtime-a")

        job_a = queue.claim_next_job(worker_id="worker-a", runtime_profile_id="runtime-a")
        job_b = queue.claim_next_job(worker_id="worker-b", runtime_profile_id="runtime-a")

        assert job_a is not None
        assert job_a.job_id == job_id
        assert job_a.worker_id == "worker-a"
        assert job_a.status == JobStatus.RUNNING

        assert job_b is None

        remaining = queue.list_jobs(status=JobStatus.QUEUED, runtime_profile_id="runtime-a")
        assert len(remaining) == 0

    def test_concurrent_claims_no_duplicates(self):
        """Simulate multi-worker load and verify no job is claimed twice."""
        tmp = tempfile.mkdtemp()
        db = Database(os.path.join(tmp, "jobs.db"))
        queue = JobQueue(db)

        num_jobs = 20
        for i in range(num_jobs):
            queue.create_job("snapshot", {"debate_id": f"d{i}"}, runtime_profile_id="runtime-x")

        claimed_jobs = []
        errors = []

        def worker(worker_id: str):
            for _ in range(num_jobs):
                try:
                    job = queue.claim_next_job(worker_id=worker_id, runtime_profile_id="runtime-x")
                    if job:
                        claimed_jobs.append((worker_id, job.job_id))
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=worker, args=(f"worker-{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors

        # Every job should be claimed exactly once
        claimed_ids = [jid for _wid, jid in claimed_jobs]
        assert len(claimed_ids) == num_jobs
        assert len(set(claimed_ids)) == num_jobs

    def test_claim_next_job_filters_by_runtime_profile(self):
        """Workers should only claim jobs matching their runtime profile."""
        tmp = tempfile.mkdtemp()
        db = Database(os.path.join(tmp, "jobs.db"))
        queue = JobQueue(db)

        job_a = queue.create_job("snapshot", {"debate_id": "d1"}, runtime_profile_id="runtime-a")
        job_b = queue.create_job("snapshot", {"debate_id": "d2"}, runtime_profile_id="runtime-b")

        claimed_a = queue.claim_next_job(worker_id="w1", runtime_profile_id="runtime-a")
        claimed_b = queue.claim_next_job(worker_id="w2", runtime_profile_id="runtime-b")

        assert claimed_a is not None
        assert claimed_a.job_id == job_a

        assert claimed_b is not None
        assert claimed_b.job_id == job_b


class TestJobQueueStuckReclaim:
    """Tests that stuck jobs are auto-reclaimed after timeout."""

    def test_reclaim_stuck_jobs_resets_old_running_jobs(self):
        """Jobs stuck in running for longer than the timeout should return to queued."""
        tmp = tempfile.mkdtemp()
        db = Database(os.path.join(tmp, "jobs.db"))
        queue = JobQueue(db)

        job_id = queue.create_job("snapshot", {"debate_id": "d1"})

        # Manually set job to running with a very old started_at
        old_started = (datetime.now(UTC) - timedelta(seconds=1000)).replace(tzinfo=None).isoformat()
        conn = db._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE jobs SET status = ?, started_at = ?, worker_id = ? WHERE job_id = ?",
            (JobStatus.RUNNING.value, old_started, "crashed-worker", job_id),
        )
        conn.commit()
        conn.close()

        reclaimed = queue.reclaim_stuck_jobs(timeout_seconds=300)
        assert reclaimed == 1

        job = queue.get_job(job_id)
        assert job is not None
        assert job.status == JobStatus.QUEUED
        assert job.worker_id is None
        assert job.started_at is None

    def test_reclaim_stuck_jobs_leaves_fresh_running_jobs(self):
        """Recently started jobs should not be reclaimed."""
        tmp = tempfile.mkdtemp()
        db = Database(os.path.join(tmp, "jobs.db"))
        queue = JobQueue(db)

        job_id = queue.create_job("snapshot", {"debate_id": "d1"})
        queue.start_job(job_id, worker_id="healthy-worker")

        reclaimed = queue.reclaim_stuck_jobs(timeout_seconds=300)
        assert reclaimed == 0

        job = queue.get_job(job_id)
        assert job is not None
        assert job.status == JobStatus.RUNNING
        assert job.worker_id == "healthy-worker"

    def test_reclaim_stuck_jobs_resets_null_started_at(self):
        """Running jobs with NULL started_at should be reclaimed."""
        tmp = tempfile.mkdtemp()
        db = Database(os.path.join(tmp, "jobs.db"))
        queue = JobQueue(db)

        job_id = queue.create_job("snapshot", {"debate_id": "d1"})

        conn = db._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE jobs SET status = ?, started_at = NULL, worker_id = ? WHERE job_id = ?",
            (JobStatus.RUNNING.value, "orphan-worker", job_id),
        )
        conn.commit()
        conn.close()

        reclaimed = queue.reclaim_stuck_jobs(timeout_seconds=300)
        assert reclaimed == 1

        job = queue.get_job(job_id)
        assert job is not None
        assert job.status == JobStatus.QUEUED
        assert job.worker_id is None


class TestJobWorkerIntegration:
    """Tests that JobWorker uses atomic claim correctly."""

    def test_worker_claims_and_processes_job(self):
        """JobWorker should claim and process a single job end-to-end."""
        tmp = tempfile.mkdtemp()
        db = Database(os.path.join(tmp, "jobs.db"))
        queue = JobQueue(db)
        worker = JobWorker(queue, runtime_profile_id="runtime-x")

        processed = []

        def handler(job_id, parameters, q):
            processed.append(job_id)
            return {"ok": True}

        worker.register_handler("snapshot", handler)

        job_id = queue.create_job("snapshot", {"debate_id": "d1"}, runtime_profile_id="runtime-x")

        worker.start()
        # Wait for the worker to process the job
        for _ in range(50):
            if processed:
                break
            time.sleep(0.05)
        worker.stop()

        assert processed == [job_id]

        job = queue.get_job(job_id)
        assert job is not None
        assert job.status == JobStatus.COMPLETED
        assert job.result == {"ok": True}

    def test_worker_reclaims_stuck_jobs_before_claiming(self):
        """Worker loop should reclaim stuck jobs before attempting new claims."""
        tmp = tempfile.mkdtemp()
        db = Database(os.path.join(tmp, "jobs.db"))
        queue = JobQueue(db)
        worker = JobWorker(queue, runtime_profile_id="runtime-x")

        processed = []

        def handler(job_id, parameters, q):
            processed.append(job_id)
            return {"ok": True}

        worker.register_handler("snapshot", handler)

        # Seed a stuck job
        job_id = queue.create_job("snapshot", {"debate_id": "d1"}, runtime_profile_id="runtime-x")
        old_started = (datetime.now(UTC) - timedelta(seconds=1000)).replace(tzinfo=None).isoformat()
        conn = db._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE jobs SET status = ?, started_at = ?, worker_id = ? WHERE job_id = ?",
            (JobStatus.RUNNING.value, old_started, "crashed-worker", job_id),
        )
        conn.commit()
        conn.close()

        worker.start()
        for _ in range(50):
            if processed:
                break
            time.sleep(0.05)
        worker.stop()

        assert processed == [job_id]

        job = queue.get_job(job_id)
        assert job is not None
        assert job.status == JobStatus.COMPLETED
