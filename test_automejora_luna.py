import base64
import io
import json
import os
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import automejora_luna
from automejora_luna import Hallazgo, SistemaAutomejora
from telegram_luna import RendimientoProveedores


class _NotificadorFalso:
    def __init__(self):
        self.mensajes = []

    def enviar(self, texto):
        self.mensajes.append(texto)
        return True


def _crear_raiz(ruta: Path, version="4.0.0"):
    contenidos = {
        "luna.py": "def search_web(*_a, **_k):\n    return [], []\n",
        "telegram_luna.py": (
            "def responder_imagen():\n    pass\n"
            "def transcribir_audio():\n    pass\n"
            "AYUDA = '/automejora'\n"
        ),
        "sabiduria_luna.py": f'NUCLEO_VERSION = "{version}"\n',
        "gestor_keys_luna.py": "ACTIVO = True\n",
        "automejora_luna.py": (
            "class SistemaAutomejora:\n    pass\n"
            "def sellar_version_buena():\n    pass\n"
        ),
        "poliglota_luna.py": (
            "LENGUAJES_SOPORTADOS = ('Python',)\n"
            "class MotorPoliglota:\n    pass\n"
        ),
    }
    for nombre, contenido in contenidos.items():
        (ruta / nombre).write_text(contenido, encoding="utf-8")
    (ruta / "test_smoke.py").write_text(
        "import unittest\n\n"
        "class Smoke(unittest.TestCase):\n"
        "    def test_ok(self):\n"
        "        self.assertTrue(True)\n",
        encoding="utf-8",
    )


class UtilidadesTests(unittest.TestCase):
    def test_limpia_secretos(self):
        texto = automejora_luna.limpiar_secreto("Authorization: Bearer abc-super-secreto")
        self.assertNotIn("abc-super-secreto", texto)

    def test_version_directorio(self):
        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            _crear_raiz(raiz, "3.4.5")
            self.assertEqual(automejora_luna.version_directorio(raiz), "3.4.5")
            self.assertGreater(
                automejora_luna.version_tuple("3.4.5"),
                automejora_luna.version_tuple("3.4.4"),
            )


class RendimientoTests(unittest.TestCase):
    def test_aprende_sin_poner_pago_por_delante(self):
        with tempfile.TemporaryDirectory() as temporal:
            rendimiento = RendimientoProveedores(Path(temporal) / "rendimiento.json")
            for _ in range(3):
                rendimiento.registrar("groq", False, 5, "HTTP 429")
                rendimiento.registrar("gemini", True, 1)
                rendimiento.registrar("openai", True, 0.2)
            orden = rendimiento.ordenar(["groq", "gemini", "openai"])
            self.assertEqual(orden[0], "gemini")
            self.assertLess(orden.index("groq"), orden.index("openai"))

    def test_estadisticas_persisten_con_permiso_privado(self):
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "rendimiento.json"
            RendimientoProveedores(ruta).registrar("groq", True, 0.5)
            recargado = RendimientoProveedores(ruta)
            self.assertEqual(recargado.datos["groq"]["exitos"], 1)
            self.assertEqual(stat.S_IMODE(ruta.stat().st_mode), 0o600)


