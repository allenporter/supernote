"""FastAPI wrapper around the macos-vision-ocr CLI (Apple Vision framework).

Accepts raw image bytes at POST /ocr, shells out to the compiled
macos-vision-ocr binary, and returns the recognized text.
"""

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("visionocr")

OCR_BINARY = os.environ.get(
    "VISIONOCR_BINARY",
    str(Path(__file__).resolve().parent.parent / "bin" / "macos-vision-ocr"),
)
REC_LANGS = os.environ.get("VISIONOCR_REC_LANGS")
OCR_TIMEOUT_SECONDS = float(os.environ.get("VISIONOCR_TIMEOUT_SECONDS", "60"))

app = FastAPI()


@app.post("/ocr")
async def ocr(request: Request) -> JSONResponse:
    image_bytes = await request.body()
    if not image_bytes:
        return JSONResponse(status_code=400, content={"error": "empty request body"})

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(image_bytes)
        tmp_path = tmp.name

    try:
        command = [OCR_BINARY, "--img", tmp_path]
        if REC_LANGS:
            command += ["--rec-langs", REC_LANGS]

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=OCR_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            logger.error("macos-vision-ocr timed out after %ss", OCR_TIMEOUT_SECONDS)
            return JSONResponse(
                status_code=502,
                content={"error": "OCR timed out"},
            )
        except OSError as exc:
            logger.error("Failed to launch macos-vision-ocr binary %s: %s", OCR_BINARY, exc)
            return JSONResponse(
                status_code=502,
                content={"error": f"Could not launch OCR binary: {exc}"},
            )

        if result.returncode != 0:
            logger.error(
                "macos-vision-ocr exited %s: %s", result.returncode, result.stderr.strip()
            )
            return JSONResponse(
                status_code=502,
                content={"error": "OCR failed", "detail": result.stderr.strip()},
            )

        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError:
            logger.error("Could not parse macos-vision-ocr stdout: %s", result.stdout)
            return JSONResponse(
                status_code=502,
                content={"error": "OCR produced unparseable output"},
            )

        return JSONResponse(content={"text": parsed.get("texts", "")})
    finally:
        Path(tmp_path).unlink(missing_ok=True)
