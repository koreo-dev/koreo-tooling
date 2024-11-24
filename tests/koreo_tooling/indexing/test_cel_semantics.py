import unittest

from koreo_tooling.indexing.cel_semantics import (
    NodeDiagnostic,
    NodeInfo,
    RelativePosition,
    Severity,
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
                position=RelativePosition(node_line=0, offset=0, length=1),
                node_type="number",
                modifier=[],
            )
        ]

        self.assertListEqual(expected, nodes)

    def test_operator(self):
        nodes = parse("+")

        expected = [
            NodeInfo(
                key="+",
                position=RelativePosition(node_line=0, offset=0, length=1),
                node_type="operator",
                modifier=[],
            ),
        ]

        self.assertListEqual(expected, nodes)

    def test_symbol(self):
        nodes = parse("inputs")

        expected = [
            NodeInfo(
                key="inputs",
                position=RelativePosition(node_line=0, offset=0, length=6),
                node_type="variable",
                modifier=[],
            ),
        ]

        self.assertListEqual(expected, nodes)

    def test_quoted(self):
        nodes = parse("'this is a lot'")

        expected = [
            NodeInfo(
                key="'",
                position=RelativePosition(node_line=0, offset=0, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="this is a lot",
                position=RelativePosition(node_line=0, offset=1, length=13),
                node_type="string",
                modifier=[],
            ),
            NodeInfo(
                key="'",
                position=RelativePosition(node_line=0, offset=13, length=1),
                node_type="operator",
                modifier=[],
            ),
        ]

        self.assertListEqual(expected, nodes)

    def test_simple_formula(self):
        nodes = parse("1 + 1")

        expected = [
            NodeInfo(
                key="1",
                position=RelativePosition(node_line=0, offset=0, length=1),
                node_type="number",
                modifier=[],
            ),
            NodeInfo(
                key="+",
                position=RelativePosition(node_line=0, offset=2, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="1",
                position=RelativePosition(node_line=0, offset=2, length=1),
                node_type="number",
                modifier=[],
            ),
        ]

        self.assertListEqual(expected, nodes)

    def test_mismatched_quote(self):
        with self.assertRaises(RuntimeError):
            parse("'")

        with self.assertRaises(RuntimeError):
            parse('"')

    def test_seed_offset_multiline(self):
        nodes = parse(
            """1
      +
      1
""",
            seed_offset=15,
        )

        expected = [
            NodeInfo(
                key="1",
                position=RelativePosition(node_line=0, offset=15, length=1),
                node_type="number",
                modifier=[],
            ),
            NodeInfo(
                key="+",
                position=RelativePosition(node_line=1, offset=6, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="1",
                position=RelativePosition(node_line=1, offset=6, length=1),
                node_type="number",
                modifier=[],
            ),
        ]

        self.maxDiff = None
        self.assertListEqual(expected, nodes)

    def test_seed_line_multiline(self):
        nodes = parse(
            """      1
      +
      1
""",
            seed_line=2,
        )

        expected = [
            NodeInfo(
                key="1",
                position=RelativePosition(node_line=2, offset=6, length=1),
                node_type="number",
                modifier=[],
            ),
            NodeInfo(
                key="+",
                position=RelativePosition(node_line=1, offset=6, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="1",
                position=RelativePosition(node_line=1, offset=6, length=1),
                node_type="number",
                modifier=[],
            ),
        ]

        self.maxDiff = None
        self.assertListEqual(expected, nodes)

    def test_trailing_comma_single_line(self):
        nodes = parse('{"key": value,  }')
        expected = [
            # {
            NodeInfo(
                key="{",
                position=RelativePosition(node_line=0, offset=0, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key='"',
                position=RelativePosition(node_line=0, offset=1, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="key",
                position=RelativePosition(node_line=0, offset=1, length=3),
                node_type="property",
                modifier=[],
            ),
            NodeInfo(
                key='"',
                position=RelativePosition(node_line=0, offset=3, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key=":",
                position=RelativePosition(node_line=0, offset=1, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="value",
                position=RelativePosition(node_line=0, offset=2, length=5),
                node_type="variable",
                modifier=[],
            ),
            NodeInfo(
                key=",",
                position=RelativePosition(node_line=0, offset=5, length=1),
                node_type="operator",
                modifier=[],
                diagnostic=NodeDiagnostic(
                    message="Trailing commas are unsupported.", severity=Severity.error
                ),
            ),
            NodeInfo(
                key="}",
                position=RelativePosition(node_line=0, offset=3, length=1),
                node_type="operator",
                modifier=[],
            ),
        ]

        self.maxDiff = None
        self.assertListEqual(expected, nodes)

    def test_trailing_comma_multi_line(self):
        nodes = parse(
            """{
  "key": value,
}
"""
        )
        expected = [
            # {
            NodeInfo(
                key="{",
                position=RelativePosition(node_line=0, offset=0, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key='"',
                position=RelativePosition(node_line=1, offset=2, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="key",
                position=RelativePosition(node_line=0, offset=1, length=3),
                node_type="property",
                modifier=[],
            ),
            NodeInfo(
                key='"',
                position=RelativePosition(node_line=0, offset=3, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key=":",
                position=RelativePosition(node_line=0, offset=1, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="value",
                position=RelativePosition(node_line=0, offset=2, length=5),
                node_type="variable",
                modifier=[],
            ),
            NodeInfo(
                key=",",
                position=RelativePosition(node_line=0, offset=5, length=1),
                node_type="operator",
                modifier=[],
                diagnostic=NodeDiagnostic(
                    message="Trailing commas are unsupported.", severity=Severity.error
                ),
            ),
            NodeInfo(
                key="}",
                position=RelativePosition(node_line=1, offset=0, length=1),
                node_type="operator",
                modifier=[],
            ),
        ]

        self.maxDiff = None
        self.assertListEqual(expected, nodes)

    def test_complex_white_space(self):
        nodes = parse("    int('1717' )            +    9")

        expected = [
            NodeInfo(
                key="int",
                position=RelativePosition(node_line=0, offset=4, length=3),
                node_type="function",
                modifier=[],
            ),
            NodeInfo(
                key="(",
                position=RelativePosition(node_line=0, offset=3, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="'",
                position=RelativePosition(node_line=0, offset=1, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="1717",
                position=RelativePosition(node_line=0, offset=1, length=4),
                node_type="string",
                modifier=[],
            ),
            NodeInfo(
                key="'",
                position=RelativePosition(node_line=0, offset=4, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key=")",
                position=RelativePosition(node_line=0, offset=2, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="+",
                position=RelativePosition(node_line=0, offset=13, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="9",
                position=RelativePosition(node_line=0, offset=5, length=1),
                node_type="number",
                modifier=[],
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
                position=RelativePosition(node_line=1, offset=0, length=1),
                node_type="operator",
                modifier=[],
            ),
            #   "complicated.key.name": 'value',
            NodeInfo(
                key='"',
                position=RelativePosition(node_line=1, offset=2, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="complicated.key.name",
                position=RelativePosition(node_line=0, offset=1, length=20),
                node_type="property",
                modifier=[],
            ),
            NodeInfo(
                key='"',
                position=RelativePosition(node_line=0, offset=20, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key=":",
                position=RelativePosition(node_line=0, offset=1, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="'",
                position=RelativePosition(node_line=0, offset=2, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="value",
                position=RelativePosition(node_line=0, offset=1, length=5),
                node_type="string",
                modifier=[],
            ),
            NodeInfo(
                key="'",
                position=RelativePosition(node_line=0, offset=5, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key=",",
                position=RelativePosition(node_line=0, offset=1, length=1),
                node_type="operator",
                modifier=[],
            ),
            #   unquoted: "key",
            NodeInfo(
                key="unquoted",
                position=RelativePosition(node_line=1, offset=2, length=8),
                node_type="variable",
                modifier=[],
            ),
            NodeInfo(
                key=":",
                position=RelativePosition(node_line=0, offset=8, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key='"',
                position=RelativePosition(node_line=0, offset=2, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="key",
                position=RelativePosition(node_line=0, offset=1, length=3),
                node_type="string",
                modifier=[],
            ),
            NodeInfo(
                key='"',
                position=RelativePosition(node_line=0, offset=3, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key=",",
                position=RelativePosition(node_line=0, offset=1, length=1),
                node_type="operator",
                modifier=[],
            ),
            #   "formula": 1 + 8,
            NodeInfo(
                key='"',
                position=RelativePosition(node_line=1, offset=2, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="formula",
                position=RelativePosition(node_line=0, offset=1, length=7),
                node_type="property",
                modifier=[],
            ),
            NodeInfo(
                key='"',
                position=RelativePosition(node_line=0, offset=7, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key=":",
                position=RelativePosition(node_line=0, offset=1, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="1",
                position=RelativePosition(node_line=0, offset=2, length=1),
                node_type="number",
                modifier=[],
            ),
            NodeInfo(
                key="+",
                position=RelativePosition(node_line=0, offset=2, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="812",
                position=RelativePosition(node_line=0, offset=2, length=3),
                node_type="number",
                modifier=[],
            ),
            NodeInfo(
                key=",",
                position=RelativePosition(node_line=0, offset=3, length=1),
                node_type="operator",
                modifier=[],
            ),
            #   function: a.name()
            NodeInfo(
                key="function",
                position=RelativePosition(node_line=1, offset=2, length=8),
                node_type="variable",
                modifier=[],
            ),
            NodeInfo(
                key=":",
                position=RelativePosition(node_line=0, offset=8, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="a",
                position=RelativePosition(node_line=0, offset=2, length=1),
                node_type="variable",
                modifier=[],
            ),
            NodeInfo(
                key=".",
                position=RelativePosition(node_line=0, offset=1, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="name",
                position=RelativePosition(node_line=0, offset=1, length=4),
                node_type="function",
                modifier=[],
            ),
            NodeInfo(
                key="(",
                position=RelativePosition(node_line=0, offset=4, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key=")",
                position=RelativePosition(node_line=0, offset=1, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key=",",
                position=RelativePosition(node_line=0, offset=1, length=1),
                node_type="operator",
                modifier=[],
            ),
            #   "index": avar[2] + avar["key"]
            NodeInfo(
                key='"',
                position=RelativePosition(node_line=1, offset=2, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="index",
                position=RelativePosition(node_line=0, offset=1, length=5),
                node_type="property",
                modifier=[],
            ),
            NodeInfo(
                key='"',
                position=RelativePosition(node_line=0, offset=5, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key=":",
                position=RelativePosition(node_line=0, offset=1, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="avar",
                position=RelativePosition(node_line=0, offset=2, length=4),
                node_type="variable",
                modifier=[],
            ),
            NodeInfo(
                key="[",
                position=RelativePosition(node_line=0, offset=4, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="2",
                position=RelativePosition(node_line=0, offset=1, length=1),
                node_type="number",
                modifier=[],
            ),
            NodeInfo(
                key="]",
                position=RelativePosition(node_line=0, offset=1, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="+",
                position=RelativePosition(node_line=0, offset=2, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="avar",
                position=RelativePosition(node_line=0, offset=2, length=4),
                node_type="variable",
                modifier=[],
            ),
            NodeInfo(
                key="[",
                position=RelativePosition(node_line=0, offset=4, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key='"',
                position=RelativePosition(node_line=0, offset=1, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="key",
                position=RelativePosition(node_line=0, offset=1, length=3),
                node_type="string",
                modifier=[],
            ),
            NodeInfo(
                key='"',
                position=RelativePosition(node_line=0, offset=3, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="]",
                position=RelativePosition(node_line=0, offset=1, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key=",",
                position=RelativePosition(node_line=0, offset=1, length=1),
                node_type="operator",
                modifier=[],
            ),
            #   "entry": inputs.map(key, {key: 22})
            NodeInfo(
                key='"',
                position=RelativePosition(node_line=1, offset=2, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="entry",
                position=RelativePosition(node_line=0, offset=1, length=5),
                node_type="property",
                modifier=[],
            ),
            NodeInfo(
                key='"',
                position=RelativePosition(node_line=0, offset=5, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key=":",
                position=RelativePosition(node_line=0, offset=1, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="inputs",
                position=RelativePosition(node_line=0, offset=2, length=6),
                node_type="variable",
                modifier=[],
            ),
            NodeInfo(
                key=".",
                position=RelativePosition(node_line=0, offset=6, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="map",
                position=RelativePosition(node_line=0, offset=1, length=3),
                node_type="keyword",
                modifier=[],
            ),
            NodeInfo(
                key="(",
                position=RelativePosition(node_line=0, offset=3, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="key",
                position=RelativePosition(node_line=0, offset=1, length=3),
                node_type="variable",
                modifier=[],
            ),
            NodeInfo(
                key=",",
                position=RelativePosition(node_line=0, offset=3, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="{",
                position=RelativePosition(node_line=0, offset=2, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="key",
                position=RelativePosition(node_line=0, offset=1, length=3),
                node_type="variable",
                modifier=[],
            ),
            NodeInfo(
                key=":",
                position=RelativePosition(node_line=0, offset=3, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key="22",
                position=RelativePosition(node_line=0, offset=2, length=2),
                node_type="number",
                modifier=[],
            ),
            NodeInfo(
                key="}",
                position=RelativePosition(node_line=0, offset=2, length=1),
                node_type="operator",
                modifier=[],
            ),
            NodeInfo(
                key=")",
                position=RelativePosition(node_line=0, offset=1, length=1),
                node_type="operator",
                modifier=[],
            ),
            # }
            NodeInfo(
                key="}",
                position=RelativePosition(node_line=1, offset=0, length=1),
                node_type="operator",
                modifier=[],
            ),
        ]

        self.maxDiff = None
        self.assertListEqual(expected, tokens)
