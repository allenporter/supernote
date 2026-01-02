"""Module for API base classes."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Self

from mashumaro import field_options
from mashumaro.config import BaseConfig
from mashumaro.mixins.json import DataClassJSONMixin


@dataclass
class BaseResponse(DataClassJSONMixin):
    """Base response class."""

    success: bool = True
    """Whether the request was successful."""

    error_code: str | None = field(
        metadata=field_options(alias="errorCode"), default=None
    )
    """Error code."""

    error_msg: str | None = field(
        metadata=field_options(alias="errorMsg"), default=None
    )
    """Error message."""

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True


def create_error_response(
    error_msg: str, error_code: str | None = None
) -> BaseResponse:
    """Create an error response."""
    return BaseResponse(success=False, error_code=error_code, error_msg=error_msg)


class BaseEnum(Enum):
    """Base enum class."""

    @classmethod
    def from_value(cls, value: int) -> Self:
        for member in cls:
            if member.value == value:
                return member
        raise ValueError(f"Invalid {cls.__name__} value: {value}")


class BooleanEnum(str, BaseEnum):
    """Boolean enum."""

    YES = "Y"
    NO = "N"

    @classmethod
    def of(cls, value: bool) -> Self:
        return cls.YES if value else cls.NO


@dataclass
class CommonList(BaseResponse):
    """Common list response class."""

    total: int = 0
    """Total count of items."""

    pages: int = 0
    """Total pages."""

    size: int = field(metadata=field_options(alias="size"), default=20)
    """Current page size."""

    vo_list: list[Any] = field(
        metadata=field_options(alias="voList"), default_factory=list
    )
    """List of items."""

    class Config(BaseConfig):
        serialize_by_alias = True
        omit_none = True


# TODO: Add an enum with these base error code mappings and messages:
#   E0701("E0701", "Operation failed!"),
#   E0702("E0702", "Deletion failed!"),
#   E0703("E0703", "Please delete the child nodes first before deleting the current node!"),
#   E0704("E0704", "ID cannot be empty!"),
#   E0705("E0705", "Modification failed!"),
#   E0706("E0706", "System error!"),
#   E0707("E0707", "There are still users under this role, deletion is not allowed!"),
#   E0708("E0708", "Incorrect username or password!"),
#   E0709("E0709", "The current user is in a disabled state. Please contact the administrator!"),
#   E0710("E0710", "The user is locked. Please contact the administrator or try logging in later!"),
#   E0711("E0711", "Incorrect username or password. Remaining login attempts"),
#   E0712("E0712", "You are not logged in or your login has expired. Please log in again!"),
#   E0713("E0713", "The password cannot be the same as the recent ones!"),
#   E0714("E0714", "The original password entered is incorrect!"),
#   E0715("E0715", "Enablement failed!"),
#   E0716("E0716", "A user cannot enable themselves!"),
#   E0717("E0717", "A user cannot disable themselves!"),
#   E0718("E0718", "Disabling failed!"),
#   E0719("E0719", "This user already has operation records and cannot be deleted!"),
#   E0720("E0720", "A user cannot delete themselves!"),
#   E0721("E0721", "Only locked users can be unlocked!"),
#   E0722("E0722", "No information found for this user!"),
#   E0723("E0723", "A user cannot authorize themselves!"),
#   E0724("E0724", "Authorization failed!"),
#   E0725("E0725", "Scheduled task disabling failed!"),
#   E0726("E0726", "Scheduled task enabling failed!"),
#   E0727("E0727", "The task is running!"),
#   E0728("E0728", "Data cleanup exception!"),
#   E0729("E0729", "Scheduled task execution exception. Please stop the task and restart it!"),
#   E0730("E0730", "Identical codes are not allowed under the same business code!"),
#   E0731("E0731", "The parameter already exists!"),
#   E0732("E0732", "Normal users are not allowed to be enabled again!"),
#   E0733("E0733", "The user already exists!"),
#   E0734("E0734", "Disabled users are not allowed to be disabled again!"),
#   E0735("E0735", "A user cannot unlock themselves!"),
#   E0736("E0736", "All data is in the enabled state. Please select a task that is not enabled!"),
#   E0737("E0737", "All data is in the disabled state. Please select a task that is not disabled!"),
#   E0738("E0738", "Please enable the task first!"),
#   E0739("E0739", "The request data is empty!"),
#   E0740("E0740", "Please delete all child roles under this role first!"),
#   E0741("E0741", "Please delete all child users under this user first!"),
#   E0742("E0742", "The system does not match the superior resources!"),
#   E0061("E0061", "The account has been cancelled!"),
#   E0062("E0062", "The phone number is empty!"),
#   E0064("E0064", "Too many SMS messages have been sent!"),
#   E0065("E0065", "Failed to send SMS!"),
#   E0066("E0066", "The phone number format is incorrect!"),
#   E0067("E0067", "Failed to upload the avatar!"),
#   E0068("E0068", "The number of copied files exceeds the limit!"),
#   E0069("E0069", "The device is invalid!"),
#   E0070("E0070", "No need to update!"),
#   E0071("E0071", "There is no compressed package!"),
#   E0072("E0072", "No operations are allowed under the supernote directory!"),
#   E0073("E0073", "The nickname cannot be empty!"),
#   E0074("E0074", "The nickname already exists. Please choose a new one!"),
#   E0075("E0075", "The device is already bound to this account. No need to bind again!"),
#   E0077("E0077", "The logged-in account is not the same as the one bound to the device!"),
#   E0078("E0078", "A device is currently synchronizing. Please wait until it's finished before synchronizing again!"),
#   E0079("E0079", "Synchronization is in progress. Please wait until it's finished before performing other operations!"),
#   E0081("E0081", "The path does not exist!"),
#   E0082("E0082", "There is a file with the same MD5 value. No need to upload!"),
#   E0083("E0083", "The device is already bound to another account. It cannot be bound to a new account!"),
#   E0084("E0084", "The published version number is incorrect!"),
#   E0085("E0085", "The token is invalid!"),
#   E0086("E0086", "The country code is empty!"),
#   E0087("E0087", "There is no latest version. No need to update."),
#   E0088("E0088", "This resource is already in use by a role and cannot be deleted"),
#   E0844("E0844", "The time zone information for this area was not obtained")
