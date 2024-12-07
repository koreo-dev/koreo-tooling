from typing import NamedTuple

from lsprotocol import types

from koreo import cache
from koreo.result import is_not_ok, is_unwrapped_ok


from koreo.function.structure import Function
from koreo.function_test.registry import get_function_tests
from koreo.workflow.structure import Workflow, ErrorStep

from koreo_tooling import constants
from koreo_tooling.function_test import TestResults
from koreo_tooling.indexing.semantics import anchor_local_key_search, compute_abs_range
from koreo_tooling.langserver.workflow import _process_workflow_step


class HoverResult(NamedTuple):
    hover: types.Hover | None = None
    logs: list[types.LogMessageParams] | None = None


def handle_hover(
    resource_key: str,
    resource_key_range: types.Range,
    local_resource: tuple[str, types.Range] | None,
    test_results: dict[str, TestResults],
):
    match = constants.TOP_LEVEL_RESOURCE.match(resource_key)
    if not match:
        if (
            resource_key.startswith("Workflow:")
            and local_resource
            and local_resource[0].startswith("Step:")
        ):
            return _workflow_step_hover(
                workflow_name=resource_key, local_resource=local_resource
            )

        return HoverResult()

    kind = match.group("kind")
    name = match.group("name")

    if kind == "Workflow":
        return _workflow_hover(
            workflow_name=name,
            resource_key_range=resource_key_range,
            test_results=test_results,
        )
    elif kind == "Function":
        return _function_hover(
            function_name=name,
            resource_key_range=resource_key_range,
            test_results=test_results,
        )
    elif kind == "FunctionTest":
        return _function_test_hover(
            test_name=name,
            resource_key_range=resource_key_range,
            test_results=test_results,
        )

    return HoverResult()


def _workflow_hover(
    workflow_name: str,
    resource_key_range: types.Range,
    test_results: dict[str, TestResults],
) -> HoverResult:
    hover_content = [f"# {workflow_name}"]

    workflow = cache.get_resource_from_cache(
        resource_class=Workflow, cache_key=workflow_name
    )

    if not workflow:
        hover_content.append(f"Workflow {workflow_name} not in Koreo Cache")

    elif not is_unwrapped_ok(workflow):
        hover_content.append("Workflow not ready")
        hover_content.append(f"{workflow.message}")

    elif is_not_ok(workflow.steps_ready):
        hover_content.append("Workflow steps not ready")
        hover_content.append(f"{workflow.steps_ready.message}")

    else:
        # TODO: How to validate inputs are OK?
        # This really just means it is in cache, not valid.
        hover_content.append("Workflow prepared successfully.")

    return HoverResult(
        hover=types.Hover(
            contents=types.MarkupContent(
                kind=types.MarkupKind.Markdown,
                value="\n".join(hover_content),
            ),
            range=resource_key_range,
        )
    )


def _workflow_step_hover(
    workflow_name: str,
    local_resource: tuple[str, types.Range],
) -> HoverResult:
    workflow_name = workflow_name.split(":", 1)[-1]

    cached = cache.get_resource_system_data_from_cache(
        resource_class=Workflow, cache_key=workflow_name
    )
    if not cached or not cached.system_data or "anchor" not in cached.system_data:
        return HoverResult()

    step_key, step_range = local_resource

    parts = step_key.split(":")
    if not len(parts) == 2:
        return HoverResult()

    _, step_label = parts

    anchor: SemanticAnchor = cached.system_data.get("anchor")
    step_blocks = anchor_local_key_search(
        search_key=step_key, search_nodes=anchor.children
    )

    if len(step_blocks) != 1:
        return HoverResult()

    label_block = anchor_local_key_search(
        search_key=f"label:{step_label}", search_nodes=anchor.children
    )
    if len(label_block) != 1:
        return HoverResult()

    for step in cached.resource.steps:
        if step.label != step_label:
            continue

        if isinstance(step, ErrorStep):
            hover_content = f"Not ready {step.outcome.message}."

        else:
            result = _process_workflow_step(
                step=step,
                step_semantic_block=step_blocks[0],
                step_spec=cached.spec,
                semantic_anchor=anchor,
            )

            if result.error:
                hover_content = "*Error*"
            else:
                hover_content = "*Ok*"

        return HoverResult(
            hover=types.Hover(
                contents=types.MarkupContent(
                    kind=types.MarkupKind.Markdown,
                    value=hover_content,
                ),
                range=compute_abs_range(node=label_block[0], anchor=anchor),
            )
        )

    return HoverResult()


