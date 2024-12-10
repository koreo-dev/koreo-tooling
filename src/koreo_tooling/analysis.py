from typing import Iterable


def call_arg_compare(
    lhs: Iterable[str], rhs: Iterable[str]
) -> dict[str, tuple[bool, bool]]:
    arguments: dict[str, tuple[bool, bool]] = {}
    for argument in lhs:
        arguments[argument] = (True, False)

    for argument in rhs:
        lhs_state, _ = arguments.get(argument, (False, False))
        arguments[argument] = (lhs_state, True)

    return arguments
