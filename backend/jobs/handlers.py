"""Background job handlers for snapshot generation and verification."""

import logging
import os

from backend import extensions

DB_PATH = os.getenv("DEBATE_DB_PATH", "data/debate_system.db")


def _handle_snapshot_job(job_id: str, parameters: dict, queue):
    """Background handler for snapshot generation jobs."""
    from backend.github_publisher import get_publisher_from_env
    from backend.published_results import PublishedResultsBuilder

    _logger = logging.getLogger("debate_system")
    debate_id = parameters.get("debate_id")
    trigger_type = parameters.get("trigger_type", "manual")
    request_id = parameters.get("request_id")
    queue.update_progress(job_id, 10)
    try:
        snapshot = extensions.debate_engine.generate_snapshot(
            debate_id=debate_id,
            trigger_type=trigger_type,
            request_id=request_id,
        )
        queue.update_progress(job_id, 90)
        publisher = get_publisher_from_env()
        if publisher:
            try:
                builder = PublishedResultsBuilder(
                    db_path=extensions.db_path or DB_PATH, engine=extensions.debate_engine
                )
                bundle = builder.build_bundle(
                    debate_id=debate_id,
                    commit_message=f"Snapshot {snapshot['snapshot_id']} — {trigger_type}",
                )
                result = publisher.publish_json(
                    payload=bundle,
                    commit_message=bundle["commit_message"],
                )
                _logger.info(
                    f"Published to GitHub: {result.commit_sha}", extra={"request_id": request_id}
                )
            except Exception as pub_err:
                _logger.error(f"GitHub publish error: {pub_err}", extra={"request_id": request_id})
        queue.update_progress(job_id, 100)
        return {
            "snapshot_id": snapshot["snapshot_id"],
            "timestamp": snapshot["timestamp"],
            "trigger_type": snapshot["trigger_type"],
            "status": snapshot.get("status", "valid"),
            "verdict": snapshot["verdict"],
            "confidence": snapshot["confidence"],
        }
    except Exception as e:
        _logger.error(
            f"Async snapshot generation error: {str(e)}", extra={"request_id": request_id}
        )
        raise


def _handle_verify_job(job_id: str, parameters: dict, queue):
    """Background handler for nightly snapshot verification jobs."""
    _logger = logging.getLogger("debate_system")
    snapshot_id = parameters.get("snapshot_id")
    request_id = parameters.get("request_id")
    queue.update_progress(job_id, 10)
    try:
        result = extensions.debate_engine.verify_snapshot(snapshot_id)
        queue.update_progress(job_id, 100)
        _logger.info(
            f"Nightly verification complete for {snapshot_id}: verified={result.get('verified')}",
            extra={"request_id": request_id},
        )
        return result
    except Exception as e:
        _logger.error(
            f"Verification job failed for {snapshot_id}: {e}", extra={"request_id": request_id}
        )
        raise
