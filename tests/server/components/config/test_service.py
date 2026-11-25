"""Unit tests for `ConfigService` and `env > yaml > database > default` resolution."""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from supernote.server.components import BuiltinComponentSpec
from supernote.server.components.config.service import (
    _COMPONENT_CONFIG_KEY_PREFIX,
    ConfigService,
    async_resolve_component_configs,
    async_save_component_config,
    load_component_config_schema,
)
from supernote.server.components.webhooks.config import WebhookConfig
from supernote.server.components.wiki.config import WikiConfig
from supernote.server.config import ServerConfig
from supernote.server.core import ComponentError, ComponentLoader
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
    tmp_path: Path,
    coordination_service: CoordinationService,
) -> None:
    """`ConfigService.resolve_all` reflects persisted database overrides."""
    server_config = ServerConfig.load(tmp_path / "empty_cfg")
    service = ConfigService(
        server_config=server_config,
        coordination=coordination_service,
        loader=ComponentLoader(),
        specs=(_WIKI_SPEC,),
    )

    initial = await service.resolve_all()
    assert initial["wiki"].enabled is False
    assert initial["wiki"].source == "default"

    await async_save_component_config(
        coordination_service,
        "wiki",
        {"enabled": True, "debounce_seconds": 120},
    )
    updated = await service.resolve_all()
    assert updated["wiki"].enabled is True
    assert updated["wiki"].source == "database"
    assert updated["wiki"].config["debounce_seconds"] == 120
