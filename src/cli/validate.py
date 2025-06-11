"""CLI command for validating Koreo resources"""

import argparse
import pathlib
import sys

from koreo_tooling.validation import ValidationError, validate_koreo_yaml, format_validation_errors


def validate_file(file_path: pathlib.Path) -> list[ValidationError]:
    """Validate a single YAML file"""
    try:
        content = file_path.read_text()
        return validate_koreo_yaml(content)
    except FileNotFoundError:
        return [ValidationError(
            message=f"File not found: {file_path}",
            source="koreo-validate"
        )]
    except Exception as e:
        return [ValidationError(
            message=f"Error reading file {file_path}: {e}",
            source="koreo-validate"
        )]


def validate_directory(dir_path: pathlib.Path) -> list[tuple[pathlib.Path, list[ValidationError]]]:
    """Validate all YAML files in a directory"""
    results = []
    
    # Look for .yaml, .yml, and .k.yaml files
    patterns = ["**/*.yaml", "**/*.yml", "**/*.k.yaml", "**/*.k.yml"]
    
    yaml_files = set()
    for pattern in patterns:
        yaml_files.update(dir_path.glob(pattern))
    
    for i, file_path in enumerate(sorted(yaml_files)):
        if file_path.is_file():
            if len(yaml_files) > 20:  # Show progress for large directories
                print(f"\rValidating files... {i+1}/{len(yaml_files)}", end="", flush=True)
            errors = validate_file(file_path)
            if errors:  # Only include files with errors
                results.append((file_path, errors))
    
    if len(yaml_files) > 20:
        print()  # New line after progress indicator
    
    return results




def register_validate_subcommand(subparsers):
    """Register the validate subcommand"""
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate Koreo YAML resources against their schemas",
        description="Validate Koreo YAML resources against their schemas",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  koreo validate workflow.k.yaml           # Validate single file
  koreo validate ./workflows/              # Validate directory
  koreo validate . --quiet                 # Only show errors
  koreo validate . --summary               # Show summary only
        """
    )
    
    validate_parser.add_argument(
        "path",
        type=pathlib.Path,
        help="Path to YAML file or directory to validate"
    )
    
    validate_parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Only output errors and warnings, suppress informational messages"
    )
    
    validate_parser.add_argument(
        "--summary", "-s", 
        action="store_true",
        help="Show only a summary of validation results"
    )
    
    validate_parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="Exit with error code if warnings are found"
    )
    
    
    validate_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging for debugging"
    )
    
    validate_parser.set_defaults(func=validate_command)


def validate_command(args):
    # Configure logging level
    if args.verbose:
        import logging
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    
    if not args.path.exists():
        print(f"Error: Path '{args.path}' does not exist", file=sys.stderr)
        sys.exit(1)
    
    # Validate files
    if args.path.is_file():
        errors = validate_file(args.path)
        results = [(args.path, errors)] if errors else []
    else:
        results = validate_directory(args.path)
    
    # Count errors and warnings
    total_files_checked = 1 if args.path.is_file() else len(list(args.path.rglob("*.yaml"))) + len(list(args.path.rglob("*.yml")))
    files_with_errors = len(results)
    total_errors = 0
    total_warnings = 0
    
    for _, errors in results:
        for error in errors:
            if error.severity.value == 1:  # Error
                total_errors += 1
            elif error.severity.value == 2:  # Warning
                total_warnings += 1
    
    # Output results
    if not args.summary:
        if results:
            for file_path, errors in results:
                print(format_validation_errors(file_path, errors))
        elif not args.quiet:
            print(f"All files valid! Checked {total_files_checked} files.")
    
    # Output summary
    if args.summary or (results and not args.quiet):
        print("\nValidation Summary:")
        print(f"   Files checked: {total_files_checked}")
        print(f"   Files with issues: {files_with_errors}")
        print(f"   Errors: {total_errors}")
        print(f"   Warnings: {total_warnings}")
    
    # Determine exit code
    exit_code = 0
    if total_errors > 0:
        exit_code = 1
    elif args.fail_on_warning and total_warnings > 0:
        exit_code = 1
    
    if exit_code != 0 and not args.quiet:
        print(f"\nValidation failed with exit code {exit_code}")
    
    sys.exit(exit_code)