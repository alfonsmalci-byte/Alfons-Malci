import io
import os
import tempfile
import unittest
import zipfile
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
    comprobar_busquedas_reales,
    comprobar_nueve_conexiones,
    contradice_busqueda_real,
    extraer_texto_documento,
    guardar_offset,
    mensaje_busqueda_fallida,
    necesita_web,
    respuesta_resultados_directos,
    _puntuacion_modelo,
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


class _RendimientoFalso:
    def ordenar(self, nombres):
        return list(nombres)

    def registrar(self, *_args, **_kwargs):
        pass

    def resumen(self, nombres):
        return ", ".join(nombres)


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
            with patch.dict(os.environ, {"A": "valor-viejo"}):
                valores = cargar_env(ruta)
                self.assertEqual(os.environ["A"], "uno")
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
        self.assertIn("gdelt", mensaje)

    def test_respuesta_directa_contiene_resultados_reales(self):
        texto = respuesta_resultados_directos(
            "Albania",
            [{"title": "Titular", "snippet": "Resumen", "url": "https://x.test"}],
        )
        self.assertIn("Búsqueda real completada", texto)
        self.assertIn("Titular", texto)


class MotorIATests(unittest.TestCase):
    def test_comprueba_exactamente_las_nueve_conexiones(self):
        entorno = {
            "GROQ_API_KEY": "a",
            "GEMINI_API_KEY": "b",
            "CEREBRAS_API_KEY": "c",
            "OPENROUTER_API_KEY": "d",
            "DEEPSEEK_API_KEY": "e",
            "OPENAI_API_KEY": "f",
            "TELEGRAM_TOKEN": "1:t",
            "TAVILY_API_KEY": "g",
            "BRAVE_SEARCH_API_KEY": "h",
        }
        motor = MotorIA(entorno, rendimiento=_RendimientoFalso())
        salud = {
            nombre: (True, "activo")
            for nombre in ("groq", "gemini", "cerebras", "openrouter", "deepseek", "openai")
        }
        with patch.object(motor, "comprobar_salud", return_value=salud), patch(
            "telegram_luna.comprobar_busquedas_reales",
            return_value={
                "tavily": (True, "búsqueda real"),
                "brave": (True, "búsqueda real"),
            },
        ):
            estados = comprobar_nueve_conexiones(
                entorno,
                motor,
                telegram_ok=True,
            )
        self.assertEqual(len(estados), 9)
        self.assertTrue(all(ok for ok, _detalle in estados.values()))

    def test_busquedas_reales_prueban_tavily_y_brave_una_vez(self):
        entorno = {
            "TAVILY_API_KEY": "tavily",
            "BRAVE_SEARCH_API_KEY": "brave",
        }
        resultado = [{"title": "Python", "url": "https://python.org"}]
        with patch("telegram_luna.tavily_search", return_value=resultado) as tavily, patch(
            "telegram_luna.brave_search", return_value=resultado
        ) as brave:
            estados = comprobar_busquedas_reales(entorno)
        self.assertTrue(estados["tavily"][0])
        self.assertTrue(estados["brave"][0])
        tavily.assert_called_once()
        brave.assert_called_once()

    def test_modelo_estable_mas_nuevo_recibe_mayor_puntuacion(self):
        self.assertGreater(
            _puntuacion_modelo("gemini", "gemini-4.0-flash"),
            _puntuacion_modelo("gemini", "gemini-2.5-flash"),
        )
        self.assertGreater(
            _puntuacion_modelo("openai", "gpt-6-mini"),
            _puntuacion_modelo("openai", "gpt-5-mini"),
        )

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
            rendimiento=_RendimientoFalso(),
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
            rendimiento=_RendimientoFalso(),
        )
        texto, _, _ = motor.responder([{"role": "user", "content": "hola"}])
        self.assertEqual(texto, "ok")
        self.assertIn("max_completion_tokens", cuerpos[0])
        self.assertIn("max_tokens", cuerpos[1])

    def test_informa_cuando_no_hay_claves(self):
        motor = MotorIA(
            {"LUNA_PROVIDERS": "groq"},
            solicitante=lambda *_a, **_k: {},
            rendimiento=_RendimientoFalso(),
        )
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
            rendimiento=_RendimientoFalso(),
        )
        estados = motor.comprobar_salud()
        self.assertEqual(estados["groq"], (True, "activo"))
        self.assertEqual(estados["gemini"], (False, "HTTP 503"))
        self.assertTrue(all(item[1].get("cuerpo") is None for item in llamadas))

    def test_imagen_solo_usa_proveedor_multimodal(self):
        cuerpos = []

        def falso(url, **kwargs):
            if url.endswith("/models"):
                return {"data": [{"id": "gemini-2.5-flash"}]}
            cuerpos.append(kwargs["cuerpo"])
            return {"choices": [{"message": {"content": "veo una bicicleta"}}]}

        motor = MotorIA(
            {
                "GROQ_API_KEY": "solo-texto",
                "GEMINI_API_KEY": "vision",
                "LUNA_PROVIDERS": "groq,gemini",
            },
            solicitante=falso,
            rendimiento=_RendimientoFalso(),
        )
        texto, proveedor, _ = motor.responder_imagen(
            [{"role": "user", "content": "¿Qué ves?"}],
            b"imagen",
            "image/jpeg",
        )
        self.assertEqual(texto, "veo una bicicleta")
        self.assertEqual(proveedor, "gemini")
        contenido = cuerpos[0]["messages"][0]["content"]
        self.assertEqual(contenido[0]["type"], "text")
        self.assertTrue(contenido[1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))

    def test_audio_se_transcribe_con_groq(self):
        llamadas = []

        def multipart(url, **kwargs):
            llamadas.append((url, kwargs))
            return {"text": "enciende la búsqueda"}

        motor = MotorIA(
            {"GROQ_API_KEY": "secreto"},
            solicitante_multipart=multipart,
            rendimiento=_RendimientoFalso(),
        )
        texto = motor.transcribir_audio(b"audio", "nota.ogg", "audio/ogg")
        self.assertEqual(texto, "enciende la búsqueda")
        self.assertIn("audio/transcriptions", llamadas[0][0])
        self.assertEqual(llamadas[0][1]["campos"]["model"], "whisper-large-v3-turbo")


