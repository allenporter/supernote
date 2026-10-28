"""Shared server utilities for authentication, hashing, storage paths, prompts, and signed URLs.

- `supernote.server.utils.auth_utils`: Request header token extraction (`x-access-token`).
- `supernote.server.utils.hashing`: MD5 and salted SHA-256 digest helpers.
- `supernote.server.utils.note_content`: Page metadata formatting and `PAGEID` date inference.
- `supernote.server.utils.paths`: Logical blob storage key conventions and UUID derivation.
- `supernote.server.utils.prompt_loader`: Externalized Markdown prompt loader (`PROMPT_LOADER`).
- `supernote.server.utils.rate_limit`: Fixed-window rate limiter backed by `CoordinationService`.
- `supernote.server.utils.tasks`: Database helpers with retry backoff for `SystemTaskDO` checkpoints.
- `supernote.server.utils.unique_id`: Snowflake-style 64-bit time-ordered integer ID generator (`next_id`).
- `supernote.server.utils.url_signer`: HS256 JWT URL signer and verifier (`UrlSigner`) for `/api/oss/*`.
"""

__all__ = [
    "auth_utils",
    "hashing",
    "note_content",
    "paths",
    "prompt_loader",
    "rate_limit",
    "tasks",
    "unique_id",
    "url_signer",
]
