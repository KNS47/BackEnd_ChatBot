import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-placeholder")
os.environ.setdefault("SESSION_SECRET", "test-placeholder")

import backfill_cloudflare_vectors as backfill
import pdf_service
from routes import chat


class CloudflareVectorTests(unittest.IsolatedAsyncioTestCase):
    def test_provider_selects_compatible_retrieval(self):
        rpc = Mock()
        rpc.execute.return_value = SimpleNamespace(data=[])
        for provider, expected in (
            ("cloudflare", "match_documents_cloudflare"),
            ("gemini", "match_documents"),
            ("vertex", "match_documents"),
        ):
            with (
                patch.object(chat, "AI_PROVIDER", provider),
                patch.object(chat.supabase, "rpc", return_value=rpc) as call,
            ):
                chat._match([0.1])
            self.assertEqual(call.call_args.args[0], expected)
            self.assertEqual(call.call_args.args[1]["query_embedding"], [0.1])

    async def test_pdf_indexes_only_provider_column(self):
        for provider, key in (("cloudflare", "embedding_cloudflare"), ("gemini", "embedding")):
            with (
                patch.object(pdf_service, "AI_PROVIDER", provider),
                patch.object(pdf_service, "extract_pages", return_value=[(3, "เทศบาลเมืองศิลา")]),
                patch.object(pdf_service, "embed_text", AsyncMock(return_value=[1])),
                patch.object(pdf_service, "_store_index") as store,
            ):
                self.assertEqual(await pdf_service.index_pdf(b"x", "one.pdf", "ทั่วไป", "คู่มือ.pdf"), 1)
            row = store.call_args.args[2][0]
            self.assertEqual(row["page_number"], 3)
            self.assertEqual(row[key], [1])
            self.assertEqual(set(row) & {"embedding", "embedding_cloudflare"}, {key})

    async def test_backfill_preview_reads_only_ids(self):
        with (
            patch.object(backfill, "pending_rows", side_effect=[[{"id": 1}], []]) as pending,
            patch.object(backfill, "embed_text", AsyncMock()) as embed,
            patch.object(backfill, "save_vector") as save,
        ):
            self.assertEqual(await backfill.run(100, False), (1, 0))
        pending.assert_any_call(None, 100, False, None)
        pending.assert_any_call(1, 99, False, None)
        embed.assert_not_awaited()
        save.assert_not_called()

    async def test_apply_only_uses_cloudflare_dimension(self):
        vector = [1] * 1024
        with (
            patch.object(backfill, "pending_rows", return_value=[{"id": 1, "content": "เทศบาล"}]) as pending,
            patch.object(backfill, "embed_text", AsyncMock(return_value=vector)) as embed,
            patch.object(backfill, "save_vector", return_value=True) as save,
        ):
            self.assertEqual(await backfill.run(1, True, "public.pdf"), (1, 1))
        embed.assert_awaited_once_with("เทศบาล")
        save.assert_called_once_with(1, vector)
        pending.assert_called_once_with(None, 1, True, "public.pdf")

    async def test_apply_requires_one_source(self):
        with patch.object(backfill, "pending_rows") as pending, self.assertRaises(ValueError):
            await backfill.run(100, True)
        pending.assert_not_called()

    def test_backfill_write_rechecks_for_missing_vector(self):
        with patch.object(backfill.supabase, "table") as table:
            update = table.return_value.update.return_value
            update.eq.return_value.is_.return_value.execute.return_value = SimpleNamespace(data=[])
            self.assertFalse(backfill.save_vector(1, [1] * 1024))
        table.assert_called_once_with("documents")
        self.assertEqual(set(table.return_value.update.call_args.args[0]), {"embedding_cloudflare"})
        update.eq.assert_called_once_with("id", 1)
        update.eq.return_value.is_.assert_called_once_with("embedding_cloudflare", "null")
