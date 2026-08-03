#!/usr/bin/env python3
"""Seed script for populating development server with notes, documents, and schedule tasks."""

import asyncio

from supernote.cli.client import async_cloud_seed


def main() -> None:
    asyncio.run(async_cloud_seed())


if __name__ == "__main__":
    main()