class DocumentosTests(unittest.TestCase):
    def test_extrae_txt(self):
        self.assertEqual(
            extraer_texto_documento(b"Hola Luna", "nota.txt", "text/plain"),
            "Hola Luna",
        )

    def test_acepta_archivos_de_codigo_poliglota(self):
        casos = {
            "motor.rs": "fn main() {}",
            "servidor.go": "package main",
            "app.js": "const luna = true;",
            "consulta.sql": "SELECT 1;",
            "Main.kt": "fun main() {}",
        }
        for nombre, contenido in casos.items():
            self.assertEqual(
                extraer_texto_documento(contenido.encode(), nombre), contenido
            )

    def test_extrae_docx_sin_ejecutar_contenido(self):
        xml = b"""<?xml version='1.0'?>
        <w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>
          <w:body><w:p><w:r><w:t>Primer texto</w:t></w:r></w:p>
          <w:p><w:r><w:t>Segundo texto</w:t></w:r></w:p></w:body>
        </w:document>"""
        salida = io.BytesIO()
        with zipfile.ZipFile(salida, "w") as archivo:
            archivo.writestr("word/document.xml", xml)
        texto = extraer_texto_documento(
            salida.getvalue(),
            "prueba.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertEqual(texto, "Primer texto\nSegundo texto")

    def test_rechaza_formato_desconocido(self):
        with self.assertRaisesRegex(Exception, "Formato no admitido"):
            extraer_texto_documento(b"x", "programa.exe")


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

    def test_comando_automejora_devuelve_estado_sin_llamar_modelo(self):
        class MotorFalso:
            def responder(self, _mensajes):
                raise AssertionError("no debe llamar al modelo")

        app = _aplicacion_falsa(MotorFalso())
        app._estado_automejora = lambda: "🧠 siete agentes activos"
        app.manejar(
            {"chat": {"id": 1, "type": "private"}, "text": "/automejora"}
        )
        self.assertIn("siete agentes", app.telegram.enviados[-1][1])

    def test_comando_reparar_fuerza_ciclo_seguro(self):
        class MotorFalso:
            pass

        app = _aplicacion_falsa(MotorFalso())
        app._forzar_automejora = lambda actualizar=False: (
            "actualización comprobada" if actualizar else "reparación comprobada"
        )
        app.manejar(
            {"chat": {"id": 1, "type": "private"}, "text": "/reparar"}
        )
        self.assertIn("reparación comprobada", app.telegram.enviados[-1][1])

    def test_comando_lenguajes_no_llama_al_modelo(self):
        class MotorFalso:
            def responder(self, _mensajes):
                raise AssertionError("no debe llamar al modelo")

        app = _aplicacion_falsa(MotorFalso())
        with patch("telegram_luna.resumen_poliglota", return_value="🌐 38 lenguajes"):
            app.manejar(
                {"chat": {"id": 1, "type": "private"}, "text": "/lenguajes"}
            )
        self.assertIn("lenguajes", app.telegram.enviados[-1][1])

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

    def test_foto_llega_al_modelo_de_vision(self):
        class MotorFalso:
            def __init__(self):
                self.recibido = None

            def responder_imagen(self, mensajes, imagen, mime):
                self.recibido = (mensajes, imagen, mime)
                return "Es una bicicleta.", "gemini", "flash"

        motor = MotorFalso()
        app = _aplicacion_falsa(motor)
        app.telegram.descargar_archivo = lambda _file_id: b"foto-real"
        with patch("telegram_luna.cargar_memoria_privada", return_value=({}, [])):
            app.manejar(
                {
                    "chat": {"id": 1, "type": "private"},
                    "caption": "¿Qué hay en esta foto?",
                    "photo": [{"file_id": "abc", "file_size": 100}],
                }
            )
        self.assertEqual(motor.recibido[1:], (b"foto-real", "image/jpeg"))
        self.assertIn("Es una bicicleta", app.telegram.enviados[-1][1])
        self.assertIn("[Imagen]", app.memoria_chat.guardado[1])


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
