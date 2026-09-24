"""Busca articulos por texto y filtra solo los que tienen stock disponible
(existencias > 0 en al menos un centro).

Usa directamente FaroPhase1Service (la misma logica de negocio que exponen
los tools MCP articulo_buscar + stock_consultar), sin pasar por el protocolo
MCP, para no tener que lanzar un proceso servidor por cada articulo.

Uso:
    .venv\\Scripts\\python.exe scripts\\buscar_articulos_con_stock.py TALADRO
    .venv\\Scripts\\python.exe scripts\\buscar_articulos_con_stock.py TALADRO --centro 1
    .venv\\Scripts\\python.exe scripts\\buscar_articulos_con_stock.py TALADRO --limite 200

Variables de entorno (mismos valores por defecto que el resto del proyecto,
puedes sobreescribirlas si tu DSN/usuario son distintos):
    FARO_ODBC_DSN, FARO_DB_USER, FARO_DB_PASSWORD, FARO_EMPRESA
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import faro_mcp  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Busca articulos con stock disponible.")
    parser.add_argument("texto", help="Texto a buscar en la descripcion del articulo (ej. TALADRO).")
    parser.add_argument("--centro", type=int, default=None, help="Si se indica, solo cuenta stock de ese centro.")
    parser.add_argument("--limite", type=int, default=500, help="Maximo de articulos a examinar (por defecto 500).")
    parser.add_argument("--dsn", default=os.getenv("FARO_ODBC_DSN", "faro"))
    parser.add_argument("--db-user", default=os.getenv("FARO_DB_USER", "SYSDBA"))
    parser.add_argument("--db-password", default=os.getenv("FARO_DB_PASSWORD", "masterkey"))
    parser.add_argument("--empresa", type=int, default=int(os.getenv("FARO_EMPRESA", "1")))
    parser.add_argument("--usuario", default=os.getenv("FARO_USUARIO", "carlos"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = faro_mcp.Settings(
        db_driver="odbc",
        db_path="",
        odbc_dsn=args.dsn,
        db_user=args.db_user,
        db_password=args.db_password,
        empresa=args.empresa,
        centro=args.centro or 1,
        usuario=args.usuario,
    )
    db = faro_mcp.FaroDb(settings)
    svc = faro_mcp.FaroPhase1Service(db)
    try:
        search_result = svc.search_articles(
            texto=args.texto, order_by="ART_DESCRI", limit=args.limite, codart_prefix=""
        )
        found = []
        for item in search_result["items"]:
            stocks = svc.article_stocks(item["codart"])
            per_centro = stocks.get("items", [])
            if args.centro is not None:
                per_centro = [row for row in per_centro if int(row.get("centro") or 0) == args.centro]
            total = sum((Decimal(str(row.get("existencias") or "0")) for row in per_centro), Decimal("0"))
            if total > 0:
                found.append({
                    "codart": item["codart"],
                    "descri": item["descri"].strip(),
                    "unimed": item["unimed"],
                    "pvp": item["pvp"],
                    "proveedor": item["proveedor"],
                    "stock_total": str(total),
                    "stock_por_centro": [
                        {"centro": row.get("centro"), "existencias": row.get("existencias")}
                        for row in per_centro
                        if Decimal(str(row.get("existencias") or "0")) != 0
                    ],
                })
        print(json.dumps(
            {
                "texto_buscado": args.texto,
                "articulos_examinados": search_result["count"],
                "articulos_con_stock": len(found),
                "items": found,
            },
            ensure_ascii=False,
            indent=2,
        ))
    finally:
        db.close()


if __name__ == "__main__":
    main()
