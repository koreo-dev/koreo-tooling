from typing import NamedTuple, Sequence
import os

os.environ["KOREO_DEV_TOOLING"] = "true"


from lsprotocol import types

from koreo import cache
from koreo.workflow.structure import Workflow, ErrorStep
from koreo.result import is_unwrapped_ok

from koreo_tooling import constants
from koreo_tooling.analysis import call_arg_compare
from koreo_tooling.indexing import compute_abs_range
from koreo_tooling.langserver.rangers import block_range_extract


def process_workflows(
    path: str, workflows: Sequence[tuple[str, types.Range]]
) -> list[types.Diagnostic]:
    diagnostics: list[types.Diagnostic] = []

    for koreo_cache_key, resource_range in workflows:
        cached_resource = cache.get_resource_system_data_from_cache(
            resource_class=Workflow, cache_key=koreo_cache_key
        )

        if not cached_resource or not cached_resource.resource:
            diagnostics.append(
                types.Diagnostic(
                    message=f"Workflow not yet prepared ({koreo_cache_key}) or not in Koreo cache.",
                    severity=types.DiagnosticSeverity.Error,
                    range=resource_range,
                )
            )
            continue

        if not is_unwrapped_ok(cached_resource.resource):
            diagnostics.append(
                types.Diagnostic(
                    message=f"Workflow ({koreo_cache_key}) is not ready ({cached_resource.resource.message}).",
                    severity=types.DiagnosticSeverity.Error,
                    range=resource_range,
                )
            )
            continue

        workflow_result = _process_workflow(
            path=path,
            resource_range=resource_range,
            workflow_name=koreo_cache_key,
            workflow=cached_resource.resource,
            raw_spec=cached_resource.spec,
            koreo_metadata=cached_resource.system_data,
        )
        if workflow_result.diagnostics:
            diagnostics.extend(workflow_result.diagnostics)

    return diagnostics


class ProcessResult(NamedTuple):
    error: bool = False
    diagnostics: list[types.Diagnostic] | None = None


def _process_workflow(
    path: str,
    resource_range: types.Range,
    workflow_name: str,
    workflow: Workflow,
    raw_spec: dict,
    koreo_metadata: dict | None,
) -> ProcessResult:
    if not koreo_metadata:
        return ProcessResult(
            error=True,
            diagnostics=[
                types.Diagnostic(
                    message=f"Workflow ('{workflow_name}') missing in Koreo Cache (this _should_ be impossible).",
                    severity=types.DiagnosticSeverity.Error,
                    range=resource_range,
                )
            ],
        )

    semantic_path = koreo_metadata.get("path", "")
    if semantic_path != path:
        return ProcessResult(
            error=True,
            diagnostics=[
                types.Diagnostic(
                    message=(
                        f"Duplicate Workflow ('{workflow_name}') detected in "
                        f"('{semantic_path}'), skipping further analysis."
                    ),
                    severity=types.DiagnosticSeverity.Error,
                    range=resource_range,
                )
            ],
        )

    semantic_anchor = koreo_metadata.get("anchor")
    if not semantic_anchor:
        return ProcessResult(
            error=True,
            diagnostics=[
                types.Diagnostic(
                    message=f"Unknown error processing Workflow ('{workflow_name}'), semantic analysis data missing from Koreo cache.",
                    severity=types.DiagnosticSeverity.Error,
                    range=resource_range,
                )
            ],
        )

    has_step_error = False

    diagnostics: list[types.Diagnostic] = []
    if not is_unwrapped_ok(workflow.steps_ready):
        diagnostics.append(
            types.Diagnostic(
                message=f"Workflow is not ready ({workflow.steps_ready.message}).",
                severity=types.DiagnosticSeverity.Warning,
                range=resource_range,
            )
        )
        if not raw_spec:
            return ProcessResult(error=True, diagnostics=diagnostics)

    raw_steps_spec = raw_spec.get("steps")

    if not raw_steps_spec:
        step_specs = {}
    else:
        step_specs = {step_spec.get("label"): step_spec for step_spec in raw_steps_spec}

    if not step_specs and workflow.steps:
        diagnostics.append(
            types.Diagnostic(
                message=f"Workflow steps are malformed.",
                severity=types.DiagnosticSeverity.Warning,
                range=resource_range,
            )
        )
        return ProcessResult(error=True, diagnostics=diagnostics)

    raw_config_step_spec = raw_spec.get("configStep")

    if raw_config_step_spec and workflow.config_step:
        step_block = block_range_extract(
            search_key=f"config_step_block",
            search_nodes=semantic_anchor.children,
            anchor=semantic_anchor,
        )
        config_step_result = _process_workflow_step(
            workflow.config_step,
            step_block,
            raw_config_step_spec,
            semantic_anchor,
            implicit_inputs=("parent",),
        )

        has_step_error = has_step_error or config_step_result.error
        if config_step_result.diagnostics:
            diagnostics.extend(config_step_result.diagnostics)

    if has_step_error:
        diagnostics.append(
            types.Diagnostic(
                message=f"Workflow steps are not ready.",
                severity=types.DiagnosticSeverity.Error,
                range=resource_range,
            )
        )

    for step in workflow.steps:
        step_block = block_range_extract(
            search_key=f"Step:{step.label}",
            search_nodes=semantic_anchor.children,
            anchor=semantic_anchor,
        )
        match step_block:
            case None:
                continue
            case list(block_diagnostics):
                diagnostics.extend(block_diagnostics)
                continue

        step_spec = step_specs.get(step.label)

        step_result = _process_workflow_step(
            step, step_block, step_spec, semantic_anchor
        )

        has_step_error = has_step_error or step_result.error
        if step_result.diagnostics:
            diagnostics.extend(step_result.diagnostics)

    if has_step_error:
        diagnostics.append(
            types.Diagnostic(
                message=f"Workflow steps are not ready.",
                severity=types.DiagnosticSeverity.Error,
                range=resource_range,
            )
        )

    return ProcessResult(error=has_step_error, diagnostics=diagnostics)


