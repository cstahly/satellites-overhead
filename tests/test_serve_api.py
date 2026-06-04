import json
import os
import sys
import tempfile
import unittest
from unittest import mock

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


class UpcomingRunsTests(unittest.TestCase):
    @mock.patch("serve.select_tles", return_value=["selected TLE"])
    @mock.patch("serve.predict_passes")
    @mock.patch("serve.fetch_tle", return_value=("TLE data", "test"))
    @mock.patch("serve.parse_tles", return_value=["parsed TLE"])
    @mock.patch("serve.read_rules")
    def test_reuses_parsed_tle_group(
        self,
        read_rules,
        parse_tles,
        fetch_tle,
        predict_passes,
        select_tles,
    ):
        read_rules.return_value = [
            {"id": "one", "type": "satellite_recurring", "norad": 1, "group": "radio"},
            {"id": "two", "type": "satellite_recurring", "norad": 2, "group": "radio"},
        ]
        predict_passes.return_value = [{
            "name": "test",
            "aos": "2026-06-04T01:00:00Z",
            "los": "2026-06-04T01:10:00Z",
            "max_el": 20,
            "duration_s": 600,
        }]

        runs = serve.upcoming_scheduler_runs(hours=12, limit_per_rule=1)

        self.assertEqual(len(runs), 2)
        fetch_tle.assert_called_once_with("radio")
        parse_tles.assert_called_once_with("TLE data")
        self.assertEqual(select_tles.call_count, 2)
        self.assertEqual(predict_passes.call_count, 2)

    @mock.patch("serve.fetch_tle", side_effect=RuntimeError("TLE unavailable"))
    @mock.patch("serve.read_rules")
    def test_returns_per_rule_prediction_error(self, read_rules, fetch_tle):
        read_rules.return_value = [
            {"id": "one", "name": "One", "type": "satellite_recurring", "norad": 1, "group": "radio"},
        ]

        runs = serve.upcoming_scheduler_runs(hours=12, limit_per_rule=1)

        self.assertEqual(runs, [{
            "rule_id": "one",
            "name": "One",
            "norad": 1,
            "prediction_error": "TLE unavailable",
        }])


if __name__ == "__main__":
    unittest.main()
