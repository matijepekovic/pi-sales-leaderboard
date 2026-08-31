#!/usr/bin/env python3
"""Deterministic contracts for Tableau workbook discovery."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
sys.path.insert(0, str(APP))

from sources import discovery  # noqa: E402


class FakeDiscoverySource:
    def __init__(self, responder):
        self.responder = responder
        self.requests = []
        self.signouts = []

    def _request(self, url, method="GET", token=None, body=None, timeout=60):
        self.requests.append({
            "url": url,
            "method": method,
            "token": token,
            "timeout": timeout,
        })
        return self.responder(url)

    def signout(self, base, token):
        self.signouts.append((base, token))


def payload(workbooks, total=None):
    data = {"workbooks": {"workbook": workbooks}}
    if total is not None:
        data["pagination"] = {
            "pageNumber": "1",
            "pageSize": str(discovery._DISCOVERY_PAGE_SIZE),
            "totalAvailable": str(total),
        }
    return json.dumps(data).encode()


class TableauWorkbookDiscoveryTests(unittest.TestCase):
    def test_workbooks_use_small_projected_pages_and_follow_pagination(self):
        first_page = [
            {"name": f"Workbook {index:03d}", "contentUrl": f"book-{index:03d}"}
            for index in range(discovery._DISCOVERY_PAGE_SIZE)
        ]

        def responder(url):
            query = parse_qs(urlsplit(url).query)
            page_number = int(query.get("pageNumber", ["1"])[0])
            if page_number == 1:
                return 200, payload(first_page, total=len(first_page) + 1)
            if page_number == 2:
                return 200, payload(
                    [{"name": "A Final Workbook", "contentUrl": "book-final"}],
                    total=len(first_page) + 1,
                )
            raise AssertionError(f"Unexpected discovery page {page_number}")

        source = FakeDiscoverySource(responder)
        with patch.object(
            discovery,
            "_signed_in",
            return_value=(source, "https://tableau.example/api/3.29", "token", "site"),
        ):
            rows = discovery.list_workbooks({})

        workbook_requests = [
            item for item in source.requests if "/workbooks" in item["url"]
        ]
        self.assertEqual(len(workbook_requests), 2)
        for item in workbook_requests:
            query = parse_qs(urlsplit(item["url"]).query)
            self.assertEqual(
                query["pageSize"], [str(discovery._DISCOVERY_PAGE_SIZE)]
            )
            self.assertEqual(query["fields"], ["name,contentUrl"])
            self.assertEqual(item["timeout"], discovery._DISCOVERY_TIMEOUT_SECONDS)

        self.assertEqual(rows[0]["name"], "A Final Workbook")
        self.assertEqual(len(rows), discovery._DISCOVERY_PAGE_SIZE + 1)
        self.assertEqual(source.signouts, [("https://tableau.example/api/3.29", "token")])

    def test_empty_site_list_keeps_the_existing_user_fallback_bounded(self):
        def responder(url):
            parsed = urlsplit(url)
            query = parse_qs(parsed.query)
            if parsed.path.endswith("/workbooks") and "/users/" not in parsed.path:
                return 200, payload([], total=0)
            if parsed.path.endswith("/users"):
                self.assertEqual(query["pageSize"], ["1"])
                self.assertEqual(query["fields"], ["id"])
                return 200, json.dumps({
                    "users": {"user": [{"id": "user-1"}]}
                }).encode()
            if parsed.path.endswith("/users/user-1/workbooks"):
                return 200, payload([
                    {"name": "Fallback Workbook", "contentUrl": "fallback"}
                ], total=1)
            raise AssertionError(f"Unexpected request: {url}")

        source = FakeDiscoverySource(responder)
        with patch.object(
            discovery,
            "_signed_in",
            return_value=(source, "https://tableau.example/api/3.29", "token", "site"),
        ):
            rows = discovery.list_workbooks({})

        self.assertEqual(rows, [
            {"name": "Fallback Workbook", "content_url": "fallback"}
        ])
        self.assertTrue(all(
            item["timeout"] == discovery._DISCOVERY_TIMEOUT_SECONDS
            for item in source.requests
        ))


if __name__ == "__main__":
    unittest.main()
