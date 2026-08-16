import unittest

from bridge.boolean_parser import normalize_editorial_query, parse
from bridge.sources import _catalog_domains, _source_group_queries


class SourceCatalogTests(unittest.TestCase):
    def test_catalog_uses_public_sources_and_excludes_platforms(self):
        group = {
            "catalog_path": "config/AGENCIA_DE_NOTICIAS.md",
            "exclude_domains": ["facebook.com", "youtube.com", "bing.com"],
        }
        domains = _catalog_domains(group)
        self.assertIn("hcdn.gob.ar", domains)
        self.assertIn("senado.gob.ar", domains)
        self.assertIn("lanacion.com.ar", domains)
        self.assertNotIn("facebook.com", domains)
        self.assertNotIn("youtube.com", domains)
        self.assertNotIn("bing.com", domains)

    def test_catalog_queries_keep_boolean_expression_and_site_scope(self):
        group = {"domains": ["hcdn.gob.ar", "senado.gob.ar", "indec.gob.ar"], "max_domains_per_query": 2}
        queries = _source_group_queries(group, "(UCR OR LLA) AND economia")
        self.assertEqual(len(queries), 2)
        self.assertIn("site:hcdn.gob.ar", queries[0])
        self.assertIn("(UCR OR LLA) AND economia", queries[0])

    def test_catalog_job_uses_primary_query_without_expanding_all_pivots(self):
        from bridge.sources import build_jobs

        jobs = build_jobs({
            "google_news": {"enabled": False},
            "source_groups": [{"id": "catalog", "domains": ["hcdn.gob.ar"], "enabled": True}],
        }, ["UCR AND Salomón", "UCR", "Salomón"])
        self.assertEqual(len(jobs), 1)
        self.assertIn("UCR+AND+Salom%C3%B3n", jobs[0].url)
        self.assertNotIn("%28UCR%29", jobs[0].url)

    def test_pasted_territorial_lists_become_or_groups(self):
        raw = '("Saladillo: Lordén, Salomón, UCR") AND ("Provincia: Abad, Kicillof")'
        normalized = normalize_editorial_query(raw)
        self.assertEqual(normalized, '(("Lordén" OR "Salomón" OR "UCR")) AND (("Abad" OR "Kicillof"))')
        self.assertTrue(parse(normalized).evaluate("Salomón y Kicillof analizaron una agenda política"))


if __name__ == "__main__":
    unittest.main()
