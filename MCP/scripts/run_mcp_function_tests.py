"""Run reproducible MCP function smoke tests for the Faro server.

The default suite is intentionally safe: it lists tools, exercises read-only
operations through the official stdio client, and verifies that write tools are
blocked while FARO_MCP_ACCESS_LEVEL=read.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import faro_mcp  # noqa: E402


@dataclass(frozen=True)
class TestCase:
    name: str
    group: str
    profile: str
    access_level: str
    tool: str
    arguments: dict[str, Any]
    expect_error: bool = False
    expect_ok_field: bool | None = True
    description: str = ""
    requires: tuple[str, ...] = field(default_factory=tuple)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Faro MCP function tests through the official stdio client."
    )
    parser.add_argument("--dsn", default=os.getenv("FARO_ODBC_DSN", "Faro"))
    parser.add_argument("--db-user", default=os.getenv("FARO_DB_USER", "SYSDBA"))
    parser.add_argument("--db-password", default=os.getenv("FARO_DB_PASSWORD", "masterkey"))
    parser.add_argument("--empresa", type=int, default=int(os.getenv("FARO_EMPRESA", "1")))
    parser.add_argument("--centro", type=int, default=int(os.getenv("FARO_CENTRO", "0")))
    parser.add_argument("--usuario", default=os.getenv("FARO_USUARIO", "codex"))
    parser.add_argument("--sample-articulo", default=os.getenv("FARO_TEST_ARTICULO", ""))
    parser.add_argument("--sample-cliente", type=int, default=int(os.getenv("FARO_TEST_CLIENTE", "0")))
    parser.add_argument("--sample-subcliente", type=int, default=int(os.getenv("FARO_TEST_SUBCLIENTE", "0")))
    parser.add_argument("--sample-ejercicio", type=int, default=int(os.getenv("FARO_TEST_EJERCICIO", "0")))
    parser.add_argument("--sample-serie", default=os.getenv("FARO_TEST_SERIE", ""))
    parser.add_argument("--sample-numero", type=int, default=int(os.getenv("FARO_TEST_NUMERO", "0")))
    parser.add_argument(
        "--include-write-dry-run",
        action="store_true",
        help="Include safe write-class tools that are simulations or permission-denial checks only.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "test-runs",
        help="Directory where JSON/CSV evidence will be written.",
    )
    parser.add_argument(
        "--server",
        type=Path,
        default=ROOT / "server.py",
        help="MCP server entry point.",
    )
    return parser.parse_args()


def base_env(args: argparse.Namespace, profile: str, access_level: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "FARO_DB_DRIVER": "odbc",
            "FARO_ODBC_DSN": args.dsn,
            "FARO_DB_USER": args.db_user,
            "FARO_DB_PASSWORD": args.db_password,
            "FARO_EMPRESA": str(args.empresa),
            "FARO_CENTRO": str(args.centro),
            "FARO_USUARIO": args.usuario,
            "FARO_MCP_TOOL_PROFILE": profile,
            "FARO_MCP_ACCESS_LEVEL": access_level,
            "FARO_MCP_TRANSPORT": "stdio",
            "FARO_MCP_AUDIT_REQUIRED": "false",
            "FARO_MCP_AUDIT_READS": "false",
        }
    )
    return env


def extract_json_text(call_result: Any) -> tuple[dict[str, Any] | None, str]:
    if not call_result.content:
        return None, ""
    text = getattr(call_result.content[0], "text", "")
    try:
        return json.loads(text), text
    except json.JSONDecodeError:
        return None, text


def first_item(result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    data = result.get("data")
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list) and items and isinstance(items[0], dict):
            return items[0]
    return {}


def _first_present(item: dict[str, Any], *keys: str) -> Any:
    """Return the first key present with a non-None value.

    Unlike chaining ``or``, this treats falsy-but-valid values (like a
    client code of ``0``, a common "walk-in"/generic customer code in
    Faro) as present instead of skipping to the next key.
    """
    for key in keys:
        value = item.get(key)
        if value is not None:
            return value
    return None


async def call_tool(
    args: argparse.Namespace,
    profile: str,
    access_level: str,
    tool: str,
    arguments: dict[str, Any],
) -> tuple[bool, dict[str, Any] | None, str]:
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(args.server)],
        cwd=str(ROOT),
        env=base_env(args, profile, access_level),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, arguments)
            payload, raw_text = extract_json_text(result)
            return bool(result.is_error), payload, raw_text


async def list_tools(args: argparse.Namespace, profile: str, access_level: str) -> list[str]:
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(args.server)],
        cwd=str(ROOT),
        env=base_env(args, profile, access_level),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return [tool.name for tool in result.tools]


async def discover_fixtures(args: argparse.Namespace) -> dict[str, Any]:
    fixtures: dict[str, Any] = {
        "articulo": args.sample_articulo,
        "cliente": args.sample_cliente or None,
        "subcliente": args.sample_subcliente,
        "ejercicio": args.sample_ejercicio or None,
        "serie": args.sample_serie,
        "numero": args.sample_numero or None,
    }

    if not fixtures["articulo"]:
        _, payload, _ = await call_tool(args, "core", "read", "articulo_buscar", {"limite": 1})
        item = first_item(payload)
        fixtures["articulo"] = item.get("codart") or item.get("articulo") or ""

    if fixtures["cliente"] is None:
        _, payload, _ = await call_tool(args, "core", "read", "cliente_buscar", {"limite": 1})
        item = first_item(payload)
        fixtures["cliente"] = _first_present(item, "codcli", "cliente", "CLI_CODCLI")
        subcliente = _first_present(item, "subcli", "subcliente", "CLI_SUBCLI")
        fixtures["subcliente"] = subcliente if subcliente is not None else 0

    return fixtures


def build_cases(args: argparse.Namespace, fixtures: dict[str, Any]) -> list[TestCase]:
    articulo = str(fixtures.get("articulo") or "")
    cliente = fixtures.get("cliente")
    subcliente = int(fixtures.get("subcliente") or 0)
    centro = args.centro

    cases = [
        TestCase(
            name="read_articulo_buscar",
            group="read-core",
            profile="core",
            access_level="read",
            tool="articulo_buscar",
            arguments={"limite": 1},
            description="Busca un articulo cualquiera con limite 1.",
        ),
        TestCase(
            name="read_cliente_buscar",
            group="read-core",
            profile="core",
            access_level="read",
            tool="cliente_buscar",
            arguments={"limite": 1},
            description="Busca un cliente cualquiera con limite 1.",
        ),
        TestCase(
            name="read_proveedor_buscar",
            group="read-core",
            profile="core",
            access_level="read",
            tool="proveedor_buscar",
            arguments={"limite": 1},
            description="Busca un proveedor cualquiera con limite 1.",
        ),
        TestCase(
            name="read_catalogo_marcas",
            group="read-core",
            profile="core",
            access_level="read",
            tool="articulo_catalogo_listar",
            arguments={"tipo": "marcas"},
            description="Lista catalogo de marcas.",
        ),
        TestCase(
            name="read_actividad_tipos",
            group="read-core",
            profile="core",
            access_level="read",
            tool="actividad_tipo_listar",
            arguments={},
            description="Lista tipos de actividad CRM.",
        ),
        TestCase(
            name="read_pedido_listar",
            group="read-core",
            profile="core",
            access_level="read",
            tool="pedido_listar",
            arguments={"centro": centro},
            description="Lista pedidos operativos del centro.",
        ),
        TestCase(
            name="read_etiqueta_listar",
            group="read-core",
            profile="core",
            access_level="read",
            tool="etiqueta_gestion",
            arguments={"accion": "listar"},
            description="Lista etiquetas pendientes.",
        ),
        TestCase(
            name="read_recuento_listar",
            group="read-core",
            profile="core",
            access_level="read",
            tool="recuento_gestion",
            arguments={"accion": "listar", "centro": centro},
            description="Lista recuentos del centro.",
        ),
        TestCase(
            name="read_falta_listar",
            group="read-core",
            profile="core",
            access_level="read",
            tool="falta_gestion",
            arguments={"accion": "listar", "centro": centro},
            description="Lista faltas del centro.",
        ),
        TestCase(
            name="security_unknown_tool",
            group="security",
            profile="core",
            access_level="read",
            tool="herramienta_inexistente",
            arguments={},
            expect_error=True,
            expect_ok_field=False,
            description="Confirma error controlado para herramienta inexistente.",
        ),
        TestCase(
            name="security_write_blocked_on_read",
            group="security",
            profile="core",
            access_level="read",
            tool="cliente_actualizar",
            arguments={
                "datos": {
                    "cliente": 99999999,
                    "subcliente": 0,
                    "nombre": "PRUEBA MCP BLOQUEADA",
                    "razon_social": "PRUEBA MCP BLOQUEADA",
                    "domicilio": "SIN CAMBIO",
                    "codigo_postal": "00000",
                    "poblacion": "PRUEBA",
                    "telefono": "",
                    "email": "prueba@example.invalid",
                    "cif": "X0000000X",
                }
            },
            expect_error=True,
            expect_ok_field=False,
            description="Confirma que una escritura se bloquea con acceso read.",
        ),
    ]

    if articulo:
        cases.extend(
            [
                TestCase(
                    name="read_articulo_obtener",
                    group="read-core",
                    profile="core",
                    access_level="read",
                    tool="articulo_obtener",
                    arguments={"identificador": articulo},
                    requires=("articulo",),
                    description="Obtiene ficha del articulo descubierto o indicado.",
                ),
                TestCase(
                    name="read_stock_consultar",
                    group="read-core",
                    profile="core",
                    access_level="read",
                    tool="stock_consultar",
                    arguments={"articulo": articulo, "centro": centro},
                    requires=("articulo",),
                    description="Consulta stock del articulo en el centro.",
                ),
                TestCase(
                    name="read_articulo_compra",
                    group="read-core",
                    profile="core",
                    access_level="read",
                    tool="articulo_compra_consultar",
                    arguments={"articulo": articulo},
                    requires=("articulo",),
                    description="Consulta proveedores/ficha de compra del articulo.",
                ),
                TestCase(
                    name="read_precio_oferta_admin",
                    group="read-admin",
                    profile="admin",
                    access_level="read",
                    tool="articulo_precio_oferta",
                    arguments={"articulo": articulo},
                    requires=("articulo",),
                    description="Consulta PVP de oferta desde perfil admin.",
                ),
            ]
        )

    if cliente is not None:
        cases.extend(
            [
                TestCase(
                    name="read_cliente_ficha",
                    group="read-core",
                    profile="core",
                    access_level="read",
                    tool="cliente_buscar",
                    arguments={"cliente": int(cliente), "subcliente": subcliente},
                    requires=("cliente",),
                    description="Obtiene ficha del cliente descubierto o indicado.",
                ),
                TestCase(
                    name="read_cliente_ultimas_ventas",
                    group="read-core",
                    profile="core",
                    access_level="read",
                    tool="cliente_ultimas_ventas",
                    arguments={"cliente": int(cliente), "subcliente": subcliente},
                    requires=("cliente",),
                    description="Consulta ultimas ventas del cliente.",
                ),
            ]
        )
        if articulo:
            cases.append(
                TestCase(
                    name="read_precio_cliente",
                    group="read-core",
                    profile="core",
                    access_level="read",
                    tool="articulo_precio_cliente",
                    arguments={
                        "articulo": articulo,
                        "cliente": int(cliente),
                        "subcliente": subcliente,
                        "cantidad": "1",
                    },
                    requires=("articulo", "cliente"),
                    description="Calcula precio efectivo para articulo/cliente.",
                )
            )

    if args.include_write_dry_run and articulo:
        cases.append(
            TestCase(
                name="dry_run_cambiar_tabla_precio",
                group="write-dry-run",
                profile="admin",
                access_level="read",
                tool="articulo_cambiar_tabla_precio",
                arguments={"articulo": articulo, "tabla_nueva": 1, "simular": True},
                requires=("articulo",),
                description="Simula cambio de tabla de precio; no aplica cambios.",
            )
        )

    return cases


def required_fixture_missing(case: TestCase, fixtures: dict[str, Any]) -> str:
    for key in case.requires:
        value = fixtures.get(key)
        if value is None or (isinstance(value, str) and value == ""):
            return key
    return ""


async def run_case(args: argparse.Namespace, case: TestCase, fixtures: dict[str, Any]) -> dict[str, Any]:
    missing = required_fixture_missing(case, fixtures)
    started = datetime.now().astimezone()
    if missing:
        return {
            "name": case.name,
            "group": case.group,
            "profile": case.profile,
            "access_level": case.access_level,
            "tool": case.tool,
            "status": "SKIPPED",
            "reason": f"missing fixture: {missing}",
            "started_at": started.isoformat(timespec="seconds"),
            "duration_ms": 0,
            "arguments": case.arguments,
            "description": case.description,
        }

    before = datetime.now().astimezone()
    try:
        is_error, payload, raw_text = await call_tool(
            args,
            case.profile,
            case.access_level,
            case.tool,
            case.arguments,
        )
    except Exception as exc:  # noqa: BLE001 - test harness must record all failures
        duration_ms = (datetime.now().astimezone() - before).total_seconds() * 1000
        return {
            "name": case.name,
            "group": case.group,
            "profile": case.profile,
            "access_level": case.access_level,
            "tool": case.tool,
            "status": "FAIL",
            "reason": f"client exception: {type(exc).__name__}: {exc}",
            "started_at": before.isoformat(timespec="seconds"),
            "duration_ms": round(duration_ms, 2),
            "arguments": case.arguments,
            "description": case.description,
        }

    duration_ms = (datetime.now().astimezone() - before).total_seconds() * 1000
    ok_field = payload.get("ok") if isinstance(payload, dict) else None
    status = "PASS"
    reason = ""
    if is_error != case.expect_error:
        status = "FAIL"
        reason = f"is_error={is_error}, expected {case.expect_error}"
    elif case.expect_ok_field is not None and ok_field is not case.expect_ok_field:
        status = "FAIL"
        reason = f"ok={ok_field}, expected {case.expect_ok_field}"

    return {
        "name": case.name,
        "group": case.group,
        "profile": case.profile,
        "access_level": case.access_level,
        "tool": case.tool,
        "status": status,
        "reason": reason,
        "is_error": is_error,
        "ok": ok_field,
        "started_at": before.isoformat(timespec="seconds"),
        "duration_ms": round(duration_ms, 2),
        "arguments": case.arguments,
        "response": payload if payload is not None else raw_text,
        "description": case.description,
    }


async def run_contract_checks(args: argparse.Namespace) -> list[dict[str, Any]]:
    expected_counts = {"core": 38, "admin": 46, "integrations": 39, "all": 47, "full": 47}
    rows = []
    for profile, expected_count in expected_counts.items():
        before = datetime.now().astimezone()
        try:
            names = await list_tools(args, profile, "read")
            status = "PASS" if len(names) == expected_count else "FAIL"
            reason = "" if status == "PASS" else f"count={len(names)}, expected {expected_count}"
        except Exception as exc:  # noqa: BLE001
            names = []
            status = "FAIL"
            reason = f"client exception: {type(exc).__name__}: {exc}"
        duration_ms = (datetime.now().astimezone() - before).total_seconds() * 1000
        rows.append(
            {
                "name": f"contract_profile_{profile}",
                "group": "contract",
                "profile": profile,
                "access_level": "read",
                "tool": "tools/list",
                "status": status,
                "reason": reason,
                "expected_count": expected_count,
                "actual_count": len(names),
                "tools": names,
                "started_at": before.isoformat(timespec="seconds"),
                "duration_ms": round(duration_ms, 2),
            }
        )

    direct_counts = {
        profile: len(faro_mcp.tool_definitions(profile))
        for profile in ["core", "admin", "integrations", "all", "full"]
    }
    rows.append(
        {
            "name": "contract_direct_runtime_counts",
            "group": "contract",
            "profile": "all",
            "access_level": "read",
            "tool": "tool_definitions",
            "status": "PASS" if direct_counts == expected_counts else "FAIL",
            "reason": "" if direct_counts == expected_counts else f"counts={direct_counts}",
            "expected_count": expected_counts,
            "actual_count": direct_counts,
            "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "duration_ms": 0,
        }
    )
    return rows


def write_outputs(args: argparse.Namespace, report: dict[str, Any]) -> tuple[Path, Path]:
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = args.out_dir / f"mcp-function-tests-{stamp}.json"
    csv_path = args.out_dir / f"mcp-function-tests-{stamp}.csv"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    rows = report["results"]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "status",
                "name",
                "group",
                "profile",
                "access_level",
                "tool",
                "duration_ms",
                "reason",
                "description",
            ],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)
    return json_path, csv_path


async def main_async() -> int:
    args = parse_args()
    started = datetime.now().astimezone()

    fixtures = await discover_fixtures(args)
    results = await run_contract_checks(args)
    cases = build_cases(args, fixtures)
    for case in cases:
        results.append(await run_case(args, case, fixtures))

    summary = {
        "PASS": sum(1 for row in results if row["status"] == "PASS"),
        "FAIL": sum(1 for row in results if row["status"] == "FAIL"),
        "SKIPPED": sum(1 for row in results if row["status"] == "SKIPPED"),
    }
    report = {
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "server": str(args.server),
        "dsn": args.dsn,
        "empresa": args.empresa,
        "centro": args.centro,
        "fixtures": fixtures,
        "summary": summary,
        "results": results,
    }
    json_path, csv_path = write_outputs(args, report)

    print(f"Summary: PASS={summary['PASS']} FAIL={summary['FAIL']} SKIPPED={summary['SKIPPED']}")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    for row in results:
        marker = row["status"]
        reason = f" - {row['reason']}" if row.get("reason") else ""
        print(f"{marker:7} {row['group']:14} {row['tool']:28} {row['name']}{reason}")

    return 1 if summary["FAIL"] else 0


def main() -> None:
    raise SystemExit(anyio.run(main_async))


if __name__ == "__main__":
    main()
