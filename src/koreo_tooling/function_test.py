import asyncio
from typing import NamedTuple

from lsprotocol import types
from pygls.lsp.server import LanguageServer

from koreo import cache
from koreo.result import DepSkip, Ok, PermFail, Retry, Skip, is_unwrapped_ok


from koreo.function_test.registry import get_function_tests
from koreo.function_test.run import run_function_test
from koreo.function_test.structure import FunctionTest


class TestResults(NamedTuple):
    success: bool
    messages: list[str] | None
    resource_field_errors: list[str] | None
    outcome_fields_errors: list[str] | None


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
        )

    try:
        test_outcome = await run_function_test(location=test_name, function_test=test)
    except Exception as err:
        return TestResults(
            success=False,
            messages=[f"Unknown {err}."],
            resource_field_errors=None,
            outcome_fields_errors=None,
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
            if not test_outcome.expected_resource or (
                test_outcome.expected_outcome is not None
                and not isinstance(test_outcome.expected_outcome, Retry)
            ):
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

            excpect_resource_matched, resource_field_errors = _check_ok_value(
                test_outcome.actual_resource,
                test_outcome.expected_resource,
            )
            success = success and excpect_resource_matched

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

            excpect_ok_matched, outcome_fields_errors = _check_ok_value(
                okValue, test_outcome.expected_ok_value
            )
            success = success and excpect_ok_matched

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
    )


def _check_ok_value(
    actual: dict | None, expected: dict | None
) -> tuple[bool, list[str]]:
    success = True

    if expected is None:
        return success, []

    mismatches = []

    if actual is None:
        success = False
        mismatches.append("Actual value was unexpectedly `None`")
        return success, mismatches

    wrong_fields = _dict_compare(actual, expected, base="")
    if not wrong_fields:
        return success, []

    success = False
    mismatches.extend(wrong_fields)
    return success, mismatches


def _dict_compare(lhs: dict, rhs: dict, base: str):
    differences = []

    lhs_keys = set(lhs.keys())
    rhs_keys = set(rhs.keys())

    differences.extend(f"{base}.{key}" for key in lhs_keys.difference(rhs_keys))
    differences.extend(f"{base}.{key}" for key in rhs_keys.difference(lhs_keys))

    for mutual_key in lhs_keys.intersection(rhs_keys):
        lhs_value = lhs[mutual_key]
        rhs_value = rhs[mutual_key]

        key = f"{base}.{mutual_key}"

        if type(lhs_value) != type(rhs_value):
            differences.append(key)
            continue

        if isinstance(lhs_value, dict):
            differences.extend(_dict_compare(lhs_value, rhs_value, base=key))
            continue

        if isinstance(lhs_value, list):
            if not _values_match(lhs_value, rhs_value):
                differences.append(key)

            continue

        if not _values_match(lhs_value, rhs_value):
            differences.append(key)

    return differences


def _values_match(lhs, rhs) -> bool:
    if type(lhs) != type(rhs):
        return False

    if isinstance(lhs, dict):
        diffs = _dict_compare(lhs, rhs, base="")
        return not diffs

    if isinstance(lhs, list):
        if len(lhs) != len(rhs):
            return False

        for lhs_value, rhs_value in zip(lhs, rhs):
            if not _values_match(lhs_value, rhs_value):
                return False

        return True

    return lhs == rhs
