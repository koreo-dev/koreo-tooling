from typing import NamedTuple, Sequence
import copy

import yaml

from lsprotocol import types

from koreo import cache
from koreo.function_test.structure import FunctionTest

from koreo_tooling import constants
from koreo_tooling.function_test import FieldMismatchResult, TestResults
from koreo_tooling.indexing.semantics import (
    SemanticAnchor,
    SemanticBlock,
    SemanticNode,
    compute_abs_range,
    compute_abs_position,
)
from koreo_tooling.langserver.rangers import block_range_extract


class LensResult(NamedTuple):
    lens: Sequence[types.CodeLens] | None = None
    logs: Sequence[types.LogMessageParams] | None = None


class EditResult(NamedTuple):
    edits: Sequence[types.TextEdit] | None = None
    logs: Sequence[types.LogMessageParams] | None = None


def handle_lens(
    uri: str, doc_uri: str, doc_version: int, test_results: dict[str, TestResults]
):
    if not test_results:
        return LensResult()

    logs = []

    lens = []
    for test_name, test_result in test_results.items():
        if test_result.success:
            continue

        cached = cache.get_resource_system_data_from_cache(
            resource_class=FunctionTest, cache_key=test_name
        )

        if not (cached and cached.resource and cached.system_data):
            continue

        if cached.system_data.get("uri") != uri:
            continue

        test_anchor = cached.system_data.get("anchor")
        if not test_anchor:
            continue

        if test_result.input_mismatches:
            lens_result = _generate_inputs_lens(
                doc_uri=doc_uri,
                doc_version=doc_version,
                test_name=test_name,
                input_mismatches=test_result.input_mismatches,
                test_anchor=test_anchor,
            )
            if lens_result.lens:
                lens.extend(lens_result.lens)

            if lens_result.logs:
                logs.extend(lens_result.logs)

        if test_result.actual_resource and test_result.missing_test_assertion:
            lens_result = _generate_current_resource_lens(
                doc_uri=doc_uri,
                doc_version=doc_version,
                test_name=test_name,
                test_anchor=test_anchor,
            )
            if lens_result.lens:
                lens.extend(lens_result.lens)

            if lens_result.logs:
                logs.extend(lens_result.logs)

        if test_result.resource_field_errors or test_result.missing_test_assertion:
            lens_result = _generate_resource_lens(
                doc_uri=doc_uri,
                doc_version=doc_version,
                test_name=test_name,
                test_anchor=test_anchor,
            )
            if lens_result.lens:
                lens.extend(lens_result.lens)

            if lens_result.logs:
                logs.extend(lens_result.logs)

        if test_result.outcome_fields_errors or test_result.missing_test_assertion:
            lens_result = _generate_return_value_lens(
                doc_uri=doc_uri,
                doc_version=doc_version,
                test_name=test_name,
                test_anchor=test_anchor,
            )
            if lens_result.lens:
                lens.extend(lens_result.lens)

            if lens_result.logs:
                logs.extend(lens_result.logs)

    return LensResult(lens=lens, logs=logs)


def _generate_inputs_lens(
    doc_uri: str,
    doc_version: int,
    test_name: str,
    input_mismatches: list[FieldMismatchResult],
    test_anchor: SemanticAnchor,
) -> LensResult:
    if not any(mismatch.field.startswith("inputs.") for mismatch in input_mismatches):
        return LensResult()

    inputs_block = block_range_extract(
        search_key="inputs",
        search_nodes=test_anchor.children,
        anchor=test_anchor,
    )
    match inputs_block:
        case None:
            return LensResult(
                logs=[
                    types.LogMessageParams(
                        type=types.MessageType.Debug,
                        message=f"Test ({test_name}) missing inputs block",
                    )
                ]
            )
        case list(_):
            return LensResult(
                logs=[
                    types.LogMessageParams(
                        type=types.MessageType.Debug,
                        message=f"Test ({test_name}) has duplicate inputs blocks",
                    )
                ]
            )

    return LensResult(
        lens=[
            types.CodeLens(
                range=compute_abs_range(inputs_block, test_anchor),
                command=types.Command(
                    title="Autocorrect Inputs",
                    command="codeLens.completeInputs",
                    arguments=[
                        {
                            "uri": doc_uri,
                            "version": doc_version,
                            "test_name": test_name,
                        }
                    ],
                ),
            )
        ]
    )


