import os
import subprocess
import time
from pathlib import Path

import yaml
from lsprotocol import types

from koreo_tooling.error_handling import ErrorFormatter
from koreo_tooling.k8s_validation import (
    is_k8s_validation_enabled,
    set_k8s_validation_enabled,
    validate_resource_function,
)


def _validate_yaml_files(
    yaml_files: list[Path], skip_k8s: bool = False
) -> bool:
    """Validate YAML files for ResourceFunctions before applying.
    
    Returns True if validation passes, False if there are errors.
    """
    if skip_k8s or not is_k8s_validation_enabled():
        return True
        
    validation_errors = []
    
    for yaml_file in yaml_files:
        try:
            with open(yaml_file) as f:
                documents = list(yaml.safe_load_all(f))
                
            for doc in documents:
                if not doc or doc.get("kind") != "ResourceFunction":
                    continue
                    
                spec = doc.get("spec", {})
                errors = validate_resource_function(spec)
                
                for error in errors:
                    validation_errors.append({
                        'file': yaml_file,
                        'error': error
                    })
                    
        except Exception as e:
            print(f"Warning: Could not validate {yaml_file}: {e}")
            continue
    
    if validation_errors:
        print("\n🚫 K8s Validation Failed:")
        print("=" * 50)
        
        for item in validation_errors:
            file_path = item['file']
            error = item['error']
            severity = (
                "ERROR" 
                if error.severity == types.DiagnosticSeverity.Error 
                else "WARNING"
            )
            print(f"{severity}: {file_path.name}")
            print(f"  {error.message}")
            if error.path:
                print(f"  Path: {error.path}")
            print()
            
        error_count = sum(
            1 for item in validation_errors 
            if item['error'].severity == types.DiagnosticSeverity.Error
        )
        
        if error_count > 0:
            print(
                f"Found {error_count} validation error(s). "
                "Use --force-invalid to apply anyway."
            )
            return False
        else:
            print("Only warnings found. Proceeding with apply.")
            
    return True


def apply_command(
    source_dir: str, 
    namespace: str, 
    force: bool, 
    skip_k8s: bool = False, 
    force_invalid: bool = False
):
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

        # If there are .k.yaml or .k.yml files in the directory,
        # we assume they should be applied as-is
        if any(dir_path.glob("*.k.yaml")) or any(dir_path.glob("*.k.yml")):
            should_apply = True

        if should_apply:
            # Pre-flight K8s validation
            all_yaml_files = list(dir_path.glob("*.yaml")) + yaml_files
            if not _validate_yaml_files(all_yaml_files, skip_k8s):
                if not force_invalid:
                    print(f"Skipping {dir_path} due to validation errors.")
                    continue
                else:
                    print(
                        f"Applying {dir_path} despite validation errors "
                        "(--force-invalid used)."
                    )
            
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
    apply_parser.add_argument(
        "source_dir", help="Directory containing .koreo files."
    )
    apply_parser.add_argument(
        "--namespace", "-n", default="default", help="Kubernetes namespace."
    )
    apply_parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force apply all files regardless of last modified.",
    )
    apply_parser.add_argument(
        "--skip-k8s",
        action="store_true",
        help="Skip K8s CRD validation before applying.",
    )
    apply_parser.add_argument(
        "--force-invalid",
        action="store_true",
        help="Apply files even if K8s validation fails.",
    )
    apply_parser.set_defaults(
        func=lambda args: apply_command(
            args.source_dir, 
            args.namespace, 
            args.force,
            args.skip_k8s,
            args.force_invalid
        )
    )
