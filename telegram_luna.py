#!/usr/bin/env python3
"""Puente privado entre Telegram y Luna para Termux.

No necesita paquetes externos. Lee las claves desde ``.env``, mantiene la
memoria de conversación solo en el teléfono y cambia de proveedor cuando una
API no responde.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from luna import search_web
from sabiduria_luna import cargar_memoria_privada, construir_prompt


ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
OWNER_FILE = ROOT / ".telegram_owner"
CHAT_MEMORY_FILE = ROOT / "memoria_telegram.json"
LOCK_FILE = ROOT / ".luna_telegram.lock"
MAX_USER_CHARS = 6_000
MAX_HISTORY_MESSAGES = 16
MAX_HISTORY_CHARS = 24_000
TELEGRAM_TEXT_LIMIT = 3_900
USER_AGENT = "Luna-Telegram/1.0"


class LunaError(RuntimeError):
    """Error controlado que no contiene secretos."""


class HttpJsonError(LunaError):
    def __init__(self, status: int, detail: str):
        self.status = int(status)
        self.detail = detail[:500]
        super().__init__(f"HTTP {self.status}: {self.detail}")


def cargar_env(ruta: Path = ENV_FILE) -> dict[str, str]:
    """Carga un archivo .env sencillo sin imprimir ni sobrescribir secretos."""
    if not ruta.exists():
        raise LunaError(f"No existe {ruta}")

    valores: dict[str, str] = {}
    for numero, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        if linea.startswith("export "):
            linea = linea[7:].lstrip()
        if "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        clave = clave.strip()
        valor = valor.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", clave):
            raise LunaError(f"Nombre inválido en .env, línea {numero}")
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        valores[clave] = valor
        os.environ.setdefault(clave, valor)
    return valores


def _detalle_seguro(datos: bytes | str) -> str:
    if isinstance(datos, bytes):
        texto = datos.decode("utf-8", errors="replace")
    else:
        texto = str(datos)
    try:
        objeto = json.loads(texto)
        texto = str(objeto.get("error", objeto))
    except (json.JSONDecodeError, AttributeError):
        pass
    texto = re.sub(r"(?i)(bearer|token|api[_ -]?key)\s*[:=]?\s*[^\s,}]+", r"\1=***", texto)
    return " ".join(texto.split())[:500]


def pedir_json(
    url: str,
    *,
    metodo: str = "GET",
    cuerpo: dict | None = None,
    cabeceras: dict[str, str] | None = None,
    timeout: int = 60,
) -> dict:
    datos = None
    headers = {"User-Agent": USER_AGENT, **(cabeceras or {})}
    if cuerpo is not None:
        datos = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    peticion = urllib.request.Request(url, data=datos, headers=headers, method=metodo)
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
            contenido = respuesta.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        detalle = _detalle_seguro(error.read())
        raise HttpJsonError(error.code, detalle or error.reason) from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise LunaError(f"Red: {type(error).__name__}: {error.reason if hasattr(error, 'reason') else error}") from None
    try:
        salida = json.loads(contenido)
    except json.JSONDecodeError:
        raise LunaError("La API devolvió una respuesta que no es JSON") from None
    if not isinstance(salida, dict):
        raise LunaError("La API devolvió un JSON inesperado")
    return salida


@dataclass(frozen=True)
class Proveedor:
    nombre: str
    clave_env: str
    base_url: str
    modelos_base: tuple[str, ...]
    cabeceras_extra: tuple[tuple[str, str], ...] = ()


PROVEEDORES = {
    "groq": Proveedor(
        "groq",
        "GROQ_API_KEY",
        "https://api.groq.com/openai/v1",
        ("openai/gpt-oss-20b", "llama-3.3-70b-versatile"),
    ),
    "gemini": Proveedor(
        "gemini",
        "GEMINI_API_KEY",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        ("gemini-2.5-flash",),
    ),
    "cerebras": Proveedor(
        "cerebras",
        "CEREBRAS_API_KEY",
        "https://api.cerebras.ai/v1",
        ("gpt-oss-120b", "qwen-3.8-27b"),
    ),
    "openrouter": Proveedor(
        "openrouter",
        "OPENROUTER_API_KEY",
        "https://openrouter.ai/api/v1",
        ("openrouter/free",),
        (
            ("HTTP-Referer", "https://github.com/alfonsmalci-byte/Alfons-Malci"),
            ("X-Title", "Luna"),
        ),
    ),
    "deepseek": Proveedor(
        "deepseek",
        "DEEPSEEK_API_KEY",
        "https://api.deepseek.com",
        ("deepseek-chat", "deepseek-flash"),
    ),
    "openai": Proveedor(
        "openai",
        "OPENAI_API_KEY",
        "https://api.openai.com/v1",
        ("gpt-4.1-mini", "gpt-4o-mini"),
    ),
}

ORDEN_POR_DEFECTO = ("groq", "gemini", "cerebras", "openrouter", "deepseek", "openai")


def _modelo_valido(modelo: str) -> bool:
    texto = modelo.lower()
    excluidos = (
        "audio",
        "embedding",
        "image",
        "moderation",
        "realtime",
        "rerank",
        "speech",
        "transcri",
        "tts",
        "whisper",
        "dall-e",
    )
    return bool(modelo) and not any(palabra in texto for palabra in excluidos)


def _puntuacion_modelo(proveedor: str, modelo: str) -> int:
    texto = modelo.lower()
    puntos = 0
    preferencias = {
        "groq": (("gpt-oss-20b", 100), ("llama-3.3-70b", 95), ("qwen", 70)),
        "gemini": (("flash", 100), ("gemini", 50), ("pro", 20)),
        "cerebras": (("gpt-oss-120b", 100), ("qwen", 90), ("llama", 70)),
        "openrouter": (("openrouter/free", 200), (":free", 120), ("auto", 80)),
        "deepseek": (("chat", 100), ("flash", 90), ("reasoner", 60)),
        "openai": (("mini", 100), ("nano", 90), ("gpt-5", 80), ("gpt-4.1", 70)),
    }
    for fragmento, valor in preferencias.get(proveedor, ()):
        if fragmento in texto:
            puntos = max(puntos, valor)
    if "preview" in texto or "experimental" in texto:
        puntos -= 15
    return puntos


def _extraer_texto(respuesta: dict) -> str:
    try:
        contenido = respuesta["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LunaError("El proveedor respondió sin texto utilizable") from None
    if isinstance(contenido, str):
        return contenido.strip()
    if isinstance(contenido, list):
        partes = []
        for parte in contenido:
            if isinstance(parte, dict) and isinstance(parte.get("text"), str):
                partes.append(parte["text"])
        return "".join(partes).strip()
    raise LunaError("El proveedor respondió con un formato de texto desconocido")


class MotorIA:
    def __init__(self, entorno: dict[str, str], solicitante=pedir_json):
        self.entorno = entorno
        self.solicitante = solicitante
        orden_texto = entorno.get("LUNA_PROVIDERS", ",".join(ORDEN_POR_DEFECTO))
        solicitados = [item.strip().lower() for item in orden_texto.split(",") if item.strip()]
        self.orden = [nombre for nombre in solicitados if nombre in PROVEEDORES]
        self._modelos_cache: dict[str, list[str]] = {}
        self.ultimo_proveedor = "ninguno"
        self.ultimo_modelo = "ninguno"
        try:
            self.max_tokens = max(128, min(2_000, int(entorno.get("LUNA_MAX_TOKENS", "700"))))
        except ValueError:
            self.max_tokens = 700

    @property
    def configurados(self) -> list[str]:
        return [
            nombre
            for nombre in self.orden
            if self.entorno.get(PROVEEDORES[nombre].clave_env, "").strip()
        ]

    def _cabeceras(self, proveedor: Proveedor) -> dict[str, str]:
        clave = self.entorno.get(proveedor.clave_env, "").strip()
        return {
            "Authorization": f"Bearer {clave}",
            **dict(proveedor.cabeceras_extra),
        }

    def _listar_modelos(self, proveedor: Proveedor) -> list[str]:
        if proveedor.nombre in self._modelos_cache:
            return self._modelos_cache[proveedor.nombre]

        override = self.entorno.get(f"{proveedor.nombre.upper()}_MODEL", "").strip()
        if override:
            self._modelos_cache[proveedor.nombre] = [override]
            return [override]

        modelos = list(proveedor.modelos_base)
        try:
            datos = self.solicitante(
                proveedor.base_url.rstrip("/") + "/models",
                cabeceras=self._cabeceras(proveedor),
                timeout=25,
            )
            for item in datos.get("data", []):
                if not isinstance(item, dict):
                    continue
                modelo = str(item.get("id") or item.get("name") or "").removeprefix("models/")
                if _modelo_valido(modelo):
                    modelos.append(modelo)
        except LunaError:
            pass

        modelos = list(dict.fromkeys(modelos))
        modelos.sort(key=lambda m: _puntuacion_modelo(proveedor.nombre, m), reverse=True)
        self._modelos_cache[proveedor.nombre] = modelos[:8]
        return self._modelos_cache[proveedor.nombre]

    def _completar(self, proveedor: Proveedor, modelo: str, mensajes: list[dict]) -> str:
        url = proveedor.base_url.rstrip("/") + "/chat/completions"
        cuerpo = {
            "model": modelo,
            "messages": mensajes,
            "max_completion_tokens": self.max_tokens,
            "stream": False,
        }
        try:
            respuesta = self.solicitante(
                url,
                metodo="POST",
                cuerpo=cuerpo,
                cabeceras=self._cabeceras(proveedor),
                timeout=90,
            )
        except HttpJsonError as error:
            if error.status == 400 and "max_completion_tokens" in error.detail:
                cuerpo["max_tokens"] = cuerpo.pop("max_completion_tokens")
                respuesta = self.solicitante(
                    url,
                    metodo="POST",
                    cuerpo=cuerpo,
                    cabeceras=self._cabeceras(proveedor),
                    timeout=90,
                )
            else:
                raise
        texto = _extraer_texto(respuesta)
        if not texto:
            raise LunaError("El proveedor devolvió una respuesta vacía")
        return texto

    def responder(self, mensajes: list[dict]) -> tuple[str, str, str]:
        errores: list[str] = []
        for nombre in self.orden:
            proveedor = PROVEEDORES[nombre]
            if not self.entorno.get(proveedor.clave_env, "").strip():
                continue
            for modelo in self._listar_modelos(proveedor)[:4]:
                try:
                    texto = self._completar(proveedor, modelo, mensajes)
                    self.ultimo_proveedor = nombre
                    self.ultimo_modelo = modelo
                    return texto, nombre, modelo
                except HttpJsonError as error:
                    errores.append(f"{nombre}/{modelo}: HTTP {error.status}")
                    if error.status in (401, 402, 403, 429):
                        break
                except LunaError as error:
                    errores.append(f"{nombre}/{modelo}: {error}")
        resumen = "; ".join(errores[-8:]) or "no hay proveedores configurados"
        raise LunaError("Ningún proveedor pudo responder. " + resumen)


class MemoriaChat:
    def __init__(self, ruta: Path = CHAT_MEMORY_FILE):
        self.ruta = ruta
        self.datos: dict[str, list[dict[str, str]]] = {}
        self._cargar()

    def _cargar(self) -> None:
        if not self.ruta.exists() or self.ruta.stat().st_size > 1_000_000:
            return
        try:
            datos = json.loads(self.ruta.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return
        if isinstance(datos, dict):
            self.datos = {
                str(chat): [m for m in mensajes if isinstance(m, dict)]
                for chat, mensajes in datos.items()
                if isinstance(mensajes, list)
            }

    def obtener(self, chat_id: int) -> list[dict[str, str]]:
        return list(self.datos.get(str(chat_id), []))

    def agregar(self, chat_id: int, usuario: str, asistente: str) -> None:
        clave = str(chat_id)
        mensajes = self.datos.setdefault(clave, [])
        mensajes.extend(
            [
                {"role": "user", "content": usuario},
                {"role": "assistant", "content": asistente},
            ]
        )
        mensajes[:] = mensajes[-MAX_HISTORY_MESSAGES:]
        while sum(len(str(m.get("content", ""))) for m in mensajes) > MAX_HISTORY_CHARS:
            mensajes.pop(0)
        self._guardar()

    def borrar(self, chat_id: int) -> None:
        self.datos.pop(str(chat_id), None)
        self._guardar()

    def _guardar(self) -> None:
        temporal = self.ruta.with_name(".memoria_telegram.tmp")
        temporal.write_text(json.dumps(self.datos, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(temporal, 0o600)
        os.replace(temporal, self.ruta)
        os.chmod(self.ruta, 0o600)


class Propietario:
    def __init__(self, ruta: Path = OWNER_FILE):
        self.ruta = ruta
        self.chat_id: int | None = None
        if ruta.exists():
            try:
                self.chat_id = int(ruta.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                self.chat_id = None

    def autorizar(self, chat_id: int, tipo_chat: str) -> tuple[bool, bool]:
        """Devuelve (autorizado, recién_vinculado)."""
        if self.chat_id is None and tipo_chat == "private":
            self.ruta.write_text(str(chat_id), encoding="utf-8")
            os.chmod(self.ruta, 0o600)
            self.chat_id = chat_id
            return True, True
        return self.chat_id == chat_id, False


class TelegramBot:
    def __init__(self, token: str, solicitante=pedir_json):
        if not token or ":" not in token:
            raise LunaError("TELEGRAM_TOKEN falta o tiene formato inválido")
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.solicitante = solicitante

    def llamar(self, metodo: str, cuerpo: dict | None = None, timeout: int = 60) -> dict:
        datos = self.solicitante(
            f"{self.base_url}/{metodo}",
            metodo="POST",
            cuerpo=cuerpo or {},
            timeout=timeout,
        )
        if not datos.get("ok"):
            raise LunaError(f"Telegram rechazó {metodo}: {_detalle_seguro(str(datos.get('description', 'error')))}")
        return datos

    def get_me(self) -> dict:
        return self.llamar("getMe").get("result", {})

    def preparar_long_polling(self) -> None:
        self.llamar("deleteWebhook", {"drop_pending_updates": False})

    def actualizaciones(self, offset: int | None) -> list[dict]:
        cuerpo: dict = {"timeout": 45, "allowed_updates": ["message"]}
        if offset is not None:
            cuerpo["offset"] = offset
        return self.llamar("getUpdates", cuerpo, timeout=55).get("result", [])

    def escribiendo(self, chat_id: int) -> None:
        try:
            self.llamar("sendChatAction", {"chat_id": chat_id, "action": "typing"})
        except LunaError:
            pass

    def enviar(self, chat_id: int, texto: str) -> None:
        for parte in dividir_texto(texto):
            self.llamar("sendMessage", {"chat_id": chat_id, "text": parte})


def dividir_texto(texto: str, limite: int = TELEGRAM_TEXT_LIMIT) -> list[str]:
    texto = texto.strip() or "(respuesta vacía)"
    partes: list[str] = []
    while len(texto) > limite:
        corte = texto.rfind("\n", 0, limite)
        if corte < limite // 2:
            corte = texto.rfind(" ", 0, limite)
        if corte < limite // 2:
            corte = limite
        partes.append(texto[:corte].strip())
        texto = texto[corte:].strip()
    if texto:
        partes.append(texto)
    return partes


def necesita_web(texto: str) -> bool:
    texto = texto.lower()
    patrones = (
        "/buscar",
        "busca en internet",
        "noticias",
        "hoy",
        "ahora mismo",
        "actualizado",
        "último",
        "ultima",
        "última",
        "precio actual",
        "clima",
        "tiempo en ",
    )
    return any(patron in texto for patron in patrones)


def buscar_contexto(texto: str) -> tuple[str, list[dict], list[str]]:
    consulta = texto
    if texto.lower().startswith("/buscar"):
        consulta = texto[len("/buscar") :].strip()
    if not consulta:
        return "", [], ["Falta escribir qué quieres buscar."]
    resultados, errores = search_web(consulta)
    return consulta, resultados[:5], errores


def fuentes_texto(resultados: list[dict]) -> str:
    lineas = []
    for resultado in resultados[:4]:
        titulo = str(resultado.get("title", "Fuente")).strip() or "Fuente"
        url = str(resultado.get("url", "")).strip()
        if url:
            lineas.append(f"- {titulo}: {url}")
    return "\n".join(lineas)


AYUDA = """Luna está conectada.

