import json
import tempfile
import unittest
from pathlib import Path

import inventario_luna


class InventarioLunaTests(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.base = Path(self.temporal.name)
        self.raiz = self.base / "luna"
        self.descargas = self.base / "downloads"
        self.raiz.mkdir()
        self.descargas.mkdir()
        (self.raiz / "luna.py").write_text("print('luna')\n", encoding="utf-8")

    def tearDown(self):
        self.temporal.cleanup()

    def ejecutar(self):
        return inventario_luna.inventariar(self.raiz, [self.descargas], integrar=True)

    def test_omite_env_y_no_copia_secreto(self):
        (self.descargas / ".env").write_text("GROQ_API_KEY=VALOR_FICTICIO_LARGO\n", encoding="utf-8")
        informe = self.ejecutar()
        self.assertEqual(informe["archivos"][0]["categoria"], "PRIVADO_NO_COPIADO")
        self.assertFalse((self.raiz / "componentes_descargados").exists())

    def test_detecta_clave_embebida(self):
        ruta = self.descargas / "luna_claves.sh"
        ruta.write_text("TELEGRAM_TOKEN=VALOR_FICTICIO_LARGO\n", encoding="utf-8")
        informe = self.ejecutar()
        self.assertEqual(informe["archivos"][0]["categoria"], "PRIVADO_NO_COPIADO")

    def test_archiva_script_de_nube_sin_ejecutarlo(self):
        ruta = self.descargas / "luna_nube.py"
        ruta.write_text("# /opt/luna\nprint('no ejecutar')\n", encoding="utf-8")
        informe = self.ejecutar()
        entrada = informe["archivos"][0]
        self.assertEqual(entrada["categoria"], "SOLO_NUBE")
        self.assertTrue((self.raiz / entrada["copia_local"]).exists())

    def test_archiva_instalador_historico(self):
        ruta = self.descargas / "instalar_luna_vieja.sh"
        ruta.write_text("#!/bin/sh\n# luna antigua\n", encoding="utf-8")
        informe = self.ejecutar()
        self.assertEqual(informe["archivos"][0]["categoria"], "INSTALADOR_HISTORICO")

    def test_detecta_duplicado_activo(self):
        (self.descargas / "otra_luna.py").write_text("print('luna')\n", encoding="utf-8")
        informe = self.ejecutar()
        self.assertEqual(informe["archivos"][0]["categoria"], "DUPLICADO_ACTIVO")

    def test_python_roto_va_a_incompatibles(self):
        (self.descargas / "luna_rota.py").write_text("def roto(:\n", encoding="utf-8")
        informe = self.ejecutar()
        self.assertEqual(informe["archivos"][0]["categoria"], "INCOMPATIBLE")

    def test_genera_informes_privados(self):
        informe = self.ejecutar()
        ruta = self.raiz / "inventario_descargas_luna.json"
        self.assertTrue(ruta.exists())
        self.assertEqual(json.loads(ruta.read_text(encoding="utf-8"))["archivos"], informe["archivos"])
        self.assertEqual(ruta.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
