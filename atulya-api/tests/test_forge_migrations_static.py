"""Static checks for Forge migration replay safety."""

from __future__ import annotations

from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "atulya_api" / "alembic" / "versions"


def test_taste_unique_constraint_fix_has_pre_fix_schema_to_fix():
    create_migration = (MIGRATIONS_DIR / "08010cd3ef01_add_forge_taste_tables.py").read_text()
    fix_migration = (MIGRATIONS_DIR / "08010de4fa02_fix_forge_taste_set_unique.py").read_text()

    assert "UNIQUE (dataset_id, set_key)" in create_migration
    assert "UNIQUE (dataset_id, set_key, variant_index)" not in create_migration
    assert "DROP CONSTRAINT IF EXISTS forge_taste_sets_dataset_id_set_key_key" in fix_migration
    assert "UNIQUE (dataset_id, set_key, variant_index)" in fix_migration
