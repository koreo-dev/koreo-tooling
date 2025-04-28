import argparse

from .prune import register_prune_subcommand
from .apply import register_apply_subcommand
from .inspect import register_inspector_subcommand


def main():
    parser = argparse.ArgumentParser(prog="koreo")
    subparsers = parser.add_subparsers(dest="command", required=True)

    register_apply_subcommand(subparsers)
    register_inspector_subcommand(subparsers)
    register_prune_subcommand(subparsers)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
