import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from poliglota_luna import (
    LENGUAJES_SOPORTADOS,
    MotorPoliglota,
    detectar_lenguaje,
    es_codigo_admitido,
)


class DeteccionTests(unittest.TestCase):
    def test_reconoce_lenguajes_principales(self):
        esperados = {
            "app.py": "Python",
            "bot.sh": "Shell",
            "web.js": "JavaScript",
            "tipos.ts": "TypeScript",
            "motor.rs": "Rust",
            "main.go": "Go",
            "App.kt": "Kotlin",
            "Dockerfile": "Dockerfile",
        }
        for nombre, lenguaje in esperados.items():
            self.assertEqual(detectar_lenguaje(nombre), lenguaje)

    def test_catalogo_es_amplio_pero_finito(self):
        self.assertGreaterEqual(len(LENGUAJES_SOPORTADOS), 30)
        self.assertTrue(es_codigo_admitido("consulta.sql"))
        self.assertFalse(es_codigo_admitido("foto.jpg"))


class ValidacionInternaTests(unittest.TestCase):
    def test_detecta_python_json_y_toml_invalidos(self):
        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            (raiz / "roto.py").write_text("def roto(:\n", encoding="utf-8")
            (raiz / "roto.json").write_text("{mal", encoding="utf-8")
            (raiz / "roto.toml").write_text("a = [", encoding="utf-8")
            resultados = MotorPoliglota(raiz).analizar_proyecto()
        self.assertEqual({item.estado for item in resultados}, {"error"})

    def test_valida_formatos_sin_ejecutarlos(self):
        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            archivos = {
                "bien.py": "x = 1\n",
                "bien.json": json.dumps({"x": 1}),
                "bien.jsonl": '{"x": 1}\n{"x": 2}\n',
                "bien.toml": 'nombre = "Luna"\n',
                "bien.xml": "<luna><ok /></luna>",
                "bien.ini": "[luna]\nactiva=true\n",
                "bien.sql": "SELECT (1 + 2);",
                "bien.ts": "const valor: number = 1;",
            }
            for nombre, contenido in archivos.items():
                (raiz / nombre).write_text(contenido, encoding="utf-8")
            resultados = MotorPoliglota(raiz).analizar_proyecto()
        self.assertTrue(resultados)
        self.assertTrue(all(item.estado == "correcto" for item in resultados))

    def test_no_lee_privados_backups_ni_dependencias(self):
        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            (raiz / ".env").write_text("TOKEN=secreto", encoding="utf-8")
            (raiz / "memoria_privada.json").write_text("{roto", encoding="utf-8")
            for carpeta in ("node_modules", ".luna_backups", "resultados"):
                (raiz / carpeta).mkdir()
                (raiz / carpeta / "roto.js").write_text("function (", encoding="utf-8")
            (raiz / "bien.py").write_text("x = 1\n", encoding="utf-8")
            rutas = [item.ruta for item in MotorPoliglota(raiz).analizar_proyecto()]
        self.assertEqual(rutas, ["bien.py"])

    def test_rechaza_ruta_fuera_del_proyecto(self):
        with tempfile.TemporaryDirectory() as temporal, tempfile.TemporaryDirectory() as fuera:
            raiz = Path(temporal)
            archivo = Path(fuera) / "externo.py"
            archivo.write_text("x = 1\n", encoding="utf-8")
            resultado = MotorPoliglota(raiz).analizar_archivo(archivo)
        self.assertEqual(resultado.estado, "error")
        self.assertIn("fuera", resultado.detalle)


class ValidacionExternaTests(unittest.TestCase):
    def test_javascript_usa_node_check_sin_shell(self):
        llamadas = []

        def ejecutar(args, **kwargs):
            llamadas.append((args, kwargs))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            archivo = raiz / "app.js"
            archivo.write_text("const luna = true;\n", encoding="utf-8")
            with patch("poliglota_luna.shutil.which", return_value="/usr/bin/node"):
                resultado = MotorPoliglota(raiz, ejecutor=ejecutar).analizar_archivo(archivo)
        self.assertEqual(resultado.estado, "correcto")
        self.assertEqual(llamadas[0][0][1], "--check")
        self.assertNotIn("shell", llamadas[0][1])

    def test_herramienta_ausente_no_inventa_error(self):
        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            archivo = raiz / "main.go"
            archivo.write_text("package main\n", encoding="utf-8")
            with patch("poliglota_luna.shutil.which", return_value=None):
                resultado = MotorPoliglota(raiz).analizar_archivo(archivo)
        self.assertEqual(resultado.estado, "sin_validador")
        self.assertIn("no está instalado", resultado.detalle)

    def test_resumen_no_incluye_contenido_privado(self):
        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            (raiz / ".env").write_text("TOKEN=supersecreto", encoding="utf-8")
            (raiz / "ok.py").write_text("x = 1\n", encoding="utf-8")
            resumen = MotorPoliglota(raiz).resumen()
        self.assertNotIn("supersecreto", resumen)
        self.assertIn("Motor políglota", resumen)


if __name__ == "__main__":
    unittest.main()
