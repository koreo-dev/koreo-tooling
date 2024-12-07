import random
import unittest


from koreo_tooling.indexing import semantics


class TestFlatten(unittest.TestCase):
    def test_no_children(self):
        expected_nodes = []

        def _node_factory():
            node_length = random.randint(5, 50)
            node_type = random.choice(semantics.TokenTypes)
            node_modifier = random.choices(
                [modifier for modifier in semantics.Modifier], k=random.randint(0, 3)
            )

            node = semantics.SemanticNode(
                position=semantics.Position(line=0, character=0),
                anchor_rel=semantics.Position(line=0, character=0),
                length=node_length,
                node_type=node_type,
                modifier=node_modifier,
                children=None,
            )

            expected_nodes.append(node)

            return node

        nodes = [_node_factory() for _ in range(random.randint(1, 10))]

        flattened = semantics.flatten(nodes)

        self.assertListEqual(expected_nodes, flattened)

    def test_children(self):

        def _node_factory(depth: int = 0):
            node_length = random.randint(5, 50)
            node_type = random.choice(semantics.TokenTypes)
            node_modifier = random.choices(
                [modifier for modifier in semantics.Modifier], k=random.randint(0, 3)
            )

            child_nodes = []
            children = None

            child_count = random.randint(0, depth)
            if child_count:
                children = []
                for _ in range(child_count):
                    child_node, child_expected_nodes = _node_factory(depth=depth - 1)
                    children.append(child_node)
                    child_nodes.extend(child_expected_nodes)

            node = semantics.SemanticNode(
                position=semantics.Position(line=0, character=0),
                anchor_rel=semantics.Position(line=0, character=0),
                length=node_length,
                node_type=node_type,
                modifier=node_modifier,
                children=children,
            )

            childless_node = semantics.SemanticNode(
                position=semantics.Position(line=0, character=0),
                anchor_rel=semantics.Position(line=0, character=0),
                length=node_length,
                node_type=node_type,
                modifier=node_modifier,
                children=None,
            )

            expected_nodes = [childless_node]
            expected_nodes.extend(child_nodes)

            return node, expected_nodes

        nodes = []
        expected_nodes = []
        for _ in range(1, random.randint(3, 10)):
            child_node, child_expected_nodes = _node_factory(5)
            nodes.append(child_node)
            expected_nodes.extend(child_expected_nodes)

        flattened = semantics.flatten(nodes)

        self.maxDiff = None
        self.assertListEqual(expected_nodes, flattened)


class TestFlattenNode(unittest.TestCase):
    def test_no_children(self):
        node_length = random.randint(5, 50)
        node_type = random.choice(semantics.TokenTypes)
        node_modifier = random.choices(
            [modifier for modifier in semantics.Modifier], k=random.randint(0, 3)
        )

        node = semantics.SemanticNode(
            position=semantics.Position(line=0, character=0),
            anchor_rel=semantics.Position(line=0, character=0),
            length=node_length,
            node_type=node_type,
            modifier=node_modifier,
            children=None,
        )

        flattened = semantics.flatten_node(node)

        self.assertListEqual(
            [
                semantics.SemanticNode(
                    position=semantics.Position(line=0, character=0),
                    anchor_rel=semantics.Position(line=0, character=0),
                    length=node_length,
                    node_type=node_type,
                    modifier=node_modifier,
                    children=None,
                )
            ],
            flattened,
        )

    def test_children(self):

        def _node_factory(depth: int = 0):
            node_length = random.randint(5, 50)
            node_type = random.choice(semantics.TokenTypes)
            node_modifier = random.choices(
                [modifier for modifier in semantics.Modifier], k=random.randint(0, 3)
            )

            child_nodes = []
            children = None

            child_count = random.randint(0, depth)
            if child_count:
                children = []
                for _ in range(child_count):
                    child_node, child_expected_nodes = _node_factory(depth=depth - 1)
                    children.append(child_node)
                    child_nodes.extend(child_expected_nodes)

            node = semantics.SemanticNode(
                position=semantics.Position(line=0, character=0),
                anchor_rel=semantics.Position(line=0, character=0),
                length=node_length,
                node_type=node_type,
                modifier=node_modifier,
                children=children,
            )

            childless_node = semantics.SemanticNode(
                position=semantics.Position(line=0, character=0),
                anchor_rel=semantics.Position(line=0, character=0),
                length=node_length,
                node_type=node_type,
                modifier=node_modifier,
                children=None,
            )

            expected_nodes = [childless_node]
            expected_nodes.extend(child_nodes)

            return node, expected_nodes

        child_node, expected_nodes = _node_factory(5)
        flattened = semantics.flatten_node(child_node)

        self.maxDiff = None
        self.assertListEqual(expected_nodes, flattened)
