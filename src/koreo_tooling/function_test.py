from typing import Any, Literal, NamedTuple
import asyncio

from lsprotocol import types
from pygls.lsp.server import LanguageServer

from celpy import celtypes

from koreo import cache
from koreo.result import DepSkip, Ok, PermFail, Retry, Skip, is_unwrapped_ok


from koreo.function_test.registry import get_function_tests
from koreo.function_test.run import run_function_test
from koreo.function_test.structure import FunctionTest

from . import constants


class CompareResult(NamedTuple):
    field: str
    expected: Any
    actual: Any


class FieldMismatchResult(NamedTuple):
    field: str
    severity: Literal["WARNING", "ERROR"]
    expected: bool
    actual: bool


class TestResults(NamedTuple):
    success: bool
    messages: list[str] | None
    resource_field_errors: list[CompareResult] | None
    outcome_fields_errors: list[CompareResult] | None
    input_mismatches: list[FieldMismatchResult] | None
    actual_resource: dict | None


async def run_function_tests(
    tests_to_run: set[str],
    functions_to_test: set[str],
) -> tuple[dict[str, TestResults], list[types.LogMessageParams]]:
    function_tests = set[str]()
    for function_name in functions_to_test:
        function_tests.update(get_function_tests(function_name))

    all_tests = tests_to_run.union(function_tests)

    if not all_tests:
        return ({}, [])

    logs = []

    tasks = []
    async with asyncio.TaskGroup() as task_group:
        for test_key in all_tests:
            test = cache.get_resource_from_cache(
                resource_class=FunctionTest, cache_key=test_key
            )
            if not test:
                logs.append(
                    types.LogMessageParams(
                        type=types.MessageType.Error,
                        message=f"Failed to find FunctionTest ('{test_key}') in Koreo cache.",
                    )
                )
                continue

            tasks.append(
                task_group.create_task(
                    _run_function_test(test_key, test), name=test_key
                )
            )

    done, pending = await asyncio.wait(tasks)
    if pending:
        for timeout in pending:
            logs.append(
                types.LogMessageParams(
                    type=types.MessageType.Error,
                    message=f"Timeout running FunctionTest ('{timeout.get_name()}')!",
                )
            )

    results = {task.get_name(): task.result() for task in done}
    return (results, logs)


async def _run_function_test(test_name: str, test: FunctionTest) -> TestResults:
    if not is_unwrapped_ok(test.function_under_test):
        return TestResults(
            success=False,
            messages=[f"{test.function_under_test}"],
            resource_field_errors=None,
            outcome_fields_errors=None,
            input_mismatches=None,
            actual_resource=None,
        )

    field_mismatches = _check_inputs(
        inputs=test.inputs,
        parent=test.parent,
        dynamic_input_keys=test.function_under_test.dynamic_input_keys,
    )

    success = True

    if field_mismatches:
        success = success and not any(
            mismatch.severity == "ERROR" for mismatch in field_mismatches
        )

    try:
        test_outcome = await run_function_test(location=test_name, function_test=test)
    except Exception as err:
        return TestResults(
            success=False,
            messages=[f"Unknown {err}."],
            resource_field_errors=None,
            outcome_fields_errors=None,
            input_mismatches=field_mismatches,
            actual_resource=None,
        )

    messages = []
    resource_field_errors = []
    outcome_fields_errors = []

    match test_outcome.outcome:
        case DepSkip(message=message, location=location):
            if not isinstance(test_outcome.expected_outcome, DepSkip):
                success = False
                messages.append(
                    f"Unexpected DepSkip(message='{message}', location='{location}'."
                )
        case Skip(message=message, location=location):
            if not isinstance(test_outcome.expected_outcome, Skip):
                success = False
                messages.append(
                    f"Unexpected Skip(message='{message}', location='{location}')."
                )
        case PermFail(message=message, location=location):
            if not isinstance(test_outcome.expected_outcome, PermFail):
                success = False
                messages.append(
                    f"Unexpected PermFail(message='{message}', location='{location}')."
                )
        case Retry(message=message, delay=delay, location=location):
            if test_outcome.expected_outcome is not None and not isinstance(
                test_outcome.expected_outcome, Retry
            ):
                messages.append(f"{test_outcome.expected_outcome}")
                success = False
                messages.append(
                    f"Unexpected Retry(message='{message}', delay={delay}, location='{location}')."
                )
            elif test_outcome.expected_ok_value:
                success = False
                messages.append(
                    "Can not assert expected ok-value when resource "
                    "modifications requested. Ensure currentResource matches "
                    "materializer."
                )

            resource_field_errors = _check_value(
                actual=test_outcome.actual_resource,
                expected=test_outcome.expected_resource,
            )
            if resource_field_errors:
                success = False

        case Ok(data=okValue) | okValue:
            if test_outcome.expected_outcome is not None and not isinstance(
                test_outcome.expected_outcome, Ok
            ):
                success = False
                messages.append("Unexpected Ok(...).")

            if test_outcome.expected_resource:
                success = False
                messages.append(
                    "Can not assert expectedResource unless changes requested."
                )

            outcome_fields_errors = _check_value(
                actual=okValue, expected=test_outcome.expected_ok_value
            )

            if outcome_fields_errors:
                success = False

    if not (
        test_outcome.expected_resource
        or test_outcome.expected_outcome
        or test_outcome.expected_ok_value
    ):
        success = False
        messages.append(
            "Must define expectedResource, expectedOutcome, or expectedOkValue."
        )

    return TestResults(
        success=success,
        messages=messages,
        resource_field_errors=resource_field_errors,
        outcome_fields_errors=outcome_fields_errors,
        input_mismatches=field_mismatches,
        actual_resource=test_outcome.actual_resource,
    )


