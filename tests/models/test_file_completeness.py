"""Tests for new File models."""

from supernote.models.file import (
    FolderFileAddDTO,
    TerminalFileUploadApplyDTO,
    TerminalFileUploadFinishDTO,
    FileQueryV2DTO,
    FileQueryV2VO,
    FileQueryByPathV2DTO,
    FileQueryByPathV2VO,
    PdfDTO,
    PdfVO,
    PngDTO,
    PngPageVO,
    PngVO,
    EntriesVO,
)


def test_folder_file_add_dto() -> None:
    dto = FolderFileAddDTO(
        file_name="NewFolder",
        file_id=123,
        directory_id=456,
        go_directory_id=789,
        is_folder="Y"
    )
    data = dto.to_dict()
    assert data["fileName"] == "NewFolder"
    assert data["fileId"] == 123
    assert data["directoryId"] == 456
    assert data["goDirectoryId"] == 789
    assert data["isFolder"] == "Y"


def test_terminal_file_upload_apply_dto() -> None:
    dto = TerminalFileUploadApplyDTO(
        file_size="1024",
        file_name="test.pdf",
        md5="md5sums",
        equipment_no="dev1",
        file_path="/data/test.pdf"
    )
    data = dto.to_dict()
    assert data["fileSize"] == "1024"
    assert data["fileName"] == "test.pdf"
    assert data["md5"] == "md5sums"
    assert data["equipmentNo"] == "dev1"
    assert data["filePath"] == "/data/test.pdf"


def test_terminal_file_upload_finish_dto() -> None:
    dto = TerminalFileUploadFinishDTO(
        file_size="1024",
        file_name="test.pdf",
        md5="md5sums",
        inner_name="inner.pdf",
        modify_time="2024-01-01",
        upload_time="2024-01-01",
        equipment_no="dev1",
        file_path="/data/test.pdf"
    )
    data = dto.to_dict()
    assert data["fileSize"] == "1024"
    assert data["fileName"] == "test.pdf"
    assert data["innerName"] == "inner.pdf"
    assert data["modifyTime"] == "2024-01-01"


def test_file_query_v2_models() -> None:
    # Test DTO
    dto = FileQueryV2DTO(id="f123", equipment_no="dev1")
    data_dto = dto.to_dict()
    assert data_dto["id"] == "f123"
    assert data_dto["equipmentNo"] == "dev1"

    # Test VO
    entry = EntriesVO(id="e1", name="entry1")
    vo = FileQueryV2VO(equipment_no="dev1", entries_vo=entry)
    data_vo = vo.to_dict()
    assert data_vo["equipmentNo"] == "dev1"
    assert data_vo["entriesVO"]["id"] == "e1"


def test_file_query_by_path_v2_models() -> None:
    dto = FileQueryByPathV2DTO(file_name="file.txt", path="/", equipment_no="dev1")
    data = dto.to_dict()
    assert data["fileName"] == "file.txt"
    assert data["path"] == "/"
    assert data["equipmentNo"] == "dev1"


def test_pdf_models() -> None:
    dto = PdfDTO(id=100, page_no_list=[1, 2, 3])
    data = dto.to_dict()
    assert data["id"] == 100
    assert data["pageNoList"] == [1, 2, 3]

    vo = PdfVO(url="http://pdf")
    assert vo.to_dict()["url"] == "http://pdf"


def test_png_models() -> None:
    dto = PngDTO(id=200)
    assert dto.to_dict()["id"] == 200

    page_vo = PngPageVO(page_no=1, url="http://png/1")
    vo = PngVO(png_page_vo_list=[page_vo])
    data = vo.to_dict()
    assert len(data["pngPageVOList"]) == 1
    assert data["pngPageVOList"][0]["pageNo"] == 1
    assert data["pngPageVOList"][0]["url"] == "http://png/1"
