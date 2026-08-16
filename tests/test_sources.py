import unittest

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


if __name__ == "__main__":
    unittest.main()
