"""Helpers for ltree path manipulation and querying.

PostgreSQL ltree stores hierarchical labels separated by dots.
Example: "company.engineering.backend"

All raw ltree SQL uses the ltree operators directly when needed.
"""

import re

LABEL_RE = re.compile(r"^[a-zA-Z0-9_]+$")


def validate_label(label: str) -> bool:
    """Each ltree label must only contain letters, digits, underscores."""
    return bool(LABEL_RE.match(label))


def validate_path(path: str) -> bool:
    """Validate a full ltree path like 'company.engineering.backend'."""
    return all(validate_label(part) for part in path.split(".") if part)


def parent_path(path: str) -> str | None:
    """Return the parent ltree path, or None if already a root label."""
    parts = path.rsplit(".", 1)
    return parts[0] if len(parts) == 2 else None


def depth(path: str) -> int:
    """Return the depth (number of labels) of a path."""
    return len(path.split("."))


def is_ancestor(ancestor: str, descendant: str) -> bool:
    """Return True if ancestor is a proper prefix of descendant."""
    return descendant.startswith(ancestor + ".") and ancestor != descendant


def children_like_pattern(path: str) -> str:
    """Return a LIKE pattern to match direct children (one level deeper)."""
    # Matches 'parent.child' but NOT 'parent.child.grandchild'
    # Used as: WHERE path LIKE 'parent.%' AND path NOT LIKE 'parent.%.%'
    return f"{path}.%"
