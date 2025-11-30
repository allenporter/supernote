#!/usr/bin/env python3
"""Cloud login debugging tool for Supernote Cloud."""

import asyncio
import logging
import sys
import os

import aiohttp

from supernote.cloud.client import Client
from supernote.cloud.login_client import LoginClient
from supernote.cloud.auth import FileCacheAuth
from supernote.cloud.cloud_client import SupernoteClient
from supernote.cloud.exceptions import SupernoteException


_LOGGER = logging.getLogger(__name__)


def setup_logging(verbose: bool = False) -> None:
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )
    # Enable debug logging for cloud modules and aiohttp
    if verbose:
        logging.getLogger("supernote.cloud").setLevel(logging.DEBUG)
        logging.getLogger("supernote.cloud.client").setLevel(logging.DEBUG)
        logging.getLogger("aiohttp").setLevel(logging.DEBUG)


async def async_cloud_login(email: str, password: str, verbose: bool = False) -> None:
    """Perform cloud login with detailed debugging output.

    Args:
        email: User email/account
        password: User password
        verbose: Enable verbose HTTP logging
    """
    setup_logging(verbose)

    print("=" * 80)
    print("Supernote Cloud Login Debugging Tool")
    print("=" * 80)
    print(f"Email: {email}")
    print(
        f"Verbose Mode: {'ENABLED' if verbose else 'DISABLED (use -v or --verbose for detailed logs)'}"
    )
    print("=" * 80)
    print()

    async with aiohttp.ClientSession() as session:
        try:
            # Step 1: Create client and login
            print("Step 1: Initializing client...")
            client = Client(session)
            login_client = LoginClient(client)

            print("Step 2: Starting login flow...")
            print("  - This will get CSRF token")
            print("  - Call token endpoint")
            print("  - Get random code")
            print("  - Encode password")
            print("  - Submit login request")
            print()

            try:
                access_token = await login_client.login(email, password)
            except SupernoteException as err:
                # Check if it's an SMS verification requirement
                # We do this by checking the exception type, but since we just added it
                # we need to make sure we import it.
                # For now, let's assume if the message contains "verification code" it is one.
                # But better to use the type.
                from supernote.cloud.exceptions import SmsVerificationRequired

                if isinstance(err, SmsVerificationRequired):
                    print()
                    print("!" * 80)
                    print("SMS Verification Required")
                    print("!" * 80)
                    print(f"Message: {err}")
                    print("The server has sent an SMS verification code to your phone.")
                    print()

                    print("Requesting SMS verification code...")
                    await login_client.request_sms_code(email)
                    print("SMS code requested successfully.")
                    print()

                    code = input("Enter verification code: ").strip()
                    print()
                    print("Submitting verification code...")

                    access_token = await login_client.sms_login(
                        email, code, err.timestamp
                    )
                else:
                    raise

            print("✓ Login successful!")
            print(
                f"Access Token: {access_token[:20]}..."
                if len(access_token) > 20
                else access_token
            )
            print()

            # Save token to cache
            cache_path = os.path.expanduser("~/.cache/supernote.pkl")
            print(f"Saving token to {cache_path}...")
            auth = FileCacheAuth(cache_path)
            auth.save_access_token(access_token)
            print("✓ Token saved!")
            print()

            # Step 2: Test basic functionality
            print("Step 3: Testing basic functionality...")
            # auth = ConstantAuth(access_token) # No longer needed as we use FileCacheAuth
            authenticated_client = Client(session, auth=auth)
            cloud_client = SupernoteClient(authenticated_client)

            # Test 1: Query user
            print("  Test 1: Querying user information...")
            try:
                user_response = await cloud_client.query_user(email)
                print("  ✓ User query successful!")
                print(f"    - User ID: {user_response.user_id}")
                print(f"    - User Name: {user_response.user_name}")
                print(f"    - Country Code: {user_response.country_code}")
                if user_response.file_server:
                    print(f"    - File Server: {user_response.file_server}")
            except SupernoteException as err:
                print(f"  ✗ User query failed: {err}")
            print()

            # Test 2: List files
            print("  Test 2: Listing files in root directory...")
            try:
                file_list_response = await cloud_client.file_list(directory_id=0)
                print("  ✓ File list successful!")
                print(f"    - Total files: {file_list_response.total}")
                print(f"    - Pages: {file_list_response.pages}")
                print(f"    - Files in this page: {file_list_response.size}")

                if file_list_response.file_list:
                    print("    - First few files:")
                    for i, file in enumerate(file_list_response.file_list[:5]):
                        folder_marker = "📁" if file.is_folder == "Y" else "📄"
                        print(f"      {folder_marker} {file.file_name} (ID: {file.id})")
                else:
                    print("    - No files found")
            except SupernoteException as err:
                print(f"  ✗ File list failed: {err}")
            print()

            print("=" * 80)
            print("All tests completed successfully!")
            print("=" * 80)

        except SupernoteException as err:
            print()
            print("=" * 80)
            print(f"✗ Error during login flow: {err}")
            print("=" * 80)
            if verbose:
                import traceback

                traceback.print_exc()
            sys.exit(1)
        except Exception as err:
            print()
            print("=" * 80)
            print(f"✗ Unexpected error: {err}")
            print("=" * 80)
            if verbose:
                import traceback

                traceback.print_exc()
            sys.exit(1)


def subcommand_cloud_login(args) -> None:
    """Handler for cloud-login subcommand.

    Args:
        args: Parsed command line arguments
    """
    asyncio.run(async_cloud_login(args.email, args.password, args.verbose))


async def async_cloud_ls(verbose: bool = False) -> None:
    """List files in Supernote Cloud using cached credentials.

    Args:
        verbose: Enable verbose logging
    """
    setup_logging(verbose)

    cache_path = os.path.expanduser("~/.cache/supernote.pkl")
    if not os.path.exists(cache_path):
        print(f"Error: No cached credentials found at {cache_path}")
        print("Please run 'supernote-tool cloud-login' first.")
        sys.exit(1)

    async with aiohttp.ClientSession() as session:
        try:
            auth = FileCacheAuth(cache_path)
            client = Client(session, auth=auth)
            cloud_client = SupernoteClient(client)

            print("Listing files in root directory...")
            file_list_response = await cloud_client.file_list()

            print(f"Total files: {file_list_response.total}")
            if file_list_response.file_list:
                for file in file_list_response.file_list:
                    folder_marker = "📁" if file.is_folder == "Y" else "📄"
                    print(f"{folder_marker} {file.file_name} (ID: {file.id})")

        except SupernoteException as err:
            print(f"Error: {err}")
            if verbose:
                import traceback

                traceback.print_exc()
            sys.exit(1)
        except Exception as err:
            print(f"Unexpected error: {err}")
            if verbose:
                import traceback

                traceback.print_exc()
            sys.exit(1)


def subcommand_cloud_ls(args) -> None:
    """Handler for cloud-ls subcommand.

    Args:
        args: Parsed command line arguments
    """
    asyncio.run(async_cloud_ls(args.verbose))
