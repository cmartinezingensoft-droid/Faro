import json
from faro_bridge import main

def legacy(argv):
    result = {
        "politica_articulo_no_encontrado": argv[1] if len(argv) > 1 else "detener",
        "politica_precio_compra": argv[2] if len(argv) > 2 else "mantener",
        "solo_gestion_documental": len(argv) > 4 and argv[4].lower() in {"1", "true", "si"},
        "selected_names": json.loads(argv[5]) if len(argv) > 5 else [],
        "persistir_propuesta": True,
    }
    if len(argv) > 3 and argv[3]: result["limite"] = int(argv[3])
    return result

if __name__ == "__main__":
    raise SystemExit(main("entrada_almacen_pendientes_integrar", legacy))
