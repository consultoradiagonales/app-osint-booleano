from pathlib import Path
import tempfile
import unittest

from bridge.models import Evidence
from bridge.notifier import create_ics
from bridge.watcher import SeenStore, alert_title, build_alert_text


class WatcherTests(unittest.TestCase):
    def test_seen_store_only_returns_new_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SeenStore(Path(directory) / "watch.sqlite3")
            first = Evidence("Uno", "https://example.test/1?utm_source=x", "Fuente")
            second = Evidence("Dos", "https://example.test/2", "Fuente")
            self.assertEqual(len(store.unseen("ucr", [first, second])), 2)
            store.mark("ucr", [first])
            unseen = store.unseen("ucr", [first, second])
            self.assertEqual([item.title for item in unseen], ["Dos"])

    def test_ics_contains_calendar_alarm_and_text(self):
        with tempfile.TemporaryDirectory() as directory:
            path = create_ics(directory, "ucr", "ALERTA UCR", "Hallazgo con enlace")
            content = path.read_text(encoding="utf-8")
            self.assertIn("BEGIN:VALARM", content)
            self.assertIn("SUMMARY:ALERTA UCR", content)
            self.assertIn("Hallazgo con enlace", content)

    def test_alert_text_is_bounded(self):
        items = [Evidence(f"Nota {index}", f"https://example.test/{index}", "Medio") for index in range(6)]
        text = build_alert_text("UCR", items, len(items), 2)
        self.assertIn("Nota 0", text)
        self.assertIn("Nota 1", text)
        self.assertNotIn("Nota 2", text)
        self.assertIn("4 hallazgo(s) adicional(es)", text)

    def test_alert_title_uses_consultora_brand_and_level(self):
        self.assertEqual(
            alert_title("media", "UCR"),
            "CABLE DE NOTICIAS CONSULTORA DIAGONALES: MEDIA · UCR",
        )
        text = build_alert_text("UCR", [Evidence("Nota", "https://example.test/1", "Medio")], 1, 10, "baja")
        self.assertTrue(text.startswith("CABLE DE NOTICIAS CONSULTORA DIAGONALES: BAJA · UCR"))


if __name__ == "__main__":
    unittest.main()
