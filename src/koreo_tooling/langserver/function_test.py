from typing import NamedTuple, Sequence
import os

os.environ["KOREO_DEV_TOOLING"] = "true"

from lsprotocol import types

from koreo import cache
from koreo.function_test.structure import FunctionTest

from koreo_tooling import function_test
from koreo_tooling.indexing import compute_abs_range
from koreo_tooling.indexing.semantics import SemanticAnchor, SemanticBlock, SemanticNode

from koreo_tooling.langserver.rangers import block_range_extract


class RunResults(NamedTuple):
    results: dict[str, function_test.TestResults] | None = None
    logs: list[types.LogMessageParams] | None = None
    diagnostics: list[types.Diagnostic] | None = None


async def run_function_tests(
    tests_to_run: set[str],
    functions_to_test: dict[type, Sequence[str]],
    test_range_map: dict[str, types.Range],
) -> RunResults:
    if not (tests_to_run or functions_to_test):
        return RunResults()

    test_results, logs = await function_test.run_function_tests(
        tests_to_run=tests_to_run,
        functions_to_test=functions_to_test,
    )

    if not test_results:
        return RunResults(logs=logs)

    return RunResults(
        results=test_results,
        logs=logs,
        diagnostics=_process_results(
            tests_to_run=tests_to_run,
            test_results=test_results,
            test_range_map=test_range_map,
        ),
    )


def _process_results(
    tests_to_run: set[str],
    test_results: dict[str, function_test.TestResults],
    test_range_map: dict[str, types.Range],
) -> list[types.Diagnostic]:
    test_diagnostics: list[types.Diagnostic] = []

    for test_key, result in test_results.items():
        if result.success:
            continue

        # TODO: Add support for reporting within Functions
        if test_key not in tests_to_run:
            continue

        cached_resource = cache.get_resource_system_data_from_cache(
            resource_class=FunctionTest, cache_key=test_key
        )
        if not (
            cached_resource and cached_resource.resource and cached_resource.system_data
        ):
            continue

        # This is the test's location within the file.
        anchor = cached_resource.system_data.get("anchor")
        if not anchor:
            continue

        if result.messages:
            test_diagnostics.append(
                types.Diagnostic(
                    message=f"Failures: {'; '.join(result.messages)}",
                    severity=types.DiagnosticSeverity.Error,
                    range=test_range_map[test_key],
                )
            )

        test_spec_block = block_range_extract(
            search_key="spec",
            search_nodes=anchor.children,
            anchor=anchor,
        )
        match test_spec_block:
            case None:
                # Could not find the FunctionTest's spec. Hopefully they're
                # typing it right now.
                continue
            case list(block_diagnostics):
                # There was some type of structural issue that resulted in the
                # spec block lookup returning errors. The diagnostics should
                # explain the issue.
                test_diagnostics.extend(block_diagnostics)
                continue

        if result.input_mismatches:
            test_diagnostics.extend(
                _process_input_errors(
                    input_mismatches=result.input_mismatches,
                    test_spec_block=test_spec_block,
                    anchor=anchor,
                )
            )

        if result.resource_field_errors:
            test_diagnostics.extend(
                _process_resource_errors(
                    field_errors=result.resource_field_errors,
                    test_spec_block=test_spec_block,
                    anchor=anchor,
                )
            )

        if result.outcome_fields_errors:
            test_diagnostics.extend(
                _process_outcome_errors(
                    field_errors=result.outcome_fields_errors,
                    test_spec_block=test_spec_block,
                    anchor=anchor,
                )
            )

    return test_diagnostics


