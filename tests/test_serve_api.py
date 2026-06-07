import json
import io
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


class FakeAuthHandler:
    def __init__(self, authorization=None):
        self.headers = FakeHeaders({"Authorization": authorization} if authorization else {})
        self.client_address = ("127.0.0.1", 12345)
        self.wfile = io.BytesIO()
        self.status = None
        self.response_headers = {}

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        self.response_headers[name] = value

    def end_headers(self):
        pass


class ApiPathTests(unittest.TestCase):
    def test_versioned_aliases(self):
        self.assertEqual(serve.api_path("/api/v1/status"), "/scheduler/status")
        self.assertEqual(serve.api_path("/api/v1/rules"), "/scheduler/rules")
        self.assertEqual(serve.api_path("/api/v1/rules/example"), "/scheduler/rules/example")
        self.assertEqual(serve.api_path("/api/v1/scans"), "/scheduler/scan-now")
        self.assertEqual(serve.api_path("/api/v1/captures/example/report"), "/captures/example/report")
        self.assertEqual(serve.api_path("/api/v1/logs"), "/scheduler/logs")
        self.assertEqual(serve.api_path("/api/v1/satellite"), "/satellite")

    def test_legacy_paths_are_unchanged(self):
        self.assertEqual(serve.api_path("/scheduler/status"), "/scheduler/status")
        self.assertEqual(serve.api_path("/passes"), "/passes")

    def test_versioned_api_scope_mapping(self):
        self.assertEqual(serve.api_required_scope("GET", "/api/v1/status"), "read")
        self.assertEqual(serve.api_required_scope("POST", "/api/v1/rules"), "control")
        self.assertEqual(serve.api_required_scope("POST", "/api/v1/devices"), "devices:manage")
        self.assertEqual(serve.api_required_scope("DELETE", "/api/v1/tokens/tok_1"), "tokens:manage")

    @mock.patch("serve.authenticate_api_token", return_value=None)
    def test_versioned_api_rejects_missing_token(self, authenticate):
        handler = FakeAuthHandler()

        allowed = serve.authorize_versioned_request(handler, "GET", "/api/v1/status")

        self.assertFalse(allowed)
        self.assertEqual(handler.status, 401)
        self.assertIn("WWW-Authenticate", handler.response_headers)
        authenticate.assert_not_called()

    @mock.patch("serve.authenticate_api_token")
    def test_versioned_api_checks_scope(self, authenticate):
        authenticate.return_value = {"id": "tok_1", "name": "phone", "scopes": ["read"]}
        handler = FakeAuthHandler("Bearer secret")

        allowed = serve.authorize_versioned_request(handler, "POST", "/api/v1/scans")

        self.assertFalse(allowed)
        self.assertEqual(handler.status, 403)

    @mock.patch("serve.authenticate_api_token")
    def test_legacy_api_does_not_require_bearer(self, authenticate):
        handler = FakeAuthHandler()

        allowed = serve.authorize_versioned_request(handler, "POST", "/scheduler/scan-now")

        self.assertTrue(allowed)
        authenticate.assert_not_called()


class RadioFilterTests(unittest.TestCase):
    def test_amateur_designator_requires_boundary(self):
        self.assertTrue(serve.radio_name_matches("SAUDISAT 1C (SO-50)"))
        self.assertTrue(serve.radio_name_matches("FUNCUBE-1 (AO-73)"))
        self.assertFalse(serve.radio_name_matches("BEIDOU-3 IGSO-1"))


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


