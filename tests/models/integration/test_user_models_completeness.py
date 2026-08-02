"""Tests for new User data models."""

from supernote.models.user import (
    LoginRecordDTO,
    LoginRecordVO,
    RetrievePasswordDTO,
    UpdateEmailDTO,
    UpdatePasswordDTO,
    UserCheckVO,
    UserRegisterDTO,
)


def test_user_register_dto() -> None:
    dto = UserRegisterDTO(
        email="test@example.com", password="secure_password", user_name="new_user"
    )
    assert dto.to_dict()["email"] == "test@example.com"
    assert dto.to_dict()["userName"] == "new_user"


def test_retrieve_password_dto() -> None:
    dto = RetrievePasswordDTO(
        password="new_password", email="test@example.com", country_code="86"
    )
    assert dto.to_dict()["password"] == "new_password"
    assert dto.to_dict()["countryCode"] == "86"


def test_update_password_dto() -> None:
    dto = UpdatePasswordDTO(password="updated_password")
    assert dto.to_dict()["password"] == "updated_password"


def test_update_email_dto() -> None:
    dto = UpdateEmailDTO(email="new@example.com")
    assert dto.to_dict()["email"] == "new@example.com"


def test_login_record_dto() -> None:
    dto = LoginRecordDTO(page_no="1", page_size="10", login_method="1")
    assert dto.to_dict()["pageNo"] == "1"
    assert dto.to_dict()["loginMethod"] == "1"


def test_login_record_vo() -> None:
    vo = LoginRecordVO(user_id="u123", login_method="2", ip="127.0.0.1")
    assert vo.to_dict()["userId"] == "u123"
    assert vo.to_dict()["loginMethod"] == "2"


def test_user_check_vo_extended() -> None:
    """Verify new fields in UserCheckVO."""
    vo = UserCheckVO(success=True, dms="CN", unique_machine_id="machine-123")
    assert vo.dms == "CN"
    assert vo.unique_machine_id == "machine-123"
    assert vo.to_dict()["dms"] == "CN"
