import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import luna_control


class LunaControlTests(unittest.TestCase):
    def test_variables_configuradas_no_devuelve_valores(self):
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / ".env"
            ruta.write_text(
                "GROQ_API_KEY=secreto-123\n"
                "BRAVE_SEARCH_API_KEY=busqueda-privada\n"
                "OTRA=visible\n"
                "export TELEGRAM_TOKEN='privado'\n",
                encoding="utf-8",
            )
            resultado = luna_control.variables_configuradas(ruta)
        self.assertEqual(
            resultado,
            ["GROQ_API_KEY", "BRAVE_SEARCH_API_KEY", "TELEGRAM_TOKEN"],
        )
        self.assertNotIn("secreto-123", repr(resultado))

    def test_raiz_respeta_luna_dir(self):
        with tempfile.TemporaryDirectory() as temporal, mock.patch.dict(os.environ, {"LUNA_DIR": temporal}):
            self.assertEqual(luna_control.raiz_luna(), Path(temporal).resolve())

    def test_estado_detecta_nucleo_completo(self):
        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            for nombre in luna_control.ARCHIVOS_NUCLEO:
                (raiz / nombre).touch()
            with mock.patch("luna_control.servicio_estado", return_value="run"):
                self.assertEqual(luna_control.mostrar_estado(raiz), 0)

    def test_estado_falla_si_falta_nucleo(self):
        with tempfile.TemporaryDirectory() as temporal, mock.patch(
            "luna_control.servicio_estado", return_value="down"
        ):
            self.assertEqual(luna_control.mostrar_estado(Path(temporal)), 1)

    def test_control_sin_sv_es_seguro(self):
        with mock.patch("luna_control.shutil.which", return_value=None):
            self.assertEqual(luna_control.controlar_servicios("up"), 1)


if __name__ == "__main__":
    unittest.main()
