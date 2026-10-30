# Chuvadai — Smart Document Reader

Chuvadai is a small Flask web app that turns **PDF, JPG, and PNG** documents into editable text, then lets you download the result as a `.txt` file.

BharatOCR Cloud is the primary OCR provider. If no cloud credentials are configured, the app automatically falls back to an on-device OCR engine so Chuvadai can still be demonstrated offline. Digital PDFs are read directly from their text layer.

## Features

- Upload a PDF, JPG, JPEG, or PNG by dragging it in or browsing.
- Process scanned pages with a configurable BharatOCR API.
- Fall back to Tesseract OCR or the built-in Windows OCR engine.
- Read text-layer PDFs without unnecessary OCR calls.
- Edit the extracted text directly in the browser.
- Copy the text, clear it, or download it as a UTF-8 TXT file.
- See page count, word count, character count, and the engine used.
- Delete uploads from the server immediately after processing.
- Try the built-in sample water bill without needing your own document.

## Workflow

```text
Upload document
      ↓
Validate + store temporarily
      ↓
PDF text layer or BharatOCR Cloud
      ↓
Local OCR fallback, if needed
      ↓
Editable text in the browser
      ↓
Download as TXT
```

## Project structure

```text
bharat-ocr-project/
├── app.py                  # Flask routes, upload handling, security headers
├── bharat_ocr.py           # BharatOCR client, PDF rendering, local OCR fallback
├── requirements.txt
├── README.md
├── .env.example
├── templates/
│   └── index.html
├── static/
│   ├── style.css
│   ├── script.js
│   ├── sample-document.png
│   └── favicon.svg
├── tests/
│   ├── test_app.py
│   └── test_bharat_ocr.py
└── uploads/                # Temporary files only; cleaned after each request
```

## Requirements

- Python 3.10+
- A BharatOCR API key or account, **or** one local OCR engine:
  - **Windows:** the `winocr` package is installed by `requirements.txt` and uses the Windows OCR language pack.
  - **Any OS:** Tesseract OCR.

## Setup

### 1. Create and activate a virtual environment

**Windows PowerShell**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

For Tesseract on macOS/Linux:

```bash
# macOS
brew install tesseract

# Ubuntu / Debian
sudo apt install tesseract-ocr
```

