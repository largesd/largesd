"""
Baseline schema for LSD v1.2

Creates all tables required by the Blind Debate Adjudicator backend.
Compatible with SQLite and PostgreSQL.

Revision ID: 0cc597040424
Revises:
Create Date: 2026-04-30
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0cc597040424"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _dialect() -> str:
    """Return the current SQLAlchemy dialect name."""
    bind = op.get_bind()
    return bind.dialect.name


def _exec(sql: str) -> None:
    """Execute raw SQL, stripping inline comments for cross-dialect safety."""
    # Remove SQLite-style inline comments
    cleaned = "\n".join(line.split("--")[0] for line in sql.splitlines())
    op.execute(cleaned)


def upgrade() -> None:
    dialect = _dialect()

    # ------------------------------------------------------------------
    # users
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE users (
            user_id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            is_verified INTEGER DEFAULT 0,
            last_login TEXT
        );
        """
    )

    # ------------------------------------------------------------------
    # user_sessions
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE user_sessions (
            session_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            token TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );
        """
    )

    # ------------------------------------------------------------------
    # user_preferences
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE user_preferences (
            preference_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            pref_key TEXT NOT NULL,
            pref_value TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, pref_key),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );
        """
    )

    # ------------------------------------------------------------------
    # debates
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE debates (
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
            is_private INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );
        """
    )

    # ------------------------------------------------------------------
    # debate_frames
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE debate_frames (
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
            frame_mode TEXT DEFAULT 'single',
            review_date TEXT,
            review_cadence_months INTEGER DEFAULT 6,
            emergency_override_reason TEXT,
            emergency_override_by TEXT,
            governance_decision_id TEXT,
            FOREIGN KEY (debate_id) REFERENCES debates(debate_id),
            UNIQUE (debate_id, version)
        );
        """
    )

    # ------------------------------------------------------------------
    # posts
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE posts (
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
            submission_id TEXT,
            FOREIGN KEY (debate_id) REFERENCES debates(debate_id),
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );
        """
    )

    # ------------------------------------------------------------------
    # spans
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE spans (
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
        );
        """
    )

    # ------------------------------------------------------------------
    # topics
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE topics (
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
        );
        """
    )

    # ------------------------------------------------------------------
    # facts
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE facts (
            fact_id TEXT PRIMARY KEY,
            debate_id TEXT NOT NULL,
            topic_id TEXT NOT NULL,
            side TEXT NOT NULL,
            fact_text TEXT NOT NULL,
            p_true REAL DEFAULT 0.5,
            provenance_links TEXT,
            created_at TEXT NOT NULL,
            fact_type TEXT DEFAULT 'empirical',
            normative_provenance TEXT,
            operationalization TEXT,
            FOREIGN KEY (debate_id) REFERENCES debates(debate_id),
            FOREIGN KEY (topic_id) REFERENCES topics(topic_id)
        );
        """
    )

    # ------------------------------------------------------------------
    # canonical_facts
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE canonical_facts (
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
            fact_type TEXT DEFAULT 'empirical',
            normative_provenance TEXT,
            operationalization TEXT,
            evidence_tier_counts_json TEXT,
            FOREIGN KEY (debate_id) REFERENCES debates(debate_id)
        );
        """
    )

    # ------------------------------------------------------------------
    # arguments
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE arguments (
            arg_id TEXT PRIMARY KEY,
            debate_id TEXT NOT NULL,
            topic_id TEXT NOT NULL,
            side TEXT NOT NULL,
            inference_text TEXT NOT NULL,
            supporting_facts TEXT,
            provenance_links TEXT,
            created_at TEXT NOT NULL,
            completeness_proxy REAL DEFAULT 0.0,
            FOREIGN KEY (debate_id) REFERENCES debates(debate_id)
        );
        """
    )

    # ------------------------------------------------------------------
    # canonical_arguments
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE canonical_arguments (
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
            completeness_proxy REAL DEFAULT 0.0,
            FOREIGN KEY (debate_id) REFERENCES debates(debate_id)
        );
        """
    )

    # ------------------------------------------------------------------
    # snapshots
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE snapshots (
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
            replay_manifest_json TEXT,
            input_hash_root TEXT,
            output_hash_root TEXT,
            recipe_versions_json TEXT,
            FOREIGN KEY (debate_id) REFERENCES debates(debate_id)
        );
        """
    )

    # ------------------------------------------------------------------
    # audit_records
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE audit_records (
            audit_id TEXT PRIMARY KEY,
            snapshot_id TEXT NOT NULL,
            audit_type TEXT NOT NULL,
            result_data TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (snapshot_id) REFERENCES snapshots(snapshot_id)
        );
        """
    )

    # ------------------------------------------------------------------
    # failed_publishes (dialect-sensitive: AUTOINCREMENT vs SERIAL)
    # ------------------------------------------------------------------
    if dialect == "postgresql":
        _exec(
            """
            CREATE TABLE failed_publishes (
                id SERIAL PRIMARY KEY,
                debate_id TEXT NOT NULL,
                snapshot_id TEXT,
                payload_json TEXT NOT NULL,
                commit_message TEXT NOT NULL,
                retry_count INTEGER DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL,
                next_retry_at TEXT
            );
            """
        )
    else:
        _exec(
            """
            CREATE TABLE failed_publishes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                debate_id TEXT NOT NULL,
                snapshot_id TEXT,
                payload_json TEXT NOT NULL,
                commit_message TEXT NOT NULL,
                retry_count INTEGER DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL,
                next_retry_at TEXT
            );
            """
        )

    # ------------------------------------------------------------------
    # moderation_templates
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE moderation_templates (
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
        );
        """
    )

    # ------------------------------------------------------------------
    # moderation_template_state
    # ------------------------------------------------------------------
    if dialect == "postgresql":
        _exec(
            """
            CREATE TABLE moderation_template_state (
                state_id INTEGER PRIMARY KEY CHECK (state_id = 1),
                active_template_record_id TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (active_template_record_id) REFERENCES moderation_templates(template_record_id)
            );
            """
        )
    else:
        # SQLite allows CHECK constraints on PRIMARY KEY
        _exec(
            """
            CREATE TABLE moderation_template_state (
                state_id INTEGER PRIMARY KEY CHECK (state_id = 1),
                active_template_record_id TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (active_template_record_id) REFERENCES moderation_templates(template_record_id)
            );
            """
        )

    # ------------------------------------------------------------------
    # frame_petitions
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE frame_petitions (
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
        );
        """
    )

    # ------------------------------------------------------------------
    # debate_proposals
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE debate_proposals (
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
        );
        """
    )

    # ------------------------------------------------------------------
    # snapshot_jobs
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE snapshot_jobs (
            job_id TEXT PRIMARY KEY,
            debate_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            progress_pct INTEGER DEFAULT 0,
            result_snapshot_id TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT
        );
        """
    )

    # ------------------------------------------------------------------
    # jobs (async worker queue)
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE jobs (
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
        );
        """
    )

    # ------------------------------------------------------------------
    # judge_pool_categories
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE judge_pool_categories (
            category_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            qualification_rubric TEXT NOT NULL DEFAULT '{}',
            max_judges INTEGER DEFAULT 10,
            created_at TEXT NOT NULL
        );
        """
    )

    # ------------------------------------------------------------------
    # judge_pool_members
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE judge_pool_members (
            member_id TEXT PRIMARY KEY,
            category_id TEXT NOT NULL,
            assigned_snapshot_count INTEGER DEFAULT 0,
            consecutive_snapshots INTEGER DEFAULT 0,
            cooldown_until TEXT,
            coi_topics_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL
        );
        """
    )

    # ------------------------------------------------------------------
    # judge_calibration_checks
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE judge_calibration_checks (
            check_id TEXT PRIMARY KEY,
            snapshot_id TEXT NOT NULL,
            consistency_score REAL,
            dispersion_distribution_json TEXT NOT NULL DEFAULT '{}',
            checked_at TEXT NOT NULL
        );
        """
    )

    # ------------------------------------------------------------------
    # changelog (governance)
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE changelog (
            entry_id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            change_type TEXT NOT NULL,
            description TEXT NOT NULL,
            previous_value TEXT,
            new_value TEXT,
            justification TEXT NOT NULL,
            changed_by TEXT NOT NULL,
            approval_references TEXT
        );
        """
    )

    # ------------------------------------------------------------------
    # appeals (governance)
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE appeals (
            appeal_id TEXT PRIMARY KEY,
            debate_id TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            claimant_id TEXT NOT NULL,
            grounds TEXT NOT NULL,
            evidence_references TEXT,
            requested_relief TEXT NOT NULL,
            status TEXT NOT NULL,
            submitted_at TEXT NOT NULL,
            reviewed_at TEXT,
            reviewer_id TEXT,
            decision_reason TEXT,
            resolution TEXT
        );
        """
    )

    # ------------------------------------------------------------------
    # judge_pool (governance)
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE judge_pool (
            judge_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            appointed_at TEXT NOT NULL,
            term_expires TEXT,
            decisions_count INTEGER DEFAULT 0,
            overturned_count INTEGER DEFAULT 0,
            accuracy_score REAL DEFAULT 0.5,
            bias_audits TEXT,
            recusals TEXT,
            specialties TEXT
        );
        """
    )

    # ------------------------------------------------------------------
    # incidents (governance)
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE incidents (
            incident_id TEXT PRIMARY KEY,
            severity TEXT NOT NULL,
            reported_at TEXT NOT NULL,
            reported_by TEXT NOT NULL,
            description TEXT NOT NULL,
            affected_debates TEXT,
            trigger_snapshot_ids TEXT,
            additive_snapshot_id TEXT,
            status TEXT NOT NULL,
            resolution_notes TEXT,
            snapshot_id TEXT,
            affected_outputs_json TEXT,
            remediation_plan TEXT,
            created_at TEXT,
            resolved_at TEXT
        );
        """
    )

    # ------------------------------------------------------------------
    # fairness_audits (governance)
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE fairness_audits (
            audit_id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            metric_name TEXT NOT NULL,
            metric_value REAL NOT NULL,
            demographic_slice TEXT,
            benchmark_value REAL,
            status TEXT,
            details TEXT
        );
        """
    )

    # ------------------------------------------------------------------
    # judge_pool_composition (governance)
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE judge_pool_composition (
            composition_id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            category TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            qualification_rubric TEXT NOT NULL DEFAULT '{}',
            snapshot_id TEXT
        );
        """
    )

    # ------------------------------------------------------------------
    # judge_rotation_policy (governance)
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE judge_rotation_policy (
            policy_id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            max_consecutive_snapshots INTEGER NOT NULL DEFAULT 5,
            cooldown_snapshots INTEGER NOT NULL DEFAULT 2,
            active INTEGER NOT NULL DEFAULT 1
        );
        """
    )

    # ------------------------------------------------------------------
    # conflict_of_interest_log (governance)
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE conflict_of_interest_log (
            entry_id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            judge_id TEXT NOT NULL,
            debate_id TEXT,
            topic_id TEXT,
            conflict_type TEXT NOT NULL,
            description TEXT NOT NULL,
            resolved INTEGER NOT NULL DEFAULT 0
        );
        """
    )

    # ------------------------------------------------------------------
    # calibration_protocol (governance)
    # ------------------------------------------------------------------
    _exec(
        """
        CREATE TABLE calibration_protocol (
            protocol_id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            guideline_version TEXT NOT NULL,
            shared_guidelines TEXT NOT NULL DEFAULT '{}',
            inter_judge_consistency_check TEXT NOT NULL DEFAULT '{}',
            active INTEGER NOT NULL DEFAULT 1
        );
        """
    )

    # ------------------------------------------------------------------
    # Indexes
    # ------------------------------------------------------------------
    _exec("CREATE INDEX idx_frame_petitions_debate ON frame_petitions(debate_id);")
    _exec("CREATE INDEX idx_frame_petitions_status ON frame_petitions(status);")
    _exec("CREATE INDEX idx_proposals_created ON debate_proposals(created_at);")
    _exec("CREATE INDEX idx_proposals_proposer ON debate_proposals(proposer_user_id);")
    _exec("CREATE INDEX idx_proposals_status ON debate_proposals(status);")


def downgrade() -> None:
    """Drop all tables in reverse dependency order."""
    tables = [
        "audit_records",
        "spans",
        "posts",
        "canonical_arguments",
        "canonical_facts",
        "arguments",
        "facts",
        "topics",
        "snapshots",
        "failed_publishes",
        "frame_petitions",
        "debate_proposals",
        "debate_frames",
        "moderation_template_state",
        "moderation_templates",
        "snapshot_jobs",
        "jobs",
        "judge_calibration_checks",
        "judge_pool_members",
        "judge_pool_categories",
        "user_preferences",
        "user_sessions",
        "users",
        "debates",
        "changelog",
        "appeals",
        "judge_pool",
        "incidents",
        "fairness_audits",
        "judge_pool_composition",
        "judge_rotation_policy",
        "conflict_of_interest_log",
        "calibration_protocol",
    ]
    for table in tables:
        op.execute(f"DROP TABLE IF EXISTS {table};")
