#!/usr/bin/env python3
"""Test LSD v1.2 Slice 1: Frame Registry + Async Infrastructure"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.frame_registry import FrameRegistry, get_public_frame_registry
from backend.job_queue import JobQueue, JobStatus
from backend.database import get_db_connection


def test_frame_registry():
    """Test Frame Registry implementation."""
    print("\n=== Testing Frame Registry ===")
    
    # Test 1: Load default frame
    registry = FrameRegistry.load_default()
    frame = registry.get_active_frame()
    
    assert frame is not None, "Active frame should be loaded"
    assert frame.frame_id == "lsd_v1_2_default"
    assert frame.version == "1.2.0"
    assert len(frame.statement) > 0, "Statement should not be empty"
    assert len(frame.scope) > 0, "Scope should not be empty"
    print(f"✓ Default frame loaded: {frame.frame_id} v{frame.version}")
    
    # Test 2: Content hash
    content_hash = frame.compute_content_hash()
    assert len(content_hash) == 16, "Hash should be 16 hex chars"
    print(f"✓ Content hash: {content_hash}")
    
    # Test 3: Public dossier
    dossier = registry.get_public_dossier()
    assert dossier is not None
    assert 'dossier' in dossier
    assert 'content_hash' in dossier
    assert dossier['dossier']['statement'] == frame.statement
    print(f"✓ Public dossier generated")
    
    # Test 4: Snapshot metadata
    metadata = registry.get_snapshot_metadata()
    assert 'frame_id' in metadata
    assert 'frame_version' in metadata
    assert 'frame_hash' in metadata
    print(f"✓ Snapshot metadata: {metadata}")
    
    print("\n=== Frame Registry: ALL PASSED ===")
    return True


def test_job_queue():
    """Test async job queue."""
    print("\n=== Testing Job Queue ===")
    
    db = get_db_connection()
    queue = JobQueue(db)
    
    # Test 1: Create job
    job_id = queue.create_job(
        job_type="snapshot_generation",
        parameters={"debate_id": "test_debate_123", "tier": "A"}
    )
    assert job_id.startswith("job_")
    print(f"✓ Job created: {job_id}")
    
    # Test 2: Get job
    job = queue.get_job(job_id)
    assert job is not None
    assert job.job_type == "snapshot_generation"
    assert job.status == JobStatus.QUEUED
    assert job.progress == 0
    print(f"✓ Job retrieved: status={job.status.value}")
    
    # Test 3: Update progress
    queue.update_progress(job_id, 50)
    job = queue.get_job(job_id)
    assert job.progress == 50
    print(f"✓ Progress updated: {job.progress}%")
    
    # Test 4: Complete job
    result = {"snapshot_id": "snap_abc123", "p_true": 0.75}
    queue.complete_job(job_id, result)
    job = queue.get_job(job_id)
    assert job.status == JobStatus.COMPLETED
    assert job.progress == 100
    assert job.result == result
    print(f"✓ Job completed with result")
    
    # Test 5: Create and fail job
    fail_job_id = queue.create_job("test", {})
    queue.fail_job(fail_job_id, "Test error message")
    job = queue.get_job(fail_job_id)
    assert job.status == JobStatus.FAILED
    assert job.error == "Test error message"
    print(f"✓ Job failed correctly")
    
    print("\n=== Job Queue: ALL PASSED ===")
    return True


def test_debate_engine_v2_integration():
    """Test that debate engine v2 integrates Frame Registry and Job Queue."""
    print("\n=== Testing DebateEngineV2 Integration ===")
    
    from backend.debate_engine_v2 import DebateEngineV2
    
    engine = DebateEngineV2(db_path=":memory:")
    
    # Check Frame Registry integration
    assert hasattr(engine, 'frame_registry')
    assert engine.frame_registry is not None
    frame = engine.frame_registry.get_active_frame()
    assert frame is not None
    print(f"✓ Frame Registry integrated: {frame.frame_id}")
    
    # Check Job Queue integration
    assert hasattr(engine, 'job_queue')
    assert engine.job_queue is not None
    print(f"✓ Job Queue integrated")
    
    # Check extended snapshot metadata
    metadata = engine.frame_registry.get_snapshot_metadata()
    assert 'frame_hash' in metadata
    print(f"✓ Extended snapshot metadata available")
    
    print("\n=== DebateEngineV2 Integration: ALL PASSED ===")
    return True


if __name__ == "__main__":
    print("\n" + "="*60)
    print("LSD v1.2 Slice 1 Test Suite")
    print("Frame Registry + Async Infrastructure")
    print("="*60)
    
    all_passed = True
    
    try:
        all_passed &= test_frame_registry()
    except Exception as e:
        print(f"✗ Frame Registry test failed: {e}")
        all_passed = False
    
    try:
        all_passed &= test_job_queue()
    except Exception as e:
        print(f"✗ Job Queue test failed: {e}")
        all_passed = False
    
    try:
        all_passed &= test_debate_engine_v2_integration()
    except Exception as e:
        print(f"✗ DebateEngineV2 test failed: {e}")
        all_passed = False
    
    print("\n" + "="*60)
    if all_passed:
        print("✓ ALL SLICE 1 TESTS PASSED")
    else:
        print("✗ SOME TESTS FAILED")
        sys.exit(1)
    print("="*60)
