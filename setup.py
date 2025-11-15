"""Setup configuration for n8n-snap package."""

from setuptools import setup, find_packages
from pathlib import Path

# Read README for long description
readme_file = Path(__file__).parent / "README.md"
long_description = readme_file.read_text(encoding="utf-8") if readme_file.exists() else ""

setup(
    name="n8n-snap",
    version="1.0.0",
    description="CLI tool to generate high-quality PNG snapshots from n8n workflow JSON files using Playwright",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="n8n Team",
    author_email="support@n8n.io",
    url="https://github.com/n8n-io/n8n-snap",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "playwright==1.48.0",
        "flask==3.0.0",
        "click==8.1.7",
        "rich==13.7.0",
        "pydantic==2.5.0",
    ],
    entry_points={
        "console_scripts": [
            "n8n-snap=src.cli:cli",
        ],
    },
    python_requires=">=3.9",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Utilities",
    ],
    keywords="n8n workflow automation snapshot png playwright",
    package_data={
        "src": [
            "templates/*.html",
            "static/*.js",
        ],
    },
)
