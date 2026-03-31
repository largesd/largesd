"""
Snapshot Diff Capability

Per MSD §16: Users can compare snapshots via diffs:
- Posts included
- Topic lineage changes
- FACT set changes
- ARGUMENT set changes
- Score distributions and D distribution changes
"""

from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import json
from collections import defaultdict


@dataclass
class FactChange:
    """Change to a canonical fact"""
    change_type: str  # added, removed, modified
    fact_id: str
    fact_text: str
    side: str
    p_true_old: Optional[float] = None
    p_true_new: Optional[float] = None
    provenance_change: Optional[str] = None


@dataclass
class ArgumentChange:
    """Change to a canonical argument"""
    change_type: str  # added, removed, modified
    arg_id: str
    inference_text: str
    side: str
    supporting_facts_old: List[str] = field(default_factory=list)
    supporting_facts_new: List[str] = field(default_factory=list)


@dataclass
class TopicChange:
    """Change to a topic"""
    change_type: str  # added, removed, merged, split, renamed, unchanged
    topic_id: str
    topic_name: str
    parent_topic_ids: List[str] = field(default_factory=list)
    operation: str = ""
    drift_score: float = 0.0


@dataclass
class ScoreChange:
    """Change to scores"""
    topic_id: Optional[str]  # None for overall
    side: Optional[str]  # None for overall
    metric: str  # factuality, reasoning, coverage, quality, overall
    old_value: float
    new_value: float
    delta: float


@dataclass
class PostChange:
    """Change to posts"""
    change_type: str  # added, removed
    post_id: str
    side: str
    topic_id: Optional[str]
    facts_preview: str = ""
    inference_preview: str = ""


