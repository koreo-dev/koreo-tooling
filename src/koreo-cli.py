from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Literal, NamedTuple
import argparse
import asyncio
import os
import re

import yaml

from rich.console import Console
from rich.text import Text
from rich.tree import Tree
from rich.table import Table

import nanoid

console = Console()

os.environ["KOREO_DEV_TOOLING"] = "true"

from koreo.cache import get_resource_from_cache, prepare_and_cache
from koreo.function.prepare import prepare_function
from koreo.function.structure import Function
from koreo.resource_template.prepare import prepare_resource_template
from koreo.resource_template.structure import ResourceTemplate
from koreo.result import is_unwrapped_ok
from koreo.workflow.prepare import prepare_workflow
from koreo.workflow.registry import get_custom_crd_workflows
from koreo.workflow.structure import Workflow, ConfigCRDRef, ErrorStep

from koreo_tooling import constants
from koreo_tooling.analysis import call_arg_compare


PREPARE_MAP = {
    "Function": (Function, prepare_function),
    "ResourceTemplate": (ResourceTemplate, prepare_resource_template),
    "Workflow": (Workflow, prepare_workflow),
}


EXIT_CODES = {"bad_yaml_path": 1}

HEADER_STYLE = "blue bold"
GROUP_STYLE = "blue"

ERROR_STYLE = "red bold"
WARN_STYLE = "yellow"
OK_STYLE = "green"
NORMAL_STYLE = ""


async def yaml_loader_directory(path: Path, root_tree: Tree, verbose: bool = False):
    tree_expanded = False or verbose
    tree = root_tree.add(
        Text(f"Processesing all YAMLs within: '{path}'", HEADER_STYLE),
        expanded=tree_expanded,
    )

    crds = set[ConfigCRDRef]()

    for yaml_file in _yaml_searcher(path):
        file_crds, file_expanded = await yaml_loader_file(
            path=yaml_file, root_tree=tree, verbose=verbose
        )
        crds.update(file_crds)
        tree_expanded = tree_expanded or file_expanded

    tree.expanded = tree_expanded

    return crds


async def yaml_loader_file(
    path: Path,
    root_tree: Tree,
    seen_functions: set[str] | None = None,
    verbose: bool = False,
):
    file_expanded = False or verbose
    file_tree = root_tree.add(
        Text(f"Processing '{path}'.", GROUP_STYLE), expanded=file_expanded
    )

    if not seen_functions:
        seen_functions = set[str]()

    crds = set[ConfigCRDRef]()

    with open(path, "r") as raw_yaml:
        yaml_blocks = yaml.load_all(raw_yaml, Loader=yaml.Loader)
        for yaml_block in yaml_blocks:
            try:
                api_version = yaml_block.get("apiVersion")
                kind = yaml_block.get("kind")
            except:
                # file_expanded = True
                file_tree.add(Text(f"Skipping empty block.", WARN_STYLE))
                continue

            if api_version not in {constants.API_VERSION, constants.CRD_API_VERSION}:
                # file_expanded = True
                file_tree.add(Text(f"Skipping '{kind}.{api_version}'.", WARN_STYLE))
                continue

            if kind not in PREPARE_MAP and kind != constants.CRD_KIND:
                file_expanded = True
                file_tree.add(Text(f"Skipping '{kind}.{api_version}'.", WARN_STYLE))
                continue

            if kind == constants.CRD_KIND:
                _load_crd_info(
                    metadata=yaml_block.get("metadata"), spec=yaml_block.get("spec")
                )
                continue

            # continue
            resource_class, preparer = PREPARE_MAP[kind]
            metadata = yaml_block.get("metadata", {})
            metadata["resourceVersion"] = nanoid.generate(size=10)

            name = metadata.get("name")

            if kind == "Function":
                if name in seen_functions:
                    file_expanded = True
                    file_tree.add(
                        Text(
                            f"WARNING: Duplicate function name ({name}) found.",
                            WARN_STYLE,
                        )
                    )
                seen_functions.add(name)

            try:
                prepared = await prepare_and_cache(
                    resource_class=resource_class,
                    preparer=preparer,
                    metadata=metadata,
                    spec=yaml_block.get("spec", {}),
                )
            except Exception as err:
                file_expanded = True
                file_tree.add(
                    Text(
                        f"FAILED TO Extract ('{kind}.{api_version}') from {yaml_block.get('metadata')} ({err}).",
                        ERROR_STYLE,
                    )
                )
                raise
                continue

            if kind == "Workflow":
                crds.add(prepared.crd_ref)

            file_tree.add(Text(f"Extracted '{kind}:{name}'.", OK_STYLE))

    file_tree.expanded = file_expanded

    return crds, file_expanded


