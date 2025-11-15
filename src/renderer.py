"""Playwright renderer module for capturing n8n workflow screenshots."""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional, Dict, Any
from urllib.parse import quote
from contextlib import asynccontextmanager

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Error as PlaywrightError

logger = logging.getLogger(__name__)


class RenderError(Exception):
    """Custom exception for rendering errors."""
    pass


class WorkflowRenderer:
    """Renderer for capturing workflow screenshots using Playwright."""

    def __init__(
        self,
        server_url: str = "http://127.0.0.1:5000",
        width: int = 1920,
        height: int = 1080,
        device_scale_factor: int = 2,
        timeout: int = 30000,
        headless: bool = True,
        max_retries: int = 3,
        dark_mode: bool = False,
    ):
        """Initialize the workflow renderer.

        Args:
            server_url: URL of the Flask server
            width: Viewport width in pixels
            height: Viewport height in pixels
            device_scale_factor: Device scale factor for retina quality (default: 2)
            timeout: Maximum timeout for page operations in milliseconds
            headless: Run browser in headless mode
            max_retries: Maximum number of retry attempts for failed renders
            dark_mode: Enable dark mode background
        """
        self.server_url = server_url
        self.width = width
        self.height = height
        self.device_scale_factor = device_scale_factor
        self.timeout = timeout
        self.headless = headless
        self.max_retries = max_retries
        self.dark_mode = dark_mode

        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._playwright = None

    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def start(self) -> None:
        """Start the Playwright browser instance."""
        logger.info("Starting Playwright browser")

        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self.headless,
                args=[
                    '--disable-web-security',  # Allow cross-origin iframe
                    '--disable-features=IsolateOrigins,site-per-process',
                ]
            )

            self._context = await self._browser.new_context(
                viewport={"width": self.width, "height": self.height},
                device_scale_factor=self.device_scale_factor,
                bypass_csp=True,  # Bypass Content Security Policy for iframe
            )

            # Set default timeout
            self._context.set_default_timeout(self.timeout)

            logger.info(
                f"Browser started - Viewport: {self.width}x{self.height}, "
                f"Scale: {self.device_scale_factor}x"
            )

        except Exception as e:
            logger.error(f"Failed to start browser: {e}")
            raise RenderError(f"Browser startup failed: {e}") from e

    async def close(self) -> None:
        """Close the Playwright browser instance."""
        logger.info("Closing Playwright browser")

        try:
            if self._context:
                await self._context.close()
                self._context = None

            if self._browser:
                await self._browser.close()
                self._browser = None

            if self._playwright:
                await self._playwright.stop()
                self._playwright = None

        except Exception as e:
            logger.error(f"Error closing browser: {e}")

    async def render_workflow(
        self,
        workflow_data: Dict[str, Any],
        output_path: Path,
        wait_time: int = 25000,
    ) -> bool:
        """Render a workflow to a PNG file.

        Args:
            workflow_data: Workflow JSON data
            output_path: Path to save the PNG screenshot
            wait_time: Time to wait for iframe rendering in milliseconds (default: 25000)

        Returns:
            True if rendering was successful, False otherwise

        Raises:
            RenderError: If rendering fails after all retries
        """
        if not self._browser or not self._context:
            raise RenderError("Browser not started. Call start() first.")

        workflow_name = workflow_data.get("name", "Unknown")

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(
                    f"Rendering workflow: {workflow_name} "
                    f"(Attempt {attempt}/{self.max_retries})"
                )

                success = await self._render_attempt(
                    workflow_data, output_path, wait_time
                )

                if success:
                    logger.info(f"Successfully rendered: {workflow_name}")
                    return True

            except Exception as e:
                logger.warning(
                    f"Render attempt {attempt} failed for {workflow_name}: {e}"
                )

                if attempt == self.max_retries:
                    logger.error(f"All retry attempts failed for {workflow_name}")
                    raise RenderError(
                        f"Failed to render {workflow_name} after {self.max_retries} attempts"
                    ) from e

                # Wait before retry
                await asyncio.sleep(2)

        return False

    async def _render_attempt(
        self,
        workflow_data: Dict[str, Any],
        output_path: Path,
        wait_time: int,
    ) -> bool:
        """Single render attempt.

        Args:
            workflow_data: Workflow JSON data
            output_path: Path to save the PNG screenshot
            wait_time: Time to wait for iframe rendering in milliseconds

        Returns:
            True if successful, False otherwise
        """
        page: Optional[Page] = None

        try:
            # Create new page
            page = await self._context.new_page()

            # Encode workflow data for URL
            workflow_json = json.dumps(workflow_data)
            encoded_workflow = quote(workflow_json)

            # Navigate to renderer
            render_url = f"{self.server_url}/render?workflow={encoded_workflow}"
            if self.dark_mode:
                render_url += "&dark=true"

            # Pass viewport dimensions to set iframe size
            render_url += f"&width={self.width}&height={self.height}"

            logger.debug(f"Navigating to: {self.server_url}/render")
            await page.goto(render_url, wait_until="networkidle", timeout=self.timeout)

            # Wait for n8n-demo component to be present
            logger.debug("Waiting for n8n-demo component")
            await page.wait_for_selector("n8n-demo", state="attached", timeout=10000)

            # Critical: Wait for iframe to fully load and render
            # The workflow visualization happens in a cross-origin iframe
            # which takes ~15-25 seconds to fully render
            logger.debug(f"Waiting {wait_time}ms for iframe rendering")
            start_time = time.time()
            await page.wait_for_timeout(wait_time)
            elapsed = time.time() - start_time
            logger.debug(f"Waited {elapsed:.1f}s for rendering")

            # Find the iframe inside the n8n-demo shadow DOM
            logger.debug("Locating iframe in shadow DOM")
            iframe = await page.evaluate_handle("""
                () => {
                    const demo = document.querySelector('n8n-demo');
                    if (!demo || !demo.shadowRoot) return null;
                    return demo.shadowRoot.querySelector('iframe');
                }
            """)

            # Convert handle to element
            iframe_element = iframe.as_element()
            if not iframe_element:
                raise Exception("Could not find iframe in n8n-demo shadow DOM")

            # Ensure output directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # Take screenshot of just the iframe
            logger.debug("Capturing screenshot of iframe only")
            await iframe_element.screenshot(
                path=str(output_path),
                type="png",
                animations="disabled",  # Disable animations for consistent output
            )

            file_size = output_path.stat().st_size / 1024  # KB
            logger.debug(f"Screenshot saved: {output_path.name} ({file_size:.1f} KB)")

            return True

        except PlaywrightError as e:
            logger.error(f"Playwright error during render: {e}")
            raise

        except Exception as e:
            logger.error(f"Unexpected error during render: {e}")
            raise

        finally:
            # Always close the page
            if page:
                await page.close()

    async def render_batch(
        self,
        workflows: list,
        output_folder: Path,
        wait_time: int = 25000,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """Render multiple workflows in batch.

        Args:
            workflows: List of WorkflowFile objects
            output_folder: Directory to save PNG files
            wait_time: Time to wait for iframe rendering in milliseconds
            progress_callback: Optional callback function called after each workflow

        Returns:
            Dictionary with batch processing results
        """
        if not self._browser:
            await self.start()

        output_folder.mkdir(parents=True, exist_ok=True)

        results = {
            "total": len(workflows),
            "successful": 0,
            "failed": 0,
            "errors": [],
        }

        for i, workflow in enumerate(workflows, 1):
            try:
                # Generate output filename
                output_filename = f"{workflow.safe_filename}.png"
                output_path = output_folder / output_filename

                # Render workflow
                await self.render_workflow(
                    workflow.workflow_data,
                    output_path,
                    wait_time=wait_time,
                )

                results["successful"] += 1

            except Exception as e:
                logger.error(f"Failed to render {workflow.name}: {e}")
                results["failed"] += 1
                results["errors"].append({
                    "workflow": workflow.name,
                    "file": str(workflow.path),
                    "error": str(e),
                })

            finally:
                # Call progress callback if provided
                if progress_callback:
                    progress_callback(i, len(workflows), workflow.name)

        return results


# Import asyncio at module level
import asyncio


@asynccontextmanager
async def create_renderer(**kwargs):
    """Async context manager to create and manage a renderer.

    Args:
        **kwargs: Arguments to pass to WorkflowRenderer

    Yields:
        WorkflowRenderer instance
    """
    renderer = WorkflowRenderer(**kwargs)
    try:
        await renderer.start()
        yield renderer
    finally:
        await renderer.close()


async def render_workflow_file(
    workflow_file,
    output_path: Path,
    server_url: str = "http://127.0.0.1:5000",
    width: int = 1920,
    height: int = 1080,
    wait_time: int = 25000,
) -> bool:
    """Convenience function to render a single workflow file.

    Args:
        workflow_file: WorkflowFile object
        output_path: Path to save the PNG screenshot
        server_url: URL of the Flask server
        width: Viewport width
        height: Viewport height
        wait_time: Time to wait for iframe rendering in milliseconds

    Returns:
        True if successful, False otherwise
    """
    async with create_renderer(
        server_url=server_url,
        width=width,
        height=height,
    ) as renderer:
        return await renderer.render_workflow(
            workflow_file.workflow_data,
            output_path,
            wait_time=wait_time,
        )
