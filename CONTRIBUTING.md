# Contributing to n8n-snap

Thank you for your interest in contributing to n8n-snap! This document provides guidelines and instructions for setting up your development environment and contributing to the project.

## Development Setup

### Prerequisites

- Python 3.9 or higher
- Git
- Internet connection

### Setting Up Your Development Environment

1. **Fork and Clone the Repository**

```bash
# Fork the repository on GitHub, then clone your fork
git clone https://github.com/YOUR_USERNAME/n8n-snap.git
cd n8n-snap
```

2. **Create a Virtual Environment**

```bash
# Create virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate  # On macOS/Linux
# or
venv\Scripts\activate     # On Windows
```

3. **Install in Development Mode**

```bash
# Install package with all dependencies in editable mode
pip install -e .

# Install Playwright browsers
playwright install chromium
```

The `-e` flag installs the package in "editable" mode, which means:
- Changes to the source code are immediately reflected without reinstalling
- Perfect for development and testing
- The package is linked to your source directory rather than copied

### Alternative: Using requirements.txt

You can also install dependencies using:

```bash
pip install -r requirements.txt
playwright install chromium
```

This is equivalent to `pip install -e .` and is useful for maintaining consistency across development environments.

## Installation Methods Explained

### For Contributors (Development)

```bash
pip install -e .
```

**Use this when:**
- You're developing or debugging
- You want changes to take effect immediately
- You're testing modifications

### For End Users (Production)

```bash
pip install .
```

**Use this when:**
- You just want to use the tool
- You don't plan to modify the code
- You want a cleaner installation in site-packages

## Making Changes

### Code Style

- Follow PEP 8 guidelines for Python code
- Use meaningful variable and function names
- Add docstrings to functions and classes
- Keep functions focused and modular

### Testing Your Changes

Before submitting a pull request:

1. **Test the CLI commands:**

```bash
# Validate workflows
n8n-snap scan examples/

# Generate snapshots
n8n-snap generate examples/ output/ --dark-mode
```

2. **Test with different options:**

```bash
# Test different viewport sizes
n8n-snap generate examples/ output/ --width 1440 --height 1440

# Test worker configurations
n8n-snap generate examples/ output/ --workers 4

# Test square format
n8n-snap generate examples/ output/ --square
```

3. **Verify error handling:**
- Test with invalid workflow files
- Test with missing dependencies
- Test with incorrect parameters

## Project Structure

```
n8n-snap/
├── src/
│   ├── cli.py           # CLI commands and interface
│   ├── renderer.py      # Workflow rendering logic
│   ├── server.py        # Flask server for workflow display
│   ├── worker.py        # Parallel worker implementation
│   ├── models.py        # Data models (Pydantic)
│   ├── templates/       # HTML templates
│   └── static/          # JavaScript files
├── examples/            # Sample workflow files
├── setup.py            # Package configuration
├── requirements.txt    # Development installation
└── README.md          # User documentation
```

## Submitting Changes

### Pull Request Process

1. **Create a new branch:**

```bash
git checkout -b feature/your-feature-name
```

2. **Make your changes and commit:**

```bash
git add .
git commit -m "Add: brief description of your changes"
```

3. **Push to your fork:**

```bash
git push origin feature/your-feature-name
```

4. **Create a Pull Request:**
   - Go to the original repository on GitHub
   - Click "New Pull Request"
   - Select your fork and branch
   - Provide a clear description of your changes

### Commit Message Guidelines

- Use present tense ("Add feature" not "Added feature")
- Use imperative mood ("Move cursor to..." not "Moves cursor to...")
- Prefix with type:
  - `Add:` for new features
  - `Fix:` for bug fixes
  - `Update:` for improvements to existing features
  - `Remove:` for removing code/features
  - `Docs:` for documentation changes

## Getting Help

- **Issues:** Check existing issues or create a new one
- **Discussions:** Use GitHub Discussions for questions
- **Documentation:** Refer to README.md for usage instructions

## Code of Conduct

- Be respectful and inclusive
- Provide constructive feedback
- Focus on what is best for the community
- Show empathy towards other contributors

## License

By contributing, you agree that your contributions will be licensed under the same license as the project (MIT License).

---

Thank you for contributing to n8n-snap! 🎉
