"""Tests for top-level supernote package initialization, exports, and repository structure conformance."""

from pathlib import Path

import supernote

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

# Test files that do not currently follow the strict 1:1 path pattern.
# As test files are renamed or refactored to match 1:1 source module paths,
# remove them from this set.
ALLOWLIST_NON_CONFORMING_TESTS = {
    "client/test_login.py",
    "models/test_file.py",
    "server/routes/test_system_extended.py",
}


def test_package_exports():
    """Verify top-level package exports and attribute integrity for supernote."""
    assert hasattr(supernote, "__all__")
    assert REQUIRED_PACKAGE_EXPORTS.issubset(supernote.__all__)


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
