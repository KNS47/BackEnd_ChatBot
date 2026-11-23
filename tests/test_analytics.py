import os
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-placeholder")
os.environ.setdefault("SESSION_SECRET", "test-placeholder")

from routes import analytics


class Query:
    def __init__(self, rows, request):
        self.rows = rows
        self.request = request

    def select(self, fields):
        self.request["fields"] = fields
        return self

    def order(self, field):
        self.request["order"] = field
        return self

    def limit(self, maximum):
        self.request["limit"] = maximum
        return self

    def gte(self, key, value):
        self.request[(key, "gte")] = value
        return self

    def lt(self, key, value):
        self.request[(key, "lt")] = value
        return self

    def eq(self, key, value):
        self.request[(key, "eq")] = value
        return self

    def gt(self, key, value):
        self.request[(key, "gt")] = value
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows)


class AnalyticsTests(unittest.TestCase):
    def test_bangkok_day_after_1700_utc_and_search_boundaries(self):
        dates = (date(2026, 11, 23), date(2026, 11, 24))
        self.assertEqual(analytics._utc_midnight(dates[0]), "2026-11-22T17:00:00")
        self.assertEqual(analytics._by_day([
            {"created_at": "2026-11-23T16:59:59"},
            {"created_at": "2026-11-23T17:00:00Z"},
        ], dates, "count"), [
            {"date": "2026-11-23", "count": 1},
            {"date": "2026-11-24", "count": 1},
        ])

    def test_keyset_continues_through_short_pages(self):
        pages = iter([[{"id": "a", "category": "forms"}], [{"id": "b", "category": "forms"}], []])
        requests = []

        def table(name):
            request = {"table": name}
            requests.append(request)
            return Query(next(pages), request)

        dates = (date(2026, 11, 23), date(2026, 11, 23))
        with patch.object(analytics.supabase, "table", side_effect=table):
            rows = list(analytics._rows("chat_analytics", "category", dates, "forms"))
        self.assertEqual([row["id"] for row in rows], ["a", "b"])
        self.assertEqual(requests[0][("created_at", "gte")], "2026-11-22T17:00:00")
        self.assertEqual(requests[0][("created_at", "lt")], "2026-11-23T17:00:00")
        self.assertEqual(requests[0][("category", "eq")], "forms")
        self.assertEqual(requests[1][("id", "gt")], "a")
        self.assertEqual(requests[2][("id", "gt")], "b")

    def test_invalid_ranges_rejected(self):
        for start, end in [
            ("text", None),
            ("2026-11-24", "2026-11-23"),
            ("2024-01-01", "2026-01-01"),
            ("0001-01-01", "0001-01-01"),
        ]:
            with self.subTest(start=start, end=end), self.assertRaises(HTTPException):
                analytics._date_range(start, end)

    def test_api_returns_expected_shape_and_validates_limit(self):
        app = FastAPI()
        app.include_router(analytics.router)
        app.dependency_overrides[analytics.verify_admin] = lambda: "test"
        with TestClient(app) as client:
            with patch.object(analytics, "_rows", return_value=iter([{"question": "forms"}])):
                self.assertEqual(client.get("/analytics/top-questions").json(), [{"question": "forms", "count": 1}])
            self.assertEqual(client.get("/analytics/top-questions?limit=101").status_code, 422)
            self.assertEqual(client.get("/analytics/summary?start=bad").status_code, 422)
