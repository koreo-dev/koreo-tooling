import asyncio
from typing import Any, NamedTuple

from lsprotocol import types
from pygls.lsp.server import LanguageServer

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


class TestResults(NamedTuple):
    success: bool
    messages: list[str] | None
    resource_field_errors: list[CompareResult] | None
    outcome_fields_errors: list[CompareResult] | None
    missing_inputs: set[str] | None
    actual_resource: dict | None


async def run_function_tests(
    server: LanguageServer,
    path_resources: set[str],
) -> dict[str, TestResults]:
    tests_to_run = set[str]()
    for resource_key in path_resources:
        if resource_key.startswith("FunctionTest:"):
            test_name = resource_key.split(":", 1)[1]
            tests_to_run.add(test_name)

        if resource_key.startswith("Function:"):
            function_name = resource_key.split(":", 1)[1]
            function_tests = get_function_tests(function_name)
            tests_to_run.update(function_tests)

    if not tests_to_run:
        return {}

    tasks = []
    async with asyncio.TaskGroup() as task_group:
        for test_key in tests_to_run:
            test = cache.get_resource_from_cache(
                resource_class=FunctionTest, cache_key=test_key
            )
            if not test:
                server.window_log_message(
                    params=types.LogMessageParams(
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
            server.window_log_message(
                params=types.LogMessageParams(
                    type=types.MessageType.Error,
                    message=f"Timeout running FunctionTest ('{timeout.get_name()}')!",
                )
            )

    results = {task.get_name(): task.result() for task in done}
    return results


async def _run_function_test(test_name: str, test: FunctionTest) -> TestResults:
    if not is_unwrapped_ok(test.function_under_test):
        return TestResults(
            success=False,
            messages=[f"{test.function_under_test}"],
            resource_field_errors=None,
            outcome_fields_errors=None,
            missing_inputs=None,
            actual_resource=None,
        )

    provided_keys = []

    if test.inputs:
        provided_keys.extend(f"inputs.{input_key}" for input_key in test.inputs.keys())

    if test.parent:
        provided_keys.extend(f"parent.{input_key}" for input_key in test.parent.keys())

    first_tier_inputs = set(
        f"inputs.{constants.INPUT_NAME_PATTERN.match(key).group(1)}"
        for key in test.function_under_test.dynamic_input_keys
        if key.startswith("inputs.")
    )
    first_tier_inputs.update(
        f"parent.{constants.PARENT_NAME_PATTERN.match(key).group(1)}"
        for key in test.function_under_test.dynamic_input_keys
        if key.startswith("parent.")
    )

    # TODO: This needs to also include the parent keys in the checker
    wrong_keys = first_tier_inputs.difference(provided_keys)
    if wrong_keys:
        return TestResults(
            success=False,
            messages=None,
            resource_field_errors=None,
            outcome_fields_errors=None,
            missing_inputs=wrong_keys,
            actual_resource=None,
        )

    try:
        test_outcome = await run_function_test(location=test_name, function_test=test)
    except Exception as err:
        return TestResults(
            success=False,
            messages=[f"Unknown {err}."],
            resource_field_errors=None,
            outcome_fields_errors=None,
            missing_inputs=None,
            actual_resource=None,
        )

    success = True
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
        missing_inputs=None,
        actual_resource=test_outcome.actual_resource,
    )


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
