from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from faro_mcp import FaroDb, FaroError, Settings  # noqa: E402


DEFAULT_SOURCE_EMPRESA = 1

MOVEMENT_TABLES = {
    "ACTIVI",
    "CABDOCM",
    "CABDOCR",
    "CABDOCV",
    "CABDOCVE",
    "CABORC",
    "CHEQUES",
    "CUEREM",
    "DETCAT",
    "DETCHE",
    "DETMOV",
    "DETMOVM",
    "DETMOVMC",
    "DETMOVR",
    "DETOFER",
    "DETORC",
    "DEVOLUCION",
    "DOCUMENTO",
    "ENVCOC",
    "ENVIOS",
    "ETIQUE",
    "FALTAS",
    "HORAS",
    "INCIDEN",
    "OFERTAS",
    "OPECAJ",
    "RECUENTO",
    "REGFAC",
    "REMESA",
    "STOCKS",
    "TAREAS",
}

MASTER_PREFIXES = (
    "ARTICUL",
    "ARTCAR",
    "ARTCOI",
    "ARTPESO",
    "ARTREL",
    "ARTUBI",
    "ARTWEB",
    "ARTZON",
    "CLI",
    "PRO",
)

AUDIT_PREFIXES = ("ELIM", "LOG", "AUD")

DEFAULT_CONFIG_TABLES = {
    "AGRUP1",
    "AGRUP2",
    "AGRUP3",
    "BANCOS",
    "CAJAS",
    "CENTROS",
    "EMPRES",
    "FAMILI",
    "FAMNCC",
    "FORENV",
    "FORPAG",
    "FORPAGA",
    "GRUPOMENU",
    "GRUPUSU",
    "GRUPUSU2",
    "MEDIDAS",
    "NUMERA",
    "PARAMETROS",
    "SSUBFAM",
    "SUBFAM",
    "TABPREC",
    "TARJET",
    "TIPACT",
    "TIPDOC",
    "TIPIVA",
    "TIPVEN",
    "USUAR",
    "USUAR2",
    "ZONAS",
}

EMPRES_OVERRIDES = {
    "nombre_comercial": "EMP_NOMEMP",
    "nombre_fiscal": "EMP_NOMFIS",
    "cif": "EMP_CIF",
    "domicilio1": "EMP_DOMFIS1",
    "domicilio2": "EMP_DOMFIS2",
    "codigo_postal": "EMP_CODPOS",
    "poblacion": "EMP_POBLAC",
    "email": "EMP_EMAIL",
    "regiva": "EMP_REGIVA",
    "codsoc": "EMP_CODSOC",
    "ejeeur": "EMP_EJEEUR",
}


@dataclass(frozen=True)
class CompanyTable:
    name: str
    company_column: str
    columns: tuple[str, ...]
    source_rows: int
    target_rows: int


def q(name: str) -> str:
    normalized = name.strip().upper()
    if not normalized.replace("_", "").isalnum():
        raise FaroError(f"Identificador no valido: {name!r}")
    return normalized


def fetch_company_tables(db: FaroDb, source: int, target: int) -> list[CompanyTable]:
    rows = db.fetch_all(
        """
        SELECT
            TRIM(rf.RDB$RELATION_NAME) AS TABLE_NAME,
            TRIM(rf.RDB$FIELD_NAME) AS FIELD_NAME
        FROM RDB$RELATION_FIELDS rf
        JOIN RDB$RELATIONS r ON r.RDB$RELATION_NAME = rf.RDB$RELATION_NAME
        WHERE COALESCE(r.RDB$SYSTEM_FLAG, 0) = 0
          AND r.RDB$VIEW_BLR IS NULL
          AND (
              UPPER(TRIM(rf.RDB$FIELD_NAME)) = 'EMPRESA'
              OR UPPER(TRIM(rf.RDB$FIELD_NAME)) LIKE '%NUMEMP'
          )
        ORDER BY rf.RDB$RELATION_NAME
        """
    )
    result: list[CompanyTable] = []
    for row in rows:
        table = q(str(row["TABLE_NAME"]))
        company_column = q(str(row["FIELD_NAME"]))
        columns = get_columns(db, table)
        source_rows = count_rows(db, table, company_column, source)
        target_rows = count_rows(db, table, company_column, target)
        result.append(CompanyTable(table, company_column, columns, source_rows, target_rows))
    return result


def get_columns(db: FaroDb, table: str) -> tuple[str, ...]:
    rows = db.fetch_all(
        """
        SELECT TRIM(RDB$FIELD_NAME) AS FIELD_NAME
        FROM RDB$RELATION_FIELDS
        WHERE RDB$RELATION_NAME = ?
        ORDER BY RDB$FIELD_POSITION
        """,
        (table,),
    )
    return tuple(q(str(row["FIELD_NAME"])) for row in rows)


def count_rows(db: FaroDb, table: str, company_column: str, empresa: int) -> int:
    row = db.fetch_one(
        f"SELECT COUNT(*) AS N FROM {q(table)} WHERE {q(company_column)}=?",
        (empresa,),
    )
    return int(row["N"] if row else 0)


def default_excluded(table: str) -> bool:
    table = q(table)
    if table in DEFAULT_CONFIG_TABLES:
        return False
    if table in MOVEMENT_TABLES:
        return True
    if table.startswith(AUDIT_PREFIXES):
        return True
    if table.startswith(MASTER_PREFIXES):
        return True
    return False


def select_tables(
    tables: list[CompanyTable],
    includes: set[str],
    excludes: set[str],
    all_company_tables: bool,
) -> list[CompanyTable]:
    selected = []
    for table in tables:
        if table.name in excludes:
            continue
        if includes and table.name not in includes:
            continue
        if not includes and not all_company_tables:
            if table.name not in DEFAULT_CONFIG_TABLES:
                continue
            if default_excluded(table.name):
                continue
        selected.append(table)
    return selected