def _generate_resource_lens(
    doc_uri: str,
    doc_version: int,
    test_name: str,
    test_anchor: SemanticAnchor,
) -> LensResult:
    expected_resource_block = block_range_extract(
        search_key="expected_resource",
        search_nodes=test_anchor.children,
        anchor=test_anchor,
    )
    match expected_resource_block:
        case None:
            return LensResult()
        case list(_):
            return LensResult(
                logs=[
                    types.LogMessageParams(
                        type=types.MessageType.Debug,
                        message=f"FunctionTest ({test_name}) has multiple expectResource blocks",
                    )
                ]
            )

    return LensResult(
        lens=[
            types.CodeLens(
                range=compute_abs_range(expected_resource_block, test_anchor),
                command=types.Command(
                    title="Autocorrect expected resource",
                    command="codeLens.completeExpectedResource",
                    arguments=[
                        {
                            "uri": doc_uri,
                            "version": doc_version,
                            "test_name": test_name,
                        }
                    ],
                ),
            )
        ]
    )


def _generate_current_resource_lens(
    doc_uri: str,
    doc_version: int,
    test_name: str,
    test_anchor: SemanticAnchor,
) -> LensResult:
    current_resource_block = block_range_extract(
        search_key="current_resource",
        search_nodes=test_anchor.children,
        anchor=test_anchor,
    )
    match current_resource_block:
        case None:
            return LensResult()
        case list(_):
            return LensResult(
                logs=[
                    types.LogMessageParams(
                        type=types.MessageType.Debug,
                        message=f"FunctionTest ({test_name}) has multiple currentResource blocks",
                    )
                ]
            )

    return LensResult(
        lens=[
            types.CodeLens(
                range=compute_abs_range(current_resource_block, test_anchor),
                command=types.Command(
                    title="Autofill current resource",
                    command="codeLens.completeCurrentResource",
                    arguments=[
                        {
                            "uri": doc_uri,
                            "version": doc_version,
                            "test_name": test_name,
                        }
                    ],
                ),
            )
        ]
    )


def _generate_return_value_lens(
    doc_uri: str,
    doc_version: int,
    test_name: str,
    test_anchor: SemanticAnchor,
) -> LensResult:
    return_value_block = block_range_extract(
        search_key="expected_return",
        search_nodes=test_anchor.children,
        anchor=test_anchor,
    )
    match return_value_block:
        case None:
            return LensResult()
        case list(_):
            return LensResult(
                logs=[
                    types.LogMessageParams(
                        type=types.MessageType.Debug,
                        message=f"Test ({test_name}) has multiple expectReturn blocks",
                    )
                ]
            )

    return LensResult(
        lens=[
            types.CodeLens(
                range=compute_abs_range(return_value_block, test_anchor),
                command=types.Command(
                    title="Autocorrect expected return value",
                    command="codeLens.completeExpectedReturnValue",
                    arguments=[
                        {
                            "uri": doc_uri,
                            "version": doc_version,
                            "test_name": test_name,
                        }
                    ],
                ),
            )
        ]
    )


