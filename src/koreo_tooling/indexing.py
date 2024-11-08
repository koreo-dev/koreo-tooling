from typing import Any

from yaml.loader import SafeLoader

from lsprotocol import types


__RANGE_KEY = "..range.."


class IndexingLoader(SafeLoader):
    def construct_mapping(self, node, deep=False):
        __RANGE_KEY = "..range.."
        mapping = super(IndexingLoader, self).construct_mapping(node=node, deep=deep)
        mapping[__RANGE_KEY] = types.Range(
            start=types.Position(
                line=node.start_mark.line, character=node.start_mark.column
            ),
            end=types.Position(line=node.end_mark.line, character=node.end_mark.column),
        )
        return mapping


def range_stripper(resource: Any):
    if isinstance(resource, dict):
        return {
            key: range_stripper(value)
            for key, value in resource.items()
            if key != __RANGE_KEY
        }

    if isinstance(resource, list):
        return [range_stripper(value) for value in resource]

    return resource
