from datetime import datetime

from supernote.models.file import BooleanEnum, UserFileVO


def test_user_file_vo_datetime_parsing() -> None:
    json_data = """
    {
        "id": "123",
        "directoryId": "456",
        "fileName": "test.txt",
        "size": 100,
        "md5": "abc",
        "isFolder": "N",
        "createTime": "2023-10-27T10:00:00Z",
        "updateTime": "2023-10-27T12:00:00Z"
    }
    """
    vo = UserFileVO.from_json(json_data)
    
    assert vo.id == "123"
    assert vo.create_time is not None
    assert isinstance(vo.create_time, datetime)
    assert vo.create_time.year == 2023
    assert vo.create_time.month == 10
    
    assert vo.update_time is not None
    assert isinstance(vo.update_time, datetime)
    
    assert vo.is_folder == BooleanEnum.NO
    # inner_name matches default None
    assert vo.inner_name is None

def test_user_file_vo_optional_fields() -> None:
    # Test with minimum fields to ensure defaults work
    json_data = """
    {
        "id": "123",
        "directoryId": "456",
        "fileName": "test.txt",
        "size": 100,
        "md5": "abc"
    }
    """
    vo = UserFileVO.from_json(json_data)
    assert vo.is_folder == BooleanEnum.NO
    assert vo.create_time is None
    assert vo.update_time is None
