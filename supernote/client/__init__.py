"""Client library for accessing Supernote Cloud services.

Example:
    async with await Supernote.login("email@example.com", "password", host="http://localhost:8080") as sn:
        # Access Web and Device APIs directly through the session object
        # Example: List root folder using path-based Device API
        result = await sn.device.list_folder("/")

        # sn.token contains the access token for use with `Supernote.from_token`
        print(sn.token)

    # Use an existing token:
    sn = Supernote.from_token("your-token", host="http://localhost:8080")
"""

from .api import Supernote
from .auth import AbstractAuth, ConstantAuth, FileCacheAuth
from .client import Client
from .login_client import LoginClient

__all__ = [
    "Supernote",
    "Client",
    "AbstractAuth",
    "ConstantAuth",
    "FileCacheAuth",
    "LoginClient",
]