def _yaml_searcher(path: Path):
    """List files ending in .yaml or .yml.

    TODO: Is there a better way than using two different recursive calls?
    """

    suffixes = ("yaml", "yml")

    for suffix in suffixes:
        for match in path.rglob(f"*.{suffix}"):
            yield match


# TODO: Preserve unknown fields and re-emit them


class SimpleTypeProperties(NamedTuple):
    property_type: Literal["integer", "string", "boolean"]
    nullable: bool | None
    description: str | None
    default: Any | None


class ObjectTypeProperties(NamedTuple):
    property_type: Literal["object"]
    nullable: bool | None
    description: str | None
    default: Any | None

    properties: dict[str, CrdPropertyType]

    required: list[str] | None


class ArrayTypeProperties(NamedTuple):
    property_type: Literal["array"]
    nullable: bool | None
    description: str | None
    default: Any | None

    items: CrdPropertyType


CrdPropertyType = SimpleTypeProperties | ObjectTypeProperties | ArrayTypeProperties


def _crd_to_type_properties(property_info_spec: dict) -> CrdPropertyType:
    property_type = property_info_spec.get("type")

    nullable = property_info_spec.get("nullable")
    description = property_info_spec.get("description")
    default = property_info_spec.get("default")
    required = property_info_spec.get("required")

    if property_type == "object":
        return ObjectTypeProperties(
            property_type="object",
            nullable=nullable,
            description=description,
            default=default,
            required=required,
            properties={
                property: _crd_to_type_properties(property_info_spec=sub_spec)
                for property, sub_spec in property_info_spec.get(
                    "properties", {}
                ).items()
            },
        )

    if property_type == "array":
        return ArrayTypeProperties(
            property_type="array",
            nullable=nullable,
            description=description,
            default=default,
            items=_crd_to_type_properties(
                property_info_spec=property_info_spec.get("items")
            ),
        )

    return SimpleTypeProperties(
        property_type=property_type,
        nullable=nullable,
        description=description,
        default=default,
    )


KNOWN_CRDS = defaultdict(lambda: defaultdict(dict))


def _load_crd_info(metadata: dict, spec: dict):
    global KNOWN_CRDS

    api_group = spec.get("group")
    kind = spec.get("names", {}).get("kind")

    for version_spec in spec.get("versions"):
        version = version_spec.get("name")
        schema_properties = version_spec.get("schema", {}).get("openAPIV3Schema")
        if not schema_properties:
            print("missing")

        KNOWN_CRDS[api_group][kind][version] = _crd_to_type_properties(
            property_info_spec=schema_properties
        )


INPUT_NAME_PATTERN = re.compile("inputs.([^.]+).?")

OUTCOME = Literal["OK", "WARN", "ERROR"]
STYLE_MAP: dict[OUTCOME, str] = {
    "OK": OK_STYLE,
    "WARN": WARN_STYLE,
    "ERROR": ERROR_STYLE,
}


class CheckerResult(NamedTuple):
    expanded: bool
    outcome: OUTCOME
    label: str
    subtree: list[Tree] | None
    koreo_inputs: set[str] | None


def extract_crds(crds: set[ConfigCRDRef], _: Tree, verbose: bool = False):
    for crd_ref in crds:
        crd_cache_key = f"{crd_ref.api_group}:{crd_ref.kind}:{crd_ref.version}"

        workflow_cache_keys = get_custom_crd_workflows(crd_cache_key)
        koreo_inputs = set[str]()
        for workflow_cache_key in workflow_cache_keys:
            result = process_workflow(workflow_cache_key, verbose=verbose)
            if result.koreo_inputs:
                koreo_inputs.update(result.koreo_inputs)

        trigger_structure = _structure_extractor("parent.spec", references=koreo_inputs)
        if trigger_structure:
            print(
                yaml.dump(
                    data_structure_to_crd(
                        api_group=crd_ref.api_group,
                        version=crd_ref.version,
                        kind=crd_ref.kind,
                        structure=trigger_structure,
                    ),
                    sort_keys=False,
                ),
            )


