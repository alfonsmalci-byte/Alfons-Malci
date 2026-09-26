#!/usr/bin/env python3
"""Gestor local y seguro de credenciales para Luna en Termux.

No crea cuentas, no obtiene claves ajenas y no evita límites de los proveedores.
Abre portales oficiales, guarda claves proporcionadas por su propietario, las
valida sin generar texto de pago y avisa por Telegram cuando cambia su estado.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
OWNER_FILE = ROOT / ".telegram_owner"
PRIVATE_DIR = Path.home() / ".config" / "luna"
ACCOUNT_FILE = PRIVATE_DIR / "cuenta.json"
STATE_FILE = PRIVATE_DIR / "estado_keys.json"
USER_AGENT = "Luna-Key-Manager/1.0"
ESTADOS_AUTENTICADOS = {"activa", "limitada"}


@dataclass(frozen=True)
class Proveedor:
    nombre: str
    variable: str
    portal: str
    endpoint: str
    acceso: str
    autenticacion: str = "bearer"


@dataclass(frozen=True)
class Resultado:
    proveedor: str
    estado: str
    detalle: str
    configurada: bool
    huella: str = ""

    @property
    def utilizable(self) -> bool:
        return self.estado in ESTADOS_AUTENTICADOS


PROVEEDORES = {
    "groq": Proveedor(
        "groq",
        "GROQ_API_KEY",
        "https://console.groq.com/keys",
        "https://api.groq.com/openai/v1/models",
        "nivel gratuito con límites",
    ),
    "gemini": Proveedor(
        "gemini",
        "GEMINI_API_KEY",
        "https://aistudio.google.com/app/apikey",
        "https://generativelanguage.googleapis.com/v1beta/models",
        "nivel gratuito según modelo y región",
        "google",
    ),
    "openrouter": Proveedor(
        "openrouter",
        "OPENROUTER_API_KEY",
        "https://openrouter.ai/settings/keys",
        "https://openrouter.ai/api/v1/auth/key",
        "modelos :free con límites",
    ),
    "cerebras": Proveedor(
        "cerebras",
        "CEREBRAS_API_KEY",
        "https://cloud.cerebras.ai/platform/",
        "https://api.cerebras.ai/v1/models",
        "prueba temporal; puede exigir tarjeta",
    ),
    "deepseek": Proveedor(
        "deepseek",
        "DEEPSEEK_API_KEY",
        "https://platform.deepseek.com/api_keys",
        "https://api.deepseek.com/models",
        "normalmente requiere saldo",
    ),
    "openai": Proveedor(
        "openai",
        "OPENAI_API_KEY",
        "https://platform.openai.com/api-keys",
        "https://api.openai.com/v1/models",
        "normalmente requiere saldo",
    ),
    "telegram": Proveedor(
        "telegram",
        "TELEGRAM_TOKEN",
        "https://t.me/BotFather",
        "https://api.telegram.org/bot{key}/getMe",
        "gratuito; sirve como interfaz y avisos",
        "telegram",
    ),
    "tavily": Proveedor(
        "tavily",
        "TAVILY_API_KEY",
        "https://app.tavily.com/home",
        "https://api.tavily.com/usage",
        "búsqueda web; el nivel gratuito tiene créditos mensuales",
    ),
    "brave": Proveedor(
        "brave",
        "BRAVE_SEARCH_API_KEY",
        "https://api-dashboard.search.brave.com/app/keys",
        (
            "https://api.search.brave.com/res/v1/web/search"
            "?q=Python+programming+language&count=1&search_lang=en"
        ),
        "búsqueda web; requiere un plan activo",
        "brave",
    ),
}

ORDEN = tuple(PROVEEDORES)
GRATIS_SIN_TARJETA = ("groq", "gemini", "openrouter", "telegram", "tavily")


def leer_env(ruta: Path = ENV_FILE) -> dict[str, str]:
    if not ruta.exists():
        return {}
    valores: dict[str, str] = {}
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        if linea.startswith("export "):
            linea = linea[7:].lstrip()
        if "=" not in linea:
            continue
        nombre, valor = linea.split("=", 1)
        nombre = nombre.strip()
        valor = valor.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", nombre):
            continue
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        valores[nombre] = valor
    return valores


def _valor_env_seguro(valor: str) -> str:
    valor = valor.strip()
    if not valor or len(valor) > 8_192:
        raise ValueError("valor vacío o demasiado largo")
    if any(caracter in valor for caracter in ("\n", "\r", "\0", "\"", "'", "`", "\\")):
        raise ValueError("la clave contiene caracteres no admitidos")
    return valor


def actualizar_env(cambios: dict[str, str], ruta: Path = ENV_FILE) -> None:
    """Actualiza .env atómicamente y conserva una copia privada anterior."""
    if not ruta.exists():
        raise FileNotFoundError(f"No existe {ruta}")
    cambios = {nombre: _valor_env_seguro(valor) for nombre, valor in cambios.items()}
    originales = ruta.read_text(encoding="utf-8").splitlines()
    nuevas = []
    pendientes = dict(cambios)
    for linea in originales:
        coincidencia = re.match(
            r"^(?P<prefijo>\s*(?:export\s+)?)"
            r"(?P<nombre>[A-Za-z_][A-Za-z0-9_]*)\s*=",
            linea,
        )
        if coincidencia and coincidencia.group("nombre") in pendientes:
            nombre = coincidencia.group("nombre")
            nuevas.append(f"{nombre}={pendientes.pop(nombre)}")
        else:
            nuevas.append(linea)
    if pendientes:
        if nuevas and nuevas[-1].strip():
            nuevas.append("")
        nuevas.extend(f"{nombre}={valor}" for nombre, valor in pendientes.items())

    copia = ruta.with_name(".env.antes_de_rotar")
    shutil.copy2(ruta, copia)
    os.chmod(copia, 0o600)
    descriptor, temporal_nombre = tempfile.mkstemp(prefix=".env.nuevo.", dir=ruta.parent)
    temporal = Path(temporal_nombre)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as salida:
            salida.write("\n".join(nuevas).rstrip() + "\n")
        os.chmod(temporal, 0o600)
        os.replace(temporal, ruta)
        os.chmod(ruta, 0o600)
    finally:
        if temporal.exists():
            temporal.unlink()


def guardar_correo(correo: str, ruta: Path = ACCOUNT_FILE) -> None:
    correo = correo.strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", correo) or len(correo) > 254:
        raise ValueError("correo no válido")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(".tmp")
    temporal.write_text(
        json.dumps({"correo": correo}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporal, 0o600)
    os.replace(temporal, ruta)
    os.chmod(ruta, 0o600)


def cargar_correo(ruta: Path = ACCOUNT_FILE) -> str:
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        correo = str(datos.get("correo", "")).strip()
        return correo if "@" in correo else ""
    except (OSError, ValueError, json.JSONDecodeError, AttributeError):
        return ""


def huella(clave: str) -> str:
    return hashlib.sha256(clave.encode("utf-8")).hexdigest()[:10]


def _peticion(proveedor: Proveedor, clave: str) -> urllib.request.Request:
    headers = {"User-Agent": USER_AGENT}
    url = proveedor.endpoint
    if proveedor.autenticacion == "google":
        headers["x-goog-api-key"] = clave
    elif proveedor.autenticacion == "telegram":
        url = url.format(key=urllib.parse.quote(clave, safe=":"))
    elif proveedor.autenticacion == "brave":
        headers["Accept"] = "application/json"
        headers["X-Subscription-Token"] = clave
    else:
        headers["Authorization"] = f"Bearer {clave}"
    return urllib.request.Request(url, headers=headers, method="GET")


def validar_clave(
    proveedor: Proveedor,
    clave: str,
    *,
    abridor=urllib.request.urlopen,
    timeout: int = 25,
) -> Resultado:
    clave = clave.strip()
    if not clave:
        return Resultado(proveedor.nombre, "no_configurada", "falta", False)
    try:
        peticion = _peticion(proveedor, clave)
        with abridor(peticion, timeout=timeout) as respuesta:
            codigo = int(getattr(respuesta, "status", respuesta.getcode()))
            respuesta.read(512)
    except urllib.error.HTTPError as error:
        codigo = int(error.code)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return Resultado(
            proveedor.nombre,
            "sin_comprobar",
            f"red: {type(error).__name__}",
            True,
            huella(clave),
        )

    if 200 <= codigo < 300:
        estado, detalle = "activa", f"HTTP {codigo}"
    elif codigo == 429:
        estado, detalle = "limitada", "autenticada, límite temporal HTTP 429"
    elif codigo == 402:
        estado, detalle = "sin_saldo", "autenticada, pero exige saldo HTTP 402"
    elif codigo in (401, 403):
        estado, detalle = "rechazada", f"credencial rechazada HTTP {codigo}"
    else:
        estado, detalle = "error_proveedor", f"HTTP {codigo}"
    return Resultado(proveedor.nombre, estado, detalle, True, huella(clave))


def validar_todas(
    entorno: dict[str, str],
    *,
    abridor=urllib.request.urlopen,
) -> dict[str, Resultado]:
    resultados: dict[str, Resultado] = {}
    tareas = {}
    with ThreadPoolExecutor(max_workers=len(ORDEN), thread_name_prefix="luna-keys") as executor:
        for nombre in ORDEN:
            proveedor = PROVEEDORES[nombre]
            clave = entorno.get(proveedor.variable, "").strip()
            if not clave:
                resultados[nombre] = Resultado(nombre, "no_configurada", "falta", False)
                continue
            futuro = executor.submit(validar_clave, proveedor, clave, abridor=abridor)
            tareas[futuro] = nombre
        for futuro in as_completed(tareas):
            nombre = tareas[futuro]
            try:
                resultados[nombre] = futuro.result()
            except Exception as error:
                resultados[nombre] = Resultado(
                    nombre,
                    "sin_comprobar",
                    f"error controlado: {type(error).__name__}",
                    True,
                )
    return {nombre: resultados[nombre] for nombre in ORDEN}


def _icono(resultado: Resultado) -> str:
    return {
        "activa": "✅",
        "limitada": "🟡",
        "sin_saldo": "💳",
        "rechazada": "❌",
        "error_proveedor": "⚠️",
        "sin_comprobar": "⚠️",
        "no_configurada": "➖",
    }.get(resultado.estado, "⚠️")


def texto_estado(resultados: dict[str, Resultado]) -> str:
    lineas = ["🔐 Estado real de las claves de Luna:"]
    for nombre in ORDEN:
        resultado = resultados[nombre]
        extra = f" · id {resultado.huella}" if resultado.huella else ""
        lineas.append(
            f"{_icono(resultado)} {nombre}: {resultado.estado} ({resultado.detalle}){extra}"
        )
    return "\n".join(lineas)


def abrir_url(url: str) -> bool:
    programa = shutil.which("termux-open-url")
    if not programa:
        return False
    subprocess.run(
        [programa, url],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return True


def mostrar_enlaces(*, todos: bool = False, abrir: bool = False) -> None:
    seleccion = ORDEN if todos else GRATIS_SIN_TARJETA
    correo = cargar_correo()
    if correo:
        print(f"Correo local para iniciar sesión: {correo}")
    for nombre in seleccion:
        proveedor = PROVEEDORES[nombre]
        print(f"\n{nombre.upper()} — {proveedor.acceso}\n{proveedor.portal}")
        if abrir:
            abrir_url(proveedor.portal)


def _reiniciar_luna() -> None:
    sv = shutil.which("sv")
    servicio = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr")) / "var/service/luna-telegram"
    if sv and (servicio / "run").exists():
        subprocess.run([sv, "restart", str(servicio)], check=False)


def rotar(nombre: str, *, ruta_env: Path = ENV_FILE) -> bool:
    nombre = nombre.lower()
    if nombre not in PROVEEDORES:
        raise ValueError("proveedor desconocido: " + nombre)
    proveedor = PROVEEDORES[nombre]
    print(f"Abriendo el portal oficial de {nombre}: {proveedor.portal}")
    abrir_url(proveedor.portal)
    nueva = getpass.getpass(f"Pega la nueva {proveedor.variable} (no se mostrará): ").strip()
    resultado = validar_clave(proveedor, nueva)
    print(f"{_icono(resultado)} {resultado.estado}: {resultado.detalle}")
    if not resultado.utilizable:
        print("❌ No se cambió la clave anterior.")
        return False
    actualizar_env({proveedor.variable: nueva}, ruta_env)
    _reiniciar_luna()
    print("✅ Nueva clave validada, guardada y Luna reiniciada.")
    return True


def configurar() -> None:
    correo = cargar_correo()
    if not correo:
        correo = input("Correo para tus cuentas (se guarda solo en el móvil): ").strip()
        guardar_correo(correo)
    entorno = leer_env()
    for nombre in GRATIS_SIN_TARJETA:
        proveedor = PROVEEDORES[nombre]
        if entorno.get(proveedor.variable, "").strip():
            print(f"✅ {nombre}: ya está configurada")
            continue
        respuesta = input(f"¿Abrir y configurar {nombre}? [s/N]: ").strip().lower()
        if respuesta not in ("s", "si", "sí", "y", "yes"):
            continue
        abrir_url(proveedor.portal)
        nueva = getpass.getpass(f"Pega {proveedor.variable} (no se mostrará): ").strip()
        resultado = validar_clave(proveedor, nueva)
        print(f"{_icono(resultado)} {resultado.estado}: {resultado.detalle}")
        if resultado.utilizable:
            actualizar_env({proveedor.variable: nueva})
            entorno[proveedor.variable] = nueva
            print("✅ Guardada de forma privada.")
        else:
            print("❌ No se guardó porque no pudo validarse.")
    _reiniciar_luna()


def _guardar_estado(resultados: dict[str, Resultado], ruta: Path = STATE_FILE) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(".tmp")
    datos = {nombre: asdict(resultado) for nombre, resultado in resultados.items()}
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporal, 0o600)
    os.replace(temporal, ruta)
    os.chmod(ruta, 0o600)


def _cargar_estado(ruta: Path = STATE_FILE) -> dict[str, dict]:
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        return datos if isinstance(datos, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def cambios_estado(
    anteriores: dict[str, dict],
    actuales: dict[str, Resultado],
) -> list[str]:
    avisos = []
    if not anteriores:
        activas = sum(resultado.utilizable for resultado in actuales.values())
        configuradas = sum(resultado.configurada for resultado in actuales.values())
        return [f"🔐 Vigilancia de claves iniciada: {activas}/{configuradas} utilizables."]
    for nombre, actual in actuales.items():
        anterior = str(anteriores.get(nombre, {}).get("estado", ""))
        antes_ok = anterior in ESTADOS_AUTENTICADOS
        ahora_ok = actual.utilizable
        if antes_ok and not ahora_ok:
            avisos.append(f"⚠️ La clave de {nombre} dejó de funcionar: {actual.estado}.")
        elif anterior and not antes_ok and ahora_ok:
            avisos.append(f"✅ La clave de {nombre} volvió a funcionar.")
    return avisos


def enviar_telegram(texto: str, entorno: dict[str, str]) -> bool:
    token = entorno.get("TELEGRAM_TOKEN", "").strip()
    if not token or not OWNER_FILE.exists():
        return False
    try:
        chat_id = int(OWNER_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    url = f"https://api.telegram.org/bot{urllib.parse.quote(token, safe=':')}/sendMessage"
    cuerpo = urllib.parse.urlencode({"chat_id": chat_id, "text": texto}).encode("utf-8")
    peticion = urllib.request.Request(
        url,
        data=cuerpo,
        headers={"User-Agent": USER_AGENT},
        method="POST",
    )
    try:
        with urllib.request.urlopen(peticion, timeout=25) as respuesta:
            return 200 <= int(respuesta.status) < 300
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def vigilar(*, notificar: bool = False) -> dict[str, Resultado]:
    entorno = leer_env()
    actuales = validar_todas(entorno)
    anteriores = _cargar_estado()
    avisos = cambios_estado(anteriores, actuales)
    _guardar_estado(actuales)
    print(texto_estado(actuales))
    if notificar:
        for aviso in avisos:
            enviar_telegram(aviso, entorno)
    return actuales


def ejecutar_servicio() -> None:
    while True:
        try:
            vigilar(notificar=True)
        except Exception as error:
            print(
                f"⚠️ Vigilancia controló un error: {type(error).__name__}",
                file=sys.stderr,
                flush=True,
            )
        entorno = leer_env()
        try:
            intervalo = int(entorno.get("LUNA_KEYS_INTERVAL", "21600"))
        except ValueError:
            intervalo = 21600
        time.sleep(max(900, min(86_400, intervalo)))


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gestiona y vigila las claves privadas de Luna sin mostrarlas."
    )
    sub = parser.add_subparsers(dest="comando")
    sub.add_parser("estado", help="comprueba todas las claves sin generar texto")
    enlaces = sub.add_parser("enlaces", help="muestra portales oficiales")
    enlaces.add_argument("--todos", action="store_true", help="incluye proveedores de pago/prueba")
    enlaces.add_argument("--abrir", action="store_true", help="abre los portales en Android")
    sub.add_parser("configurar", help="asistente local para claves gratuitas que faltan")
    rotacion = sub.add_parser("rotar", help="valida y sustituye una clave")
    rotacion.add_argument("proveedor", choices=ORDEN)
    correo = sub.add_parser("correo", help="guarda el correo solo en el móvil")
    correo.add_argument("direccion")
    vigilancia = sub.add_parser("vigilar", help="comprueba cambios de estado")
    vigilancia.add_argument("--notificar", action="store_true")
    sub.add_parser("servicio", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    comando = args.comando or "estado"
    if comando == "estado":
        print(texto_estado(validar_todas(leer_env())))
    elif comando == "enlaces":
        mostrar_enlaces(todos=args.todos, abrir=args.abrir)
    elif comando == "configurar":
        configurar()
    elif comando == "rotar":
        return 0 if rotar(args.proveedor) else 1
    elif comando == "correo":
        guardar_correo(args.direccion)
        print("✅ Correo guardado solo en el móvil; no se guardó ninguna contraseña.")
    elif comando == "vigilar":
        vigilar(notificar=args.notificar)
    elif comando == "servicio":
        ejecutar_servicio()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, FileNotFoundError) as error:
        print(f"❌ {error}", file=sys.stderr)
        raise SystemExit(1)
