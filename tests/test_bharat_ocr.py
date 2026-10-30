import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from bharat_ocr import (
    BharatOCRClient,
    Settings,
    _clean_text,
    _engine_label,
    _flatten_payload,
)


class PayloadParsingTests(unittest.TestCase):
    def test_plain_text_payload(self):
        self.assertEqual(_flatten_payload({"text": "Hello\nWorld"}), "Hello\nWorld")

    def test_nested_text_payload(self):
        payload = {"data": {"text": "Invoice 42", "confidence": 0.98}}
        self.assertEqual(_flatten_payload(payload), "Invoice 42")

    def test_ocr_lines_payload(self):
        payload = {"lines": [{"text": "Line one"}, {"text": "Line two"}]}
        self.assertEqual(_flatten_payload(payload), "Line one\nLine two")

    def test_structured_document_payload(self):
        payload = {
            "name": "Ananya Sharma",
            "pan_number": "ABCDE1234F",
            "status": "success",
        }
        text = _flatten_payload(payload)
        self.assertIn("Name: Ananya Sharma", text)
        self.assertIn("Pan Number: ABCDE1234F", text)
        self.assertNotIn("Status", text)

    def test_clean_text(self):
        self.assertEqual(_clean_text("  a  \r\n\r\n\r\nb  "), "a\n\nb")

    def test_engine_label(self):
        self.assertEqual(_engine_label(["BharatOCR Cloud"]), "BharatOCR Cloud")
        self.assertEqual(
            _engine_label(["BharatOCR Cloud", "PDF text layer"]),
            "BharatOCR Cloud + PDF text",
        )


class SettingsTests(unittest.TestCase):
    def test_document_type_switches_file_field(self):
        import os

        previous = {
            key: os.environ.get(key)
            for key in ("BHARATOCR_DOCUMENT_TYPE", "BHARATOCR_FILE_FIELD")
        }
        try:
            os.environ["BHARATOCR_DOCUMENT_TYPE"] = "pan"
            os.environ.pop("BHARATOCR_FILE_FIELD", None)
            settings = Settings.load()
            self.assertEqual(settings.endpoint, "pan")
            self.assertEqual(settings.file_field, "image")
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


class BharatOCRClientTests(unittest.TestCase):
    def setUp(self):
        self.settings = replace(
            Settings.load(),
            mode="cloud",
            api_key="",
            api_url="https://ocr.example.test/v1/ocr",
            email="user@example.test",
            password="secret",
        )

    @patch("bharat_ocr.requests.post")
    def test_login_then_extract(self, post):
        login_response = Mock(status_code=200)
        login_response.json.return_value = {"auth_token": "token-123"}
        ocr_response = Mock(status_code=200)
        ocr_response.json.return_value = {"data": {"text": "Extracted invoice"}}
        post.side_effect = [login_response, ocr_response]

        client = BharatOCRClient(self.settings)
        text = client.extract(b"image-bytes", "page.jpg")

        self.assertEqual(text, "Extracted invoice")
        self.assertEqual(post.call_count, 2)
        login_call, ocr_call = post.call_args_list
        self.assertTrue(login_call.args[0].endswith("/auth/login"))
        self.assertEqual(ocr_call.args[0], "https://ocr.example.test/v1/ocr")
        self.assertEqual(ocr_call.kwargs["headers"]["Authorization"], "Bearer token-123")
        self.assertIn("file", ocr_call.kwargs["files"])

    @patch("bharat_ocr.requests.post")
    def test_document_type_uses_image_field(self, post):
        settings = replace(
            self.settings,
            api_key="api-key",
            api_url="",
            endpoint="pan",
            file_field="image",
        )
        response = Mock(status_code=200)
        response.json.return_value = {"name": "Ananya Sharma", "pan_number": "ABCDE1234F"}
        post.return_value = response

        text = BharatOCRClient(settings).extract(b"image-bytes", "pan.jpg")

        self.assertIn("Name: Ananya Sharma", text)
        self.assertIn("Pan Number: ABCDE1234F", text)
        self.assertEqual(post.call_count, 1)
        self.assertIn("image", post.call_args.kwargs["files"])

    @patch("bharat_ocr.requests.post")
    def test_missing_text_raises(self, post):
        response = Mock(status_code=200)
        response.json.return_value = {"status": "success", "message": "No text"}
        post.return_value = response

        client = BharatOCRClient(replace(self.settings, api_key="api-key"))
        with self.assertRaises(Exception) as context:
            client.extract(b"image-bytes", "blank.jpg")
        self.assertIn("no readable text", str(context.exception).lower())


if __name__ == "__main__":
    unittest.main()