def _process_input_errors(
    input_mismatches: Sequence[function_test.FieldMismatchResult],
    test_spec_block: SemanticAnchor | SemanticBlock | SemanticNode,
    anchor: SemanticAnchor,
) -> list[types.Diagnostic]:
    inputs_block = block_range_extract(
        search_key="inputs",
        search_nodes=test_spec_block.children,
        anchor=anchor,
    )
    match inputs_block:
        case None:
            return [
                types.Diagnostic(
                    message="Input expected, but none provided.",
                    severity=types.DiagnosticSeverity.Warning,
                    range=compute_abs_range(test_spec_block, anchor),
                )
            ]
        case list(block_diagnostics):
            return block_diagnostics

    input_values_block = block_range_extract(
        search_key="input-values",
        search_nodes=inputs_block.children,
        anchor=anchor,
    )
    match input_values_block:
        case None:
            return []
        case list(block_diagnostics):
            return block_diagnostics

    diagnostics: list[types.Diagnostic] = []

    for mismatch in input_mismatches:
        if not mismatch.expected and mismatch.actual:
            input_block = block_range_extract(
                search_key=f"input:{mismatch.field.split(".", 1)[-1]}",
                search_nodes=input_values_block.children,
                anchor=anchor,
            )
            match input_block:
                case None:
                    continue
                case list(block_diagnostics):
                    diagnostics.extend(block_diagnostics)
                    continue

            diagnostics.append(
                types.Diagnostic(
                    message=f"Input ('{mismatch.field}') not expected.",
                    severity=types.DiagnosticSeverity.Warning,
                    range=compute_abs_range(input_block, anchor),
                )
            )

        elif mismatch.expected and not mismatch.actual:
            diagnostics.append(
                types.Diagnostic(
                    message=f"Missing input ('{mismatch.field}').",
                    severity=types.DiagnosticSeverity.Error,
                    range=compute_abs_range(inputs_block, anchor),
                )
            )

    return diagnostics


def _process_resource_errors(
    field_errors: Sequence[function_test.CompareResult],
    test_spec_block: SemanticAnchor | SemanticBlock | SemanticNode,
    anchor: SemanticAnchor,
) -> list[types.Diagnostic]:
    resource_block = block_range_extract(
        search_key="expected_resource",
        search_nodes=test_spec_block.children,
        anchor=anchor,
    )
    match resource_block:
        case None:
            return [
                types.Diagnostic(
                    message="Resource unexpectedly modified.",
                    severity=types.DiagnosticSeverity.Error,
                    range=compute_abs_range(test_spec_block, anchor),
                )
            ]
        case list(block_diagnostics):
            return block_diagnostics

    diagnostics: list[types.Diagnostic] = []

    for mismatch in field_errors:
        mismatch_block = block_range_extract(
            search_key=mismatch.field,
            search_nodes=resource_block.children,
            anchor=anchor,
        )
        match mismatch_block:
            case None:
                diagnostics.append(
                    types.Diagnostic(
                        message=f"Missing value for '{mismatch.field}'",
                        severity=types.DiagnosticSeverity.Error,
                        range=compute_abs_range(resource_block, anchor),
                    )
                )
                continue
            case list(block_diagnostics):
                diagnostics.extend(block_diagnostics)
                continue

        diagnostics.append(
            types.Diagnostic(
                message=f"Actual: '{mismatch.actual}'",
                severity=types.DiagnosticSeverity.Error,
                range=compute_abs_range(mismatch_block, anchor),
            )
        )

    return diagnostics


def _process_outcome_errors(
    field_errors: Sequence[function_test.CompareResult],
    test_spec_block: SemanticAnchor | SemanticBlock | SemanticNode,
    anchor: SemanticAnchor,
) -> list[types.Diagnostic]:
    outcome_block = block_range_extract(
        search_key="expected_return",
        search_nodes=test_spec_block.children,
        anchor=anchor,
    )
    match outcome_block:
        case None:
            return [
                types.Diagnostic(
                    message="Outcome unexpectedly reached.",
                    severity=types.DiagnosticSeverity.Error,
                    range=compute_abs_range(test_spec_block, anchor),
                )
            ]
        case list(block_diagnostics):
            return block_diagnostics

    diagnostics: list[types.Diagnostic] = []

    for mismatch in field_errors:
        mismatch_block = block_range_extract(
            search_key=mismatch.field,
            search_nodes=outcome_block.children,
            anchor=anchor,
        )
        match mismatch_block:
            case None:
                diagnostics.append(
                    types.Diagnostic(
                        message=f"Missing value for '{mismatch.field}'",
                        severity=types.DiagnosticSeverity.Error,
                        range=compute_abs_range(outcome_block, anchor),
                    )
                )
                continue
            case list(block_diagnostics):
                diagnostics.extend(block_diagnostics)
                continue

        diagnostics.append(
            types.Diagnostic(
                message=f"Actual: '{mismatch.actual}'",
                severity=types.DiagnosticSeverity.Error,
                range=compute_abs_range(mismatch_block, anchor),
            )
        )

    return diagnostics
