"""n8n-snap - Generate high-quality PNG snapshots from n8n workflow JSON files.

This package provides a CLI tool and Python API for rendering n8n workflows
to PNG images using Playwright browser automation.
"""

__version__ = "1.0.0"
__author__ = "n8n Team"
__license__ = "MIT"

from n8n_snap.scanner import WorkflowScanner, WorkflowFile, scan_workflows
from n8n_snap.renderer import WorkflowRenderer, create_renderer, render_workflow_file
from n8n_snap.server import WorkflowServer, create_server

__all__ = [
    # Version info
    "__version__",
    "__author__",
    "__license__",
    # Scanner
    "WorkflowScanner",
    "WorkflowFile",
    "scan_workflows",
    # Renderer
    "WorkflowRenderer",
    "create_renderer",
    "render_workflow_file",
    # Server
    "WorkflowServer",
    "create_server",
]
