"""Workflow scanner module for discovering and validating n8n workflow JSON files."""

import json
import logging
from pathlib import Path
from typing import List, Dict, Optional, Any, Union
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)


class WorkflowNode(BaseModel):
    """Model for workflow node validation."""

    name: str
    type: str
    position: List[float] = Field(min_length=2, max_length=2)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    typeVersion: Union[int, float] = Field(ge=1)


class WorkflowData(BaseModel):
    """Model for workflow validation."""

    name: str
    nodes: List[WorkflowNode] = Field(min_length=1)
    connections: Dict[str, Any] = Field(default_factory=dict)
    active: bool = True


@dataclass
class WorkflowFile:
    """Represents a discovered workflow file with metadata."""

    path: Path
    name: str
    valid: bool = False
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    workflow_data: Optional[Dict[str, Any]] = None

    @property
    def filename(self) -> str:
        """Get the filename without extension."""
        return self.path.stem

    @property
    def safe_filename(self) -> str:
        """Get a filesystem-safe version of the workflow name."""
        # Replace special characters with underscores
        safe_name = "".join(
            c if c.isalnum() or c in ("-", "_") else "_"
            for c in self.filename
        )
        # Remove consecutive underscores
        while "__" in safe_name:
            safe_name = safe_name.replace("__", "_")
        return safe_name.strip("_")


class WorkflowScanner:
    """Scanner for discovering and validating n8n workflow files."""

    def __init__(self, input_folder: Path, recursive: bool = True):
        """Initialize the workflow scanner.

        Args:
            input_folder: Path to folder containing workflow JSON files
            recursive: Whether to scan subdirectories recursively
        """
        self.input_folder = Path(input_folder)
        self.recursive = recursive
        self.workflows: List[WorkflowFile] = []

        if not self.input_folder.exists():
            raise FileNotFoundError(f"Input folder not found: {self.input_folder}")

        if not self.input_folder.is_dir():
            raise NotADirectoryError(f"Input path is not a directory: {self.input_folder}")

    def scan(self) -> List[WorkflowFile]:
        """Scan for workflow JSON files.

        Returns:
            List of discovered WorkflowFile objects
        """
        logger.info(f"Scanning for workflows in: {self.input_folder}")

        # Find all JSON files
        pattern = "**/*.json" if self.recursive else "*.json"
        json_files = list(self.input_folder.glob(pattern))

        logger.info(f"Found {len(json_files)} JSON files")

        self.workflows = []
        for json_file in json_files:
            workflow = self._process_file(json_file)
            self.workflows.append(workflow)

        valid_count = sum(1 for w in self.workflows if w.valid)
        logger.info(f"Validated workflows: {valid_count}/{len(self.workflows)}")

        return self.workflows

    def _process_file(self, file_path: Path) -> WorkflowFile:
        """Process a single JSON file.

        Args:
            file_path: Path to the JSON file

        Returns:
            WorkflowFile object with validation results
        """
        try:
            # Read JSON file
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Validate workflow structure
            workflow_data = WorkflowData(**data)

            # Extract metadata
            metadata = {
                "node_count": len(workflow_data.nodes),
                "connection_count": len(workflow_data.connections),
                "active": workflow_data.active,
                "node_types": list(set(node.type for node in workflow_data.nodes)),
            }

            return WorkflowFile(
                path=file_path,
                name=workflow_data.name,
                valid=True,
                metadata=metadata,
                workflow_data=data,
            )

        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON in {file_path.name}: {e}")
            return WorkflowFile(
                path=file_path,
                name=file_path.stem,
                valid=False,
                error=f"Invalid JSON: {str(e)}",
            )

        except ValidationError as e:
            logger.warning(f"Invalid workflow structure in {file_path.name}: {e}")
            return WorkflowFile(
                path=file_path,
                name=file_path.stem,
                valid=False,
                error=f"Validation error: {self._format_validation_error(e)}",
            )

        except Exception as e:
            logger.error(f"Error processing {file_path.name}: {e}")
            return WorkflowFile(
                path=file_path,
                name=file_path.stem,
                valid=False,
                error=f"Processing error: {str(e)}",
            )

    def _format_validation_error(self, error: ValidationError) -> str:
        """Format Pydantic validation error for display.

        Args:
            error: Pydantic ValidationError

        Returns:
            Formatted error message
        """
        errors = error.errors()
        if len(errors) == 1:
            err = errors[0]
            field = " -> ".join(str(loc) for loc in err["loc"])
            return f"{field}: {err['msg']}"
        else:
            return f"{len(errors)} validation errors"

    def get_valid_workflows(self) -> List[WorkflowFile]:
        """Get only valid workflows.

        Returns:
            List of valid WorkflowFile objects
        """
        return [w for w in self.workflows if w.valid]

    def get_invalid_workflows(self) -> List[WorkflowFile]:
        """Get only invalid workflows.

        Returns:
            List of invalid WorkflowFile objects
        """
        return [w for w in self.workflows if not w.valid]

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the scan results.

        Returns:
            Dictionary containing scan statistics
        """
        valid = self.get_valid_workflows()
        invalid = self.get_invalid_workflows()

        total_nodes = sum(w.metadata.get("node_count", 0) for w in valid)
        all_node_types = set()
        for w in valid:
            all_node_types.update(w.metadata.get("node_types", []))

        return {
            "total_files": len(self.workflows),
            "valid_workflows": len(valid),
            "invalid_workflows": len(invalid),
            "total_nodes": total_nodes,
            "unique_node_types": len(all_node_types),
            "node_types": sorted(list(all_node_types)),
        }


def scan_workflows(
    input_folder: str | Path,
    recursive: bool = True,
) -> List[WorkflowFile]:
    """Convenience function to scan workflows.

    Args:
        input_folder: Path to folder containing workflow JSON files
        recursive: Whether to scan subdirectories recursively

    Returns:
        List of discovered WorkflowFile objects
    """
    scanner = WorkflowScanner(input_folder, recursive=recursive)
    return scanner.scan()
