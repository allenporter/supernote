"""Sanity tests for user models to catch import and serialization errors."""

from supernote.models.user import (
    UserCheckDTO,
    UserCheckVO,
    UserQueryByIdVO,
    UserQueryVO,
    UserVO,
)


def test_user_check_serialization() -> None:
    """Test basic serialization of UserCheckVO."""
    data = {
        "success": True,
        "dms": "US",
        "userId": 456,
        "uniqueMachineId": "machine-123",
    }
    vo = UserCheckVO.from_dict(data)
    assert vo.dms == "US"
    assert vo.user_id == 456

    dumped = vo.to_dict()
    assert dumped["dms"] == "US"
    assert dumped["userId"] == 456


def test_user_vo_serialization() -> None:
    """Test basic serialization of UserVO."""
    data = {"userId": "123", "userName": "testuser", "wechatNo": "wx123"}
    vo = UserVO.from_dict(data)
    assert vo.user_id == "123"
    assert vo.wechat_no == "wx123"


def test_user_query_vo_serialization() -> None:
    """Test UserQueryVO with nested UserInfo."""
    data = {
        "success": True,
        "user": {"userId": 789, "userName": "queryuser", "phone": "555-1234"},
        "isUser": True,
        "equipmentNo": "eq-999",
    }
    vo = UserQueryVO.from_dict(data)
    assert vo.user
    assert vo.user.user_id == 789
    assert vo.is_user is True


def test_user_query_by_id_vo_serialization() -> None:
    """Test flattened UserQueryByIdVO."""
    data = {
        "success": True,
        "userId": 101,
        "userName": "flatuser",
        "totalCapacity": "10GB",
    }
    vo = UserQueryByIdVO.from_dict(data)
    assert vo.user_id == 101
    assert vo.total_capacity == "10GB"


def test_user_check_dto_serialization() -> None:
    """Test UserCheckDTO."""
    data = {"countryCode": "1", "userName": "test"}
    dto = UserCheckDTO.from_dict(data)
    assert dto.country_code == "1"
    assert dto.user_name == "test"
