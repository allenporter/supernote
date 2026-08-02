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
    "integration/test_live_server.py",
    "models/test_auth_completeness.py",
    "models/test_file.py",
    "models/test_file_completeness.py",
    "models/test_log_requests.py",
    "models/test_user_models_completeness.py",
    "server/db/models/test_models.py",
    "server/db/test_db_snapshot.py",
    "server/device/test_capacity.py",
    "server/device/test_clobber.py",
    "server/device/test_directory.py",
    "server/device/test_download.py",
    "server/device/test_errors.py",
    "server/device/test_file.py",
    "server/device/test_file_conversion.py",
    "server/device/test_listing.py",
    "server/device/test_move_copy.py",
    "server/device/test_query.py",
    "server/device/test_query_repro.py",
    "server/device/test_sync.py",
    "server/device/test_upload.py",
    "server/equipment/test_binding.py",
    "server/equipment/test_login.py",
    "server/mcp/test_as_discovery.py",
    "server/mcp/test_client.py",
    "server/mcp/test_oauth_flow.py",
    "server/routes/test_auth_rate_limit.py",
    "server/routes/test_oss_security.py",
    "server/routes/test_oss_upload_security.py",
    "server/routes/test_oss_upload_security_extra.py",
    "server/routes/test_system_extended.py",
    "server/services/processor_modules/test_processor_integration.py",
    "server/services/processor_modules/test_summary_module.py",
    "server/services/test_blob_integration.py",
    "server/services/test_coordination_increment.py",
    "server/services/test_processor_modules.py",
    "server/services/test_prompt_loader.py",
    "server/services/test_user_bootstrap.py",
    "server/services/test_user_password.py",
    "server/services/test_user_refactor.py",
    "server/services/test_user_token_expiration.py",
    "server/services/test_user_validation.py",
    "server/test_admin_api.py",
    "server/test_schedule_api.py",
    "server/test_trace.py",
    "server/web/test_capacity.py",
    "server/web/test_device_vs_web_structure.py",
    "server/web/test_empty_subdir.py",
    "server/web/test_listing.py",
    "server/web/test_recycle.py",
    "server/web/test_search.py",
    "server/web/test_system_directories.py",
    "server/web/test_web_parity.py",
    "server/web/test_web_upload_processing.py",
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
        and t.relative_to(TEST_ROOT) not in expected_1to1
        and str(t.relative_to(TEST_ROOT)) not in ALLOWLIST_NON_CONFORMING_TESTS
    ]

    assert not non_conforming, (
        f"Found {len(non_conforming)} test file(s) that do not match the 1:1 source module structure:\n"
        + "\n".join(f"  - tests/{t}" for t in non_conforming)
        + "\n\nPlease rename/refactor the test file to match 1:1 or add it to ALLOWLIST_NON_CONFORMING_TESTS."
    )
