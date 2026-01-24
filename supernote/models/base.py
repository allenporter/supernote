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


class ProcessingStatus(str, BaseEnum):
    """Processing status for system tasks."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    NONE = "NONE"  # Used in view aggregation


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


class ErrorCode(str, Enum):
    """API Error Codes."""

    description: str

    def __new__(cls, code: str, message: str) -> "ErrorCode":
        obj = str.__new__(cls, code)
        obj._value_ = code
        setattr(obj, "description", message)
        return obj

    SUCCESS = ("200", "Success")
    BAD_REQUEST = ("400", "Bad Request")
    UNAUTHORIZED = ("401", "Unauthorized")
    FORBIDDEN = ("403", "Forbidden")
    NOT_FOUND = ("404", "Not Found")
    CONFLICT = ("409", "Conflict")
    INTERNAL_ERROR = ("500", "Internal Server Error")

    # Specific Error Codes from legacy system
    OPERATION_FAILED = ("E0701", "Operation failed!")
    DELETION_FAILED = ("E0702", "Deletion failed!")
    DELETE_CHILDREN_FIRST = (
        "E0703",
        "Please delete the child nodes first before deleting the current node!",
    )
    ID_EMPTY = ("E0704", "ID cannot be empty!")
    MODIFICATION_FAILED = ("E0705", "Modification failed!")
    SYSTEM_ERROR = ("E0706", "System error!")
    ROLE_DELETION_FAILED_USERS_EXIST = (
        "E0707",
        "There are still users under this role, deletion is not allowed!",
    )
    INVALID_CREDENTIALS = ("E0708", "Incorrect username or password!")
    USER_DISABLED = (
        "E0709",
        "The current user is in a disabled state. Please contact the administrator!",
    )
    USER_LOCKED = (
        "E0710",
        "The user is locked. Please contact the administrator or try logging in later!",
    )
    LOGIN_ATTEMPTS_REMAINING = (
        "E0711",
        "Incorrect username or password. Remaining login attempts",
    )
    LOGIN_EXPIRED = (
        "E0712",
        "You are not logged in or your login has expired. Please log in again!",
    )
    PASSWORD_RECENTLY_USED = (
        "E0713",
        "The password cannot be the same as the recent ones!",
    )
    ORIGINAL_PASSWORD_INCORRECT = (
        "E0714",
        "The original password entered is incorrect!",
    )
    ENABLEMENT_FAILED = ("E0715", "Enablement failed!")
    CANNOT_ENABLE_SELF = ("E0716", "A user cannot enable themselves!")
    CANNOT_DISABLE_SELF = ("E0717", "A user cannot disable themselves!")
    DISABLE_FAILED = ("E0718", "Disabling failed!")
    USER_HAS_RECORDS_CANNOT_DELETE = (
        "E0719",
        "This user already has operation records and cannot be deleted!",
    )
    CANNOT_DELETE_SELF = ("E0720", "A user cannot delete themselves!")
    ONLY_LOCKED_CAN_UNLOCK = ("E0721", "Only locked users can be unlocked!")
    USER_INFO_NOT_FOUND = ("E0722", "No information found for this user!")
    CANNOT_AUTHORIZE_SELF = ("E0723", "A user cannot authorize themselves!")
    AUTHORIZATION_FAILED = ("E0724", "Authorization failed!")
    TASK_DISABLE_FAILED = ("E0725", "Scheduled task disabling failed!")
    TASK_ENABLE_FAILED = ("E0726", "Scheduled task enabling failed!")
    TASK_RUNNING = ("E0727", "The task is running!")
    QUOTA_EXCEEDED = ("E0728", "Data cleanup exception!")
    TASK_EXECUTION_EXCEPTION = (
        "E0729",
        "Scheduled task execution exception. Please stop the task and restart it!",
    )
    DUPLICATE_BUSINESS_CODE = (
        "E0730",
        "Identical codes are not allowed under the same business code!",
    )
    PARAMETER_EXISTS = ("E0731", "The parameter already exists!")
    ALREADY_ENABLED = ("E0732", "Normal users are not allowed to be enabled again!")
    USER_ALREADY_EXISTS = ("E0733", "The user already exists!")
    ALREADY_DISABLED = ("E0734", "Disabled users are not allowed to be disabled again!")
    CANNOT_UNLOCK_SELF = ("E0735", "A user cannot unlock themselves!")
    ALL_ENABLED = (
        "E0736",
        "All data is in the enabled state. Please select a task that is not enabled!",
    )
    ALL_DISABLED = (
        "E0737",
        "All data is in the disabled state. Please select a task that is not disabled!",
    )
    ENABLE_TASK_FIRST = ("E0738", "Please enable the task first!")
    REQUEST_DATA_EMPTY = ("E0739", "The request data is empty!")
    ROLE_DELETION_FAILED_CHILDREN_EXIST = (
        "E0740",
        "Please delete all child roles under this role first!",
    )
    USER_DELETION_FAILED_CHILDREN_EXIST = (
        "E0741",
        "Please delete all child users under this user first!",
    )
    SUPERIOR_RESOURCES_MISMATCH = (
        "E0742",
        "The system does not match the superior resources!",
    )
    ACCOUNT_CANCELLED = ("E0061", "The account has been cancelled!")
    PHONE_EMPTY = ("E0062", "The phone number is empty!")
    TOO_MANY_SMS = ("E0064", "Too many SMS messages have been sent!")
    FAILED_TO_SEND_SMS = ("E0065", "Failed to send SMS!")
    INVALID_PHONE_FORMAT = ("E0066", "The phone number format is incorrect!")
    AVATAR_UPLOAD_FAILED = ("E0067", "Failed to upload the avatar!")
    COPY_LIMIT_EXCEEDED = ("E0068", "The number of copied files exceeds the limit!")
    INVALID_DEVICE = ("E0069", "The device is invalid!")
    NO_NEED_TO_UPDATE = ("E0070", "No need to update!")
    NO_COMPRESSED_PACKAGE = ("E0071", "There is no compressed package!")
    ACCESS_DENIED_SYSTEM = (
        "E0072",
        "No operations are allowed under the supernote directory!",
    )
    NICKNAME_EMPTY = ("E0073", "The nickname cannot be empty!")
    NICKNAME_EXISTS = ("E0074", "The nickname already exists. Please choose a new one!")
    DEVICE_ALREADY_BOUND = (
        "E0075",
        "The device is already bound to this account. No need to bind again!",
    )
    BINDING_ACCOUNT_MISMATCH = (
        "E0077",
        "The logged-in account is not the same as the one bound to the device!",
    )
    ANOTHER_DEVICE_SYNCING = (
        "E0078",
        "A device is currently synchronizing. Please wait until it's finished before synchronizing again!",
    )
    SYNC_IN_PROGRESS = (
        "E0079",
        "Synchronization is in progress. Please wait until it's finished before performing other operations!",
    )
    PATH_NOT_FOUND = ("E0081", "The path does not exist!")
    HASH_EXITS = (
        "E0082",
        "There is a file with the same MD5 value. No need to upload!",
    )
    DEVICE_BOUND_OTHER_ACCOUNT = (
        "E0083",
        "The device is already bound to another account. It cannot be bound to a new account!",
    )
    INVALID_VERSION_NUMBER = ("E0084", "The published version number is incorrect!")
    INVALID_TOKEN = ("E0085", "The token is invalid!")
    COUNTRY_CODE_EMPTY = ("E0086", "The country code is empty!")
    NO_LATEST_VERSION = ("E0087", "There is no latest version. No need to update.")
    RESOURCE_IN_USE_BY_ROLE = (
        "E0088",
        "This resource is already in use by a role and cannot be deleted",
    )
    CONFLICT_EXISTS = ("E0322", "File or directory already exists!")
    TIMEZONE_NOT_OBTAINED = (
        "E0844",
        "The time zone information for this area was not obtained",
    )

    @property
    def message(self) -> str:
        """Get the default message for the error code."""
        return str(getattr(self, "description", "An error occurred"))


def create_error_response(
    error_msg: str, error_code: str | ErrorCode | None = None
) -> BaseResponse:
    """Create an error response."""
    if isinstance(error_code, ErrorCode):
        error_code = error_code.value
    return BaseResponse(success=False, error_code=error_code, error_msg=error_msg)
