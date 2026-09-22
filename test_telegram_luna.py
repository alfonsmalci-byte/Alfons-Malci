import os
import tempfile
import unittest
from pathlib import Path

from telegram_luna import (
    HttpJsonError,
    MemoriaChat,
    MotorIA,
    Propietario,
    TelegramBot,
    cargar_env,
    dividir_texto,
    necesita_web,
)


class ConfiguracionTests(unittest.TestCase):
    def test_carga_env_con_comillas_y_export(self):
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / ".env"
            ruta.write_text('A="uno"\nexport B=dos\n# comentario\n', encoding="utf-8")
            valores = cargar_env(ruta)
        self.assertEqual(valores, {"A": "uno", "B": "dos"})

    def test_divide_respuesta_para_telegram(self):
        partes = dividir_texto("a" * 100, limite=30)
        self.assertGreater(len(partes), 1)
        self.assertTrue(all(len(parte) <= 30 for parte in partes))
        self.assertEqual("".join(partes), "a" * 100)

    def test_detecta_consulta_web(self):
        self.assertTrue(necesita_web("Busca en Internet noticias de hoy"))
        self.assertFalse(necesita_web("Hola, ¿qué tal?"))


class MotorIATests(unittest.TestCase):
    def test_cambia_de_proveedor_si_el_primero_falla(self):
        llamadas = []

        def falso(url, **kwargs):
            llamadas.append(url)
            if url.endswith("/models"):
                return {"data": [{"id": "modelo-chat"}]}
            if "api.groq.com" in url:
                raise HttpJsonError(429, "límite")
            return {"choices": [{"message": {"content": "respuesta real"}}]}

        motor = MotorIA(
            {
                "GROQ_API_KEY": "secreto-a",
                "GEMINI_API_KEY": "secreto-b",
                "LUNA_PROVIDERS": "groq,gemini",
            },
            solicitante=falso,
        )
        texto, proveedor, _ = motor.responder([{"role": "user", "content": "hola"}])
        self.assertEqual(texto, "respuesta real")
        self.assertEqual(proveedor, "gemini")
        self.assertTrue(any("api.groq.com" in url for url in llamadas))
        self.assertTrue(any("generativelanguage.googleapis.com" in url for url in llamadas))

    def test_adapta_max_tokens_si_api_lo_pide(self):
        cuerpos = []

        def falso(url, **kwargs):
            if url.endswith("/models"):
                return {"data": [{"id": "openrouter/free"}]}
            cuerpos.append(kwargs["cuerpo"].copy())
            if len(cuerpos) == 1:
                raise HttpJsonError(400, "max_completion_tokens no admitido")
            return {"choices": [{"message": {"content": "ok"}}]}

        motor = MotorIA(
            {"OPENROUTER_API_KEY": "secreto", "LUNA_PROVIDERS": "openrouter"},
            solicitante=falso,
        )
        texto, _, _ = motor.responder([{"role": "user", "content": "hola"}])
        self.assertEqual(texto, "ok")
        self.assertIn("max_completion_tokens", cuerpos[0])
        self.assertIn("max_tokens", cuerpos[1])

    def test_informa_cuando_no_hay_claves(self):
        motor = MotorIA({"LUNA_PROVIDERS": "groq"}, solicitante=lambda *_a, **_k: {})
        self.assertEqual(motor.configurados, [])
        with self.assertRaisesRegex(Exception, "no hay proveedores configurados"):
            motor.responder([{"role": "user", "content": "hola"}])


class MemoriaYPropietarioTests(unittest.TestCase):
    def test_memoria_persiste_y_se_borra(self):
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "memoria_telegram.json"
            memoria = MemoriaChat(ruta)
            memoria.agregar(123, "hola", "buenas")
            recargada = MemoriaChat(ruta)
            self.assertEqual(len(recargada.obtener(123)), 2)
            self.assertEqual(os.stat(ruta).st_mode & 0o777, 0o600)
            recargada.borrar(123)
            self.assertEqual(recargada.obtener(123), [])

    def test_primer_chat_privado_se_vincula_y_otro_no(self):
        with tempfile.TemporaryDirectory() as temporal:
            propietario = Propietario(Path(temporal) / ".telegram_owner")
            self.assertEqual(propietario.autorizar(10, "private"), (True, True))
            self.assertEqual(propietario.autorizar(10, "private"), (True, False))
            self.assertEqual(propietario.autorizar(11, "private"), (False, False))

    def test_grupo_no_puede_reclamar_bot_sin_propietario(self):
        with tempfile.TemporaryDirectory() as temporal:
            propietario = Propietario(Path(temporal) / ".telegram_owner")
            self.assertEqual(propietario.autorizar(-100, "group"), (False, False))


class TelegramTests(unittest.TestCase):
    def test_get_me_no_expone_token_en_cuerpo(self):
        llamadas = []

        def falso(url, **kwargs):
            llamadas.append((url, kwargs))
            return {"ok": True, "result": {"username": "LunaBot"}}

        bot = TelegramBot("123:secreto", solicitante=falso)
        self.assertEqual(bot.get_me()["username"], "LunaBot")
        self.assertNotIn("123:secreto", str(llamadas[0][1]))


if __name__ == "__main__":
    unittest.main()
