
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
        "createTime": "176722962336",
        "updateTime": "176722963237"
    }
    """
    vo = UserFileVO.from_json(json_data)
    
    assert vo.id == "123"
    assert vo.create_time == 176722962336
    assert vo.update_time == 176722963237

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
