import unittest

import faro_mcp


class Phase3PublicSchemaValidationTests(unittest.TestCase):
    def test_union_number_or_string_accepts_both_representations(self):
        for value in (10, 10.5, "10.5"):
            with self.subTest(value=value):
                translated = faro_mcp.translate_public_arguments(
                    "stock_regularizar",
                    {"articulo": "A1", "centro": 0, "cantidad": value},
                )
                self.assertEqual(translated["cantid"], value)

    def test_union_number_or_string_rejects_invalid_types_and_boolean(self):
        for value in (True, False, [], {}, None):
            with self.subTest(value=value):
                with self.assertRaises(faro_mcp.FaroError) as ctx:
                    faro_mcp.translate_public_arguments(
                        "stock_regularizar",
                        {"articulo": "A1", "centro": 0, "cantidad": value},
                    )
                self.assertIn("number o string", str(ctx.exception))

    def test_offer_discounts_enforce_max_items(self):
        valid = {
            "tipo_oferta": "T",
            "nombre": "Oferta",
            "fecha_inicio": "2027-01-01",
            "fecha_fin": "2027-01-31",
            "articulos": [
                {"articulo": "A1", "precio_oferta": 9.99, "descuentos": [10, 5]}
            ],
        }
        translated = faro_mcp.translate_public_arguments("oferta_crear", valid)
        self.assertEqual(translated["articulos"][0]["descuentos"], [10, 5])

        invalid = dict(valid)
        invalid["articulos"] = [
            {"articulo": "A1", "precio_oferta": 9.99, "descuentos": [10, 5, 2]}
        ]
        with self.assertRaises(faro_mcp.FaroError) as ctx:
            faro_mcp.translate_public_arguments("oferta_crear", invalid)
        self.assertIn("permite como maximo 2 elemento(s)", str(ctx.exception))

    def test_offer_discounts_validate_each_union_item(self):
        invalid = {
            "tipo_oferta": "T",
            "nombre": "Oferta",
            "fecha_inicio": "2027-01-01",
            "fecha_fin": "2027-01-31",
            "articulos": [
                {"articulo": "A1", "precio_oferta": 9.99, "descuentos": [10, True]}
            ],
        }
        with self.assertRaises(faro_mcp.FaroError) as ctx:
            faro_mcp.translate_public_arguments("oferta_crear", invalid)
        self.assertIn("arguments.articulos[0].descuentos[1]", str(ctx.exception))
        self.assertIn("number o string", str(ctx.exception))

    def test_existing_simple_type_error_messages_are_preserved(self):
        with self.assertRaises(faro_mcp.FaroError) as ctx:
            faro_mcp.translate_public_arguments(
                "stock_consultar", {"articulo": 123}
            )
        self.assertIn("debe ser texto", str(ctx.exception))

    def test_min_items_still_applies(self):
        with self.assertRaises(faro_mcp.FaroError) as ctx:
            faro_mcp.translate_public_arguments(
                "stock_trasvasar",
                {"centro_origen": 1, "centro_destino": 2, "lineas": []},
            )
        self.assertIn("requiere al menos 1 elemento(s)", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
