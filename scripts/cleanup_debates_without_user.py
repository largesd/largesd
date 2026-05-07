#!/usr/bin/env python3
"""
Remove debates without a user_id and all related records.
"""

import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "debate_system.db"


def main():
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Identify debates without user_id
    cursor.execute(
        "SELECT debate_id, resolution, created_at FROM debates WHERE user_id IS NULL OR user_id = ''"
    )
    debates_to_delete = cursor.fetchall()

    if not debates_to_delete:
        print("No debates without user_id found. Nothing to do.")
        return

    debate_ids = [row["debate_id"] for row in debates_to_delete]
    placeholders = ",".join("?" * len(debate_ids))

    print(f"Found {len(debate_ids)} debates without user_id:")
    for row in debates_to_delete:
        print(f"  - {row['debate_id']}: {row['resolution'][:60]}... (created {row['created_at']})")

    # Count related records
    counts = {}

    cursor.execute(f"SELECT COUNT(*) FROM posts WHERE debate_id IN ({placeholders})", debate_ids)
    counts["posts"] = cursor.fetchone()[0]

    cursor.execute(
        f"SELECT COUNT(*) FROM spans WHERE post_id IN (SELECT post_id FROM posts WHERE debate_id IN ({placeholders}))",
        debate_ids,
    )
    counts["spans"] = cursor.fetchone()[0]

    cursor.execute(
        f"SELECT COUNT(*) FROM snapshots WHERE debate_id IN ({placeholders})", debate_ids
    )
    counts["snapshots"] = cursor.fetchone()[0]

    cursor.execute(
        f"SELECT COUNT(*) FROM audit_records WHERE snapshot_id IN (SELECT snapshot_id FROM snapshots WHERE debate_id IN ({placeholders}))",
        debate_ids,
    )
    counts["audit_records"] = cursor.fetchone()[0]

    cursor.execute(f"SELECT COUNT(*) FROM topics WHERE debate_id IN ({placeholders})", debate_ids)
    counts["topics"] = cursor.fetchone()[0]

    cursor.execute(f"SELECT COUNT(*) FROM facts WHERE debate_id IN ({placeholders})", debate_ids)
    counts["facts"] = cursor.fetchone()[0]

    cursor.execute(
        f"SELECT COUNT(*) FROM canonical_facts WHERE debate_id IN ({placeholders})", debate_ids
    )
    counts["canonical_facts"] = cursor.fetchone()[0]

    cursor.execute(
        f"SELECT COUNT(*) FROM arguments WHERE debate_id IN ({placeholders})", debate_ids
    )
    counts["arguments"] = cursor.fetchone()[0]

    cursor.execute(
        f"SELECT COUNT(*) FROM canonical_arguments WHERE debate_id IN ({placeholders})", debate_ids
    )
    counts["canonical_arguments"] = cursor.fetchone()[0]

    cursor.execute(
        f"SELECT COUNT(*) FROM debate_frames WHERE debate_id IN ({placeholders})", debate_ids
    )
    counts["debate_frames"] = cursor.fetchone()[0]

    cursor.execute(
        f"SELECT COUNT(*) FROM failed_publishes WHERE debate_id IN ({placeholders})", debate_ids
    )
    counts["failed_publishes"] = cursor.fetchone()[0]

    cursor.execute(
        f"SELECT COUNT(*) FROM frame_petitions WHERE debate_id IN ({placeholders})", debate_ids
    )
    counts["frame_petitions"] = cursor.fetchone()[0]

    print("\nRelated records to be deleted:")
    for table, count in counts.items():
        if count > 0:
            print(f"  {table}: {count}")

    confirm = input(f"\nDelete {len(debate_ids)} debates and all related records? [y/N]: ")
    if confirm.lower() not in ("y", "yes"):
        print("Aborted.")
        return

    # Delete in dependency order
    # 1. audit_records via snapshots
    cursor.execute(
        f"DELETE FROM audit_records WHERE snapshot_id IN (SELECT snapshot_id FROM snapshots WHERE debate_id IN ({placeholders}))",
        debate_ids,
    )

    # 2. spans via posts
    cursor.execute(
        f"DELETE FROM spans WHERE post_id IN (SELECT post_id FROM posts WHERE debate_id IN ({placeholders}))",
        debate_ids,
    )

    # 3. posts
    cursor.execute(f"DELETE FROM posts WHERE debate_id IN ({placeholders})", debate_ids)

    # 4. snapshots
    cursor.execute(f"DELETE FROM snapshots WHERE debate_id IN ({placeholders})", debate_ids)

    # 5. topics
    cursor.execute(f"DELETE FROM topics WHERE debate_id IN ({placeholders})", debate_ids)

    # 6. facts / canonical_facts / arguments / canonical_arguments
    cursor.execute(f"DELETE FROM facts WHERE debate_id IN ({placeholders})", debate_ids)
    cursor.execute(f"DELETE FROM canonical_facts WHERE debate_id IN ({placeholders})", debate_ids)
    cursor.execute(f"DELETE FROM arguments WHERE debate_id IN ({placeholders})", debate_ids)
    cursor.execute(
        f"DELETE FROM canonical_arguments WHERE debate_id IN ({placeholders})", debate_ids
    )

    # 7. debate_frames
    cursor.execute(f"DELETE FROM debate_frames WHERE debate_id IN ({placeholders})", debate_ids)

    # 8. failed_publishes / frame_petitions
    cursor.execute(f"DELETE FROM failed_publishes WHERE debate_id IN ({placeholders})", debate_ids)
    cursor.execute(f"DELETE FROM frame_petitions WHERE debate_id IN ({placeholders})", debate_ids)

    # 9. debates
    cursor.execute(f"DELETE FROM debates WHERE debate_id IN ({placeholders})", debate_ids)

    conn.commit()

    # Verify
    cursor.execute("SELECT COUNT(*) FROM debates WHERE user_id IS NULL OR user_id = ''")
    remaining = cursor.fetchone()[0]

    print(f"\nDone. Deleted {len(debate_ids)} debates.")
    print(f"Remaining debates without user_id: {remaining}")

    cursor.execute("SELECT COUNT(*) as total FROM debates")
    total = cursor.fetchone()[0]
    print(f"Total debates remaining: {total}")

    conn.close()


if __name__ == "__main__":
    main()
