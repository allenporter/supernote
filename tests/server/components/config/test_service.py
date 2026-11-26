"""Unit tests for `ConfigService` and `env > yaml > database > default` resolution."""

from __future__ import annotations

import json
import os
from collections.abc import Generator
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from supernote.models.base import TaskType
from supernote.models.config import (
    ComponentConfigSource,
    ComponentFieldSpecVO,
    ComponentFieldType,
)
from supernote.server.components import BUILTIN_COMPONENTS, BuiltinComponentSpec
from supernote.server.components.ai import (
    EMBEDDING_MODEL_KEY,
    OCR_MODEL_KEY,
    SUMMARY_MODEL_KEY,
    TEXT_MODEL_KEY,
)
from supernote.server.components.config.service import (
    _COMPONENT_CONFIG_KEY_PREFIX,
    ConfigService,
    ConfigurationConflictError,
    async_resolve_component_configs,
    async_save_component_config,
    extract_component_field_specs,
    load_component_config_schema,
)
from supernote.server.components.events import EventsComponent
from supernote.server.components.gemini.config import GeminiConfig
from supernote.server.components.processor import PROCESSOR_SERVICE_KEY
from supernote.server.components.search import SEARCH_SERVICE_KEY
from supernote.server.components.webhooks.config import WebhookConfig
from supernote.server.components.wiki.compiler import WIKI_COMPILER_KEY
from supernote.server.components.wiki.config import WikiConfig
from supernote.server.config import ServerConfig
from supernote.server.core import ComponentError, ComponentLoader, ServerCore
from supernote.server.exceptions import InvalidInputError
from supernote.server.services.coordination import CoordinationService
from tests.server.components.conftest import LoadComponents

_WEBHOOKS_SPEC = BuiltinComponentSpec(
    domain="webhooks",
    import_path="supernote.server.components.webhooks:WebhooksComponent",
    default_enabled=False,
    config_schema_path="supernote.server.components.webhooks.config:WebhookConfig",
    runtime_configurable=True,
)
_WIKI_SPEC = BuiltinComponentSpec(
    domain="wiki",
    import_path="supernote.server.components.wiki:WikiComponent",
    default_enabled=False,
    config_schema_path="supernote.server.components.wiki.config:WikiConfig",
)


@pytest.fixture(autouse=True)
def patch_server_config() -> Generator[None]:
    """Allow `ServerConfig.load` to execute real YAML and env resolution in config service tests."""
    yield


def test_load_component_config_schema_resolves_declared_schemas() -> None:
    """`load_component_config_schema` returns `None` when unset and the `DataClassDictMixin` class when set."""
    no_schema = BuiltinComponentSpec(
        domain="events",
        import_path="supernote.server.components.events:EventsComponent",
    )
    assert load_component_config_schema(no_schema) is None
    assert load_component_config_schema(_WEBHOOKS_SPEC) is WebhookConfig
    assert load_component_config_schema(_WIKI_SPEC) is WikiConfig


@pytest.mark.parametrize(
    ("schema_path", "expected_match"),
    [
        ("invalid_format", "Invalid config_schema_path"),
        (
            "supernote.server.components.webhooks.config:__all__",
            "did not resolve to a DataClassDictMixin dataclass",
        ),
        (
            "builtins:dict",
            "did not resolve to a DataClassDictMixin dataclass",
        ),
    ],
)
def test_load_component_config_schema_rejects_invalid_paths(
    schema_path: str,
    expected_match: str,
) -> None:
    """`load_component_config_schema` raises `ComponentError` for malformed paths or non-Mashumaro targets."""
    spec = BuiltinComponentSpec(
        domain="webhooks",
        import_path="supernote.server.components.webhooks:WebhooksComponent",
        config_schema_path=schema_path,
    )
    with pytest.raises(ComponentError, match=expected_match):
        load_component_config_schema(spec)


