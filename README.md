# n8n Workflow Snapshot Generator

Generate high-quality PNG snapshots of n8n workflows using Python and Playwright.

## Features

- **Dark Mode Support** - Render workflows with light or dark theme
- **Flexible Dimensions** - Square, widescreen, or custom aspect ratios
- **High Quality** - 2x retina resolution for crisp images
- **Iframe-only Capture** - Clean workflow screenshots without page chrome
- **Batch Processing** - Process multiple workflows at once
- **CLI-first** - Simple command-line interface for automation

## Prerequisites

- Python 3.8 or higher
- Internet connection (workflows render via n8n cloud service)

## Installation

### 1. Navigate to Project Directory

```bash
cd /Users/edmundhee/Work/GitHub/n8nspace/n8n-snap/python-n8n-snap
```

### 2. Create and Activate Virtual Environment

```bash
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate  # On macOS/Linux
# or
venv\Scripts\activate     # On Windows
```

### 3. Install Dependencies

```bash
# Install Python packages
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

### 4. Install the Package

```bash
pip install -e .
```

## Quick Start

```bash
# Activate virtual environment
source venv/bin/activate

# Scan workflows to validate
n8n-snap scan examples/

# Generate snapshots (default: 1920×1080, light mode)
n8n-snap generate examples/ output/

# Square format with dark mode
n8n-snap generate examples/ output/ --square --dark-mode
```

## Usage

### Commands

#### `scan` - Validate Workflows

Scan and validate workflow JSON files:

```bash
n8n-snap scan <input_folder>

# Options:
#   --recursive/--no-recursive  Scan subdirectories (default: true)
#   -v, --verbose              Enable verbose logging
```

#### `generate` - Generate Snapshots

Generate PNG snapshots from workflows:

```bash
n8n-snap generate <input_folder> <output_folder> [OPTIONS]

# Options:
#   --width INTEGER       Viewport width (default: 1920)
#   --height INTEGER      Viewport height (default: 1080)
#   --square             Use square aspect ratio (2560×2560)
#   --dark-mode          Enable dark theme
#   --timeout INTEGER    Render timeout in seconds (default: 30)
#   --wait-time INTEGER  Wait time for iframe (default: 25)
#   --port INTEGER       Flask server port (default: 5000)
#   -v, --verbose        Enable verbose logging
```

#### `preview` - Preview Single Workflow

Preview a single workflow:

```bash
n8n-snap preview <workflow.json> [OPTIONS]

# Options:
#   --width INTEGER   Viewport width (default: 1920)
#   --height INTEGER  Viewport height (default: 1080)
#   --open           Open the generated image
```

### Examples

#### Light Mode (Default)

```bash
# Standard HD resolution
n8n-snap generate workflows/ output/

# Custom dimensions
n8n-snap generate workflows/ output/ --width 2560 --height 1440
```

#### Dark Mode

```bash
# Dark mode with default dimensions
n8n-snap generate workflows/ output/ --dark-mode

# Dark mode with custom size
n8n-snap generate workflows/ output/ --width 3840 --height 2160 --dark-mode
```

#### Square Format

```bash
# Square format (2560×2560 viewport = 5120×5120 output)
n8n-snap generate workflows/ output/ --square

# Square with dark mode
n8n-snap generate workflows/ output/ --square --dark-mode
```

#### Custom Aspect Ratios

```bash
# Ultra-wide (21:9)
n8n-snap generate workflows/ output/ --width 3440 --height 1440 --dark-mode

# Portrait (9:16)
n8n-snap generate workflows/ output/ --width 1080 --height 1920 --dark-mode

# 4K (16:9)
n8n-snap generate workflows/ output/ --width 3840 --height 2160 --dark-mode
```

#### Verbose Output

```bash
# Show detailed logs for debugging
n8n-snap generate workflows/ output/ --square --dark-mode --verbose
```

## Output

### File Format

- **Format**: PNG
- **Resolution**: Viewport dimensions × 2 (retina quality)
- **Naming**: `{sanitized-filename}.png`

### Examples

| Viewport | Device Scale | Output Resolution |
|----------|--------------|-------------------|
| 1920×1080 | 2x | 3840×2160 (4K) |
| 2560×1440 | 2x | 5120×2880 (5K) |
| 2560×2560 | 2x | 5120×5120 (Square 5K) |
| 3840×2160 | 2x | 7680×4320 (8K) |

### File Sizes

Typical file sizes range from 100-350 KB depending on:
- Workflow complexity
- Number of nodes
- Dimensions

## How It Works

1. **Flask Server** - Serves HTML page with n8n-demo web component
2. **n8n-demo Component** - Official n8n workflow visualization component
3. **Playwright Browser** - Launches headless Chromium to render workflows
4. **Screenshot Capture** - Captures iframe content at specified dimensions
5. **PNG Output** - Saves high-quality PNG to output folder

### Architecture

```
Workflow JSON → Flask Server → n8n-demo Component
                                      ↓
                              Shadow DOM + iframe
                                      ↓
                         n8n Cloud Rendering Service
                                      ↓
                            Playwright Screenshot
                                      ↓
                                  PNG Output
```

## Workflow JSON Format

Workflows must be valid n8n workflow JSON files with:

```json
{
  "name": "Workflow Name",
  "nodes": [
    {
      "name": "Node Name",
      "type": "node-type",
      "position": [x, y],
      "parameters": {},
      "typeVersion": 1.0
    }
  ],
  "connections": {},
  "active": true
}
```

## Troubleshooting

### "No valid workflows found"

- Ensure JSON files are valid n8n workflow exports
- Check that files have `.json` extension
- Verify workflow structure with `n8n-snap scan`

### "Failed to render workflow"

- Check internet connection (requires n8n cloud service)
- Increase timeout: `--timeout 60`
- Increase wait time: `--wait-time 30`
- Run with `--verbose` to see detailed logs

### "Module not found" errors

- Ensure virtual environment is activated
- Reinstall dependencies: `pip install -r requirements.txt`
- Reinstall package: `pip install -e .`

### Playwright browser not found

```bash
playwright install chromium
```

## Using with Your Own Virtual Environment

If you prefer to use your own virtual environment:

```bash
# Activate your virtualenv
source /path/to/your/venv/bin/activate

# Navigate to project
cd /Users/edmundhee/Work/GitHub/n8nspace/n8n-snap/python-n8n-snap

# Install package
pip install -e .

# Install Playwright browsers
playwright install chromium

# Use the tool
n8n-snap --help
```

## Performance

- **Processing Time**: ~25 seconds per workflow (iframe rendering)
- **Memory Usage**: ~200-400 MB per browser instance
- **Processing Mode**: Sequential (one workflow at a time)

## Technical Details

### Dependencies

- **playwright** (1.48.0) - Browser automation
- **flask** (3.0.0) - Web server for rendering
- **click** (8.1.7) - CLI framework
- **rich** (13.7.0) - Terminal formatting
- **pydantic** (2.5.0) - Data validation

### Limitations

- Requires internet connection (n8n cloud rendering service)
- ~25 second minimum render time per workflow
- Sequential processing only
- Light and dark themes supported (via n8n-demo component)

## License

[Add your license here]

## Contributing

[Add contribution guidelines here]

---

**Version**: 1.0.0
**Last Updated**: 2025-11-15
