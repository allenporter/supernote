"""Tests for top-level supernote package initialization, exports, and repository structure conformance."""

from pathlib import Path

import supernote
import supernote.server.services as services_module

# Repository paths
REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT / "supernote"
TEST_ROOT = REPO_ROOT / "tests"

# Required top-level package exports for supernote/__init__.py
REQUIRED_PACKAGE_EXPORTS = {"notebook", "models"}

# Test file names globally excluded from 1:1 module path matching (package markers and pytest fixtures)
IGNORED_TEST_FILENAMES = {"__init__.py", "conftest.py"}

# Module and test naming constants for package init files
INIT_MODULE_NAME = "__init__.py"
INIT_TEST_NAME = "test_init.py"

# Directories in supernote/ excluded from requiring 1:1 test files
IGNORED_SOURCE_DIRS = {"alembic"}

# Source filenames excluded from requiring tests (e.g. auxiliary test runner harness)
IGNORED_SOURCE_FILENAMES = {"server_runner.py"}

# Source __init__.py files that have dedicated test files
PACKAGE_INIT_TESTED = {"__init__.py", "notebook/__init__.py"}

# Legacy source modules that do not yet have corresponding test files.
# As test files are added for legacy modules, remove them from this set.
ALLOWLIST_LEGACY_UNTESTED_SOURCES = {
    "client/device.py",
    "client/exceptions.py",
    "client/extended.py",
    "client/schedule.py",
    "client/socket.py",
    "client/summary.py",
    "client/web.py",
    "models/auth.py",
    "models/extended.py",
    "models/file_common.py",
    "notebook/color.py",
    "notebook/decoder.py",
    "notebook/exceptions.py",
    "notebook/fileformat.py",
    "notebook/parser.py",
    "notebook/utils.py",
    "server/constants.py",
    "server/db/base.py",
    "server/events.py",
    "server/mcp/auth.py",
    "server/mcp/models.py",
    "server/mcp/server.py",
    "server/routes/decorators.py",
    "server/routes/file_device.py",
    "server/services/gemini.py",
    "server/services/summary.py",
    "server/utils/auth_utils.py",
    "server/utils/gemini_content.py",
    "server/utils/hashing.py",
    "server/utils/note_content.py",
    "server/utils/tasks.py",
}

# Test files that do not currently follow the strict 1:1 path pattern.
# As test files are renamed or refactored to match 1:1 source module paths,
# remove them from this set.
ALLOWLIST_NON_CONFORMING_TESTS = set()


def test_package_exports():
    """Verify top-level package exports and attribute integrity for supernote."""
    assert hasattr(supernote, "__all__")
    assert REQUIRED_PACKAGE_EXPORTS.issubset(supernote.__all__)


def test_services_package_exports() -> None:
    """Verify supernote.server.services exports storage_cleanup and recycle_cleanup and does not export obsolete modules."""
    assert hasattr(services_module, "__all__")
    assert "storage_cleanup" in services_module.__all__
    assert "recycle_cleanup" in services_module.__all__
    assert "state" not in services_module.__all__
    assert "storage" not in services_module.__all__
    assert sorted(services_module.__all__) == [
        "blob",
        "coordination",
        "file",
        "recycle_cleanup",
        "storage_cleanup",
        "user",
        "vfs",
    ]


def test_all_test_files_conform_to_1to1_mapping():
    """Verify each test file in tests/ corresponds 1:1 to a source module in supernote/."""
    expected_1to1 = {
        p.relative_to(SRC_ROOT).parent
        / (INIT_TEST_NAME if p.name == INIT_MODULE_NAME else f"test_{p.name}")
        for p in SRC_ROOT.rglob("*.py")
        if not any(part.startswith(".") for part in p.parts)
    }

    non_conforming = [
        str(t.relative_to(TEST_ROOT))
        for t in TEST_ROOT.rglob("*.py")
        if not any(part.startswith(".") for part in t.parts)
        and t.name not in IGNORED_TEST_FILENAMES
        and not any(part == "integration" for part in t.relative_to(TEST_ROOT).parts)
        and t.relative_to(TEST_ROOT) not in expected_1to1
        and str(t.relative_to(TEST_ROOT)) not in ALLOWLIST_NON_CONFORMING_TESTS
    ]

    assert not non_conforming, (
        f"Found {len(non_conforming)} test file(s) that do not match the 1:1 source module structure:\n"
        + "\n".join(f"  - tests/{t}" for t in non_conforming)
        + "\n\nPlease rename/refactor the test file to match 1:1 or add it to ALLOWLIST_NON_CONFORMING_TESTS."
    )


def test_all_source_files_conform_to_1to1_mapping():
    """Verify each non-ignored source module in supernote/ has a corresponding test file in tests/."""
    missing_tests: list[str] = []

    for src_file in sorted(SRC_ROOT.rglob("*.py")):
        if any(part.startswith(".") for part in src_file.parts):
            continue
        rel = src_file.relative_to(SRC_ROOT)
        rel_str = str(rel)

        if rel.parts[0] in IGNORED_SOURCE_DIRS:
            continue
        if src_file.name in IGNORED_SOURCE_FILENAMES:
            continue
        if src_file.name == INIT_MODULE_NAME and rel_str not in PACKAGE_INIT_TESTED:
            continue
        if rel_str in ALLOWLIST_LEGACY_UNTESTED_SOURCES:
            continue

        expected_test = (
            TEST_ROOT
            / rel.parent
            / (
                INIT_TEST_NAME
                if src_file.name == INIT_MODULE_NAME
                else f"test_{src_file.name}"
            )
        )
        if not expected_test.exists():
            missing_tests.append(f"{rel_str} -> {expected_test.relative_to(TEST_ROOT)}")

    assert not missing_tests, (
        f"Found {len(missing_tests)} source module(s) missing 1:1 test files:\n"
        + "\n".join(f"  - supernote/{m}" for m in missing_tests)
        + "\n\nPlease create the corresponding test file in tests/ or add legacy modules to ALLOWLIST_LEGACY_UNTESTED_SOURCES."
    )