def _function_hover(
    function_name: str,
    resource_key_range: types.Range,
    test_results: dict[str, TestResults],
):
    hover_content = [f"# {function_name}"]

    function = cache.get_resource_from_cache(
        resource_class=Function, cache_key=function_name
    )

    if is_unwrapped_ok(function):
        hover_content.append("*Ready*")

    else:
        hover_content.append("Function not ready")
        hover_content.append(f"{function.message}")

    tests = {
        test_name: test_results[test_name]
        for test_name in get_function_tests(function_name)
        if test_name in test_results
    }

    if tests:
        hover_content.append("## Test Results")
        hover_content.append("| Test | Status | Warnings |")
        hover_content.append("|:-|-:|:-:|")
        for test_name, test_result in tests.items():
            hover_content.append(
                f"| `{test_name}` | {'Pass' if test_result.success else 'Fail'} | {'warnings' if test_result.input_mismatches or test_result.messages else ''} |"
            )

    return HoverResult(
        hover=types.Hover(
            contents=types.MarkupContent(
                kind=types.MarkupKind.Markdown,
                value="\n".join(hover_content),
            ),
            range=resource_key_range,
        )
    )


def _function_test_hover(
    test_name: str,
    resource_key_range: types.Range,
    test_results: dict[str, TestResults],
) -> HoverResult:
    result = test_results.get(test_name)

    if not result:
        return HoverResult(
            hover=types.Hover(
                contents=types.MarkupContent(
                    kind=types.MarkupKind.Markdown, value="*Test has not ran*"
                ),
                range=resource_key_range,
            )
        )

    hover_content = []

    if result.success:
        hover_content.append(f"# *Success*")

        if result.input_mismatches:
            hover_content.append("## Unused Inputs")
            hover_content.append("| Field | Issue | Severity |")
            hover_content.append("|:-|-:|:-:|")
            for mismatch in result.input_mismatches:
                hover_content.append(
                    f"| `{mismatch.field}` | {_input_error_formatter(actual=mismatch.actual, expected=mismatch.expected)} | {mismatch.severity} |"
                )
            hover_content.append("\n")

    else:
        hover_content.append("# *Error*")
        if result.messages:
            hover_content.append("## Failure")
            hover_content.extend(result.messages)

        if result.input_mismatches:
            hover_content.append("## Input Mismatches")
            hover_content.append("| Field | Issue | Severity |")
            hover_content.append("|:-|-:|:-:|")
            for mismatch in result.input_mismatches:
                hover_content.append(
                    f"| `{mismatch.field}` | {_input_error_formatter(actual=mismatch.actual, expected=mismatch.expected)} | {mismatch.severity} |"
                )
            hover_content.append("\n")

        if result.resource_field_errors:
            hover_content.append("## Field Mismatches")
            hover_content.append("| Field | Actual | Expected |")
            hover_content.append("|:-|-:|-:|")
            for compare in result.resource_field_errors:
                hover_content.append(
                    f"| `{compare.field}` | {compare.actual} | {compare.expected} |"
                )
            hover_content.append("\n")

        if result.outcome_fields_errors:
            hover_content.append("## Outcome Mismatches")
            hover_content.append("| Field | Actual | Expected |")
            hover_content.append("|:-|-:|-:|")
            for compare in result.outcome_fields_errors:
                hover_content.append(
                    f"| `{compare.field}` | {compare.actual} | {compare.expected} |"
                )
            hover_content.append("\n")

    return HoverResult(
        hover=types.Hover(
            contents=types.MarkupContent(
                kind=types.MarkupKind.Markdown,
                value="\n".join(hover_content),
            ),
            range=resource_key_range,
        )
    )


def _input_error_formatter(actual: bool, expected: bool) -> str:
    if actual and not expected:
        return "unexpected"

    if not actual and expected:
        return "*missing*"

    return "_unknown_"