@dataclass
class SnapshotDiff:
    """
    Complete diff between two snapshots.
    
    Per MSD §16:
    - posts included changes
    - topic lineage changes
    - FACT set changes
    - ARGUMENT set changes
    - score distributions and D distribution changes
    """
    snapshot_id_old: str
    snapshot_id_new: str
    timestamp_old: str
    timestamp_new: str
    
    # Changes
    posts: List[PostChange] = field(default_factory=list)
    topics: List[TopicChange] = field(default_factory=list)
    facts: List[FactChange] = field(default_factory=list)
    arguments: List[ArgumentChange] = field(default_factory=list)
    scores: List[ScoreChange] = field(default_factory=list)
    
    # Verdict changes
    verdict_old: str = ""
    verdict_new: str = ""
    confidence_old: float = 0.0
    confidence_new: float = 0.0
    margin_d_old: float = 0.0
    margin_d_new: float = 0.0
    
    # Summary
    summary: Dict[str, int] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization"""
        return {
            "snapshot_id_old": self.snapshot_id_old,
            "snapshot_id_new": self.snapshot_id_new,
            "timestamp_old": self.timestamp_old,
            "timestamp_new": self.timestamp_new,
            "posts": [
                {
                    "change_type": p.change_type,
                    "post_id": p.post_id,
                    "side": p.side,
                    "topic_id": p.topic_id,
                    "facts_preview": p.facts_preview[:100] + "..." if len(p.facts_preview) > 100 else p.facts_preview,
                    "inference_preview": p.inference_preview[:100] + "..." if len(p.inference_preview) > 100 else p.inference_preview
                }
                for p in self.posts
            ],
            "topics": [
                {
                    "change_type": t.change_type,
                    "topic_id": t.topic_id,
                    "topic_name": t.topic_name,
                    "parent_topic_ids": t.parent_topic_ids,
                    "operation": t.operation,
                    "drift_score": t.drift_score
                }
                for t in self.topics
            ],
            "facts": [
                {
                    "change_type": f.change_type,
                    "fact_id": f.fact_id,
                    "fact_text": f.fact_text[:100] + "..." if len(f.fact_text) > 100 else f.fact_text,
                    "side": f.side,
                    "p_true_old": f.p_true_old,
                    "p_true_new": f.p_true_new
                }
                for f in self.facts
            ],
            "arguments": [
                {
                    "change_type": a.change_type,
                    "arg_id": a.arg_id,
                    "inference_text": a.inference_text[:100] + "..." if len(a.inference_text) > 100 else a.inference_text,
                    "side": a.side
                }
                for a in self.arguments
            ],
            "scores": [
                {
                    "topic_id": s.topic_id,
                    "side": s.side,
                    "metric": s.metric,
                    "old_value": round(s.old_value, 3),
                    "new_value": round(s.new_value, 3),
                    "delta": round(s.delta, 3)
                }
                for s in self.scores
            ],
            "verdict_change": {
                "old": self.verdict_old,
                "new": self.verdict_new,
                "changed": self.verdict_old != self.verdict_new
            },
            "confidence_change": {
                "old": round(self.confidence_old, 3),
                "new": round(self.confidence_new, 3),
                "delta": round(self.confidence_new - self.confidence_old, 3)
            },
            "margin_d_change": {
                "old": round(self.margin_d_old, 4),
                "new": round(self.margin_d_new, 4),
                "delta": round(self.margin_d_new - self.margin_d_old, 4)
            },
            "summary": self.summary
        }


class SnapshotDiffEngine:
    """Engine for computing diffs between snapshots"""
    
    def __init__(self, database):
        """
        Initialize with database connection.
        
        Args:
            database: DebateDatabase instance
        """
        self.db = database
    
    def diff_snapshots(self, snapshot_id_old: str, 
                       snapshot_id_new: str) -> SnapshotDiff:
        """
        Compute diff between two snapshots.
        
        Args:
            snapshot_id_old: ID of older snapshot
            snapshot_id_new: ID of newer snapshot
        
        Returns:
            SnapshotDiff object with all changes
        """
        # Load snapshots
        snap_old = self._load_snapshot(snapshot_id_old)
        snap_new = self._load_snapshot(snapshot_id_new)
        
        if not snap_old or not snap_new:
            raise ValueError("One or both snapshots not found")
        
        diff = SnapshotDiff(
            snapshot_id_old=snapshot_id_old,
            snapshot_id_new=snapshot_id_new,
            timestamp_old=snap_old.get('timestamp', ''),
            timestamp_new=snap_new.get('timestamp', '')
        )
        
        # Compute diffs
        diff.posts = self._diff_posts(snap_old, snap_new)
        diff.topics = self._diff_topics(snap_old, snap_new)
        diff.facts = self._diff_facts(snap_old, snap_new)
        diff.arguments = self._diff_arguments(snap_old, snap_new)
        diff.scores = self._diff_scores(snap_old, snap_new)
        
        # Verdict changes
        diff.verdict_old = snap_old.get('verdict', 'NO VERDICT')
        diff.verdict_new = snap_new.get('verdict', 'NO VERDICT')
        diff.confidence_old = snap_old.get('confidence', 0.0)
        diff.confidence_new = snap_new.get('confidence', 0.0)
        diff.margin_d_old = snap_old.get('margin_d', 0.0)
        diff.margin_d_new = snap_new.get('margin_d', 0.0)
        
        # Summary
        diff.summary = {
            "posts_added": len([p for p in diff.posts if p.change_type == "added"]),
            "topics_changed": len([t for t in diff.topics if t.change_type != "unchanged"]),
            "facts_added": len([f for f in diff.facts if f.change_type == "added"]),
            "facts_removed": len([f for f in diff.facts if f.change_type == "removed"]),
            "facts_modified": len([f for f in diff.facts if f.change_type == "modified"]),
            "arguments_added": len([a for a in diff.arguments if a.change_type == "added"]),
            "arguments_removed": len([a for a in diff.arguments if a.change_type == "removed"]),
            "verdict_changed": diff.verdict_old != diff.verdict_new
        }
        
        return diff
    
    def _load_snapshot(self, snapshot_id: str) -> Optional[Dict]:
        """Load snapshot data from database"""
        conn = self.db._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM snapshots WHERE snapshot_id = ?", (snapshot_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
    
    def _diff_posts(self, snap_old: Dict, snap_new: Dict) -> List[PostChange]:
        """Diff posts between snapshots"""
        # Get posts for each snapshot's debate
        debate_id = snap_new.get('debate_id')
        
        # Get all posts for this debate up to each snapshot timestamp
        old_time = snap_old.get('timestamp', '1970-01-01')
        new_time = snap_new.get('timestamp', '1970-01-01')
        
        conn = self.db._get_connection()
        cursor = conn.cursor()
        
        # Posts up to old snapshot
        cursor.execute("""
            SELECT post_id, side, topic_id, facts, inference, timestamp
            FROM posts 
            WHERE debate_id = ? AND timestamp <= ?
        """, (debate_id, old_time))
        old_posts = {row['post_id']: dict(row) for row in cursor.fetchall()}
        
        # Posts up to new snapshot
        cursor.execute("""
            SELECT post_id, side, topic_id, facts, inference, timestamp
            FROM posts 
            WHERE debate_id = ? AND timestamp <= ?
        """, (debate_id, new_time))
        new_posts = {row['post_id']: dict(row) for row in cursor.fetchall()}
        
        conn.close()
        
        changes = []
        
        # Find added posts
        for post_id, post in new_posts.items():
            if post_id not in old_posts:
                changes.append(PostChange(
                    change_type="added",
                    post_id=post_id,
                    side=post.get('side', ''),
                    topic_id=post.get('topic_id'),
                    facts_preview=post.get('facts', '')[:200],
                    inference_preview=post.get('inference', '')[:200]
                ))
        
        # Find removed posts (rare but possible if posts are retracted)
        for post_id, post in old_posts.items():
            if post_id not in new_posts:
                changes.append(PostChange(
                    change_type="removed",
                    post_id=post_id,
                    side=post.get('side', ''),
                    topic_id=post.get('topic_id'),
                    facts_preview=post.get('facts', '')[:200],
                    inference_preview=post.get('inference', '')[:200]
                ))
        
        return changes
    
    def _diff_topics(self, snap_old: Dict, snap_new: Dict) -> List[TopicChange]:
        """Diff topics between snapshots"""
        # Load topics from database
        debate_id = snap_new.get('debate_id')
        
        old_time = snap_old.get('timestamp', '1970-01-01')
        new_time = snap_new.get('timestamp', '1970-01-01')
        
        conn = self.db._get_connection()
        cursor = conn.cursor()
        
        # Topics from old snapshot period
        cursor.execute("""
            SELECT topic_id, name, parent_topic_ids, operation, drift_score
            FROM topics 
            WHERE debate_id = ? AND created_at <= ?
        """, (debate_id, old_time))
        old_topics = {row['topic_id']: dict(row) for row in cursor.fetchall()}
        
        # Topics from new snapshot period
        cursor.execute("""
            SELECT topic_id, name, parent_topic_ids, operation, drift_score
            FROM topics 
            WHERE debate_id = ? AND created_at <= ?
        """, (debate_id, new_time))
        new_topics = {row['topic_id']: dict(row) for row in cursor.fetchall()}
        
        conn.close()
        
        changes = []
        
        for topic_id, topic in new_topics.items():
            if topic_id not in old_topics:
                # New topic
                changes.append(TopicChange(
                    change_type="added",
                    topic_id=topic_id,
                    topic_name=topic.get('name', ''),
                    parent_topic_ids=json.loads(topic.get('parent_topic_ids', '[]') or '[]'),
                    operation=topic.get('operation', 'created'),
                    drift_score=topic.get('drift_score', 0.0)
                ))
            else:
                # Existing topic - check for changes
                old_topic = old_topics[topic_id]
                op = topic.get('operation', 'unchanged')
                
                if op in ['merged', 'split', 'renamed']:
                    change_type = op
                else:
                    change_type = "unchanged"
                
                changes.append(TopicChange(
                    change_type=change_type,
                    topic_id=topic_id,
                    topic_name=topic.get('name', ''),
                    parent_topic_ids=json.loads(topic.get('parent_topic_ids', '[]') or '[]'),
                    operation=op,
                    drift_score=topic.get('drift_score', 0.0)
                ))
        
        # Check for removed topics
        for topic_id, topic in old_topics.items():
            if topic_id not in new_topics:
                changes.append(TopicChange(
                    change_type="removed",
                    topic_id=topic_id,
                    topic_name=topic.get('name', ''),
                    parent_topic_ids=json.loads(topic.get('parent_topic_ids', '[]') or '[]'),
                    operation="removed"
                ))
        
        return changes
    
    def _diff_facts(self, snap_old: Dict, snap_new: Dict) -> List[FactChange]:
        """Diff canonical facts between snapshots"""
        # Facts are stored in the database per snapshot context
        # For now, compare based on available data
        
        # Get topic scores which contain fact references
        old_scores = json.loads(snap_old.get('topic_scores', '{}') or '{}')
        new_scores = json.loads(snap_new.get('topic_scores', '{}') or '{}')
        
        # This is a simplified diff - in a full implementation,
        # we'd track facts with their IDs across snapshots
        changes = []
        
        # Get debate_id to query facts
        debate_id = snap_new.get('debate_id')
        
        conn = self.db._get_connection()
        cursor = conn.cursor()
        
        # Get facts up to each snapshot
        old_time = snap_old.get('timestamp', '1970-01-01')
        new_time = snap_new.get('timestamp', '1970-01-01')
        
        cursor.execute("""
            SELECT canon_fact_id, canon_fact_text, side, p_true, created_at
            FROM canonical_facts 
            WHERE debate_id = ? AND created_at <= ?
        """, (debate_id, old_time))
        old_facts = {row['canon_fact_id']: dict(row) for row in cursor.fetchall()}
        
        cursor.execute("""
            SELECT canon_fact_id, canon_fact_text, side, p_true, created_at
            FROM canonical_facts 
            WHERE debate_id = ? AND created_at <= ?
        """, (debate_id, new_time))
        new_facts = {row['canon_fact_id']: dict(row) for row in cursor.fetchall()}
        
        conn.close()
        
        # Find changes
        for fact_id, fact in new_facts.items():
            if fact_id not in old_facts:
                changes.append(FactChange(
                    change_type="added",
                    fact_id=fact_id,
                    fact_text=fact.get('canon_fact_text', ''),
                    side=fact.get('side', ''),
                    p_true_new=fact.get('p_true', 0.5)
                ))
            else:
                old_fact = old_facts[fact_id]
                if old_fact.get('p_true') != fact.get('p_true'):
                    changes.append(FactChange(
                        change_type="modified",
                        fact_id=fact_id,
                        fact_text=fact.get('canon_fact_text', ''),
                        side=fact.get('side', ''),
                        p_true_old=old_fact.get('p_true'),
                        p_true_new=fact.get('p_true')
                    ))
        
        for fact_id, fact in old_facts.items():
            if fact_id not in new_facts:
                changes.append(FactChange(
                    change_type="removed",
                    fact_id=fact_id,
                    fact_text=fact.get('canon_fact_text', ''),
                    side=fact.get('side', ''),
                    p_true_old=fact.get('p_true')
                ))
        
        return changes
    
    def _diff_arguments(self, snap_old: Dict, snap_new: Dict) -> List[ArgumentChange]:
        """Diff canonical arguments between snapshots"""
        debate_id = snap_new.get('debate_id')
        
        conn = self.db._get_connection()
        cursor = conn.cursor()
        
        old_time = snap_old.get('timestamp', '1970-01-01')
        new_time = snap_new.get('timestamp', '1970-01-01')
        
        cursor.execute("""
            SELECT canon_arg_id, inference_text, side, supporting_facts, created_at
            FROM canonical_arguments 
            WHERE debate_id = ? AND created_at <= ?
        """, (debate_id, old_time))
        old_args = {row['canon_arg_id']: dict(row) for row in cursor.fetchall()}
        
        cursor.execute("""
            SELECT canon_arg_id, inference_text, side, supporting_facts, created_at
            FROM canonical_arguments 
            WHERE debate_id = ? AND created_at <= ?
        """, (debate_id, new_time))
        new_args = {row['canon_arg_id']: dict(row) for row in cursor.fetchall()}
        
        conn.close()
        
        changes = []
        
        for arg_id, arg in new_args.items():
            if arg_id not in old_args:
                changes.append(ArgumentChange(
                    change_type="added",
                    arg_id=arg_id,
                    inference_text=arg.get('inference_text', ''),
                    side=arg.get('side', '')
                ))
            else:
                old_arg = old_args[arg_id]
                old_facts = json.loads(old_arg.get('supporting_facts', '[]') or '[]')
                new_facts = json.loads(arg.get('supporting_facts', '[]') or '[]')
                
                if set(old_facts) != set(new_facts):
                    changes.append(ArgumentChange(
                        change_type="modified",
                        arg_id=arg_id,
                        inference_text=arg.get('inference_text', ''),
                        side=arg.get('side', ''),
                        supporting_facts_old=old_facts,
                        supporting_facts_new=new_facts
                    ))
        
        for arg_id, arg in old_args.items():
            if arg_id not in new_args:
                changes.append(ArgumentChange(
                    change_type="removed",
                    arg_id=arg_id,
                    inference_text=arg.get('inference_text', ''),
                    side=arg.get('side', '')
                ))
        
        return changes
    
    def _diff_scores(self, snap_old: Dict, snap_new: Dict) -> List[ScoreChange]:
        """Diff scores between snapshots"""
        changes = []
        
        # Parse topic scores
        old_scores = json.loads(snap_old.get('topic_scores', '{}') or '{}')
        new_scores = json.loads(snap_new.get('topic_scores', '{}') or '{}')
        
        metrics = ['factuality', 'reasoning', 'coverage', 'quality']
        
        # Compare topic-side scores
        all_keys = set(old_scores.keys()) | set(new_scores.keys())
        
        for key in all_keys:
            old_vals = old_scores.get(key, {})
            new_vals = new_scores.get(key, {})
            
            # Parse topic_id and side from key (format: "topic_id_side")
            parts = key.rsplit('_', 1)
            if len(parts) == 2:
                topic_id, side = parts
            else:
                topic_id, side = key, None
            
            for metric in metrics:
                old_val = old_vals.get(metric, 0.0)
                new_val = new_vals.get(metric, 0.0)
                
                if abs(old_val - new_val) > 0.001:  # Significant change
                    changes.append(ScoreChange(
                        topic_id=topic_id,
                        side=side,
                        metric=metric,
                        old_value=old_val,
                        new_value=new_val,
                        delta=new_val - old_val
                    ))
        
        # Overall scores
        overall_metrics = [
            ('overall_for', None, 'overall_for'),
            ('overall_against', None, 'overall_against')
        ]
        
        for field_name, side, metric_name in overall_metrics:
            old_val = snap_old.get(field_name, 0.0)
            new_val = snap_new.get(field_name, 0.0)
            
            if abs(old_val - new_val) > 0.001:
                changes.append(ScoreChange(
                    topic_id=None,
                    side=side,
                    metric=metric_name,
                    old_value=old_val,
                    new_value=new_val,
                    delta=new_val - old_val
                ))
        
        return changes
    
    def get_snapshot_history(self, debate_id: str) -> List[Dict]:
        """Get chronological history of snapshots for a debate"""
        conn = self.db._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT snapshot_id, timestamp, trigger_type, verdict, confidence, margin_d
            FROM snapshots 
            WHERE debate_id = ?
            ORDER BY timestamp ASC
        """, (debate_id,))
        rows = cursor.fetchall()
        conn.close()
        
        return [
            {
                "snapshot_id": row['snapshot_id'],
                "timestamp": row['timestamp'],
                "trigger_type": row['trigger_type'],
                "verdict": row['verdict'],
                "confidence": row['confidence'],
                "margin_d": row['margin_d']
            }
            for row in rows
        ]
