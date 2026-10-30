"""Document extraction pipeline for Chuvadai Smart Document Reader.

The pipeline has three layers:

1. Digital PDF text layers are read directly with PyMuPDF (fast and exact).
2. Images (and scanned PDF pages) are sent to a configurable BharatOCR API.
3. If the API is unavailable and the app is in "auto" mode, a local OCR engine
   (Tesseract or the Windows OCR engine) is used as a fallback.

Only the public ``DocumentOCR.extract`` method is used by the Flask app.
"""

from __future__ import annotations

import io
import logging
import os
import re
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz
import requests
from PIL import Image, ImageOps, UnidentifiedImageError

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).with_name(".env"))
except ImportError:  # python-dotenv is optional at runtime
    pass

LOGGER = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | {".pdf"}

# A very large image can exhaust memory. Pillow's decompression-bomb guard is
# useful here because uploads are untrusted.
MAX_IMAGE_PIXELS = 60_000_000
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

_TEXT_KEYS = (
    "text",
    "extracted_text",
    "ocr_text",
    "raw_text",
    "plain_text",
    "full_text",
    "content",
    "markdown",
    "lines",
)
_CONTAINER_KEYS = (
    "data",
    "result",
    "response",
    "document",
    "extracted_data",
    "fields",
    "output",
)
_META_KEYS = {
    "status",
    "success",
    "ok",
    "message",
    "error",
    "code",
    "request_id",
    "confidence",
    "processing_time",
    "page_count",
    "pages",
    "file_name",
    "filename",
}


