"""Servidor web local para probar las herramientas del MCP Faro a mano.

Levanta una pagina en tu navegador con la lista de todas las funciones
del servidor MCP (las mismas que veria Claude), un formulario generado
automaticamente a partir del esquema de cada una, y el resultado JSON
que devuelve. Usa exactamente la misma logica de negocio, permisos y
auditoria que el servidor MCP real: llama directamente a
``faro_mcp.FaroToolRuntime.invoke_tool(...)``, sin pasar por el
protocolo MCP ni por ningun cliente de IA. No hace falta terminal para
ir probando funciones: se prueban a golpe de clic desde el navegador.

Uso (desde la carpeta MCP, con el mismo entorno que usas siempre):
    .venv\\Scripts\\python.exe scripts\\mcp_tester_web.py
    .venv\\Scripts\\python.exe scripts\\mcp_tester_web.py --port 8901
    .venv\\Scripts\\python.exe scripts\\mcp_tester_web.py --perfil full
    .venv\\Scripts\\python.exe scripts\\mcp_tester_web.py --centro 2

Se abre solo en tu navegador. Para pararlo, Ctrl+C en la ventana donde
lo lanzaste.

Variables de entorno (mismos valores por defecto que el resto del
proyecto; los flags de arriba las sobreescriben si los usas):
    FARO_ODBC_DSN, FARO_DB_USER, FARO_DB_PASSWORD, FARO_EMPRESA,
    FARO_CENTRO, FARO_USUARIO, FARO_MCP_TOOL_PROFILE

Importante: esta pagina habla con tu base de datos Faro real (el
mismo DSN que usa el servidor MCP). Las operaciones marcadas como
"ESCRITURA" modifican datos de verdad; la pagina pide una confirmacion
extra antes de ejecutarlas, pero esa confirmacion es solo una ayuda de
la interfaz -- el control de permisos real lo sigue haciendo el propio
backend (FARO_MCP_ACCESS_LEVEL / seguridad del runtime).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import faro_mcp  # noqa: E402

# Ficha empresa/centro/usuario guardados desde el icono de ajustes de la
# pagina, para que sigan aplicados la proxima vez que se arranque el
# probador (con un .bat o a mano) sin tener que volver a escribirlos.
SETTINGS_PATH = ROOT / "mcp_tester_settings.json"
PERSISTABLE_ENV_VARS = {"FARO_EMPRESA", "FARO_CENTRO", "FARO_USUARIO"}


def load_persisted_settings() -> dict:
    try:
        raw = SETTINGS_PATH.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if k in PERSISTABLE_ENV_VARS}


def save_persisted_settings(updates: dict) -> None:
    """Fusiona ``updates`` (nombres de variable de entorno -> valor) con lo
    ya guardado en disco y lo escribe de nuevo. No lanza si falla la
    escritura: quien llama decide como avisar."""
    current = load_persisted_settings()
    current.update({k: str(v) for k, v in updates.items() if k in PERSISTABLE_ENV_VARS})
    SETTINGS_PATH.write_text(
        json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interfaz web local para probar las herramientas del MCP Faro.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--host", default="127.0.0.1", help="Interfaz de red donde escuchar (por defecto solo esta maquina).")
    parser.add_argument("--port", type=int, default=8765, help="Puerto donde escuchar (por defecto 8765).")
    parser.add_argument("--perfil", choices=["core", "full"], default=None, help="Sobreescribe FARO_MCP_TOOL_PROFILE.")
    parser.add_argument("--dsn", default=None, help="Sobreescribe FARO_ODBC_DSN.")
    parser.add_argument("--db-user", default=None, help="Sobreescribe FARO_DB_USER.")
    parser.add_argument("--db-password", default=None, help="Sobreescribe FARO_DB_PASSWORD.")
    parser.add_argument("--empresa", default=None, help="Sobreescribe FARO_EMPRESA.")
    parser.add_argument("--centro", default=None, help="Sobreescribe FARO_CENTRO.")
    parser.add_argument("--usuario", default=None, help="Sobreescribe FARO_USUARIO (nombre para la auditoria).")
    parser.add_argument("--no-abrir-navegador", action="store_true", help="No abrir el navegador automaticamente.")
    return parser.parse_args()


def apply_env_overrides(args: argparse.Namespace) -> None:
    mapping = {
        "dsn": "FARO_ODBC_DSN",
        "db_user": "FARO_DB_USER",
        "db_password": "FARO_DB_PASSWORD",
        "empresa": "FARO_EMPRESA",
        "centro": "FARO_CENTRO",
        "usuario": "FARO_USUARIO",
        "perfil": "FARO_MCP_TOOL_PROFILE",
    }
    for attr, env_name in mapping.items():
        value = getattr(args, attr)
        if value is not None:
            os.environ[env_name] = str(value)
    # Un flag de arranque o una variable de entorno ya puesta antes de lanzar
    # el script siguen ganando siempre; lo guardado desde el icono de
    # ajustes solo rellena lo que no se haya indicado explicitamente.
    for env_name, value in load_persisted_settings().items():
        os.environ.setdefault(env_name, value)
    os.environ.setdefault("FARO_DB_DRIVER", "odbc")
    os.environ.setdefault("FARO_ODBC_DSN", "faro")
    os.environ.setdefault("FARO_DB_USER", "SYSDBA")
    os.environ.setdefault("FARO_DB_PASSWORD", "masterkey")
    os.environ.setdefault("FARO_EMPRESA", "1")
    os.environ.setdefault("FARO_CENTRO", "0")
    os.environ.setdefault("FARO_USUARIO", "probador-web")


_CONFIGURABLE_ENV_VARS = {
    "empresa": "FARO_EMPRESA",
    "centro": "FARO_CENTRO",
    "usuario": "FARO_USUARIO",
}


def _help_group_prefix(name: str) -> str:
    """Mismo criterio de agrupacion que usa la barra lateral del probador
    (prefijo hasta el primer '_'), para que la pagina de ayuda organice las
    herramientas exactamente igual que la lista de la izquierda."""
    idx = name.find("_")
    return name[:idx] if idx != -1 else name


# Mismas etiquetas descriptivas que GROUP_LABELS en el JS de la barra
# lateral (ver renderList), para que /ayuda muestre el mismo nombre de grupo.
_HELP_GROUP_LABELS = {
    "orden": "Ordenes de Compra",
    "venta": "Ventas / rentabilidad",
}


def _help_group_label(group: str) -> str:
    return _HELP_GROUP_LABELS.get(group, group.upper())


def _help_tool_risk(name: str) -> str:
    if name in faro_mcp.READ_ONLY_TOOL_NAMES:
        return "lectura"
    if name in faro_mcp.WRITE_TOOL_NAMES:
        return "escritura"
    if name in faro_mcp.CRITICAL_TOOL_NAMES:
        return "critica"
    return "?"


def _help_tool_min_profile(name: str) -> str:
    """Perfil mas restrictivo en el que ya aparece la herramienta."""
    for profile in ("core", "integrations", "admin", "all"):
        if name in faro_mcp.public_tool_names_for_profile(profile):
            return profile
    return "all"


def _help_escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _help_param_rows(schema: dict) -> str:
    props = (schema or {}).get("properties") or {}
    required = set((schema or {}).get("required") or [])
    if not props:
        return '<tr><td colspan="4" class="help-empty">Sin parametros.</td></tr>'
    rows = []
    for pname, pschema in props.items():
        ptype = pschema.get("type", "")
        if isinstance(ptype, list):
            ptype = " | ".join(ptype)
        pdesc = pschema.get("description", "") or ""
        if "enum" in pschema:
            pdesc = (pdesc + " " if pdesc else "") + "Valores: " + ", ".join(str(v) for v in pschema["enum"]) + "."
        rows.append(
            "<tr><td class=\"help-param-name\">{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                _help_escape(pname),
                _help_escape(ptype),
                "si" if pname in required else "no",
                _help_escape(pdesc),
            )
        )
    return "\n".join(rows)


def build_help_html(current_profile: str) -> str:
    """Genera la pagina /ayuda al vuelo a partir de faro_mcp.tool_definitions,
    con el catalogo publico completo (perfil 'all'), para documentar todas
    las funciones exista o no en el perfil con el que arranco el probador."""
    defs = {d["name"]: d for d in faro_mcp.tool_definitions("all")}
    groups: dict[str, list[str]] = {}
    for name in defs:
        groups.setdefault(_help_group_prefix(name), []).append(name)

    toc_items = []
    body_sections = []
    for group in sorted(groups):
        anchor = "grupo-" + group
        toc_items.append(f'<a href="#{anchor}">{_help_escape(_help_group_label(group))}</a>')
        tool_blocks = []
        for name in sorted(groups[group]):
            item = defs[name]
            risk = _help_tool_risk(name)
            profile = _help_tool_min_profile(name)
            tool_blocks.append(
                """
                <article class="help-tool" id="tool-{anchor_id}">
                  <h3>{name} <span class="help-pill help-risk-{risk}">{risk}</span>
                    <span class="help-pill help-profile">{profile}</span></h3>
                  <p class="help-desc">{desc}</p>
                  <table class="help-params">
                    <thead><tr><th>Parametro</th><th>Tipo</th><th>Obligatorio</th><th>Descripcion</th></tr></thead>
                    <tbody>{rows}</tbody>
                  </table>
                </article>
                """.format(
                    anchor_id=_help_escape(name),
                    name=_help_escape(name),
                    risk=risk,
                    profile=profile,
                    desc=_help_escape(item.get("description", "")),
                    rows=_help_param_rows(item.get("inputSchema") or {}),
                )
            )
        body_sections.append(
            f'<section class="help-group" id="{anchor}"><h2>{_help_escape(_help_group_label(group))}'
            f' <span class="help-count">{len(groups[group])}</span></h2>{"".join(tool_blocks)}</section>'
        )

    core_n = len(faro_mcp.public_tool_names_for_profile("core"))
    admin_n = len(faro_mcp.public_tool_names_for_profile("admin"))
    integ_n = len(faro_mcp.public_tool_names_for_profile("integrations"))
    all_n = len(defs)

    return """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ayuda - MCP Faro</title>
