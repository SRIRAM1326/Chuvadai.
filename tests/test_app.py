import io
import unittest
from pathlib import Path
from unittest.mock import patch

import app as app_module
from bharat_ocr import OCRResult


class AppTestCase(unittest.TestCase):
    def setUp(self):
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()
        self.uploads = Path(app_module.UPLOAD_DIR)

    def test_home_page(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Chuvadai", response.data)
        self.assertIn(b"BharatOCR", response.data)
        self.assertIn(b"Extract text", response.data)

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")

    def test_status(self):
        response = self.client.get("/api/status")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("cloud_configured", payload)
        self.assertIn("local_available", payload)
        self.assertIn("max_pages", payload)

    def test_missing_file(self):
        response = self.client.post("/api/ocr", data={})
        self.assertEqual(response.status_code, 400)
        self.assertIn("choose", response.get_json()["error"].lower())

    def test_unsupported_extension(self):
        response = self.client.post(
            "/api/ocr",
            data={"file": (io.BytesIO(b"not a document"), "notes.txt")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Unsupported", response.get_json()["error"])

    def test_ocr_success_and_upload_cleanup(self):
        before = {p.name for p in self.uploads.iterdir()}
        result = OCRResult(
            text="Invoice 2026-0042\nAnanya Sharma",
            pages=2,
            engine="BharatOCR Cloud",
            warnings=[],
        )
        with patch.object(app_module.ocr_service, "extract", return_value=result):
            response = self.client.post(
                "/api/ocr",
                data={"file": (io.BytesIO(b"fake pdf bytes"), "invoice.pdf")},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["pages"], 2)
        self.assertEqual(payload["engine"], "BharatOCR Cloud")
        self.assertIn("Ananya Sharma", payload["text"])
        self.assertEqual({p.name for p in self.uploads.iterdir()}, before)

    def test_empty_file_is_rejected(self):
        response = self.client.post(
            "/api/ocr",
            data={"file": (io.BytesIO(b""), "empty.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("empty", response.get_json()["error"].lower())


if __name__ == "__main__":
    unittest.main()