def _code_lens_inputs_action(test_name: str, test_result: TestResults):
    if not test_result.input_mismatches:
        return EditResult()

    cached = cache.get_resource_system_data_from_cache(
        resource_class=FunctionTest, cache_key=test_name
    )
    if not (cached and cached.resource and cached.system_data):
        return EditResult(
            logs=[
                types.LogMessageParams(
                    type=types.MessageType.Debug,
                    message=f"test ({test_name}) isn't cached right",
                )
            ]
        )

    test_anchor = cached.system_data.get("anchor")
    if not test_anchor:
        return EditResult(
            logs=[
                types.LogMessageParams(
                    type=types.MessageType.Debug,
                    message=f"test ({test_name}) cache missing anchor",
                )
            ]
        )

    inputs_block = block_range_extract(
        search_key="inputs",
        search_nodes=test_anchor.children,
        anchor=test_anchor,
    )
    match inputs_block:
        case None:
            return EditResult(
                logs=[
                    types.LogMessageParams(
                        type=types.MessageType.Debug,
                        message=f"test ({test_name}) missing inputs block",
                    )
                ]
            )
        case list(_):
            return EditResult(
                logs=[
                    types.LogMessageParams(
                        type=types.MessageType.Debug,
                        message=f"test ({test_name}) duplicate inputs block",
                    )
                ]
            )

    inputs_value_block = block_range_extract(
        search_key="input-values",
        search_nodes=inputs_block.children,
        anchor=test_anchor,
    )
    match inputs_value_block:
        case None | list(_):
            return EditResult()

    # We're going to mutate this object, so make a copy.
    spec_inputs = copy.deepcopy(cached.spec.get("inputs"))

    logs: list[types.LogMessageParams] = []

    input_fields = (
        (input_match.group("name"), mismatch)
        for input_match, mismatch in (
            (constants.INPUT_NAME_PATTERN.match(mismatch.field), mismatch)
            for mismatch in test_result.input_mismatches
        )
        if input_match
    )

    place_holder = "TODO"

    if not spec_inputs:
        spec_inputs = {
            input_name: place_holder
            for (input_name, mismatch) in input_fields
            if mismatch.expected
        }
    else:
        for input_name, mismatch in input_fields:
            if mismatch.actual and not mismatch.expected:
                del spec_inputs[input_name]

            if not mismatch.actual and mismatch.expected:
                spec_inputs[input_name] = place_holder

    offset, edit_range = _compute_edit_range(
        label=inputs_block, value_block=inputs_value_block, anchor=test_anchor
    )

    indent = (offset + 2) * " "
    formated_inputs = f"\n{"\n".join(
        f"{indent}{line}"
        for line in yaml.dump(spec_inputs).splitlines()
    )}\n\n"

    return EditResult(
        edits=(types.TextEdit(new_text=formated_inputs, range=edit_range),),
        logs=logs,
    )


def _code_lens_current_resource_action(test_name: str, test_result: TestResults):
    if not (test_result.actual_resource and test_result.missing_test_assertion):
        return EditResult()

    return _code_lens_replace_value_block_action(
        test_name=test_name,
        label_block_key="current_resource",
        value_block_key="current_value",
        new_value=test_result.actual_resource,
    )


def _code_lens_resource_action(test_name: str, test_result: TestResults):
    if not (test_result.resource_field_errors or test_result.missing_test_assertion):
        return EditResult()

    return _code_lens_replace_value_block_action(
        test_name=test_name,
        label_block_key="expected_resource",
        value_block_key="expected_value",
        new_value=test_result.actual_resource,
    )


def _code_lens_return_value_action(test_name: str, test_result: TestResults):
    if not (test_result.outcome_fields_errors or test_result.missing_test_assertion):
        return EditResult()

    return _code_lens_replace_value_block_action(
        test_name=test_name,
        label_block_key="expected_return",
        value_block_key="expected_value",
        new_value=test_result.actual_return,
    )


