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
        anchor_base_pos = Position(line=0, offset=0)
        nodes = parse([""], anchor_base_pos=anchor_base_pos)
        self.assertListEqual([], nodes)

    def test_simple_number(self):
        anchor_base_pos = Position(line=0, offset=0)
        nodes = parse(["1"], anchor_base_pos=anchor_base_pos)

        expected = [
            SemanticNode(
                position=Position(line=0, offset=0),
                anchor_rel=anchor_base_pos,
                length=1,
                node_type="number",
                modifier=[],
            )
        ]

        self.assertListEqual(expected, nodes)

    def test_operator(self):
        anchor_base_pos = Position(line=0, offset=0)
        nodes = parse(["+"], anchor_base_pos=anchor_base_pos)

        expected = [
            SemanticNode(
                position=Position(line=0, offset=0),
                anchor_rel=Position(line=0, offset=0),
                length=1,
                node_type="operator",
                modifier=[],
            ),
        ]

        self.assertListEqual(expected, nodes)

    def test_symbol(self):
        anchor_base_pos = Position(line=0, offset=0)
        nodes = parse(["inputs"], anchor_base_pos=anchor_base_pos)

        expected = [
            SemanticNode(
                position=Position(line=0, offset=0),
                anchor_rel=Position(line=0, offset=0),
                length=6,
                node_type="variable",
                modifier=[],
            ),
        ]

        self.assertListEqual(expected, nodes)

    def test_quoted(self):
        anchor_base_pos = Position(line=0, offset=0)
        nodes = parse(["'this is a lot'"], anchor_base_pos=anchor_base_pos)

        expected = [
            SemanticNode(
                position=Position(line=0, offset=0),
                anchor_rel=Position(line=0, offset=0),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=0, offset=1),
                length=13,
                node_type="string",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=13),
                anchor_rel=Position(line=0, offset=14),
                length=1,
                node_type="operator",
                modifier=[],
            ),
        ]

        self.assertListEqual(expected, nodes)

    def test_simple_formula(self):
        anchor_base_pos = Position(line=0, offset=0)
        nodes = parse(["1 + 1"], anchor_base_pos=anchor_base_pos)

        expected = [
            SemanticNode(
                position=Position(line=0, offset=0),
                anchor_rel=Position(line=0, offset=0),
                length=1,
                node_type="number",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=2),
                anchor_rel=Position(line=0, offset=2),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=2),
                anchor_rel=Position(line=0, offset=4),
                length=1,
                node_type="number",
                modifier=[],
            ),
        ]

        self.assertListEqual(expected, nodes)

    def test_mismatched_quote(self):
        anchor_base_pos = Position(line=0, offset=0)
        with self.assertRaises(RuntimeError):
            parse(["'"], anchor_base_pos=anchor_base_pos)

        with self.assertRaises(RuntimeError):
            parse(['"'], anchor_base_pos=anchor_base_pos)

    def test_seed_offset_multiline(self):
        anchor_base_pos = Position(line=10, offset=0)
        nodes = parse(
            ["1", "      +", "      1", ""],
            seed_offset=15,
            abs_offset=5,
            anchor_base_pos=anchor_base_pos,
        )

        expected = [
            SemanticNode(
                position=Position(line=0, offset=15),
                anchor_rel=Position(line=10, offset=20),
                length=1,
                node_type="number",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=1, offset=6),
                anchor_rel=Position(line=11, offset=6),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=1, offset=6),
                anchor_rel=Position(line=12, offset=6),
                length=1,
                node_type="number",
                modifier=[],
            ),
        ]

        self.maxDiff = None
        self.assertListEqual(expected, nodes)

    def test_seed_line_multiline(self):
        anchor_base_pos = Position(line=5, offset=0)
        nodes = parse(
            ["      1", "      + ", "      1 ", ""],
            seed_line=2,
            anchor_base_pos=anchor_base_pos,
        )

        expected = [
            SemanticNode(
                position=Position(line=2, offset=6),
                anchor_rel=Position(line=7, offset=6),
                length=1,
                node_type="number",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=1, offset=6),
                anchor_rel=Position(line=8, offset=6),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=1, offset=6),
                anchor_rel=Position(line=9, offset=6),
                length=1,
                node_type="number",
                modifier=[],
            ),
        ]

        self.maxDiff = None
        self.assertListEqual(expected, nodes)

    def test_multiline_with_extra_newlines(self):
        anchor_base_pos = Position(line=13, offset=0)
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
                position=Position(line=1, offset=6),
                anchor_rel=Position(line=14, offset=6),
                length=1,
                node_type="number",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=4, offset=6),
                anchor_rel=Position(line=18, offset=6),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=6, offset=6),
                anchor_rel=Position(line=24, offset=6),
                length=1,
                node_type="number",
                modifier=[],
            ),
        ]

        self.maxDiff = None
        self.assertListEqual(expected, nodes)

    def test_trailing_comma_single_line(self):
        anchor_base_pos = Position(line=1, offset=0)
        nodes = parse(['{"key": value,  }'], anchor_base_pos=anchor_base_pos)
        expected = [
            # {
            SemanticNode(
                position=Position(line=0, offset=0),
                anchor_rel=Position(line=1, offset=0),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=1, offset=1),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=1, offset=2),
                length=3,
                node_type="property",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=3),
                anchor_rel=Position(line=1, offset=5),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=1, offset=6),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=2),
                anchor_rel=Position(line=1, offset=8),
                length=5,
                node_type="variable",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=5),
                anchor_rel=Position(line=1, offset=13),
                length=1,
                node_type="operator",
                modifier=[],
                diagnostic=NodeDiagnostic(
                    message="Trailing commas are unsupported.", severity=Severity.error
                ),
            ),
            SemanticNode(
                position=Position(line=0, offset=3),
                anchor_rel=Position(line=1, offset=16),
                length=1,
                node_type="operator",
                modifier=[],
            ),
        ]

        self.maxDiff = None
        self.assertListEqual(expected, nodes)

    def test_trailing_comma_multi_line(self):
        anchor_base_pos = Position(line=2, offset=0)
        nodes = parse(
            ["{", '  "key": value,', "}", ""], anchor_base_pos=anchor_base_pos
        )
        expected = [
            # {
            SemanticNode(
                position=Position(line=0, offset=0),
                anchor_rel=Position(line=2, offset=0),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=1, offset=2),
                anchor_rel=Position(line=3, offset=2),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=3, offset=3),
                length=3,
                node_type="property",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=3),
                anchor_rel=Position(line=3, offset=6),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=3, offset=7),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=2),
                anchor_rel=Position(line=3, offset=9),
                length=5,
                node_type="variable",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=5),
                anchor_rel=Position(line=3, offset=14),
                length=1,
                node_type="operator",
                modifier=[],
                diagnostic=NodeDiagnostic(
                    message="Trailing commas are unsupported.", severity=Severity.error
                ),
            ),
            SemanticNode(
                position=Position(line=1, offset=0),
                anchor_rel=Position(line=4, offset=0),
                length=1,
                node_type="operator",
                modifier=[],
            ),
        ]

        self.maxDiff = None
        self.assertListEqual(expected, nodes)

    def test_complex_white_space(self):
        anchor_base_pos = Position(line=0, offset=0)
        nodes = parse(
            ["    int('1717' )            +    9"], anchor_base_pos=anchor_base_pos
        )

        expected = [
            SemanticNode(
                position=Position(line=0, offset=4),
                anchor_rel=Position(line=0, offset=4),
                length=3,
                node_type="function",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=3),
                anchor_rel=Position(line=0, offset=7),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=0, offset=8),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=0, offset=9),
                length=4,
                node_type="string",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=4),
                anchor_rel=Position(line=0, offset=13),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=2),
                anchor_rel=Position(line=0, offset=15),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=13),
                anchor_rel=Position(line=0, offset=28),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=5),
                anchor_rel=Position(line=0, offset=33),
                length=1,
                node_type="number",
                modifier=[],
            ),
        ]

        self.maxDiff = None
        self.assertListEqual(expected, nodes)

    def test_complex_multiline(self):
        anchor_base_pos = Position(line=3, offset=0)
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
                position=Position(line=1, offset=0),
                anchor_rel=Position(line=4, offset=0),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            #   "complicated.key.name": 'value',
            SemanticNode(
                position=Position(line=1, offset=2),
                anchor_rel=Position(line=5, offset=2),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=5, offset=3),
                length=20,
                node_type="property",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=20),
                anchor_rel=Position(line=5, offset=23),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=5, offset=24),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=2),
                anchor_rel=Position(line=5, offset=26),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=5, offset=27),
                length=5,
                node_type="string",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=5),
                anchor_rel=Position(line=5, offset=32),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=5, offset=33),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            #   unquoted: "key",
            SemanticNode(
                position=Position(line=1, offset=2),
                anchor_rel=Position(line=6, offset=2),
                length=8,
                node_type="variable",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=8),
                anchor_rel=Position(line=6, offset=10),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=2),
                anchor_rel=Position(line=6, offset=12),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=6, offset=13),
                length=3,
                node_type="string",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=3),
                anchor_rel=Position(line=6, offset=16),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=6, offset=17),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            #   "formula": 1 + 8,
            SemanticNode(
                position=Position(line=1, offset=2),
                anchor_rel=Position(line=7, offset=2),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=7, offset=3),
                length=7,
                node_type="property",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=7),
                anchor_rel=Position(line=7, offset=10),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=7, offset=11),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=2),
                anchor_rel=Position(line=7, offset=13),
                length=1,
                node_type="number",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=2),
                anchor_rel=Position(line=7, offset=15),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=2),
                anchor_rel=Position(line=7, offset=17),
                length=3,
                node_type="number",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=3),
                anchor_rel=Position(line=7, offset=20),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            #   function: a.name()
            SemanticNode(
                position=Position(line=1, offset=2),
                anchor_rel=Position(line=8, offset=2),
                length=8,
                node_type="variable",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=8),
                anchor_rel=Position(line=8, offset=10),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=2),
                anchor_rel=Position(line=8, offset=12),
                length=1,
                node_type="variable",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=8, offset=13),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=8, offset=14),
                length=4,
                node_type="function",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=4),
                anchor_rel=Position(line=8, offset=18),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=8, offset=19),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=8, offset=20),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            #   "index": avar[2] + avar["key"]
            SemanticNode(
                position=Position(line=1, offset=2),
                anchor_rel=Position(line=9, offset=2),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=9, offset=3),
                length=5,
                node_type="property",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=5),
                anchor_rel=Position(line=9, offset=8),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=9, offset=9),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=2),
                anchor_rel=Position(line=9, offset=11),
                length=4,
                node_type="variable",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=4),
                anchor_rel=Position(line=9, offset=15),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=9, offset=16),
                length=1,
                node_type="number",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=9, offset=17),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=2),
                anchor_rel=Position(line=9, offset=19),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=2),
                anchor_rel=Position(line=9, offset=21),
                length=4,
                node_type="variable",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=4),
                anchor_rel=Position(line=9, offset=25),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=9, offset=26),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=9, offset=27),
                length=3,
                node_type="string",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=3),
                anchor_rel=Position(line=9, offset=30),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=9, offset=31),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=9, offset=32),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            #   "entry": inputs.map(key, {key: 22})
            SemanticNode(
                position=Position(line=1, offset=2),
                anchor_rel=Position(line=10, offset=2),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=10, offset=3),
                length=5,
                node_type="property",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=5),
                anchor_rel=Position(line=10, offset=8),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=10, offset=9),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=2),
                anchor_rel=Position(line=10, offset=11),
                length=6,
                node_type="variable",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=6),
                anchor_rel=Position(line=10, offset=17),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=10, offset=18),
                length=3,
                node_type="keyword",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=3),
                anchor_rel=Position(line=10, offset=21),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=10, offset=22),
                length=3,
                node_type="variable",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=3),
                anchor_rel=Position(line=10, offset=25),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=2),
                anchor_rel=Position(line=10, offset=27),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=10, offset=28),
                length=3,
                node_type="variable",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=3),
                anchor_rel=Position(line=10, offset=31),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=2),
                anchor_rel=Position(line=10, offset=33),
                length=2,
                node_type="number",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=2),
                anchor_rel=Position(line=10, offset=35),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            SemanticNode(
                position=Position(line=0, offset=1),
                anchor_rel=Position(line=10, offset=36),
                length=1,
                node_type="operator",
                modifier=[],
            ),
            # }
            SemanticNode(
                position=Position(line=1, offset=0),
                anchor_rel=Position(line=11, offset=0),
                length=1,
                node_type="operator",
                modifier=[],
            ),
        ]

        self.maxDiff = None
        self.assertListEqual(expected, tokens)
