import os
import stat
import tempfile
import unittest

import sdr_runtime


class RuntimeStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.original_paths = {
            name: getattr(sdr_runtime, name)
            for name in (
                "API_TOKENS_PATH",
                "EVENTS_PATH",
                "DEVICES_PATH",
                "NOTIFICATION_OUTBOX_PATH",
            )
        }
        for name in self.original_paths:
            setattr(sdr_runtime, name, os.path.join(self.tmp.name, name.lower()))

    def tearDown(self):
        for name, value in self.original_paths.items():
            setattr(sdr_runtime, name, value)
        self.tmp.cleanup()

    def test_token_secret_is_returned_once_and_hash_is_stored(self):
        created = sdr_runtime.create_api_token("phone", ["read", "control"])
        token = created["token"]

        listed = sdr_runtime.list_api_tokens()
        self.assertEqual(listed[0]["name"], "phone")
        self.assertNotIn("token", listed[0])
        self.assertNotIn("token_hash", listed[0])
        self.assertEqual(stat.S_IMODE(os.stat(sdr_runtime.API_TOKENS_PATH).st_mode), 0o600)

        principal = sdr_runtime.authenticate_api_token(token)
        self.assertEqual(principal["id"], created["id"])
        self.assertTrue(sdr_runtime.principal_has_scope(principal, "read"))
        self.assertTrue(sdr_runtime.principal_has_scope(principal, "control"))
        self.assertFalse(sdr_runtime.principal_has_scope(principal, "tokens:manage"))

        sdr_runtime.revoke_api_token(created["id"])
        self.assertIsNone(sdr_runtime.authenticate_api_token(token))

    def test_event_stream_and_notification_outbox(self):
        first = sdr_runtime.emit_event("scheduler.started", "test")
        second = sdr_runtime.emit_event(
            "capture.started",
            "test",
            {"name": "M2-4"},
            {"title": "Capture started", "body": "M2-4"},
        )

        self.assertEqual(sdr_runtime.read_events(after=first["id"]), [second])
        notifications = sdr_runtime.read_notifications(status="pending")
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]["event_id"], second["id"])
        self.assertEqual(notifications[0]["title"], "Capture started")

    def test_device_registration_redacts_push_token(self):
        device = sdr_runtime.register_device(
            {
                "name": "iPhone",
                "platform": "ios",
                "push_token": "secret-device-token",
                "preferences": {"capture.failed": True},
            },
            owner_token_id="tok_owner",
        )

        self.assertNotIn("push_token", device)
        self.assertEqual(device["push_token_suffix"], "ce-token")
        self.assertEqual(sdr_runtime.list_devices(), [device])
        self.assertEqual(sdr_runtime.delete_device(device["id"]), device)
        self.assertEqual(sdr_runtime.list_devices(), [])


if __name__ == "__main__":
    unittest.main()
