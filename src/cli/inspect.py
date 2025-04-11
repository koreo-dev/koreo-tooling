from typing import TypedDict
import json

import kr8s
from kr8s._objects import APIObject

from colorist import BrightColor, Color

BAD_RESPONSE = 10

MANAGED_RESOURCES_ANNOTATION = "koreo.dev/managed-resources"

VERBOSE = 0


def _api_version(api_version: str):
    return f"{Color.CYAN}{api_version}{Color.OFF}"


def _kind(kind: str):
    return f"{BrightColor.BLUE}{kind}{BrightColor.OFF}"


def _namespace(namespace: str):
    return f"{BrightColor.GREEN}{namespace}{BrightColor.OFF}"


def _name(name: str):
    return f"{Color.YELLOW}{name}{Color.OFF}"


def _label(name: str):
    return f"{Color.MAGENTA}{name}{Color.OFF}"


def _step_name(name: str):
    return f"{BrightColor.RED}{name}{BrightColor.OFF}"


RESOURCE_PRINTER = f"""
{_label('apiVersion')}: {_api_version('{apiVersion}')}
{_label('kind')}: {_kind('{kind}')}
{_label('metadata')}:
    {_label('name')}: {_name('{metadata.name}')}
    {_label('namespace')}: {_namespace('{metadata.namespace}')}
    {_label('uid')}: {{metadata.uid}}
"""

CONDITION_PRINTER = f"""
              {_label('type')}: {_api_version('{type}')}
            {_label('reason')}: {_kind('{reason}')}
           {_label('message')}: {{message}}
          {_label('location')}: {{location}}
            {_label('status')}: {{status}}
{_label('lastTransitionTime')}: {{lastTransitionTime}}
    {_label('lastUpdateTime')}: {{lastUpdateTime}}
"""

default_condition = {
    "type": "<missing>",
    "reason": "<missing>",
    "message": "<missing>",
    "location": "<missing>",
    "status": "<missing>",
    "lastTransitionTime": "<missing>",
    "lastUpdateTime": "<missing>",
}


def inspect_resource(resource: APIObject):
    print(RESOURCE_PRINTER.format_map(resource.raw))
    if VERBOSE and "status" in resource.raw:
        conditions = resource.status.get("conditions")
        if conditions:
            print("Conditions:")
            for condition in conditions:
                print(CONDITION_PRINTER.format_map(default_condition | condition))

    if VERBOSE > 2:
        print(json.dumps(resource.raw, indent="  "))
    elif VERBOSE > 1:
        if "spec" in resource.raw:
            print(json.dumps(resource.spec, indent="  "))

    managed_resources_raw = resource.annotations.get(MANAGED_RESOURCES_ANNOTATION)
    if not managed_resources_raw:
        return

    _process_managed_resources(json.loads(managed_resources_raw))


class ManagedResourceRef(TypedDict):
    apiVersion: str
    kind: str
    plural: str
    name: str
    namespace: str
    readonly: bool


def _process_managed_resources(
    managed_resources: dict[
        str,
        ManagedResourceRef
        | list[ManagedResourceRef]
        | dict[str, ManagedResourceRef]
        | None,
    ],
):
    for step, resource_ref in managed_resources.items():
        match resource_ref:
            case None:
                continue
            case list():
                print(f"Step '{_step_name(step)}' managed resources:")
                for sub_resource_ref in resource_ref:
                    load_resource(sub_resource_ref)
            case {"apiVersion": _, "kind": _, "name": _, "namespace": _}:
                print(f"Step '{_step_name(step)}' managed resource:")
                load_resource(resource_ref=resource_ref)

            case {}:
                print(f"Step '{_step_name(step)}' managed resources (sub-workflow):")
                _process_managed_resources(resource_ref)


def load_resource(resource_ref: ManagedResourceRef):
    if not resource_ref:
        print("No resource")
        return

    resources = kr8s.get(
        resource_ref.get("kind"),
        resource_ref.get("name"),
        namespace=resource_ref.get("namespace"),
    )

    match resources:
        case list():
            for resource in resources:
                match resource:
                    case APIObject():
                        inspect_resource(resource)
                    case _:
                        print(
                            f"Unexpected response type from Kubernetes API Server {type(resource)}"
                        )
                        if VERBOSE:
                            print(resource)
                        exit(BAD_RESPONSE)

        case APIObject():
            inspect_resource(resources)

        case other:
            print(f"Unexpected response type from Kubernetes API Server {type(other)}")
            if VERBOSE:
                print(other)
            exit(BAD_RESPONSE)


def run_inspector(args):
    if args.verbose:
        global VERBOSE
        VERBOSE = args.verbose

    print(f"Getting {args.kind}:{args.namespace}:{args.name}")

    resource_ref = ManagedResourceRef(
        kind=args.kind,
        name=args.name,
        namespace=args.namespace,
        apiVersion="",
        plural="",
        readonly=False,
    )

    print("Workflow Trigger")
    load_resource(resource_ref)


def register_inspector_subcommand(subparsers):
    inspect_parser = subparsers.add_parser(
        "inspect", help="Inspect a Koreo Workflow and resource hierarchy."
    )
    inspect_parser.add_argument("kind", help="Kubernetes Resource Kind")
    inspect_parser.add_argument("name", help="Resource name")
    inspect_parser.add_argument(
        "--namespace", "-n", default="default", help="Namespace"
    )
    inspect_parser.add_argument(
        "--verbose", "-v", action="count", help="Verbose output"
    )
    inspect_parser.set_defaults(func=run_inspector)