class OCRServiceError(Exception):
    """An error that is safe to show to the person using the app."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class Settings:
    mode: str
    api_base: str
    api_url: str
    api_key: str
    email: str
    password: str
    endpoint: str
    file_field: str
    timeout: int
    force_cloud: bool
    dpi: int
    max_pdf_pages: int
    text_min_chars: int
    tesseract_lang: str
    winocr_lang: str

    @classmethod
    def load(cls) -> "Settings":
        mode = os.getenv("BHARATOCR_MODE", "auto").strip().lower()
        if mode not in {"auto", "cloud", "local"}:
            raise OCRServiceError(
                "BHARATOCR_MODE must be one of: auto, cloud, or local.", 500
            )

        document_type = os.getenv("BHARATOCR_DOCUMENT_TYPE", "").strip().lower()
        endpoint = document_type or os.getenv("BHARATOCR_ENDPOINT", "ocr").strip()
        default_field = "image" if document_type else "file"
        file_field = os.getenv("BHARATOCR_FILE_FIELD", "").strip() or default_field

        return cls(
            mode=mode,
            api_base=os.getenv(
                "BHARATOCR_API_BASE", "https://api.essentiasoftserv.com/api/v1"
            ).strip(),
            api_url=os.getenv("BHARATOCR_API_URL", "").strip(),
            api_key=os.getenv("BHARATOCR_API_KEY", "").strip(),
            email=os.getenv("BHARATOCR_EMAIL", "").strip(),
            password=os.getenv("BHARATOCR_PASSWORD", ""),
            endpoint=endpoint or "ocr",
            file_field=file_field,
            timeout=max(5, _env_int("BHARATOCR_TIMEOUT", 60)),
            force_cloud=_env_bool("BHARATOCR_FORCE_CLOUD", False),
            dpi=max(100, min(_env_int("OCR_DPI", 200), 400)),
            max_pdf_pages=max(1, min(_env_int("MAX_PDF_PAGES", 20), 100)),
            text_min_chars=max(0, _env_int("PDF_TEXT_MIN_CHARS", 30)),
            tesseract_lang=os.getenv("TESSERACT_LANG", "eng").strip() or "eng",
            winocr_lang=os.getenv("WINOCR_LANG", "en").strip() or "en",
        )

    @property
    def cloud_configured(self) -> bool:
        return bool(self.api_key or (self.email and self.password))

    @property
    def cloud_url(self) -> str:
        if self.api_url:
            return self.api_url
        return f"{self.api_base.rstrip('/')}/{self.endpoint.lstrip('/')}"


@dataclass
class OCRResult:
    text: str
    pages: int
    engine: str
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "pages": self.pages,
            "engine": self.engine,
            "warnings": self.warnings,
        }


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _humanize_field(key: str) -> str:
    return re.sub(r"[_-]+", " ", key).strip().title()


def _flatten_payload(payload: Any, depth: int = 0) -> str:
    """Turn the many possible BharatOCR JSON shapes into readable text.

    Some endpoints return ``{"text": "..."}``, others return a list of OCR
    lines, and document endpoints return structured fields such as
    ``{"name": "...", "pan_number": "..."}``. This handles all three.
    """

    if depth > 8:
        return ""
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, (int, float)):
        return str(payload)
    if isinstance(payload, list):
        parts: list[str] = []
        for item in payload:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"].strip())
            else:
                part = _flatten_payload(item, depth + 1)
                if part:
                    parts.append(part)
        return "\n".join(part for part in parts if part.strip())
    if not isinstance(payload, dict):
        return ""

    # Prefer the response's dedicated text field.
    for key in _TEXT_KEYS:
        if key in payload:
            text = _flatten_payload(payload[key], depth + 1)
            if text.strip():
                return text

    # Then look inside common wrapper objects.
    for key in _CONTAINER_KEYS:
        if key in payload:
            text = _flatten_payload(payload[key], depth + 1)
            if text.strip():
                return text

    # Finally, flatten structured fields into "Label: value" lines.
    lines: list[str] = []
    for key, value in payload.items():
        if str(key).lower() in _META_KEYS:
            continue
        if isinstance(value, (str, int, float, bool)):
            rendered = str(value).strip()
            if rendered and rendered.lower() not in {"none", "null"}:
                lines.append(f"{_humanize_field(str(key))}: {rendered}")
        elif isinstance(value, (dict, list)):
            nested = _flatten_payload(value, depth + 1)
            if nested.strip():
                lines.append(f"{_humanize_field(str(key))}:\n{nested}")
    return "\n".join(lines)


def _response_error(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        for key in ("message", "error", "detail"):
            value = payload.get(key)
            if value:
                return str(value)[:300]
    body = (response.text or "").strip()
    return body[:300]


def _clean_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def _engine_label(engines: list[str]) -> str:
    unique = list(dict.fromkeys(engines))
    if not unique:
        return "OCR"
    if len(unique) == 1:
        return unique[0]
    if set(unique) == {"BharatOCR Cloud", "PDF text layer"}:
        return "BharatOCR Cloud + PDF text"
    return " + ".join(unique[:3])


def _image_to_jpeg_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95, optimize=True, progressive=True)
    return buffer.getvalue()


def _prepare_image(path: Path) -> Image.Image:
    """Load, orient, flatten transparency, and normalise an image for OCR."""

    try:
        with Image.open(path) as source:
            source.load()
            image = ImageOps.exif_transpose(source)
            if image.mode in {"RGBA", "LA"} or (
                image.mode == "P" and "transparency" in image.info
            ):
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise OCRServiceError(
            "That image could not be opened. Try a valid JPG, PNG, or PDF file.",
            400,
        ) from exc

    if image.width * image.height > MAX_IMAGE_PIXELS:
        raise OCRServiceError(
            "The image dimensions are too large. Please upload a smaller image.",
            400,
        )

    longest = max(image.size)
    if longest < 1600:
        scale = min(2.0, 1600 / longest)
        image = image.resize(
            (round(image.width * scale), round(image.height * scale)),
            Image.Resampling.LANCZOS,
        )
    elif longest > 5000:
        scale = 5000 / longest
        image = image.resize(
            (round(image.width * scale), round(image.height * scale)),
            Image.Resampling.LANCZOS,
        )
    return image


class BharatOCRClient:
    """Small, dependency-free client for a BharatOCR-compatible HTTP API."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._token = settings.api_key
        self._token_lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return self.settings.cloud_configured

    def _login(self) -> str:
        if not (self.settings.email and self.settings.password):
            return ""

        login_url = f"{self.settings.api_base.rstrip('/')}/auth/login"
        try:
            response = requests.post(
                login_url,
                json={
                    "email": self.settings.email,
                    "password": self.settings.password,
                },
                timeout=self.settings.timeout,
                headers={"Accept": "application/json"},
            )
        except requests.RequestException as exc:
            raise OCRServiceError(
                "Could not reach the BharatOCR login service. Check your connection settings.",
                503,
            ) from exc

        if response.status_code != 200:
            detail = _response_error(response)
            raise OCRServiceError(
                "BharatOCR login failed. Check BHARATOCR_EMAIL and BHARATOCR_PASSWORD."
                + (f" ({detail})" if detail else ""),
                502,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise OCRServiceError(
                "BharatOCR returned an unexpected login response.", 502
            ) from exc

        token = payload.get("auth_token") or payload.get("token") or payload.get("key")
        if not token:
            raise OCRServiceError(
                "BharatOCR login succeeded but no access token was returned.", 502
            )
        return str(token)

    def _get_token(self) -> str:
        if self._token:
            return self._token
        with self._token_lock:
            if not self._token:
                self._token = self._login()
            return self._token

    def _send(self, image_bytes: bytes, filename: str) -> requests.Response:
        token = self._get_token()
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        safe_name = Path(filename).name.replace("\r", "").replace("\n", "") or "page.jpg"
        files = {
            self.settings.file_field: (
                safe_name,
                image_bytes,
                "image/jpeg",
            )
        }
        try:
            return requests.post(
                self.settings.cloud_url,
                headers=headers,
                files=files,
                timeout=self.settings.timeout,
            )
        except requests.RequestException as exc:
            raise OCRServiceError(
                "Could not reach the BharatOCR API. Check your internet connection and API settings.",
                503,
            ) from exc

    def extract(self, image_bytes: bytes, filename: str) -> str:
        response = self._send(image_bytes, filename)

        # A cached login token can expire while the app is running. Retry once
        # with a fresh token, but only when using email/password authentication.
        if (
            response.status_code == 401
            and not self.settings.api_key
            and self.settings.email
            and self.settings.password
        ):
            with self._token_lock:
                self._token = ""
            response = self._send(image_bytes, filename)

        if response.status_code == 401:
            raise OCRServiceError(
                "BharatOCR rejected the API credentials. Check your API key or login details.",
                502,
            )
        if response.status_code == 429:
            raise OCRServiceError(
                "The BharatOCR API rate limit was reached. Please try again shortly.",
                429,
            )
        if response.status_code >= 400:
            detail = _response_error(response)
            raise OCRServiceError(
                "BharatOCR could not process this document."
                + (f" {detail}" if detail else ""),
                502,
            )

        try:
            payload = response.json()
        except ValueError:
            text = (response.text or "").strip()
            if text:
                return text
            raise OCRServiceError("BharatOCR returned an empty response.", 502)

        text = _flatten_payload(payload)
        if text.strip():
            return text.strip()

        message = ""
        if isinstance(payload, dict):
            message = str(payload.get("message") or payload.get("error") or "").strip()
        raise OCRServiceError(
            "BharatOCR returned no readable text."
            + (f" {message[:300]}" if message else ""),
            422,
        )


class LocalOCREngine:
    """Best-effort offline OCR so the demo works without cloud credentials."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._pytesseract = None
        self._tesseract_cmd = self._find_tesseract()
        if self._tesseract_cmd:
            try:
                import pytesseract

                pytesseract.pytesseract.tesseract_cmd = self._tesseract_cmd
                self._pytesseract = pytesseract
            except ImportError:
                self._tesseract_cmd = ""

        self._winocr = None
        if os.name == "nt":
            try:
                import winocr

                self._winocr = winocr
            except ImportError:
                self._winocr = None

    @staticmethod
    def _find_tesseract() -> str:
        candidates = [
            os.getenv("TESSERACT_CMD", "").strip(),
            shutil.which("tesseract") or "",
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return candidate
        return ""

    @property
    def available_label(self) -> str:
        if self._tesseract_cmd:
            return "Tesseract OCR"
        if self._winocr is not None:
            return "Windows OCR"
        return ""

    def extract(self, image: Image.Image) -> tuple[str, str]:
        errors: list[str] = []

        if self._pytesseract is not None:
            text = self._tesseract_extract(image, errors)
            if text:
                return text, "Tesseract OCR"

        if self._winocr is not None:
            text = self._windows_extract(image, errors)
            if text:
                return text, "Windows OCR"

        if errors:
            LOGGER.warning("Local OCR failed: %s", " | ".join(errors[:2]))
        raise OCRServiceError(
            "No local OCR engine is available. Install Tesseract OCR, enable the "
            "Windows OCR language pack, or configure BharatOCR Cloud in .env.",
            503,
        )

    def _tesseract_extract(self, image: Image.Image, errors: list[str]) -> str:
        try:
            text = self._pytesseract.image_to_string(
                image, lang=self.settings.tesseract_lang, config="--psm 3"
            )
        except Exception as exc:  # Tesseract errors are varied and often opaque
            errors.append(f"Tesseract: {exc}")
            if self.settings.tesseract_lang != "eng":
                try:
                    text = self._pytesseract.image_to_string(
                        image, lang="eng", config="--psm 3"
                    )
                except Exception as fallback_exc:
                    errors.append(f"Tesseract English fallback: {fallback_exc}")
                    return ""
            else:
                return ""
        return _clean_text(text)

    def _windows_extract(self, image: Image.Image, errors: list[str]) -> str:
        languages = [self.settings.winocr_lang]
        if languages[0] != "en":
            languages.append("en")

        for language in languages:
            try:
                result = self._winocr.recognize_pil_sync(image, lang=language)
            except Exception as exc:
                errors.append(f"Windows OCR ({language}): {exc}")
                continue

            lines = [
                str(line.get("text", "")).strip()
                for line in result.get("lines", [])
                if line.get("text")
            ]
            text = _clean_text("\n".join(lines) or str(result.get("text", "")))
            if text:
                return text
        return ""


class DocumentOCR:
    """High-level document extraction service used by the Flask app."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.load()
        self.cloud = BharatOCRClient(self.settings)
        self.local = LocalOCREngine(self.settings)

    def status(self) -> dict[str, Any]:
        return {
            "mode": self.settings.mode,
            "cloud_configured": self.cloud.configured,
            "local_available": bool(self.local.available_label),
            "local_engine": self.local.available_label,
            "max_pages": self.settings.max_pdf_pages,
        }

    def extract(self, path: Path, original_name: str = "") -> OCRResult:
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise OCRServiceError("Only PDF, JPG, JPEG, and PNG files are supported.", 400)
        if self.settings.mode == "cloud" and not self.cloud.configured:
            raise OCRServiceError(
                "BHARATOCR_MODE is set to cloud, but no BharatOCR credentials are configured.",
                503,
            )

        if suffix == ".pdf":
            return self._extract_pdf(path)
        return self._extract_image(path, original_name)

    def _extract_image(self, path: Path, original_name: str = "") -> OCRResult:
        image = _prepare_image(path)
        text, engine, warnings = self._ocr_image(
            image, Path(original_name or path.name).name
        )
        text = _clean_text(text)
        if not text:
            raise OCRServiceError(
                "No readable text was found in this image. Try a sharper photo "
                "with good lighting and contrast.",
                422,
            )
        return OCRResult(text=text, pages=1, engine=engine, warnings=warnings)

    def _extract_pdf(self, path: Path) -> OCRResult:
        try:
            document = fitz.open(path)
        except Exception as exc:
            raise OCRServiceError(
                "That PDF could not be opened. It may be damaged or password protected.",
                400,
            ) from exc

        try:
            if document.needs_pass:
                raise OCRServiceError(
                    "Password-protected PDFs are not supported. Remove the password "
                    "and try again.",
                    400,
                )
            if document.page_count == 0:
                raise OCRServiceError("This PDF has no pages.", 400)
            if document.page_count > self.settings.max_pdf_pages:
                raise OCRServiceError(
                    f"This PDF has {document.page_count} pages. The limit is "
                    f"{self.settings.max_pdf_pages} pages per document.",
                    400,
                )

            page_texts: list[str] = []
            engines: list[str] = []
            warnings: list[str] = []

            for page_number, page in enumerate(document, start=1):
                direct_text = _clean_text(page.get_text("text", sort=True))
                use_text_layer = (
                    len(direct_text) >= self.settings.text_min_chars
                    and not self.settings.force_cloud
                )

                if use_text_layer:
                    page_texts.append(direct_text)
                    engines.append("PDF text layer")
                    continue

                try:
                    pixmap = page.get_pixmap(dpi=self.settings.dpi, alpha=False)
                    image = Image.open(
                        io.BytesIO(pixmap.tobytes("png"))
                    ).convert("RGB")
                except Exception as exc:
                    raise OCRServiceError(
                        f"Page {page_number} could not be rendered for OCR.", 422
                    ) from exc

                text, engine, page_warnings = self._ocr_image(
                    image, f"page-{page_number}.jpg"
                )
                if not text.strip():
                    warnings.append(f"Page {page_number} contained no readable text.")
                page_texts.append(_clean_text(text))
                engines.append(engine)
                warnings.extend(page_warnings)

            text = _clean_text("\n\n".join(part for part in page_texts if part))
            if not text:
                raise OCRServiceError(
                    "No readable text was found. Try a clearer scan or a PDF with "
                    "selectable text.",
                    422,
                )

            return OCRResult(
                text=text,
                pages=document.page_count,
                engine=_engine_label(engines),
                warnings=_dedupe(warnings),
            )
        finally:
            document.close()

    def _ocr_image(
        self, image: Image.Image, filename: str
    ) -> tuple[str, str, list[str]]:
        warnings: list[str] = []

        if self.settings.mode != "local" and self.cloud.configured:
            try:
                text = self.cloud.extract(_image_to_jpeg_bytes(image), filename)
                return _clean_text(text), "BharatOCR Cloud", warnings
            except OCRServiceError as exc:
                if self.settings.mode == "cloud":
                    raise
                LOGGER.warning("BharatOCR fallback to local OCR: %s", exc.message)
                warnings.append(
                    "BharatOCR Cloud was unavailable, so this page was read with "
                    "the local OCR engine."
                )

        text, engine = self.local.extract(image)
        return text, f"{engine} (local)", warnings
