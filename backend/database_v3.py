"""
Extended database methods for v3 API
Adds user preferences and enhanced debate management
"""
import sqlite3
import json
import hashlib
import secrets
from datetime import datetime
from typing import List, Dict, Optional, Any
from backend.database import DebateDatabase
from werkzeug.security import check_password_hash


class DatabaseV3(DebateDatabase):
    """Extended database with v3 features"""
    
    def _init_tables(self):
        """Initialize tables with v3 additions"""
        super()._init_tables()
        
        conn = self._get_connection()
        cursor = conn.cursor()
        
        # User preferences table for active debate tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                preference_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                pref_key TEXT NOT NULL,
                pref_value TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, pref_key),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        
        # Add is_private column to debates if not exists
        cursor.execute("PRAGMA table_info(debates)")
        columns = {row[1] for row in cursor.fetchall()}
        if 'is_private' not in columns:
            cursor.execute("ALTER TABLE debates ADD COLUMN is_private INTEGER DEFAULT 0")
        
        # LSD §2.2: Async snapshot jobs tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS snapshot_jobs (
                job_id TEXT PRIMARY KEY,
                debate_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                progress_pct INTEGER DEFAULT 0,
                result_snapshot_id TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT
            )
        """)
        
        # LSD §20.1: Judge pool categories
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS judge_pool_categories (
                category_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                qualification_rubric TEXT NOT NULL DEFAULT '{}',
                max_judges INTEGER DEFAULT 10,
                created_at TEXT NOT NULL
            )
        """)
        
        # LSD §20.1: Judge pool members
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS judge_pool_members (
                member_id TEXT PRIMARY KEY,
                category_id TEXT NOT NULL,
                assigned_snapshot_count INTEGER DEFAULT 0,
                consecutive_snapshots INTEGER DEFAULT 0,
                cooldown_until TEXT,
                coi_topics_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            )
        """)
        
        # LSD §20.1: Judge calibration checks
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS judge_calibration_checks (
                check_id TEXT PRIMARY KEY,
                snapshot_id TEXT NOT NULL,
                consistency_score REAL,
                dispersion_distribution_json TEXT NOT NULL DEFAULT '{}',
                checked_at TEXT NOT NULL
            )
        """)
        
        conn.commit()
        conn.close()
    
    # User preference operations
    def get_user_preferences(self, user_id: str) -> Dict[str, Any]:
        """Get all preferences for a user"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT pref_key, pref_value FROM user_preferences WHERE user_id = ?",
            (user_id,)
        )
        rows = cursor.fetchall()
        conn.close()
        return {row['pref_key']: row['pref_value'] for row in rows}
    
    def get_user_preference(self, user_id: str, key: str, default=None):
        """Get a specific user preference"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT pref_value FROM user_preferences WHERE user_id = ? AND pref_key = ?",
            (user_id, key)
        )
        row = cursor.fetchone()
        conn.close()
        return row['pref_value'] if row else default
    
    def set_user_preference(self, user_id: str, key: str, value: str):
        """Set a user preference"""
        import uuid
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO user_preferences
            (preference_id, user_id, pref_key, pref_value, updated_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            str(uuid.uuid4()),
            user_id,
            key,
            value,
            datetime.now().isoformat()
        ))
        conn.commit()
        conn.close()
    
    # Enhanced debate operations
    def get_debates_by_user(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all debates created by a user"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM debates WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,)
        )
        rows = cursor.fetchall()
        
        # Add has_snapshot flag
        result = []
        for row in rows:
            debate = dict(row)
            cursor.execute(
                "SELECT COUNT(*) as count FROM snapshots WHERE debate_id = ?",
                (debate['debate_id'],)
            )
            snapshot_count = cursor.fetchone()['count']
            debate['has_snapshot'] = snapshot_count > 0
            result.append(debate)
        
        conn.close()
        return result
    
    def get_public_debates(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get public debates (not private)"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM debates WHERE is_private = 0 OR is_private IS NULL ORDER BY created_at DESC LIMIT ?",
            (limit,)
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def get_topic(self, topic_id: str, debate_id: str) -> Optional[Dict[str, Any]]:
        """Get specific topic by ID and debate"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM topics WHERE topic_id = ? AND debate_id = ?",
            (topic_id, debate_id)
        )
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    
    # Enhanced user operations with password hashing
    def create_user(self, email: str, password: str, display_name: str) -> Dict[str, Any]:
        """Create a new user with hashed password. First registered user becomes admin."""
        import uuid
        
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        password_hash = self._hash_password(password)
        created_at = datetime.now().isoformat()
        
        with self.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            count = cursor.fetchone()[0]
            is_admin = (count == 0)
            
            user_data = {
                'user_id': user_id,
                'email': email.lower().strip(),
                'password_hash': password_hash,
                'display_name': display_name.strip(),
                'created_at': created_at,
                'is_active': True,
                'is_verified': False,
                'is_admin': is_admin,
                'last_login': None
            }
            
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
        
        return user_data
    
    def verify_user(self, email: str, password: str) -> Optional[Dict[str, Any]]:
        """Verify user credentials"""
        user = self.get_user_by_email(email)
        if not user:
            return None
        
        # Check if user is active
        if not user.get('is_active', True):
            return None
        
        # Verify password
        password_hash = (user.get('password_hash') or '').strip()
        if not self._verify_password(password, password_hash):
            return None

        # Opportunistically upgrade older password hash formats on successful login.
        if self._password_hash_needs_rehash(password_hash):
            self.change_password(user['user_id'], password)
            user = self.get_user_by_id(user['user_id']) or user
        
        return user
    
    def _hash_password(self, password: str) -> str:
        """Hash password using bcrypt with a random salt."""
        import bcrypt
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('utf-8')
    
    def _verify_password(self, password: str, password_hash: str) -> bool:
        """Verify a password against current and legacy hash formats."""
        if not password_hash:
            return False

        if self._is_bcrypt_hash(password_hash):
            import bcrypt

            try:
                return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
            except ValueError:
                return False

        if self._is_legacy_werkzeug_hash(password_hash):
            try:
                return check_password_hash(password_hash, password)
            except (ValueError, TypeError):
                return False

        if self._is_legacy_sha256_hash(password_hash):
            digest = hashlib.sha256(password.encode('utf-8')).hexdigest()
            return secrets.compare_digest(password_hash.lower(), digest)

        return False

    def _password_hash_needs_rehash(self, password_hash: str) -> bool:
        """Return True when a verified password should be re-encoded with bcrypt."""
        return not self._is_bcrypt_hash(password_hash)

    def _is_bcrypt_hash(self, password_hash: str) -> bool:
        return password_hash.startswith(('$2a$', '$2b$', '$2y$'))

    def _is_legacy_werkzeug_hash(self, password_hash: str) -> bool:
        return password_hash.startswith(('scrypt:', 'pbkdf2:'))

    def _is_legacy_sha256_hash(self, password_hash: str) -> bool:
        return len(password_hash) == 64 and all(ch in '0123456789abcdefABCDEF' for ch in password_hash)
    
    def change_password(self, user_id: str, new_password: str):
        """Change user password"""
        password_hash = self._hash_password(new_password)
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET password_hash = ? WHERE user_id = ?",
            (password_hash, user_id)
        )
        conn.commit()
        conn.close()


# Backwards compatibility - Database class that includes v3 features
class Database(DatabaseV3):
    """Main database class with all features"""
    pass
