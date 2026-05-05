"""
SQLite database layer for debate system persistence
"""
import os
import sqlite3
import json
import uuid
from datetime import datetime
from typing import List, Dict, Optional, Any
from pathlib import Path

try:
    from debate_proposal import hydrate_frame_record, serialize_frame_record
except ModuleNotFoundError:
    from .debate_proposal import hydrate_frame_record, serialize_frame_record


class DebateDatabase:
    """SQLite database for debate system persistence"""
    
    def __init__(self, db_path: str = "data/debate_system.db"):
        self.db_path = db_path
        self._db_url = os.getenv("DATABASE_URL", "")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_tables()
    
    def _get_connection(self):
        db_url = os.getenv("DATABASE_URL", "")
        if db_url.startswith("postgresql://"):
            try:
                import psycopg2
                conn = psycopg2.connect(db_url)
                return conn
            except ImportError:
                raise RuntimeError("psycopg2 required for PostgreSQL. Install: pip install psycopg2-binary")
        elif db_url.startswith("sqlite:///"):
            conn = sqlite3.connect(db_url.replace("sqlite:///", ""))
            conn.row_factory = sqlite3.Row
            return conn
        else:
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
                motion TEXT DEFAULT '',
                moderation_criteria TEXT DEFAULT '',
                debate_frame TEXT DEFAULT '',
                active_frame_id TEXT,
                created_at TEXT NOT NULL,
                current_snapshot_id TEXT,
                user_id TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS debate_frames (
                frame_id TEXT PRIMARY KEY,
                debate_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                stage TEXT NOT NULL,
                label TEXT DEFAULT '',
                motion TEXT NOT NULL,
                frame_summary TEXT DEFAULT '',
                sides TEXT NOT NULL,
                evaluation_criteria TEXT NOT NULL,
                definitions TEXT NOT NULL,
                scope_constraints TEXT NOT NULL,
                notes TEXT DEFAULT '',
                supersedes_frame_id TEXT,
                framing_debate_id TEXT,
                created_at TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                FOREIGN KEY (debate_id) REFERENCES debates(debate_id),
                UNIQUE (debate_id, version)
            )
        """)
        
        # Posts table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                post_id TEXT PRIMARY KEY,
                debate_id TEXT NOT NULL,
                frame_id TEXT,
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
        
        # Lightweight migrations for email processor improvements
        self._ensure_column(cursor, "posts", "submission_id", "TEXT")
        
        # Failed publishes queue for atomic/retriable GitHub publishing
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS failed_publishes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                debate_id TEXT NOT NULL,
                snapshot_id TEXT,
                payload_json TEXT NOT NULL,
                commit_message TEXT NOT NULL,
                retry_count INTEGER DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL,
                next_retry_at TEXT
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
                frame_id TEXT,
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
                frame_id TEXT,
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
                frame_id TEXT,
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
                frame_id TEXT,
                timestamp TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                template_name TEXT NOT NULL,
                template_version TEXT NOT NULL,
                allowed_count INTEGER DEFAULT 0,
                blocked_count INTEGER DEFAULT 0,
                block_reasons TEXT,
                side_order TEXT,
                overall_scores TEXT,
                overall_for REAL DEFAULT 0.0,
                overall_against REAL DEFAULT 0.0,
                margin_d REAL DEFAULT 0.0,
                ci_d_lower REAL DEFAULT -0.1,
                ci_d_upper REAL DEFAULT 0.1,
                confidence REAL DEFAULT 0.0,
                verdict TEXT DEFAULT 'NO VERDICT',
                topic_scores TEXT,
                borderline_rate REAL DEFAULT 0.0,
                suppression_policy_json TEXT,
                status TEXT DEFAULT 'valid',
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
                is_admin INTEGER DEFAULT 0,
                last_login TEXT
            )
        """)
        self._ensure_column(cursor, 'users', 'is_admin', 'INTEGER DEFAULT 0')
        
        # Migration: if no user is admin, promote the oldest registered user to admin
        cursor.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1")
        admin_count = cursor.fetchone()[0]
        if admin_count == 0:
            cursor.execute(
                "UPDATE users SET is_admin = 1 WHERE user_id = ("
                "SELECT user_id FROM users ORDER BY created_at ASC LIMIT 1"
                ")"
            )
        
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

        # Moderation template persistence for admin workflow.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS moderation_templates (
                template_record_id TEXT PRIMARY KEY,
                base_template_id TEXT NOT NULL,
                template_name TEXT NOT NULL,
                version TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('draft', 'active')),
                topic_requirements TEXT NOT NULL,
                toxicity_settings TEXT NOT NULL,
                pii_settings TEXT NOT NULL,
                spam_rate_limit_settings TEXT NOT NULL,
                prompt_injection_settings TEXT NOT NULL,
                author_user_id TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                applied_at TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS moderation_template_state (
                state_id INTEGER PRIMARY KEY CHECK (state_id = 1),
                active_template_record_id TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (active_template_record_id) REFERENCES moderation_templates(template_record_id)
            )
        """)

        # Lightweight schema migrations for older local databases.
        self._ensure_column(cursor, "debates", "user_id", "TEXT")
        self._ensure_column(cursor, "debates", "motion", "TEXT DEFAULT ''")
        self._ensure_column(cursor, "debates", "moderation_criteria", "TEXT DEFAULT ''")
        self._ensure_column(cursor, "debates", "debate_frame", "TEXT DEFAULT ''")
        self._ensure_column(cursor, "debates", "active_frame_id", "TEXT")
        self._ensure_column(cursor, "posts", "user_id", "TEXT")
        self._ensure_column(cursor, "posts", "frame_id", "TEXT")
        self._ensure_column(cursor, "topics", "frame_id", "TEXT")
        self._ensure_column(cursor, "canonical_facts", "frame_id", "TEXT")
        self._ensure_column(cursor, "canonical_arguments", "frame_id", "TEXT")
        self._ensure_column(cursor, "snapshots", "frame_id", "TEXT")
        self._ensure_column(cursor, "snapshots", "side_order", "TEXT")
        self._ensure_column(cursor, "snapshots", "overall_scores", "TEXT")
        self._ensure_column(cursor, "moderation_templates", "notes", "TEXT")
        self._ensure_column(cursor, "moderation_templates", "applied_at", "TEXT")
        # Phase 1 snapshot integrity fields
        self._ensure_column(cursor, "snapshots", "replay_manifest_json", "TEXT")
        self._ensure_column(cursor, "snapshots", "input_hash_root", "TEXT")
        self._ensure_column(cursor, "snapshots", "output_hash_root", "TEXT")
        self._ensure_column(cursor, "snapshots", "recipe_versions_json", "TEXT")
        # LSD v1.2 gap-closure fields
        self._ensure_column(cursor, "snapshots", "borderline_rate", "REAL DEFAULT 0.0")
        self._ensure_column(cursor, "snapshots", "suppression_policy_json", "TEXT")
        self._ensure_column(cursor, "snapshots", "status", "TEXT DEFAULT 'valid'")
        self._ensure_column(cursor, "snapshots", "provider_metadata_json", "TEXT")
        self._ensure_column(cursor, "snapshots", "cost_estimate", "REAL")
        self._ensure_column(cursor, "facts", "fact_type", "TEXT DEFAULT 'empirical'")
        self._ensure_column(cursor, "facts", "normative_provenance", "TEXT")
        self._ensure_column(cursor, "facts", "operationalization", "TEXT")
        self._ensure_column(cursor, "canonical_facts", "fact_type", "TEXT DEFAULT 'empirical'")
        self._ensure_column(cursor, "canonical_facts", "normative_provenance", "TEXT")
        self._ensure_column(cursor, "canonical_facts", "operationalization", "TEXT")
        self._ensure_column(cursor, "canonical_facts", "evidence_tier_counts_json", "TEXT")
        self._ensure_column(cursor, "arguments", "completeness_proxy", "REAL DEFAULT 0.0")
        self._ensure_column(cursor, "canonical_arguments", "completeness_proxy", "REAL DEFAULT 0.0")
        self._ensure_column(cursor, "debate_frames", "frame_mode", "TEXT DEFAULT 'single'")
        self._ensure_column(cursor, "debate_frames", "review_date", "TEXT")
        self._ensure_column(cursor, "debate_frames", "review_cadence_months", "INTEGER DEFAULT 6")
        self._ensure_column(cursor, "debate_frames", "emergency_override_reason", "TEXT")
        self._ensure_column(cursor, "debate_frames", "emergency_override_by", "TEXT")
        self._ensure_column(cursor, "debate_frames", "governance_decision_id", "TEXT")
        # v1.5 deterministic ternary fact-checking columns
        self._ensure_column(cursor, "canonical_facts", "v15_status", "TEXT")
        self._ensure_column(cursor, "canonical_facts", "v15_insufficiency_reason", "TEXT")
        self._ensure_column(cursor, "canonical_facts", "v15_human_review_flags_json", "TEXT")
        self._ensure_column(cursor, "canonical_facts", "v15_best_evidence_tier", "INTEGER")
        self._ensure_column(cursor, "canonical_facts", "subclaim_results_json", "TEXT")
        self._ensure_column(cursor, "canonical_facts", "human_review_flags_json", "TEXT")
        self._ensure_column(cursor, "canonical_facts", "insufficiency_reason", "TEXT")
        self._ensure_column(cursor, "canonical_facts", "best_evidence_tier", "INTEGER")
        self._ensure_column(cursor, "canonical_facts", "limiting_evidence_tier", "INTEGER")
        self._ensure_column(cursor, "canonical_facts", "decisive_evidence_tier", "INTEGER")
        self._ensure_column(cursor, "canonical_facts", "citations_json", "TEXT")
        self._ensure_column(cursor, "canonical_facts", "synthesis_logic_json", "TEXT")
        self._ensure_column(cursor, "snapshots", "fact_checker_version", "TEXT DEFAULT 'v1.5'")
        self._ensure_column(cursor, "snapshots", "evidence_policy_version", "TEXT")
        self._ensure_column(cursor, "snapshots", "synthesis_rule_engine_version", "TEXT")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS fact_check_evidence_items (
                evidence_id TEXT PRIMARY KEY,
                canon_fact_id TEXT NOT NULL,
                source_type TEXT,
                source_tier INTEGER,
                source_url TEXT,
                source_title TEXT,
                quote_or_span TEXT,
                direction TEXT,
                direction_confidence REAL,
                relevance_score REAL,
                FOREIGN KEY (canon_fact_id) REFERENCES canonical_facts(canon_fact_id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_evidence_canon_fact ON fact_check_evidence_items(canon_fact_id)")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS frame_petitions (
                petition_id TEXT PRIMARY KEY,
                debate_id TEXT NOT NULL,
                proposer_user_id TEXT,
                candidate_frame_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('pending', 'accepted', 'rejected')),
                governance_decision_json TEXT,
                reviewer_user_id TEXT,
                reviewed_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (debate_id) REFERENCES debates(debate_id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_frame_petitions_debate ON frame_petitions(debate_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_frame_petitions_status ON frame_petitions(status)")

        # Debate proposals table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS debate_proposals (
                proposal_id TEXT PRIMARY KEY,
                proposer_user_id TEXT NOT NULL,
                motion TEXT NOT NULL,
                moderation_criteria TEXT NOT NULL,
                debate_frame TEXT DEFAULT '',
                frame_payload_json TEXT DEFAULT '{}',
                status TEXT NOT NULL CHECK (status IN ('pending', 'accepted', 'rejected')),
                decision_reason TEXT,
                reviewer_user_id TEXT,
                reviewed_at TEXT,
                accepted_debate_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (proposer_user_id) REFERENCES users(user_id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_proposals_status ON debate_proposals(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_proposals_proposer ON debate_proposals(proposer_user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_proposals_created ON debate_proposals(created_at)")

        # Ensure singleton moderation template pointer exists.
        now = datetime.now().isoformat()
        cursor.execute(
            """
            INSERT OR IGNORE INTO moderation_template_state
            (state_id, active_template_record_id, updated_at)
            VALUES (1, NULL, ?)
            """,
            (now,),
        )

        # Seed a default active template if no active pointer is present.
        cursor.execute(
            "SELECT active_template_record_id FROM moderation_template_state WHERE state_id = 1"
        )
        state_row = cursor.fetchone()
        active_id = state_row["active_template_record_id"] if state_row else None
        active_exists = False
        if active_id:
            cursor.execute(
                "SELECT template_record_id FROM moderation_templates WHERE template_record_id = ?",
                (active_id,),
            )
            active_exists = cursor.fetchone() is not None

        if not active_exists:
            defaults = self._default_moderation_template_settings()
            template_record_id = f"modtpl_{uuid.uuid4().hex[:12]}"
            cursor.execute(
                """
                INSERT INTO moderation_templates
                (template_record_id, base_template_id, template_name, version, status,
                 topic_requirements, toxicity_settings, pii_settings, spam_rate_limit_settings,
                 prompt_injection_settings, author_user_id, notes, created_at, updated_at, applied_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    template_record_id,
                    "standard_civility",
                    "Standard Civility + PII Guard",
                    "1.0.0",
                    "active",
                    json.dumps(defaults["topic_requirements"]),
                    json.dumps(defaults["toxicity_settings"]),
                    json.dumps(defaults["pii_settings"]),
                    json.dumps(defaults["spam_rate_limit_settings"]),
                    json.dumps(defaults["prompt_injection_settings"]),
                    "system",
                    "Seeded default template",
                    now,
                    now,
                    now,
                ),
            )
            cursor.execute(
                """
                UPDATE moderation_template_state
                SET active_template_record_id = ?, updated_at = ?
                WHERE state_id = 1
                """,
                (template_record_id, now),
            )
        
        conn.commit()
        conn.close()

    @staticmethod
    def _default_moderation_template_settings() -> Dict[str, Dict[str, Any]]:
        return {
            "topic_requirements": {
                "required_keywords": [],
                "relevance_threshold": "moderate",
                "enforce_scope": True,
            },
            "toxicity_settings": {
                "sensitivity_level": 3,
                "block_personal_attacks": True,
                "block_hate_speech": True,
                "block_threats": True,
                "block_sexual_harassment": True,
                "block_mild_profanity": False,
            },
            "pii_settings": {
                "detect_email": True,
                "detect_phone": True,
                "detect_address": True,
                "detect_full_names": False,
                "detect_social_handles": False,
                "action": "block",
            },
            "spam_rate_limit_settings": {
                "min_length": 50,
                "max_length": 5000,
                "flood_threshold_per_hour": 10,
                "duplicate_detection": True,
                "rate_limiting": True,
            },
            "prompt_injection_settings": {
                "enabled": True,
                "block_markdown_hiding": True,
                "custom_patterns": [],
            },
        }

    @staticmethod
    def _coerce_json_field(raw_value: Any, fallback: Any) -> Any:
        if raw_value is None:
            return fallback
        if isinstance(raw_value, (dict, list)):
            return raw_value
        if isinstance(raw_value, str):
            try:
                return json.loads(raw_value)
            except json.JSONDecodeError:
                return fallback
        return fallback

    def _serialize_moderation_template_row(
        self,
        row: sqlite3.Row | Dict[str, Any],
        current_active_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        data = dict(row)
        template_record_id = data["template_record_id"]
        is_current = bool(current_active_id and template_record_id == current_active_id)
        raw_status = data.get("status", "draft")
        if is_current:
            status = "active"
        elif raw_status == "active":
            status = "applied"
        else:
            status = "draft"

        defaults = self._default_moderation_template_settings()
        return {
            "template_record_id": template_record_id,
            "base_template_id": data.get("base_template_id", "standard_civility"),
            "template_name": data.get("template_name", ""),
            "version": data.get("version", ""),
            "status": status,
            "raw_status": raw_status,
            "is_current": is_current,
            "topic_requirements": self._coerce_json_field(
                data.get("topic_requirements"), defaults["topic_requirements"]
            ),
            "toxicity_settings": self._coerce_json_field(
                data.get("toxicity_settings"), defaults["toxicity_settings"]
            ),
            "pii_settings": self._coerce_json_field(
                data.get("pii_settings"), defaults["pii_settings"]
            ),
            "spam_rate_limit_settings": self._coerce_json_field(
                data.get("spam_rate_limit_settings"), defaults["spam_rate_limit_settings"]
            ),
            "prompt_injection_settings": self._coerce_json_field(
                data.get("prompt_injection_settings"), defaults["prompt_injection_settings"]
            ),
            "author_user_id": data.get("author_user_id"),
            "notes": data.get("notes") or "",
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "applied_at": data.get("applied_at"),
        }
    
    # Debate operations
    def save_debate(self, debate_data: Dict[str, Any]):
        """Save or update a debate"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO debates 
            (debate_id, resolution, scope, motion, moderation_criteria, debate_frame,
             active_frame_id, created_at, current_snapshot_id, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            debate_data['debate_id'],
            debate_data['resolution'],
            debate_data['scope'],
            debate_data.get('motion', debate_data.get('resolution', '')),
            debate_data.get('moderation_criteria', ''),
            debate_data.get('debate_frame', ''),
            debate_data.get('active_frame_id'),
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

    # Debate frame operations
    def save_debate_frame(self, frame_data: Dict[str, Any]):
        """Save or update a debate frame version."""
        serialized = serialize_frame_record(frame_data)
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO debate_frames
            (frame_id, debate_id, version, stage, label, motion, frame_summary,
             sides, evaluation_criteria, definitions, scope_constraints, notes,
             supersedes_frame_id, framing_debate_id, created_at, is_active,
             frame_mode, review_date, review_cadence_months, emergency_override_reason,
             emergency_override_by, governance_decision_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            serialized['frame_id'],
            serialized['debate_id'],
            serialized['version'],
            serialized['stage'],
            serialized['label'],
            serialized['motion'],
            serialized['frame_summary'],
            serialized['sides'],
            serialized['evaluation_criteria'],
            serialized['definitions'],
            serialized['scope_constraints'],
            serialized['notes'],
            serialized['supersedes_frame_id'],
            serialized['framing_debate_id'],
            serialized['created_at'],
            serialized['is_active'],
            serialized.get('frame_mode', 'single'),
            serialized.get('review_date'),
            serialized.get('review_cadence_months', 6),
            serialized.get('emergency_override_reason'),
            serialized.get('emergency_override_by'),
            serialized.get('governance_decision_id'),
        ))
        conn.commit()
        conn.close()

    def set_active_frame(self, debate_id: str, frame_id: str):
        """Mark one frame active for a debate and deactivate the rest."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE debate_frames SET is_active = 0 WHERE debate_id = ?",
            (debate_id,),
        )
        cursor.execute(
            "UPDATE debate_frames SET is_active = 1 WHERE frame_id = ?",
            (frame_id,),
        )
        cursor.execute(
            "UPDATE debates SET active_frame_id = ? WHERE debate_id = ?",
            (frame_id, debate_id),
        )
        conn.commit()
        conn.close()

    def get_debate_frame(self, frame_id: str) -> Optional[Dict[str, Any]]:
        """Get a debate frame by ID."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM debate_frames WHERE frame_id = ?", (frame_id,))
        row = cursor.fetchone()
        conn.close()
        return hydrate_frame_record(dict(row)) if row else None

    def get_active_debate_frame(self, debate_id: str) -> Optional[Dict[str, Any]]:
        """Get the active frame for a debate."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM debate_frames
            WHERE debate_id = ? AND is_active = 1
            ORDER BY version DESC
            LIMIT 1
        """, (debate_id,))
        row = cursor.fetchone()
        conn.close()
        return hydrate_frame_record(dict(row)) if row else None

    def get_debate_frames(self, debate_id: str) -> List[Dict[str, Any]]:
        """List all frames for a debate in version order."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM debate_frames
            WHERE debate_id = ?
            ORDER BY version ASC
        """, (debate_id,))
        rows = cursor.fetchall()
        conn.close()
        return [hydrate_frame_record(dict(row)) for row in rows]

    def update_frame_review_schedule(
        self,
        debate_id: str,
        review_date: Optional[str],
        review_cadence_months: int,
    ):
        """Update review cadence metadata for active frame(s) in a debate."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE debate_frames
            SET review_date = ?, review_cadence_months = ?
            WHERE debate_id = ? AND is_active = 1
            """,
            (review_date, review_cadence_months, debate_id),
        )
        conn.commit()
        conn.close()

    def apply_emergency_override(
        self,
        frame_id: str,
        reason: str,
        by_user_id: Optional[str],
        governance_decision_id: Optional[str] = None,
    ):
        """Attach emergency override metadata to a frame record."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE debate_frames
            SET emergency_override_reason = ?,
                emergency_override_by = ?,
                governance_decision_id = COALESCE(?, governance_decision_id)
            WHERE frame_id = ?
            """,
            (reason, by_user_id, governance_decision_id, frame_id),
        )
        conn.commit()
        conn.close()
    
    # Post operations
    def save_post(self, post_data: Dict[str, Any]):
        """Save a post"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO posts
            (post_id, debate_id, frame_id, user_id, side, topic_id, facts, inference, counter_arguments,
             timestamp, modulation_outcome, block_reason, submission_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            post_data['post_id'],
            post_data['debate_id'],
            post_data.get('frame_id'),
            post_data.get('user_id'),
            post_data['side'],
            post_data.get('topic_id'),
            post_data['facts'],
            post_data['inference'],
            post_data.get('counter_arguments', ''),
            post_data['timestamp'],
            post_data['modulation_outcome'],
            post_data.get('block_reason'),
            post_data.get('submission_id')
        ))
        conn.commit()
        conn.close()
    
    def get_posts_by_debate(self, debate_id: str,
                            frame_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all posts for a debate"""
        conn = self._get_connection()
        cursor = conn.cursor()
        if frame_id:
            cursor.execute(
                "SELECT * FROM posts WHERE debate_id = ? AND frame_id = ?",
                (debate_id, frame_id),
            )
        else:
            cursor.execute("SELECT * FROM posts WHERE debate_id = ?", (debate_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def get_post_by_submission_id(self, submission_id: str) -> Optional[Dict]:
        """Return a post row if submission_id already exists."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT post_id, debate_id, timestamp FROM posts WHERE submission_id = ?",
            (submission_id,)
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return {
                "post_id": row[0],
                "debate_id": row[1],
                "timestamp": row[2],
            }
        return None
    
    # Failed publish queue operations
    def queue_failed_publish(self, debate_id: str, snapshot_id: Optional[str],
                             payload_json: str, commit_message: str,
                             last_error: str) -> None:
        """Queue a failed GitHub publish for later retry."""
        conn = self._get_connection()
        cursor = conn.cursor()
        created_at = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO failed_publishes
            (debate_id, snapshot_id, payload_json, commit_message, retry_count, last_error, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (debate_id, snapshot_id, payload_json, commit_message, 0, last_error, created_at))
        conn.commit()
        conn.close()
    
    def get_failed_publishes(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get pending failed publishes ordered by creation time."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, debate_id, snapshot_id, payload_json, commit_message, retry_count, last_error, created_at
            FROM failed_publishes
            ORDER BY created_at ASC
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "id": row[0],
                "debate_id": row[1],
                "snapshot_id": row[2],
                "payload_json": row[3],
                "commit_message": row[4],
                "retry_count": row[5],
                "last_error": row[6],
                "created_at": row[7],
            }
            for row in rows
        ]
    
    def mark_publish_success(self, item_id: int) -> None:
        """Remove a failed publish entry after successful retry."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM failed_publishes WHERE id = ?", (item_id,))
        conn.commit()
        conn.close()
    
    def increment_publish_retry(self, item_id: int, error: str) -> None:
        """Increment retry count and update last error for a failed publish."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE failed_publishes
            SET retry_count = retry_count + 1, last_error = ?
            WHERE id = ?
        """, (error, item_id))
        conn.commit()
        conn.close()
    
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
            (topic_id, debate_id, frame_id, name, scope, relevance, drift_score, coherence, distinctness,
             parent_topic_ids, operation, summary_for, summary_against, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            topic_data['topic_id'],
            topic_data['debate_id'],
            topic_data.get('frame_id'),
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
    
    def get_topics_by_debate(self, debate_id: str,
                             frame_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all topics for a debate"""
        conn = self._get_connection()
        cursor = conn.cursor()
        if frame_id:
            cursor.execute(
                "SELECT * FROM topics WHERE debate_id = ? AND frame_id = ?",
                (debate_id, frame_id),
            )
        else:
            cursor.execute("SELECT * FROM topics WHERE debate_id = ?", (debate_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_topic(self, topic_id: str, debate_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get one topic, optionally scoped to a debate."""
        conn = self._get_connection()
        cursor = conn.cursor()
        if debate_id:
            cursor.execute(
                "SELECT * FROM topics WHERE topic_id = ? AND debate_id = ?",
                (topic_id, debate_id),
            )
        else:
            cursor.execute("SELECT * FROM topics WHERE topic_id = ?", (topic_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    
    # Canonical fact operations
    def save_canonical_fact(self, fact_data: Dict[str, Any]):
        """Save a canonical fact"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO canonical_facts
            (canon_fact_id, debate_id, frame_id, topic_id, side, canon_fact_text, member_fact_ids,
             p_true, provenance_links, referenced_by_au_ids, fact_type, normative_provenance,
             operationalization, evidence_tier_counts_json, created_at,
             v15_status, v15_insufficiency_reason, v15_human_review_flags_json, v15_best_evidence_tier)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            fact_data['canon_fact_id'],
            fact_data['debate_id'],
            fact_data.get('frame_id'),
            fact_data['topic_id'],
            fact_data['side'],
            fact_data['canon_fact_text'],
            json.dumps(fact_data.get('member_fact_ids', [])),
            fact_data.get('p_true', 0.5),
            json.dumps(fact_data.get('provenance_links', [])),
            json.dumps(fact_data.get('referenced_by_au_ids', [])),
            fact_data.get('fact_type', 'empirical'),
            fact_data.get('normative_provenance'),
            fact_data.get('operationalization'),
            json.dumps(fact_data.get('evidence_tier_counts', {})),
            fact_data['created_at'],
            fact_data.get('v15_status'),
            fact_data.get('v15_insufficiency_reason'),
            json.dumps(fact_data.get('v15_human_review_flags', [])),
            fact_data.get('v15_best_evidence_tier'),
        ))
        conn.commit()
        conn.close()
    
    def get_canonical_facts_by_debate(self, debate_id: str,
                                      frame_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all canonical facts for a debate"""
        conn = self._get_connection()
        cursor = conn.cursor()
        if frame_id:
            cursor.execute(
                "SELECT * FROM canonical_facts WHERE debate_id = ? AND frame_id = ?",
                (debate_id, frame_id),
            )
        else:
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
            (canon_arg_id, debate_id, frame_id, topic_id, side, inference_text, supporting_facts,
             member_au_ids, provenance_links, reasoning_score, reasoning_iqr, completeness_proxy, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            arg_data['canon_arg_id'],
            arg_data['debate_id'],
            arg_data.get('frame_id'),
            arg_data['topic_id'],
            arg_data['side'],
            arg_data['inference_text'],
            json.dumps(arg_data.get('supporting_facts', [])),
            json.dumps(arg_data.get('member_au_ids', [])),
            json.dumps(arg_data.get('provenance_links', [])),
            arg_data.get('reasoning_score', 0.5),
            arg_data.get('reasoning_iqr', 0.0),
            arg_data.get('completeness_proxy', 0.0),
            arg_data['created_at']
        ))
        conn.commit()
        conn.close()
    
    def get_canonical_arguments_by_debate(self, debate_id: str,
                                          frame_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all canonical arguments for a debate"""
        conn = self._get_connection()
        cursor = conn.cursor()
        if frame_id:
            cursor.execute(
                "SELECT * FROM canonical_arguments WHERE debate_id = ? AND frame_id = ?",
                (debate_id, frame_id),
            )
        else:
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
        """Save a snapshot (append-only; rejects duplicate snapshot_id)."""
        conn = self._get_connection()
        cursor = conn.cursor()
        # Enforce append-only: reject duplicate snapshot_id
        cursor.execute(
            "SELECT 1 FROM snapshots WHERE snapshot_id = ?",
            (snapshot_data['snapshot_id'],)
        )
        if cursor.fetchone() is not None:
            conn.close()
            raise ValueError(
                f"Snapshot {snapshot_data['snapshot_id']} already exists. "
                "Snapshots are append-only."
            )
        cursor.execute("""
            INSERT INTO snapshots
            (snapshot_id, debate_id, frame_id, timestamp, trigger_type, template_name, template_version,
             allowed_count, blocked_count, block_reasons, side_order, overall_scores,
             overall_for, overall_against, margin_d, ci_d_lower, ci_d_upper, confidence,
             verdict, topic_scores, replay_manifest_json, input_hash_root, output_hash_root,
             recipe_versions_json, borderline_rate, suppression_policy_json, status,
             provider_metadata_json, cost_estimate,
             fact_checker_version, evidence_policy_version, synthesis_rule_engine_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            snapshot_data['snapshot_id'],
            snapshot_data['debate_id'],
            snapshot_data.get('frame_id'),
            snapshot_data['timestamp'],
            snapshot_data['trigger_type'],
            snapshot_data['template_name'],
            snapshot_data['template_version'],
            snapshot_data.get('allowed_count', 0),
            snapshot_data.get('blocked_count', 0),
            json.dumps(snapshot_data.get('block_reasons', {})),
            json.dumps(snapshot_data.get('side_order', [])),
            json.dumps(snapshot_data.get('overall_scores', {})),
            snapshot_data.get('overall_for', 0.0),
            snapshot_data.get('overall_against', 0.0),
            snapshot_data.get('margin_d', 0.0),
            snapshot_data.get('ci_d_lower', -0.1),
            snapshot_data.get('ci_d_upper', 0.1),
            snapshot_data.get('confidence', 0.0),
            snapshot_data.get('verdict', 'NO VERDICT'),
            json.dumps(snapshot_data.get('topic_scores', {})),
            json.dumps(snapshot_data.get('replay_manifest_json', {})),
            snapshot_data.get('input_hash_root'),
            snapshot_data.get('output_hash_root'),
            json.dumps(snapshot_data.get('recipe_versions_json', {})),
            snapshot_data.get('borderline_rate', 0.0),
            json.dumps(snapshot_data.get('suppression_policy_json', {})),
            snapshot_data.get('status', 'valid'),
            json.dumps(snapshot_data.get('provider_metadata', {})),
            snapshot_data.get('cost_estimate'),
            snapshot_data.get('fact_checker_version', 'v1.5'),
            snapshot_data.get('evidence_policy_version'),
            snapshot_data.get('synthesis_rule_engine_version'),
        ))
        conn.commit()
        conn.close()
    
    def get_snapshots_by_debate(self, debate_id: str,
                                frame_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all snapshots for a debate"""
        conn = self._get_connection()
        cursor = conn.cursor()
        if frame_id:
            cursor.execute(
                "SELECT * FROM snapshots WHERE debate_id = ? AND frame_id = ? ORDER BY timestamp DESC",
                (debate_id, frame_id)
            )
        else:
            cursor.execute(
                "SELECT * FROM snapshots WHERE debate_id = ? ORDER BY timestamp DESC",
                (debate_id,)
            )
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def get_latest_snapshot(self, debate_id: str,
                            frame_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get latest snapshot for a debate"""
        conn = self._get_connection()
        cursor = conn.cursor()
        if frame_id:
            cursor.execute(
                "SELECT * FROM snapshots WHERE debate_id = ? AND frame_id = ? ORDER BY timestamp DESC LIMIT 1",
                (debate_id, frame_id)
            )
        else:
            cursor.execute(
                "SELECT * FROM snapshots WHERE debate_id = ? ORDER BY timestamp DESC LIMIT 1",
                (debate_id,)
            )
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_snapshot_by_id(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        """Get a snapshot by id."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM snapshots WHERE snapshot_id = ?", (snapshot_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def update_snapshot_status(self, snapshot_id: str, status: str):
        """Update additive snapshot status metadata."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE snapshots SET status = ? WHERE snapshot_id = ?",
            (status, snapshot_id),
        )
        conn.commit()
        conn.close()
    
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
            (user_id, email, password_hash, display_name, created_at, is_active, is_verified, is_admin, last_login)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_data['user_id'],
            user_data['email'],
            user_data['password_hash'],
            user_data['display_name'],
            user_data['created_at'],
            1 if user_data.get('is_active', True) else 0,
            1 if user_data.get('is_verified', False) else 0,
            1 if user_data.get('is_admin', False) else 0,
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

    # Moderation template operations
    def create_moderation_template_version(
        self,
        *,
        base_template_id: str,
        template_name: str,
        version: str,
        status: str,
        topic_requirements: Dict[str, Any],
        toxicity_settings: Dict[str, Any],
        pii_settings: Dict[str, Any],
        spam_rate_limit_settings: Dict[str, Any],
        prompt_injection_settings: Dict[str, Any],
        author_user_id: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new moderation template record."""
        if status not in {"draft", "active"}:
            raise ValueError("status must be 'draft' or 'active'")

        template_record_id = f"modtpl_{uuid.uuid4().hex[:12]}"
        now = datetime.now().isoformat()

        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO moderation_templates
            (template_record_id, base_template_id, template_name, version, status,
             topic_requirements, toxicity_settings, pii_settings, spam_rate_limit_settings,
             prompt_injection_settings, author_user_id, notes, created_at, updated_at, applied_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                template_record_id,
                base_template_id,
                template_name,
                version,
                status,
                json.dumps(topic_requirements),
                json.dumps(toxicity_settings),
                json.dumps(pii_settings),
                json.dumps(spam_rate_limit_settings),
                json.dumps(prompt_injection_settings),
                author_user_id,
                notes or "",
                now,
                now,
                now if status == "active" else None,
            ),
        )

        if status == "active":
            cursor.execute(
                """
                UPDATE moderation_template_state
                SET active_template_record_id = ?, updated_at = ?
                WHERE state_id = 1
                """,
                (template_record_id, now),
            )

        conn.commit()
        conn.close()

        row = self.get_moderation_template_by_id(template_record_id)
        if not row:
            raise RuntimeError("Failed to create moderation template record")
        return row

    def get_moderation_template_by_id(self, template_record_id: str) -> Optional[Dict[str, Any]]:
        """Get one moderation template record by id."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT active_template_record_id FROM moderation_template_state WHERE state_id = 1"
        )
        state_row = cursor.fetchone()
        active_id = state_row["active_template_record_id"] if state_row else None

        cursor.execute(
            "SELECT * FROM moderation_templates WHERE template_record_id = ?",
            (template_record_id,),
        )
        row = cursor.fetchone()
        conn.close()
        return self._serialize_moderation_template_row(row, active_id) if row else None

    def activate_moderation_template(
        self,
        template_record_id: str,
        *,
        author_user_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Mark an existing template record as active and update the pointer."""
        now = datetime.now().isoformat()
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE moderation_templates
            SET status = 'active',
                updated_at = ?,
                applied_at = COALESCE(applied_at, ?),
                author_user_id = COALESCE(?, author_user_id)
            WHERE template_record_id = ?
            """,
            (now, now, author_user_id, template_record_id),
        )

        if cursor.rowcount == 0:
            conn.close()
            return None

        cursor.execute(
            """
            UPDATE moderation_template_state
            SET active_template_record_id = ?, updated_at = ?
            WHERE state_id = 1
            """,
            (template_record_id, now),
        )

        conn.commit()
        conn.close()
        return self.get_moderation_template_by_id(template_record_id)

    def get_active_moderation_template(self) -> Optional[Dict[str, Any]]:
        """Return the currently active moderation template record."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT active_template_record_id FROM moderation_template_state WHERE state_id = 1"
        )
        state_row = cursor.fetchone()
        active_id = state_row["active_template_record_id"] if state_row else None
        if not active_id:
            conn.close()
            return None

        cursor.execute(
            "SELECT * FROM moderation_templates WHERE template_record_id = ?",
            (active_id,),
        )
        row = cursor.fetchone()
        conn.close()
        return self._serialize_moderation_template_row(row, active_id) if row else None

    def get_moderation_template_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return moderation template records from newest to oldest."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT active_template_record_id FROM moderation_template_state WHERE state_id = 1"
        )
        state_row = cursor.fetchone()
        active_id = state_row["active_template_record_id"] if state_row else None

        cursor.execute(
            """
            SELECT * FROM moderation_templates
            ORDER BY datetime(COALESCE(applied_at, created_at)) DESC, datetime(created_at) DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [self._serialize_moderation_template_row(row, active_id) for row in rows]

    def get_latest_snapshot_any(self) -> Optional[Dict[str, Any]]:
        """Get the latest snapshot across all debates."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM snapshots ORDER BY timestamp DESC LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    @staticmethod
    def _block_reason_description(reason: str) -> str:
        descriptions = {
            "off_topic": "Post does not relate to the debate scope or resolution.",
            "pii": "Personally identifiable information detected.",
            "spam": "Duplicate or flooding behavior detected.",
            "harassment": "Harassment or personal attack detected.",
            "toxicity": "Toxic or abusive language detected.",
            "prompt_injection": "Prompt-manipulation attempt detected.",
            "length": "Post violated length constraints.",
        }
        return descriptions.get(reason.lower(), "Moderation rule triggered.")

    # Debate proposal operations
    def save_debate_proposal(self, proposal_data: Dict[str, Any]):
        """Save a debate proposal"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO debate_proposals
            (proposal_id, proposer_user_id, motion, moderation_criteria, debate_frame,
             frame_payload_json, status, decision_reason, reviewer_user_id, reviewed_at,
             accepted_debate_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            proposal_data['proposal_id'],
            proposal_data['proposer_user_id'],
            proposal_data['motion'],
            proposal_data.get('moderation_criteria', ''),
            proposal_data.get('debate_frame', ''),
            json.dumps(proposal_data.get('frame_payload_json', {})),
            proposal_data.get('status', 'pending'),
            proposal_data.get('decision_reason'),
            proposal_data.get('reviewer_user_id'),
            proposal_data.get('reviewed_at'),
            proposal_data.get('accepted_debate_id'),
            proposal_data['created_at'],
            proposal_data['updated_at']
        ))
        conn.commit()
        conn.close()

    def get_debate_proposal(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        """Get a debate proposal by ID"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM debate_proposals WHERE proposal_id = ?", (proposal_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        proposal = dict(row)
        try:
            proposal['frame_payload_json'] = json.loads(proposal.get('frame_payload_json', '{}') or '{}')
        except json.JSONDecodeError:
            proposal['frame_payload_json'] = {}
        return proposal

    def get_debate_proposals_by_user(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all proposals submitted by a user"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM debate_proposals WHERE proposer_user_id = ? ORDER BY created_at DESC",
            (user_id,)
        )
        rows = cursor.fetchall()
        conn.close()
        result = []
        for row in rows:
            proposal = dict(row)
            try:
                proposal['frame_payload_json'] = json.loads(proposal.get('frame_payload_json', '{}') or '{}')
            except json.JSONDecodeError:
                proposal['frame_payload_json'] = {}
            result.append(proposal)
        return result

    def get_debate_proposals_by_status(self, status: Optional[str] = None,
                                        limit: int = 100) -> List[Dict[str, Any]]:
        """Get proposals filtered by status"""
        conn = self._get_connection()
        cursor = conn.cursor()
        if status:
            cursor.execute(
                "SELECT * FROM debate_proposals WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit)
            )
        else:
            cursor.execute(
                "SELECT * FROM debate_proposals ORDER BY created_at DESC LIMIT ?",
                (limit,)
            )
        rows = cursor.fetchall()
        conn.close()
        result = []
        for row in rows:
            proposal = dict(row)
            try:
                proposal['frame_payload_json'] = json.loads(proposal.get('frame_payload_json', '{}') or '{}')
            except json.JSONDecodeError:
                proposal['frame_payload_json'] = {}
            result.append(proposal)
        return result

    def update_debate_proposal_status(self, proposal_id: str, status: str,
                                       decision_reason: Optional[str] = None,
                                       reviewer_user_id: Optional[str] = None,
                                       accepted_debate_id: Optional[str] = None):
        """Update proposal status with decision info"""
        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute("""
            UPDATE debate_proposals
            SET status = ?, decision_reason = ?, reviewer_user_id = ?,
                reviewed_at = ?, accepted_debate_id = ?, updated_at = ?
            WHERE proposal_id = ?
        """, (status, decision_reason, reviewer_user_id, now, accepted_debate_id, now, proposal_id))
        conn.commit()
        conn.close()

    # Frame petition operations
    def create_frame_petition(
        self,
        debate_id: str,
        proposer_user_id: Optional[str],
        candidate_frame: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a public frame petition for governance review."""
        petition_id = f"frpet_{uuid.uuid4().hex[:12]}"
        now = datetime.now().isoformat()
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO frame_petitions
            (petition_id, debate_id, proposer_user_id, candidate_frame_json, status,
             governance_decision_json, reviewer_user_id, reviewed_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                petition_id,
                debate_id,
                proposer_user_id,
                json.dumps(candidate_frame),
                "pending",
                None,
                None,
                None,
                now,
            ),
        )
        conn.commit()
        conn.close()
        return self.get_frame_petition(petition_id) or {}

    def get_frame_petition(self, petition_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM frame_petitions WHERE petition_id = ?", (petition_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return self._serialize_frame_petition_row(row)

    def get_frame_petitions(self, debate_id: Optional[str] = None,
                            status: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        query = "SELECT * FROM frame_petitions WHERE 1=1"
        params: List[Any] = []
        if debate_id:
            query += " AND debate_id = ?"
            params.append(debate_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY datetime(created_at) DESC"
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        return [self._serialize_frame_petition_row(row) for row in rows]

    def update_frame_petition_status(
        self,
        petition_id: str,
        status: str,
        governance_decision: Dict[str, Any],
        reviewer_user_id: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        now = datetime.now().isoformat()
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE frame_petitions
            SET status = ?, governance_decision_json = ?, reviewer_user_id = ?, reviewed_at = ?
            WHERE petition_id = ?
            """,
            (status, json.dumps(governance_decision), reviewer_user_id, now, petition_id),
        )
        conn.commit()
        conn.close()
        return self.get_frame_petition(petition_id)

    @staticmethod
    def _serialize_frame_petition_row(row: sqlite3.Row | Dict[str, Any]) -> Dict[str, Any]:
        data = dict(row)
        return {
            "petition_id": data["petition_id"],
            "debate_id": data["debate_id"],
            "proposer_user_id": data.get("proposer_user_id"),
            "candidate_frame": DebateDatabase._coerce_json_field(
                data.get("candidate_frame_json"), {}
            ),
            "status": data.get("status", "pending"),
            "governance_decision": DebateDatabase._coerce_json_field(
                data.get("governance_decision_json"), {}
            ),
            "reviewer_user_id": data.get("reviewer_user_id"),
            "reviewed_at": data.get("reviewed_at"),
            "created_at": data.get("created_at"),
        }

    def get_moderation_outcome_summary(self, debate_id: Optional[str] = None) -> Dict[str, Any]:
        """Return latest moderation outcome summary for admin dashboards."""
        snapshot = self.get_latest_snapshot(debate_id) if debate_id else self.get_latest_snapshot_any()
        if not snapshot:
            return {
                "snapshot_id": None,
                "debate_id": debate_id,
                "allowed_count": 0,
                "blocked_count": 0,
            "block_rate": 0.0,
            "top_reason": None,
            "block_reasons": [],
            "borderline_rate": 0.0,
            "suppression_policy": {"k": 5, "affected_buckets": [], "affected_bucket_count": 0},
        }

        raw_reasons = self._coerce_json_field(snapshot.get("block_reasons"), {})
        if not isinstance(raw_reasons, dict):
            raw_reasons = {}
        sorted_reasons = sorted(raw_reasons.items(), key=lambda pair: pair[1], reverse=True)

        blocked_count = int(snapshot.get("blocked_count") or 0)
        allowed_count = int(snapshot.get("allowed_count") or 0)
        total = allowed_count + blocked_count
        block_rate = (blocked_count / total) if total > 0 else 0.0

        reason_rows = []
        for reason, count in sorted_reasons:
            percentage = (count / blocked_count * 100.0) if blocked_count > 0 else 0.0
            reason_rows.append({
                "reason": reason,
                "count": int(count),
                "percentage": round(percentage, 2),
                "description": self._block_reason_description(reason),
            })

        return {
            "snapshot_id": snapshot.get("snapshot_id"),
            "debate_id": snapshot.get("debate_id"),
            "allowed_count": allowed_count,
            "blocked_count": blocked_count,
            "block_rate": round(block_rate, 4),
            "top_reason": reason_rows[0]["reason"] if reason_rows else None,
            "block_reasons": reason_rows,
            "borderline_rate": snapshot.get("borderline_rate", 0.0) or 0.0,
            "suppression_policy": self._coerce_json_field(
                snapshot.get("suppression_policy_json"), {}
            ),
        }
