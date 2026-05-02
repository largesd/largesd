# Database Migrations

The Blind Debate Adjudicator uses [Alembic](https://alembic.sqlalchemy.org/) for database schema migrations.

## Quick Start

### SQLite (development)

```bash
# Upgrade to latest schema
DATABASE_URL=sqlite:///data/debate_system.db alembic upgrade head

# Downgrade one revision
DATABASE_URL=sqlite:///data/debate_system.db alembic downgrade -1
```

### PostgreSQL (production)

```bash
# Upgrade to latest schema
DATABASE_URL=postgresql://user:pass@localhost:5432/bda_db alembic upgrade head

# Generate migration SQL without executing (dry run)
DATABASE_URL=postgresql://user:pass@localhost:5432/bda_db alembic upgrade head --sql
```

## Initial Setup (New Database)

For a fresh database, simply run:

```bash
DATABASE_URL=<your_database_url> alembic upgrade head
```

This creates all 34 tables plus the Alembic version tracking table.

## Migration from Legacy SQLite (`_ensure_column`)

If you have an existing SQLite database created by the app's runtime `_ensure_column()` patches:

1. **Back up your database:**
   ```bash
   cp data/debate_system.db data/debate_system.db.bak
   ```

2. **Stamp the database with the baseline revision:**
   ```bash
   DATABASE_URL=sqlite:///data/debate_system.db alembic stamp 0cc597040424
   ```

   This tells Alembic "this database already has the baseline schema" without running any DDL.

3. Future schema changes will use normal Alembic migrations.

## Creating New Migrations

When you need to change the schema:

```bash
# Create a new migration file
DATABASE_URL=sqlite:///data/debate_system.db alembic revision -m "add_user_roles"

# Edit the generated file in alembic/versions/
# Implement upgrade() and downgrade() using op.create_table(), op.add_column(), etc.
```

Since the project uses raw SQL (not SQLAlchemy ORM models), **autogenerate is disabled**. Write migrations manually using Alembic operations or `op.execute()` with raw SQL.

### Example: Adding a Column

```python
def upgrade() -> None:
    op.add_column('users', sa.Column('role', sa.Text(), nullable=True))

def downgrade() -> None:
    op.drop_column('users', 'role')
```

## Configuration

- **alembic.ini**: Main configuration file
- **alembic/env.py**: Environment script that reads `DATABASE_URL` from the environment
- **alembic/versions/**: Migration script directory

## Cross-Database Compatibility

Migrations are written to work with both SQLite and PostgreSQL. Dialect-specific differences (e.g., `AUTOINCREMENT` vs `SERIAL`) are handled with runtime dialect detection:

```python
dialect = op.get_bind().dialect.name
if dialect == "postgresql":
    op.execute("CREATE TABLE ... (id SERIAL PRIMARY KEY, ...)")
else:
    op.execute("CREATE TABLE ... (id INTEGER PRIMARY KEY AUTOINCREMENT, ...)")
```

## Troubleshooting

### "table already exists" error

You tried to run `alembic upgrade head` on a database that already has tables but no Alembic version stamp. Fix with:

```bash
alembic stamp 0cc597040424
```

### "No such revision" error

Make sure `alembic.ini` has the correct `script_location` and the migration files exist in `alembic/versions/`.

### Missing `psycopg2`

For PostgreSQL support:

```bash
pip install psycopg2-binary
```
