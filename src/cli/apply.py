import argparse
import os
import subprocess
import time
from pathlib import Path


def apply_command(source_dir: str, namespace: str, force: bool):
    source_path = Path(source_dir)

    if not source_path.is_dir():
        print(f"Error: Directory {source_dir} does not exist.")
        exit(1)

    for dirpath, _, _ in os.walk(source_path):
        dir_path = Path(dirpath)
        last_modified_file = dir_path / ".last_modified"

        if not force and last_modified_file.exists():
            with open(last_modified_file) as f:
                try:
                    last_run = int(f.read().strip())
                except ValueError:
                    last_run = 0
        else:
            last_run = 0

        yaml_files = []

        for koreo_file in dir_path.glob("*.koreo"):
            try:
                file_mod_time = int(koreo_file.stat().st_mtime)
            except OSError:
                continue

            if not force and file_mod_time <= last_run:
                continue

            yaml_file = koreo_file.with_suffix(".yaml")
            yaml_file.write_text(koreo_file.read_text())
            print(f"Converted {koreo_file} to {yaml_file}")
            yaml_files.append(yaml_file)

        if yaml_files:
            try:
                subprocess.run(
                    ["kubectl", "apply", "-f", str(dir_path), "-n", namespace],
                    check=True,
                )
                print(f"Applied all YAML files in {dir_path} successfully.")
            except subprocess.CalledProcessError:
                print(f"Error applying YAML files in {dir_path}.")
                exit(1)

            for yaml_file in yaml_files:
                yaml_file.unlink()
            print(f"Cleaned up YAML files in {dir_path}.")

        # Write new timestamp
        with open(last_modified_file, "w") as f:
            f.write(str(int(time.time())))
        print(f"Updated last modified time for {dir_path}.")

    print("All .koreo files processed and cleaned up successfully.")


# To integrate with your CLI, add this to your argparse setup
def register_apply_subcommand(subparsers):
    apply_parser = subparsers.add_parser(
        "apply", help="Apply updated .koreo files as YAML via kubectl."
    )
    apply_parser.add_argument("source_dir", help="Directory containing .koreo files.")
    apply_parser.add_argument(
        "--namespace", "-n", default="default", help="Kubernetes namespace."
    )
    apply_parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force apply all files regardless of last modified.",
    )
    apply_parser.set_defaults(
        func=lambda args: apply_command(args.source_dir, args.namespace, args.force)
    )