<style>
  :root {{ --accent:#2563eb; --accent-weak:#eaf1ff; --border:#e2e8f0; --muted:#64748b; --text:#0f172a; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif; color:var(--text); background:#f8fafc; }}
  header {{ position: sticky; top: 0; background:#fff; border-bottom:1px solid var(--border); padding:16px 24px; z-index: 5; }}
  header h1 {{ margin:0 0 4px; font-size:20px; }}
  header p {{ margin:0; color:var(--muted); font-size:13px; }}
  main {{ max-width: 980px; margin: 0 auto; padding: 24px; }}
  nav.help-toc {{ display:flex; flex-wrap:wrap; gap:8px; margin-bottom: 24px; }}
  nav.help-toc a {{ font-size:12px; font-weight:600; color:var(--accent); background:var(--accent-weak); border:1px solid #cfe0ff; border-radius:999px; padding:5px 12px; text-decoration:none; }}
  nav.help-toc a:hover {{ background:var(--accent); color:#fff; }}
  section.help-group {{ margin-bottom: 32px; }}
  section.help-group h2 {{ font-size:16px; border-bottom:2px solid var(--border); padding-bottom:6px; }}
  .help-count {{ font-weight:400; color:var(--muted); font-size:12px; }}
  article.help-tool {{ background:#fff; border:1px solid var(--border); border-radius:10px; padding:14px 16px; margin:12px 0; }}
  article.help-tool h3 {{ margin:0 0 6px; font-size:14px; font-family: ui-monospace, Consolas, monospace; }}
  .help-desc {{ margin: 0 0 10px; font-size:13px; color:#334155; }}
  .help-pill {{ display:inline-block; font-family: -apple-system, sans-serif; font-size:10px; font-weight:700; text-transform:uppercase; padding:2px 8px; border-radius:999px; margin-left:6px; vertical-align:middle; }}
  .help-risk-lectura {{ background:#e0f2fe; color:#0369a1; }}
  .help-risk-escritura {{ background:#fef3c7; color:#92400e; }}
  .help-risk-critica {{ background:#fee2e2; color:#b91c1c; }}
  .help-profile {{ background:#ede9fe; color:#5b21b6; }}
  table.help-params {{ width:100%; border-collapse: collapse; font-size:12px; }}
  table.help-params th {{ text-align:left; background:#f1f5f9; padding:6px 8px; border-bottom:1px solid var(--border); }}
  table.help-params td {{ padding:6px 8px; border-bottom:1px solid #eef2f7; vertical-align:top; }}
  .help-param-name {{ font-family: ui-monospace, Consolas, monospace; white-space:nowrap; }}
  .help-empty {{ color:var(--muted); font-style: italic; }}
  .help-back {{ display:inline-block; margin-bottom:16px; font-size:13px; color:var(--accent); text-decoration:none; }}
</style>
</head>
<body>
<header>
  <h1>Ayuda - MCP Faro</h1>
  <p>Generado en el momento desde faro_mcp.tool_definitions() &middot; servidor v{server_version} &middot; perfil activo del probador: <strong>{current_profile}</strong> &middot; catalogo completo (perfil "all"): <strong>{all_n}</strong> herramientas &middot; core {core_n} / admin {admin_n} / integrations {integ_n} / all {all_n}</p>
</header>
<main>
  <a class="help-back" href="/">&larr; Volver al probador</a>
  <nav class="help-toc">{toc}</nav>
  {sections}
</main>
</body>
</html>
""".format(
        server_version=_help_escape(faro_mcp.SERVER_VERSION),
        current_profile=_help_escape(current_profile),
        core_n=core_n, admin_n=admin_n, integ_n=integ_n, all_n=all_n,
        toc="".join(toc_items),
        sections="".join(body_sections),
    )


def make_handler(initial_runtime: "faro_mcp.FaroToolRuntime"):
    # El runtime se guarda en un dict (en vez de una variable normal) para
    # poder sustituirlo desde /api/config sin tener que reiniciar el proceso
    # ni el servidor HTTP: cada peticion vuelve a leer state["runtime"].
    state = {"runtime": initial_runtime}
    config_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        server_version = "FaroMCPTester/1.0"

        def log_message(self, fmt, *log_args):  # noqa: A002
            sys.stderr.write("[web] " + (fmt % log_args) + "\n")

        def _send_json(self, status: int, payload) -> None:
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _info_payload(self) -> dict:
            runtime = state["runtime"]
            return {
                "dsn": os.environ.get("FARO_ODBC_DSN", ""),
                "db_driver": os.environ.get("FARO_DB_DRIVER", ""),
                "empresa": os.environ.get("FARO_EMPRESA", ""),
                "centro": os.environ.get("FARO_CENTRO", ""),
                "usuario": os.environ.get("FARO_USUARIO", ""),
                "profile": runtime.tool_profile,
                "server_version": faro_mcp.SERVER_VERSION,
            }

        def _read_json_body(self):
            length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(length) if length else b"{}"
            return json.loads(raw.decode("utf-8") or "{}")

        def do_GET(self) -> None:  # noqa: N802
            runtime = state["runtime"]
            if self.path in ("/", "/index.html"):
                self._send_html(PAGE_HTML)
                return
            if self.path in ("/ayuda", "/ayuda/", "/help", "/help/"):
                try:
                    html = build_help_html(runtime.tool_profile)
                except Exception as exc:
                    self._send_html(f"<pre>No se pudo generar la ayuda: {_help_escape(exc)}</pre>")
                    return
                self._send_html(html)
                return
            if self.path.startswith("/api/tools"):
                try:
                    defs = faro_mcp.tool_definitions(runtime.tool_profile)
                except Exception as exc:
                    self._send_json(500, {"error": str(exc)})
                    return
                self._send_json(200, {
                    "profile": runtime.tool_profile,
                    "server_version": faro_mcp.SERVER_VERSION,
                    "tool_count": len(defs),
                    "tools": defs,
                })
                return
            if self.path.startswith("/api/info"):
                self._send_json(200, self._info_payload())
                return
            self._send_json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path == "/api/config":
                try:
                    body = self._read_json_body()
                except Exception as exc:
                    self._send_json(400, {"error": f"JSON invalido en la peticion: {exc}"})
                    return
                if not isinstance(body, dict):
                    self._send_json(400, {"error": "Se esperaba un objeto JSON"})
                    return
                updates = {}
                for public_name, env_name in _CONFIGURABLE_ENV_VARS.items():
                    if public_name not in body:
                        continue
                    raw_value = body[public_name]
                    text_value = "" if raw_value is None else str(raw_value).strip()
                    if text_value == "":
                        self._send_json(400, {"error": f"{public_name} no puede quedar vacio"})
                        return
                    updates[env_name] = text_value
                if not updates:
                    self._send_json(400, {"error": "Indica al menos empresa, centro o usuario"})
                    return
                with config_lock:
                    previous = {env_name: os.environ.get(env_name) for env_name in updates}
                    os.environ.update(updates)
                    try:
                        state["runtime"] = faro_mcp.FaroToolRuntime()
                    except Exception as exc:
                        # Los valores nuevos no son validos (p.ej. empresa no
                        # numerica): se revierte para no dejar el probador
                        # con una configuracion rota a medias.
                        for env_name, old_value in previous.items():
                            if old_value is None:
                                os.environ.pop(env_name, None)
                            else:
                                os.environ[env_name] = old_value
                        self._send_json(400, {"error": f"No se pudo aplicar la configuracion: {exc}"})
                        return
                    payload = self._info_payload()
                    try:
                        save_persisted_settings(updates)
                    except OSError as exc:
                        # La configuracion ya esta aplicada para esta sesion;
                        # si no se pudo escribir a disco solo se avisa, no se
                        # deshace el cambio en memoria por eso.
                        payload["persist_warning"] = (
                            f"Aplicado para esta sesion, pero no se pudo guardar en {SETTINGS_PATH.name}: {exc}"
                        )
                self._send_json(200, payload)
                return
            if self.path != "/api/call":
                self._send_json(404, {"error": "not found"})
                return
            runtime = state["runtime"]
            try:
                body = self._read_json_body()
            except Exception as exc:
                self._send_json(400, {"error": f"JSON invalido en la peticion: {exc}"})
                return
            name = str(body.get("name") or "")
            arguments = body.get("arguments")
            if not isinstance(arguments, dict):
                arguments = {}
            started = time.perf_counter()
            try:
                result, is_error = runtime.invoke_tool(name, arguments)
            except Exception as exc:
                self._send_json(200, {
                    "result": {"ok": False, "error": {"code": "EXCEPCION_SERVIDOR", "message": str(exc)}},
                    "is_error": True,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                    "traceback": traceback.format_exc(),
                })
                return
            self._send_json(200, {
                "result": result,
                "is_error": is_error,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            })

    return Handler


PAGE_HTML = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Probador MCP Faro</title>
<style>
  :root {
    color-scheme: light;
    --bg: #edf2f7;
    --panel: #ffffff;
    --panel-soft: #f8fafc;
    --panel-tint: #f1f7ff;
    --border: #d6dce5;
    --text: #18202a;
    --muted: #687280;
    --accent: #2563eb;
    --accent-2: #0891b2;
    --accent-3: #16a34a;
    --accent-weak: #e8f1ff;
    --accent-border: #b9d0ff;
    --ok: #147a46;
    --ok-bg: #e2f6ea;
    --err: #bf2432;
    --err-bg: #ffeaec;
    --write: #966300;
    --write-bg: #fff4cc;
    --shadow: 0 18px 42px rgba(15, 23, 42, .10);
    --mono: "Consolas", "SFMono-Regular", Menlo, monospace;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
    background:
      radial-gradient(circle at 12% 8%, rgba(37, 99, 235, .16), transparent 28%),
      radial-gradient(circle at 88% 2%, rgba(8, 145, 178, .14), transparent 26%),
      linear-gradient(180deg, rgba(255,255,255,.76), rgba(255,255,255,0) 260px),
      var(--bg);
    color: var(--text);
    height: 100vh;
    display: flex;
    flex-direction: column;
  }
  header {
    padding: 12px 18px;
    background: linear-gradient(90deg, rgba(255,255,255,.94), rgba(241,247,255,.9));
    border-bottom: 1px solid var(--border);
    box-shadow: 0 1px 0 rgba(255,255,255,.7) inset;
    display: flex;
    align-items: center;
    gap: 16px;
    flex-wrap: wrap;
  }
  header h1 {
    font-size: 17px;
    margin: 0;
    font-weight: 800;
    color: #0f172a;
  }
  header .info { font-size: 12px; color: var(--muted); font-family: var(--mono); }
  header .badge {
    font-size: 11px;
    padding: 4px 9px;
    border-radius: 999px;
    background: var(--accent-weak);
    color: var(--accent);
    font-weight: 600;
    border: 1px solid var(--accent-border);
  }
  .help-link {
    margin-left: auto;
    font-size: 12px;
    font-weight: 700;
    color: var(--accent);
    text-decoration: none;
    padding: 5px 12px;
    border-radius: 999px;
    background: var(--accent-weak);
    border: 1px solid var(--accent-border);
  }
  .help-link:hover { background: var(--accent); color: #fff; }
  .settings-btn {
    width: 30px;
    height: 30px;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: #ffffff;
    color: #475569;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    flex: none;
  }
  .settings-btn:hover { background: var(--accent-weak); color: var(--accent); border-color: var(--accent-border); }
  .settings-btn svg { width: 18px; height: 18px; }
  .modal-backdrop {
    /* display:none por defecto y solo display:flex con .open: un selector
       propio con "display" siempre gana al [hidden] del navegador (son de
       distinto origen en la cascada, no compite por especificidad), asi que
       basarse en el atributo hidden aqui nunca cerraria el modal. */
    position: fixed;
    inset: 0;
    background: rgba(15, 23, 42, .38);
    display: none;
    align-items: center;
    justify-content: center;
    z-index: 50;
    padding: 16px;
  }
  .modal-backdrop.open { display: flex; }
  .modal {
    background: #ffffff;
    border-radius: 10px;
    border: 1px solid var(--border);
    box-shadow: var(--shadow);
    padding: 20px 22px;
    width: 100%;
    max-width: 380px;
  }
  .modal h2 { margin: 0 0 6px; font-size: 16px; }
  .modal-hint { font-size: 12.5px; color: var(--muted); margin: 0 0 14px; line-height: 1.4; }
  .modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 4px; }
  button.modal-cancel {
    background: #ffffff;
    color: var(--muted);
    border: 1px solid var(--border);
    padding: 9px 16px;
    border-radius: 7px;
    font-size: 13px;
    cursor: pointer;
  }
  button.modal-cancel:hover { background: var(--panel-soft); }
  .layout { flex: 1; display: flex; min-height: 0; }
  .sidebar {
    width: 330px;
    min-width: 220px;
    background:
      linear-gradient(180deg, rgba(37, 99, 235, .05), transparent 260px),
      linear-gradient(180deg, #f8fafc 0%, #edf4fb 100%);
    border-right: 1px solid #cbd5e1;
    display: flex;
    flex-direction: column;
    color: #1f2937;
    box-shadow: 12px 0 28px rgba(15, 23, 42, .08);
  }
  .sidebar .search { padding: 12px; border-bottom: 1px solid #d7e0eb; }
  .sidebar .search input {
    width: 100%;
    padding: 9px 11px;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    font-size: 13px;
    background: #ffffff;
    outline: none;
  }
  .sidebar .search input:focus {
    border-color: var(--accent-border);
    box-shadow: 0 0 0 3px rgba(37, 99, 235, .11);
  }
  .tool-list { overflow-y: auto; flex: 1; }
  .group-title {
    width: 100%;
    border: 0;
    background: transparent;
    color: #334155;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 10px 12px 5px;
    font: inherit;
    text-align: left;
  }
  .group-title:hover { background: #e8f1fa; }
  .group-title .group-left {
    display: flex;
    align-items: center;
    min-width: 0;
    gap: 7px;
  }
  .group-title .chevron {
    color: #64748b;
    font-family: var(--mono);
    font-size: 11px;
    width: 12px;
  }
  .group-title .label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: .04em;
    font-weight: 700;
  }
  .branch-icon {
    width: 17px;
    height: 17px;
    color: #2563eb;
    flex: none;
  }
  .group-title .count {
    color: #475569;
    background: #dbe7f3;
    border-radius: 999px;
    font-size: 11px;
    min-width: 22px;
    padding: 1px 7px;
    text-align: center;
  }
  .tool-item {
    margin: 2px 8px;
    padding: 8px 10px 8px 13px;
    cursor: pointer;
    font-size: 13px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 6px;
    border-left: 3px solid transparent;
    border-radius: 7px;
    color: #334155;
  }
  .tool-item:hover { background: #e8f1fa; }
  .tool-item.active {
    background: #ffffff;
    border-left-color: #2563eb;
    color: #0f172a;
    font-weight: 600;
    box-shadow: 0 10px 24px rgba(15, 23, 42, .18);
  }
  .tool-item .tool-name {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .tool-icon {
    width: 24px;
    height: 24px;
    border-radius: 999px;
    flex: none;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: 1px solid currentColor;
    background: #ffffff;
    color: #64748b;
  }
  .tool-icon svg { width: 14px; height: 14px; display: block; }
  .tool-item.active .tool-icon {
    background: #eff6ff;
  }
  .tool-icon.read { color: #0284c7; }
  .tool-icon.write { color: #b45309; }
  .tool-icon.delete { color: #dc2626; }
  .tool-icon.critical { color: #7c3aed; }
  .tag.read { background: #e0f2fe; color: #0369a1; }
  .tag.delete { background: #fee2e2; color: #b91c1c; }
  .tag.critical { background: #ede9fe; color: #6d28d9; }
  .tool-legend {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 6px;
    padding: 0 12px 12px;
    border-bottom: 1px solid #d7e0eb;
  }
  .legend-item {
    color: #475569;
    background: #ffffff;
    border: 1px solid #d7e0eb;
    border-radius: 8px;
    padding: 5px 6px;
    font-size: 11px;
    display: flex;
    align-items: center;
    gap: 5px;
  }
  main {
    flex: 1;
    overflow-y: auto;
    padding: 22px 26px;
    display: flex;
    gap: 20px;
    align-items: flex-start;
  }
  .empty-state { color: var(--muted); padding: 40px; text-align: center; width: 100%; }
  .form-col { flex: 1 1 560px; min-width: 320px; max-width: 900px; }
  .result-col { flex: 1 1 420px; min-width: 320px; }
  .card {
    background: linear-gradient(180deg, #ffffff, #fbfdff);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px 18px;
    margin-bottom: 16px;
    box-shadow: var(--shadow);
    position: relative;
    overflow: hidden;
  }
  .card::before {
    content: "";
    position: absolute;
    inset: 0 0 auto 0;
    height: 3px;
    background: linear-gradient(90deg, var(--accent), var(--accent-2), var(--accent-3));
  }
  .card h2 { margin: 0 0 4px; font-size: 16px; position: relative; }
  .card .desc { font-size: 13px; color: var(--muted); margin-bottom: 12px; line-height: 1.4; }
  .tag {
    display: inline-block;
    font-size: 11px;
    font-weight: 600;
    padding: 2px 7px;
    border-radius: 8px;
    margin-left: 8px;
    vertical-align: middle;
  }
  .tag.write { background: var(--write-bg); color: var(--write); }
  .field { margin-bottom: 10px; }
  .field-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(165px, 1fr));
    gap: 10px 12px;
    align-items: start;
  }
  .field-grid.two-cols {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .field label { display: block; font-size: 13px; font-weight: 600; margin-bottom: 3px; }
  .field label .req { color: var(--err); }
  .field .hint { font-size: 11.5px; color: var(--muted); margin-top: 3px; }
  .field input[type=text], .field input[type=number], .field select, .field textarea {
    width: 100%;
    padding: 8px 9px;
    border: 1px solid var(--border);
    border-radius: 8px;
    font-size: 13px;
    font-family: inherit;
    background: #fff;
    outline: none;
  }
  .field input[type=text]:focus, .field input[type=number]:focus, .field select:focus, .field textarea:focus {
    border-color: var(--accent-border);
    box-shadow: 0 0 0 3px rgba(37, 99, 235, .12);
  }
  .field textarea { font-family: var(--mono); font-size: 12px; min-height: 70px; resize: vertical; }
  .field.json-field textarea { min-height: 90px; }
  @media (max-width: 760px) {
    .field-grid { grid-template-columns: 1fr; }
    .field-grid.two-cols { grid-template-columns: 1fr; }
  }
  .tariff-editor {
    border: 1px solid var(--border);
    border-radius: 10px;
    background: #f8fbff;
    padding: 10px;
    margin-bottom: 12px;
  }
  .tariff-editor-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    margin-bottom: 9px;
    flex-wrap: wrap;
  }
  .tariff-editor-title { font-size: 12px; font-weight: 700; color: #334155; }
  .tariff-editor-count { font-size: 11px; color: var(--muted); margin-left: 6px; }
  button.tariff-add, button.tariff-remove, button.tariff-advanced {
    border: 1px solid var(--accent-border);
    background: #fff;
    color: var(--accent);
    border-radius: 7px;
    padding: 6px 10px;
    font-size: 11.5px;
    font-weight: 650;
    cursor: pointer;
  }
  button.tariff-remove { color: #b91c1c; border-color: #fecaca; }
  button.tariff-advanced { color: #475569; border-color: #cbd5e1; }
  button.tariff-add:hover { background: var(--accent-weak); }
  button.tariff-remove:hover { background: #fff1f2; }
  button.tariff-advanced:hover { background: #f1f5f9; }
  .tariff-lines { display: grid; gap: 10px; }
  .tariff-line-card {
    background: #fff;
    border: 1px solid #d9e2ec;
    border-radius: 9px;
    padding: 10px 11px;
    box-shadow: 0 3px 10px rgba(15,23,42,.04);
  }
  .tariff-line-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 8px;
  }
  .tariff-line-number { font-size: 12px; font-weight: 800; color: #1e3a8a; }
  .tariff-line-actions { display: flex; gap: 6px; }
  .tariff-grid-main {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr .72fr;
    gap: 8px;
  }
  .tariff-grid-secondary {
    display: grid;
    grid-template-columns: 2fr .7fr repeat(6, .55fr);
    gap: 8px;
    margin-top: 8px;
  }
  .tariff-grid-advanced {
    display: grid;
    grid-template-columns: repeat(5, minmax(120px, 1fr));
    gap: 8px;
    margin-top: 9px;
    padding-top: 9px;
    border-top: 1px dashed #cbd5e1;
  }
  .tariff-mini label {
    display: block;
    font-size: 10.5px;
    font-weight: 700;
    color: #64748b;
    margin-bottom: 2px;
  }
  .tariff-mini input {
    width: 100%;
    min-width: 0;
    padding: 6px 7px;
    border: 1px solid var(--border);
    border-radius: 6px;
    font-size: 12px;
    background: #fff;
    outline: none;
  }
  .tariff-mini input:focus {
    border-color: var(--accent-border);
    box-shadow: 0 0 0 2px rgba(37,99,235,.1);
  }
  .tariff-required-note { font-size: 11px; color: var(--muted); line-height: 1.35; }
  .tariff-summary {
    display: grid;
    grid-template-columns: repeat(4, minmax(105px, 1fr));
    gap: 8px;
    margin: 8px 0 10px;
  }
  .tariff-summary-item {
    border: 1px solid var(--border);
    background: #fff;
    border-radius: 8px;
    padding: 8px 10px;
  }
  .tariff-summary-item strong { display:block; font-size:16px; color:#0f172a; }
  .tariff-summary-item span { font-size:10.5px; color:var(--muted); text-transform:uppercase; letter-spacing:.03em; }
  @media (max-width: 1100px) {
    .tariff-grid-main { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .tariff-grid-secondary { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .tariff-grid-advanced { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }
  @media (max-width: 700px) {
    .tariff-grid-main, .tariff-grid-secondary, .tariff-grid-advanced { grid-template-columns: 1fr; }
    .tariff-summary { grid-template-columns: repeat(2, minmax(0,1fr)); }
  }
  .sample-write-note {
    background: var(--write-bg);
    border: 1px solid #e3c66b;
    border-radius: 8px;
    padding: 8px 11px;
    font-size: 12px;
    line-height: 1.4;
    color: #6b4c00;
    margin-bottom: 12px;
  }
  .confirm-write {
    background: var(--write-bg);
    border: 1px solid #e3c66b;
    border-radius: 8px;
    padding: 10px 12px;
    font-size: 12.5px;
    margin-bottom: 12px;
    display: flex;
    gap: 8px;
    align-items: flex-start;
  }
  .confirm-write input { margin-top: 2px; }
  .actions {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }
  button.run, button.sample, button.grid-toggle {
    background: linear-gradient(135deg, var(--accent), #1746c6);
    color: white;
    border: none;
    padding: 9px 18px;
    border-radius: 7px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    box-shadow: 0 10px 22px rgba(37, 99, 235, .18);
  }
  button.sample {
    background: linear-gradient(135deg, #0f766e, #0891b2);
  }
  button.sample:hover { background: #0c5f59; }
  button.run:disabled { background: #a8b3cc; cursor: not-allowed; }
  button.run:hover:not(:disabled) { background: #1940d1; }
  button.grid-toggle {
    background: #ffffff;
    color: var(--accent);
    border: 1px solid var(--accent-border);
    box-shadow: none;
    padding: 7px 12px;
  }
  button.grid-toggle.active {
    background: var(--accent);
    color: #ffffff;
    border-color: var(--accent);
  }
  .override-toggle {
    font-size: 12px;
    color: var(--accent);
    cursor: pointer;
    margin-bottom: 8px;
    display: inline-block;
    user-select: none;
  }
  .client-error { color: var(--err); font-size: 12.5px; margin-top: 8px; }
  .result-box {
    border-radius: 8px;
    border: 1px solid var(--border);
    padding: 12px 14px;
    font-family: var(--mono);
    font-size: 12px;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 420px;
    overflow-y: auto;
  }
  .result-box.ok { border-color: #9ae3af; background: var(--ok-bg); }
  .result-box.err { border-color: #f3aeae; background: var(--err-bg); }
  .result-meta {
    font-size: 11.5px;
    color: var(--muted);
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    flex-wrap: wrap;
  }
  .result-actions {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .grid-wrap {
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: auto;
    max-height: 420px;
    background: #ffffff;
  }
  .grid-table {
    border-collapse: collapse;
    width: 100%;
    min-width: 520px;
    font-size: 12px;
  }
  .grid-table th {
    position: sticky;
    top: 0;
    z-index: 1;
    background: #eaf2ff;
    color: #15346f;
    text-align: left;
    font-weight: 700;
    border-bottom: 1px solid var(--accent-border);
    padding: 8px 10px;
    white-space: nowrap;
  }
  .grid-table td {
    border-bottom: 1px solid #edf1f6;
    padding: 7px 10px;
    vertical-align: top;
    max-width: 280px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .grid-table tr:nth-child(even) td { background: #f8fbff; }
  .grid-empty {
    color: var(--muted);
    padding: 14px;
    font-size: 12.5px;
  }
  .history-item {
    padding: 8px 10px;
    border: 1px solid var(--border);
    border-radius: 7px;
    margin-bottom: 6px;
    font-size: 12px;
    cursor: pointer;
    display: flex;
    justify-content: space-between;
    gap: 8px;
    background: var(--panel);
  }
  .history-item:hover { background: #f0f2f5; }
  .history-item .h-ok { color: var(--ok); font-weight: 600; }
  .history-item .h-err { color: var(--err); font-weight: 600; }
  .history-item .h-time { color: var(--muted); }
  .spinner {
    display: inline-block; width: 12px; height: 12px; border-radius: 50%;
    border: 2px solid #b9c2ff; border-top-color: var(--accent);
    animation: spin .7s linear infinite; margin-right: 6px; vertical-align: -1px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<header>
  <h1>Probador MCP Faro</h1>
  <span class="badge" id="badge-profile">cargando...</span>
  <span class="info" id="info-conn"></span>
  <a class="help-link" id="help-link" href="/ayuda" target="_blank" rel="noopener">Ayuda</a>
  <button type="button" class="settings-btn" id="settings-btn" title="Configurar empresa, centro y usuario" aria-label="Ajustes">
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M19.4 13.5c.04-.5.04-1 0-1.5l1.9-1.5-2-3.5-2.2.9c-.4-.3-.8-.6-1.3-.8L15.5 5h-4l-.3 2.1c-.5.2-.9.5-1.3.8l-2.2-.9-2 3.5 1.9 1.5c-.04.5-.04 1 0 1.5l-1.9 1.5 2 3.5 2.2-.9c.4.3.8.6 1.3.8l.3 2.1h4l.3-2.1c.5-.2.9-.5 1.3-.8l2.2.9 2-3.5z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>
  </button>
</header>
<div class="modal-backdrop" id="settings-backdrop">
  <div class="modal" role="dialog" aria-modal="true" aria-label="Configuracion del servidor MCP">
    <h2>Configuracion del servidor</h2>
    <p class="modal-hint">Cambia empresa, centro y usuario del probador. Se aplica al momento, sin reiniciar el servidor, y queda guardado para la proxima vez que lo arranques (salvo que uses un flag o variable de entorno al lanzarlo, que siempre manda).</p>
    <form id="settings-form">
      <div class="field">
        <label for="settings-empresa">Empresa</label>
        <input type="number" id="settings-empresa" name="empresa" required>
      </div>
      <div class="field">
        <label for="settings-centro">Centro</label>
        <input type="number" id="settings-centro" name="centro" required>
      </div>
      <div class="field">
        <label for="settings-usuario">Usuario</label>
        <input type="text" id="settings-usuario" name="usuario" required>
      </div>
      <div class="client-error" id="settings-error" style="display:none"></div>
      <div class="modal-actions">
        <button type="button" class="modal-cancel" id="settings-cancel">Cancelar</button>
        <button type="submit" class="run" id="settings-save">Guardar</button>
      </div>
    </form>
  </div>
</div>
<div class="layout">
  <div class="sidebar">
    <div class="search"><input type="text" id="search" placeholder="Buscar herramienta..."></div>
    <div class="tool-legend">
      <span class="legend-item"><span class="tool-icon read" data-icon="read"></span>Lectura</span>
      <span class="legend-item"><span class="tool-icon write" data-icon="write"></span>Escritura</span>
      <span class="legend-item"><span class="tool-icon critical" data-icon="write"></span>Crítica</span>
      <span class="legend-item"><span class="tool-icon delete" data-icon="delete"></span>Borrado</span>
    </div>
    <div class="tool-list" id="tool-list"></div>
  </div>
  <main id="main">
    <div class="empty-state">Cargando herramientas del servidor MCP...</div>
  </main>
</div>
<script>
let TOOLS = [];
let ACTIVE = null;
const HISTORY = [];
const OPEN_GROUPS = new Set();

function el(tag, attrs, children) {
  const e = document.createElement(tag);
  if (attrs) for (const [k, v] of Object.entries(attrs)) {
    if (k === 'text') e.textContent = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  if (children) for (const c of children) if (c) e.appendChild(c);
  return e;
}

function icon(name, className) {
  const svgByName = {
    read: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h7a4 4 0 0 1 4 4v10a3 3 0 0 0-3-3H4z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M20 5h-5a4 4 0 0 0-4 4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    write: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>',
    delete: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M8 6V4h8v2" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M6 6l1 15h10l1-15" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>',
    actividad: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19V5h16v14z" fill="none" stroke="currentColor" stroke-width="2"/><path d="M8 9h8M8 13h5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    articulo: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7l8-4 8 4-8 4z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M4 7v10l8 4 8-4V7" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M12 11v10" fill="none" stroke="currentColor" stroke-width="2"/></svg>',
    cliente: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M16 19a4 4 0 0 0-8 0" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="12" cy="8" r="3" fill="none" stroke="currentColor" stroke-width="2"/></svg>',
    control: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 8v5l3 2" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    etiqueta: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12l8-8h7v7l-8 8z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><circle cx="16" cy="8" r="1" fill="currentColor"/></svg>',
    falta: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l9 16H3z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M12 9v4M12 17h.01" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    mostrador: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 9h14l-1 10H6z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M8 9a4 4 0 0 1 8 0" fill="none" stroke="currentColor" stroke-width="2"/></svg>',
    pedido: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 3h10l2 4v14H5V7z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M9 12h6M9 16h6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    recuento: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 6h13M8 12h13M8 18h13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M3 6h.01M3 12h.01M3 18h.01" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"/></svg>',
    stock: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7h18v14H3z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M7 7V4h10v3M7 12h10" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    venta: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h2l2 10h9l2-7H7" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><circle cx="10" cy="19" r="1.5" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="17" cy="19" r="1.5" fill="none" stroke="currentColor" stroke-width="2"/></svg>',
    default: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 5h6v6H5zM13 5h6v6h-6zM5 13h6v6H5zM13 13h6v6h-6z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>',
  };
  const span = el('span', {class: className || ''});
  span.innerHTML = svgByName[name] || svgByName.default;
  return span;
}

function branchIconName(groupName) {
  const key = String(groupName || '').toLowerCase();
  if (key in {actividad: 1, articulo: 1, cliente: 1, control: 1, etiqueta: 1, falta: 1, mostrador: 1, pedido: 1, recuento: 1, stock: 1, venta: 1}) {
    return key;
  }
  return 'default';
}

function hydrateStaticIcons() {
  document.querySelectorAll('[data-icon]').forEach(node => {
    const name = node.getAttribute('data-icon');
    node.innerHTML = icon(name).innerHTML;
  });
}

function isLikelyWrite(tool) {
  return toolAccessKind(tool).kind !== 'read';
}

function toolAccessKind(tool) {
  const props = (tool.inputSchema && tool.inputSchema.properties) || {};
  const accion = props.accion;
  const destructiveWords = ['borrar', 'eliminar', 'delete', 'remove', 'anular'];
  const writeActionWords = ['grabar', 'guardar', 'crear', 'actualizar', 'regularizar', 'cobrar', 'cerrar', 'finalizar', 'albaranar', 'trasvasar', 'fichar', 'marcar', 'cargar_pedido'];

  // Herramientas tipo "_gestion" (etiqueta, recuento, falta, mostrador_venta...)
  // exponen listar/grabar/borrar bajo un unico "accion": el icono debe reflejar
  // que la herramienta gestiona el recurso (Escritura), no que solo borra.
  // "Borrado" queda reservado para herramientas cuya UNICA accion posible es
  // destructiva.
  if (accion && Array.isArray(accion.enum) && accion.enum.length) {
    const actions = accion.enum.map(v => String(v).toLowerCase());
    const allDestructive = actions.every(v => destructiveWords.includes(v));
    if (allDestructive) {
      return {kind: 'delete', label: 'Borrado', icon: 'delete'};
    }
    if (actions.some(v => writeActionWords.includes(v) || destructiveWords.includes(v))) {
      return {kind: 'write', label: 'Escritura', icon: 'write'};
    }
    return {kind: 'read', label: 'Lectura', icon: 'read'};
  }

  const text = ((tool.name || '') + ' ' + (tool.description || '')).toLowerCase();
  if (tool.description && tool.description.toUpperCase().includes('CRITICA')) {
    return {kind: 'critical', label: 'Crítica', icon: 'write'};
  }
  if (tool.description && tool.description.includes('ESCRITURA')) {
    return {kind: 'write', label: 'Escritura', icon: 'write'};
  }
  if (destructiveWords.some(word => text.includes(word))) {
    return {kind: 'delete', label: 'Borrado', icon: 'delete'};
  }
  if (writeActionWords.some(word => text.includes(word))) {
    return {kind: 'write', label: 'Escritura', icon: 'write'};
  }
  return {kind: 'read', label: 'Lectura', icon: 'read'};
}

// Herramientas que se clasifican como Lectura (por seguridad, ya que por
// defecto simulan) pero cuya accion real es modificar algo: se les pone el
// icono de "modificar" aunque la etiqueta siga diciendo Lectura.
const ICON_OVERRIDES = {
  articulo_cambiar_tabla_precio: 'write',
};

// Nombre mostrado en el listado y en la ficha, sin cambiar el nombre real
// de la herramienta MCP (el que se usa para llamarla con /api/call).
const DISPLAY_NAME_OVERRIDES = {
  articulo_catalogo_listar: 'Listar familias',
};

function displayName(tool) {
  return DISPLAY_NAME_OVERRIDES[tool.name] || tool.name;
}

function displayIcon(tool, access) {
  return ICON_OVERRIDES[tool.name] || access.icon;
}

// Orden de aparicion por tipo dentro de cada grupo: primero Lectura, luego
// Escritura, y Borrado al final.
const KIND_ORDER = {read: 0, write: 1, critical: 2, delete: 3};

// Excepciones manuales de orden dentro del grupo: la herramienta de la
// izquierda se coloca justo detras de la de la derecha, aunque por su
// clasificacion (Lectura/Escritura) le tocara otra posicion. Se usa para
// "articulo_cambiar_tabla_precio", que se comporta como modificar pero se
// clasifica como Lectura por seguridad (por defecto simula).
const MOVE_AFTER = {
  articulo_cambiar_tabla_precio: 'articulo_familia_guardar',
};

function applyManualPositions(tools) {
  const list = tools.slice();
  for (const [name, afterName] of Object.entries(MOVE_AFTER)) {
    const idx = list.findIndex(t => t.name === name);
    if (idx === -1) continue;
    const [moved] = list.splice(idx, 1);
    const afterIdx = list.findIndex(t => t.name === afterName);
    if (afterIdx === -1) {
      // No esta en este listado (p.ej. filtrado por busqueda): lo dejamos
      // donde estaba.
      list.splice(idx, 0, moved);
      continue;
    }
    list.splice(afterIdx + 1, 0, moved);
  }
  return list;
}

function sortByAccessKind(tools) {
  const sorted = tools
    .map((tool, index) => ({tool, index, access: toolAccessKind(tool)}))
    .sort((a, b) => {
      const rank = (KIND_ORDER[a.access.kind] ?? 99) - (KIND_ORDER[b.access.kind] ?? 99);
      return rank !== 0 ? rank : a.index - b.index;
    })
    .map(entry => entry.tool);
  return applyManualPositions(sorted);
}

function groupPrefix(name) {
  const idx = name.indexOf('_');
  return idx === -1 ? name : name.slice(0, idx);
}

// Etiquetas de grupo mas descriptivas que el prefijo tecnico crudo. Solo se
// listan aqui las que necesitan un nombre distinto; el resto sigue mostrando
// el prefijo (en mayusculas, por el CSS de .group-title .label).
const GROUP_LABELS = {
  orden: 'Ordenes de Compra',
  venta: 'Ventas / rentabilidad',
};

function groupLabel(g) {
  return GROUP_LABELS[g] || g;
}

function activeGroup() {
  return ACTIVE ? groupPrefix(ACTIVE) : null;
}

let CURRENT_INFO = null;

function applyInfo(info) {
  CURRENT_INFO = info;
  document.getElementById('badge-profile').textContent = 'perfil: ' + info.profile + ' · v' + info.server_version;
  document.getElementById('info-conn').textContent =
    'DSN=' + info.dsn + '  empresa=' + info.empresa + '  centro=' + info.centro + '  usuario=' + info.usuario;
}

async function loadTools() {
  hydrateStaticIcons();
  const infoRes = await fetch('/api/info');
  applyInfo(await infoRes.json());

  const res = await fetch('/api/tools');
  const data = await res.json();
  TOOLS = data.tools.slice().sort((a, b) => a.name.localeCompare(b.name));
  renderList('');
  document.getElementById('main').innerHTML = '';
  document.getElementById('main').appendChild(
    el('div', {class: 'empty-state', text: 'Elige una herramienta de la izquierda para ver sus parametros.'})
  );
}

function openSettings() {
  const backdrop = document.getElementById('settings-backdrop');
  const errorBox = document.getElementById('settings-error');
  errorBox.style.display = 'none';
  errorBox.textContent = '';
  if (CURRENT_INFO) {
    document.getElementById('settings-empresa').value = CURRENT_INFO.empresa;
    document.getElementById('settings-centro').value = CURRENT_INFO.centro;
    document.getElementById('settings-usuario').value = CURRENT_INFO.usuario;
  }
  backdrop.classList.add('open');
  document.getElementById('settings-empresa').focus();
}

function closeSettings() {
  document.getElementById('settings-backdrop').classList.remove('open');
}

async function saveSettings(ev) {
  ev.preventDefault();
  const errorBox = document.getElementById('settings-error');
  errorBox.style.display = 'none';
  const saveBtn = document.getElementById('settings-save');
  const payload = {
    empresa: document.getElementById('settings-empresa').value.trim(),
    centro: document.getElementById('settings-centro').value.trim(),
    usuario: document.getElementById('settings-usuario').value.trim(),
  };
  saveBtn.disabled = true;
  const previousText = saveBtn.textContent;
  saveBtn.textContent = 'Guardando...';
  try {
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.error || 'No se pudo guardar la configuracion');
    }
    applyInfo(data);
    closeSettings();
    if (data.persist_warning) {
      // Se aplico igualmente para esta sesion; solo avisa de que no quedara
      // para la proxima vez que se arranque el probador.
      window.alert(data.persist_warning);
    }
  } catch (e) {
    errorBox.textContent = e.message;
    errorBox.style.display = 'block';
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = previousText;
  }
}

function renderList(filterText) {
  const list = document.getElementById('tool-list');
  list.innerHTML = '';
  const normalizedFilter = filterText.trim().toLowerCase();
  const filtered = TOOLS.filter(t => t.name.toLowerCase().includes(filterText.toLowerCase())
    || displayName(t).toLowerCase().includes(filterText.toLowerCase())
    || (t.description || '').toLowerCase().includes(filterText.toLowerCase()));
  const groups = {};
  for (const t of filtered) {
    const g = groupPrefix(t.name);
    (groups[g] = groups[g] || []).push(t);
  }
  const groupNames = Object.keys(groups).sort();
  for (const g of groupNames) {
    const isOpen = normalizedFilter !== '' || OPEN_GROUPS.has(g) || activeGroup() === g;
    const groupButton = el('button', {
      type: 'button',
      class: 'group-title',
      onclick: () => {
        if (OPEN_GROUPS.has(g)) OPEN_GROUPS.delete(g);
        else OPEN_GROUPS.add(g);
        renderList(document.getElementById('search').value);
      },
    }, [
      el('span', {class: 'group-left'}, [
        el('span', {class: 'chevron', text: isOpen ? 'v' : '>'}),
        icon(branchIconName(g), 'branch-icon'),
        el('span', {class: 'label', text: groupLabel(g)}),
      ]),
      el('span', {class: 'count', text: String(groups[g].length)}),
    ]);
    list.appendChild(groupButton);
    if (!isOpen) continue;
    for (const tool of sortByAccessKind(groups[g])) {
      const access = toolAccessKind(tool);
      const iconName = displayIcon(tool, access);
      const item = el('div', {
        class: 'tool-item ' + access.kind + (ACTIVE === tool.name ? ' active' : ''),
        onclick: () => selectTool(tool.name),
      }, [
        el('span', {class: 'tool-name', text: displayName(tool)}),
        icon(iconName, 'tool-icon ' + iconName),
      ]);
      if (DISPLAY_NAME_OVERRIDES[tool.name]) {
        item.querySelector('.tool-name').setAttribute('title', tool.name);
      }
      item.querySelector('.tool-icon').setAttribute('title', access.label);
      list.appendChild(item);
    }
  }
}

function exampleFor(schema) {
  if (!schema) return null;
  if (schema.enum) return schema.enum[0];
  const t = Array.isArray(schema.type) ? schema.type[0] : schema.type;
  if (t === 'object') {
    const obj = {};
    for (const [k, s] of Object.entries(schema.properties || {})) obj[k] = exampleFor(s);
    return obj;
  }
  if (t === 'array') {
    const item = exampleFor(schema.items);
    return item === null ? [] : [item];
  }
  if (t === 'integer' || t === 'number') return 0;
  if (t === 'boolean') return false;
  return '';
}

function sampleForField(fieldName, schema, toolName) {
  if (!schema) return '';
  if (schema.default !== undefined) return schema.default;
  if (schema.enum && schema.enum.length) {
    const safeAction = schema.enum.find(v => ['listar', 'buscar', 'obtener', 'consultar', 'detalle', 'tipos'].includes(String(v)));
    return safeAction !== undefined ? safeAction : schema.enum[0];
  }

  const lower = fieldName.toLowerCase();
  const type = Array.isArray(schema.type) ? schema.type.find(t => t !== 'null') || schema.type[0] : schema.type;

  if (type === 'boolean') return lower.includes('simular') ? true : false;
  if (type === 'object') {
    const obj = {};
    for (const [k, s] of Object.entries(schema.properties || {})) obj[k] = sampleForField(k, s, toolName);
    return obj;
  }
  if (type === 'array') {
    const itemSchema = schema.items || {};
    const itemType = Array.isArray(itemSchema.type) ? itemSchema.type[0] : itemSchema.type;
    if (itemType === 'object' && !(itemSchema.properties && Object.keys(itemSchema.properties).length)) {
      // El esquema no dice que forma tiene cada linea (objeto libre, p.ej. las
      // "lineas" de mostrador_venta_gestion, que cambian de forma segun accion
      // y ademas graban una venta real). No inventamos aqui una linea de
      // prueba: se deja vacio para que la persona introduzca a proposito una
      // linea real, en vez de que el boton de "datos de prueba" cuele una.
      return [];
    }
    const item = sampleForField(lower.replace(/s$/, ''), itemSchema, toolName);
    return item === '' || item === null ? [] : [item];
  }
  if (type === 'integer' || type === 'number' || (Array.isArray(schema.type) && schema.type.includes('number'))) {
    if (lower.includes('subcliente') || lower.includes('subcli')) return 0;
    if (lower.includes('articulo') || lower.includes('codart')) return 814943103;
    if (lower.includes('cliente') || lower.includes('codcli')) return 100;
    if (lower.includes('empresa')) return 1;
    if (lower.includes('centro')) return 0;
    if (lower.includes('ejercicio') || lower.includes('anio') || lower.includes('ano')) return new Date().getFullYear();
    if (lower.includes('cantidad')) return 1;
    if (lower.includes('precio') || lower.includes('importe')) return 1;
    if (lower.includes('limite') || lower.includes('max') || lower.includes('rows')) return 10;
    if (lower.includes('pagina') || lower.includes('page')) return 1;
    if (lower.includes('numero') || lower.includes('num')) return 1;
    return 0;
  }

  if (lower.includes('fecha')) return new Date().toISOString().slice(0, 10);
  if (lower.includes('email') || lower.includes('correo')) return 'prueba@example.com';
  if (lower.includes('telefono') || lower.includes('movil')) return '600000000';
  if (lower.includes('usuario')) return 'probador-web';
  if (lower.includes('subcliente') || lower.includes('subcli')) return '0';
  if (lower.includes('centro')) return '0';
  if (lower.includes('articulo') || lower.includes('codart')) return '814943103';
  if (lower.includes('cliente') || lower.includes('codcli')) return '100';
  if (lower.includes('familia')) return '01';
  if (lower.includes('marca')) return 'GENERAL';
  if (lower.includes('proveedor')) return '1';
  if (lower.includes('buscar') || lower.includes('texto') || lower.includes('nombre') || lower.includes('descripcion')) return 'a';
  if (lower.includes('sql')) return 'select 1 as prueba';
  if (lower.includes('path') || lower.includes('ruta') || lower.includes('fichero')) return 'prueba.txt';
  return '';
}

function setInputValue(inputEl, schema, value) {
  if (!inputEl) return;
  if (inputEl.dataset.tariffHidden === 'true') {
    supplierTariffSetLines(inputEl, value);
    return;
  }
  const widget = inputEl.dataset.widget;
  if (widget === 'json') inputEl.value = JSON.stringify(value, null, 2);
  else if (widget === 'bool') inputEl.value = String(Boolean(value));
  else inputEl.value = value === undefined || value === null ? '' : String(value);
}

async function callToolForSample(name, args) {
  const res = await fetch('/api/call', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name, arguments: args}),
  });
  const payload = await res.json();
  if (payload.is_error || !payload.result || payload.result.ok === false) {
    throw new Error((payload.result && payload.result.error && payload.result.error.message) || 'No se pudieron obtener datos de prueba');
  }
  return payload.result.data;
}

function saleLineFallbacks() {
  return [
    {articulo: '814943103', descripcion: 'CAFETERA ALUMINIO INDUCCION NEGRA 1-3 TAZAS LUCCIA', cantidad: 1, precio: 16.5702, descuento1: 25, descuento2: 0, iva: 21, recargo: 0, tipo_precio: '3', unidad_medida: 'UNI', precio_iva_incluido: false, pvp: 20.05, oferta_ejercicio: 0, oferta_numero: 0},
    {articulo: 'INABM6067', descripcion: '100 ABRAZADERAS M-6 67MM.', cantidad: 2, precio: 35.1157, descuento1: 0, descuento2: 0, iva: 21, recargo: 0, tipo_precio: '3', unidad_medida: 'CENT', precio_iva_incluido: false, pvp: 42.49, oferta_ejercicio: 0, oferta_numero: 0},
    {articulo: '402426035', descripcion: 'ANTI HUMOS DIESEL SMOKE STOP CAR 200ML 32028-AC', cantidad: 1, precio: 8.8017, descuento1: 0, descuento2: 0, iva: 21, recargo: 0, tipo_precio: '3', unidad_medida: 'UNI', precio_iva_incluido: false, pvp: 10.65, oferta_ejercicio: 0, oferta_numero: 0},
    {articulo: '422402036', descripcion: 'BARRERA DE INSECTOS 1L', cantidad: 3, precio: 11.8182, descuento1: 0, descuento2: 0, iva: 21, recargo: 0, tipo_precio: '3', unidad_medida: 'UNID', precio_iva_incluido: false, pvp: 14.30, oferta_ejercicio: 0, oferta_numero: 0},
  ];
}

function readFormNumber(form, fieldName, fallback) {
  const inputEl = form.querySelector(`[name="${CSS.escape(fieldName)}"]`);
  if (!inputEl || inputEl.value === '') return fallback;
  const value = Number(inputEl.value);
  return Number.isNaN(value) ? fallback : value;
}

async function buildSaleDocumentLines(form, clienteField, subclienteField) {
  const cliente = readFormNumber(form, clienteField || 'cliente', 100);
  const subcliente = readFormNumber(form, subclienteField || 'subcliente', 0);
  const articlesData = await callToolForSample('articulo_buscar', {texto: 'a', limite: 4});
  const items = ((articlesData && articlesData.items) || []).slice(0, 4);
  if (!items.length) return saleLineFallbacks();
  const quantities = [1, 2, 1, 3];
  const lines = [];
  for (let index = 0; index < items.length; index += 1) {
    const item = items[index];
    const articulo = String(item.codart || item.articulo || '');
    const cantidad = quantities[index] || 1;
    let price = {};
    try {
      price = await callToolForSample('articulo_precio_cliente', {articulo, cliente, subcliente, cantidad});
    } catch (e) {
      price = {};
    }
    lines.push({
      articulo,
      descripcion: String(item.descri || item.descripcion || '').trim(),
      cantidad,
      precio: price.preven || item.preven4 || 0,
      descuento1: price.dto1 || 0,
      descuento2: price.dto2 || 0,
      iva: price.poriva || 21,
      recargo: price.porreq || 0,
      tipo_precio: price.tippre || '',
      unidad_medida: price.unimed || item.unimed || 'UNI',
      precio_iva_incluido: String(price.preiva || '').toUpperCase() === 'S',
      pvp: price.pvp || item.pvp || 0,
      oferta_ejercicio: price.ejeofe || 0,
      oferta_numero: price.numofe || 0,
    });
  }
  return lines;
}

function currentCustomerUpdateKey(form) {
  const inputEl = form.querySelector('[name="datos"]');
  if (!inputEl || !inputEl.value.trim()) return {cliente: 100, subcliente: 0};
  try {
    const current = JSON.parse(inputEl.value);
    return {
      cliente: Number(current.cliente ?? 100) || 100,
      subcliente: Number(current.subcliente ?? 0) || 0,
    };
  } catch (e) {
    return {cliente: 100, subcliente: 0};
  }
}

async function fillClienteActualizarSampleData(form, tool, props) {
  const {cliente, subcliente} = currentCustomerUpdateKey(form);
  const data = await callToolForSample('cliente_buscar', {cliente, subcliente});
  const detail = (data && data.resultado) || {};
  if (!detail.found) throw new Error(`Cliente ${cliente}/${subcliente} no encontrado`);
  const sample = {
    cliente: Number(detail.codcli ?? detail.cliente ?? cliente) || cliente,
    subcliente: Number(detail.subcli ?? detail.subcliente ?? subcliente) || subcliente,
    nombre: String(detail.nomcli ?? detail.nombre ?? '').trim(),
    razon_social: String(detail.razsoc ?? detail.razon_social ?? '').trim(),
    domicilio: String(detail.domici ?? detail.domicilio ?? '').trim(),
    codigo_postal: String(detail.codpos ?? detail.codigo_postal ?? '').trim(),
    poblacion: String(detail.poblac ?? detail.poblacion ?? '').trim(),
    telefono: String(detail.telefo ?? detail.telefono ?? '').trim(),
    email: String(detail.email ?? '').trim(),
    cif: String(detail.cif ?? '').trim(),
  };
  setInputValue(form.querySelector('[name="datos"]'), props.datos, sample);
}

async function fillSaleDocumentSampleData(form, tool, props, fieldNames) {
  for (const fieldName of fieldNames) {
    if (fieldName === 'lineas') continue;
    const inputEl = form.querySelector(`[name="${CSS.escape(fieldName)}"]`);
    let value = sampleForField(fieldName, props[fieldName], tool.name);
    if (fieldName === 'tipo_documento') value = 'A';
    if (fieldName === 'centro') value = 0;
    if (fieldName === 'subcliente') value = 0;
    setInputValue(inputEl, props[fieldName], value);
  }
  const lineInput = form.querySelector('[name="lineas"]');
  const lines = await buildSaleDocumentLines(form);
  setInputValue(lineInput, props.lineas, lines);
}

async function fillMostradorVentaSampleData(form, tool, props, fieldNames) {
  const accionInput = form.querySelector('[name="accion"]');
  const accion = (accionInput && accionInput.value) || 'guardar';
  for (const fieldName of fieldNames) {
    if (fieldName === 'lineas' || fieldName === 'accion') continue;
    const inputEl = form.querySelector(`[name="${CSS.escape(fieldName)}"]`);
    let value = sampleForField(fieldName, props[fieldName], tool.name);
    if (fieldName === 'tipo_documento') value = 'A';
    if (fieldName === 'centro') value = 0;
    setInputValue(inputEl, props[fieldName], value);
  }
  const lineInput = form.querySelector('[name="lineas"]');
  if (accion !== 'guardar') {
    // "borrar" no usa lineas, y "cargar_pedido" espera objetos {linea,
    // cantidad} referidos a un pedido real que aqui no conocemos: se deja
    // vacio para que la persona ponga las suyas en vez de inventar numeros
    // de linea de un pedido que no existe.
    setInputValue(lineInput, props.lineas, []);
    return;
  }
  // Igual que en venta_documento_crear: se piden articulos y precios reales
  // (via articulo_buscar / articulo_precio_cliente) para tener varias lineas
  // de venta ya coherentes, en vez de un objeto vacio o inventado a mano.
  // cliente/subcliente son los nombres publicos reales de este formulario
  // (codcli/subcli en el contrato interno), por eso se leen tal cual sin
  // pasar nombres alternativos.
  const lines = await buildSaleDocumentLines(form);
  setInputValue(lineInput, props.lineas, lines);
}

async function fillMostradorCobrarSampleData(form, tool, props, fieldNames) {
  const cliente = readFormNumber(form, 'cliente', 100);
  const subcliente = readFormNumber(form, 'subcliente', 0);
  const usuario = (form.querySelector('[name="usuario"]') || {}).value || 'probador-web';
  // Antes esto forzaba siempre centro=0 sin mirar con que centro esta
  // configurado el servidor MCP (el que se ve/edita con el icono de
  // ajustes). Si tu centro real no es el 0, el ticket se creaba igualmente
  // pero en un centro distinto al que luego consultas en Faro, y parecia
  // que "no se habia generado" cuando en realidad estaba en otro centro.
  const centro = readFormNumber(form, 'centro', parseInt((CURRENT_INFO && CURRENT_INFO.centro) || '0', 10) || 0);

  // No hay forma de listar ventas abiertas ya existentes, asi que se crea
  // una de verdad (mostrador_venta_gestion, accion=guardar) con articulos y
  // precios reales, y se reutiliza su clave y su total para poder cobrarla.
  const lines = await buildSaleDocumentLines(form);
  const venta = await callToolForSample('mostrador_venta_gestion', {
    accion: 'guardar',
    centro,
    cliente,
    subcliente,
    tipo_documento: 'A',
    usuario,
    lineas: lines,
  });
  const total = venta.totald ?? venta.totals ?? 0;

  for (const fieldName of fieldNames) {
    if (fieldName === 'lineas') continue;
    const inputEl = form.querySelector(`[name="${CSS.escape(fieldName)}"]`);
    let value = sampleForField(fieldName, props[fieldName], tool.name);
    if (fieldName === 'centro') value = centro;
    if (fieldName === 'cliente') value = cliente;
    if (fieldName === 'subcliente') value = subcliente;
    if (fieldName === 'caja') value = 1;
    if (fieldName === 'tipo_documento') value = 'T';
    if (fieldName === 'venta') value = venta.venta || '';
    if (fieldName === 'total') value = total;
    if (fieldName === 'efectivo') value = total;
    if (fieldName === 'tarjeta') value = 0;
    if (fieldName === 'otros') value = 0;
    if (fieldName === 'usuario') value = usuario;
    setInputValue(inputEl, props[fieldName], value);
  }
  // La venta abierta ya trae sus propias lineas: dejarlo vacio es lo que
  // hace que mostrador_cobrar la consuma en vez de esperar lineas nuevas.
  setInputValue(form.querySelector('[name="lineas"]'), props.lineas, []);
}

async function fillEntradaAlmacenSampleData(form, tool, props) {
  const articulo = '814943103';
  let proveedor = 1;
  let referencia = articulo;
  try {
    const proveedores = await callToolForSample('articulo_compra_consultar', {articulo});
    const first = ((proveedores && proveedores.items) || [])[0] || {};
    proveedor = Number(first.codpro || first.proveedor || proveedor) || proveedor;
    const ficha = await callToolForSample('articulo_compra_consultar', {articulo, proveedor});
    referencia = String(ficha.refpro || ficha.referencia_proveedor || articulo);
  } catch (e) {
    referencia = articulo;
  }
  const cabecera = {
    centro: parseInt((CURRENT_INFO && CURRENT_INFO.centro) || '0', 10) || 0,
    proveedor,
    cif: '',
    fecha: new Date().toISOString().slice(0, 10),
    albaran: 'ALB-PRUEBA',
    factura: '',
    fecha_recepcion: new Date().toISOString().slice(0, 10),
    portes: 0,
    descuento: 0,
    observaciones: 'Prueba MCP',
  };
  const lineas = [{
    articulo: referencia,
    cantidad: 1,
    descripcion: 'Prueba entrada MCP',
    precio: 1,
    descuento1: 0,
    descuento2: 0,
    descuento3: 0,
    descuento4: 0,
    descuento5: 0,
    descuento6: 0,
    iva: 21,
    recargo: 0,
  }];
  setInputValue(form.querySelector('[name="cabecera"]'), props.cabecera, cabecera);
  setInputValue(form.querySelector('[name="lineas"]'), props.lineas, lineas);
}

async function fillSupplierTariffSampleData(form, tool, props) {
  const articulo = '814943103';
  let proveedor = 1;
  let ficha = {};
  try {
    const proveedores = await callToolForSample('articulo_compra_consultar', {articulo});
    const first = ((proveedores && proveedores.items) || [])[0] || {};
    proveedor = Number(first.codpro || first.proveedor || proveedor) || proveedor;
    ficha = await callToolForSample('articulo_compra_consultar', {articulo, proveedor});
  } catch (e) {
    ficha = {};
  }
  setInputValue(form.querySelector('[name="proveedor"]'), props.proveedor, proveedor);
  setInputValue(form.querySelector('[name="actualizar_precio_venta"]'), props.actualizar_precio_venta, false);
  const line = {
    articulo,
    referencia_proveedor: String(ficha.refpro || articulo),
    descripcion: String(ficha.descri || 'Tarifa de prueba MCP'),
    unidad_medida: String(ficha.unimed || 'UNI'),
    precio_base: ficha.prebas ?? 1,
    descuento1: 0,
    descuento2: 0,
    descuento3: 0,
    descuento4: 0,
    descuento5: 0,
    descuento6: 0,
    cantidad_conversion_compra: ficha.cancon ?? 1,
    cantidad_conversion_venta: ficha.canven ?? 1,
    unidades_paquete: ficha.unipaq ?? 1,
    ampliacion_unidad_venta: String(ficha.ampuniv || ''),
    ajuste: String(ficha.ajuste || ''),
  };
  setInputValue(form.querySelector('[name="lineas"]'), props.lineas, [line]);
}

async function fillSampleData(form, tool, props, fieldNames) {
  if (tool.name === 'tarifa_proveedor_actualizar') {
    await fillSupplierTariffSampleData(form, tool, props);
    return;
  }
  if (tool.name === 'cliente_actualizar') {
    await fillClienteActualizarSampleData(form, tool, props);
    return;
  }
  if (tool.name === 'entrada_almacen_crear') {
    await fillEntradaAlmacenSampleData(form, tool, props);
    return;
  }
  if (tool.name === 'etiqueta_gestion') {
    const sample = {
      accion: 'grabar',
      articulo: '814943103',
      descripcion: '',
      cantidad: 1,
      aumentar: false,
      modelo: 0,
      imprimir: false,
    };
    for (const fieldName of fieldNames) {
      const inputEl = form.querySelector(`[name="${CSS.escape(fieldName)}"]`);
      const value = Object.prototype.hasOwnProperty.call(sample, fieldName) ? sample[fieldName] : sampleForField(fieldName, props[fieldName], tool.name);
      setInputValue(inputEl, props[fieldName], value);
    }
    return;
  }
  if (tool.name === 'venta_documento_crear') {
    await fillSaleDocumentSampleData(form, tool, props, fieldNames);
    return;
  }
  if (tool.name === 'mostrador_venta_gestion') {
    await fillMostradorVentaSampleData(form, tool, props, fieldNames);
    return;
  }
  if (tool.name === 'mostrador_cobrar') {
    await fillMostradorCobrarSampleData(form, tool, props, fieldNames);
    return;
  }
  if (tool.name === 'stock_regularizar') {
    const sample = {articulo: '706550550', centro: 0, cantidad: 5};
    for (const fieldName of fieldNames) {
      const inputEl = form.querySelector(`[name="${CSS.escape(fieldName)}"]`);
      const value = Object.prototype.hasOwnProperty.call(sample, fieldName) ? sample[fieldName] : '';
      setInputValue(inputEl, props[fieldName], value);
    }
    return;
  }
  if (tool.name === 'stock_trasvasar') {
    const sample = {
      centro_origen: 0,
      centro_destino: 1,
      lineas: [
        {articulo: '814943103', cantidad: 1},
        {articulo: '706550550', cantidad: 2},
      ],
    };
    for (const fieldName of fieldNames) {
      const inputEl = form.querySelector(`[name="${CSS.escape(fieldName)}"]`);
      const value = Object.prototype.hasOwnProperty.call(sample, fieldName) ? sample[fieldName] : '';
      setInputValue(inputEl, props[fieldName], value);
    }
    return;
  }
  for (const fieldName of fieldNames) {
    const inputEl = form.querySelector(`[name="${CSS.escape(fieldName)}"]`);
    const value = sampleForField(fieldName, props[fieldName], tool.name);
    setInputValue(inputEl, props[fieldName], value);
  }
}

const PREFERRED_FIELD_ORDER = {
  tarifa_proveedor_actualizar: ['proveedor', 'actualizar_precio_venta', 'actualizar_solo_si_sube_precio', 'actualizar_solo_proveedor_principal', 'actualizar_solo_si_propio', 'generar_etiquetas', 'etiqueta_modelo', 'dar_de_alta', 'usar_referencia_proveedor_como_codigo', 'digitos_codigo_articulo', 'numerador_inicial', 'lineas'],
  venta_documento_crear: ['centro', 'tipo_documento', 'serie', 'cliente', 'subcliente', 'lineas', 'usuario', 'venta'],
  // cliente y subcliente van juntos; codigo_pedido solo hace falta para
  // accion=cargar_pedido, asi que baja al final (junto a lineas, que ya se
  // renderiza aparte por ser JSON).
  mostrador_venta_gestion: ['accion', 'centro', 'cliente', 'subcliente', 'tipo_documento', 'usuario', 'venta', 'codigo_pedido', 'lineas'],
  // familia, subfamilia y ssubfamilia van juntos en la misma fila; tabla_nueva
  // baja debajo por ser un caso menos habitual (override manual de precio).
  articulo_familia_guardar: ['articulo', 'familia', 'subfamilia', 'ssubfamilia', 'tabla_nueva'],
};

function orderedFieldNames(toolName, props) {
  const names = Object.keys(props);
  const preferred = PREFERRED_FIELD_ORDER[toolName];
  if (!preferred) return names;
  return preferred.filter(name => names.includes(name)).concat(names.filter(name => !preferred.includes(name)));
}

function isCompactField(propSchema) {
  if (!propSchema) return true;
  if (propSchema.enum) return true;
  const type = Array.isArray(propSchema.type) ? (propSchema.type.find(t => t !== 'null') || propSchema.type[0]) : propSchema.type;
  return type !== 'array' && type !== 'object';
}

// Agrupa los campos "cortos" (texto/numero/booleano/enum) en una rejilla de
// varias columnas para que quepan mas parametros por pantallazo, y deja los
// campos "largos" (arrays/objetos, editados como JSON) a ancho completo
// debajo, cada uno en su propia fila.
function appendFieldsCompactly(form, names, props, required) {
  const compact = names.filter(name => isCompactField(props[name]));
  const long = names.filter(name => !isCompactField(props[name]));
  if (compact.length) {
    const grid = el('div', {class: 'field-grid'});
    for (const name of compact) grid.appendChild(buildField(name, props[name], required.includes(name)));
    form.appendChild(grid);
  }
  for (const name of long) form.appendChild(buildField(name, props[name], required.includes(name)));
}

const SUPPLIER_TARIFF_BASIC_FIELDS = [
  ['articulo', 'Artículo', 'text'],
  ['codigo_barras', 'EAN / código barras', 'text'],
  ['referencia_proveedor', 'Ref. proveedor', 'text'],
  ['precio_base', 'Precio base *', 'number'],
];
const SUPPLIER_TARIFF_SECONDARY_FIELDS = [
  ['descripcion', 'Descripción', 'text'],
  ['unidad_medida', 'Unidad', 'text'],
  ['descuento1', 'Dto. 1 %', 'number'],
  ['descuento2', 'Dto. 2 %', 'number'],
  ['descuento3', 'Dto. 3 %', 'number'],
  ['descuento4', 'Dto. 4 %', 'number'],
  ['descuento5', 'Dto. 5 %', 'number'],
  ['descuento6', 'Dto. 6 %', 'number'],
];
const SUPPLIER_TARIFF_ADVANCED_FIELDS = [
  ['cantidad_conversion_compra', 'Conversión compra', 'number'],
  ['cantidad_conversion_venta', 'Conversión venta', 'number'],
  ['unidades_paquete', 'Unidades paquete', 'number'],
  ['ampliacion_unidad_venta', 'Ampliación unidad venta', 'text'],
  ['ajuste', 'Ajuste', 'text'],
];
// Solo tienen efecto si dar_de_alta=true y el articulo de la linea no existe
// todavia (replican la rama B_ALTA de IMPTAR_U.pas). seccion/tipo_iva/
// tipo_precio/unidad_medida son obligatorios en ese caso.
const SUPPLIER_TARIFF_ALTA_FIELDS = [
  ['seccion', 'Sección (alta) *', 'text'],
  ['tipo_iva', 'Tipo IVA (alta) *', 'number'],
  ['tipo_precio', 'Tipo precio: V/C/M... (alta) *', 'text'],
  ['familia', 'Familia (alta)', 'number'],
  ['subfamilia', 'Subfamilia (alta)', 'number'],
  ['tabla_precios', 'Tabla de precios (alta)', 'number'],
  ['canon', 'Canon (alta)', 'number'],
  ['tarifa', 'P. tarifa (alta)', 'number'],
  ['pvp', 'PVP directo (alta)', 'number'],
  ['cantidad_pedido_minimo', 'Cant. pedido mínimo (alta)', 'number'],
  ['norma', 'Norma (alta)', 'text'],
];

function supplierTariffMiniField(fieldDef, line, onChange) {
  const [name, labelText, inputType] = fieldDef;
  const wrap = el('div', {class: 'tariff-mini'});
  wrap.appendChild(el('label', {text: labelText}));
  const attrs = {type: inputType, 'data-tariff-field': name};
  if (inputType === 'number') attrs.step = 'any';
  const input = el('input', attrs);
  const value = line && Object.prototype.hasOwnProperty.call(line, name) ? line[name] : '';
  input.value = value === null || value === undefined ? '' : String(value);
  input.addEventListener('input', onChange);
  wrap.appendChild(input);
  return wrap;
}

function supplierTariffReadLine(card) {
  const line = {};
  card.querySelectorAll('[data-tariff-field]').forEach(input => {
    const key = input.dataset.tariffField;
    const raw = input.value.trim();
    if (raw === '') return;
    if (input.type === 'number') {
      const n = Number(raw);
      line[key] = Number.isNaN(n) ? raw : n;
    } else {
      line[key] = raw;
    }
  });
  return line;
}

function supplierTariffSync(editor) {
  const hidden = editor.querySelector('textarea[data-tariff-hidden="true"]');
  const lines = Array.from(editor.querySelectorAll('.tariff-line-card')).map(supplierTariffReadLine);
  hidden.value = JSON.stringify(lines, null, 2);
  const count = editor.querySelector('.tariff-editor-count');
  if (count) count.textContent = lines.length + (lines.length === 1 ? ' línea' : ' líneas');
  editor.querySelectorAll('.tariff-line-number').forEach((node, index) => { node.textContent = 'Línea ' + (index + 1); });
}

function supplierTariffAddLine(editor, line) {
  const list = editor.querySelector('.tariff-lines');
  const card = el('div', {class: 'tariff-line-card'});
  const head = el('div', {class: 'tariff-line-head'});
  head.appendChild(el('span', {class: 'tariff-line-number', text: 'Línea'}));
  const actions = el('div', {class: 'tariff-line-actions'});
  const advancedBtn = el('button', {type: 'button', class: 'tariff-advanced', text: 'Más campos'});
  const removeBtn = el('button', {type: 'button', class: 'tariff-remove', text: 'Eliminar'});
  actions.appendChild(advancedBtn);
  actions.appendChild(removeBtn);
  head.appendChild(actions);
  card.appendChild(head);

  const mainGrid = el('div', {class: 'tariff-grid-main'});
  const secondaryGrid = el('div', {class: 'tariff-grid-secondary'});
  const advancedGrid = el('div', {class: 'tariff-grid-advanced', style: 'display:none'});
  const altaNote = el('div', {
    class: 'tariff-alta-note',
    style: 'display:none',
    text: 'Solo hacen falta si dar_de_alta=true y este artículo todavía no existe (replican B_ALTA de IMPTAR_U.pas).',
  });
  const altaGrid = el('div', {class: 'tariff-grid-advanced', style: 'display:none'});
  const sync = () => supplierTariffSync(editor);
  SUPPLIER_TARIFF_BASIC_FIELDS.forEach(def => mainGrid.appendChild(supplierTariffMiniField(def, line || {}, sync)));
  SUPPLIER_TARIFF_SECONDARY_FIELDS.forEach(def => secondaryGrid.appendChild(supplierTariffMiniField(def, line || {}, sync)));
  SUPPLIER_TARIFF_ADVANCED_FIELDS.forEach(def => advancedGrid.appendChild(supplierTariffMiniField(def, line || {}, sync)));
  SUPPLIER_TARIFF_ALTA_FIELDS.forEach(def => altaGrid.appendChild(supplierTariffMiniField(def, line || {}, sync)));
  card.appendChild(mainGrid);
  card.appendChild(secondaryGrid);
  card.appendChild(advancedGrid);
  card.appendChild(altaNote);
  card.appendChild(altaGrid);

  advancedBtn.addEventListener('click', () => {
    const open = advancedGrid.style.display !== 'none';
    advancedGrid.style.display = open ? 'none' : 'grid';
    altaNote.style.display = open ? 'none' : 'block';
    altaGrid.style.display = open ? 'none' : 'grid';
    advancedBtn.textContent = open ? 'Más campos' : 'Ocultar campos';
  });
  removeBtn.addEventListener('click', () => {
    card.remove();
    supplierTariffSync(editor);
  });
  list.appendChild(card);
  supplierTariffSync(editor);
}

function supplierTariffSetLines(hidden, lines) {
  const editor = hidden.closest('.tariff-editor');
  if (!editor) {
    hidden.value = JSON.stringify(lines || [], null, 2);
    return;
  }
  const list = editor.querySelector('.tariff-lines');
  list.innerHTML = '';
  const cleanLines = Array.isArray(lines) ? lines : [];
  cleanLines.forEach(line => supplierTariffAddLine(editor, line));
  if (!cleanLines.length) supplierTariffAddLine(editor, {});
  supplierTariffSync(editor);
}

function buildSupplierTariffLinesField(name, propSchema, required) {
  const outer = el('div', {class: 'field json-field'});
  const label = el('label', {}, [document.createTextNode(name + (required ? ' ' : ''))]);
  if (required) label.appendChild(el('span', {class: 'req', text: '*'}));
  outer.appendChild(label);
  const editor = el('div', {class: 'tariff-editor'});
  const toolbar = el('div', {class: 'tariff-editor-toolbar'});
  const title = el('div', {}, [
    el('span', {class: 'tariff-editor-title', text: 'Tarifas a procesar'}),
    el('span', {class: 'tariff-editor-count', text: '0 líneas'}),
  ]);
  const addBtn = el('button', {type: 'button', class: 'tariff-add', text: '+ Añadir línea'});
  toolbar.appendChild(title);
  toolbar.appendChild(addBtn);
  editor.appendChild(toolbar);
  editor.appendChild(el('div', {class: 'tariff-required-note', text: 'Cada línea necesita precio base y al menos uno de estos identificadores: artículo, EAN o referencia de proveedor.'}));
  editor.appendChild(el('div', {class: 'tariff-lines', style: 'margin-top:9px'}));
  const hidden = el('textarea', {name, style: 'display:none', 'data-tariff-hidden': 'true'});
  hidden.dataset.widget = 'json';
  editor.appendChild(hidden);
  addBtn.addEventListener('click', () => supplierTariffAddLine(editor, {}));
  outer.appendChild(editor);
  if (propSchema.description) outer.appendChild(el('div', {class: 'hint', text: propSchema.description}));
  supplierTariffAddLine(editor, {});
  return outer;
}

function buildField(name, propSchema, required) {
  if (ACTIVE === 'tarifa_proveedor_actualizar' && name === 'lineas') {
    return buildSupplierTariffLinesField(name, propSchema, required);
  }
  const wrap = el('div', {class: 'field' + ((propSchema.type === 'array' || propSchema.type === 'object') ? ' json-field' : '')});
  const label = el('label', {}, [
    document.createTextNode(name + (required ? ' ' : '')),
  ]);
  if (required) label.appendChild(el('span', {class: 'req', text: '*'}));
  wrap.appendChild(label);

  let widget;
  const type = propSchema.type;
  const isUnion = Array.isArray(type);

  if (propSchema.enum) {
    widget = el('select', {name});
    if (!required) widget.appendChild(el('option', {value: ''}, [document.createTextNode('(no especificado)')]));
    for (const opt of propSchema.enum) {
      const o = el('option', {value: opt}, [document.createTextNode(String(opt))]);
      if (propSchema.default === opt) o.setAttribute('selected', 'selected');
      widget.appendChild(o);
    }
    widget.dataset.widget = 'plain';
  } else if (type === 'boolean') {
    widget = el('select', {name});
    widget.appendChild(el('option', {value: ''}, [document.createTextNode('(no especificado)')]));
    widget.appendChild(el('option', {value: 'true'}, [document.createTextNode('true')]));
    widget.appendChild(el('option', {value: 'false'}, [document.createTextNode('false')]));
    widget.dataset.widget = 'bool';
  } else if (type === 'integer' || type === 'number') {
    widget = el('input', {type: 'number', name});
    if (propSchema.default !== undefined) widget.value = propSchema.default;
    widget.dataset.widget = 'number';
  } else if (type === 'array' || type === 'object') {
    widget = el('textarea', {name, placeholder: JSON.stringify(exampleFor(propSchema), null, 2)});
    if (propSchema.default !== undefined) widget.value = JSON.stringify(propSchema.default, null, 2);
    widget.dataset.widget = 'json';
  } else {
    widget = el('input', {type: 'text', name});
    if (propSchema.default !== undefined) widget.value = propSchema.default;
    widget.dataset.widget = isUnion && type.includes('number') ? 'autonum' : 'plain';
  }
  wrap.appendChild(widget);
  if (propSchema.description) wrap.appendChild(el('div', {class: 'hint', text: propSchema.description}));
  return wrap;
}

function coerceValue(el, propSchema) {
  const raw = el.value;
  const widget = el.dataset.widget;
  if (raw === '' || raw === undefined) return undefined;
  if (widget === 'json') {
    return JSON.parse(raw); // puede lanzar, se captura fuera
  }
  if (widget === 'bool') return raw === 'true';
  if (widget === 'number') {
    const n = Number(raw);
    return Number.isNaN(n) ? raw : n;
  }
  if (widget === 'autonum') {
    if (raw.trim() !== '' && !Number.isNaN(Number(raw))) return Number(raw);
    return raw;
  }
  return raw;
}

// Solo para comodidad al rellenar el formulario del probador: algunos
// campos son texto libre en el esquema publico real (para no atarse a una
// lista cerrada en el contrato del MCP) pero en la practica solo se usan
// unos pocos valores conocidos. Aqui se muestran como desplegable con esos
// valores habituales; el valor que se envia sigue siendo el texto normal,
// no cambia el contrato de la herramienta.
const FIELD_ENUM_HINTS = {
  'mostrador_venta_gestion.tipo_documento': ['R', 'P', 'A', 'F', 'T', 'C'],
};

const SAMPLE_BUTTON_LABELS = {
  venta_documento_crear: 'Calculando precios...',
  mostrador_venta_gestion: 'Calculando precios...',
  mostrador_cobrar: 'Creando venta abierta...',
};

// No hay ninguna herramienta publica para listar ventas abiertas ya
// existentes (solo se puede consultar una si ya se sabe su clave
// EJERCI-NUMDOC). Para que mostrador_cobrar tenga siempre algo real que
// cobrar, "Cargar datos de prueba" llama de verdad a
// mostrador_venta_gestion (accion=guardar): a diferencia del resto de
// botones de datos de prueba, aqui SI hay una escritura real en Faro en
// el momento de pulsar el boton, antes de "Ejecutar". Se avisa en la propia
// tarjeta para que no pille por sorpresa.
const SAMPLE_BUTTON_WRITE_NOTE = {
  tarifa_proveedor_actualizar: (
    'Los datos de prueba solo rellenan el formulario y consultan una ficha existente; no modifican la base de datos hasta pulsar "Ejecutar". ' +
    'La ejecución de esta herramienta es CRÍTICA y actualiza ARTICULP; si activas actualizar_precio_venta también recalcula ARTICUL (precio y, si envías descripcion, también ART_DESCRI). ' +
    'Si activas generar_etiquetas y sube el PVP, además inserta una fila nueva en ETIQUE para reimpresión de etiquetas. ' +
    'Si activas dar_de_alta, una línea cuyo artículo no exista crea una ficha ARTICUL nueva además de ARTICULP (requiere también sección, tipo_iva, tipo_precio y unidad_medida en esa línea; campos en "Más campos"). ' +
    'El código de artículo de esa línea es opcional: si no lo informas, se toma de referencia_proveedor cuando activas usar_referencia_proveedor_como_codigo, o si no, se autogenera a partir de sección + proveedor (4 dígitos) + un contador, controlado por digitos_codigo_articulo y numerador_inicial.'
  ),
  mostrador_cobrar: (
    'No existe ninguna herramienta para listar ventas abiertas existentes, asi que ' +
    '"Cargar datos de prueba" crea una venta abierta real (via mostrador_venta_gestion) ' +
    'para poder rellenar "venta" y "total" con algo que sirva. Es una escritura real en ' +
    'Faro en el momento de pulsar el boton, no solo al pulsar "Ejecutar".'
  ),
};

function withFieldEnumHints(toolName, props) {
  const result = Object.assign({}, props);
  for (const [key, values] of Object.entries(FIELD_ENUM_HINTS)) {
    const sep = key.indexOf('.');
    const hintTool = key.slice(0, sep);
    const hintField = key.slice(sep + 1);
    if (hintTool === toolName && result[hintField]) {
      result[hintField] = Object.assign({}, result[hintField], {enum: values});
    }
  }
  return result;
}

function selectTool(name) {
  ACTIVE = name;
  OPEN_GROUPS.add(groupPrefix(name));
  renderList(document.getElementById('search').value);
  const tool = TOOLS.find(t => t.name === name);
  const main = document.getElementById('main');
  main.innerHTML = '';

  const schema = tool.inputSchema || {properties: {}, required: []};
  const props = withFieldEnumHints(tool.name, schema.properties || {});
  const required = schema.required || [];
  const access = toolAccessKind(tool);
  const write = access.kind !== 'read';

  const formCol = el('div', {class: 'form-col'});
  const card = el('div', {class: 'card'});
  const titleParts = [
    document.createTextNode(displayName(tool)),
    el('span', {class: 'tag ' + access.kind, text: access.label.toUpperCase()}),
  ];
  if (DISPLAY_NAME_OVERRIDES[tool.name]) {
    titleParts.push(el('span', {
      style: 'font-size: 12px; font-weight: 400; color: #64748b; margin-left: 4px;',
      text: '(' + tool.name + ')',
    }));
  }
  card.appendChild(el('h2', {}, titleParts));
  card.appendChild(el('div', {class: 'desc', text: tool.description || ''}));
  if (SAMPLE_BUTTON_WRITE_NOTE[tool.name]) {
    card.appendChild(el('div', {class: 'sample-write-note', text: SAMPLE_BUTTON_WRITE_NOTE[tool.name]}));
  }

  const form = el('form', {id: 'tool-form'});
  const fieldNames = orderedFieldNames(tool.name, props);
  if (fieldNames.length === 0) {
    form.appendChild(el('div', {class: 'hint', text: 'Esta herramienta no tiene parametros.'}));
  }
  if (tool.name === 'venta_documento_crear') {
    const topFields = ['centro', 'tipo_documento', 'serie'].filter(field => fieldNames.includes(field));
    const customerFields = ['cliente', 'subcliente'].filter(field => fieldNames.includes(field));
    const topGrid = el('div', {class: 'field-grid'});
    for (const fieldName of topFields) {
      topGrid.appendChild(buildField(fieldName, props[fieldName], required.includes(fieldName)));
    }
    form.appendChild(topGrid);
    const customerGrid = el('div', {class: 'field-grid two-cols'});
    for (const fieldName of customerFields) {
      customerGrid.appendChild(buildField(fieldName, props[fieldName], required.includes(fieldName)));
    }
    form.appendChild(customerGrid);
    const restFields = fieldNames.filter(field => !topFields.includes(field) && !customerFields.includes(field));
    appendFieldsCompactly(form, restFields, props, required);
  } else {
    appendFieldsCompactly(form, fieldNames, props, required);
  }

  const overrideToggle = el('span', {class: 'override-toggle', text: '+ JSON adicional / override manual'});
  const overrideWrap = el('div', {class: 'field json-field', style: 'display:none'});
  const overrideLabel = el('label', {text: 'Argumentos JSON (se fusionan sobre el formulario; gana el JSON)'});
  const overrideArea = el('textarea', {placeholder: '{\n  "algun_campo": "valor"\n}'});
  overrideWrap.appendChild(overrideLabel);
  overrideWrap.appendChild(overrideArea);
  overrideToggle.addEventListener('click', () => {
    overrideWrap.style.display = overrideWrap.style.display === 'none' ? 'block' : 'none';
  });
  form.appendChild(overrideToggle);
  form.appendChild(overrideWrap);

  let confirmCheckbox = null;
  if (write) {
    const confirmWrap = el('div', {class: 'confirm-write'});
    confirmCheckbox = el('input', {type: 'checkbox', id: 'confirm-write'});
    confirmWrap.appendChild(confirmCheckbox);
    confirmWrap.appendChild(el('label', {for: 'confirm-write', text:
      'Esta operacion escribe en la base de datos real de Faro. Confirmo que quiero ejecutarla.'}));
    form.appendChild(confirmWrap);
  }

  const errorBox = el('div', {class: 'client-error', style: 'display:none'});
  const actions = el('div', {class: 'actions'});
  const sampleBtn = el('button', {type: 'button', class: 'sample', text: 'Cargar datos de prueba'});
  const runBtn = el('button', {type: 'submit', class: 'run', text: 'Ejecutar'});
  if (write) runBtn.disabled = true;
  sampleBtn.addEventListener('click', async () => {
    const previousText = sampleBtn.textContent;
    sampleBtn.disabled = true;
    sampleBtn.textContent = SAMPLE_BUTTON_LABELS[tool.name] || 'Cargando...';
    errorBox.style.display = 'none';
    try {
      await fillSampleData(form, tool, props, fieldNames);
    } catch (e) {
      errorBox.textContent = 'No se pudieron cargar los datos de prueba: ' + e.message;
      errorBox.style.display = 'block';
    } finally {
      sampleBtn.disabled = false;
      sampleBtn.textContent = previousText;
    }
  });
  actions.appendChild(sampleBtn);
  actions.appendChild(runBtn);
  form.appendChild(actions);
  form.appendChild(errorBox);

  if (confirmCheckbox) {
    confirmCheckbox.addEventListener('change', () => { runBtn.disabled = !confirmCheckbox.checked; });
  }

  form.addEventListener('submit', (ev) => {
    ev.preventDefault();
    errorBox.style.display = 'none';
    const args = {};
    try {
      for (const name of fieldNames) {
        const inputEl = form.querySelector(`[name="${CSS.escape(name)}"]`);
        const value = coerceValue(inputEl, props[name]);
        if (value === undefined) continue;
        args[name] = value;
      }
      if (overrideArea.value.trim() !== '') {
        const overrides = JSON.parse(overrideArea.value);
        Object.assign(args, overrides);
      }
    } catch (e) {
      errorBox.textContent = 'Error en los parametros: ' + e.message;
      errorBox.style.display = 'block';
      return;
    }
    const missing = required.filter(r => !(r in args));
    if (missing.length) {
      errorBox.textContent = 'Faltan campos obligatorios: ' + missing.join(', ');
      errorBox.style.display = 'block';
      return;
    }
    if (tool.name === 'tarifa_proveedor_actualizar') {
      if (!Array.isArray(args.lineas) || args.lineas.length === 0) {
        errorBox.textContent = 'Añade al menos una línea de tarifa.';
        errorBox.style.display = 'block';
        return;
      }
      for (let index = 0; index < args.lineas.length; index += 1) {
        const line = args.lineas[index] || {};
        const hasIdentifier = [line.articulo, line.codigo_barras, line.referencia_proveedor].some(v => String(v || '').trim() !== '');
        if (!hasIdentifier) {
          errorBox.textContent = 'La línea ' + (index + 1) + ' necesita artículo, EAN o referencia de proveedor.';
          errorBox.style.display = 'block';
          return;
        }
        if (line.precio_base === undefined || line.precio_base === null || String(line.precio_base).trim() === '') {
          errorBox.textContent = 'La línea ' + (index + 1) + ' necesita precio base.';
          errorBox.style.display = 'block';
          return;
        }
      }
    }
    runTool(tool.name, args);
  });

  card.appendChild(form);
  formCol.appendChild(card);

  const resultCol = el('div', {class: 'result-col'});
  resultCol.appendChild(el('div', {class: 'card'}, [
    el('h2', {text: 'Resultado'}),
    el('div', {id: 'result-current'}, [el('div', {class: 'hint', text: 'Sin ejecutar todavia.'})]),
  ]));
  resultCol.appendChild(el('div', {class: 'card'}, [
    el('h2', {text: 'Historial de esta sesion'}),
    el('div', {id: 'history-list'}),
  ]));

  main.appendChild(formCol);
  main.appendChild(resultCol);
  renderHistory();
}

async function runTool(name, args) {
  const box = document.getElementById('result-current');
  box.innerHTML = '';
  box.appendChild(el('div', {class: 'result-meta'}, [
    el('span', {class: 'spinner'}),
    document.createTextNode('Ejecutando ' + name + '...'),
  ]));
  let payload;
  try {
    const res = await fetch('/api/call', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name, arguments: args}),
    });
    payload = await res.json();
  } catch (e) {
    box.innerHTML = '';
    box.appendChild(el('div', {class: 'result-box err', text: 'Error de red hablando con el servidor local: ' + e.message}));
    return;
  }
  showResult(name, args, payload);
}

function flattenRows(value, path) {
  if (Array.isArray(value)) {
    if (value.length === 0) return {rows: [], path};
    if (value.every(item => item && typeof item === 'object' && !Array.isArray(item))) {
      return {rows: value, path};
    }
    return {rows: value.map((item, index) => ({indice: index + 1, valor: item})), path};
  }
  if (value && typeof value === 'object') {
    const preferredKeys = ['items', 'rows', 'registros', 'datos', 'data', 'resultados', 'lineas', 'detalle'];
    for (const key of preferredKeys) {
      if (Array.isArray(value[key])) return flattenRows(value[key], path ? path + '.' + key : key);
    }
    for (const [key, nested] of Object.entries(value)) {
      if (Array.isArray(nested)) return flattenRows(nested, path ? path + '.' + key : key);
    }
    return {rows: [value], path};
  }
  return {rows: [], path};
}

function gridValueText(value) {
  if (value === null || value === undefined) return '';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function supplierTariffSummary(payload) {
  const data = payload && payload.result && payload.result.data;
  if (!data || typeof data !== 'object') return null;
  const wrap = el('div', {class: 'tariff-summary'});
  const items = [
    ['Líneas', data.lineas ?? 0],
    ['Altas', data.altas ?? 0],
    ['Modificaciones', data.modificaciones ?? 0],
    ['PVP actualizados', data.precios_venta_actualizados ?? 0],
  ];
  for (const [label, value] of items) {
    wrap.appendChild(el('div', {class: 'tariff-summary-item'}, [
      el('strong', {text: String(value)}),
      el('span', {text: label}),
    ]));
  }
  return wrap;
}

function supplierTariffGridRows(payload) {
  const data = payload && payload.result && payload.result.data;
  const rows = data && Array.isArray(data.resultados) ? data.resultados : null;
  if (!rows) return null;
  return rows.map(row => {
    const sale = row.precio_venta || {};
    const precios = sale.precios || {};
    return {
      linea: row.linea,
      articulo: row.articulo,
      accion: row.accion,
      resuelto_por: row.resuelto_por,
      referencia_proveedor: row.referencia_proveedor,
      precio_anterior: row.precio_anterior,
      precio_base: row.precio_base,
      coste_neto: row.coste_neto,
      pvp_modificado: sale.actualizado ? Boolean(sale.pvp_modificado) : '',
      pvp: precios.ART_PVP ?? '',
    };
  });
}

function makeGrid(payload, toolName) {
  const tariffRows = toolName === 'tarifa_proveedor_actualizar' ? supplierTariffGridRows(payload) : null;
  const result = payload ? payload.result : null;
  const source = tariffRows || (result && typeof result === 'object' && 'data' in result ? result.data : result);
  const grid = tariffRows ? {rows: tariffRows, path: 'data.resultados'} : flattenRows(source, result && source === result.data ? 'data' : 'result');
  const rows = grid.rows || [];
  if (!rows.length) {
    return {
      available: false,
      node: el('div', {class: 'grid-empty', text: 'No hay filas tabulares en este resultado.'}),
    };
  }
  const columns = [];
  const seen = new Set();
  for (const row of rows) {
    for (const key of Object.keys(row)) {
      if (!seen.has(key)) {
        seen.add(key);
        columns.push(key);
      }
    }
  }
  const table = el('table', {class: 'grid-table'});
  table.appendChild(el('thead', {}, [
    el('tr', {}, columns.map(col => el('th', {text: col}))),
  ]));
  const tbody = el('tbody');
  for (const row of rows) {
    tbody.appendChild(el('tr', {}, columns.map(col => el('td', {title: gridValueText(row[col]), text: gridValueText(row[col])}))));
  }
  table.appendChild(tbody);
  return {
    available: true,
    path: grid.path,
    count: rows.length,
    node: el('div', {class: 'grid-wrap'}, [table]),
  };
}

function showResult(name, args, payload) {
  const box = document.getElementById('result-current');
  box.innerHTML = '';
  const cls = payload.is_error ? 'err' : 'ok';
  const jsonView = el('pre', {class: 'result-box ' + cls, text: JSON.stringify(payload.result, null, 2)});
  const grid = makeGrid(payload, name);
  const gridView = grid.node;
  const preferGrid = name === 'tarifa_proveedor_actualizar' && grid.available && !payload.is_error;
  jsonView.style.display = preferGrid ? 'none' : 'block';
  gridView.style.display = preferGrid ? 'block' : 'none';
  const jsonBtn = el('button', {type: 'button', class: 'grid-toggle' + (preferGrid ? '' : ' active'), text: 'JSON'});
  const gridBtn = el('button', {type: 'button', class: 'grid-toggle' + (preferGrid ? ' active' : ''), text: 'Ver grid'});
  if (!grid.available) gridBtn.disabled = true;
  jsonBtn.addEventListener('click', () => {
    jsonView.style.display = 'block';
    gridView.style.display = 'none';
    jsonBtn.classList.add('active');
    gridBtn.classList.remove('active');
  });
  gridBtn.addEventListener('click', () => {
    jsonView.style.display = 'none';
    gridView.style.display = 'block';
    gridBtn.classList.add('active');
    jsonBtn.classList.remove('active');
  });
  const metaText = (payload.is_error ? 'ERROR' : 'OK') + ' · ' + (payload.elapsed_ms ?? '?') + ' ms · ' + new Date().toLocaleTimeString()
    + (grid.available ? ' · grid: ' + grid.count + ' filas (' + grid.path + ')' : '');
  box.appendChild(el('div', {class: 'result-meta'}, [
    el('span', {text: metaText}),
    el('span', {class: 'result-actions'}, [jsonBtn, gridBtn]),
  ]));
  if (name === 'tarifa_proveedor_actualizar' && !payload.is_error) {
    const summary = supplierTariffSummary(payload);
    if (summary) box.appendChild(summary);
  }
  box.appendChild(jsonView);
  box.appendChild(gridView);
  if (payload.traceback) {
    box.appendChild(el('pre', {class: 'result-box err', text: payload.traceback}));
  }
  HISTORY.unshift({name, args, payload, time: new Date().toLocaleTimeString()});
  if (HISTORY.length > 50) HISTORY.pop();
  renderHistory();
}

function renderHistory() {
  const listEl = document.getElementById('history-list');
  if (!listEl) return;
  listEl.innerHTML = '';
  if (HISTORY.length === 0) {
    listEl.appendChild(el('div', {class: 'hint', text: 'Todavia no has ejecutado nada en esta sesion.'}));
    return;
  }
  for (const h of HISTORY) {
    const item = el('div', {class: 'history-item', onclick: () => showResult(h.name, h.args, h.payload)}, [
      el('span', {}, [
        el('span', {class: h.payload.is_error ? 'h-err' : 'h-ok', text: h.payload.is_error ? 'ERR' : 'OK'}),
        document.createTextNode(' ' + h.name),
      ]),
      el('span', {class: 'h-time', text: h.time}),
    ]);
    listEl.appendChild(item);
  }
}

document.getElementById('search').addEventListener('input', (e) => renderList(e.target.value));
document.getElementById('settings-btn').addEventListener('click', openSettings);
document.getElementById('settings-cancel').addEventListener('click', closeSettings);
document.getElementById('settings-form').addEventListener('submit', saveSettings);
document.getElementById('settings-backdrop').addEventListener('click', (e) => {
  if (e.target.id === 'settings-backdrop') closeSettings();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && document.getElementById('settings-backdrop').classList.contains('open')) closeSettings();
});
loadTools().catch(e => {
  document.getElementById('main').innerHTML = '';
  document.getElementById('main').appendChild(
    el('div', {class: 'empty-state', text: 'No se pudo cargar la lista de herramientas: ' + e.message})
  );
});
</script>
</body>
</html>
"""


def main() -> None:
    args = parse_args()
    apply_env_overrides(args)
    runtime = faro_mcp.FaroToolRuntime()
    handler_cls = make_handler(runtime)
    httpd = ThreadingHTTPServer((args.host, args.port), handler_cls)
    httpd.daemon_threads = True
    url = f"http://{args.host}:{args.port}/"
    print(f"[faro-mcp-tester] Perfil de herramientas: {runtime.tool_profile} ({len(runtime.tools)} herramientas)")
    print(
        "[faro-mcp-tester] DSN=%s usuario_db=%s empresa=%s centro=%s usuario_auditoria=%s"
        % (
            os.environ.get("FARO_ODBC_DSN"),
            os.environ.get("FARO_DB_USER"),
            os.environ.get("FARO_EMPRESA"),
            os.environ.get("FARO_CENTRO"),
            os.environ.get("FARO_USUARIO"),
        )
    )
    print(f"[faro-mcp-tester] Escuchando en {url}  (Ctrl+C para parar)")
    if not args.no_abrir_navegador:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[faro-mcp-tester] Parado.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
