import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-placeholder")
os.environ.setdefault("SESSION_SECRET", "test-placeholder")

from main import app
from routes import auth, chat
from middleware import limiter


class ReleaseSecurityTests(unittest.TestCase):
    def test_staff_cookie_and_origin(self):
        with patch.object(auth, "ADMIN_USER", "operator"), patch.object(auth, "ADMIN_PASS", "initial"):
            with TestClient(app, base_url="https://municipal.example") as client:
                credentials = {"username": "operator", "password": "initial"}
                login = client.post("/api/login", data=credentials, headers={"Origin": "https://municipal.example"})
                self.assertEqual(login.status_code, 200)
                self.assertIn("Max-Age=28800", login.headers["set-cookie"])
                self.assertTrue(client.get("/api/check-admin").json()["authenticated"])
                self.assertEqual(client.post("/api/logout", headers={"Origin": "https://untrusted.example"}).status_code, 403)
                with patch.object(auth, "ADMIN_PASS", "rotated"):
                    self.assertFalse(client.get("/api/check-admin").json()["authenticated"])
                    self.assertEqual(client.get("/pdfs").status_code, 401)

    @patch.object(limiter, "enabled", False)
    @patch.object(chat, "record_usage")
    @patch.object(chat, "_save_messages")
    @patch.object(chat, "_answer", new_callable=AsyncMock)
    def test_chat_size_and_opt_in(self, answer, save, usage):
        answer.return_value = ("Verified answer", "Contact")
        save.side_effect = RuntimeError("Storage unavailable")
        with TestClient(app, base_url="https://municipal.example") as client:
            large = client.post("/chat", json={"message": "x", "padding": "x" * 33_000})
            self.assertEqual(large.status_code, 413)
            self.assertEqual(client.post("/chat", json={"message": "Hello"}).json(), {"answer": "Verified answer"})
            save.assert_not_called()
            opt_in = client.post("/chat", json={"message": "Hello", "no_save": False})
            self.assertEqual(opt_in.json(), {"answer": "Verified answer", "history_saved": False})
            save.assert_called_once()
            self.assertEqual(usage.call_count, 2)
