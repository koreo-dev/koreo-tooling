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
            try:
                last_run = int(last_modified_file.read_text().strip())
            except ValueError:
                last_run = 0
        else:
            last_run = 0

        yaml_files = []
        should_apply = force  # Default to apply if force is set

        for ext in [".k", ".koreo"]:
            for file in dir_path.glob(f"*{ext}"):
                try:
                    file_mod_time = int(file.stat().st_mtime)
                except OSError:
                    continue

                if not force and file_mod_time <= last_run:
                    continue

                yaml_file = file.with_suffix(".yaml")
                yaml_file.write_text(file.read_text())
                print(f"Converted {file} to {yaml_file}")
                yaml_files.append(yaml_file)
                should_apply = True

        # If there are .k.yaml or .k.yml files in the directory, we assume they should be applied as-is
        if any(dir_path.glob("*.k.yaml")) or any(dir_path.glob("*.k.yml")):
            should_apply = True

        if should_apply:
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
            if yaml_files:
                print(f"Cleaned up generated YAML files in {dir_path}.")

        # Update timestamp
        with open(last_modified_file, "w") as f:
            f.write(str(int(time.time())))
        print(f"Updated last modified time for {dir_path}.")

    print("All files processed and applied successfully.")


def register_apply_subcommand(subparsers):
    apply_parser = subparsers.add_parser(
        "apply", help="Apply updated .koreo/.k files as YAML via kubectl."
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
