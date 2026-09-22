import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from telegram_luna import (
    Aplicacion,
    HttpJsonError,
    MemoriaChat,
    MotorIA,
    Propietario,
    TelegramBot,
    Vigilante,
    cargar_env,
    cargar_offset,
    dividir_texto,
    buscar_contexto,
    contradice_busqueda_real,
    guardar_offset,
    mensaje_busqueda_fallida,
    necesita_web,
    respuesta_resultados_directos,
)


class _TelegramFalso:
    def __init__(self):
        self.enviados = []

    def escribiendo(self, _chat_id):
        pass

    def enviar(self, chat_id, texto):
        self.enviados.append((chat_id, texto))


class _PropietarioFalso:
    def autorizar(self, _chat_id, _tipo_chat):
        return True, False


class _MemoriaFalsa:
    def __init__(self):
        self.guardado = None

    def obtener(self, _chat_id):
        return []

    def agregar(self, chat_id, pregunta, respuesta):
        self.guardado = (chat_id, pregunta, respuesta)

    def borrar(self, _chat_id):
        pass


def _aplicacion_falsa(motor):
    app = Aplicacion.__new__(Aplicacion)
    app.telegram = _TelegramFalso()
    app.motor = motor
    app.memoria_chat = _MemoriaFalsa()
    app.propietario = _PropietarioFalso()
    app.vigilante = None
    return app


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
        self.assertTrue(necesita_web("Hazme una búsqueda online sobre Albania"))
        self.assertTrue(necesita_web("/buscar@LacKurbin_bot Albania"))
        self.assertFalse(necesita_web("Hola, ¿qué tal?"))

    def test_limpia_comando_antes_de_buscar(self):
        with patch("telegram_luna.search_web", return_value=([{"title": "ok"}], [])) as buscar:
            consulta, resultados, _ = buscar_contexto(
                "Busca en Internet noticias de Albania hoy"
            )
        self.assertEqual(consulta, "noticias de Albania hoy")
        buscar.assert_called_once_with("noticias de Albania hoy")
        self.assertEqual(resultados[0]["title"], "ok")

    def test_bloquea_falsa_negacion_de_internet(self):
        self.assertTrue(contradice_busqueda_real("No tengo acceso a Internet."))
        self.assertTrue(contradice_busqueda_real("Abre tu navegador y obtén una API key."))
        self.assertFalse(contradice_busqueda_real("Encontré dos noticias recientes."))

    def test_fallo_no_inventa_resultados(self):
        mensaje = mensaje_busqueda_fallida("Albania", ["gdelt devolvió 0 resultados"])
        self.assertIn("no voy a inventar", mensaje)
        self.assertIn("GDELT", mensaje)

    def test_respuesta_directa_contiene_resultados_reales(self):
        texto = respuesta_resultados_directos(
            "Albania",
            [{"title": "Titular", "snippet": "Resumen", "url": "https://x.test"}],
        )
        self.assertIn("Búsqueda real completada", texto)
        self.assertIn("Titular", texto)


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

    def test_salud_detecta_api_activa_y_caida_sin_generar(self):
        llamadas = []

        def falso(url, **kwargs):
            llamadas.append((url, kwargs))
            if "api.groq.com" in url:
                return {"data": [{"id": "modelo-chat"}]}
            raise HttpJsonError(503, "temporalmente fuera de servicio")

        motor = MotorIA(
            {
                "GROQ_API_KEY": "secreto-a",
                "GEMINI_API_KEY": "secreto-b",
                "LUNA_PROVIDERS": "groq,gemini",
            },
            solicitante=falso,
        )
        estados = motor.comprobar_salud()
        self.assertEqual(estados["groq"], (True, "activo"))
        self.assertEqual(estados["gemini"], (False, "HTTP 503"))
        self.assertTrue(all(item[1].get("cuerpo") is None for item in llamadas))


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

    def test_offset_persiste_con_permisos_privados(self):
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / "memoria_telegram_offset.json"
            guardar_offset(321, ruta)
            self.assertEqual(cargar_offset(ruta), 321)
            self.assertEqual(os.stat(ruta).st_mode & 0o777, 0o600)


class TelegramTests(unittest.TestCase):
    def test_get_me_no_expone_token_en_cuerpo(self):
        llamadas = []

        def falso(url, **kwargs):
            llamadas.append((url, kwargs))
            return {"ok": True, "result": {"username": "LunaBot"}}

        bot = TelegramBot("123:secreto", solicitante=falso)
        self.assertEqual(bot.get_me()["username"], "LunaBot")
        self.assertNotIn("123:secreto", str(llamadas[0][1]))

    def test_no_llama_al_modelo_si_toda_busqueda_falla(self):
        class MotorFalso:
            def responder(self, _mensajes):
                raise AssertionError("no debe llamarse")

        app = _aplicacion_falsa(MotorFalso())
        with patch(
            "telegram_luna.buscar_contexto",
            return_value=("Albania", [], ["fuentes sin respuesta"]),
        ):
            app.manejar(
                {"chat": {"id": 1, "type": "private"}, "text": "/buscar Albania"}
            )
        self.assertIn("no voy a inventar", app.telegram.enviados[-1][1])

    def test_sustituye_negacion_del_modelo_por_resultados(self):
        class MotorFalso:
            def responder(self, _mensajes):
                return "No tengo acceso a Internet.", "groq", "modelo"

        resultado = {
            "title": "Titular comprobado",
            "url": "https://medio.test/noticia",
            "snippet": "Resumen comprobado",
            "source": "gdelt",
        }
        app = _aplicacion_falsa(MotorFalso())
        with patch(
            "telegram_luna.buscar_contexto",
            return_value=("Albania", [resultado], []),
        ), patch("telegram_luna.cargar_memoria_privada", return_value=({}, [])):
            app.manejar(
                {"chat": {"id": 1, "type": "private"}, "text": "/buscar Albania"}
            )
        respuesta = app.telegram.enviados[-1][1]
        self.assertIn("Titular comprobado", respuesta)
        self.assertIn("https://medio.test/noticia", respuesta)
        self.assertNotIn("No tengo acceso", respuesta)


class VigilanciaTests(unittest.TestCase):
    def test_avisa_caida_y_recuperacion(self):
        class TelegramFalso:
            def __init__(self):
                self.enviados = []

            def enviar(self, chat_id, texto):
                self.enviados.append((chat_id, texto))

        class MotorFalso:
            configurados = ["groq"]

            def __init__(self):
                self.estados = [
                    {"groq": (True, "activo")},
                    {"groq": (False, "HTTP 503")},
                    {"groq": (True, "activo")},
                ]

            def comprobar_salud(self):
                return self.estados.pop(0)

        telegram = TelegramFalso()
        propietario = Propietario(Path("/ruta/que/no/existe"))
        propietario.chat_id = 77
        vigilante = Vigilante(telegram, MotorFalso(), propietario)
        vigilante.revisar()
        vigilante.revisar()
        vigilante.revisar()
        textos = [texto for _, texto in telegram.enviados]
        self.assertTrue(any("Vigilancia activa" in texto for texto in textos))
        self.assertTrue(any("dejó de responder" in texto for texto in textos))
        self.assertTrue(any("volvió a funcionar" in texto for texto in textos))


if __name__ == "__main__":
    unittest.main()
