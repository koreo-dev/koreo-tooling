import datetime

import kr8s

ANNOTATION = "koreo.dev/last-manual-reconcile"


def run_reconcile(args):
    if args.verbose:
        global VERBOSE
        VERBOSE = args.verbose

    print(f"Getting {args.kind}:{args.namespace}:{args.name}")

    kr8s_api = kr8s.api()

    resources = kr8s_api.get(
        args.kind,
        args.name,
        namespace=args.namespace,
    )
    now = datetime.datetime.utcnow().isoformat() + "Z"

    print("Workflow Trigger")
    # Create patch to apply
    patch = {"metadata": {"annotations": {ANNOTATION: now}}}

    # Apply patch
    for resource in resources:
        resource.patch(patch)
        print(
            f"Updated {args.kind}/{args.name} in {args.namespace} with last reconciled={now}"
        )


def register_reconcile_subcommand(subparsers):
    reconcile_parser = subparsers.add_parser(
        "reconcile", help="Reconcile a Koreo Workflow instance."
    )
    reconcile_parser.add_argument("kind", help="Kubernetes Resource Kind")
    reconcile_parser.add_argument("name", help="Resource name")
    reconcile_parser.add_argument(
        "--namespace", "-n", default="default", help="Namespace"
    )
    reconcile_parser.add_argument(
        "--verbose", "-v", action="count", help="Verbose output"
    )
    reconcile_parser.set_defaults(func=run_reconcile)