Escríbeme normalmente.
/buscar tema — consulta Internet y responde con fuentes
/estado — muestra conexión y último proveedor
/reiniciar — borra esta conversación local
/ayuda — muestra estos comandos"""


class Aplicacion:
    def __init__(self, telegram: TelegramBot, motor: MotorIA):
        self.telegram = telegram
        self.motor = motor
        self.memoria_chat = MemoriaChat()
        self.propietario = Propietario()

    def _estado(self) -> str:
        configurados = ", ".join(self.motor.configurados) or "ninguno"
        return (
            "✅ Telegram conectado\n"
            f"🧠 Proveedores configurados: {configurados}\n"
            f"🔄 Último proveedor: {self.motor.ultimo_proveedor}\n"
            f"🤖 Último modelo: {self.motor.ultimo_modelo}\n"
            "🔒 Memoria y claves: solo en Termux"
        )

    def manejar(self, mensaje: dict) -> None:
        chat = mensaje.get("chat") or {}
        chat_id = chat.get("id")
        tipo_chat = str(chat.get("type", ""))
        if not isinstance(chat_id, int):
            return
        autorizado, nuevo = self.propietario.autorizar(chat_id, tipo_chat)
        if not autorizado:
            self.telegram.enviar(chat_id, "Este es un bot privado.")
            return

        texto = mensaje.get("text")
        if not isinstance(texto, str):
            self.telegram.enviar(chat_id, "Por ahora envíame texto.")
            return
        texto = texto.strip()
        if not texto:
            return
        if nuevo:
            print(f"🔒 Propietario vinculado: chat {chat_id}")

        comando = texto.split(maxsplit=1)[0].split("@", 1)[0].lower()
        if comando in ("/start", "/ayuda", "/help"):
            self.telegram.enviar(chat_id, AYUDA)
            return
        if comando in ("/estado", "/proveedores"):
            self.telegram.enviar(chat_id, self._estado())
            return
        if comando in ("/reiniciar", "/borrar_conversacion"):
            self.memoria_chat.borrar(chat_id)
            self.telegram.enviar(chat_id, "✅ Conversación local borrada. La memoria privada de Alfons sigue intacta.")
            return
        if len(texto) > MAX_USER_CHARS:
            self.telegram.enviar(chat_id, f"El mensaje es demasiado largo. Máximo: {MAX_USER_CHARS} caracteres.")
            return

        self.telegram.escribiendo(chat_id)
        resultados_web: list[dict] = []
        errores_web: list[str] = []
        pregunta = texto
        if necesita_web(texto):
            pregunta, resultados_web, errores_web = buscar_contexto(texto)
            if not pregunta:
                self.telegram.enviar(chat_id, errores_web[0])
                return

        memoria_privada, advertencias = cargar_memoria_privada(ROOT / "memoria_privada.json")
        prompt = construir_prompt(memoria=memoria_privada, contexto_web=resultados_web)
        prompt += (
            "\n\nResponde en el idioma del usuario, primero con la conclusión y después con "
            "los pasos mínimos. Estás hablando por Telegram. No afirmes que consultaste "
            "Internet si CONTEXTO WEB está vacío."
        )
        mensajes = [{"role": "system", "content": prompt}]
        mensajes.extend(self.memoria_chat.obtener(chat_id))
        mensajes.append({"role": "user", "content": pregunta})

        try:
            respuesta, proveedor, modelo = self.motor.responder(mensajes)
        except LunaError as error:
            print(f"❌ {error}", file=sys.stderr)
            self.telegram.enviar(
                chat_id,
                "❌ Ningún proveedor pudo responder. Mira la última línea de Termux; las claves no se mostraron.",
            )
            return

        if resultados_web:
            fuentes = fuentes_texto(resultados_web)
            if fuentes:
                respuesta += "\n\nFuentes consultadas:\n" + fuentes
        elif necesita_web(texto) and errores_web:
            respuesta += "\n\n⚠️ Esta vez la búsqueda web falló; la respuesta procede del modelo."

        self.memoria_chat.agregar(chat_id, pregunta, respuesta)
        self.telegram.enviar(chat_id, respuesta)
        print(f"✅ Respuesta enviada con {proveedor}/{modelo}")


def adquirir_bloqueo():
    archivo = LOCK_FILE.open("w", encoding="utf-8")
    try:
        fcntl.flock(archivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        archivo.close()
        raise LunaError("Ya hay otra copia de telegram_luna.py ejecutándose") from None
    archivo.write(str(os.getpid()))
    archivo.flush()
    return archivo


def ejecutar(check_only: bool = False) -> int:
    entorno = cargar_env()
    token = entorno.get("TELEGRAM_TOKEN", "").strip()
    telegram = TelegramBot(token)
    info = telegram.get_me()
    usuario = info.get("username", "bot")
    motor = MotorIA(entorno)

    print(f"✅ Telegram autenticado: @{usuario}")
    print("✅ Proveedores configurados: " + (", ".join(motor.configurados) or "ninguno"))
    if not motor.configurados:
        raise LunaError("No hay ninguna clave de IA configurada")
    if check_only:
        print("✅ COMPROBACIÓN TERMINADA (no se hizo ninguna generación de pago)")
        return 0

    bloqueo = adquirir_bloqueo()
    telegram.preparar_long_polling()
    aplicacion = Aplicacion(telegram, motor)
    print("✅ Luna Telegram iniciada")
    print("📩 Esperando mensajes... Pulsa CTRL+C para cerrar.")

    offset: int | None = None
    espera = 2
    try:
        while True:
            try:
                actualizaciones = telegram.actualizaciones(offset)
                espera = 2
                for actualizacion in actualizaciones:
                    update_id = actualizacion.get("update_id")
                    if isinstance(update_id, int):
                        offset = update_id + 1
                    mensaje = actualizacion.get("message")
                    if isinstance(mensaje, dict):
                        try:
                            aplicacion.manejar(mensaje)
                        except LunaError as error:
                            print(f"⚠️ Mensaje no procesado: {error}", file=sys.stderr)
                        except Exception as error:  # evita que un mensaje aislado mate el bot
                            print(
                                f"⚠️ Error interno controlado: {type(error).__name__}",
                                file=sys.stderr,
                            )
            except HttpJsonError as error:
                if error.status == 409:
                    raise LunaError(
                        "Telegram detectó otra copia del bot en ejecución (HTTP 409)"
                    ) from None
                print(
                    f"⚠️ Telegram HTTP {error.status}; reintento en {espera}s",
                    file=sys.stderr,
                )
                time.sleep(espera)
                espera = min(espera * 2, 30)
            except LunaError as error:
                print(f"⚠️ {error}; reintento en {espera}s", file=sys.stderr)
                time.sleep(espera)
                espera = min(espera * 2, 30)
    finally:
        bloqueo.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Puente privado Telegram ↔ Luna")
    parser.add_argument("--check", action="store_true", help="comprueba Telegram sin generar texto")
    opciones = parser.parse_args()
    try:
        return ejecutar(check_only=opciones.check)
    except KeyboardInterrupt:
        print("\n👋 Luna Telegram detenida.")
        return 0
    except LunaError as error:
        print(f"❌ {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