async def test_async_resolve_component_configs_default_and_database_tiers(
    tmp_path: Path,
    coordination_service: CoordinationService,
) -> None:
    """Database tier overrides default tier when neither env nor YAML is configured."""
    empty_config = ServerConfig.load(tmp_path / "empty_cfg")
    resolved_default = await async_resolve_component_configs(
        empty_config, coordination_service, specs=(_WEBHOOKS_SPEC,)
    )
    assert resolved_default["webhooks"].enabled is False
    assert resolved_default["webhooks"].source == "default"

    await async_save_component_config(
        coordination_service,
        "webhooks",
        {
            "enabled": True,
            "endpoints": [
                {
                    "url": "http://127.0.0.1:9999/db-hook",
                    "user": "test@example.com",
                    "secret": "db-secret",
                }
            ],
        },
    )
    resolved_db = await async_resolve_component_configs(
        empty_config, coordination_service, specs=(_WEBHOOKS_SPEC,)
    )
    assert resolved_db["webhooks"].enabled is True
    assert resolved_db["webhooks"].source == "database"
    assert (
        resolved_db["webhooks"].config["endpoints"][0]["url"]
        == "http://127.0.0.1:9999/db-hook"
    )


async def test_async_resolve_component_configs_yaml_and_env_override_database(
    tmp_path: Path,
    coordination_service: CoordinationService,
) -> None:
    """Explicit `config.yaml` overrides `database`, and `SUPERNOTE_*` env vars override both."""
    await async_save_component_config(
        coordination_service,
        "webhooks",
        {"enabled": True, "endpoints": []},
    )

    yaml_dir = tmp_path / "yaml_cfg"
    yaml_dir.mkdir()
    (yaml_dir / "config.yaml").write_text(
        yaml.safe_dump({"webhooks": {"enabled": False, "endpoints": []}})
    )
    yaml_config = ServerConfig.load(yaml_dir)
    resolved_yaml = await async_resolve_component_configs(
        yaml_config, coordination_service, specs=(_WEBHOOKS_SPEC,)
    )
    assert resolved_yaml["webhooks"].enabled is False
    assert resolved_yaml["webhooks"].source == "yaml"

    with patch.dict(os.environ, {"SUPERNOTE_WEBHOOKS_ENABLED": "true"}):
        env_config = ServerConfig.load(yaml_dir)
    resolved_env = await async_resolve_component_configs(
        env_config, coordination_service, specs=(_WEBHOOKS_SPEC,)
    )
    assert resolved_env["webhooks"].enabled is True
    assert resolved_env["webhooks"].source == "env"


@pytest.mark.parametrize(
    "raw_value",
    [
        "not-valid-json",
        '["not-an-object"]',
        '{"enabled": "not-a-bool"}',
        '{"enabled": true, "endpoints": [{"url": "ftp://bad", "user": "u@e.com", "secret": "s"}]}',
    ],
)
async def test_async_resolve_component_configs_ignores_invalid_db_payload(
    tmp_path: Path,
    coordination_service: CoordinationService,
    raw_value: str,
) -> None:
    """Invalid JSON, non-boolean `enabled`, or schema validation failures in DB fall back to default."""
    empty_config = ServerConfig.load(tmp_path / "empty_cfg")
    await coordination_service.set_value(
        f"{_COMPONENT_CONFIG_KEY_PREFIX}webhooks", raw_value
    )
    resolved = await async_resolve_component_configs(
        empty_config, coordination_service, specs=(_WEBHOOKS_SPEC,)
    )
    assert resolved["webhooks"].enabled is False
    assert resolved["webhooks"].source == "default"


async def test_config_service_resolve_all(
    component_core: ServerCore,
) -> None:
    """`ConfigService.resolve_all` reflects persisted database overrides."""
    service = ConfigService(
        core=component_core,
        loader=ComponentLoader(),
        specs=(_WIKI_SPEC,),
    )

    initial = await service.resolve_all()
    assert initial["wiki"].enabled is False
    assert initial["wiki"].source == "default"

    await async_save_component_config(
        component_core.coordination,
        "wiki",
        {"enabled": True, "debounce_seconds": 120},
    )
    updated = await service.resolve_all()
    assert updated["wiki"].enabled is True
    assert updated["wiki"].source == "database"
    assert updated["wiki"].config["debounce_seconds"] == 120


