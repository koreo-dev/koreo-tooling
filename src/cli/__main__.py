import argparse
from .apply import register_apply_subcommand
from .inspect import register_inspector_subcommand


def main():
    parser = argparse.ArgumentParser(prog="koreo")
    subparsers = parser.add_subparsers(dest="command", required=True)

    register_apply_subcommand(subparsers=subparsers)
    register_inspector_subcommand(subparsers)

    args = parser.parse_args()

    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