def call_checker(crds: set[ConfigCRDRef], root_tree: Tree, verbose: bool = False):
    call_tree_expanded = False or verbose
    call_checker_tree = root_tree.add(
        Text("Checking CRD call stacks", HEADER_STYLE), expanded=call_tree_expanded
    )

    for crd_ref in crds:
        crd_cache_key = f"{crd_ref.api_group}:{crd_ref.kind}:{crd_ref.version}"

        crd_tree_expanded = False or verbose
        crd_tree = call_checker_tree.add(
            Text(f"Processing Workflows for {crd_cache_key}", GROUP_STYLE),
            expanded=crd_tree_expanded,
        )

        workflow_cache_keys = get_custom_crd_workflows(crd_cache_key)
        for workflow_cache_key in workflow_cache_keys:
            result = process_workflow(workflow_cache_key, verbose=verbose)

            workflow_tree = crd_tree.add(
                Text(result.label, style=STYLE_MAP[result.outcome]),
                expanded=result.expanded,
            )

            if result.subtree:
                workflow_tree.children.extend(result.subtree)

            if result.expanded:
                crd_tree.expanded = True
                call_checker_tree.expanded = True


def process_workflow(workflow_cache_key, verbose: bool) -> CheckerResult:
    workflow = get_resource_from_cache(
        resource_class=Workflow, cache_key=workflow_cache_key
    )
    if not workflow:
        return CheckerResult(
            expanded=True,
            outcome="ERROR",
            label=f"Workflow ({workflow_cache_key}) is missing.",
            subtree=None,
            koreo_inputs=None,
        )

    # if not is_unwrapped_ok(workflow.steps_ready):
    #     return CheckerResult(
    #         expanded=True,
    #         outcome="ERROR",
    #         label=f"Workflow ({workflow_cache_key}) is not ready ({workflow.steps_ready.message}).",
    #         subtree=None,
    #         koreo_inputs=None,
    #     )

    expanded = False or verbose
    step_trees = []
    koreo_inputs = set[str]()
    seen_step_labels = set[str]()

    for step in workflow.steps:
        tree, step_koreo_inputs = process_step(step, verbose=verbose)

        if step.label in seen_step_labels:
            tree.label = Text(f"Duplicate: {step.label}", ERROR_STYLE)
            expanded = True

        seen_step_labels.add(step.label)

        step_trees.append(tree)
        koreo_inputs.update(step_koreo_inputs)
        expanded = expanded or tree.expanded

    label = f"Workflow ({workflow_cache_key}) steps"
    return CheckerResult(
        expanded=expanded,
        outcome="OK" if is_unwrapped_ok(workflow.steps_ready) else "ERROR",
        label=label,
        subtree=step_trees,
        koreo_inputs=koreo_inputs,
    )


def process_step(step, verbose: bool):
    expand_step = False or verbose
    if isinstance(step, ErrorStep):
        step_tree = Tree(Text(f"{step.label}", ERROR_STYLE), expanded=True)
        step_tree.add(Text(step.outcome.message, ERROR_STYLE))
        return step_tree, []

    step_tree = Tree(Text(f"{step.label}", OK_STYLE), expanded=expand_step)

    # These are just the "top level" direct inputs. No consideration to
    # internal structure.
    first_tier_inputs: set[str] = set(
        INPUT_NAME_PATTERN.match(key).group(1)
        for key in step.logic.dynamic_input_keys
        if key.startswith("inputs")
    )

    input_table = Table("[bold]Argument", "[bold]Provided", "[bold]Expected")
    inputs = call_arg_compare(step.provided_input_keys, first_tier_inputs)
    for argument, (provided, expected) in inputs.items():
        style = NORMAL_STYLE
        if not expected and provided:
            style = WARN_STYLE
            expand_step = True
        elif expected and not provided:
            style = ERROR_STYLE
            expand_step = True

        input_table.add_row(
            Text(
                argument,
            ),
            Text(
                "\u2713" if provided else "missing",
                justify="center",
            ),
            Text(
                "\u2713" if expected else "unused",
                justify="center",
            ),
            style=style,
        )

    step_tree.add(input_table)
    step_tree.expanded = expand_step

    return step_tree, [
        key
        for key in step.logic.dynamic_input_keys
        if not (
            key.startswith("inputs")
            or key.startswith("resource")
            or key.startswith("template")
            or key.startswith("context")
        )
    ]


