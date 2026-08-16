import unittest

from bridge.models import Evidence
from bridge.pipeline import canonical_url, deduplicate, item_allowed_by_policy, score_item
from bridge.boolean_parser import parse


class PipelineTests(unittest.TestCase):
    def test_tracking_parameters_are_removed(self):
        self.assertEqual(
            canonical_url("https://example.com/nota/?utm_source=x&id=2#parte"),
            "https://example.com/nota?id=2",
        )

    def test_near_identical_titles_are_merged(self):
        items = [
            Evidence("La UCR bonaerense realizo su convencion provincial", "https://a.test/1", "A"),
            Evidence("La UCR bonaerense realizó su convención provincial", "https://b.test/2", "B"),
        ]
        result = deduplicate(items)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].mentions, 2)
        self.assertEqual(result[0].corroborating_sources, ["A", "B"])

    def test_direct_source_replaces_news_redirect(self):
        items = [
            Evidence("Resolucion oficial UCR", "https://news.google.com/rss/a", "Google", domain="news.google.com"),
            Evidence("Resolución oficial UCR", "https://ucr.test/resolucion", "UCR", domain="ucr.test"),
        ]
        result = deduplicate(items)
        self.assertEqual(result[0].url, "https://ucr.test/resolucion")
        self.assertEqual(result[0].domain, "ucr.test")

    def test_editorial_policy_excludes_international_and_judicial_content(self):
        config = {
            "content_policy": {
                "enabled": True,
                "require_argentina_context": True,
                "domestic_domain_suffixes": [".gob.ar"],
                "argentina_markers": ["Argentina", "Saladillo"],
                "excluded_terms": ["Donald Trump", "juicio"],
            }
        }
        self.assertFalse(item_allowed_by_policy(Evidence("Donald Trump firmó un decreto", "https://x.test/1", "Medio"), config))
        self.assertFalse(item_allowed_by_policy(Evidence("Comenzó el juicio en Argentina", "https://x.test/2", "Medio"), config))
        self.assertFalse(item_allowed_by_policy(Evidence("Política de Colombia", "https://x.test/3", "Medio"), config))
        self.assertTrue(item_allowed_by_policy(Evidence("Nueva licitación en Saladillo", "https://x.test/4", "Medio"), config))
        self.assertTrue(item_allowed_by_policy(Evidence("Licitación pública", "https://argentina.gob.ar/1", "Argentina.gob.ar", domain="argentina.gob.ar"), config))

    def test_discovery_query_metadata_does_not_force_a_match(self):
        item = Evidence(
            "Resultado deportivo sin relación",
            "https://example.test/deportes",
            "Medio",
            discovered_by="Argentina AND licitación AND salud",
        )
        self.assertFalse(parse("Argentina AND licitación").evaluate(item.searchable_text()))

    def test_news_media_is_not_marked_as_an_official_source(self):
        media = Evidence("Argentina anunció una medida", "https://clarin.com/nota", "Clarín", domain="clarin.com")
        government = Evidence("Argentina anunció una medida", "https://argentina.gob.ar/nota", "Argentina.gob.ar", domain="argentina.gob.ar")
        root = parse("Argentina")
        score_item(media, root, {}, {"argentina.gob.ar"}, (".gob.ar",))
        score_item(government, root, {}, {"argentina.gob.ar"}, (".gob.ar",))
        self.assertFalse(media.official)
        self.assertTrue(government.official)


if __name__ == "__main__":
    unittest.main()
