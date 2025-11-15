#!/usr/bin/env python3
"""Fix n8n workflow JSON files by adding missing 'name' field."""

import json
import logging
from pathlib import Path
from typing import Dict, Any, List
import sys

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def fix_workflow_file(file_path: Path, dry_run: bool = False) -> tuple[bool, str]:
    """Fix a single workflow file by adding missing name field.

    Args:
        file_path: Path to the workflow JSON file
        dry_run: If True, don't write changes, just report what would be done

    Returns:
        Tuple of (success, message)
    """
    try:
        # Read JSON file
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Try to parse as JSON
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            # Check if there's extra data at the end (common issue)
            # Try to find where the valid JSON ends
            brace_count = 0
            json_end = -1
            in_string = False
            escape_next = False

            for i, char in enumerate(content):
                if escape_next:
                    escape_next = False
                    continue
                if char == '\\':
                    escape_next = True
                    continue
                if char == '"' and not escape_next:
                    in_string = not in_string
                if not in_string:
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            json_end = i + 1
                            break

            if json_end > 0:
                try:
                    truncated = content[:json_end]
                    data = json.loads(truncated)
                    # Update content to be the truncated version (will be saved later)
                    content = truncated
                    logger.warning(f"{file_path.name}: Truncated extra data after character {json_end}")
                except Exception:
                    return False, f"Invalid JSON: {e}"
            else:
                return False, f"Invalid JSON: {e}"

        # Check if nodes field exists (required by n8n)
        if 'nodes' not in data:
            return False, "Missing nodes field - not a valid workflow"

        # Check if name field exists
        needs_name_fix = 'name' not in data or not data['name']
        needs_truncate = len(content) != len(json.dumps(data, ensure_ascii=False))

        if not needs_name_fix and not needs_truncate:
            return False, "Already valid"

        # Use filename as workflow name
        workflow_name = file_path.stem

        # Create new data dict with name as first field
        if needs_name_fix:
            fixed_data = {'name': workflow_name}
            fixed_data.update(data)
        else:
            fixed_data = data

        if not dry_run:
            # Write back with proper formatting
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(fixed_data, f, indent=2, ensure_ascii=False)

            fixes = []
            if needs_name_fix:
                fixes.append(f"Added name: '{workflow_name}'")
            if needs_truncate:
                fixes.append("Removed extra data")
            return True, "; ".join(fixes)
        else:
            fixes = []
            if needs_name_fix:
                fixes.append(f"Would add name: '{workflow_name}'")
            if needs_truncate:
                fixes.append("Would remove extra data")
            return True, "; ".join(fixes)

    except Exception as e:
        return False, f"Error: {e}"


def fix_workflows_in_directory(
    directory: Path,
    recursive: bool = True,
    dry_run: bool = False
) -> Dict[str, List[str]]:
    """Fix all workflow files in a directory.

    Args:
        directory: Path to directory containing workflow files
        recursive: Whether to scan subdirectories
        dry_run: If True, don't write changes, just report

    Returns:
        Dictionary with lists of fixed, skipped, and failed files
    """
    results = {
        'fixed': [],
        'skipped': [],
        'failed': []
    }

    # Find all JSON files
    pattern = "**/*.json" if recursive else "*.json"
    json_files = sorted(directory.glob(pattern))

    logger.info(f"Found {len(json_files)} JSON files in {directory}")

    for json_file in json_files:
        success, message = fix_workflow_file(json_file, dry_run)

        if success:
            results['fixed'].append(str(json_file.name))
            logger.info(f"✓ {json_file.name}: {message}")
        elif "Already valid" in message:
            results['skipped'].append(str(json_file.name))
            logger.debug(f"- {json_file.name}: {message}")
        else:
            results['failed'].append(str(json_file.name))
            logger.warning(f"✗ {json_file.name}: {message}")

    return results


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Fix n8n workflow JSON files by adding missing name field'
    )
    parser.add_argument(
        'directory',
        type=str,
        help='Directory containing workflow JSON files'
    )
    parser.add_argument(
        '--no-recursive',
        action='store_true',
        help='Do not scan subdirectories'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )

    args = parser.parse_args()

    directory = Path(args.directory)
    if not directory.exists():
        logger.error(f"Directory not found: {directory}")
        sys.exit(1)

    if args.dry_run:
        logger.info("DRY RUN MODE - No changes will be made")

    results = fix_workflows_in_directory(
        directory,
        recursive=not args.no_recursive,
        dry_run=args.dry_run
    )

    # Print summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Fixed:   {len(results['fixed'])} files")
    print(f"Skipped: {len(results['skipped'])} files (already valid)")
    print(f"Failed:  {len(results['failed'])} files")

    if results['failed']:
        print("\nFailed files:")
        for filename in results['failed']:
            print(f"  - {filename}")

    if args.dry_run and results['fixed']:
        print("\nRe-run without --dry-run to apply changes")


if __name__ == '__main__':
    main()
