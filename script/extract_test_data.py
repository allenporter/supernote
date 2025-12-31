import json
import os
import pathlib
import time
from typing import Any, Dict
from urllib.parse import urlparse

# Configuration
LOG_FILE = pathlib.Path("storage/system/trace.log")
OUTPUT_FILE = pathlib.Path("tests/model/testdata/extracted_requests.json")

REDACT_KEYS = {
    "equipmentNo": "test-equipment-no",
    "account": "test-account",
    "email": "test-email",
    "password": "test-password",
    "x-access-token": "ATO_DUMMY_TOKEN",
    "token": "ATO_DUMMY_TOKEN",
    "content_hash": "some-content-hash",
    "timestamp": int(time.time() * 1000),
}


def redact_data(data: Any) -> Any:
    """Recursively redact some sensitive fields in the data."""
    if isinstance(data, dict):
        new_data = {}
        for k, v in data.items():
            if k in REDACT_KEYS:
                new_data[k] = REDACT_KEYS[k]
            else:
                if isinstance(v, dict):
                    new_data[k] = redact_data(v)
                elif isinstance(v, list):
                    new_data[k] = [redact_data(item) for item in v]
                else:
                    new_data[k] = v
        return new_data
    elif isinstance(data, list):
        return [redact_data(item) for item in data]
    else:
        return data


def extract_path(url: str) -> str:
    """Extracts the path from the full URL."""
    parsed = urlparse(url)
    return parsed.path


def main():
    if not LOG_FILE.exists():
        print(f"Error: Log file not found at {LOG_FILE}")
        return

    extracted_requests: Dict[str, Any] = {}

    print(f"Reading from {LOG_FILE}...")
    with LOG_FILE.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                print(f"Skipping invalid JSON line: {line[:50]}...")
                continue

            # We are interested in POST requests usually containing interesting bodies
            if entry.get("method") != "POST":
                continue

            url = entry.get("url", "")
            path = extract_path(url)

            # Extract body
            body_str = entry.get("body")
            if not body_str:
                continue

            try:
                body_json = json.loads(body_str)
            except json.JSONDecodeError:
                # If body isn't JSON, we might skip or handle differently.
                # For now, strict JSON requirement for model testing.
                continue

            # Anonymize
            anon_body = redact_data(body_json)

            # Store unique requests by path.
            # Strategy: Keep the last one encountered to get the 'latest' structure,
            # or collect list. For simple model testing, one valid example per endpoint is a good start.
            extracted_requests[path] = {
                "method": "POST",
                "path": path,
                "body": anon_body,
            }

    # Prepare output list
    output_data = list(extracted_requests.values())

    # Ensure output dir exists
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    print(f"Writing {len(output_data)} unique requests to {OUTPUT_FILE}...")
    with OUTPUT_FILE.open("w") as f:
        json.dump(output_data, f, indent=2)


if __name__ == "__main__":
    main()
