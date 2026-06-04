import json
import os
import sys
import tempfile
import unittest

sys.argv = ["test_serve_api.py"]
import serve


class FakeHeaders(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class FakeHandler:
    headers = FakeHeaders({
        "X-Remote-User": "cstahly",
        "X-Real-IP": "203.0.113.10",
        "X-Forwarded-For": "203.0.113.10",
        "User-Agent": "test-agent",
    })
    client_address = ("127.0.0.1", 12345)


class ApiPathTests(unittest.TestCase):
    def test_versioned_aliases(self):
        self.assertEqual(serve.api_path("/api/v1/status"), "/scheduler/status")
        self.assertEqual(serve.api_path("/api/v1/rules"), "/scheduler/rules")
        self.assertEqual(serve.api_path("/api/v1/rules/example"), "/scheduler/rules/example")
        self.assertEqual(serve.api_path("/api/v1/scans"), "/scheduler/scan-now")
        self.assertEqual(serve.api_path("/api/v1/captures/example/report"), "/captures/example/report")
        self.assertEqual(serve.api_path("/api/v1/satellite"), "/satellite")

    def test_legacy_paths_are_unchanged(self):
        self.assertEqual(serve.api_path("/scheduler/status"), "/scheduler/status")
        self.assertEqual(serve.api_path("/passes"), "/passes")


class AuditTests(unittest.TestCase):
    def test_append_and_read_audit(self):
        old_path = serve.AUDIT_PATH
        try:
            with tempfile.TemporaryDirectory() as tmp:
                serve.AUDIT_PATH = os.path.join(tmp, "audit.jsonl")
                serve.append_audit(FakeHandler(), "rule.upsert", "rule-1", {"enabled": True})
                records = serve.read_audit()
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]["action"], "rule.upsert")
                self.assertEqual(records[0]["target"], "rule-1")
                self.assertEqual(records[0]["actor"]["user"], "cstahly")
                with open(serve.AUDIT_PATH, encoding="utf-8") as f:
                    json.loads(f.readline())
        finally:
            serve.AUDIT_PATH = old_path


if __name__ == "__main__":
    unittest.main()
