#!/usr/bin/env python
"""Close PREDICTIVE's source for a sealed delivery (v4 Phase 5).

Run from the project root inside the Docker builder. The value — business
rules and use cases — is compiled to native modules (.so) with Nuitka; the
Django glue to bytecode (.pyc); the readable .py are removed. A file Nuitka
cannot compile falls back to bytecode and is noted, so a stubborn dependency
never blocks the delivery (plan §Riesgos).
"""

from __future__ import annotations

import argparse
import compileall
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from modules.licensing.domain.build import Compilation, source_class

ROOTS = ("modules", "config")


def _nuitka(path: Path) -> bool:
    result = subprocess.run(
        [sys.executable, "-m", "nuitka", "--module", str(path), f"--output-dir={path.parent}",
         "--remove-output", "--no-pyi-file", "--quiet", "--jobs=2"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        sys.stderr.write(f"nuitka no pudo con {path}: {result.stderr.strip().splitlines()[-1:]}\n")
    return result.returncode == 0


def _bytecode(path: Path) -> bool:
    # -b: legacy layout, `foo.pyc` beside `foo.py`; imported sourceless.
    return compileall.compile_file(str(path), legacy=True, quiet=1, optimize=0)


def compile_tree(root: Path, limit: int | None, jobs: int) -> dict:
    native, glue = [], []
    for part in ROOTS:
        for path in sorted((root / part).rglob("*.py")):
            (native if source_class(path) is Compilation.NATIVE else glue).append(path)
    if limit is not None:
        glue += native[limit:]
        native = native[:limit]

    fell_back: list[str] = []
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for path, ok in zip(native, pool.map(_nuitka, native), strict=True):
            if not ok:
                fell_back.append(str(path.relative_to(root)))
                _bytecode(path)
    for path in glue:
        if not _bytecode(path):
            raise SystemExit(f"no se pudo compilar a bytecode: {path}")

    for path in native + glue:
        path.unlink()
    for part in ROOTS:
        for cache in (root / part).rglob("__pycache__"):
            for item in cache.iterdir():
                item.unlink()
            cache.rmdir()
    return {
        "native": len(native) - len(fell_back),
        "bytecode": len(glue) + len(fell_back),
        "fell_back_to_bytecode": sorted(fell_back),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--limit", type=int, default=None,
                        help="compile only the first N value files to native")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--report", default="")
    options = parser.parse_args()

    report = compile_tree(Path(options.root).resolve(), options.limit, options.jobs)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if options.report:
        Path(options.report).write_text(text)
    print(text)
    # The point of the phase: no readable source of our code survives.
    root = Path(options.root)
    leftover = [str(p) for part in ROOTS for p in (root / part).rglob("*.py")]
    if leftover:
        raise SystemExit(f"quedaron .py legibles: {leftover[:5]}")


if __name__ == "__main__":
    main()
