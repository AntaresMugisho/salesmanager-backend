"""Shared helper for the "this module imports no Django" tests.

Not named `test_*.py` so pytest does not collect it.

AST-based rather than a substring search: several of these modules mention
Django in a docstring explaining *why* they do not import it, and a grep-based
check fails on its own documentation.
"""

import ast
import inspect


def django_imports_of(module) -> list[str]:
    """Every `django...` name the module imports, by reading its source."""
    tree = ast.parse(inspect.getsource(module))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if a.name.split(".")[0] == "django"]
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "django":
                found.append(node.module)
    return found
