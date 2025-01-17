from typing import TypedDict
import argparse
import json

import kr8s
from kr8s._objects import APIObject

BAD_RESPONSE = 10

MANAGED_RESOURCES_ANNOTATION = "koreo.realkinetic.com/managed-resources"

VERBOSE = 0


def main():
    arg_parser = argparse.ArgumentParser(
        description="Inpsect Koreo Workflow resources and resource hierarchy.",
        epilog="Example usage: inspector ResourceKind -n resource-namespace resource-name",
    )

    arg_parser.add_argument(
        "kind",
        help="Kubernetes Resource Kind for the workflow resource to inspect.",
    )

    arg_parser.add_argument(
        "name",
        help="Kubernetes Resource name for the workflow resource to inspect.",
    )

    arg_parser.add_argument(
        "--namespace",
        "-n",
        help="Kubernetes namespace containing the workflow resource.",
        default="default",
    )

    arg_parser.add_argument(
        "--verbose",
        "-v",
        help="Verbose output, each -v adds another level of verbosity.",
        action="count",
    )

    arguments = arg_parser.parse_args()

    if arguments.verbose:
        global VERBOSE
        VERBOSE = arguments.verbose

    print(f"Getting {arguments.kind}:{arguments.namespace}:{arguments.name}")

    resource_ref = ManagedResourceRef(
        kind=arguments.kind,
        name=arguments.name,
        namespace=arguments.namespace,
        apiVersion="",
        plural="",
        readonly=False,
    )

    print("Workflow Trigger")
    load_resource(resource_ref)


RESOURCE_PRINTER = """
apiVersion: {apiVersion}
kind: {kind}
metadata:
    name: {metadata.name}
    namespace: {metadata.namespace}
    uid: {metadata.uid}
"""

CONDITION_PRINTER = """
              type: {type}
            reason: {reason}
           message: {message}
          location: {location}
            status: {status}
lastTransitionTime: {lastTransitionTime}
    lastUpdateTime: {lastUpdateTime}
"""


def inspect_resource(resource: APIObject):
    print(RESOURCE_PRINTER.format_map(resource.raw))
    if VERBOSE and "status" in resource.raw:
        conditions = resource.status.get("conditions")
        if conditions:
            for condition in conditions:
                print("Conditions:")
                print(CONDITION_PRINTER.format_map(condition))

    if VERBOSE > 2:
        print(json.dumps(resource.raw, indent="  "))
    elif VERBOSE > 1:
        print(json.dumps(resource.spec, indent="  "))

    managed_resources_raw = resource.annotations.get(MANAGED_RESOURCES_ANNOTATION)
    if not managed_resources_raw:
        return

    managed_resources: dict[
        str, ManagedResourceRef | list[ManagedResourceRef] | None
    ] = json.loads(managed_resources_raw)
    for step, resource_ref in managed_resources.items():
        match resource_ref:
            case None:
                continue
            case list():
                print(f"Step '{step}' managed resources:")
                for sub_resource_ref in resource_ref:
                    load_resource(resource_ref=sub_resource_ref)
            case {}:
                print(f"Step '{step}' managed resources:")
                load_resource(resource_ref=resource_ref)


class ManagedResourceRef(TypedDict):
    apiVersion: str
    kind: str
    plural: str
    name: str
    namespace: str
    readonly: bool


def load_resource(resource_ref: ManagedResourceRef):
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


if __name__ == "__main__":
    main()
