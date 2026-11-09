#!/usr/bin/env python3
"""Mark user-facing Python literals for Django translation."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_DIRS = ("accounts", "billing", "integrations", "operations", "portal", "properties")
MESSAGE_METHODS = {"success", "error", "warning", "info"}


def dotted_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def english_literal(node):
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and any(
        char.isalpha() and char.isascii() for char in node.value
    )


def candidates(tree):
    found = []
    parents = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent

    def eligible(node):
        parent = parents.get(id(node))
        already_wrapped = (
            isinstance(parent, ast.Call)
            and isinstance(parent.func, ast.Name)
            and parent.func.id == "_"
        )
        dictionary_key = isinstance(parent, ast.Dict) and node in parent.keys
        return (
            english_literal(node)
            and not already_wrapped
            and not dictionary_key
            and not isinstance(parent, ast.JoinedStr)
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = dotted_name(node.func)
            if name.startswith("messages.") and name.rsplit(".", 1)[-1] in MESSAGE_METHODS:
                if len(node.args) > 1 and eligible(node.args[1]):
                    found.append(node.args[1])
            elif name.endswith("ValidationError") or name == "ValueError":
                if node.args:
                    found.extend(item for item in ast.walk(node.args[0]) if eligible(item))
            elif name.endswith("add_error") and len(node.args) > 1 and eligible(node.args[1]):
                found.append(node.args[1])
            for keyword in node.keywords:
                if keyword.arg in {"label", "help_text"} and eligible(keyword.value):
                    found.append(keyword.value)
        if isinstance(node, ast.ClassDef) and any(dotted_name(base).endswith("TextChoices") for base in node.bases):
            for statement in node.body:
                if isinstance(statement, ast.Assign) and isinstance(statement.value, ast.Tuple):
                    if len(statement.value.elts) == 2 and eligible(statement.value.elts[1]):
                        found.append(statement.value.elts[1])
    unique = {}
    for node in found:
        unique[(node.lineno, node.col_offset, node.end_lineno, node.end_col_offset)] = node
    return list(unique.values())


def position_offsets(source):
    offsets = [0]
    for line in source.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets


def add_import(source, tree):
    if "django.utils.translation import" in source:
        return source
    last_import_line = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            last_import_line = max(last_import_line, node.end_lineno)
        elif not (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            break
    lines = source.splitlines(keepends=True)
    lines.insert(last_import_line, "from django.utils.translation import gettext_lazy as _\n")
    return "".join(lines)


def transform(path):
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    nodes = candidates(tree)
    if not nodes:
        return False
    offsets = position_offsets(source)
    replacements = []
    for node in nodes:
        start = offsets[node.lineno - 1] + node.col_offset
        end = offsets[node.end_lineno - 1] + node.end_col_offset
        replacements.append((start, end, f"_({source[start:end]})"))
    for start, end, replacement in sorted(replacements, reverse=True):
        source = source[:start] + replacement + source[end:]
    source = add_import(source, ast.parse(source))
    path.write_text(source, encoding="utf-8")
    return True


def main():
    changed = 0
    for app in APP_DIRS:
        for path in sorted((ROOT / app).rglob("*.py")):
            if "migrations" in path.parts or "tests" in path.name or path.name.startswith("test_"):
                continue
            changed += transform(path)
    print(f"Marked {changed} Python modules for translation.")


if __name__ == "__main__":
    main()
