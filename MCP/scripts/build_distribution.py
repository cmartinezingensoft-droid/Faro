"""Genera un ZIP limpio y reproducible del servidor MCP Faro.

Excluye entornos virtuales, caches, bytecode, resultados de pruebas y
salidas de distribucion. El ZIP conserva la carpeta raiz ``MCP/``.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]

EXCLUDED_DIRS = {
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "test-runs",
    "dist",
    "build",
    ".git",
    ".idea",
    ".vscode",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
EXCLUDED_FILES = {".DS_Store", "Thumbs.db", ".coverage"}


def should_exclude(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if any(part in EXCLUDED_DIRS for part in rel.parts):
        return True
    if path.name in EXCLUDED_FILES:
        return True
    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return True
    if path.name.endswith(".egg-info"):
        return True
    return False


def build_zip(output: Path) -> tuple[Path, int]:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    files = [p for p in ROOT.rglob("*") if p.is_file() and not should_exclude(p)]
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for source in sorted(files):
            arcname = Path(ROOT.name) / source.relative_to(ROOT)
            zf.write(source, arcname.as_posix())
    return output, len(files)


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera la distribucion limpia del MCP Faro")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "dist" / "MCP.zip",
        help="Ruta del ZIP de salida (por defecto: dist/MCP.zip)",
    )
    args = parser.parse_args()
    output, count = build_zip(args.output)
    print(f"Distribucion generada: {output} ({count} ficheros)")


if __name__ == "__main__":
    main()
