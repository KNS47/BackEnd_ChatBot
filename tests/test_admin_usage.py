import asyncio
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-placeholder")
os.environ.setdefault("SESSION_SECRET", "test-placeholder")

from routes import usage
from usage_counter import add_generation_usage, generation_usage


class UsageTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_usage_survives_child_task_context(self):
        counter = [0]
        context = generation_usage.set(counter)
        try:
            async def provider_call():
                add_generation_usage({"usageMetadata": {"totalTokenCount": 82}})
                add_generation_usage({"usageMetadata": {"totalTokenCount": 5}})
                add_generation_usage({"usageMetadata": {"totalTokenCount": True}})
            await asyncio.wait_for(provider_call(), timeout=1)
            self.assertEqual(counter[0], 87)
        finally:
            generation_usage.reset(context)

    async def test_measured_zero_differs_from_missing_data(self):
        with patch.object(usage.supabase, "rpc", return_value=Mock(
            execute=Mock(return_value=Mock(data=[{"questions": 0, "tokens": 0, "used_bytes": 0}]))
        )), patch.dict(os.environ, {"ADMIN_DAILY_TOKEN_LIMIT": "5000"}):
            response = usage.admin_usage()
        self.assertTrue(response["durable"])
        self.assertEqual(response["today"], {"questions": 0, "tokens": 0})
        self.assertEqual(response["limits"]["tokens"], 5000)

        with patch.object(usage.supabase, "rpc", side_effect=RuntimeError("unavailable")):
            missing = usage.admin_usage()
        self.assertFalse(missing["durable"])
        self.assertIsNone(missing["storage"]["used_bytes"])
