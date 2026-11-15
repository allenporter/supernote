#!/usr/bin/env python3
"""SessionStart hook that refreshes origin/main and warns if HEAD is behind."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _read_cwd() -> str:
    default_cwd = str(Path(__file__).resolve().parents[2])
    raw = sys.stdin.read().strip()
    if not raw:
        return default_cwd
    payload: object = json.loads(raw)
    if isinstance(payload, dict):
        cwd = payload.get("cwd")
        if isinstance(cwd, str) and cwd:
            return cwd
    return default_cwd


def _check_freshness(cwd: str) -> dict[str, object]:
    fetch_ff = subprocess.run(
        ["git", "-C", cwd, "fetch", "origin", "main:main", "--quiet"],
        capture_output=True,
        text=True,
        timeout=6,
        check=False,
    )
    if fetch_ff.returncode != 0:
        subprocess.run(
            ["git", "-C", cwd, "fetch", "origin", "main", "--quiet"],
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
        )

    rev_res = subprocess.run(
        ["git", "-C", cwd, "rev-list", "--count", "HEAD..origin/main"],
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )
    if rev_res.returncode != 0:
        return {}

    behind = int(rev_res.stdout.strip() or "0")
    if behind <= 0:
        return {}

    notice = (
        f"Workspace git notice: HEAD is {behind} commit(s) behind origin/main "
        "(local main has been fetched). If starting new work in a fresh worktree, "
        "sync or branch from origin/main first; if resuming in-progress branch "
        "commits, preserve them unless rebasing is requested."
    )
    return {"injectSteps": [{"systemMessage": {"systemMessage": notice}}]}


def main() -> None:
    """Emit a SessionStart injectSteps notice if the workspace lags origin/main."""
    try:
        output = _check_freshness(_read_cwd())
    except (OSError, subprocess.SubprocessError, ValueError):
        output = {}
    print(json.dumps(output))


if __name__ == "__main__":
    main()
