from pathlib import Path
from supernote.notebook import parse_metadata

TESTDATA = Path("tests/testdata")
NOTEBOOK_FILE = TESTDATA / "20251207_221454.note"

def test_parse_metadata() -> None:
    with NOTEBOOK_FILE.open("rb") as fd:
        notebook = parse_metadata(fd)
    data = notebook.header
    assert data["FILE_TYPE"] == "NOTE"
    assert data["APPLY_EQUIPMENT"] == "N6"
    assert data["FILE_ID"] == "F202512072214597017338I6OJBpDccy1"