async def test_config_service_list_and_update_component_config(
    component_core: ServerCore,
) -> None:
    """`ConfigService.list_component_statuses` and `update_component_config` validate and persist updates."""
    loader = ComponentLoader()
    await loader.async_setup_all(component_core, {})
    await loader.async_start_all(component_core)
    service = ConfigService(
        core=component_core,
        loader=loader,
        specs=(_WIKI_SPEC, _WEBHOOKS_SPEC),
    )

    statuses = await service.list_component_statuses()
    assert [s.domain for s in statuses] == ["wiki", "webhooks"]

    updated_wiki = await service.update_component_config(
        "wiki", {"enabled": True, "debounce_seconds": 45.0}
    )
    assert updated_wiki.domain == "wiki"
    assert updated_wiki.enabled is True
    assert updated_wiki.running is False
    assert updated_wiki.restart_required is True
    assert updated_wiki.source is ComponentConfigSource.DATABASE
    assert updated_wiki.config["debounce_seconds"] == 45.0

    await loader.async_stop_all(component_core)


def test_extract_component_field_specs() -> None:
    """`extract_component_field_specs` returns typed `ComponentFieldSpecVO` descriptors."""
    fields = extract_component_field_specs(_WIKI_SPEC)
    by_name = {f.name: f for f in fields}
    assert by_name["enabled"] == ComponentFieldSpecVO(
        name="enabled",
        type=ComponentFieldType.BOOLEAN,
        default=False,
    )
    assert by_name["debounce_seconds"].type is ComponentFieldType.NUMBER
    assert by_name["max_pages_per_batch"].type is ComponentFieldType.INTEGER


async def test_config_service_protects_host_components_and_enforces_dependencies(
    component_core: ServerCore,
) -> None:
    """`ConfigService` marks protected host components read-only and blocks breaking dependency order."""
    web_ui_spec = BuiltinComponentSpec(
        domain="web_ui",
        import_path="supernote.server.components.web_ui:WebUiComponent",
        default_enabled=True,
    )
    conversion_spec = BuiltinComponentSpec(
        domain="conversion",
        import_path="supernote.server.components.conversion:ConversionComponent",
        default_enabled=True,
    )
    summary_spec = BuiltinComponentSpec(
        domain="summary",
        import_path="supernote.server.components.summary:SummaryComponent",
        default_enabled=True,
    )
    service = ConfigService(
        core=component_core,
        loader=ComponentLoader(),
        specs=(web_ui_spec, conversion_spec, summary_spec),
    )

    statuses = {s.domain: s for s in await service.list_component_statuses()}
    assert statuses["web_ui"].read_only is True
    assert statuses["conversion"].read_only is False
    assert statuses["summary"].read_only is False

    with pytest.raises(
        ConfigurationConflictError,
        match="Component 'web_ui' cannot be modified dynamically via the API",
    ):
        await service.update_component_config("web_ui", {"enabled": False})

    with pytest.raises(
        ConfigurationConflictError,
        match="Cannot disable component 'conversion' while dependent component 'summary' is enabled",
    ):
        await service.update_component_config("conversion", {"enabled": False})

    await service.update_component_config("summary", {"enabled": False})
    disabled_conversion = await service.update_component_config(
        "conversion", {"enabled": False}
    )
    assert disabled_conversion.enabled is False

    with pytest.raises(
        ConfigurationConflictError,
        match="Cannot enable component 'summary' while required dependency 'conversion' is disabled",
    ):
        await service.update_component_config("summary", {"enabled": True})


