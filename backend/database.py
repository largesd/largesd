"""
SQLite database layer for debate system persistence
"""
import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Optional, Any
from pathlib import Path


class DebateDatabase:
    """SQLite database for debate system persistence"""
    
    def __init__(self, db_path: str = "data/debate_system.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_tables()
    
    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_column(self, cursor: sqlite3.Cursor, table_name: str,
                       column_name: str, column_definition: str):
        """Add a missing column to an existing table for lightweight migrations."""
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing_columns = {row[1] for row in cursor.fetchall()}

        if column_name not in existing_columns:
            cursor.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
            )
    
    def _init_tables(self):
        """Initialize database tables"""
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # Debates table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS debates (
                debate_id TEXT PRIMARY KEY,
                resolution TEXT NOT NULL,
                scope TEXT NOT NULL,
                created_at TEXT NOT NULL,
                current_snapshot_id TEXT,
                user_id TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        
        # Posts table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                post_id TEXT PRIMARY KEY,
                debate_id TEXT NOT NULL,
                user_id TEXT,
                side TEXT NOT NULL,
                topic_id TEXT,
                facts TEXT NOT NULL,
                inference TEXT NOT NULL,
                counter_arguments TEXT,
                timestamp TEXT NOT NULL,
                modulation_outcome TEXT NOT NULL,
                block_reason TEXT,
                FOREIGN KEY (debate_id) REFERENCES debates(debate_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        
        # Spans table for traceability (MSD §5)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS spans (
                span_id TEXT PRIMARY KEY,
                post_id TEXT NOT NULL,
                start_offset INTEGER NOT NULL,
                end_offset INTEGER NOT NULL,
                span_text TEXT NOT NULL,
                topic_id TEXT,
                side TEXT NOT NULL,
                span_type TEXT NOT NULL DEFAULT 'fact',
                token_count INTEGER DEFAULT 0,
                FOREIGN KEY (post_id) REFERENCES posts(post_id)
            )
        """)
        
        # Topics table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS topics (
                topic_id TEXT PRIMARY KEY,
                debate_id TEXT NOT NULL,
                name TEXT NOT NULL,
                scope TEXT NOT NULL,
                relevance REAL DEFAULT 0.0,
                drift_score REAL DEFAULT 0.0,
                coherence REAL DEFAULT 0.0,
                distinctness REAL DEFAULT 0.0,
                parent_topic_ids TEXT,
                operation TEXT DEFAULT 'created',
                summary_for TEXT,
                summary_against TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (debate_id) REFERENCES debates(debate_id)
            )
        """)
        
        # Facts table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS facts (
                fact_id TEXT PRIMARY KEY,
                debate_id TEXT NOT NULL,
                topic_id TEXT NOT NULL,
                side TEXT NOT NULL,
                fact_text TEXT NOT NULL,
                p_true REAL DEFAULT 0.5,
                provenance_links TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (debate_id) REFERENCES debates(debate_id),
                FOREIGN KEY (topic_id) REFERENCES topics(topic_id)
            )
        """)
        
        # Canonical facts table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS canonical_facts (
                canon_fact_id TEXT PRIMARY KEY,
                debate_id TEXT NOT NULL,
                topic_id TEXT NOT NULL,
                side TEXT NOT NULL,
                canon_fact_text TEXT NOT NULL,
                member_fact_ids TEXT NOT NULL,
                p_true REAL DEFAULT 0.5,
                provenance_links TEXT,
                referenced_by_au_ids TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (debate_id) REFERENCES debates(debate_id)
            )
        """)
        
        # Arguments table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS arguments (
                arg_id TEXT PRIMARY KEY,
                debate_id TEXT NOT NULL,
                topic_id TEXT NOT NULL,
                side TEXT NOT NULL,
                inference_text TEXT NOT NULL,
                supporting_facts TEXT,
                provenance_links TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (debate_id) REFERENCES debates(debate_id)
            )
        """)
        
        # Canonical arguments table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS canonical_arguments (
                canon_arg_id TEXT PRIMARY KEY,
                debate_id TEXT NOT NULL,
                topic_id TEXT NOT NULL,
                side TEXT NOT NULL,
                inference_text TEXT NOT NULL,
                supporting_facts TEXT NOT NULL,
                member_au_ids TEXT NOT NULL,
                provenance_links TEXT,
                reasoning_score REAL DEFAULT 0.5,
                reasoning_iqr REAL DEFAULT 0.0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (debate_id) REFERENCES debates(debate_id)
            )
        """)
        
        # Snapshots table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                snapshot_id TEXT PRIMARY KEY,
                debate_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                template_name TEXT NOT NULL,
                template_version TEXT NOT NULL,
                allowed_count INTEGER DEFAULT 0,
                blocked_count INTEGER DEFAULT 0,
                block_reasons TEXT,
                frame_id TEXT,
                overall_for REAL DEFAULT 0.0,
                overall_against REAL DEFAULT 0.0,
                margin_d REAL DEFAULT 0.0,
                ci_d_lower REAL DEFAULT -0.1,
                ci_d_upper REAL DEFAULT 0.1,
                confidence REAL DEFAULT 0.0,
                verdict TEXT DEFAULT 'NO VERDICT',
                topic_scores TEXT,
                FOREIGN KEY (debate_id) REFERENCES debates(debate_id)
            )
        """)
        
        # Audit records table
        self._ensure_column(cursor, 'snapshots', 'frame_id', 'TEXT')
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_records (
                audit_id TEXT PRIMARY KEY,
                snapshot_id TEXT NOT NULL,
                audit_type TEXT NOT NULL,
                result_data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (snapshot_id) REFERENCES snapshots(snapshot_id)
            )
        """)
        
        # Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                display_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                is_verified INTEGER DEFAULT 0,
                last_login TEXT
            )
        """)
        
        # User sessions table for tracking logins
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                token TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        # Lightweight schema migrations for older local databases.
        self._ensure_column(cursor, "debates", "user_id", "TEXT")
        self._ensure_column(cursor, "posts", "user_id", "TEXT")
        
        conn.commit()
        conn.close()
    
    # Debate operations
    def save_debate(self, debate_data: Dict[str, Any]):
        """Save or update a debate"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO debates 
            (debate_id, resolution, scope, created_at, current_snapshot_id, user_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            debate_data['debate_id'],
            debate_data['resolution'],
            debate_data['scope'],
            debate_data['created_at'],
            debate_data.get('current_snapshot_id'),
            debate_data.get('user_id')
        ))
        conn.commit()
        conn.close()
    
    def get_debate(self, debate_id: str) -> Optional[Dict[str, Any]]:
        """Get debate by ID"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM debates WHERE debate_id = ?", (debate_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    
    # Post operations
    def save_post(self, post_data: Dict[str, Any]):
        """Save a post"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO posts
            (post_id, debate_id, user_id, side, topic_id, facts, inference, counter_arguments,
             timestamp, modulation_outcome, block_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            post_data['post_id'],
            post_data['debate_id'],
            post_data.get('user_id'),
            post_data['side'],
            post_data.get('topic_id'),
            post_data['facts'],
            post_data['inference'],
            post_data.get('counter_arguments', ''),
            post_data['timestamp'],
            post_data['modulation_outcome'],
            post_data.get('block_reason')
        ))
        conn.commit()
        conn.close()
    
    def get_posts_by_debate(self, debate_id: str) -> List[Dict[str, Any]]:
        """Get all posts for a debate"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM posts WHERE debate_id = ?", (debate_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    # Span operations
    def save_span(self, span_data: Dict[str, Any]):
        """Save a span with token count for content mass calculation (MSD §11)"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO spans
            (span_id, post_id, start_offset, end_offset, span_text, topic_id, side, span_type, token_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            span_data['span_id'],
            span_data['post_id'],
            span_data['start_offset'],
            span_data['end_offset'],
            span_data['span_text'],
            span_data.get('topic_id'),
            span_data['side'],
            span_data.get('span_type', 'fact'),
            span_data.get('token_count', 0)
        ))
        conn.commit()
        conn.close()
    
    def get_spans_by_post(self, post_id: str) -> List[Dict[str, Any]]:
        """Get all spans for a post"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM spans WHERE post_id = ?", (post_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def get_spans_by_debate(self, debate_id: str) -> List[Dict[str, Any]]:
        """Get all spans for a debate via posts"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.* FROM spans s
            JOIN posts p ON s.post_id = p.post_id
            WHERE p.debate_id = ?
        """, (debate_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    # Topic operations
    def save_topic(self, topic_data: Dict[str, Any]):
        """Save or update a topic"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO topics
            (topic_id, debate_id, name, scope, relevance, drift_score, coherence, distinctness,
             parent_topic_ids, operation, summary_for, summary_against, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            topic_data['topic_id'],
            topic_data['debate_id'],
            topic_data['name'],
            topic_data['scope'],
            topic_data.get('relevance', 0.0),
            topic_data.get('drift_score', 0.0),
            topic_data.get('coherence', 0.0),
            topic_data.get('distinctness', 0.0),
            json.dumps(topic_data.get('parent_topic_ids', [])),
            topic_data.get('operation', 'created'),
            topic_data.get('summary_for', ''),
            topic_data.get('summary_against', ''),
            topic_data['created_at']
        ))
        conn.commit()
        conn.close()
    
    def get_topics_by_debate(self, debate_id: str) -> List[Dict[str, Any]]:
        """Get all topics for a debate"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM topics WHERE debate_id = ?", (debate_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    # Canonical fact operations
    def save_canonical_fact(self, fact_data: Dict[str, Any]):
        """Save a canonical fact"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO canonical_facts
            (canon_fact_id, debate_id, topic_id, side, canon_fact_text, member_fact_ids,
             p_true, provenance_links, referenced_by_au_ids, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            fact_data['canon_fact_id'],
            fact_data['debate_id'],
            fact_data['topic_id'],
            fact_data['side'],
            fact_data['canon_fact_text'],
            json.dumps(fact_data.get('member_fact_ids', [])),
            fact_data.get('p_true', 0.5),
            json.dumps(fact_data.get('provenance_links', [])),
            json.dumps(fact_data.get('referenced_by_au_ids', [])),
            fact_data['created_at']
        ))
        conn.commit()
        conn.close()
    
    def get_canonical_facts_by_debate(self, debate_id: str) -> List[Dict[str, Any]]:
        """Get all canonical facts for a debate"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM canonical_facts WHERE debate_id = ?", (debate_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def get_canonical_facts_by_topic(self, topic_id: str) -> List[Dict[str, Any]]:
        """Get all canonical facts for a topic"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM canonical_facts WHERE topic_id = ?", (topic_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    # Canonical argument operations
    def save_canonical_argument(self, arg_data: Dict[str, Any]):
        """Save a canonical argument"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO canonical_arguments
            (canon_arg_id, debate_id, topic_id, side, inference_text, supporting_facts,
             member_au_ids, provenance_links, reasoning_score, reasoning_iqr, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            arg_data['canon_arg_id'],
            arg_data['debate_id'],
            arg_data['topic_id'],
            arg_data['side'],
            arg_data['inference_text'],
            json.dumps(arg_data.get('supporting_facts', [])),
            json.dumps(arg_data.get('member_au_ids', [])),
            json.dumps(arg_data.get('provenance_links', [])),
            arg_data.get('reasoning_score', 0.5),
            arg_data.get('reasoning_iqr', 0.0),
            arg_data['created_at']
        ))
        conn.commit()
        conn.close()
    
    def get_canonical_arguments_by_debate(self, debate_id: str) -> List[Dict[str, Any]]:
        """Get all canonical arguments for a debate"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM canonical_arguments WHERE debate_id = ?", (debate_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def get_canonical_arguments_by_topic(self, topic_id: str) -> List[Dict[str, Any]]:
        """Get all canonical arguments for a topic"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM canonical_arguments WHERE topic_id = ?", (topic_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    # Snapshot operations
    def save_snapshot(self, snapshot_data: Dict[str, Any]):
        """Save a snapshot"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO snapshots
            (snapshot_id, debate_id, timestamp, trigger_type, template_name, template_version,
             allowed_count, blocked_count, block_reasons, frame_id, overall_for, overall_against,
             margin_d, ci_d_lower, ci_d_upper, confidence, verdict, topic_scores)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            snapshot_data['snapshot_id'],
            snapshot_data['debate_id'],
            snapshot_data['timestamp'],
            snapshot_data['trigger_type'],
            snapshot_data['template_name'],
            snapshot_data['template_version'],
            snapshot_data.get('allowed_count', 0),
            snapshot_data.get('blocked_count', 0),
            json.dumps(snapshot_data.get('block_reasons', {})),
            snapshot_data.get('frame_id'),
            snapshot_data.get('overall_for', 0.0),
            snapshot_data.get('overall_against', 0.0),
            snapshot_data.get('margin_d', 0.0),
            snapshot_data.get('ci_d_lower', -0.1),
            snapshot_data.get('ci_d_upper', 0.1),
            snapshot_data.get('confidence', 0.0),
            snapshot_data.get('verdict', 'NO VERDICT'),
            json.dumps(snapshot_data.get('topic_scores', {}))
        ))
        conn.commit()
        conn.close()
    
    def get_snapshots_by_debate(self, debate_id: str) -> List[Dict[str, Any]]:
        """Get all snapshots for a debate"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM snapshots WHERE debate_id = ? ORDER BY timestamp DESC",
            (debate_id,)
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def get_latest_snapshot(self, debate_id: str) -> Optional[Dict[str, Any]]:
        """Get latest snapshot for a debate"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM snapshots WHERE debate_id = ? ORDER BY timestamp DESC LIMIT 1",
            (debate_id,)
        )
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    
    # Audit operations
    def save_audit(self, audit_data: Dict[str, Any]):
        """Save an audit record"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO audit_records
            (audit_id, snapshot_id, audit_type, result_data, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            audit_data['audit_id'],
            audit_data['snapshot_id'],
            audit_data['audit_type'],
            json.dumps(audit_data['result_data']),
            audit_data['created_at']
        ))
        conn.commit()
        conn.close()
    
    def get_audits_by_snapshot(self, snapshot_id: str) -> List[Dict[str, Any]]:
        """Get all audits for a snapshot"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_records WHERE snapshot_id = ?", (snapshot_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    # User operations
    def save_user(self, user_data: Dict[str, Any]):
        """Save or update a user"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO users
            (user_id, email, password_hash, display_name, created_at, is_active, is_verified, last_login)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_data['user_id'],
            user_data['email'],
            user_data['password_hash'],
            user_data['display_name'],
            user_data['created_at'],
            1 if user_data.get('is_active', True) else 0,
            1 if user_data.get('is_verified', False) else 0,
            user_data.get('last_login')
        ))
        conn.commit()
        conn.close()
    
    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email address"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    
    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    
    def update_last_login(self, user_id: str):
        """Update user's last login timestamp"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET last_login = ? WHERE user_id = ?",
            (datetime.now().isoformat(), user_id)
        )
        conn.commit()
        conn.close()
    
    def save_session(self, session_data: Dict[str, Any]):
        """Save a user session"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO user_sessions
            (session_id, user_id, token, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            session_data['session_id'],
            session_data['user_id'],
            session_data['token'],
            session_data['created_at'],
            session_data['expires_at']
        ))
        conn.commit()
        conn.close()
    
    def get_session_by_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Get session by token"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM user_sessions WHERE token = ? AND expires_at > ?",
            (token, datetime.now().isoformat())
        )
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
