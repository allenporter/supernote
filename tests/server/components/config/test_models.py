"""Unit tests for `supernote.server.components.config.models`."""

from __future__ import annotations

import pytest

from supernote.server.components.config.models import (
    ComponentFieldSpecVO,
    ComponentFieldType,
    ComponentListResponseVO,
    ComponentStatusResponseVO,
    ComponentStatusVO,
    UpdateComponentConfigDTO,
)
from supernote.server.config import ComponentConfigSource


@pytest.mark.parametrize(
    ("type_repr", "expected"),
    [
        ("bool", ComponentFieldType.BOOLEAN),
        ("int", ComponentFieldType.INTEGER),
        ("int | None", ComponentFieldType.INTEGER),
        ("float", ComponentFieldType.NUMBER),
        ("list[str]", ComponentFieldType.ARRAY),
        ("dict[str, Any]", ComponentFieldType.OBJECT),
        ("str", ComponentFieldType.STRING),
    ],
)
def test_component_field_type_from_type_annotation(
    type_repr: str,
    expected: ComponentFieldType,
) -> None:
    """`ComponentFieldType.from_type_annotation` maps Python type strings to UI field types."""
    assert ComponentFieldType.from_type_annotation(type_repr) is expected


def test_component_status_vo_camel_case_serialization() -> None:
    """`ComponentStatusVO` serializes camelCase aliases (`readOnly`, `runtimeConfigurable`, `restartRequired`)."""
    vo = ComponentStatusVO(
        domain="webhooks",
        enabled=True,
        running=True,
        source=ComponentConfigSource.DATABASE,
        read_only=False,
        runtime_configurable=True,
        restart_required=False,
        config={"enabled": True},
        fields=[
            ComponentFieldSpecVO(
                name="enabled",
                type=ComponentFieldType.BOOLEAN,
                default=False,
            )
        ],
    )
    expected_vo_dict = {
        "domain": "webhooks",
        "enabled": True,
        "running": True,
        "source": "database",
        "readOnly": False,
        "runtimeConfigurable": True,
        "restartRequired": False,
        "config": {"enabled": True},
        "fields": [{"name": "enabled", "type": "boolean", "default": False}],
    }
    assert vo.to_dict() == expected_vo_dict
    assert ComponentListResponseVO(components=[vo]).to_dict() == {
        "success": True,
        "components": [expected_vo_dict],
    }
    assert ComponentStatusResponseVO(component=vo).to_dict() == {
        "success": True,
        "component": expected_vo_dict,
    }


def test_update_component_config_dto_deserialization() -> None:
    """`UpdateComponentConfigDTO` parses a component configuration update payload."""
    dto = UpdateComponentConfigDTO.from_dict({"config": {"enabled": True}})
    assert dto.config == {"enabled": True}