On Windows, install Tesseract from [UB Mannheim Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) if it is not already installed. The app also checks the default `C:\Program Files\Tesseract-OCR\` location.

### 3. Configure the app

```powershell
Copy-Item .env.example .env
```

```bash
cp .env.example .env
```

Open `.env` and add BharatOCR credentials if you have them:

```dotenv
BHARATOCR_MODE=auto
BHARATOCR_API_KEY=your_api_key
# or:
# BHARATOCR_EMAIL=you@example.com
# BHARATOCR_PASSWORD=your_password
```

If you do not have credentials, leave these blank. The app will use Tesseract or Windows OCR.

### 4. Run

```bash
python app.py
```

Open <http://127.0.0.1:5000> in your browser.

Click **Try a sample document**, then **Extract text** to test the complete flow immediately.

## BharatOCR API configuration

BharatOCR plans and deployments expose different endpoints, so the endpoint is configurable instead of hard-coded.

| Variable | Purpose |
| --- | --- |
| `BHARATOCR_MODE` | `auto`, `cloud`, or `local`. Default: `auto`. |
| `BHARATOCR_API_KEY` | Bearer API key. |
| `BHARATOCR_EMAIL` / `BHARATOCR_PASSWORD` | Alternative login flow. The app calls `/auth/login` and caches the returned token. |
| `BHARATOCR_API_BASE` | Base URL used for login and for constructing the OCR URL. |
| `BHARATOCR_API_URL` | Exact OCR endpoint. Overrides the base + endpoint combination. |
| `BHARATOCR_ENDPOINT` | Endpoint appended to the base, for example `ocr`. |
| `BHARATOCR_DOCUMENT_TYPE` | Optional document-specific endpoint such as `pan`, `passport`, or `degree`. It overrides `BHARATOCR_ENDPOINT` and sends the file as `image`. |
| `BHARATOCR_FILE_FIELD` | Multipart field name. Defaults to `file` for a generic endpoint and `image` for a document-specific endpoint. |
| `BHARATOCR_FORCE_CLOUD` | Set to `true` to OCR every PDF page even if a text layer exists. |
| `BHARATOCR_TIMEOUT` | Request timeout in seconds. |

The client accepts several common response shapes:

```json
{"text": "Extracted text..."}
```

```json
{"data": {"text": "Extracted text..."}}
```

```json
{"name": "Ananya Sharma", "pan_number": "ABCDE1234F"}
```

Structured fields are converted into editable `Field: value` lines.

### Example: a generic OCR endpoint

```dotenv
BHARATOCR_MODE=cloud
BHARATOCR_API_URL=https://your-bharatocr-host.example/api/v1/ocr
BHARATOCR_API_KEY=your_key
BHARATOCR_FILE_FIELD=file
```

### Example: a document-specific endpoint

```dotenv
BHARATOCR_MODE=cloud
BHARATOCR_API_BASE=https://api.essentiasoftserv.com/api/v1
BHARATOCR_API_KEY=your_key
BHARATOCR_DOCUMENT_TYPE=pan
```

> The public BharatOCR/OpenBharatOCR ecosystem contains both document-specific APIs and self-hosted OCR tools. Confirm the exact endpoint and authentication scheme available to your account, then set `BHARATOCR_API_URL` or `BHARATOCR_DOCUMENT_TYPE` accordingly.

## Local OCR fallback

The fallback chain is:

1. **Tesseract** if `tesseract` is on `PATH` or found at the standard Windows install location.
2. **Windows OCR** via the `winocr` package on Windows.
3. Digital PDFs with a text layer still work even when no OCR engine is available.

Configure languages with:

```dotenv
TESSERACT_LANG=eng
WINOCR_LANG=en
```

For Hindi with Tesseract, install the `hin` language data and use `TESSERACT_LANG=eng+hin`. Windows OCR requires the corresponding Windows language pack.

## Run the tests

The tests use Python's built-in `unittest` module and mock the OCR service, so they do not need API credentials or a Tesseract install:

```bash
python -m unittest discover -s tests -v
```

## API endpoints

### `GET /`

Renders the web app.

### `GET /api/status`

Reports the active configuration without exposing credentials.

```json
{
  "mode": "auto",
  "cloud_configured": false,
  "local_available": true,
  "local_engine": "Tesseract OCR",
  "max_pages": 20
}
```

### `POST /api/ocr`

Multipart form upload with a field named `file`.

```bash
curl -X POST http://127.0.0.1:5000/api/ocr -F "file=@sample-water-bill.png"
```

Example response:

```json
{
  "text": "BHARAT MUNICIPAL WATER BOARD...",
  "pages": 1,
  "engine": "BharatOCR Cloud",
  "warnings": [],
  "file": {
    "name": "sample-water-bill.png",
    "size": 142164
  }
}
```

Errors return a JSON `error` field and an appropriate HTTP status.

### `GET /health`

Simple uptime check.

## Limits and validation

- Maximum upload size: `20 MB` by default (`MAX_UPLOAD_MB`).
- Maximum PDF pages: `20` by default (`MAX_PDF_PAGES`).
- Supported types: `.pdf`, `.png`, `.jpg`, `.jpeg`.
- Password-protected PDFs are rejected.
- Images are validated with Pillow, not just by file extension.
- Uploaded files are stored under a random UUID name and deleted in a `finally` block.

## Privacy notes

- There is no database and no user account.
- Uploads exist only for the duration of the OCR request.
- Extracted text remains in the browser unless you download it.
- If BharatOCR Cloud is used, page images are sent to that provider. Review your provider's data policy before using real documents.

## Troubleshooting

**The status badge says “PDF text mode.”**
No cloud API and no local OCR engine are available. Digital PDFs still work; install Tesseract or configure BharatOCR for images.

**BharatOCR calls fail and the result says local OCR was used.**
`BHARATOCR_MODE=auto` falls back to local OCR when the API is unreachable or rejects the request. Set `BHARATOCR_MODE=cloud` if you want the failure to be visible instead.

**Tesseract is installed but not detected.**
Set `TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe` in `.env`.

**Hindi text is not recognised.**
Install the `hin` Tesseract language pack and set `TESSERACT_LANG=eng+hin`, or enable the Hindi Windows OCR language pack.

## License

This is a learning/mini-project implementation. BharatOCR and its APIs belong to their respective owners.
