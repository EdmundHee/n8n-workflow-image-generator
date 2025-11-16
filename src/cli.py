"""CLI interface for n8n-snap workflow snapshot generator."""

import asyncio
import json
import logging
import multiprocessing
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from functools import partial

import click
import psutil
from rich.console import Console, Group
from rich.table import Table
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
    TimeRemainingColumn,
)
from rich.panel import Panel
from rich.logging import RichHandler
from rich.live import Live

from src.scanner import WorkflowScanner
from src.renderer import WorkflowRenderer
from src.server import create_server
from src.worker import render_workflow_worker, WorkflowTask, WorkflowResult

# Initialize Rich console and logger
console = Console()
logger = logging.getLogger(__name__)


def load_existing_state(input_folder: Path) -> dict:
    """Load existing state from n8n-snap-job.json if it exists.

    Args:
        input_folder: Path to the input folder

    Returns:
        Dictionary containing existing state or empty dict if no state exists
    """
    state_file = input_folder / "n8n-snap-job.json"
    if not state_file.exists():
        return {}

    try:
        with open(state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
            logger.info(f"Loaded existing state from {state_file}")
            return state
    except Exception as e:
        logger.warning(f"Failed to load existing state from {state_file}: {e}")
        return {}


def setup_logging(verbose: bool = False) -> None:
    """Configure logging with Rich handler.

    Args:
        verbose: Enable debug level logging
    """
    level = logging.DEBUG if verbose else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
    )

    # Suppress verbose loggers
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def run_server_thread(port: int = 5000) -> threading.Thread:
    """Run Flask server in a background thread.

    Args:
        port: Port number for the server

    Returns:
        Thread object running the server
    """
    server = create_server(port=port, debug=False)

    def run_server():
        server.run(host="127.0.0.1")

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()

    # Wait for server to start
    time.sleep(2)

    return thread


@click.group()
@click.version_option(version="1.0.0", prog_name="n8n-snap")
def cli():
    """n8n-snap - Generate high-quality PNG snapshots from n8n workflow JSON files.

    This tool uses Playwright to render n8n workflows and capture them as PNG images.
    """
    pass


@cli.command()
@click.argument("input_folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--recursive/--no-recursive", default=True, help="Scan subdirectories recursively")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def scan(input_folder: Path, recursive: bool, verbose: bool):
    """Scan and validate workflow JSON files.

    INPUT_FOLDER: Directory containing workflow JSON files
    """
    setup_logging(verbose)

    console.print(Panel.fit(
        f"[bold cyan]Scanning workflows in:[/bold cyan] {input_folder}",
        border_style="cyan"
    ))

    try:
        # Scan workflows
        with console.status("[bold green]Scanning files..."):
            scanner = WorkflowScanner(input_folder, recursive=recursive)
            workflows = scanner.scan()

        if not workflows:
            console.print("[yellow]No JSON files found in the specified folder.[/yellow]")
            return

        # Get summary
        summary = scanner.get_summary()

        # Create results table
        table = Table(title="Scan Results", show_header=True, header_style="bold magenta")
        table.add_column("Workflow", style="cyan", no_wrap=True)
        table.add_column("Status", justify="center")
        table.add_column("Nodes", justify="right")
        table.add_column("File", style="dim")

        for workflow in workflows:
            status = "[green]Valid[/green]" if workflow.valid else "[red]Invalid[/red]"
            nodes = str(workflow.metadata.get("node_count", "-")) if workflow.valid else "-"

            table.add_row(
                workflow.name[:50],
                status,
                nodes,
                workflow.path.name,
            )

        console.print(table)

        # Print summary
        console.print("\n[bold]Summary:[/bold]")
        console.print(f"  Total files: {summary['total_files']}")
        console.print(f"  [green]Valid workflows: {summary['valid_workflows']}[/green]")
        console.print(f"  [red]Invalid workflows: {summary['invalid_workflows']}[/red]")
        console.print(f"  Total nodes: {summary['total_nodes']}")

        # Show errors for invalid workflows
        invalid = scanner.get_invalid_workflows()
        if invalid:
            console.print("\n[bold red]Validation Errors:[/bold red]")
            for workflow in invalid:
                console.print(f"  [red]✗[/red] {workflow.path.name}: {workflow.error}")

        # Exit with error code if any invalid workflows
        if summary['invalid_workflows'] > 0:
            sys.exit(1)

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        if verbose:
            console.print_exception()
        sys.exit(1)