@pytest.mark.parametrize(
    ("domain", "legacy_yaml", "root_yaml"),
    [
        (
            "events",
            {"event_log_retention_days": 14},
            {"events": {"retention_days": 14}},
        ),
        (
            "metrics",
            {"metrics_enabled": False, "metrics_path": "/custom-metrics"},
            {"metrics": {"enabled": False, "path": "/custom-metrics"}},
        ),
        (
            "mcp",
            {
                "mcp_enabled": False,
                "mcp_port": 9091,
                "mcp_base_url": "https://mcp.example.com",
            },
            {
                "mcp": {
                    "enabled": False,
                    "port": 9091,
                    "base_url": "https://mcp.example.com",
                }
            },
        ),
        (
            "http",
            {"proxy_mode": "strict", "trusted_proxies": ["10.0.0.0/8"]},
            {"http": {"proxy_mode": "strict", "trusted_proxies": ["10.0.0.0/8"]}},
        ),
        (
            "conversion",
            {"web_notebook_preview": False},
            {"conversion": {"notebook_preview": False}},
        ),
        (
            "processor",
            {
                "enable_image_processing": False,
                "image_include_patterns": ["Notes/**"],
                "image_exclude_patterns": ["Archive/**"],
            },
            {
                "processor": {
                    "enable_image_processing": False,
                    "image_include_patterns": ["Notes/**"],
                    "image_exclude_patterns": ["Archive/**"],
                }
            },
        ),
        (
            "web_ui",
            {"web_enabled": False},
            {"web_ui": {"enabled": False}},
        ),
        (
            "ai",
            {"prompts_dir": "/custom/prompts"},
            {"ai": {"prompts_dir": "/custom/prompts"}},
        ),
    ],
)
async def test_legacy_and_root_yaml_resolve_identically(
    tmp_path: Path,
    coordination_service: CoordinationService,
    domain: str,
    legacy_yaml: dict[str, object],
    root_yaml: dict[str, dict[str, object]],
) -> None:
    """Every migrated component resolves `DEFAULT -> DATABASE -> YAML` and matches across legacy and root YAML."""
    empty_cfg = ServerConfig.load(tmp_path / "empty")
    default_resolved = (
        await async_resolve_component_configs(empty_cfg, coordination_service)
    )[domain]
    assert default_resolved.source == ComponentConfigSource.DEFAULT

    toggled_enabled = not default_resolved.enabled
    await async_save_component_config(
        coordination_service, domain, {"enabled": toggled_enabled}
    )
    db_resolved = (
        await async_resolve_component_configs(empty_cfg, coordination_service)
    )[domain]
    assert db_resolved.source == ComponentConfigSource.DATABASE
    assert db_resolved.enabled is toggled_enabled

    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    (legacy_dir / "config.yaml").write_text(yaml.safe_dump(legacy_yaml))
    legacy_resolved = (
        await async_resolve_component_configs(
            ServerConfig.load(legacy_dir), coordination_service
        )
    )[domain]

    root_dir = tmp_path / "root"
    root_dir.mkdir()
    (root_dir / "config.yaml").write_text(yaml.safe_dump(root_yaml))
    root_resolved = (
        await async_resolve_component_configs(
            ServerConfig.load(root_dir), coordination_service
        )
    )[domain]

    assert legacy_resolved == root_resolved
    assert root_resolved.source == ComponentConfigSource.YAML
    for key, expected_val in root_yaml[domain].items():
        assert root_resolved.config[key] == expected_val