def _process_workflow_step(
    step,
    step_semantic_block,
    step_spec,
    semantic_anchor,
    implicit_inputs: Sequence[str] | None = None,
) -> ProcessResult:
    if isinstance(step, ErrorStep):
        return ProcessResult(
            error=True,
            diagnostics=_step_label_error_diagnostic(
                label=step.label,
                step_semantic_block=step_semantic_block,
                semantic_anchor=semantic_anchor,
                message=f"Not ready {step.outcome.message}.",
            ),
        )

    # These are just the "top level" direct inputs. No consideration to
    # internal structure.
    first_tier_inputs = set(
        input_key.group("name")
        for input_key in (
            constants.INPUT_NAME_PATTERN.match(key)
            for key in step.logic.dynamic_input_keys
        )
        if input_key
    )

    raw_inputs = step_spec.get("inputs", {})

    provided_input_keys = list(raw_inputs.keys())

    if implicit_inputs:
        provided_input_keys.extend(implicit_inputs)

    raw_mapped_input = step_spec.get("mappedInput", {})
    mapped_input_key = raw_mapped_input.get("inputKey")
    if mapped_input_key:
        provided_input_keys.append(f"{mapped_input_key}")

    has_error = False
    diagnostics: list[types.Diagnostic] = []

    inputs_block = block_range_extract(
        search_key="inputs",
        search_nodes=step_semantic_block.children,
        anchor=semantic_anchor,
    )
    match inputs_block:
        case list(block_diagnostics):
            has_error = True
            diagnostics.extend(block_diagnostics)
            inputs_block = None

    inputs = call_arg_compare(provided_input_keys, first_tier_inputs)
    for argument, (provided, expected) in inputs.items():
        if not expected and provided:
            has_error = True

            # This is not done earlier so that we can still flag issues at the
            # workflow level.
            if not inputs_block:
                continue

            input_block = block_range_extract(
                search_key=f"input:{argument}",
                search_nodes=step_semantic_block.children,
                anchor=semantic_anchor,
            )
            match input_block:
                case None:
                    continue
                case list(block_diagnostics):
                    diagnostics.extend(block_diagnostics)
                    continue

            raw_arg = raw_inputs.get(argument)

            diagnostics.append(
                types.Diagnostic(
                    message=f"Input ('{argument}') not expected. {raw_arg}.",
                    severity=types.DiagnosticSeverity.Warning,
                    range=compute_abs_range(input_block, semantic_anchor),
                )
            )

        elif expected and not provided:
            has_error = True

            # This is not done earlier so that we can still flag issues at the
            # workflow level.
            if not inputs_block:
                continue

            diagnostics.append(
                types.Diagnostic(
                    message=f"Missing input ('{argument}').",
                    severity=types.DiagnosticSeverity.Error,
                    range=compute_abs_range(inputs_block, semantic_anchor),
                )
            )

    if has_error:
        diagnostics.extend(
            _step_label_error_diagnostic(
                label=step.label,
                step_semantic_block=step_semantic_block,
                semantic_anchor=semantic_anchor,
                message="Step has errors",
            )
        )
    return ProcessResult(error=has_error, diagnostics=diagnostics)


def _step_label_error_diagnostic(
    label: str, step_semantic_block, semantic_anchor, message: str
) -> list[types.Diagnostic]:
    label_block = block_range_extract(
        search_key=f"label:{label}",
        search_nodes=step_semantic_block.children,
        anchor=semantic_anchor,
    )
    match label_block:
        case list(label_diagnostics):
            return label_diagnostics
        case None:
            diagnostic_range = compute_abs_range(step_semantic_block, semantic_anchor)
        case _:
            diagnostic_range = compute_abs_range(label_block, semantic_anchor)

    return [
        types.Diagnostic(
            message=message,
            severity=types.DiagnosticSeverity.Warning,
            range=diagnostic_range,
        )
    ]
