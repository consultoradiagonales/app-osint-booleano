import unittest

from bridge.boolean_parser import BooleanSyntaxError, coverage, discovery_queries, parse


class BooleanParserTests(unittest.TestCase):
    def test_precedence(self):
        root = parse("UCR OR radicalismo AND convencion")
        self.assertTrue(root.evaluate("UCR"))
        self.assertTrue(root.evaluate("radicalismo convencion"))
        self.assertFalse(root.evaluate("radicalismo"))

    def test_parentheses_and_not(self):
        root = parse('(UCR OR "Union Civica Radical") AND convencion NOT nacional')
        self.assertTrue(root.evaluate("UCR convencion bonaerense"))
        self.assertFalse(root.evaluate("UCR convencion nacional"))

    def test_aliases(self):
        root = parse("UCR AND Buenos_Aires")
        aliases = {"UCR": ["radicalismo"], "Buenos_Aires": ["bonaerense"]}
        self.assertTrue(root.evaluate("El radicalismo bonaerense se reunio", aliases))

    def test_syntax_error(self):
        with self.assertRaises(BooleanSyntaxError):
            parse("UCR AND (convencion OR autoridades")

    def test_discovery_is_bounded(self):
        root = parse("UCR AND convencion")
        pivots = discovery_queries("UCR AND convencion", root, {"UCR": ["radicalismo"]}, limit=3)
        self.assertEqual(len(pivots), 3)
        self.assertEqual(pivots[0], "UCR AND convencion")

    def test_coverage_respects_or_branches(self):
        root = parse("UCR AND (convencion OR autoridades OR alianzas)")
        self.assertEqual(coverage(root, "UCR convencion bonaerense"), 1.0)


if __name__ == "__main__":
    unittest.main()
