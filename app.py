"""Chuvadai Smart Document Reader - Flask web application."""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

from bharat_ocr import OCRServiceError, SUPPORTED_EXTENSIONS, DocumentOCR, Settings

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

try:
    MAX_UPLOAD_MB = max(1, int(os.getenv("MAX_UPLOAD_MB", "20")))
except ValueError:
    MAX_UPLOAD_MB = 20
DEBUG = os.getenv("FLASK_DEBUG", "0").strip().lower() in {"1", "true", "yes", "on"}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
LOGGER = logging.getLogger(__name__)

app = Flask(__name__)
app.config.update(
    MAX_CONTENT_LENGTH=MAX_UPLOAD_MB * 1024 * 1024,
    UPLOAD_FOLDER=str(UPLOAD_DIR),
    JSON_SORT_KEYS=False,
)

try:
    ocr_service = DocumentOCR(Settings.load())
except OCRServiceError:
    LOGGER.exception("Invalid OCR configuration")
    ocr_service = None


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
    )
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "img-src 'self' blob: data:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; "
        "connect-src 'self'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'",
    )
    if request.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.get("/")
def index():
    return render_template(
        "index.html",
        max_upload_mb=MAX_UPLOAD_MB,
    )


@app.get("/health")
def health():
    return jsonify(status="ok")


@app.get("/api/status")
def api_status():
    if ocr_service is None:
        return (
            jsonify(
                error="OCR service configuration is invalid. Check your .env file."
            ),
            500,
        )
    return jsonify(ocr_service.status())


@app.post("/api/ocr")
def api_ocr():
    if ocr_service is None:
        return (
            jsonify(
                error="OCR service configuration is invalid. Check your .env file."
            ),
            500,
        )

    upload = request.files.get("file")
    if upload is None or not upload.filename:
        return jsonify(error="Please choose a PDF, JPG, or PNG file."), 400

    raw_name = Path(upload.filename).name
    suffix = Path(raw_name).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        return (
            jsonify(error="Unsupported file type. Please upload a PDF, JPG, or PNG."),
            400,
        )

    # secure_filename() drops non-ASCII names entirely, so keep the original
    # extension before sanitising and fall back to a generic display name.
    original_name = secure_filename(raw_name) or f"document{suffix}"
    stored_name = f"{uuid.uuid4().hex}{suffix}"
    stored_path = UPLOAD_DIR / stored_name

    try:
        upload.save(stored_path)
        if stored_path.stat().st_size == 0:
            raise OCRServiceError("The uploaded file is empty.", 400)

        result = ocr_service.extract(stored_path, original_name)
        LOGGER.info(
            "Processed %s (%s pages) with %s",
            original_name,
            result.pages,
            result.engine,
        )
        return jsonify(
            {
                **result.as_dict(),
                "file": {
                    "name": original_name,
                    "size": stored_path.stat().st_size,
                },
            }
        )
    except OCRServiceError as exc:
        return jsonify(error=exc.message), exc.status_code
    except RequestEntityTooLarge:
        raise
    except Exception:
        LOGGER.exception("Unexpected OCR failure for %s", original_name)
        return (
            jsonify(
                error="Something went wrong while reading this document. "
                "Please try a different file."
            ),
            500,
        )
    finally:
        # Uploads are temporary by design: delete even when OCR fails.
        stored_path.unlink(missing_ok=True)


@app.errorhandler(RequestEntityTooLarge)
def handle_too_large(_error):
    return (
        jsonify(
            error=f"That file is too large. The maximum upload size is {MAX_UPLOAD_MB} MB."
        ),
        413,
    )


if __name__ == "__main__":
    app.run(
        host=os.getenv("FLASK_HOST", "127.0.0.1"),
        port=int(os.getenv("FLASK_PORT", "5000")),
        debug=DEBUG,
    )
