#!/usr/bin/env python3
"""Seed script for populating development server with notes, documents, and schedule tasks."""

import asyncio
from pathlib import Path

from supernote.client import Supernote
from supernote.client.admin import AdminClient
from supernote.client.exceptions import ApiException
from supernote.client.schedule import ScheduleClient

SERVER_URL = "http://127.0.0.1:8080"
EMAIL = "debug@example.com"
PASSWORD = "password"


async def seed():
    print(f"==> Connecting to server at {SERVER_URL}...")

    # Ensure user exists by attempting login or registration via AdminClient
    try:
        sn = await Supernote.login(EMAIL, PASSWORD, host=SERVER_URL)
    except ApiException:
        print(f"User {EMAIL} not found or invalid password, attempting registration...")
        import aiohttp  # noqa: PLC0415

        async with aiohttp.ClientSession() as session:
            admin_client = AdminClient(session, host=SERVER_URL)  # type: ignore[arg-type]
            await admin_client.register(EMAIL, PASSWORD, "Debug User")
        sn = await Supernote.login(EMAIL, PASSWORD, host=SERVER_URL)

    async with sn:
        print(f"✓ Logged in as {EMAIL}")

        schedule = ScheduleClient(sn.client)

        print("\n--- Creating Task Groups & Schedule Tasks ---")

        # Group 1: Work & Projects
        g1 = await schedule.create_group("Work & Projects")
        g1_id = int(g1.task_list_id)  # type: ignore[arg-type]
        print(f"Created Group: Work & Projects (id={g1_id})")

        await schedule.create_task(
            g1_id,
            "Finalize Q3 Supernote Architecture Proposal",
            detail="Review VFS layer and MCP server integration.",
            status="needsAction",
            importance="high",
        )
        print("  - Task: Finalize Q3 Supernote Architecture Proposal")

        await schedule.create_task(
            g1_id,
            "Deploy Partner App Integration",
            detail="Verify OAuth & API sync flows against server",
            status="needsAction",
            importance="high",
        )
        print("  - Task: Deploy Partner App Integration")

        await schedule.create_task(
            g1_id,
            "Setup CI/CD Pipeline for Supernote",
            detail="Automate ruff, mypy and pytest runs on PR",
            status="completed",
            importance="normal",
        )
        print("  - Task: Setup CI/CD Pipeline (Completed)")

        await schedule.create_task(
            g1_id,
            "Update OpenAPI Specs for Task Schedule V2",
            detail="Document links and sort fields",
            status="needsAction",
            importance="normal",
        )
        print("  - Task: Update OpenAPI Specs for Task Schedule V2")

        # Group 2: Personal & Notes
        g2 = await schedule.create_group("Personal & Notes")
        g2_id = int(g2.task_list_id)  # type: ignore[arg-type]
        print(f"Created Group: Personal & Notes (id={g2_id})")

        await schedule.create_task(
            g2_id,
            "Buy Stylus Replacement Nibs",
            detail="Check Supernote store for FeelWrite 2 nibs",
            status="needsAction",
            importance="normal",
        )
        print("  - Task: Buy Stylus Replacement Nibs")

        await schedule.create_task(
            g2_id,
            "Organize Travel Notes",
            detail="Export Kyoto trip notes to PDF and archive",
            status="completed",
            importance="low",
        )
        print("  - Task: Organize Travel Notes (Completed)")

        await schedule.create_task(
            g2_id,
            "Weekly Journal Review",
            detail="Review handwritten notes from last week",
            status="needsAction",
            importance="high",
        )
        print("  - Task: Weekly Journal Review")

        # Group 3: Supernote Roadmap & Ideas
        g3 = await schedule.create_group("Supernote Roadmap & Ideas")
        g3_id = int(g3.task_list_id)  # type: ignore[arg-type]
        print(f"Created Group: Supernote Roadmap & Ideas (id={g3_id})")

        await schedule.create_task(
            g3_id,
            "Implement Vector Search for Hand-written OCR",
            detail="Explore Gemini embedding integration with MCP server",
            status="needsAction",
            importance="high",
        )
        print("  - Task: Implement Vector Search for Hand-written OCR")

        await schedule.create_task(
            g3_id,
            "Support Canvas Layering in Exporter",
            detail="Support vector drawing layers and png backgrounds",
            status="needsAction",
            importance="normal",
        )
        print("  - Task: Support Canvas Layering in Exporter")

        await schedule.create_task(
            g3_id,
            "Fix Page Hashing Cache Invalidation",
            detail="Cache key should incorporate modified timestamp",
            status="completed",
            importance="normal",
        )
        print("  - Task: Fix Page Hashing Cache Invalidation (Completed)")

        print("\n--- Creating Cloud Directories & Uploading Files ---")

        # Standard Supernote Device & Web Directory Structure
        folders = [
            "/NOTE",
            "/NOTE/Note",
            "/NOTE/MyStyle",
            "/DOCUMENT",
            "/DOCUMENT/Document",
            "/EXPORT",
            "/SCREENSHOT",
            "/INBOX",
        ]
        for folder in folders:
            try:
                await sn.device.create_folder(folder, equipment_no="WEB")
                print(f"Created folder: {folder}")
            except Exception:
                pass

        test_notes = [
            ("tests/testdata/20251207_221454.note", "/NOTE/Note/20251207_221454.note"),
            ("tests/testdata/philips/test.note", "/NOTE/Note/Meeting_Notes.note"),
            ("tests/testdata/philips/manta.note", "/NOTE/Note/Project_Ideas.note"),
            (
                "tests/testdata/dsummersl/sn2md_20260618.note",
                "/NOTE/Note/Weekly_Journal.note",
            ),
            (
                "tests/testdata/mmujynya/stroller.note",
                "/DOCUMENT/Document/Stroller_Specs.note",
            ),
            (
                "tests/testdata/philips/horizontal_1090.note",
                "/DOCUMENT/Document/Horizontal_Diagram.note",
            ),
        ]

        for local_file, remote_path in test_notes:
            path_obj = Path(local_file)
            if path_obj.exists():
                content = path_obj.read_bytes()
                print(
                    f"Uploading {local_file} -> {remote_path} ({len(content)} bytes)..."
                )
                await sn.device.upload_content(remote_path, content, equipment_no="WEB")
                print(f"  ✓ Uploaded {remote_path}")
            else:
                print(f"  ✗ Local file {local_file} not found")

        print("\n=== Server Seed Completed Successfully! ===")


if __name__ == "__main__":
    asyncio.run(seed())
