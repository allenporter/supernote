"""Script to help correlate openapi.yaml and models.

This script helps to dump the openapi.yaml file and models directory
in a way that groups the API paths and the data models used all together.

The motivation is that in pydoc we'd like to document the data objects,
so we need to know which data models are used in which API paths so we can
give an explanation.
"""

import pathlib
from typing import Any

import yaml

OPENAPI_API_PATH = pathlib.Path("api-spec/openapi.yaml")
SPEC_PATH = pathlib.Path("api-spec")


def get_ref_name(ref: str) -> str | None:
    if not ref:
        return None
    return ref.split("/")[-1]


def get_schema_from_content(content: dict[str, Any]) -> str | None:
    if not content:
        return None
    json_content = content.get("application/json", {})
    schema = json_content.get("schema", {})
    if "allOf" in schema:
        # Usually the last one is the specific VO
        return get_ref_name(schema["allOf"][-1].get("$ref"))
    return get_ref_name(schema.get("$ref"))


def main() -> None:
    if not OPENAPI_API_PATH.exists():
        print(f"Error: {OPENAPI_API_PATH} not found.")
        return

    openapi_content = OPENAPI_API_PATH.read_text()
    openapi_dict = yaml.safe_load(openapi_content)

    results: dict[str, list[dict[str, Any]]] = {}  # tag -> list of items

    for path, path_item in openapi_dict.get("paths", {}).items():
        ref = path_item.get("$ref")
        if not ref:
            # Handle inline paths if any
            path_data = path_item
            current_file = OPENAPI_API_PATH
        else:
            file_path, fragment = ref.split("#")
            current_file = (SPEC_PATH / file_path).resolve()

            if not current_file.exists():
                print(f"File not found: {current_file}")
                continue

            with open(current_file) as f:
                file_data = yaml.safe_load(f)

            fragment_key = fragment.lstrip("/")
            path_data = file_data.get(fragment_key)

        if not path_data:
            print(f"Path data not found for {path}")
            continue

        for method, operation in path_data.items():
            if method not in ["get", "post", "put", "delete", "patch"]:
                continue

            tags = operation.get("tags", ["Untagged"])
            tag = tags[0]

            request_vo = get_schema_from_content(
                operation.get("requestBody", {}).get("content")
            )

            response_vo = None
            if "responses" in operation:
                resp_200 = operation["responses"].get(
                    "200", operation["responses"].get("default", {})
                )
                response_vo = get_schema_from_content(resp_200.get("content"))

            if tag not in results:
                results[tag] = []

            results[tag].append(
                {
                    "path": path,
                    "method": method.upper(),
                    "request": request_vo,
                    "response": response_vo,
                }
            )

    for tag in sorted(results.keys()):
        print(f"\n{tag}")
        for item in sorted(results[tag], key=lambda x: x["path"]):
            print(f"{item['path']} ({item['method']}):")
            if item["request"]:
                print(f"  Request: {item['request']}")
            if item["response"]:
                print(f"  Response: {item['response']}")


if __name__ == "__main__":
    main()