class DataStructureTree(NamedTuple):
    name: str
    children: list[DataStructureTree] | None


def data_structure_to_crd(
    api_group: str, version: str, kind: str, structure: DataStructureTree
) -> dict:
    pluralized = f"{kind.lower()}s"
    return {
        "apiVersion": constants.CRD_API_VERSION,
        "kind": constants.CRD_KIND,
        "metadata": {"name": f"{pluralized}.{api_group}"},
        "spec": {
            "scope": "Namespaced",
            "group": api_group,
            "names": {"kind": kind, "plural": pluralized, "singular": kind.lower()},
            "versions": [
                {
                    "name": version,
                    "served": True,
                    "storage": True,
                    "schema": {
                        "openAPIV3Schema": data_structure_to_openapi_schema(structure)
                    },
                }
            ],
        },
    }


def data_structure_to_openapi_schema(structure: DataStructureTree) -> dict:
    if not structure.children:
        return {"type": "TODO", "nullable": False}

    properties = {}
    for child in structure.children:
        properties[child.name] = data_structure_to_openapi_schema(structure=child)

    return {
        "type": "object",
        "nullable": False,
        "properties": properties,
        "required": list(properties.keys()),
    }


def _structure_extractor(root: str, references: list[str]) -> DataStructureTree | None:

    root_children = []

    sub_structures = [key for key in references if key.startswith(f"{root}.")]
    for field in sub_structures:
        # Pop off the root + the separating '.'
        field_name = field[len(root) + 1 :]

        # If there are more parts in the name, skip.
        if "." in field_name:
            continue

        root_children.append(
            _structure_extractor(root=field, references=sub_structures),
        )

    field_name = root[root.rfind(".") + 1 :]
    return DataStructureTree(
        name=field_name, children=root_children if root_children else None
    )


async def main():
    program_args = argparse.ArgumentParser(
        prog="koreo-dev",
        description=(
            "Koreo Dev Tooling provides helpers to make working with Koreo "
            "resources more ergonomic."
        ),
    )

    program_args.add_argument(
        "--verbose",
        dest="verbose",
        action="store_true",
        default=False,
    )

    yaml_source = program_args.add_mutually_exclusive_group(required=True)
    yaml_source.add_argument(
        "--yaml-dir",
        dest="yaml_dir",
        type=Path,
    )

    yaml_source.add_argument(
        "--yaml-file",
        dest="yaml_file",
        type=Path,
    )

    run_mode = program_args.add_mutually_exclusive_group(required=True)

    run_mode.add_argument(
        "--check",
        dest="check_calls",
        action="store_true",
        default=False,
    )

    run_mode.add_argument(
        "--check-watch",
        dest="check_calls_watch",
        action="store_true",
        default=False,
    )

    run_mode.add_argument(
        "--generate-trigger-crds",
        dest="generate_trigger_crds",
        action="store_true",
        default=False,
    )

    parsed_args = program_args.parse_args()

    tree = Tree(label="[bold white]Koreo Dev Tooling")

    if parsed_args.yaml_dir:
        if not parsed_args.yaml_dir.exists():
            console.print("The YAML directory provided does not exist.")
            exit(EXIT_CODES["bad_yaml_path"])

        crds = await yaml_loader_directory(
            path=parsed_args.yaml_dir, root_tree=tree, verbose=parsed_args.verbose
        )
    elif parsed_args.yaml_file:
        if not parsed_args.yaml_file.exists():
            console.print("The YAML file provided does not exist.")
            exit(EXIT_CODES["bad_yaml_path"])

        crds, _ = await yaml_loader_file(
            path=parsed_args.yaml_file, root_tree=tree, verbose=parsed_args.verbose
        )

    if parsed_args.generate_trigger_crds:
        extract_crds(crds, tree, verbose=parsed_args.verbose)

    if parsed_args.check_calls:
        call_checker(crds, root_tree=tree, verbose=parsed_args.verbose)
        console.print(tree)


if __name__ == "__main__":
    asyncio.run(main())
