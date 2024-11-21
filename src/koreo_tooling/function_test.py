import asyncio

from lsprotocol import types
from pygls.lsp.server import LanguageServer

from koreo import cache
from koreo.result import DepSkip, Ok, PermFail, Retry, Skip


from koreo.function_test.registry import get_function_tests
from koreo.function_test.run import run_function_test
from koreo.function_test.structure import FunctionTest


async def run_function_tests(
    server: LanguageServer,
    path: str,
    path_resources: set[str],
    resource_range_index: dict[str, dict[str, list[types.Range]]],
):
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
        return []

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

            ranges = resource_range_index[f"FunctionTest:{test_key}"][path]
            tasks.append(
                task_group.create_task(
                    _run_function_test(test_key, test, ranges), name=test_key
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

    return [diagnostic for task in done for diagnostic in task.result()]


async def _run_function_test(
    test_name: str, test: FunctionTest, ranges: list[types.Range]
) -> list[types.Diagnostic]:
    try:
        test_outcome = await run_function_test(location=test_name, function_test=test)
    except Exception as err:
        return [
            types.Diagnostic(
                message=f"FunctionTest ('{test_name}') failed. Unknown {err}.",
                severity=types.DiagnosticSeverity.Error,
                range=range,
            )
            for range in ranges
        ]

    diagnostics: list[types.Diagnostic] = []

    match test_outcome.outcome:
        case DepSkip(message=message, location=location):
            if not isinstance(test_outcome.expected_outcome, DepSkip):
                diagnostics.extend(
                    types.Diagnostic(
                        message=f"FunctionTest ('{test_name}') failed. Unexpected DepSkip(message='{message}', location='{location}'.",
                        severity=types.DiagnosticSeverity.Error,
                        range=range,
                    )
                    for range in ranges
                )
        case Skip(message=message, location=location):
            if not isinstance(test_outcome.expected_outcome, Skip):
                diagnostics.extend(
                    types.Diagnostic(
                        message=f"FunctionTest ('{test_name}') failed. Unexpected Skip(message='{message}', location='{location}').",
                        severity=types.DiagnosticSeverity.Error,
                        range=range,
                    )
                    for range in ranges
                )
        case PermFail(message=message, location=location):
            if not isinstance(test_outcome.expected_outcome, Skip):
                diagnostics.extend(
                    types.Diagnostic(
                        message=f"FunctionTest ('{test_name}') failed. Unexpected PermFail(message='{message}', location='{location}').",
                        severity=types.DiagnosticSeverity.Error,
                        range=range,
                    )
                    for range in ranges
                )
        case Retry(message=message, delay=delay, location=location):
            if not test_outcome.expected_resource or (
                test_outcome.expected_outcome is not None
                and not isinstance(test_outcome.expected_outcome, Skip)
            ):
                diagnostics.extend(
                    types.Diagnostic(
                        message=f"FunctionTest ('{test_name}') failed. Unexpected Retry(message='{message}', delay={delay}, location='{location}').",
                        severity=types.DiagnosticSeverity.Error,
                        range=range,
                    )
                    for range in ranges
                )
            elif test_outcome.expected_ok_value:
                diagnostics.extend(
                    types.Diagnostic(
                        message=(
                            f"FunctionTest ('{test_name}') failed. Can not "
                            "assert expected ok-value when resource modifications "
                            "requested. Ensure currentResource matches Function materializers."
                        ),
                        severity=types.DiagnosticSeverity.Error,
                        range=range,
                    )
                    for range in ranges
                )

            diagnostics.extend(
                _check_ok_value(
                    "resource",
                    test_outcome.actual_resource,
                    test_outcome.expected_resource,
                    ranges,
                )
            )

        case Ok(data=okValue) | okValue:
            if test_outcome.expected_outcome is not None and not isinstance(
                test_outcome.expected_outcome, Ok
            ):
                diagnostics.extend(
                    types.Diagnostic(
                        message=f"FunctionTest ('{test_name}') failed. Unexpected Ok(...).",
                        severity=types.DiagnosticSeverity.Error,
                        range=range,
                    )
                    for range in ranges
                )

            if test_outcome.expected_resource:
                diagnostics.extend(
                    types.Diagnostic(
                        message=f"FunctionTest ('{test_name}') failed. Can not assert expectedResource unless changes requested.",
                        severity=types.DiagnosticSeverity.Error,
                        range=range,
                    )
                    for range in ranges
                )

            diagnostics.extend(
                _check_ok_value(
                    "ok-value", okValue, test_outcome.expected_ok_value, ranges
                )
            )

    if not (
        test_outcome.expected_resource
        or test_outcome.expected_outcome
        or test_outcome.expected_ok_value
    ):
        diagnostics.extend(
            types.Diagnostic(
                message=f"FunctionTest ('{test_name}') must define expectedResource, expectedOutcome, or expectedOkValue.",
                severity=types.DiagnosticSeverity.Error,
                range=range,
            )
            for range in ranges
        )

    return diagnostics


def _check_ok_value(
    thing: str, actual: dict | None, expected: dict | None, ranges: list[types.Range]
) -> list[types.Diagnostic]:
    if expected is None:
        return []

    if actual is None:
        return [
            types.Diagnostic(
                message=f"Actual {thing} was unexpectedly `None`",
                severity=types.DiagnosticSeverity.Error,
                range=range,
            )
            for range in ranges
        ]

    wrong_fields = _dict_compare(actual, expected, base="")
    if not wrong_fields:
        return []

    return [
        types.Diagnostic(
            message=f"Mismatched {thing} fields: {wrong_fields}",
            severity=types.DiagnosticSeverity.Error,
            range=range,
        )
        for range in ranges
    ]


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