def _code_lens_replace_value_block_action(
    test_name: str,
    label_block_key: str,
    value_block_key: str,
    new_value: dict | None,
):
    if new_value is None:
        return EditResult(
            logs=[
                types.LogMessageParams(
                    type=types.MessageType.Debug,
                    message=f"FunctionTest ({test_name}) can not auto-complete {label_block_key}",
                )
            ]
        )

    cached = cache.get_resource_system_data_from_cache(
        resource_class=FunctionTest, cache_key=test_name
    )
    if not (cached and cached.resource and cached.system_data):
        return EditResult(
            logs=[
                types.LogMessageParams(
                    type=types.MessageType.Debug,
                    message=f"FunctionTest ({test_name}) isn't cached, or cache is corrupt",
                )
            ]
        )

    test_anchor = cached.system_data.get("anchor")
    if not test_anchor:
        return EditResult(
            logs=[
                types.LogMessageParams(
                    type=types.MessageType.Debug,
                    message=f"FunctionTest ({test_name}) cache corrupt, missing anchor",
                )
            ]
        )

    label_block = block_range_extract(
        search_key=label_block_key,
        search_nodes=test_anchor.children,
        anchor=test_anchor,
    )
    match label_block:
        case None:
            return EditResult(
                logs=[
                    types.LogMessageParams(
                        type=types.MessageType.Debug,
                        message=f"FunctionTest ({test_name}) missing {label_block_key} block",
                    )
                ]
            )
        case list(_):
            return EditResult(
                logs=[
                    types.LogMessageParams(
                        type=types.MessageType.Debug,
                        message=f"FunctionTest ({test_name}) duplicate {label_block_key} block",
                    )
                ]
            )

    value_block = block_range_extract(
        search_key=value_block_key,
        search_nodes=label_block.children,
        anchor=test_anchor,
    )
    match value_block:
        case None | list(_):
            return EditResult()

    logs: list[types.LogMessageParams] = []

    offset, edit_range = _compute_edit_range(
        label=label_block, value_block=value_block, anchor=test_anchor
    )

    indent = (offset + 2) * " "
    formated = f"\n{"\n".join(
        f"{indent}{line}"
        for line in yaml.dump(new_value, width=10000).splitlines()
    )}\n\n"

    return EditResult(
        edits=(types.TextEdit(new_text=formated, range=edit_range),),
        logs=logs,
    )


def _compute_edit_range(
    label: SemanticAnchor | SemanticBlock | SemanticNode,
    value_block: SemanticAnchor | SemanticBlock | SemanticNode,
    anchor: SemanticAnchor,
) -> tuple[int, types.Range]:
    match label:
        case SemanticAnchor(abs_position=abs_position):
            # TODO: This would be wrong. Probably should be first-child-start?
            edit_start_pos = abs_position
            offset = abs_position.character
        case SemanticBlock(anchor_rel=anchor_rel):
            # TODO: This would be wrong. Probably should be first-child-start?
            edit_start_pos = compute_abs_position(
                rel_position=anchor_rel.start, abs_position=anchor.abs_position
            )
            offset = anchor_rel.start.character
        case SemanticNode(anchor_rel=anchor_rel, length=length):
            edit_start_pos = compute_abs_position(
                rel_position=anchor_rel,
                abs_position=anchor.abs_position,
                length=length + 1,
            )
            offset = anchor_rel.character

    match value_block:
        case SemanticAnchor(abs_position=abs_position):
            # TODO: This should really never be an anchor node, but if it is,
            # this should probably be the end-position of the deepest last
            # child.
            edit_end_pos = abs_position
        case SemanticBlock(anchor_rel=anchor_rel):
            end_line = anchor_rel.end.line + anchor.abs_position.line
            character = 0
            if end_line == edit_start_pos.line:
                character = anchor_rel.end.character

            edit_end_pos = types.Position(
                line=end_line,
                character=character,
            )
        case SemanticNode(anchor_rel=anchor_rel, length=length):
            edit_end_pos = compute_abs_position(
                rel_position=anchor_rel,
                abs_position=anchor.abs_position,
                length=length,
            )

    return offset, types.Range(start=edit_start_pos, end=edit_end_pos)


LENS_COMMANDS = (
    ("codeLens.completeInputs", _code_lens_inputs_action),
    ("codeLens.completeCurrentResource", _code_lens_current_resource_action),
    ("codeLens.completeExpectedResource", _code_lens_resource_action),
    ("codeLens.completeExpectedReturnValue", _code_lens_return_value_action),
)