def _check_inputs(
    inputs: celtypes.MapType | None,
    parent: celtypes.MapType | None,
    dynamic_input_keys: set[str],
) -> list[FieldMismatchResult]:
    provided_keys = set[str]()
    if inputs:
        provided_keys.update(f"inputs.{input_key}" for input_key in inputs.keys())

    if parent:
        provided_keys.update(f"parent.{input_key}" for input_key in parent.keys())

    first_tier_inputs = set(
        f"inputs.{constants.INPUT_NAME_PATTERN.match(key).group(1)}"
        for key in dynamic_input_keys
        if key.startswith("inputs.")
    )
    first_tier_inputs.update(
        f"parent.{constants.PARENT_NAME_PATTERN.match(key).group(1)}"
        for key in dynamic_input_keys
        if key.startswith("parent.")
    )

    mismatches = []
    for missing in first_tier_inputs.difference(provided_keys):
        mismatches.append(
            FieldMismatchResult(
                field=missing,
                severity="ERROR",
                actual=False,
                expected=True,
            )
        )

    for extra in provided_keys.difference(first_tier_inputs):
        mismatches.append(
            FieldMismatchResult(
                field=extra,
                severity="WARNING",
                actual=True,
                expected=False,
            )
        )

    return mismatches


def _check_value(actual: dict | None, expected: dict | None) -> list[CompareResult]:
    if expected is None:
        return []

    mismatches: list[CompareResult] = []

    if actual is None:
        mismatches.append(CompareResult(field="", actual="missing", expected="..."))
        return mismatches

    mismatches.extend(_dict_compare(base_field="", actual=actual, expected=expected))

    return mismatches


def _dict_compare(base_field: str, actual: dict, expected: dict) -> list[CompareResult]:
    differences: list[CompareResult] = []

    if base_field:
        base_prefix = f"{base_field}."
    else:
        base_prefix = ""

    actual_keys = set(actual.keys())
    expected_keys = set(expected.keys())

    for key in actual_keys.difference(expected_keys):
        differences.append(
            CompareResult(
                field=f"{base_prefix}{key}",
                actual="...",
                expected="missing",
            )
        )

    for key in expected_keys.difference(actual_keys):
        differences.append(
            CompareResult(
                field=f"{base_prefix}{key}",
                actual="missing",
                expected="...",
            )
        )

    for mutual_key in actual_keys.intersection(expected_keys):
        actual_value = actual[mutual_key]
        expected_value = expected[mutual_key]

        key = f"{base_prefix}{mutual_key}"

        if type(actual_value) != type(expected_value):
            differences.append(
                CompareResult(
                    field=key,
                    actual=f"{type(actual_value)}",
                    expected=f"{type(expected_value)}",
                )
            )
            continue

        if isinstance(actual_value, dict):
            differences.extend(
                _dict_compare(
                    base_field=key, actual=actual_value, expected=expected_value
                )
            )
            continue

        differences.extend(
            _values_match(field=key, actual=actual_value, expected=expected_value)
        )

    return differences


def _values_match(field: str, actual, expected) -> list[CompareResult]:
    if type(actual) != type(expected):
        return [
            CompareResult(
                field=field,
                actual=f"{type(actual)}",
                expected=f"{type(expected)}",
            )
        ]

    if isinstance(actual, dict):
        return _dict_compare(base_field=field, actual=actual, expected=expected)

    if isinstance(actual, list):
        if len(actual) != len(expected):
            return [
                CompareResult(
                    field=field,
                    actual=f"{len(actual)} items",
                    expected=f"{len(expected)} items",
                )
            ]

        mismatches = []
        for idx, (actual_value, expected_value) in enumerate(zip(actual, expected)):
            mismatches.extend(
                _values_match(
                    field=f"{field}[{idx}]",
                    actual=actual_value,
                    expected=expected_value,
                )
            )

        return mismatches

    if actual == expected:
        return []

    return [
        CompareResult(
            field=field,
            actual=f"{actual}",
            expected=f"{expected}",
        )
    ]
