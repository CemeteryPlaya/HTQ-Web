#!/usr/bin/env python3
"""
Scaffold a new microservice from the template.

Usage:
    python scaffold.py hr "HR management service"
    python scaffold.py tasks "Task tracking service"

This copies the _template directory and replaces all placeholders.
"""

import shutil
import sys
from pathlib import Path


PLACEHOLDER = "__service_name__"
TEMPLATE_DIR = Path(__file__).parent / "_template"


def scaffold(service_name: str, description: str) -> None:
    """Create a new service directory from template."""
    target = Path(__file__).parent / service_name

    if target.exists():
        print(f"Error: Service '{service_name}' already exists at {target}")
        sys.exit(1)

    print(f"Creating service '{service_name}' from template...")

    # Copy template
    shutil.copytree(TEMPLATE_DIR, target)

    # Replace placeholders in all text files
    for file_path in target.rglob("*"):
        if file_path.is_file():
            try:
                content = file_path.read_text(encoding="utf-8")
                new_content = content.replace(PLACEHOLDER, service_name)
                new_content = new_content.replace("__service_description__", description)
                if new_content != content:
                    file_path.write_text(new_content, encoding="utf-8")
                    print(f"  Updated: {file_path.relative_to(target)}")
            except UnicodeDecodeError:
                pass  # Skip binary files

    # Rename .env.example to .env
    env_example = target / ".env.example"
    env_file = target / ".env"
    if env_example.exists():
        env_example.rename(env_file)

    print(f"\nDone! Service created at: {target}")
    print("\nNext steps:")
    print(f"  1. cd services/{service_name}")
    print("  2. Edit .env — set JWT_SECRET, DB_PASSWORD, SERVICE_PORT")
    print("  3. pip install -r requirements.txt")
    print("  4. uvicorn app.main:app --reload --port <SERVICE_PORT>")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scaffold.py <service_name> <description>")
        print("Example: python scaffold.py hr 'HR management service'")
        sys.exit(1)

    scaffold(sys.argv[1], sys.argv[2])
