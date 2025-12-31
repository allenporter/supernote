import json
import pathlib
from typing import Dict, Type

import pytest

from supernote.models.auth import (
    LoginDTO,
    RandomCodeDTO,
)
from supernote.models.file import (
    CreateFolderLocalDTO,
    FileDownloadLocalDTO,
    FileQueryByPathLocalDTO,
    FileQueryLocalDTO,
    FileUploadApplyLocalDTO,
    FileUploadFinishLocalDTO,
    ListFolderV2DTO,
    SynchronousEndLocalDTO,
    SynchronousStartLocalDTO,
)
from supernote.models.user import (
    UserCheckDTO,
)

EXTRACTED_REQUESTS_PATH = pathlib.Path("tests/model/testdata/extracted_requests.json")

# Registry mapping URL paths to Model classes
MODEL_REGISTRY: Dict[str, Type] = {
    # Auth & User
    "/api/official/user/check/exists/server": UserCheckDTO,
    "/api/official/user/query/random/code": RandomCodeDTO,
    "/api/official/user/account/login/equipment": LoginDTO,
    # File / Sync
    "/api/file/2/files/synchronous/start": SynchronousStartLocalDTO,
    "/api/file/2/files/synchronous/end": SynchronousEndLocalDTO,
    "/api/file/2/files/list_folder": ListFolderV2DTO,
    "/api/file/2/files/create_folder_v2": CreateFolderLocalDTO,
    "/api/file/3/files/query/by/path_v3": FileQueryByPathLocalDTO,
    "/api/file/3/files/query_v3": FileQueryLocalDTO,
    "/api/file/3/files/upload/apply": FileUploadApplyLocalDTO,
    "/api/file/2/files/upload/finish": FileUploadFinishLocalDTO,
    "/api/file/2/files/download": FileDownloadLocalDTO,
}


def load_requests():
    """Load requests from the generated JSON file."""
    with EXTRACTED_REQUESTS_PATH.open("r") as f:
        return json.load(f)


@pytest.mark.parametrize("request_entry", load_requests(), ids=lambda x: x["path"])
def test_log_request_model(request_entry):
    """Test request parsing."""

    path = request_entry["path"]
    body = request_entry["body"]

    # Check if known path is in the request path
    model_class = MODEL_REGISTRY.get(path)

    if not model_class:
        pytest.skip(f"No model mapping found for path: {path}")

    try:
        model_class.from_dict(body)
    except Exception as e:
        pytest.fail(
            f"Failed to instantiate {model_class.__name__} for path {path} with error: {e}"
        )
