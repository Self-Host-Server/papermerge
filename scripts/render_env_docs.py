#!/usr/bin/env python3
"""Render *.md.template files, substituting ${VAR} references from .env.

Finds every *.md.template file in the repo and writes it alongside itself
with the .template suffix stripped (e.g. docs/setup.md.template ->
docs/setup.md), substituting variable references using the same syntax as
compose.yml: ${VAR}, ${VAR:-default}, ${VAR:?error message}.

Values come from the repo-root .env file, overlaid with the real process
environment (a real exported env var wins over .env, matching common
dotenv-loader convention).
"""

import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"
SKIP_DIRS = {".git", ".tox", "node_modules", "__pycache__"}

VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:-)([^}]*)|(:\?)([^}]*))?\}")


def load_dotenv(path):
    values = {}
    if not path.is_file():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def render(text, env, source):
    def replace(match):
        name, default_op, default_val, error_op, error_msg = match.groups()
        value = env.get(name)
        if value:
            return value
        if default_op == ":-":
            return default_val
        if error_op == ":?":
            message = error_msg or f"{name} is not set"
            print(f"error: {source}: {message}", file=sys.stderr)
            sys.exit(1)
        print(f"warning: {source}: {name} is not set, substituting empty string", file=sys.stderr)
        return ""

    return VAR_PATTERN.sub(replace, text)


def find_templates(root):
    for path in sorted(root.rglob("*.md.template")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def main():
    env = {**load_dotenv(ENV_FILE), **os.environ}
    templates = list(find_templates(REPO_ROOT))
    if not templates:
        print("no *.md.template files found")
        return
    for template_path in templates:
        output_path = template_path.with_suffix("")  # strip ".template"
        rendered = render(template_path.read_text(), env, template_path.relative_to(REPO_ROOT))
        output_path.write_text(rendered)
        print(f"rendered {output_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
