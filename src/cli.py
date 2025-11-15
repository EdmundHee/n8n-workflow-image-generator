"""CLI interface for n8n-snap workflow snapshot generator."""

import asyncio
import logging
import multiprocessing
import os
import sys
import threading
import time
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

# Initialize Rich console
console = Console()


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
@click.argument("output_folder", type=click.Path(file_okay=False, path_type=Path))
@click.option("--width", default=1920, type=int, help="Viewport width (default: 1920)")
@click.option("--height", default=1080, type=int, help="Viewport height (default: 1080)")
@click.option("--square", is_flag=True, help="Use square aspect ratio (2560x2560)")
@click.option("--dark-mode", is_flag=True, help="Enable dark mode background")
@click.option("--timeout", default=30, type=int, help="Render timeout in seconds (default: 30)")
@click.option("--wait-time", default=25, type=int, help="Wait time for iframe rendering in seconds (default: 25)")
@click.option("--port", default=5000, type=int, help="Flask server port (default: 5000)")
@click.option("--workers", default=1, type=int, help="Number of parallel workers (default: 1, max: cpu_count)")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def generate(
    input_folder: Path,
    output_folder: Path,
    width: int,
    height: int,
    square: bool,
    dark_mode: bool,
    timeout: int,
    wait_time: int,
    port: int,
    workers: int,
    verbose: bool,
):
    """Generate PNG snapshots from workflow JSON files.

    INPUT_FOLDER: Directory containing workflow JSON files

    OUTPUT_FOLDER: Directory to save PNG snapshots
    """
    setup_logging(verbose)

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

    console.print(Panel.fit(
        f"[bold cyan]n8n Workflow Snapshot Generator[/bold cyan]\n"
        f"Input: {input_folder}\n"
        f"Output: {output_folder}\n"
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
    output_folder: Path,
    width: int,
    height: int,
    timeout: int,
    wait_time: int,
    port: int,
    dark_mode: bool = False,
):
    """Async function to render workflows with progress tracking.

    Args:
        workflows: List of valid WorkflowFile objects
        output_folder: Output directory path
        width: Viewport width
        height: Viewport height
        timeout: Timeout in seconds
        wait_time: Wait time for iframe in seconds
        port: Server port number
        dark_mode: Enable dark mode background
    """
    # Create output folder
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
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:

            task = progress.add_task(
                "[cyan]Rendering workflows...",
                total=len(workflows)
            )

            results = {
                "successful": 0,
                "failed": 0,
                "errors": [],
            }

            for i, workflow in enumerate(workflows, 1):
                try:
                    # Update progress description
                    progress.update(
                        task,
                        description=f"[cyan]Rendering {workflow.name[:40]}...",
                    )

                    # Generate output path
                    output_filename = f"{workflow.safe_filename}.png"
                    output_path = output_folder / output_filename

                    # Render workflow
                    await renderer.render_workflow(
                        workflow.workflow_data,
                        output_path,
                        wait_time=wait_time * 1000,  # Convert to milliseconds
                    )

                    results["successful"] += 1

                except Exception as e:
                    results["failed"] += 1
                    results["errors"].append({
                        "workflow": workflow.name,
                        "error": str(e),
                    })

                finally:
                    # Update progress
                    progress.update(task, advance=1)

        # Print results
        console.print("\n[bold]Results:[/bold]")
        console.print(f"  [green]✓ {results['successful']} workflows processed successfully[/green]")

        if results["failed"] > 0:
            console.print(f"  [red]✗ {results['failed']} workflows failed[/red]")

            console.print("\n[bold red]Errors:[/bold red]")
            for error in results["errors"]:
                console.print(f"  [red]✗[/red] {error['workflow']}: {error['error']}")

        console.print(f"\n[bold cyan]Output folder:[/bold cyan] {output_folder}")

    finally:
        await renderer.close()


def render_workflows_parallel(
    workflows: list,
    output_folder: Path,
    width: int,
    height: int,
    timeout: int,
    wait_time: int,
    port: int,
    dark_mode: bool,
    workers: int,
):
    """Render workflows using parallel workers with resource monitoring.

    Args:
        workflows: List of valid WorkflowFile objects
        output_folder: Output directory path
        width: Viewport width
        height: Viewport height
        timeout: Timeout in seconds
        wait_time: Wait time for iframe in seconds
        port: Server port number
        dark_mode: Enable dark mode background
        workers: Number of parallel workers
    """
    # Create output folder
    output_folder.mkdir(parents=True, exist_ok=True)

    # Create tasks for all workflows
    tasks = []
    for workflow in workflows:
        output_filename = f"{workflow.safe_filename}.png"
        output_path = output_folder / output_filename

        task = WorkflowTask(
            workflow_data=workflow.workflow_data,
            workflow_name=workflow.name,
            safe_filename=workflow.safe_filename,
            output_path=output_path,
        )
        tasks.append(task)

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

    # Initialize results
    results = {
        "successful": 0,
        "failed": 0,
        "errors": [],
    }

    # Track worker statuses
    worker_status = {i: {"workflow": None, "status": "idle"} for i in range(workers)}
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
            total=len(workflows)
        )

        # Create grouped display (worker status + progress)
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
                        status_lines.append(f"  [cyan]Worker {worker_id}:[/cyan] [yellow]Rendering[/yellow] {workflow_name}")
                    elif worker_info["status"] == "completed":
                        workflow_name = worker_info["workflow"]
                        if len(workflow_name) > 40:
                            workflow_name = workflow_name[:37] + "..."
                        status_lines.append(f"  [cyan]Worker {worker_id}:[/cyan] [green]✓[/green] {workflow_name}")

            return Panel(
                "\n".join(status_lines) if status_lines else "[dim]No workers active[/dim]",
                title="Worker Status",
                border_style="blue",
            )

        def make_display():
            return Group(
                make_worker_status_panel(),
                progress
            )

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
                            "workflow": workflow_task.workflow_name,
                            "status": "rendering"
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

                            # Update results
                            if result.success:
                                results["successful"] += 1
                            else:
                                results["failed"] += 1
                                results["errors"].append({
                                    "workflow": result.workflow_name,
                                    "error": result.error or "Unknown error",
                                })

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

        # Print results
        console.print("\n[bold]Results:[/bold]")
        console.print(f"  [green]✓ {results['successful']} workflows processed successfully[/green]")

        if results["failed"] > 0:
            console.print(f"  [red]✗ {results['failed']} workflows failed[/red]")

            console.print("\n[bold red]Errors:[/bold red]")
            for error in results["errors"]:
                console.print(f"  [red]✗[/red] {error['workflow']}: {error['error']}")

        console.print(f"\n[bold cyan]Output folder:[/bold cyan] {output_folder}")

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
