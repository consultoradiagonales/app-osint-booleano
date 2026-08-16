from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import urlopen
from urllib.request import Request
from urllib.error import HTTPError
import json

from bridge.server import BridgeApp, make_handler


class ServerTests(unittest.TestCase):
    def test_programmed_watches_are_persistent_and_validated(self):
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as directory:
            watch_path = Path(directory) / "watches.json"
            watch_path.write_text('{"alert_mode":"outlook_or_ics","max_alert_items":5,"watches":[]}', encoding="utf-8")
            app = BridgeApp(
                str(root / "config" / "sources.json"),
                str(root / "config" / "aliases.json"),
                str(Path(directory) / "test.sqlite3"),
                str(watch_path),
            )
            created = app.add_watch({
                "label": "UCR cierre",
                "query": "UCR AND (convencion OR autoridades)",
                "since_days": 3,
                "minimum_relevance": 65,
            })
            self.assertEqual(created["id"], "ucr-cierre")
            self.assertTrue(app.list_watches()["watches"][0]["enabled"])
            app.update_watch(created["id"], {"enabled": False})
            self.assertFalse(app.list_watches()["watches"][0]["enabled"])
            with self.assertRaises(ValueError):
                app.add_watch({"label": "Inválida", "query": "UCR AND ("})
            app.delete_watch(created["id"])
            self.assertEqual(app.list_watches()["watches"], [])

    def test_health_endpoint(self):
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as directory:
            app = BridgeApp(
                str(root / "config" / "sources.json"),
                str(root / "config" / "aliases.json"),
                str(Path(directory) / "test.sqlite3"),
            )
            app.token = ""
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urlopen(f"http://127.0.0.1:{server.server_port}/api/bridge/health") as response:
                    payload = json.load(response)
                self.assertTrue(payload["ok"])
                self.assertFalse(payload["ai_used"])
                self.assertFalse(payload["paid_services_used"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_recipient_endpoints(self):
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as directory:
            app = BridgeApp(
                str(root / "config" / "sources.json"),
                str(root / "config" / "aliases.json"),
                str(Path(directory) / "test.sqlite3"),
            )
            app.token = ""
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}/api/bridge"
            try:
                request = Request(
                    f"{base}/recipients",
                    data=json.dumps({"email": "cliente@example.com", "name": "Cliente"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request) as response:
                    created = json.load(response)["recipient"]
                with urlopen(f"{base}/recipients") as response:
                    recipients = json.load(response)["recipients"]
                self.assertEqual(recipients[0]["email"], "cliente@example.com")

                request = Request(
                    f"{base}/recipients/{created['id']}",
                    data=b'{"enabled":false}',
                    headers={"Content-Type": "application/json"},
                    method="PATCH",
                )
                with urlopen(request) as response:
                    self.assertFalse(json.load(response)["recipient"]["enabled"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_mobile_panel_connects_locally_without_key(self):
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as directory:
            app = BridgeApp(
                str(root / "config" / "sources.json"),
                str(root / "config" / "aliases.json"),
                str(Path(directory) / "test.sqlite3"),
            )
            app.token = "test-mobile-token"
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(f"{base}/mobile") as response:
                    html = response.read().decode("utf-8")
                self.assertIn("Control móvil OSINT–BOOLEANO", html)
                self.assertIn("AGENCIA DE NOTICIAS", html)
                self.assertIn("consultora_diagonales_logo.png", html)

                with urlopen(f"{base}/api/bridge/runs") as response:
                    self.assertEqual(json.load(response), [])

                request = Request(
                    f"{base}/api/bridge/runs",
                    headers={"Authorization": "Bearer test-mobile-token"},
                )
                with urlopen(request) as response:
                    self.assertEqual(json.load(response), [])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_mobile_can_start_configured_watchers(self):
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as directory:
            app = BridgeApp(
                str(root / "config" / "sources.json"),
                str(root / "config" / "aliases.json"),
                str(Path(directory) / "test.sqlite3"),
            )
            app.token = "test-mobile-token"
            app.run_watchers = lambda: {
                "ok": True,
                "watchers": [{"watch_id": "ucr", "matched": 2, "new_items": 1}],
                "ai_used": False,
                "paid_services_used": False,
            }
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                request = Request(
                    f"http://127.0.0.1:{server.server_port}/api/bridge/watch/run",
                    data=b"{}",
                    headers={
                        "Authorization": "Bearer test-mobile-token",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                with urlopen(request) as response:
                    payload = json.load(response)
                self.assertTrue(payload["ok"])
                self.assertFalse(payload["ai_used"])
                self.assertEqual(payload["watchers"][0]["new_items"], 1)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
