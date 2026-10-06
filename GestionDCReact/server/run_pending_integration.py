from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(r"C:\IA\Faro")
MCP_DIR = ROOT / "MCP"

sys.path.insert(0, str(MCP_DIR))

from faro_mcp import FaroToolRuntime  # noqa: E402


def parse_bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "si", "sí", "yes"}


def parse_int(value: str | None) -> int | None:
    value = str(value or "").strip()
    if not value:
        return None
    return int(value)


def main(argv: list[str]) -> int:
    missing_policy = argv[1] if len(argv) > 1 and argv[1] else "detener"
    price_policy = argv[2] if len(argv) > 2 and argv[2] else "mantener"
    limit = parse_int(argv[3] if len(argv) > 3 else "")
    document_only = parse_bool(argv[4] if len(argv) > 4 else "")

    args: dict[str, object] = {
        "politica_articulo_no_encontrado": missing_policy,
        "politica_precio_compra": price_policy,
        "solo_gestion_documental": document_only,
    }
    if limit is not None:
        args["limite"] = limit

    server = FaroToolRuntime()
    result, is_error = server.invoke_tool("entrada_almacen_pendientes_integrar", args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if is_error else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
