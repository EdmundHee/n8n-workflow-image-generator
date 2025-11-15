"""Worker process module for parallel workflow rendering."""

import asyncio
import logging
import multiprocessing
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass

from src.renderer import WorkflowRenderer, RenderError

logger = logging.getLogger(__name__)


@dataclass
class WorkflowTask:
    """Represents a workflow rendering task."""
    workflow_data: Dict[str, Any]
    workflow_name: str
    safe_filename: str
    output_path: Path


@dataclass
class WorkflowResult:
    """Represents the result of a workflow rendering task."""
    workflow_name: str
    output_path: Path
    success: bool
    error: Optional[str] = None
    worker_id: int = 0


def render_workflow_worker(
    task: WorkflowTask,
    worker_id: int,
    server_url: str,
    width: int,
    height: int,
    timeout: int,
    wait_time: int,
    dark_mode: bool,
) -> WorkflowResult:
    """Worker function to render a single workflow.

    This function runs in a separate process and initializes its own
    Playwright browser instance.

    Args:
        task: WorkflowTask containing workflow data and output path
        worker_id: Unique identifier for this worker process
        server_url: URL of the Flask server
        width: Viewport width in pixels
        height: Viewport height in pixels
        timeout: Maximum timeout for page operations in seconds
        wait_time: Time to wait for iframe rendering in seconds
        dark_mode: Enable dark mode background

    Returns:
        WorkflowResult with success status and any error information
    """
    # Set up logging for this worker process
    logging.basicConfig(
        level=logging.INFO,
        format=f'[Worker-{worker_id}] %(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    logger.info(f"Worker {worker_id} starting to render: {task.workflow_name}")

    try:
        # Run the async rendering in this process
        result = asyncio.run(_render_workflow_async(
            task=task,
            worker_id=worker_id,
            server_url=server_url,
            width=width,
            height=height,
            timeout=timeout,
            wait_time=wait_time,
            dark_mode=dark_mode,
        ))
        return result

    except Exception as e:
        logger.error(f"Worker {worker_id} failed to render {task.workflow_name}: {e}")
        return WorkflowResult(
            workflow_name=task.workflow_name,
            output_path=task.output_path,
            success=False,
            error=str(e),
            worker_id=worker_id,
        )


async def _render_workflow_async(
    task: WorkflowTask,
    worker_id: int,
    server_url: str,
    width: int,
    height: int,
    timeout: int,
    wait_time: int,
    dark_mode: bool,
) -> WorkflowResult:
    """Async function to render a workflow using Playwright.

    Each worker gets its own isolated browser instance.
    """
    # Initialize renderer for this worker
    renderer = WorkflowRenderer(
        server_url=server_url,
        width=width,
        height=height,
        timeout=timeout * 1000,  # Convert to milliseconds
        dark_mode=dark_mode,
    )

    try:
        # Start browser
        async with renderer:
            # Render the workflow
            await renderer.render_workflow(
                workflow_data=task.workflow_data,
                output_path=task.output_path,
                wait_time=wait_time * 1000,  # Convert to milliseconds
            )

            logger.info(f"Worker {worker_id} successfully rendered: {task.workflow_name}")
            return WorkflowResult(
                workflow_name=task.workflow_name,
                output_path=task.output_path,
                success=True,
                worker_id=worker_id,
            )

    except RenderError as e:
        logger.error(f"Worker {worker_id} render error for {task.workflow_name}: {e}")
        return WorkflowResult(
            workflow_name=task.workflow_name,
            output_path=task.output_path,
            success=False,
            error=str(e),
            worker_id=worker_id,
        )
    except Exception as e:
        logger.error(f"Worker {worker_id} unexpected error for {task.workflow_name}: {e}")
        return WorkflowResult(
            workflow_name=task.workflow_name,
            output_path=task.output_path,
            success=False,
            error=f"Unexpected error: {str(e)}",
            worker_id=worker_id,
        )