class SchedulerLogsTests(unittest.TestCase):
    def test_scheduler_logs_tails_scheduler_and_current_satdump_log(self):
        old_status = serve.STATUS_PATH
        old_commands = serve.COMMANDS_PATH
        old_scheduler_log = serve.SCHEDULER_LOG_PATH
        try:
            with tempfile.TemporaryDirectory(dir=os.path.expanduser("~")) as tmp:
                output = os.path.join(tmp, "capture")
                satdump_log = output + ".log"
                serve.STATUS_PATH = os.path.join(tmp, "status.json")
                serve.COMMANDS_PATH = os.path.join(tmp, "commands.json")
                serve.SCHEDULER_LOG_PATH = os.path.join(tmp, "scheduler.log")
                with open(serve.STATUS_PATH, "w", encoding="utf-8") as f:
                    json.dump({
                        "live": True,
                        "updated_at": "2026-06-05T01:00:00Z",
                        "current_job": {"output": output},
                    }, f)
                with open(serve.COMMANDS_PATH, "w", encoding="utf-8") as f:
                    json.dump([], f)
                with open(serve.SCHEDULER_LOG_PATH, "w", encoding="utf-8") as f:
                    f.write("scheduler one\nscheduler two\nscheduler three\n")
                with open(satdump_log, "w", encoding="utf-8") as f:
                    f.write("start\nSNR 12\nSYNCED\n")

                logs = serve.scheduler_logs(limit=2)

                self.assertEqual(logs["scheduler_log_path"], serve.SCHEDULER_LOG_PATH)
                self.assertEqual(logs["satdump_log_path"], satdump_log)
                self.assertEqual(logs["scheduler_tail"], ["scheduler two", "scheduler three"])
                self.assertEqual(logs["satdump_tail"], ["SNR 12", "SYNCED"])
                self.assertEqual(logs["signal_tail"], ["SNR 12", "SYNCED"])
        finally:
            serve.STATUS_PATH = old_status
            serve.COMMANDS_PATH = old_commands
            serve.SCHEDULER_LOG_PATH = old_scheduler_log


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
        predict_passes.side_effect = [
            [{
                "name": "test one",
                "aos": "2026-06-04T01:00:00Z",
                "los": "2026-06-04T01:10:00Z",
                "max_el": 20,
                "duration_s": 600,
            }],
            [{
                "name": "test two",
                "aos": "2026-06-04T02:00:00Z",
                "los": "2026-06-04T02:10:00Z",
                "max_el": 30,
                "duration_s": 600,
            }],
        ]

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

    @mock.patch("serve.select_tles", return_value=["selected TLE"])
    @mock.patch("serve.predict_passes")
    @mock.patch("serve.fetch_tle", return_value=("TLE data", "test"))
    @mock.patch("serve.parse_tles", return_value=["parsed TLE"])
    @mock.patch("serve.read_rules")
    def test_overlapping_upcoming_runs_trim_lower_priority_pass(
        self,
        read_rules,
        parse_tles,
        fetch_tle,
        predict_passes,
        select_tles,
    ):
        read_rules.return_value = [
            {"id": "low", "name": "Low", "type": "satellite_recurring", "norad": 1, "group": "radio"},
            {"id": "high", "name": "High", "type": "satellite_recurring", "norad": 2, "group": "radio"},
        ]
        predict_passes.side_effect = [
            [{
                "name": "low",
                "aos": "2026-06-04T01:00:00Z",
                "los": "2026-06-04T01:10:00Z",
                "max_el": 20,
                "duration_s": 600,
            }],
            [{
                "name": "high",
                "aos": "2026-06-04T01:05:00Z",
                "los": "2026-06-04T01:15:00Z",
                "max_el": 70,
                "duration_s": 600,
            }],
        ]

        runs = serve.upcoming_scheduler_runs(hours=12, limit_per_rule=1)

        self.assertEqual([run["rule_id"] for run in runs], ["low", "high"])
        self.assertTrue(runs[0]["partial"])
        self.assertEqual(runs[0]["fire_time"], "2026-06-04T00:59:30Z")
        self.assertEqual(runs[0]["end_time"], "2026-06-04T01:04:30Z")
        self.assertEqual(runs[0]["duration_s"], 300)
        self.assertEqual(runs[1].get("partial"), None)


if __name__ == "__main__":
    unittest.main()
