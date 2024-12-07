import unittest

from koreo_tooling.indexing.cel_semantics import (
    NodeDiagnostic,
    SemanticNode,
    Position,
    Severity,
    parse,
)


class TestParse(unittest.TestCase):
    def test_empty_cel(self):
        anchor_base_pos = Position(line=0, character=0)
        nodes = parse([""], anchor_base_pos=anchor_base_pos)
        self.assertListEqual([], nodes)

    def test_simple_number(self):
        anchor_base_pos = Position(line=0, character=0)
        nodes = parse(["1"], anchor_base_pos=anchor_base_pos)

        expected = [
            SemanticNode(
                position=Position(line=0, character=0),
                anchor_rel=anchor_base_pos,
                length=1,
                node_type="number",
                modifier=[],
            )
        ]

        self.assertListEqual(expected, nodes)

    def test_operator(self):
        anchor_base_pos = Position(line=0, character=0)
        nodes = parse(["+"], anchor_base_pos=anchor_base_pos)

        expected = [
            SemanticNode(
                position=Position(line=0, character=0),
                anchor_rel=Position(line=0, character=0),
                length=1,
                node_type="operator",
                modifier=[],
            ),
        ]

        self.assertListEqual(expected, nodes)

    def test_symbol(self):
        anchor_base_pos = Position(line=0, character=0)
        nodes = parse(["inputs"], anchor_base_pos=anchor_base_pos)

        expected = [
            SemanticNode(
                position=Position(line=0, character=0),
                anchor_rel=Position(line=0, character=0),
                length=6,
                node_type="variable",
                modifier=[],
            ),
        ]

        self.assertListEqual(expected, nodes)

    def test_quoted(self):
        anchor_base_pos = Position(line=0, character=0)
        nodes = parse(["'this is a lot'"], anchor_base_pos=anchor_base_pos)

        expected = [
            SemanticNode(
                position=Position(line=0, character=0),
                anchor_rel=Position(line=0, character=0),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=0, character=1),
                length=13,
                node_type="string",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=13),
                anchor_rel=Position(line=0, character=14),
                length=1,
                node_type="operator",
                modifier=[],
            ),
        ]

        self.assertListEqual(expected, nodes)

    def test_simple_formula(self):
        anchor_base_pos = Position(line=0, character=0)
        nodes = parse(["1 + 1"], anchor_base_pos=anchor_base_pos)

        expected = [
            SemanticNode(
                position=Position(line=0, character=0),
                anchor_rel=Position(line=0, character=0),
                length=1,
                node_type="number",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=2),
                anchor_rel=Position(line=0, character=2),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=2),
                anchor_rel=Position(line=0, character=4),
                length=1,
                node_type="number",
                modifier=[],
            ),
        ]

        self.assertListEqual(expected, nodes)

    def test_mismatched_quote(self):
        anchor_base_pos = Position(line=0, character=0)
        with self.assertRaises(RuntimeError):
            parse(["'"], anchor_base_pos=anchor_base_pos)

        with self.assertRaises(RuntimeError):
            parse(['"'], anchor_base_pos=anchor_base_pos)

    def test_seed_offset_multiline(self):
        anchor_base_pos = Position(line=10, character=0)
        nodes = parse(
            ["1", "      +", "      1", ""],
            seed_offset=15,
            abs_offset=5,
            anchor_base_pos=anchor_base_pos,
        )

        expected = [
            SemanticNode(
                position=Position(line=0, character=15),
                anchor_rel=Position(line=10, character=20),
                length=1,
                node_type="number",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=1, character=6),
                anchor_rel=Position(line=11, character=6),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=1, character=6),
                anchor_rel=Position(line=12, character=6),
                length=1,
                node_type="number",
                modifier=[],
            ),
        ]

        self.maxDiff = None
        self.assertListEqual(expected, nodes)

    def test_seed_line_multiline(self):
        anchor_base_pos = Position(line=5, character=0)
        nodes = parse(
            ["      1", "      + ", "      1 ", ""],
            seed_line=2,
            anchor_base_pos=anchor_base_pos,
        )

        expected = [
            SemanticNode(
                position=Position(line=2, character=6),
                anchor_rel=Position(line=7, character=6),
                length=1,
                node_type="number",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=1, character=6),
                anchor_rel=Position(line=8, character=6),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=1, character=6),
                anchor_rel=Position(line=9, character=6),
                length=1,
                node_type="number",
                modifier=[],
            ),
        ]

        self.maxDiff = None
        self.assertListEqual(expected, nodes)

    def test_multiline_with_extra_newlines(self):
        anchor_base_pos = Position(line=13, character=0)
        nodes = parse(
            [
                "      1",
                "",
                "",
                "",
                "      +",
                "",
                "",
                "       ",
                "",
                "",
                "      1",
                "",
            ],
            seed_line=1,
            anchor_base_pos=anchor_base_pos,
        )

        expected = [
            SemanticNode(
                position=Position(line=1, character=6),
                anchor_rel=Position(line=14, character=6),
                length=1,
                node_type="number",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=4, character=6),
                anchor_rel=Position(line=18, character=6),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=6, character=6),
                anchor_rel=Position(line=24, character=6),
                length=1,
                node_type="number",
                modifier=[],
            ),
        ]

        self.maxDiff = None
        self.assertListEqual(expected, nodes)

    def test_trailing_comma_single_line(self):
        anchor_base_pos = Position(line=1, character=0)
        nodes = parse(['{"key": value,  }'], anchor_base_pos=anchor_base_pos)
        expected = [
            # {
            SemanticNode(
                position=Position(line=0, character=0),
                anchor_rel=Position(line=1, character=0),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=1, character=1),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=1, character=2),
                length=3,
                node_type="property",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=3),
                anchor_rel=Position(line=1, character=5),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=1, character=6),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=2),
                anchor_rel=Position(line=1, character=8),
                length=5,
                node_type="variable",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=5),
                anchor_rel=Position(line=1, character=13),
                length=1,
                node_type="operator",
                modifier=[],
                diagnostic=NodeDiagnostic(
                    message="Trailing commas are unsupported.", severity=Severity.error
                ),
            ),
            SemanticNode(
                position=Position(line=0, character=3),
                anchor_rel=Position(line=1, character=16),
                length=1,
                node_type="operator",
                modifier=[],
            ),
        ]

        self.maxDiff = None
        self.assertListEqual(expected, nodes)

    def test_trailing_comma_multi_line(self):
        anchor_base_pos = Position(line=2, character=0)
        nodes = parse(
            ["{", '  "key": value,', "}", ""], anchor_base_pos=anchor_base_pos
        )
        expected = [
            # {
            SemanticNode(
                position=Position(line=0, character=0),
                anchor_rel=Position(line=2, character=0),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=1, character=2),
                anchor_rel=Position(line=3, character=2),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=3, character=3),
                length=3,
                node_type="property",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=3),
                anchor_rel=Position(line=3, character=6),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=3, character=7),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=2),
                anchor_rel=Position(line=3, character=9),
                length=5,
                node_type="variable",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=5),
                anchor_rel=Position(line=3, character=14),
                length=1,
                node_type="operator",
                modifier=[],
                diagnostic=NodeDiagnostic(
                    message="Trailing commas are unsupported.", severity=Severity.error
                ),
            ),
            SemanticNode(
                position=Position(line=1, character=0),
                anchor_rel=Position(line=4, character=0),
                length=1,
                node_type="operator",
                modifier=[],
            ),
        ]

        self.maxDiff = None
        self.assertListEqual(expected, nodes)

    def test_complex_white_space(self):
        anchor_base_pos = Position(line=0, character=0)
        nodes = parse(
            ["    int('1717' )            +    9"], anchor_base_pos=anchor_base_pos
        )

        expected = [
            SemanticNode(
                position=Position(line=0, character=4),
                anchor_rel=Position(line=0, character=4),
                length=3,
                node_type="function",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=3),
                anchor_rel=Position(line=0, character=7),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=0, character=8),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=0, character=9),
                length=4,
                node_type="string",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=4),
                anchor_rel=Position(line=0, character=13),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=2),
                anchor_rel=Position(line=0, character=15),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=13),
                anchor_rel=Position(line=0, character=28),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=5),
                anchor_rel=Position(line=0, character=33),
                length=1,
                node_type="number",
                modifier=[],
            ),
        ]

        self.maxDiff = None
        self.assertListEqual(expected, nodes)

    def test_complex_multiline(self):
        anchor_base_pos = Position(line=3, character=0)
        tokens = parse(
            [
                "",
                "{",
                "  \"complicated.key.name\": 'value',",
                '  unquoted: "key",',
                '  "formula": 1 + 812,',
                "  function: a.name(),",
                '  "index": avar[2] + avar["key"],',
                '  "entry": inputs.map(key, {key: 22})',
                "}",
                "",
            ],
            anchor_base_pos=anchor_base_pos,
        )

        expected = [
            # {
            SemanticNode(
                position=Position(line=1, character=0),
                anchor_rel=Position(line=4, character=0),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            #   "complicated.key.name": 'value',
            SemanticNode(
                position=Position(line=1, character=2),
                anchor_rel=Position(line=5, character=2),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=5, character=3),
                length=20,
                node_type="property",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=20),
                anchor_rel=Position(line=5, character=23),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=5, character=24),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=2),
                anchor_rel=Position(line=5, character=26),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=5, character=27),
                length=5,
                node_type="string",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=5),
                anchor_rel=Position(line=5, character=32),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=5, character=33),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            #   unquoted: "key",
            SemanticNode(
                position=Position(line=1, character=2),
                anchor_rel=Position(line=6, character=2),
                length=8,
                node_type="variable",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=8),
                anchor_rel=Position(line=6, character=10),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=2),
                anchor_rel=Position(line=6, character=12),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=6, character=13),
                length=3,
                node_type="string",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=3),
                anchor_rel=Position(line=6, character=16),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=6, character=17),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            #   "formula": 1 + 8,
            SemanticNode(
                position=Position(line=1, character=2),
                anchor_rel=Position(line=7, character=2),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=7, character=3),
                length=7,
                node_type="property",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=7),
                anchor_rel=Position(line=7, character=10),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=7, character=11),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=2),
                anchor_rel=Position(line=7, character=13),
                length=1,
                node_type="number",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=2),
                anchor_rel=Position(line=7, character=15),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=2),
                anchor_rel=Position(line=7, character=17),
                length=3,
                node_type="number",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=3),
                anchor_rel=Position(line=7, character=20),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            #   function: a.name()
            SemanticNode(
                position=Position(line=1, character=2),
                anchor_rel=Position(line=8, character=2),
                length=8,
                node_type="variable",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=8),
                anchor_rel=Position(line=8, character=10),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=2),
                anchor_rel=Position(line=8, character=12),
                length=1,
                node_type="variable",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=8, character=13),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=8, character=14),
                length=4,
                node_type="function",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=4),
                anchor_rel=Position(line=8, character=18),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=8, character=19),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=8, character=20),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            #   "index": avar[2] + avar["key"]
            SemanticNode(
                position=Position(line=1, character=2),
                anchor_rel=Position(line=9, character=2),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=9, character=3),
                length=5,
                node_type="property",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=5),
                anchor_rel=Position(line=9, character=8),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=9, character=9),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=2),
                anchor_rel=Position(line=9, character=11),
                length=4,
                node_type="variable",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=4),
                anchor_rel=Position(line=9, character=15),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=9, character=16),
                length=1,
                node_type="number",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=9, character=17),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=2),
                anchor_rel=Position(line=9, character=19),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=2),
                anchor_rel=Position(line=9, character=21),
                length=4,
                node_type="variable",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=4),
                anchor_rel=Position(line=9, character=25),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=9, character=26),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=9, character=27),
                length=3,
                node_type="string",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=3),
                anchor_rel=Position(line=9, character=30),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=9, character=31),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=9, character=32),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            #   "entry": inputs.map(key, {key: 22})
            SemanticNode(
                position=Position(line=1, character=2),
                anchor_rel=Position(line=10, character=2),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=10, character=3),
                length=5,
                node_type="property",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=5),
                anchor_rel=Position(line=10, character=8),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=10, character=9),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=2),
                anchor_rel=Position(line=10, character=11),
                length=6,
                node_type="variable",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=6),
                anchor_rel=Position(line=10, character=17),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=10, character=18),
                length=3,
                node_type="keyword",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=3),
                anchor_rel=Position(line=10, character=21),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=10, character=22),
                length=3,
                node_type="variable",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=3),
                anchor_rel=Position(line=10, character=25),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=2),
                anchor_rel=Position(line=10, character=27),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=10, character=28),
                length=3,
                node_type="variable",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=3),
                anchor_rel=Position(line=10, character=31),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=2),
                anchor_rel=Position(line=10, character=33),
                length=2,
                node_type="number",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=2),
                anchor_rel=Position(line=10, character=35),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, character=1),
                anchor_rel=Position(line=10, character=36),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            # }
            SemanticNode(
                position=Position(line=1, character=0),
                anchor_rel=Position(line=11, character=0),
                length=1,
                node_type="operator",
                modifier=[],
            ),
        ]

        self.maxDiff = None
        self.assertListEqual(expected, tokens)
