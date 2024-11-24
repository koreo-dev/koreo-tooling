import unittest

from koreo_tooling.indexing.cel_semantics import (
    NodeInfo,
    RelativePosition,
    parse,
)


class TestParse(unittest.TestCase):
    def test_empty_cel(self):
        nodes = parse("")
        self.assertListEqual([], nodes)

    def test_simple_number(self):
        nodes = parse("1")

        expected = [
            NodeInfo(
                key="1",
                position=RelativePosition(line_offset=0, char_offset=0, length=1),
                node_type="number",
                modifier=[],
                children=None,
            )
        ]

        self.assertListEqual(expected, nodes)

    def test_operator(self):
        nodes = parse("+")

        expected = [
            NodeInfo(
                key="+",
                position=RelativePosition(line_offset=0, char_offset=0, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
        ]

        self.assertListEqual(expected, nodes)

    def test_symbol(self):
        nodes = parse("inputs")

        expected = [
            NodeInfo(
                key="inputs",
                position=RelativePosition(line_offset=0, char_offset=0, length=6),
                node_type="variable",
                modifier=[],
                children=None,
            ),
        ]

        self.assertListEqual(expected, nodes)

    def test_quoted(self):
        nodes = parse("'this is a lot'")

        expected = [
            NodeInfo(
                key="'",
                position=RelativePosition(line_offset=0, char_offset=0, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="this is a lot",
                position=RelativePosition(line_offset=0, char_offset=1, length=13),
                node_type="string",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="'",
                position=RelativePosition(line_offset=0, char_offset=13, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
        ]

        self.assertListEqual(expected, nodes)

    def test_mismatched_quote(self):
        with self.assertRaises(RuntimeError):
            parse("'")

        with self.assertRaises(RuntimeError):
            parse('"')

    def test_simple_formula(self):
        nodes = parse("1 + 1")

        expected = [
            NodeInfo(
                key="1",
                position=RelativePosition(line_offset=0, char_offset=0, length=1),
                node_type="number",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="+",
                position=RelativePosition(line_offset=0, char_offset=2, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="1",
                position=RelativePosition(line_offset=0, char_offset=2, length=1),
                node_type="number",
                modifier=[],
                children=None,
            ),
        ]

        self.assertListEqual(expected, nodes)

    def test_complex_white_space(self):
        nodes = parse("    int('1717' )            +    9")

        expected = [
            NodeInfo(
                key="int",
                position=RelativePosition(line_offset=0, char_offset=4, length=3),
                node_type="function",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="(",
                position=RelativePosition(line_offset=0, char_offset=3, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="'",
                position=RelativePosition(line_offset=0, char_offset=1, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="1717",
                position=RelativePosition(line_offset=0, char_offset=1, length=4),
                node_type="string",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="'",
                position=RelativePosition(line_offset=0, char_offset=4, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key=")",
                position=RelativePosition(line_offset=0, char_offset=2, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="+",
                position=RelativePosition(line_offset=0, char_offset=13, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="9",
                position=RelativePosition(line_offset=0, char_offset=5, length=1),
                node_type="number",
                modifier=[],
                children=None,
            ),
        ]

        self.maxDiff = None
        self.assertListEqual(expected, nodes)

    def test_complex_multiline(self):
        tokens = parse(
            """
{
  "complicated.key.name": 'value',
  unquoted: "key",
  "formula": 1 + 812,
  function: a.name(),
  "index": avar[2] + avar["key"],
  "entry": inputs.map(key, {key: 22})
}
"""
        )

        expected = [
            # {
            NodeInfo(
                key="{",
                position=RelativePosition(line_offset=1, char_offset=0, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            #   "complicated.key.name": 'value',
            NodeInfo(
                key='"',
                position=RelativePosition(line_offset=1, char_offset=2, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="complicated.key.name",
                position=RelativePosition(line_offset=0, char_offset=1, length=20),
                node_type="property",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key='"',
                position=RelativePosition(line_offset=0, char_offset=20, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key=":",
                position=RelativePosition(line_offset=0, char_offset=1, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="'",
                position=RelativePosition(line_offset=0, char_offset=2, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="value",
                position=RelativePosition(line_offset=0, char_offset=1, length=5),
                node_type="string",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="'",
                position=RelativePosition(line_offset=0, char_offset=5, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key=",",
                position=RelativePosition(line_offset=0, char_offset=1, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            #   unquoted: "key",
            NodeInfo(
                key="unquoted",
                position=RelativePosition(line_offset=1, char_offset=2, length=8),
                node_type="variable",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key=":",
                position=RelativePosition(line_offset=0, char_offset=8, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key='"',
                position=RelativePosition(line_offset=0, char_offset=2, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="key",
                position=RelativePosition(line_offset=0, char_offset=1, length=3),
                node_type="string",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key='"',
                position=RelativePosition(line_offset=0, char_offset=3, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key=",",
                position=RelativePosition(line_offset=0, char_offset=1, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            #   "formula": 1 + 8,
            NodeInfo(
                key='"',
                position=RelativePosition(line_offset=1, char_offset=2, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="formula",
                position=RelativePosition(line_offset=0, char_offset=1, length=7),
                node_type="property",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key='"',
                position=RelativePosition(line_offset=0, char_offset=7, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key=":",
                position=RelativePosition(line_offset=0, char_offset=1, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="1",
                position=RelativePosition(line_offset=0, char_offset=2, length=1),
                node_type="number",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="+",
                position=RelativePosition(line_offset=0, char_offset=2, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="812",
                position=RelativePosition(line_offset=0, char_offset=2, length=3),
                node_type="number",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key=",",
                position=RelativePosition(line_offset=0, char_offset=3, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            #   function: a.name()
            NodeInfo(
                key="function",
                position=RelativePosition(line_offset=1, char_offset=2, length=8),
                node_type="variable",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key=":",
                position=RelativePosition(line_offset=0, char_offset=8, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="a",
                position=RelativePosition(line_offset=0, char_offset=2, length=1),
                node_type="variable",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key=".",
                position=RelativePosition(line_offset=0, char_offset=1, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="name",
                position=RelativePosition(line_offset=0, char_offset=1, length=4),
                node_type="function",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="(",
                position=RelativePosition(line_offset=0, char_offset=4, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key=")",
                position=RelativePosition(line_offset=0, char_offset=1, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key=",",
                position=RelativePosition(line_offset=0, char_offset=1, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            #   "index": avar[2] + avar["key"]
            NodeInfo(
                key='"',
                position=RelativePosition(line_offset=1, char_offset=2, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="index",
                position=RelativePosition(line_offset=0, char_offset=1, length=5),
                node_type="property",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key='"',
                position=RelativePosition(line_offset=0, char_offset=5, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key=":",
                position=RelativePosition(line_offset=0, char_offset=1, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="avar",
                position=RelativePosition(line_offset=0, char_offset=2, length=4),
                node_type="variable",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="[",
                position=RelativePosition(line_offset=0, char_offset=4, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="2",
                position=RelativePosition(line_offset=0, char_offset=1, length=1),
                node_type="number",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="]",
                position=RelativePosition(line_offset=0, char_offset=1, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="+",
                position=RelativePosition(line_offset=0, char_offset=2, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="avar",
                position=RelativePosition(line_offset=0, char_offset=2, length=4),
                node_type="variable",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="[",
                position=RelativePosition(line_offset=0, char_offset=4, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key='"',
                position=RelativePosition(line_offset=0, char_offset=1, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="key",
                position=RelativePosition(line_offset=0, char_offset=1, length=3),
                node_type="string",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key='"',
                position=RelativePosition(line_offset=0, char_offset=3, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="]",
                position=RelativePosition(line_offset=0, char_offset=1, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key=",",
                position=RelativePosition(line_offset=0, char_offset=1, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            #   "entry": inputs.map(key, {key: 22})
            NodeInfo(
                key='"',
                position=RelativePosition(line_offset=1, char_offset=2, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="entry",
                position=RelativePosition(line_offset=0, char_offset=1, length=5),
                node_type="property",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key='"',
                position=RelativePosition(line_offset=0, char_offset=5, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key=":",
                position=RelativePosition(line_offset=0, char_offset=1, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="inputs",
                position=RelativePosition(line_offset=0, char_offset=2, length=6),
                node_type="variable",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key=".",
                position=RelativePosition(line_offset=0, char_offset=6, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="map",
                position=RelativePosition(line_offset=0, char_offset=1, length=3),
                node_type="keyword",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="(",
                position=RelativePosition(line_offset=0, char_offset=3, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="key",
                position=RelativePosition(line_offset=0, char_offset=1, length=3),
                node_type="variable",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key=",",
                position=RelativePosition(line_offset=0, char_offset=3, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="{",
                position=RelativePosition(line_offset=0, char_offset=2, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="key",
                position=RelativePosition(line_offset=0, char_offset=1, length=3),
                node_type="variable",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key=":",
                position=RelativePosition(line_offset=0, char_offset=3, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="22",
                position=RelativePosition(line_offset=0, char_offset=2, length=2),
                node_type="number",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key="}",
                position=RelativePosition(line_offset=0, char_offset=2, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            NodeInfo(
                key=")",
                position=RelativePosition(line_offset=0, char_offset=1, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
            # }
            NodeInfo(
                key="}",
                position=RelativePosition(line_offset=1, char_offset=0, length=1),
                node_type="operator",
                modifier=[],
                children=None,
            ),
        ]

        self.maxDiff = None
        self.assertListEqual(expected, tokens)