@pytest.mark.parametrize(
    ("domain", "root_yaml", "env_vars", "expected_subset"),
    [
        (
            "events",
            {"events": {"retention_days": 14}},
            {"SUPERNOTE_EVENT_LOG_RETENTION_DAYS": "30"},
            {"retention_days": 30},
        ),
        (
            "metrics",
            {"metrics": {"enabled": False, "path": "/custom"}},
            {
                "SUPERNOTE_METRICS_ENABLED": "true",
                "SUPERNOTE_METRICS_PATH": "/env-metrics",
            },
            {"enabled": True, "path": "/env-metrics"},
        ),
        (
            "mcp",
            {"mcp": {"enabled": False, "port": 9091}},
            {
                "SUPERNOTE_MCP_ENABLED": "true",
                "SUPERNOTE_MCP_PORT": "9092",
                "SUPERNOTE_MCP_BASE_URL": "https://env-mcp.example.com",
            },
            {
                "enabled": True,
                "port": 9092,
                "base_url": "https://env-mcp.example.com",
            },
        ),
        (
            "http",
            {"http": {"proxy_mode": "strict"}},
            {
                "SUPERNOTE_PROXY_MODE": "relaxed",
                "SUPERNOTE_TRUSTED_PROXIES": "192.168.1.1,10.1.0.0/16",
            },
            {
                "proxy_mode": "relaxed",
                "trusted_proxies": ["192.168.1.1", "10.1.0.0/16"],
            },
        ),
        (
            "conversion",
            {"conversion": {"notebook_preview": False}},
            {"SUPERNOTE_WEB_NOTEBOOK_PREVIEW": "true"},
            {"notebook_preview": True},
        ),
        (
            "web_ui",
            {"web_ui": {"enabled": False}},
            {"SUPERNOTE_WEB_ENABLED": "true"},
            {"enabled": True},
        ),
        (
            "webhooks",
            {"webhooks": {"enabled": False}},
            {"SUPERNOTE_WEBHOOKS_ENABLED": "true"},
            {"enabled": True},
        ),
        (
            "wiki",
            {"wiki": {"enabled": False, "debounce_seconds": 30.0}},
            {"SUPERNOTE_WIKI_ENABLED": "true"},
            {"enabled": True},
        ),
        (
            "gemini",
            {"gemini": {"enabled": True, "api_key": "yaml-gemini-key"}},
            {"SUPERNOTE_GEMINI_API_KEY": "env-gemini-key"},
            {"api_key": "env-gemini-key"},
        ),
        (
            "ai",
            {
                "ai": {
                    "prompts_dir": "/yaml/prompts",
                    "ocr": {"provider": "gemini", "model": "gemini-2.5-flash"},
                }
            },
            {
                "SUPERNOTE_GEMINI_API_KEY": "env-gemini-key",
                "SUPERNOTE_PROMPTS_DIR": "/env/prompts",
                "SUPERNOTE_GEMINI_OCR_MODEL": "gemini-2.5-pro",
                "SUPERNOTE_GEMINI_MAX_CONCURRENCY": "9",
            },
            {
                "prompts_dir": "/env/prompts",
                "ocr": {
                    "provider": "gemini",
                    "model": "gemini-2.5-pro",
                    "max_concurrency": 9,
                },
            },
        ),
    ],
)
async def test_env_overrides_root_yaml_and_database_tiers(
    tmp_path: Path,
    coordination_service: CoordinationService,
    domain: str,
    root_yaml: dict[str, object],
    env_vars: dict[str, str],
    expected_subset: dict[str, object],
) -> None:
    """`SUPERNOTE_*` environment variables override both database and root `<domain>:` YAML tiers."""
    await async_save_component_config(coordination_service, domain, {"enabled": False})

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    yaml_dir = tmp_path / "yaml"
    yaml_dir.mkdir()
    (yaml_dir / "config.yaml").write_text(yaml.safe_dump(root_yaml))

    for cfg_dir in (empty_dir, yaml_dir):
        with patch.dict(os.environ, env_vars):
            server_cfg = ServerConfig.load(cfg_dir)
        resolved = (
            await async_resolve_component_configs(server_cfg, coordination_service)
        )[domain]
        assert resolved.source == ComponentConfigSource.ENV
        for key, expected_val in expected_subset.items():
            assert resolved.config[key] == expected_val


async def test_ai_and_provider_root_yaml_compatibility(
    tmp_path: Path,
    coordination_service: CoordinationService,
) -> None:
    """Root `gemini:`, `openai:`, and `ai:` sections in `config.yaml` resolve cleanly alongside legacy `ai.providers`."""
    root_dir = tmp_path / "ai_root_providers"
    root_dir.mkdir()
    (root_dir / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "gemini": {"enabled": True, "api_key": "root-gemini-key"},
                "openai": {
                    "enabled": True,
                    "providers": {
                        "ollama": {"base_url": "http://localhost:11434/v1"},
                    },
                },
                "ai": {
                    "enabled": False,
                    "prompts_dir": "/root/prompts",
                    "ocr": {"provider": "ollama", "model": "qwen2.5vl"},
                },
            }
        )
    )
    resolved = await async_resolve_component_configs(
        ServerConfig.load(root_dir), coordination_service
    )

    assert resolved["gemini"].enabled is True
    assert resolved["gemini"].source == ComponentConfigSource.YAML
    gemini_cfg = GeminiConfig.from_dict(resolved["gemini"].config)
    assert gemini_cfg.api_key == "root-gemini-key"
    assert gemini_cfg.providers["gemini"].api_key == "root-gemini-key"

    assert resolved["openai"].enabled is True
    assert resolved["openai"].source == ComponentConfigSource.YAML
    assert (
        resolved["openai"].config["providers"]["ollama"]["base_url"]
        == "http://localhost:11434/v1"
    )

    assert resolved["ai"].enabled is False
    assert resolved["ai"].source == ComponentConfigSource.YAML
    assert resolved["ai"].config["prompts_dir"] == "/root/prompts"
    assert resolved["ai"].config["providers"]["ollama"] == {
        "base_url": "http://localhost:11434/v1",
        "type": "openai",
    }

    with patch.dict(os.environ, {"SUPERNOTE_GEMINI_API_KEY": "env-gemini-key"}):
        env_resolved = await async_resolve_component_configs(
            ServerConfig.load(root_dir), coordination_service
        )
    assert env_resolved["gemini"].source == ComponentConfigSource.ENV
    assert env_resolved["gemini"].config["api_key"] == "env-gemini-key"


