"""Snapshot test for verifying fixture database schema and content integrity using Syrupy."""

import re
import sqlite3
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent.parent.parent / "fixtures"
SQLITE_FIXTURES = sorted(FIXTURES_DIR.glob("*.sqlite"))


def normalize_sql_line(stmt: str) -> str:
    """Normalize floating point numbers and strip trailing whitespace in SQL dump lines."""

    def norm_num(m: re.Match[str]) -> str:
        val = float(m.group(0))
        return f"{val:.4f}"

    lines = stmt.splitlines()
    norm_lines = [
        re.sub(r"\b\d+\.\d+(?:e[+-]\d+)?\b", norm_num, line).rstrip() for line in lines
    ]
    return "\n".join(norm_lines)


def generate_sql_dump(db_path: Path) -> str:
    """Generate a deterministic SQL dump from a SQLite database file."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    statements = [normalize_sql_line(line) for line in conn.iterdump()]
    conn.close()
    return "\n".join(statements)


@pytest.mark.parametrize("db_path", SQLITE_FIXTURES, ids=lambda p: p.name)
def test_sqlite_fixture_matches_snapshot(db_path: Path, snapshot) -> None:
    """Verify that all fixture SQLite databases match their golden Syrupy snapshots."""
    assert db_path.exists(), f"Fixture database not found at {db_path}"
    actual_dump = generate_sql_dump(db_path)
    assert actual_dump == snapshot(name=f"{db_path.stem}_sql_dump")