class AgentesTests(unittest.TestCase):
    def _sistema(self, raiz):
        return SistemaAutomejora(
            raiz,
            prefix=Path(raiz) / "prefix",
            notificador=_NotificadorFalso(),
        )

    def test_sella_y_restaura_codigo_roto(self):
        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            _crear_raiz(raiz)
            sistema = self._sistema(raiz)
            ok, _ = sistema.sellar_version_buena()
            self.assertTrue(ok)
            (raiz / "luna.py").write_text("def roto(:\n", encoding="utf-8")
            with patch("automejora_luna.shutil.which", return_value=None), patch(
                "automejora_luna.importlib.util.find_spec", return_value=object()
            ):
                hallazgos = sistema.inspeccionar()
                reparaciones = sistema.reparar(hallazgos)
            self.assertTrue(any(item.codigo == "codigo_invalido" for item in hallazgos))
            self.assertTrue(any(item.ok for item in reparaciones))
            self.assertIn("def search_web", (raiz / "luna.py").read_text(encoding="utf-8"))

    def test_restaura_codigo_sql_roto(self):
        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            _crear_raiz(raiz)
            sql = raiz / "consulta.sql"
            sql.write_text("SELECT (1 + 2);\n", encoding="utf-8")
            sistema = self._sistema(raiz)
            self.assertTrue(sistema.sellar_version_buena()[0])
            sql.write_text("SELECT (\n", encoding="utf-8")
            with patch("automejora_luna.shutil.which", return_value=None), patch(
                "automejora_luna.importlib.util.find_spec", return_value=object()
            ):
                hallazgos = sistema.inspeccionar()
                reparaciones = sistema.reparar(hallazgos)
            self.assertTrue(
                any(item.codigo == "codigo_poliglota_invalido" for item in hallazgos)
            )
            self.assertTrue(any(item.ok for item in reparaciones))
            self.assertEqual(sql.read_text(encoding="utf-8"), "SELECT (1 + 2);\n")

    def test_codigo_nuevo_roto_va_a_cuarentena_recuperable(self):
        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            _crear_raiz(raiz)
            sistema = self._sistema(raiz)
            self.assertTrue(sistema.sellar_version_buena()[0])
            nuevo = raiz / "nuevo.json"
            nuevo.write_text("{roto", encoding="utf-8")
            with patch("automejora_luna.shutil.which", return_value=None), patch(
                "automejora_luna.importlib.util.find_spec", return_value=object()
            ):
                resultados = sistema.reparar(sistema.inspeccionar())
            self.assertFalse(nuevo.exists())
            self.assertTrue(list(sistema.backups.glob("cuarentena-*/nuevo.json")))
            self.assertTrue(
                any(item.codigo == "codigo_poliglota_invalido" and item.ok for item in resultados)
            )

    def test_promueve_mejora_valida_despues_de_tres_ciclos(self):
        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            _crear_raiz(raiz)
            sistema = self._sistema(raiz)
            self.assertTrue(sistema.sellar_version_buena()[0])
            nuevo = raiz / "mejora.ts"
            nuevo.write_text("const nivel: number = 4;\n", encoding="utf-8")
            self.assertIn("1/3", sistema._observar_evolucion(False))
            self.assertIn("2/3", sistema._observar_evolucion(False))
            self.assertIn("promovido", sistema._observar_evolucion(False))
            manifiesto = json.loads(
                (sistema.baseline / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertIn("mejora.ts", manifiesto["files"])

    def test_protege_permisos_y_elimina_lock_obsoleto(self):
        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            _crear_raiz(raiz)
            env = raiz / ".env"
            env.write_text("GROQ_API_KEY=falsa\n", encoding="utf-8")
            os.chmod(env, 0o644)
            (raiz / ".luna_telegram.lock").write_text("999999999", encoding="utf-8")
            sistema = self._sistema(raiz)
            with patch("automejora_luna.shutil.which", return_value=None), patch(
                "automejora_luna.importlib.util.find_spec", return_value=object()
            ):
                resultados = sistema.reparar(sistema.inspeccionar())
            self.assertEqual(stat.S_IMODE(env.stat().st_mode), 0o600)
            self.assertFalse((raiz / ".luna_telegram.lock").exists())
            self.assertGreaterEqual(sum(item.ok for item in resultados), 2)

    def test_memoria_corrupta_vuelve_a_copia_valida(self):
        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            _crear_raiz(raiz)
            memoria = raiz / "memoria_telegram.json"
            memoria.write_text('{"1": []}', encoding="utf-8")
            sistema = self._sistema(raiz)
            sistema.snapshot_memoria()
            memoria.write_text("{roto", encoding="utf-8")
            with patch("automejora_luna.shutil.which", return_value=None), patch(
                "automejora_luna.importlib.util.find_spec", return_value=object()
            ):
                resultados = sistema.reparar(sistema.inspeccionar())
            self.assertEqual(json.loads(memoria.read_text(encoding="utf-8")), {"1": []})
            self.assertTrue(any(item.codigo == "json_corrupto" and item.ok for item in resultados))

    def test_no_borra_memoria_si_no_hay_copia(self):
        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            _crear_raiz(raiz)
            memoria = raiz / "memoria_telegram.json"
            memoria.write_text("{roto", encoding="utf-8")
            sistema = self._sistema(raiz)
            resultado = sistema.reparar(
                [Hallazgo("json_corrupto", "alto", "memoria_telegram.json: JSON", "restaurar_memoria")]
            )[0]
            self.assertFalse(resultado.ok)
            self.assertEqual(memoria.read_text(encoding="utf-8"), "{roto")

    def test_ciclo_guarda_estado_de_siete_agentes(self):
        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            _crear_raiz(raiz)
            sistema = self._sistema(raiz)
            sistema.estado["ultima_revision_actualizacion_epoch"] = 10**12
            sistema.estado["ultimo_intento_pypdf"] = 10**12
            with patch("automejora_luna.shutil.which", return_value=None), patch(
                "automejora_luna.importlib.util.find_spec", return_value=object()
            ):
                informe = sistema.ciclo(avisar=False)
            self.assertTrue(informe["ok"])
            self.assertEqual(len(informe["agentes"]), 7)
            self.assertTrue((raiz / "estado_automejora.json").is_file())


class ActualizadorTests(unittest.TestCase):
    def test_no_instala_version_antigua(self):
        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            _crear_raiz(raiz, "3.0.0")
            sistema = SistemaAutomejora(raiz, notificador=_NotificadorFalso())
            remoto = base64.b64encode(b'NUCLEO_VERSION = "2.9.0"\n').decode()
            sistema._http_bytes = lambda _url, _limite: json.dumps(
                {"content": remoto}
            ).encode()
            with patch.dict(os.environ, {"LUNA_AUTO_UPDATE": "1"}):
                estado, detalle = sistema.comprobar_actualizacion(forzar=True)
            self.assertEqual(estado, "actual")
            self.assertIn("3.0.0", detalle)

    def test_rechaza_zip_con_ruta_peligrosa(self):
        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            _crear_raiz(raiz)
            archivo = raiz / "malo.zip"
            with zipfile.ZipFile(archivo, "w") as salida:
                salida.writestr("../fuera.py", "x = 1")
            sistema = SistemaAutomejora(raiz, notificador=_NotificadorFalso())
            with self.assertRaisesRegex(RuntimeError, "ruta no segura"):
                sistema._extraer_actualizacion(archivo, raiz / "extraido")

    def test_rechaza_candidato_que_pierde_vision(self):
        with tempfile.TemporaryDirectory() as temporal:
            raiz = Path(temporal)
            _crear_raiz(raiz)
            (raiz / "telegram_luna.py").write_text("AYUDA='/automejora'\n", encoding="utf-8")
            sistema = SistemaAutomejora(raiz, notificador=_NotificadorFalso())
            ok, detalle = sistema._validar_candidato(raiz)
            self.assertFalse(ok)
            self.assertIn("pierde capacidades", detalle)


if __name__ == "__main__":
    unittest.main()