@cli.command()
@click.argument("input_folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("output_folder", type=click.Path(file_okay=False, path_type=Path), required=False)
@click.option("--width", default=1920, type=int, help="Viewport width (default: 1920)")
@click.option("--height", default=1080, type=int, help="Viewport height (default: 1080)")
@click.option("--square", is_flag=True, help="Use square aspect ratio (2560x2560)")
@click.option("--dark-mode", is_flag=True, help="Enable dark mode background")
@click.option("--in-place", is_flag=True, help="Save images in same folder as source JSON files")
@click.option("--force", is_flag=True, help="Force re-render of all workflows, ignoring previous state")
@click.option("--timeout", default=120, type=int, help="Render timeout in seconds (default: 120)")
@click.option("--wait-time", default=60, type=int, help="Wait time for iframe rendering in seconds (default: 60)")
@click.option("--port", default=5000, type=int, help="Flask server port (default: 5000)")
@click.option("--workers", default=1, type=int, help="Number of parallel workers (default: 1, max: cpu_count)")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def generate(
    input_folder: Path,
    output_folder: Optional[Path],
    width: int,
    height: int,
    square: bool,
    dark_mode: bool,
    in_place: bool,
    force: bool,
    timeout: int,
    wait_time: int,
    port: int,
    workers: int,
    verbose: bool,
):
    """Generate PNG snapshots from workflow JSON files.

    INPUT_FOLDER: Directory containing workflow JSON files

    OUTPUT_FOLDER: Directory to save PNG snapshots (optional if --in-place is used)
    """
    setup_logging(verbose)

    # Validate output_folder and in_place options
    if in_place and output_folder:
        console.print("[yellow]Warning: --in-place flag is set. The output_folder argument will be ignored.[/yellow]")
        output_folder = None

    if not in_place and not output_folder:
        console.print("[red]Error: Either provide OUTPUT_FOLDER or use --in-place flag[/red]")
        sys.exit(1)

    # Apply square dimensions if requested
    if square:
        width = height = 2560

    # Validate and configure workers
    cpu_count = os.cpu_count() or 1

    # Validate worker count
    if workers < 1:
        console.print("[red]Error: --workers must be at least 1[/red]")
        sys.exit(1)

    if workers > cpu_count:
        console.print(f"[yellow]Warning: Requested {workers} workers exceeds CPU count ({cpu_count}). Using {cpu_count} workers.[/yellow]")
        workers = cpu_count

    # Memory check
    available_memory_gb = psutil.virtual_memory().available / (1024**3)
    estimated_memory_per_worker_gb = 0.4  # ~400MB per browser instance
    estimated_total_memory_gb = workers * estimated_memory_per_worker_gb

    if estimated_total_memory_gb > available_memory_gb * 0.8:  # Warning if using >80% available memory
        console.print(
            f"[yellow]Warning: {workers} workers may use ~{estimated_total_memory_gb:.1f}GB memory. "
            f"Available: {available_memory_gb:.1f}GB[/yellow]"
        )

    # Build viewport description
    viewport_desc = f"Viewport: {width}x{height} @ 2x scale"
    if dark_mode:
        viewport_desc += " (dark mode)"

    # Build worker description
    worker_mode = "single worker" if workers == 1 else f"{workers} parallel workers"

    # Build output description
    if in_place:
        output_desc = f"Output: In-place (same folder as JSON files)\nStatus report: {input_folder}/n8n-snap-job.json"
    else:
        output_desc = f"Output: {output_folder}"

    console.print(Panel.fit(
        f"[bold cyan]n8n Workflow Snapshot Generator[/bold cyan]\n"
        f"Input: {input_folder}\n"
        f"{output_desc}\n"
        f"{viewport_desc}\n"
        f"Mode: {worker_mode}",
        border_style="cyan"
    ))

    try:
        # Scan workflows
        with console.status("[bold green]Scanning workflows..."):
            scanner = WorkflowScanner(input_folder)
            workflows = scanner.scan()
            valid_workflows = scanner.get_valid_workflows()

        if not valid_workflows:
            console.print("[yellow]No valid workflows found.[/yellow]")
            return

        console.print(f"Found {len(valid_workflows)} valid workflows\n")

        # Start Flask server
        console.print("[bold green]Starting Flask server...[/bold green]")
        server_thread = run_server_thread(port=port)
        console.print(f"[green]✓[/green] Server running on http://127.0.0.1:{port}\n")

        # Choose rendering mode based on worker count
        if workers == 1:
            # Single worker - use original async rendering
            asyncio.run(
                render_workflows_async(
                    valid_workflows,
                    output_folder,
                    width,
                    height,
                    timeout,
                    wait_time,
                    port,
                    dark_mode,
                    in_place,
                    input_folder,
                    force,
                )
            )
        else:
            # Multiple workers - use parallel rendering
            render_workflows_parallel(
                valid_workflows,
                output_folder,
                width,
                height,
                timeout,
                wait_time,
                port,
                dark_mode,
                workers,
                in_place,
                input_folder,
                force,
            )

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        if verbose:
            console.print_exception()
        sys.exit(1)


async def render_workflows_async(
    workflows: list,
    output_folder: Optional[Path],
    width: int,
    height: int,
    timeout: int,
    wait_time: int,
    port: int,
    dark_mode: bool = False,
    in_place: bool = False,
    input_folder: Optional[Path] = None,
    force: bool = False,
):
    """Async function to render workflows with progress tracking.

    Args:
        workflows: List of valid WorkflowFile objects
        output_folder: Output directory path (None if in_place mode)
        width: Viewport width
        height: Viewport height
        timeout: Timeout in seconds
        wait_time: Wait time for iframe in seconds
        port: Server port number
        dark_mode: Enable dark mode background
        in_place: Save images in same folder as source JSON files
        input_folder: Input folder path (required for in_place mode)
        force: Force re-render of all workflows, ignoring previous state
    """
    # Load existing state if in_place mode and not forcing
    existing_state = {}
    previously_successful = {}
    if in_place and input_folder and not force:
        existing_state = load_existing_state(input_folder)
        # Build a map of successfully processed workflows by source_path
        if "workflows" in existing_state:
            for workflow_entry in existing_state["workflows"]:
                if workflow_entry.get("status") == "success":
                    previously_successful[workflow_entry["source_path"]] = workflow_entry

    # Filter out already processed workflows (unless force is enabled)
    original_count = len(workflows)
    workflows_to_process = []
    for workflow in workflows:
        source_path = str(workflow.path.relative_to(input_folder)) if in_place and input_folder else workflow.path.name
        if not force and source_path in previously_successful:
            logger.info(f"Skipping already processed workflow: {source_path}")
        else:
            workflows_to_process.append(workflow)

    if workflows_to_process:
        skipped_count = original_count - len(workflows_to_process)
        if skipped_count > 0:
            console.print(f"[yellow]Skipping {skipped_count} already processed workflow(s)[/yellow]")
        console.print(f"Processing {len(workflows_to_process)} workflow(s)\n")
    else:
        console.print("[green]All workflows have already been processed successfully![/green]")
        return

    # Create output folder only if not in in_place mode
    if not in_place and output_folder:
        output_folder.mkdir(parents=True, exist_ok=True)

    # Initialize renderer
    renderer = WorkflowRenderer(
        server_url=f"http://127.0.0.1:{port}",
        width=width,
        height=height,
        timeout=timeout * 1000,  # Convert to milliseconds
        dark_mode=dark_mode,
    )

    await renderer.start()

    try:
        # Setup progress bar
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
            auto_refresh=False,
        )

        task = progress.add_task(
            "[cyan]Rendering workflows...",
            total=len(workflows_to_process)
        )

        # Initialize results and status tracking
        start_time = datetime.now(timezone.utc)
        results = {
            "successful": 0,
            "failed": 0,
            "errors": [],
            "replaced_existing": 0,
        }
        workflow_statuses = []
        current_workflow = {"name": "", "status": "", "start_time": None}

        # Initialize CPU monitoring (first call returns 0, subsequent calls return actual values)
        process = psutil.Process()
        process.cpu_percent()  # Initialize CPU measurement

        # Create live display components
        def make_status_panel():
            """Create current status panel."""
            # Current workflow status
            if current_workflow["name"]:
                workflow_name = current_workflow["name"]
                if len(workflow_name) > 60:
                    workflow_name = workflow_name[:57] + "..."

                status_emoji = {
                    "rendering": "⏳",
                    "success": "✓",
                    "failed": "✗",
                }.get(current_workflow["status"], "")

                status_color = {
                    "rendering": "yellow",
                    "success": "green",
                    "failed": "red",
                }.get(current_workflow["status"], "white")

                # Calculate elapsed time for current workflow
                elapsed = ""
                if current_workflow["start_time"] and current_workflow["status"] == "rendering":
                    elapsed_seconds = (datetime.now(timezone.utc) - current_workflow["start_time"]).total_seconds()
                    elapsed = f" [dim]({elapsed_seconds:.1f}s)[/dim]"

                status_text = f"  [{status_color}]{status_emoji}[/{status_color}] {workflow_name}{elapsed}"
            else:
                status_text = "  [dim]Initializing...[/dim]"

            # Statistics
            completed = results["successful"] + results["failed"]
            remaining = len(workflows_to_process) - completed

            # Calculate ETA
            eta_text = ""
            if completed > 0 and remaining > 0:
                elapsed_total = (datetime.now(timezone.utc) - start_time).total_seconds()
                avg_time_per_workflow = elapsed_total / completed
                eta_seconds = avg_time_per_workflow * remaining
                eta_minutes = int(eta_seconds // 60)
                eta_secs = int(eta_seconds % 60)
                if eta_minutes > 0:
                    eta_text = f"  [dim]ETA: {eta_minutes}m {eta_secs}s[/dim]"
                else:
                    eta_text = f"  [dim]ETA: {eta_secs}s[/dim]"

            # Resource usage (use the initialized process instance)
            memory_mb = process.memory_info().rss / (1024 * 1024)
            cpu_percent = process.cpu_percent()

            stats = (
                f"  [green]✓ Success:[/green] {results['successful']}  "
                f"[red]✗ Failed:[/red] {results['failed']}  "
                f"[cyan]Remaining:[/cyan] {remaining}\n"
                f"  [dim]Memory: {memory_mb:.1f} MB  CPU: {cpu_percent:.1f}%[/dim]{eta_text}"
            )

            return Panel(
                f"{status_text}\n\n{stats}",
                title="Current Status",
                border_style="cyan",
            )

        def make_display():
            return Group(
                make_status_panel(),
                progress
            )

        # Temporarily suppress console logging during Live display
        # Save original log levels
        saved_levels = {}
        loggers_to_suppress = ['src.server', 'src.renderer', 'src.worker', '']  # '' is root logger
        for logger_name in loggers_to_suppress:
            lgr = logging.getLogger(logger_name)
            saved_levels[logger_name] = lgr.level
            lgr.setLevel(logging.CRITICAL)  # Only show critical errors

        # Use Live display for continuous updates
        with Live(make_display(), console=console, refresh_per_second=4) as live:
            for i, workflow in enumerate(workflows_to_process, 1):
                workflow_start_time = datetime.now(timezone.utc)
                status_entry = {
                    "source_path": str(workflow.path.relative_to(input_folder)) if in_place else workflow.path.name,
                    "output_path": None,
                    "status": "failed",
                    "error": None,
                    "timestamp": workflow_start_time.isoformat(),
                    "replaced_existing": False,
                }

                try:
                    # Update current workflow status
                    current_workflow["name"] = workflow.name
                    current_workflow["status"] = "rendering"
                    current_workflow["start_time"] = datetime.now(timezone.utc)

                    # Update progress description
                    progress.update(
                        task,
                        description=f"[cyan]Rendering workflows... ({i}/{len(workflows_to_process)})",
                    )

                    # Refresh display
                    live.update(make_display())

                    # Generate output path based on mode
                    output_filename = f"{workflow.safe_filename}.png"
                    if in_place:
                        # Save in same folder as source JSON
                        output_path = workflow.path.parent / output_filename
                        # Track relative path for status report
                        status_entry["output_path"] = str(output_path.relative_to(input_folder))
                    else:
                        # Save in output folder
                        output_path = output_folder / output_filename
                        status_entry["output_path"] = output_filename

                    # Check if file already exists
                    if output_path.exists():
                        results["replaced_existing"] += 1
                        status_entry["replaced_existing"] = True
                        logger.debug(f"Replacing existing image: {output_path}")

                    # Render workflow
                    await renderer.render_workflow(
                        workflow.workflow_data,
                        output_path,
                        wait_time=wait_time * 1000,  # Convert to milliseconds
                    )

                    results["successful"] += 1
                    status_entry["status"] = "success"
                    current_workflow["status"] = "success"

                except Exception as e:
                    results["failed"] += 1
                    current_workflow["status"] = "failed"

                    # Capture detailed error information
                    import traceback
                    error_traceback = traceback.format_exc()

                    error_details = {
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                        "node_count": len(workflow.workflow_data.get("nodes", [])),
                        "has_connections": bool(workflow.workflow_data.get("connections")),
                    }

                    status_entry["error"] = str(e)
                    status_entry["error_details"] = error_details

                    results["errors"].append({
                        "workflow": workflow.name,
                        "error": str(e),
                        "error_type": type(e).__name__,
                        "node_count": error_details["node_count"],
                        "traceback": error_traceback if logger.level <= logging.DEBUG else None,
                    })

                    # Log detailed error
                    logger.error(f"Failed to render {workflow.name}:")
                    logger.error(f"  Error type: {type(e).__name__}")
                    logger.error(f"  Message: {str(e)}")
                    logger.error(f"  Nodes: {error_details['node_count']}")
                    if logger.level <= logging.DEBUG:
                        logger.debug(f"  Traceback:\n{error_traceback}")

                finally:
                    # Add status entry to list
                    workflow_statuses.append(status_entry)
                    # Update progress
                    progress.update(task, advance=1)
                    # Refresh display
                    live.update(make_display())

        # Restore original logging levels
        for logger_name, level in saved_levels.items():
            logging.getLogger(logger_name).setLevel(level)

        # Generate n8n-snap-job.json if in_place mode
        end_time = datetime.now(timezone.utc)
        if in_place and input_folder:
            # Merge old successful workflows with new results
            all_workflows = list(previously_successful.values()) + workflow_statuses

            # Calculate totals
            total_successful = len([w for w in all_workflows if w.get("status") == "success"])
            total_failed = len([w for w in all_workflows if w.get("status") == "failed"])
            total_replaced = results["replaced_existing"]

            status_report = {
                "processing_info": {
                    "start_time": existing_state.get("processing_info", {}).get("start_time", start_time.isoformat()),
                    "end_time": end_time.isoformat(),
                    "input_folder": str(input_folder.absolute()),
                    "mode": "in-place",
                    "settings": {
                        "width": width,
                        "height": height,
                        "dark_mode": dark_mode,
                    }
                },
                "summary": {
                    "total_workflows": len(workflows),
                    "successful": total_successful,
                    "failed": total_failed,
                    "replaced_existing": total_replaced,
                },
                "workflows": all_workflows,
            }

            # Write status report to input folder
            report_path = input_folder / "n8n-snap-job.json"
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(status_report, f, indent=2)
            logger.info(f"Status report written to: {report_path}")

        # Calculate total elapsed time
        total_elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        elapsed_minutes = int(total_elapsed // 60)
        elapsed_seconds = int(total_elapsed % 60)

        # Create summary panel
        summary_lines = []
        summary_lines.append(f"[green]✓ Success:[/green] {results['successful']}")
        summary_lines.append(f"[red]✗ Failed:[/red] {results['failed']}")

        if results["replaced_existing"] > 0:
            summary_lines.append(f"[yellow]⟳ Replaced:[/yellow] {results['replaced_existing']}")

        if elapsed_minutes > 0:
            summary_lines.append(f"[cyan]⏱ Time:[/cyan] {elapsed_minutes}m {elapsed_seconds}s")
        else:
            summary_lines.append(f"[cyan]⏱ Time:[/cyan] {elapsed_seconds}s")

        if in_place:
            summary_lines.append(f"[dim]Output:[/dim] Images saved in source folders")
            summary_lines.append(f"[dim]Report:[/dim] {input_folder}/n8n-snap-job.json")
        else:
            summary_lines.append(f"[dim]Output:[/dim] {output_folder}")

        console.print("\n")
        console.print(Panel(
            "\n".join(summary_lines),
            title="[bold]Summary[/bold]",
            border_style="green" if results["failed"] == 0 else "yellow",
        ))

        if results["failed"] > 0:
            console.print("\n[bold red]Errors:[/bold red]")
            for error in results["errors"]:
                console.print(f"  [red]✗[/red] {error['workflow']}: {error['error']}")

    finally:
        await renderer.close()


def render_workflows_parallel(
    workflows: list,
    output_folder: Optional[Path],
    width: int,
    height: int,
    timeout: int,
    wait_time: int,
    port: int,
    dark_mode: bool,
    workers: int,
    in_place: bool = False,
    input_folder: Optional[Path] = None,
    force: bool = False,
):
    """Render workflows using parallel workers with resource monitoring.

    Args:
        workflows: List of valid WorkflowFile objects
        output_folder: Output directory path (None if in_place mode)
        width: Viewport width
        height: Viewport height
        timeout: Timeout in seconds
        wait_time: Wait time for iframe in seconds
        port: Server port number
        dark_mode: Enable dark mode background
        workers: Number of parallel workers
        in_place: Save images in same folder as source JSON files
        input_folder: Input folder path (required for in_place mode)
        force: Force re-render of all workflows, ignoring previous state
    """
    # Load existing state if in_place mode and not forcing
    existing_state = {}
    previously_successful = {}
    if in_place and input_folder and not force:
        existing_state = load_existing_state(input_folder)
        # Build a map of successfully processed workflows by source_path
        if "workflows" in existing_state:
            for workflow_entry in existing_state["workflows"]:
                if workflow_entry.get("status") == "success":
                    previously_successful[workflow_entry["source_path"]] = workflow_entry

    # Filter out already processed workflows (unless force is enabled)
    original_count = len(workflows)
    workflows_to_process = []
    for workflow in workflows:
        source_path = str(workflow.path.relative_to(input_folder)) if in_place and input_folder else workflow.path.name
        if not force and source_path in previously_successful:
            logger.info(f"Skipping already processed workflow: {source_path}")
        else:
            workflows_to_process.append(workflow)

    if workflows_to_process:
        skipped_count = original_count - len(workflows_to_process)
        if skipped_count > 0:
            console.print(f"[yellow]Skipping {skipped_count} already processed workflow(s)[/yellow]")
        console.print(f"Processing {len(workflows_to_process)} workflow(s)\n")
    else:
        console.print("[green]All workflows have already been processed successfully![/green]")
        return

    # Create output folder only if not in in_place mode
    if not in_place and output_folder:
        output_folder.mkdir(parents=True, exist_ok=True)

    # Create tasks for all workflows
    tasks = []
    workflow_paths = {}  # Track workflow paths for status reporting
    for workflow in workflows_to_process:
        output_filename = f"{workflow.safe_filename}.png"

        # Generate output path based on mode
        if in_place:
            # Save in same folder as source JSON
            output_path = workflow.path.parent / output_filename
            # Create display name with folder path
            relative_path = workflow.path.relative_to(input_folder)
            display_name = f"{relative_path.parent.name}/{workflow.name}" if relative_path.parent.name else workflow.name
        else:
            # Save in output folder
            output_path = output_folder / output_filename
            display_name = workflow.name

        task = WorkflowTask(
            workflow_data=workflow.workflow_data,
            workflow_name=workflow.name,
            safe_filename=workflow.safe_filename,
            output_path=output_path,
            display_name=display_name,
        )
        tasks.append(task)

        # Store workflow path for status tracking
        workflow_paths[workflow.name] = {
            "source_path": workflow.path,
            "output_path": output_path,
        }

    # Prepare worker arguments
    server_url = f"http://127.0.0.1:{port}"

    # Create partial function with fixed parameters
    worker_func = partial(
        render_workflow_worker,
        server_url=server_url,
        width=width,
        height=height,
        timeout=timeout,
        wait_time=wait_time,
        dark_mode=dark_mode,
    )

    # Initialize results and status tracking
    start_time = datetime.now(timezone.utc)
    results = {
        "successful": 0,
        "failed": 0,
        "errors": [],
        "replaced_existing": 0,
    }
    workflow_statuses = []

    # Initialize CPU monitoring (first call returns 0, subsequent calls return actual values)
    process = psutil.Process()
    process.cpu_percent()  # Initialize CPU measurement

    # Track worker statuses
    worker_status = {i: {"workflow": None, "status": "idle", "start_time": None} for i in range(workers)}
    worker_status_lock = threading.Lock()

    try:
        # Setup progress bar
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
            auto_refresh=False,  # Disable auto-refresh since Live will handle it
        )

        task = progress.add_task(
            "[cyan]Rendering workflows...",
            total=len(workflows_to_process)
        )

        # Create grouped display (worker status + progress + stats)
        def make_worker_status_panel():
            """Create worker status panel."""
            status_lines = []
            with worker_status_lock:
                for worker_id in range(workers):
                    worker_info = worker_status[worker_id]
                    if worker_info["status"] == "idle":
                        status_lines.append(f"  [dim]Worker {worker_id}: Idle[/dim]")
                    elif worker_info["status"] == "rendering":
                        workflow_name = worker_info["workflow"]
                        if len(workflow_name) > 40:
                            workflow_name = workflow_name[:37] + "..."

                        # Calculate elapsed time
                        elapsed = ""
                        if worker_info.get("start_time"):
                            elapsed_seconds = (datetime.now(timezone.utc) - worker_info["start_time"]).total_seconds()
                            elapsed = f" [dim]({elapsed_seconds:.1f}s)[/dim]"

                        status_lines.append(f"  [cyan]Worker {worker_id}:[/cyan] [yellow]⏳[/yellow] {workflow_name}{elapsed}")
                    elif worker_info["status"] == "completed":
                        workflow_name = worker_info["workflow"]
                        if len(workflow_name) > 40:
                            workflow_name = workflow_name[:37] + "..."
                        status_lines.append(f"  [cyan]Worker {worker_id}:[/cyan] [green]✓[/green] {workflow_name}")

            return Panel(
                "\n".join(status_lines) if status_lines else "[dim]No workers active[/dim]",
                title=f"Worker Status ({workers} workers)",
                border_style="blue",
            )

        def make_stats_panel():
            """Create statistics panel."""
            completed = results["successful"] + results["failed"]
            remaining = len(workflows_to_process) - completed

            # Calculate ETA
            eta_text = "Calculating..."
            if completed > 0 and remaining > 0:
                elapsed_total = (datetime.now(timezone.utc) - start_time).total_seconds()
                avg_time_per_workflow = elapsed_total / completed
                eta_seconds = avg_time_per_workflow * remaining
                eta_minutes = int(eta_seconds // 60)
                eta_secs = int(eta_seconds % 60)
                if eta_minutes > 0:
                    eta_text = f"{eta_minutes}m {eta_secs}s"
                else:
                    eta_text = f"{eta_secs}s"
            elif remaining == 0:
                eta_text = "Complete"

            # Resource usage (use the initialized process instance)
            memory_mb = process.memory_info().rss / (1024 * 1024)
            cpu_percent = process.cpu_percent()

            stats_text = (
                f"  [green]✓ Success:[/green] {results['successful']}  "
                f"[red]✗ Failed:[/red] {results['failed']}  "
                f"[cyan]Remaining:[/cyan] {remaining}\n"
                f"  [dim]Memory: {memory_mb:.1f} MB  CPU: {cpu_percent:.1f}%  ETA: {eta_text}[/dim]"
            )

            return Panel(
                stats_text,
                title="Statistics",
                border_style="cyan",
            )

        def make_display():
            return Group(
                make_worker_status_panel(),
                make_stats_panel(),
                progress
            )

        # Temporarily suppress console logging during Live display
        # Save original log levels
        saved_levels = {}
        loggers_to_suppress = ['src.server', 'src.renderer', 'src.worker', '']  # '' is root logger
        for logger_name in loggers_to_suppress:
            lgr = logging.getLogger(logger_name)
            saved_levels[logger_name] = lgr.level
            lgr.setLevel(logging.CRITICAL)  # Only show critical errors

        # Use Live display for continuous updates
        with Live(make_display(), console=console, refresh_per_second=4) as live:
            # Create multiprocessing pool and process workflows
            with multiprocessing.Pool(processes=workers) as pool:
                # Submit all tasks asynchronously
                pending_results = []
                task_to_worker = {}  # Map async_result to (worker_id, workflow_name)

                for i, workflow_task in enumerate(tasks):
                    worker_id = i % workers
                    async_result = pool.apply_async(
                        worker_func,
                        args=(workflow_task, worker_id)
                    )
                    pending_results.append(async_result)

                    # Track worker assignment
                    task_to_worker[id(async_result)] = (worker_id, workflow_task.workflow_name)

                    # Update worker status
                    with worker_status_lock:
                        worker_status[worker_id] = {
                            "workflow": workflow_task.display_name or workflow_task.workflow_name,
                            "status": "rendering",
                            "start_time": datetime.now(timezone.utc)
                        }

                # Trigger initial display update to show worker assignments
                live.update(make_display())

                # Collect results as they complete (check for ready results)
                while pending_results:
                    completed_this_iteration = False

                    # Find completed results
                    for async_result in pending_results[:]:  # Copy list to allow removal during iteration
                        if async_result.ready():
                            # Get the result
                            result = async_result.get()
                            pending_results.remove(async_result)
                            completed_this_iteration = True

                            # Get worker info for this task
                            worker_id, workflow_name = task_to_worker.get(id(async_result), (None, None))

                            # Prepare status entry
                            workflow_info = workflow_paths.get(result.workflow_name, {})
                            source_path = workflow_info.get("source_path", Path())
                            output_path = workflow_info.get("output_path", Path())

                            status_entry = {
                                "source_path": str(source_path.relative_to(input_folder)) if in_place and input_folder else source_path.name,
                                "output_path": str(output_path.relative_to(input_folder)) if in_place and input_folder else output_path.name,
                                "status": "success" if result.success else "failed",
                                "error": None if result.success else (result.error or "Unknown error"),
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "replaced_existing": output_path.exists() if not result.success else False,  # Will be set properly later
                            }

                            # Update results
                            if result.success:
                                results["successful"] += 1
                            else:
                                results["failed"] += 1
                                results["errors"].append({
                                    "workflow": result.workflow_name,
                                    "error": result.error or "Unknown error",
                                })

                            # Add status entry
                            workflow_statuses.append(status_entry)

                            # Update worker status
                            if worker_id is not None:
                                with worker_status_lock:
                                    worker_status[worker_id] = {
                                        "workflow": workflow_name,
                                        "status": "completed"
                                    }

                            # Update progress
                            completed_count = results["successful"] + results["failed"]
                            progress.update(
                                task,
                                advance=1,
                                description=f"[cyan]Rendering workflows... ({completed_count}/{len(workflows)})",
                            )

                            # Update display with fresh worker status and progress
                            live.update(make_display())

                    # Refresh display periodically even if no results ready
                    if not completed_this_iteration and pending_results:
                        live.update(make_display())
                        time.sleep(0.1)

        # Restore original logging levels
        for logger_name, level in saved_levels.items():
            logging.getLogger(logger_name).setLevel(level)

        # Generate n8n-snap-job.json if in_place mode
        end_time = datetime.now(timezone.utc)
        if in_place and input_folder:
            # Merge old successful workflows with new results
            all_workflows = list(previously_successful.values()) + workflow_statuses

            # Calculate totals
            total_successful = len([w for w in all_workflows if w.get("status") == "success"])
            total_failed = len([w for w in all_workflows if w.get("status") == "failed"])
            total_replaced = results["replaced_existing"]

            status_report = {
                "processing_info": {
                    "start_time": existing_state.get("processing_info", {}).get("start_time", start_time.isoformat()),
                    "end_time": end_time.isoformat(),
                    "input_folder": str(input_folder.absolute()),
                    "mode": "in-place",
                    "settings": {
                        "width": width,
                        "height": height,
                        "dark_mode": dark_mode,
                    }
                },
                "summary": {
                    "total_workflows": len(workflows),
                    "successful": total_successful,
                    "failed": total_failed,
                    "replaced_existing": total_replaced,
                },
                "workflows": all_workflows,
            }

            # Write status report to input folder
            report_path = input_folder / "n8n-snap-job.json"
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(status_report, f, indent=2)
            logger.info(f"Status report written to: {report_path}")

        # Calculate total elapsed time
        total_elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        elapsed_minutes = int(total_elapsed // 60)
        elapsed_seconds = int(total_elapsed % 60)

        # Create summary panel
        summary_lines = []
        summary_lines.append(f"[green]✓ Success:[/green] {results['successful']}")
        summary_lines.append(f"[red]✗ Failed:[/red] {results['failed']}")

        if results["replaced_existing"] > 0:
            summary_lines.append(f"[yellow]⟳ Replaced:[/yellow] {results['replaced_existing']}")

        if elapsed_minutes > 0:
            summary_lines.append(f"[cyan]⏱ Time:[/cyan] {elapsed_minutes}m {elapsed_seconds}s")
        else:
            summary_lines.append(f"[cyan]⏱ Time:[/cyan] {elapsed_seconds}s")

        # Add throughput stats for parallel mode
        if total_elapsed > 0:
            workflows_per_min = (results['successful'] + results['failed']) / (total_elapsed / 60)
            summary_lines.append(f"[dim]Throughput:[/dim] {workflows_per_min:.1f} workflows/min")

        if in_place:
            summary_lines.append(f"[dim]Output:[/dim] Images saved in source folders")
            summary_lines.append(f"[dim]Report:[/dim] {input_folder}/n8n-snap-job.json")
        else:
            summary_lines.append(f"[dim]Output:[/dim] {output_folder}")

        console.print("\n")
        console.print(Panel(
            "\n".join(summary_lines),
            title="[bold]Summary[/bold]",
            border_style="green" if results["failed"] == 0 else "yellow",
        ))

        if results["failed"] > 0:
            console.print("\n[bold red]Errors:[/bold red]")
            for error in results["errors"]:
                console.print(f"  [red]✗[/red] {error['workflow']}: {error['error']}")

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user - cleaning up workers...[/yellow]")
        raise


@cli.command()
@click.argument("workflow_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", "-o", type=click.Path(path_type=Path), help="Output PNG file path")
@click.option("--width", default=1920, type=int, help="Viewport width (default: 1920)")
@click.option("--height", default=1080, type=int, help="Viewport height (default: 1080)")
@click.option("--open", "open_file", is_flag=True, help="Open the generated image after rendering")
@click.option("--port", default=5000, type=int, help="Flask server port (default: 5000)")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def preview(
    workflow_file: Path,
    output: Optional[Path],
    width: int,
    height: int,
    open_file: bool,
    port: int,
    verbose: bool,
):
    """Preview a single workflow by generating its snapshot.

    WORKFLOW_FILE: Path to the workflow JSON file
    """
    setup_logging(verbose)

    console.print(Panel.fit(
        f"[bold cyan]Previewing Workflow[/bold cyan]\n"
        f"File: {workflow_file.name}\n"
        f"Viewport: {width}x{height} @ 2x scale",
        border_style="cyan"
    ))

    try:
        # Determine output path
        if output is None:
            output = workflow_file.parent / f"{workflow_file.stem}.png"

        # Scan single file
        with console.status("[bold green]Validating workflow..."):
            scanner = WorkflowScanner(workflow_file.parent, recursive=False)
            workflows = scanner.scan()

            # Find the specific workflow
            workflow = next(
                (w for w in workflows if w.path == workflow_file),
                None
            )

            if not workflow:
                console.print("[red]Workflow file not found in scan results[/red]")
                sys.exit(1)

            if not workflow.valid:
                console.print(f"[red]Invalid workflow:[/red] {workflow.error}")
                sys.exit(1)

        console.print(f"[green]✓[/green] Workflow validated: {workflow.name}\n")

        # Start Flask server
        console.print("[bold green]Starting Flask server...[/bold green]")
        server_thread = run_server_thread(port=port)
        console.print(f"[green]✓[/green] Server running on http://127.0.0.1:{port}\n")

        # Render workflow
        with console.status(f"[bold cyan]Rendering {workflow.name}..."):
            asyncio.run(
                render_single_workflow(
                    workflow,
                    output,
                    width,
                    height,
                    port,
                )
            )

        file_size = output.stat().st_size / 1024  # KB
        console.print(f"\n[green]✓[/green] Snapshot saved: {output} ({file_size:.1f} KB)")

        # Open file if requested
        if open_file:
            import subprocess
            import platform

            system = platform.system()
            if system == "Darwin":  # macOS
                subprocess.run(["open", str(output)])
            elif system == "Windows":
                subprocess.run(["start", str(output)], shell=True)
            elif system == "Linux":
                subprocess.run(["xdg-open", str(output)])

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(130)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        if verbose:
            console.print_exception()
        sys.exit(1)


async def render_single_workflow(
    workflow,
    output_path: Path,
    width: int,
    height: int,
    port: int,
):
    """Render a single workflow.

    Args:
        workflow: WorkflowFile object
        output_path: Output file path
        width: Viewport width
        height: Viewport height
        port: Server port number
    """
    renderer = WorkflowRenderer(
        server_url=f"http://127.0.0.1:{port}",
        width=width,
        height=height,
    )

    await renderer.start()

    try:
        await renderer.render_workflow(
            workflow.workflow_data,
            output_path,
            wait_time=25000,  # 25 seconds
        )
    finally:
        await renderer.close()


if __name__ == "__main__":
    cli()
