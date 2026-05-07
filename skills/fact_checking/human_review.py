"""
HumanReviewFlag, HumanReviewRecord, review queue, and aggregate counts
for the LSD Fact-Checking System v1.5.

Responsibilities:
- Immutable, additive human review records
- Review queue listing for human reviewers
- Additive invalidation support (Phase 5)
- Aggregate public counts by review flag with small-count suppression

Per 01_DATA_MODELS.md, 03_PIPELINE.md §human_review, and 04_ROADMAP.md Phase 5/7.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .v15_models import HumanReviewFlag, HumanReviewRecord, ReviewOutcome

# ---------------------------------------------------------------------------
# Small-count suppression threshold
# ---------------------------------------------------------------------------

SMALL_COUNT_THRESHOLD = 5


# ---------------------------------------------------------------------------
# HumanReviewQueue
# ---------------------------------------------------------------------------


@dataclass
class QueuedReviewItem:
    """Item in the human review queue."""

    queue_id: str
    audit_id: str
    premise_id: str
    snapshot_id: str
    premise_text: str
    flags: list[HumanReviewFlag]
    assigned_reviewer: str | None = None
    queue_timestamp: str = ""
    status: str = "pending"  # pending, in_review, completed


class HumanReviewQueue:
    """
    Queue for human review of fact-check results.

    Stores pending review items in SQLite. Items are added when
    FactCheckResults contain human_review_flags.
    """

    def __init__(self, db_path: str = ".fact_check_review_queue.db"):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, timeout=10.0)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS review_queue (
                    queue_id TEXT PRIMARY KEY,
                    audit_id TEXT NOT NULL,
                    premise_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    premise_text TEXT NOT NULL,
                    flags TEXT NOT NULL,
                    assigned_reviewer TEXT,
                    queue_timestamp TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_queue_status
                ON review_queue(status)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_queue_snapshot
                ON review_queue(snapshot_id)
                """
            )
            conn.commit()

    def enqueue(
        self,
        audit_id: str,
        premise_id: str,
        snapshot_id: str,
        premise_text: str,
        flags: list[HumanReviewFlag],
    ) -> str:
        """Add a fact-check result to the review queue."""
        queue_id = f"queue_{audit_id}"
        timestamp = datetime.now(UTC).isoformat()
        flags_str = ",".join(f.value for f in flags)

        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO review_queue
                    (queue_id, audit_id, premise_id, snapshot_id, premise_text,
                     flags, assigned_reviewer, queue_timestamp, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        queue_id,
                        audit_id,
                        premise_id,
                        snapshot_id,
                        premise_text,
                        flags_str,
                        None,
                        timestamp,
                        "pending",
                    ),
                )
                conn.commit()
        return queue_id

    def list_pending(
        self,
        snapshot_id: str | None = None,
        limit: int = 100,
    ) -> list[QueuedReviewItem]:
        """List pending review items, optionally filtered by snapshot."""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            if snapshot_id:
                cursor = conn.execute(
                    """
                    SELECT * FROM review_queue
                    WHERE status = 'pending' AND snapshot_id = ?
                    ORDER BY queue_timestamp ASC
                    LIMIT ?
                    """,
                    (snapshot_id, limit),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT * FROM review_queue
                    WHERE status = 'pending'
                    ORDER BY queue_timestamp ASC
                    LIMIT ?
                    """,
                    (limit,),
                )
            rows = cursor.fetchall()
            return [_row_to_queued_item(dict(row)) for row in rows]

    def assign(self, queue_id: str, reviewer: str) -> bool:
        """Assign a review item to a reviewer."""
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    UPDATE review_queue
                    SET assigned_reviewer = ?, status = 'in_review'
                    WHERE queue_id = ? AND status = 'pending'
                    """,
                    (reviewer, queue_id),
                )
                conn.commit()
                return cursor.rowcount > 0

    def complete(
        self,
        queue_id: str,
        outcome: ReviewOutcome,
        note: str = "",
    ) -> bool:
        """Mark a review item as completed."""
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    UPDATE review_queue
                    SET status = 'completed'
                    WHERE queue_id = ? AND status = 'in_review'
                    """,
                    (queue_id,),
                )
                conn.commit()
                return cursor.rowcount > 0

    def complete_review(
        self,
        queue_id: str,
        outcome: ReviewOutcome,
        reviewer_role: str = "reviewer",
        note: str = "",
    ) -> HumanReviewRecord | None:
        """Complete a review and persist an immutable HumanReviewRecord."""
        with self._lock:
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM review_queue WHERE queue_id = ?",
                    (queue_id,),
                ).fetchone()
                if row is None:
                    return None

                cursor = conn.execute(
                    """
                    UPDATE review_queue
                    SET status = 'completed'
                    WHERE queue_id = ? AND status = 'in_review'
                    """,
                    (queue_id,),
                )
                conn.commit()
                if cursor.rowcount == 0:
                    return None

        record = create_human_review_record(
            target_audit_id=row["audit_id"],
            target_snapshot_id=row["snapshot_id"],
            reviewer_role=reviewer_role,
            review_outcome=outcome,
            review_note=note,
        )
        self._record_store.store(record)
        return record


def _row_to_queued_item(row: dict[str, Any]) -> QueuedReviewItem:
    flags = []
    for f in row.get("flags", "").split(","):
        if f:
            try:
                flags.append(HumanReviewFlag(f))
            except ValueError:
                pass
    return QueuedReviewItem(
        queue_id=row["queue_id"],
        audit_id=row["audit_id"],
        premise_id=row["premise_id"],
        snapshot_id=row["snapshot_id"],
        premise_text=row["premise_text"],
        flags=flags,
        assigned_reviewer=row.get("assigned_reviewer"),
        queue_timestamp=row["queue_timestamp"],
        status=row["status"],
    )


# ---------------------------------------------------------------------------
# Aggregate public counts with small-count suppression
# ---------------------------------------------------------------------------


def compute_aggregate_counts(
    records: list[Any],
    small_count_threshold: int = SMALL_COUNT_THRESHOLD,
) -> dict[str, Any]:
    """
    Compute aggregate public counts by review flag with small-count suppression.

    Returns a dict with:
    - total_records
    - flag_counts (suppressed if < threshold)
    - suppression_notes
    """
    from collections import Counter

    flag_counter: Counter = Counter()
    for record in records:
        flags = getattr(record, "human_review_flags", [])
        for flag in flags:
            flag_name = flag.value if hasattr(flag, "value") else str(flag)
            flag_counter[flag_name] += 1

    flag_counts: dict[str, int] = {}
    suppression_notes: list[str] = []
    for flag_name, count in flag_counter.most_common():
        if count < small_count_threshold:
            flag_counts[flag_name] = 0
            suppression_notes.append(
                f"{flag_name}: suppressed (count={count} < threshold={small_count_threshold})"
            )
        else:
            flag_counts[flag_name] = count

    return {
        "total_records": len(records),
        "flag_counts": flag_counts,
        "suppression_notes": suppression_notes,
        "small_count_threshold": small_count_threshold,
    }


# ---------------------------------------------------------------------------
# Human review record creation
# ---------------------------------------------------------------------------


class ReviewRecordStore:
    """Append-only immutable storage for HumanReviewRecord."""

    def __init__(self, db_path: str = ".fact_check_review_records.db"):
        self._db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS review_records (
                    review_id TEXT PRIMARY KEY,
                    target_audit_id TEXT NOT NULL,
                    target_snapshot_id TEXT NOT NULL,
                    reviewer_role TEXT NOT NULL,
                    review_outcome TEXT NOT NULL,
                    review_note TEXT,
                    review_timestamp TEXT NOT NULL,
                    review_record_hash TEXT NOT NULL
                )
            """)
            conn.commit()

    def store(self, record: HumanReviewRecord) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO review_records
                (review_id, target_audit_id, target_snapshot_id, reviewer_role,
                 review_outcome, review_note, review_timestamp, review_record_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.review_id,
                    record.target_audit_id,
                    record.target_snapshot_id,
                    record.reviewer_role,
                    record.review_outcome.value,
                    record.review_note,
                    record.review_timestamp,
                    record.review_record_hash,
                ),
            )
            conn.commit()

    def get_by_audit(self, audit_id: str) -> list[HumanReviewRecord]:
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM review_records WHERE target_audit_id = ?", (audit_id,)
            ).fetchall()
            return [self._row_to_record(r) for r in rows]

    def _row_to_record(self, row) -> HumanReviewRecord:
        return HumanReviewRecord(
            review_id=row[0],
            target_audit_id=row[1],
            target_snapshot_id=row[2],
            reviewer_role=row[3],
            review_outcome=ReviewOutcome(row[4]),
            review_note=row[5],
            review_timestamp=row[6],
            review_record_hash=row[7],
        )


def create_human_review_record(
    target_audit_id: str,
    target_snapshot_id: str,
    reviewer_role: str,
    review_outcome: ReviewOutcome,
    review_note: str = "",
) -> HumanReviewRecord:
    """Create an immutable HumanReviewRecord."""
    from .v15_cache import canonical_json_hash

    timestamp = datetime.now(UTC).isoformat()
    review_id = f"review_{target_audit_id}_{timestamp}"

    record = HumanReviewRecord(
        review_id=review_id,
        target_audit_id=target_audit_id,
        target_snapshot_id=target_snapshot_id,
        reviewer_role=reviewer_role,
        review_outcome=review_outcome,
        review_note=review_note,
        review_timestamp=timestamp,
        review_record_hash="",
    )
    # Compute hash over all fields
    record.review_record_hash = canonical_json_hash(record)
    return record
