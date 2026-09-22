import io
import os
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import gestor_keys_luna as gestor


class RespuestaFalsa:
    def __init__(self, codigo=200, cuerpo=b"{}"):
        self.status = codigo
        self.cuerpo = cuerpo

    def getcode(self):
        return self.status

    def read(self, _limite=-1):
        return self.cuerpo

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class ArchivoEnvTests(unittest.TestCase):
    def test_actualiza_env_sin_borrar_otros_valores(self):
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / ".env"
            ruta.write_text("GROQ_API_KEY=antigua\nOTRA=cosa\n", encoding="utf-8")
            gestor.actualizar_env(
                {"GROQ_API_KEY": "nueva-segura", "GEMINI_API_KEY": "gemini-nueva"},
                ruta,
            )
            valores = gestor.leer_env(ruta)
            self.assertEqual(valores["GROQ_API_KEY"], "nueva-segura")
            self.assertEqual(valores["GEMINI_API_KEY"], "gemini-nueva")
            self.assertEqual(valores["OTRA"], "cosa")
            self.assertEqual(os.stat(ruta).st_mode & 0o777, 0o600)
            self.assertEqual(
                gestor.leer_env(ruta.with_name(".env.antes_de_rotar"))["GROQ_API_KEY"],
                "antigua",
            )

    def test_rechaza_salto_de_linea_en_una_clave(self):
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / ".env"
            ruta.write_text("A=uno\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "caracteres"):
                gestor.actualizar_env({"A": "valor\nINYECCION=si"}, ruta)

    def test_correo_se_guarda_fuera_del_repo_con_permiso_privado(self):
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "cuenta.json"
            gestor.guardar_correo("alfons@example.com", ruta)
            self.assertEqual(gestor.cargar_correo(ruta), "alfons@example.com")
            self.assertEqual(os.stat(ruta).st_mode & 0o777, 0o600)


class ValidacionTests(unittest.TestCase):
    def test_clave_activa_no_se_muestra(self):
        clave = "secreto-super-privado"
        resultado = gestor.validar_clave(
            gestor.PROVEEDORES["groq"],
            clave,
            abridor=lambda *_a, **_k: RespuestaFalsa(200),
        )
        self.assertEqual(resultado.estado, "activa")
        texto = gestor.texto_estado({
            nombre: resultado if nombre == "groq" else gestor.Resultado(nombre, "no_configurada", "falta", False)
            for nombre in gestor.ORDEN
        })
        self.assertNotIn(clave, texto)
        self.assertIn(gestor.huella(clave), texto)

    def test_http_401_es_rechazada(self):
        def rechaza(peticion, **_kwargs):
            raise urllib.error.HTTPError(peticion.full_url, 401, "no", {}, None)

        resultado = gestor.validar_clave(
            gestor.PROVEEDORES["openai"], "clave-falsa", abridor=rechaza
        )
        self.assertEqual(resultado.estado, "rechazada")
        self.assertFalse(resultado.utilizable)

    def test_http_429_conserva_clave_como_autenticada(self):
        def limita(peticion, **_kwargs):
            raise urllib.error.HTTPError(peticion.full_url, 429, "límite", {}, None)

        resultado = gestor.validar_clave(
            gestor.PROVEEDORES["groq"], "clave-limitada", abridor=limita
        )
        self.assertEqual(resultado.estado, "limitada")
        self.assertTrue(resultado.utilizable)

    def test_gemini_envia_clave_en_cabecera_no_en_url(self):
        peticion = gestor._peticion(gestor.PROVEEDORES["gemini"], "gemini-secreta")
        self.assertNotIn("gemini-secreta", peticion.full_url)
        self.assertEqual(peticion.get_header("X-goog-api-key"), "gemini-secreta")

    def test_validacion_paralela_incluye_faltantes(self):
        resultados = gestor.validar_todas(
            {"GROQ_API_KEY": "groq-secreta"},
            abridor=lambda *_a, **_k: RespuestaFalsa(200),
        )
        self.assertEqual(resultados["groq"].estado, "activa")
        self.assertEqual(resultados["gemini"].estado, "no_configurada")


class RotacionYVigilanciaTests(unittest.TestCase):
    def test_no_reemplaza_clave_si_la_nueva_falla(self):
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / ".env"
            ruta.write_text("GROQ_API_KEY=antigua\n", encoding="utf-8")
            fallo = gestor.Resultado("groq", "rechazada", "HTTP 401", True, "abc")
            with patch("gestor_keys_luna.abrir_url"), patch(
                "gestor_keys_luna.getpass.getpass", return_value="nueva-invalida"
            ), patch("gestor_keys_luna.validar_clave", return_value=fallo), redirect_stdout(io.StringIO()):
                self.assertFalse(gestor.rotar("groq", ruta_env=ruta))
            self.assertEqual(gestor.leer_env(ruta)["GROQ_API_KEY"], "antigua")

    def test_reemplaza_solo_despues_de_validar(self):
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / ".env"
            ruta.write_text("GROQ_API_KEY=antigua\n", encoding="utf-8")
            activa = gestor.Resultado("groq", "activa", "HTTP 200", True, "abc")
            with patch("gestor_keys_luna.abrir_url"), patch(
                "gestor_keys_luna.getpass.getpass", return_value="nueva-valida"
            ), patch("gestor_keys_luna.validar_clave", return_value=activa), patch(
                "gestor_keys_luna._reiniciar_luna"
            ), redirect_stdout(io.StringIO()):
                self.assertTrue(gestor.rotar("groq", ruta_env=ruta))
            self.assertEqual(gestor.leer_env(ruta)["GROQ_API_KEY"], "nueva-valida")

    def test_avisa_caida_y_recuperacion(self):
        actual_caida = {
            "groq": gestor.Resultado("groq", "rechazada", "HTTP 401", True)
        }
        avisos = gestor.cambios_estado(
            {"groq": {"estado": "activa"}}, actual_caida
        )
        self.assertIn("dejó de funcionar", avisos[0])
        actual_vuelta = {
            "groq": gestor.Resultado("groq", "activa", "HTTP 200", True)
        }
        avisos = gestor.cambios_estado(
            {"groq": {"estado": "rechazada"}}, actual_vuelta
        )
        self.assertIn("volvió a funcionar", avisos[0])


if __name__ == "__main__":
    unittest.main()
