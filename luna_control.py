#!/usr/bin/env python3
"""Panel de control local para Luna en Termux, sin exponer credenciales."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path


SERVICIOS = ("luna-telegram", "luna-automejora")
ARCHIVOS_NUCLEO = (
    "luna.py", "sabiduria_luna.py", "telegram_luna.py", "gestor_keys_luna.py",
    "automejora_luna.py", "poliglota_luna.py", "inventario_luna.py",
)
PATRON_ENV = re.compile(r"^(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=")
NOMBRES_CLAVE = (
    "GROQ_API_KEY", "GEMINI_API_KEY", "CEREBRAS_API_KEY",
    "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY",
    "TAVILY_API_KEY", "BRAVE_SEARCH_API_KEY", "TELEGRAM_TOKEN",
)


def raiz_luna() -> Path:
    return Path(os.environ.get("LUNA_DIR", Path(__file__).resolve().parent)).expanduser().resolve()


def variables_configuradas(ruta: Path) -> list[str]:
    if not ruta.exists():
        return []
    nombres: set[str] = set()
    try:
        lineas = ruta.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for linea in lineas:
        coincidencia = PATRON_ENV.match(linea.strip())
        if coincidencia and coincidencia.group(1) in NOMBRES_CLAVE:
            nombres.add(coincidencia.group(1))
    return [nombre for nombre in NOMBRES_CLAVE if nombre in nombres]


def ejecutar(comando: list[str], raiz: Path, mostrar: bool = True) -> int:
    resultado = subprocess.run(comando, cwd=raiz, text=True, check=False)
    if mostrar and resultado.returncode:
        print(f"❌ Falló: {' '.join(comando)}", file=sys.stderr)
    return resultado.returncode


def servicio_estado(nombre: str) -> str:
    sv = shutil.which("sv")
    if not sv:
        return "sv no disponible"
    resultado = subprocess.run([sv, "status", nombre], text=True, capture_output=True, check=False)
    texto = (resultado.stdout or resultado.stderr).strip()
    return texto or f"sin estado (código {resultado.returncode})"


def mostrar_estado(raiz: Path) -> int:
    faltantes = [nombre for nombre in ARCHIVOS_NUCLEO if not (raiz / nombre).is_file()]
    env = raiz / ".env"
    permisos = stat.S_IMODE(env.stat().st_mode) if env.exists() else None
    claves = variables_configuradas(env)
    print("🌙 Estado local de Luna")
    print(f"📁 Núcleo: {raiz}")
    print("✅ Archivos principales completos" if not faltantes else f"❌ Faltan: {', '.join(faltantes)}")
    if env.exists():
        print(f"🔒 .env: presente, permisos {permisos:03o}")
    else:
        print("⚠️ .env: no existe")
    print(f"🔑 Variables configuradas: {', '.join(claves) if claves else 'ninguna detectada'}")
    for nombre in SERVICIOS:
        print(f"⚙️ {nombre}: {servicio_estado(nombre)}")
    estado_auto = raiz / "estado_automejora.json"
    print("🧠 Automejora: con estado guardado" if estado_auto.exists() else "🧠 Automejora: esperando primer ciclo")
    return 1 if faltantes else 0


def probar(raiz: Path, sin_red: bool = False) -> int:
    print("🧪 Compilando el núcleo...")
    archivos = [str(raiz / nombre) for nombre in ARCHIVOS_NUCLEO if (raiz / nombre).exists()]
    if ejecutar([sys.executable, "-m", "py_compile", *archivos], raiz):
        return 1
    print("🧪 Ejecutando pruebas unitarias...")
    if ejecutar([sys.executable, "-m", "unittest", "discover", "-v"], raiz):
        return 1
    if sin_red:
        print("✅ Pruebas locales superadas; no se probaron APIs por petición.")
        return 0
    print("🌐 Comprobando Telegram y proveedores sin generar respuestas de pago...")
    return ejecutar([sys.executable, "telegram_luna.py", "--check"], raiz)


def controlar_servicios(accion: str) -> int:
    sv = shutil.which("sv")
    if not sv:
        print("❌ Falta termux-services o aún no se abrió una sesión nueva.", file=sys.stderr)
        return 1
    codigo = 0
    for nombre in SERVICIOS:
        resultado = subprocess.run([sv, accion, nombre], text=True, check=False)
        codigo = max(codigo, resultado.returncode)
    return codigo


def mostrar_logs(seguir: bool = False) -> int:
    prefijo = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"))
    rutas = [prefijo / "var" / "log" / "sv" / nombre / "current" for nombre in SERVICIOS]
    existentes = [str(ruta) for ruta in rutas if ruta.exists()]
    if not existentes:
        print("⚠️ Todavía no hay registros de servicio.")
        return 1
    comando = ["tail", "-f" if seguir else "-n", "80", *existentes]
    return subprocess.run(comando, text=True, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Control único de Luna en Termux")
    sub = parser.add_subparsers(dest="comando")
    sub.add_parser("estado", help="muestra núcleo, configuración y servicios")
    pruebas = sub.add_parser("probar", help="compila, prueba y comprueba conexiones")
    pruebas.add_argument("--sin-red", action="store_true")
    sub.add_parser("iniciar", help="inicia los dos servicios")
    sub.add_parser("reiniciar", help="reinicia los dos servicios")
    sub.add_parser("parar", help="detiene los dos servicios")
    sub.add_parser("claves", help="comprueba claves sin mostrar valores")
    sub.add_parser("inventario", help="revisa de nuevo las descargas")
    logs = sub.add_parser("logs", help="muestra los últimos registros")
    logs.add_argument("--seguir", action="store_true")
    opciones = parser.parse_args(argv)
    comando = opciones.comando or "estado"
    raiz = raiz_luna()
    if comando == "estado":
        return mostrar_estado(raiz)
    if comando == "probar":
        return probar(raiz, sin_red=opciones.sin_red)
    if comando in {"iniciar", "reiniciar", "parar"}:
        accion = {"iniciar": "up", "reiniciar": "restart", "parar": "down"}[comando]
        return controlar_servicios(accion)
    if comando == "claves":
        return ejecutar([sys.executable, "gestor_keys_luna.py", "estado"], raiz)
    if comando == "inventario":
        return ejecutar([sys.executable, "inventario_luna.py", "--integrar"], raiz)
    if comando == "logs":
        return mostrar_logs(seguir=opciones.seguir)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