async def test_ai_per_field_static_pinning_and_role_clearing(
    tmp_path: Path,
    component_core: ServerCore,
) -> None:
    """`SUPERNOTE_GEMINI_API_KEY` pins `ai.providers` without locking `ai` model roles, and clearing roles persists."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    with patch.dict(os.environ, {"SUPERNOTE_GEMINI_API_KEY": "secret-gemini-key"}):
        core = replace(component_core, config=ServerConfig.load(empty_dir))

    loader = ComponentLoader()
    service = ConfigService(core=core, loader=loader)

    initial_statuses = {s.domain: s for s in await service.list_component_statuses()}
    ai_status = initial_statuses["ai"]
    assert ai_status.read_only is False
    assert ai_status.field_sources == {"providers": ComponentConfigSource.ENV}
    assert ai_status.config["providers"]["gemini"]["api_key"] == "***"
    assert initial_statuses["gemini"].config["api_key"] == "***"

    # Update ocr and explicitly clear embedding while providers stays ENV-pinned.
    updated = await service.update_component_config(
        "ai",
        {
            "ocr": {
                "provider": "gemini",
                "model": "gemini-2.5-pro",
                "max_concurrency": 2,
            },
            "embedding": None,
        },
    )
    assert updated.config["ocr"]["model"] == "gemini-2.5-pro"
    assert updated.config["ocr"]["max_concurrency"] == 2
    assert "embedding" not in updated.config
    assert updated.field_sources["ocr"] is ComponentConfigSource.DATABASE
    assert updated.field_sources["embedding"] is ComponentConfigSource.DATABASE
    assert updated.field_sources["providers"] is ComponentConfigSource.ENV

    # Static providers (and API keys) must never be written into SQLite.
    raw_db = await core.coordination.get_value(f"{_COMPONENT_CONFIG_KEY_PREFIX}ai")
    assert raw_db is not None
    persisted = json.loads(raw_db)
    assert "providers" not in persisted
    assert persisted["embedding"] is None
    assert persisted["ocr"]["model"] == "gemini-2.5-pro"

    # Re-resolving preserves cleared embedding instead of resurrecting legacy Gemini defaults.
    re_resolved = (await service.resolve_all())["ai"]
    assert re_resolved.config["ocr"]["model"] == "gemini-2.5-pro"
    assert "embedding" not in re_resolved.config

    # Pinning SUPERNOTE_GEMINI_OCR_MODEL locks ocr/summary while leaving text editable.
    with patch.dict(
        os.environ,
        {
            "SUPERNOTE_GEMINI_API_KEY": "secret-gemini-key",
            "SUPERNOTE_GEMINI_OCR_MODEL": "gemini-2.5-flash",
        },
    ):
        core_pinned = replace(component_core, config=ServerConfig.load(empty_dir))
    service = ConfigService(core=core_pinned, loader=loader)

    with pytest.raises(
        ConfigurationConflictError,
        match="Field 'ocr' of component 'ai' is managed by env configuration",
    ):
        await service.update_component_config(
            "ai", {"ocr": {"provider": "gemini", "model": "gemini-2.5-pro"}}
        )

    text_updated = await service.update_component_config(
        "ai", {"text": {"provider": "gemini", "model": "gemini-2.5-pro"}}
    )
    assert text_updated.config["text"]["model"] == "gemini-2.5-pro"
    assert text_updated.config["ocr"]["model"] == "gemini-2.5-flash"


async def test_secret_redaction_preserves_existing_secret_on_partial_update(
    component_core: ServerCore,
) -> None:
    """Echoing redacted `'***'` secrets back on update preserves the stored secret."""
    loader = ComponentLoader()
    loader.register(EventsComponent())
    await loader.async_setup_all(component_core, {"events": {"enabled": True}})
    await loader.async_start_all(component_core)
    service = ConfigService(core=component_core, loader=loader, specs=(_WEBHOOKS_SPEC,))

    created = await service.update_component_config(
        "webhooks",
        {
            "enabled": True,
            "endpoints": [
                {
                    "url": "http://127.0.0.1:9999/hook",
                    "user": "admin@example.com",
                    "secret": "real-hmac-secret",
                }
            ],
        },
    )
    assert created.config["endpoints"][0]["secret"] == "***"

    # Toggle enabled while echoing the redacted config back (matching Web UI behavior).
    toggled = await service.update_component_config(
        "webhooks", {**created.config, "enabled": False}
    )
    assert toggled.config["endpoints"][0]["secret"] == "***"

    resolved = (await service.resolve_all())["webhooks"]
    assert resolved.config["endpoints"][0]["secret"] == "real-hmac-secret"
    await loader.async_stop_all(component_core)


async def test_ai_live_reconfiguration_propagates_to_consumers(
    component_core: ServerCore,
    load_components: LoadComponents,
) -> None:
    """Updating `ai` roles live-updates `core.app` keys and all subscribed AI consumers."""
    selected_domains = (
        "ai",
        "fake_ai",
        "conversion",
        "events",
        "processor",
        "transcript",
        "summary",
        "search",
        "wiki",
    )
    loader = await load_components(
        *selected_domains,
        configs={"conversion": {"enabled": True, "notebook_preview": False}},
    )
    specs = tuple(s for s in BUILTIN_COMPONENTS if s.domain in selected_domains)

    processor = component_core.app[PROCESSOR_SERVICE_KEY]
    search_service = component_core.app[SEARCH_SERVICE_KEY]
    wiki_compiler = component_core.app[WIKI_COMPILER_KEY]
    modules_by_type = {m.task_type: m for m in processor.task_graph.modules}

    assert modules_by_type[TaskType.PNG_CONVERSION].enabled is False
    assert modules_by_type[TaskType.OCR_EXTRACTION].enabled is False
    assert modules_by_type[TaskType.SUMMARY_GENERATION].enabled is False
    assert modules_by_type[TaskType.EMBEDDING_GENERATION].enabled is False
    assert search_service.embedding_model is None
    assert wiki_compiler._text_model is None

    service = ConfigService(core=component_core, loader=loader, specs=specs)
    await service.update_component_config(
        "ai",
        {
            "ocr": {"provider": "fake_ai", "model": "fake-ocr-v2"},
            "summary": {"provider": "fake_ai", "model": "fake-summary-v2"},
            "embedding": {"provider": "fake_ai", "model": "fake-embed-v2"},
            "text": {"provider": "fake_ai", "model": "fake-text-v2"},
        },
    )

    ocr_model = component_core.app[OCR_MODEL_KEY]
    summary_model = component_core.app[SUMMARY_MODEL_KEY]
    embedding_model = component_core.app[EMBEDDING_MODEL_KEY]
    text_model = component_core.app[TEXT_MODEL_KEY]
    assert ocr_model is not None and ocr_model.model_id == "fake-ocr-v2"
    assert summary_model is not None and summary_model.model_id == "fake-summary-v2"
    assert embedding_model is not None and embedding_model.model_id == "fake-embed-v2"
    assert text_model is not None and text_model.model_id == "fake-text-v2"

    assert modules_by_type[TaskType.PNG_CONVERSION].enabled is True
    assert modules_by_type[TaskType.OCR_EXTRACTION].enabled is True
    assert modules_by_type[TaskType.SUMMARY_GENERATION].enabled is True
    assert modules_by_type[TaskType.EMBEDDING_GENERATION].enabled is True
    assert processor.task_graph.is_effectively_enabled(TaskType.OCR_EXTRACTION) is True
    assert search_service.embedding_model is embedding_model
    assert wiki_compiler._text_model is text_model

    # Clearing `text` falls back to `summary` live.
    await service.update_component_config("ai", {"text": None})
    fallback_text_model = component_core.app[TEXT_MODEL_KEY]
    assert (
        fallback_text_model is not None
        and fallback_text_model.model_id == "fake-summary-v2"
    )
    assert wiki_compiler._text_model is fallback_text_model

    # Invalid provider fails with 400 and leaves live models intact.
    with pytest.raises(InvalidInputError, match="Unsupported OCR model provider type"):
        await service.update_component_config(
            "ai", {"ocr": {"provider": "missing_provider", "model": "bad"}}
        )
    still_ocr = component_core.app[OCR_MODEL_KEY]
    assert still_ocr is not None and still_ocr.model_id == "fake-ocr-v2"