def empres_overrides(args: argparse.Namespace) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for attr, column in EMPRES_OVERRIDES.items():
        value = getattr(args, attr)
        if value is not None:
            values[column] = value
    return values


def centros_overrides(args: argparse.Namespace) -> dict[str, Any]:
    name = args.nombre_comercial or args.nombre_fiscal
    if not name:
        return {}
    return {"CEN_NOMCEN": name}


def copy_table(
    db: FaroDb,
    table: CompanyTable,
    source: int,
    target: int,
    overrides: dict[str, dict[str, Any]],
    batch_size: int,
) -> int:
    columns = table.columns
    placeholders = ", ".join("?" for _ in columns)
    sql = f"INSERT INTO {table.name} ({', '.join(columns)}) VALUES ({placeholders})"
    read_cur = db.conn.cursor()
    write_cur = db.conn.cursor()
    inserted = 0
    try:
        read_cur.execute(
            f"SELECT {', '.join(columns)} FROM {table.name} WHERE {table.company_column}=?",
            (source,),
        )
        rows = read_cur.fetchmany(batch_size)
        while rows:
            params_batch = []
            for row in rows:
                data = {columns[i]: row[i] for i in range(len(columns))}
                data[table.company_column] = target
                data.update(overrides.get(table.name, {}))
                params_batch.append(tuple(data[column] for column in columns))
            write_cur.executemany(sql, params_batch)
            inserted += len(params_batch)
            rows = read_cur.fetchmany(batch_size)
    finally:
        write_cur.close()
        read_cur.close()
    return inserted


def export_plan(path: Path, tables: list[CompanyTable], selected: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(["tabla", "campo_empresa", "filas_origen", "filas_destino", "seleccionada"])
        for table in tables:
            writer.writerow(
                [
                    table.name,
                    table.company_column,
                    table.source_rows,
                    table.target_rows,
                    "S" if table.name in selected else "N",
                ]
            )


def parse_names(values: list[str]) -> set[str]:
    names: set[str] = set()
    for value in values:
        for part in value.split(","):
            clean = part.strip()
            if clean:
                names.add(q(clean))
    return names


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Replica tablas auxiliares/de configuracion de una empresa Faro a otra. "
            "Por defecto solo simula; use --execute para escribir."
        )
    )
    parser.add_argument("--source-empresa", type=int, default=DEFAULT_SOURCE_EMPRESA)
    parser.add_argument("--target-empresa", type=int, required=True)
    parser.add_argument("--execute", action="store_true", help="Escribe cambios. Sin esto solo muestra el plan.")
    parser.add_argument("--allow-target-data", action="store_true", help="Permite insertar aunque la empresa destino ya tenga filas en alguna tabla seleccionada.")
    parser.add_argument("--all-company-tables", action="store_true", help="Incluye todas las tablas con campo empresa, tambien maestras/movimientos.")
    parser.add_argument("--include", action="append", default=[], help="Lista de tablas a incluir, separadas por coma. Si se indica, solo replica esas tablas.")
    parser.add_argument("--exclude", action="append", default=[], help="Lista adicional de tablas a excluir, separadas por coma.")
    parser.add_argument("--plan-csv", type=Path, help="Guarda el plan completo en CSV.")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--nombre-comercial")
    parser.add_argument("--nombre-fiscal")
    parser.add_argument("--cif")
    parser.add_argument("--domicilio1")
    parser.add_argument("--domicilio2")
    parser.add_argument("--codigo-postal", dest="codigo_postal")
    parser.add_argument("--poblacion")
    parser.add_argument("--email")
    parser.add_argument("--regiva")
    parser.add_argument("--codsoc")
    parser.add_argument("--ejeeur", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.source_empresa == args.target_empresa:
        parser.error("La empresa origen y destino deben ser distintas.")
    includes = parse_names(args.include)
    excludes = parse_names(args.exclude)
    db = FaroDb(Settings.from_env())
    try:
        tables = fetch_company_tables(db, args.source_empresa, args.target_empresa)
        selected = select_tables(tables, includes, excludes, args.all_company_tables)
        selected_names = {table.name for table in selected}
        if args.plan_csv:
            export_plan(args.plan_csv, tables, selected_names)
        blocked = [table for table in selected if table.target_rows and not args.allow_target_data]
        print(f"Empresa origen: {args.source_empresa}")
        print(f"Empresa destino: {args.target_empresa}")
        print(f"Tablas con campo empresa: {len(tables)}")
        print(f"Tablas seleccionadas: {len(selected)}")
        print(f"Filas a copiar: {sum(table.source_rows for table in selected)}")
        if blocked:
            print("ERROR: la empresa destino ya tiene datos en estas tablas seleccionadas:")
            for table in blocked:
                print(f"  - {table.name}: {table.target_rows} filas")
            print("Use --allow-target-data si quiere insertar igualmente.")
            return 2
        if not args.execute:
            print("Modo simulacion. No se ha escrito nada.")
            for table in selected:
                print(f"  - {table.name}.{table.company_column}: {table.source_rows} filas")
            return 0
        overrides = {
            "EMPRES": empres_overrides(args),
            "CENTROS": centros_overrides(args),
        }
        inserted_total = 0
        try:
            for table in selected:
                inserted = copy_table(
                    db,
                    table,
                    args.source_empresa,
                    args.target_empresa,
                    overrides,
                    max(1, args.batch_size),
                )
                inserted_total += inserted
                print(f"{table.name}: {inserted} filas insertadas")
            db.commit()
        except Exception:
            db.rollback()
            raise
        print(f"Replica completada. Filas insertadas: {inserted_total}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
