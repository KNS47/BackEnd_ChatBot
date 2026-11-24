import unittest
from types import SimpleNamespace
from unittest.mock import patch

import middleware


def _request(forwarded=None, peer="10.0.0.1"):
    headers = {"x-forwarded-for": forwarded} if forwarded is not None else {}
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host=peer))


class ClientIpTests(unittest.TestCase):
    def test_without_trusted_proxy_uses_peer_address(self):
        with patch.object(middleware, "PROXY_HOPS", 0):
            self.assertEqual(middleware.client_ip(_request("203.0.113.9")), "10.0.0.1")

    def test_trusted_proxy_uses_entry_it_appended(self):
        with patch.object(middleware, "PROXY_HOPS", 1):
            self.assertEqual(middleware.client_ip(_request("203.0.113.9")), "203.0.113.9")

    def test_spoofed_leading_entries_are_ignored(self):
        with patch.object(middleware, "PROXY_HOPS", 1):
            self.assertEqual(middleware.client_ip(_request("1.2.3.4, 203.0.113.9")), "203.0.113.9")

    def test_missing_header_falls_back_to_peer(self):
        with patch.object(middleware, "PROXY_HOPS", 1):
            self.assertEqual(middleware.client_ip(_request()), "10.0.0.1")


if __name__ == "__main__":
    unittest.main()
