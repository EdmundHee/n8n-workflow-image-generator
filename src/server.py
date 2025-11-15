"""Flask server for rendering n8n workflows with the n8n-demo component."""

import json
import logging
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

from flask import Flask, render_template, request, jsonify

logger = logging.getLogger(__name__)


class WorkflowServer:
    """Flask server to serve workflow rendering pages."""

    def __init__(self, port: int = 5000, debug: bool = False):
        """Initialize the Flask server.

        Args:
            port: Port number to run the server on
            debug: Enable Flask debug mode
        """
        self.port = port
        self.debug = debug
        self.app = self._create_app()

    def _create_app(self) -> Flask:
        """Create and configure Flask application.

        Returns:
            Configured Flask app instance
        """
        # Get the package directory
        package_dir = Path(__file__).parent.parent

        app = Flask(
            __name__,
            template_folder=str(package_dir / "templates"),
            static_folder=str(package_dir / "static"),
        )

        # Disable Flask's default logging in production
        if not self.debug:
            log = logging.getLogger("werkzeug")
            log.setLevel(logging.ERROR)

        self._register_routes(app)

        return app

    def _register_routes(self, app: Flask) -> None:
        """Register Flask routes.

        Args:
            app: Flask application instance
        """

        @app.route("/")
        def index():
            """Health check endpoint."""
            return jsonify({"status": "ok", "message": "n8n-snap workflow renderer"})

        @app.route("/render", methods=["GET", "POST"])
        def render():
            """Render a workflow from JSON data.

            GET Query Parameters:
                workflow: URL-encoded JSON string of the workflow data
                dark: Enable dark mode (optional, default: false)
                width: Viewport width (optional)
                height: Viewport height (optional)

            POST JSON Body:
                workflow: Workflow JSON object
                dark: Enable dark mode (optional, default: false)
                width: Viewport width (optional)
                height: Viewport height (optional)

            Returns:
                Rendered HTML page with n8n-demo component
            """
            # Support both GET (for small workflows) and POST (for large workflows)
            if request.method == "POST":
                # POST: workflow data in request body
                data = request.get_json() or {}
                workflow_data = data.get("workflow")
                dark_mode = data.get("dark", False)
                width = data.get("width", "1920")
                height = data.get("height", "1080")

                if not workflow_data:
                    logger.error("No workflow data provided in POST body")
                    return render_template(
                        "workflow-renderer.html",
                        workflow_json=None,
                        dark_mode=False,
                        width=width,
                        height=height
                    ), 400

                workflow_json_str = json.dumps(workflow_data) if isinstance(workflow_data, dict) else workflow_data
            else:
                # GET: workflow data in query parameter
                workflow_param = request.args.get("workflow", "")
                dark_mode = request.args.get("dark", "false").lower() == "true"
                width = request.args.get("width", "1920")
                height = request.args.get("height", "1080")

                if not workflow_param:
                    logger.error("No workflow data provided")
                    return render_template(
                        "workflow-renderer.html",
                        workflow_json=None,
                        dark_mode=False,
                        width=width,
                        height=height
                    ), 400

                # Decode URL-encoded JSON
                workflow_json_str = unquote(workflow_param)

            try:
                # Validate JSON
                workflow_data = json.loads(workflow_json_str)

                # Basic validation
                if not isinstance(workflow_data, dict):
                    raise ValueError("Workflow data must be a JSON object")

                # Convert back to JSON string for template
                workflow_json = json.dumps(workflow_data)

                logger.debug(f"Rendering workflow: {workflow_data.get('name', 'Unknown')}")

                return render_template(
                    "workflow-renderer.html",
                    workflow_json=workflow_json,
                    dark_mode=dark_mode,
                    width=width,
                    height=height
                )

            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON data: {e}")
                return jsonify({"error": "Invalid JSON data", "details": str(e)}), 400
            except Exception as e:
                logger.error(f"Error rendering workflow: {e}")
                return jsonify({"error": "Failed to render workflow", "details": str(e)}), 500

        @app.route("/health")
        def health():
            """Health check endpoint for monitoring."""
            return jsonify({
                "status": "healthy",
                "port": self.port,
                "debug": self.debug
            })

    def run(self, host: str = "127.0.0.1") -> None:
        """Start the Flask server.

        Args:
            host: Host address to bind to
        """
        logger.info(f"Starting workflow renderer server on http://{host}:{self.port}")
        self.app.run(host=host, port=self.port, debug=self.debug, threaded=True)

    def get_app(self) -> Flask:
        """Get the Flask app instance.

        Returns:
            Flask application instance
        """
        return self.app


def create_server(port: int = 5000, debug: bool = False) -> WorkflowServer:
    """Factory function to create a WorkflowServer instance.

    Args:
        port: Port number to run the server on
        debug: Enable Flask debug mode

    Returns:
        WorkflowServer instance
    """
    return WorkflowServer(port=port, debug=debug)


if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Create and run server
    server = create_server(debug=True)
    server.run()
