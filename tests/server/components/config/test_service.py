"""Unit tests for `ConfigService` and `env > yaml > database > default` resolution."""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from supernote.server.components import BuiltinComponentSpec
from supernote.server.components.config.models import (
    ComponentFieldSpecVO,
    ComponentFieldType,
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
from supernote.server.components.webhooks.config import WebhookConfig
from supernote.server.components.wiki.config import WikiConfig
from supernote.server.config import ComponentConfigSource, ServerConfig
from supernote.server.core import ComponentError, ComponentLoader, ServerCore
from supernote.server.services.coordination import CoordinationService

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
