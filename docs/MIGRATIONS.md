# Database migrations (Alembic)

Trippy uses **Alembic** for schema changes. SQLite is the default self-hosted database (`trippy.db`).

## Commands

From the repo root (with `venv` activated):

```bash
# Apply all pending migrations
alembic upgrade head

# Create a new revision after changing models
alembic revision --autogenerate -m "describe change"

# Show current revision
alembic current

# Downgrade one step (use carefully)
alembic downgrade -1
```

## `create_all` vs Alembic

`app/main.py` still calls `models.Base.metadata.create_all(bind=engine)` on startup so a brand-new checkout can boot without running migrations. That only creates **missing** tables; it does **not** add columns to existing tables.

**After the first migration is applied, treat Alembic as the source of truth for schema changes.** Always run `alembic upgrade head` when pulling model changes. Do not rely on `create_all` to evolve an existing `trippy.db`.

## Fresh install

1. `pip install -r requirements.txt`
2. `alembic upgrade head` (creates tables via migrations)
3. Start the API (`uvicorn app.main:app --reload`)

## Existing database (pre-Alembic)

If `trippy.db` already exists from an older `create_all` run:

```bash
# Mark the baseline revision as applied without re-running CREATE TABLE
alembic stamp <baseline_revision_id>
alembic upgrade head
```

Or backup and recreate:

```bash
cp trippy.db trippy.db.bak
rm trippy.db
alembic upgrade head
```

## SQLite notes

`alembic/env.py` enables `render_as_batch=True` so column adds/renames use Alembic’s batch mode (required for many SQLite ALTERs).
