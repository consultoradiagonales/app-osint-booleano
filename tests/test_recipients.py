from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from bridge.notifier import build_email_message, create_calendar_invite, email_status, send_email_alert
from bridge.recipients import RecipientStore, normalize_email


class RecipientTests(unittest.TestCase):
    def test_validate_and_crud(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RecipientStore(Path(directory) / "test.sqlite3")
            recipient = store.add(" Cliente@Example.com ", "Cliente Uno")
            self.assertEqual(recipient["email"], "cliente@example.com")
            self.assertTrue(recipient["enabled"])
            updated = store.update(recipient["id"], enabled=False)
            self.assertFalse(updated["enabled"])
            self.assertEqual(store.list(enabled_only=True), [])
            store.delete(recipient["id"])
            self.assertEqual(store.list(), [])

    def test_rejects_invalid_and_duplicate_email(self):
        with self.assertRaises(ValueError):
            normalize_email("correo-invalido")
        with tempfile.TemporaryDirectory() as directory:
            store = RecipientStore(Path(directory) / "test.sqlite3")
            store.add("a@example.com")
            with self.assertRaises(ValueError):
                store.add("A@example.com")

    @patch("bridge.notifier.get_smtp_password", return_value="")
    @patch("bridge.notifier._setting", return_value="")
    @patch.dict(os.environ, {}, clear=True)
    def test_missing_smtp_is_reported_without_network(self, _setting_mock, _password_mock):
        self.assertFalse(email_status()["configured"])
        result = send_email_alert(["a@example.com"], "Prueba", "Texto")
        self.assertEqual(result[0]["status"], "skipped")

    def test_delivery_log(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RecipientStore(Path(directory) / "test.sqlite3")
            store.log_delivery("a@example.com", "ucr", "Alerta", "sent")
            deliveries = store.deliveries()
            self.assertEqual(deliveries[0]["status"], "sent")
            self.assertEqual(deliveries[0]["watch_id"], "ucr")

    def test_email_contains_clickable_link_and_calendar_invite(self):
        message = build_email_message(
            "alertas@example.com",
            "cliente@example.com",
            "ALERTA UCR",
            "Hallazgo\nhttps://example.com/nota?id=1",
        )
        rendered = message.as_string()
        self.assertIn("text/html", rendered)
        self.assertIn("text/calendar", rendered)
        self.assertIn("alerta_osint_booleano.ics", rendered)

    def test_calendar_invite_targets_recipient_and_contains_url(self):
        invite = create_calendar_invite(
            "ALERTA UCR",
            "Hallazgo\nhttps://example.com/nota",
            "cliente@example.com",
            "alertas@example.com",
        )
        self.assertIn("METHOD:REQUEST", invite)
        self.assertIn("ATTENDEE;CN=cliente@example.com;RSVP=FALSE:mailto:cliente@example.com", invite)
        self.assertIn("URL:https://example.com/nota", invite)


if __name__ == "__main__":
    unittest.main()
