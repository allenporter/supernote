#!/usr/bin/env python3
import argparse
import asyncio

from sqlalchemy import delete

from supernote.server.config import ServerConfig
from supernote.server.db.models.note_processing import SystemTaskDO
from supernote.server.db.session import DatabaseSessionManager


async def reprocess(task_type: str, file_id: int | None = None):
    config = ServerConfig.load()
    db_manager = DatabaseSessionManager(config.db_url)

    async with db_manager.session() as session:
        # Build query
        stmt = delete(SystemTaskDO)
        if task_type.upper() != "ALL":
            # Map friendly names to task types
            task_type_map = {
                "ocr": "OCR_EXTRACTION",
                "summary": "SUMMARY_GENERATION",
                "embedding": "EMBEDDING_GENERATION",
                "png": "PNG_CONVERSION",
                "hashing": "PAGE_HASHING",
            }
            mapped_type = task_type_map.get(task_type.lower(), task_type.upper())
            stmt = stmt.where(SystemTaskDO.task_type == mapped_type)

        if file_id is not None:
            stmt = stmt.where(SystemTaskDO.file_id == file_id)

        result = await session.execute(stmt)
        await session.commit()

        rowcount = getattr(result, "rowcount", 0)
        print(f"Cleared task entries in database. Rows affected: {rowcount}")
        print(
            "Note: The server will automatically detect the missing tasks and reprocess the notes using the latest prompt templates on next startup or during the next polling loop."
        )


def main():
    parser = argparse.ArgumentParser(
        description="Force reprocessing of notes by clearing task states in the database."
    )
    parser.add_argument(
        "--type",
        choices=["all", "ocr", "summary", "embedding", "png"],
        default="summary",
        help="Type of tasks to clear and reprocess (default: summary).",
    )
    parser.add_argument(
        "--file-id",
        type=int,
        default=None,
        help="Specific file ID to reprocess (default: all files).",
    )

    args = parser.parse_args()
    asyncio.run(reprocess(args.type, args.file_id))


if __name__ == "__main__":
    main()
