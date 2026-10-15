"""Test .dockerignore with Docker itself, using harmless synthetic canaries.

No project data, credentials, or model calls enter this test. Directory
exceptions are deliberately not added to the allowlist: Docker treats them as
recursive inclusions, which previously admitted non-Python files under src.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

ALLOWED = {
    ".dockerignore",
    "Dockerfile",
    "pyproject.toml",
    "uv.lock",
    "README.md",
    "LICENSE",
    "src/dep_triage/__init__.py",
    "src/dep_triage/agent/loop.py",
    "data/tasks.json",
    "data/fixture/manifest.json",
}
FORBIDDEN = {
    ".env",
    ".env.example",
    ".git/config",
    ".docker-context-canary",
    "results/private.json",
    "data/.held-out-runs/probe.json",
    "data/private.json",
    "data/fixture/private.txt",
    "src/dep_triage/.env",
    "src/dep_triage/private.txt",
    "src/dep_triage/agent/private.json",
    "src/dep_triage/agent/__pycache__/loop.pyc",
    ".venv/private.py",
    "model.gguf",
    "tests/private.py",
    "scripts/private.py",
}


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    base = re.search(
        r"^FROM (python:\S+@sha256:[a-f0-9]{64}) AS python$",
        (root / "Dockerfile").read_text(),
        re.MULTILINE,
    )
    assert base, "expected the runtime's pinned Python image"
    with tempfile.TemporaryDirectory(prefix="dep-triage-context-check-") as temporary:
        context = Path(temporary)
        for name in ALLOWED | FORBIDDEN:
            path = context / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("Harmless synthetic canary. Not a credential.\n")
        (context / ".dockerignore").write_bytes((root / ".dockerignore").read_bytes())
        assertion = (
            "from pathlib import Path; "
            "actual = {str(p) for p in Path('.').rglob('*') if p.is_file()}; "
            f"expected = set({sorted(ALLOWED)!r}); "
            "assert actual == expected, {'unexpected': sorted(actual - expected), "
            "'missing': sorted(expected - actual)}; print('context allowlist passed')"
        )
        dockerfile = (
            f"FROM {base.group(1)}\nWORKDIR /context\nCOPY . .\n"
            f"RUN {json.dumps(['python', '-c', assertion])}\n"
        )
        (context / "Dockerfile").write_text(dockerfile)
        subprocess.run(["docker", "build", "--progress=plain", str(context)], check=True)
    print(f"Docker context: {len(ALLOWED)} allowed paths; {len(FORBIDDEN)} canaries excluded")


if __name__ == "__main__":
    main()
