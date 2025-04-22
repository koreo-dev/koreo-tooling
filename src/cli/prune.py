import kr8s

KIND_TO_PLURAL = {
    "ResourceFunction": "resourcefunctions",
    "ValueFunction": "valuefunctions",
}


def prune_orphaned_functions(namespace=None, dry_run=True):
    workflows = list(kr8s.get("workflows.koreo.dev", namespace=namespace or kr8s.ALL))

    used_functions = set()

    for wf in workflows:
        wf_ns = wf.metadata.namespace

        for step in wf.spec.get("steps", []):
            for ref_key in ["ref", "refSwitch"]:
                ref = step.get(ref_key)
                if ref_key == "ref":
                    refs = [ref] if ref else []
                elif ref_key == "refSwitch":
                    refs = ref.get("cases", []) if ref else []

                for item in refs:
                    kind = item.get("kind")
                    name = item.get("name")
                    plural = KIND_TO_PLURAL.get(kind)
                    if plural:
                        used_functions.add((wf_ns, plural, name))

        resource_funcs = list(kr8s.get("resourcefunctions.koreo.dev", namespace=wf_ns))

        for func in resource_funcs:
            overlays = func.spec.get("overlays", [])
            for overlay_entry in overlays:
                overlay_ref = overlay_entry.get("overlayRef")
                if overlay_ref:
                    kind = overlay_ref.get("kind")
                    name = overlay_ref.get("name")
                    plural = KIND_TO_PLURAL.get(kind)
                    if plural:
                        used_functions.add((wf_ns, plural, name))

    def check_and_delete(plural):
        funcs = list(kr8s.get(f"{plural}.koreo.dev", namespace=namespace or kr8s.ALL))
        for func in funcs:
            key = (func.metadata.namespace, plural, func.metadata.name)
            if key not in used_functions:
                if dry_run:
                    print(
                        f"Orphaned {plural}: {func.metadata.namespace}/{func.metadata.name}"
                    )
                else:
                    print(
                        f"Deleting orphaned {plural}: {func.metadata.namespace}/{func.metadata.name}"
                    )
                    func.delete()

    for plural in KIND_TO_PLURAL.values():
        check_and_delete(plural)


def run_prune(args):
    if args.verbose:
        global VERBOSE
        VERBOSE = args.verbose

    prune_orphaned_functions(args.namespace, args.dry_run)


def register_prune_subcommand(subparsers):
    prune_parser = subparsers.add_parser(
        "prune", help="Prune unused koreo resource and value functions."
    )
    prune_parser.add_argument("--namespace", "-n", help="Namespace")
    prune_parser.add_argument(
        "--dry-run", "-d", action="store_true", help="Dry run mode"
    )
    prune_parser.add_argument("--verbose", "-v", action="count", help="Verbose output")
    prune_parser.set_defaults(func=run_prune)
