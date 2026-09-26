#!/usr/bin/env python3
"""Motor políglota seguro para Luna.

Detecta y valida código sin ejecutarlo. Usa analizadores de la biblioteca
estándar y, cuando existen en el sistema, compiladores/intérpretes únicamente
en modo de sintaxis. Nunca instala herramientas ni abre archivos privados.
"""

from __future__ import annotations

import ast
import configparser
import html.parser
import json
import os
import re
import shutil
import subprocess
import tomllib
import xml.etree.ElementTree as ElementTree
from dataclasses import asdict, dataclass
from pathlib import Path


POLIGLOTA_VERSION = "6.0.0"
MAX_ARCHIVOS = 600
MAX_BYTES_ARCHIVO = 2 * 1024 * 1024
DIRECTORIOS_EXCLUIDOS = {
    ".git",
    ".luna_backups",
    ".luna_last_good",
    ".luna_last_good.previous",
    ".luna_tmp",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "cache",
    "log",
    "logs",
    "resultados",
    "target",
    "tmp",
    "vendor",
}
ARCHIVOS_PRIVADOS = {
    ".env",
    ".telegram_owner",
    "memoria_privada.json",
    "memoria_telegram.json",
    "memoria_telegram_offset.json",
    "rendimiento_proveedores.json",
    "estado_automejora.json",
    "eventos_automejora.jsonl",
}

LENGUAJES_POR_EXTENSION = {
    ".py": "Python",
    ".pyi": "Python",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Zsh",
    ".fish": "Fish",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".jsx": "JSX",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".json": "JSON",
    ".jsonl": "JSONL",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".xml": "XML",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sql": "SQL",
    ".ini": "INI",
    ".cfg": "INI",
    ".c": "C",
    ".h": "C/C++",
    ".cc": "C++",
    ".cpp": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".php": "PHP",
    ".rb": "Ruby",
    ".lua": "Lua",
    ".r": "R",
    ".swift": "Swift",
    ".dart": "Dart",
    ".cs": "C#",
    ".ps1": "PowerShell",
    ".pl": "Perl",
    ".pm": "Perl",
    ".hs": "Haskell",
    ".scala": "Scala",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".md": "Markdown",
}

LENGUAJES_POR_NOMBRE = {
    "dockerfile": "Dockerfile",
    "makefile": "Makefile",
    "cmakelists.txt": "CMake",
}

EXTENSIONES_TEXTO_CODIGO = frozenset(LENGUAJES_POR_EXTENSION)
LENGUAJES_SOPORTADOS = tuple(
    sorted(set(LENGUAJES_POR_EXTENSION.values()) | set(LENGUAJES_POR_NOMBRE.values()))
)


@dataclass(frozen=True)
class ResultadoCodigo:
    ruta: str
    lenguaje: str
    estado: str
    detalle: str
    validador: str

    def publico(self) -> dict:
        return asdict(self)


class _HTMLSeguro(html.parser.HTMLParser):
    def error(self, message):  # pragma: no cover - compatibilidad con Python antiguo
        raise ValueError(message)


def detectar_lenguaje(ruta: Path | str) -> str | None:
    archivo = Path(ruta)
    por_nombre = LENGUAJES_POR_NOMBRE.get(archivo.name.lower())
    if por_nombre:
        return por_nombre
    return LENGUAJES_POR_EXTENSION.get(archivo.suffix.lower())


def es_codigo_admitido(ruta: Path | str) -> bool:
    return detectar_lenguaje(ruta) is not None


def _detalle(error: object) -> str:
    texto = str(error).replace("\x00", " ").strip().splitlines()
    return (texto[-1] if texto else type(error).__name__)[:500]


def _estructura_equilibrada(texto: str, pares: dict[str, str]) -> tuple[bool, str]:
    pila: list[str] = []
    inversos = {cierre: apertura for apertura, cierre in pares.items()}
    comilla = ""
    escape = False
    linea = 1
    for caracter in texto:
        if caracter == "\n":
            linea += 1
        if escape:
            escape = False
            continue
        if comilla:
            if caracter == "\\":
                escape = True
            elif caracter == comilla:
                comilla = ""
            continue
        if caracter in {'"', "'", "`"}:
            comilla = caracter
        elif caracter in pares:
            pila.append(caracter)
        elif caracter in inversos:
            if not pila or pila.pop() != inversos[caracter]:
                return False, f"cierre {caracter} sin pareja cerca de la línea {linea}"
    if comilla:
        return False, "cadena de texto sin cerrar"
    if pila:
        return False, f"falta cerrar {pares[pila[-1]]}"
    return True, "estructura equilibrada"


class MotorPoliglota:
    """Inventaría y valida muchos lenguajes con límites de tiempo y tamaño."""

    def __init__(self, root: Path | str, ejecutor=subprocess.run):
        self.root = Path(root).resolve()
        self.ejecutor = ejecutor

    def archivos(self) -> list[Path]:
        encontrados: list[Path] = []
        for base, directorios, nombres in os.walk(self.root, followlinks=False):
            directorios[:] = sorted(
                nombre
                for nombre in directorios
                if nombre not in DIRECTORIOS_EXCLUIDOS and not nombre.startswith(".")
            )
            base_path = Path(base)
            for nombre in sorted(nombres):
                if len(encontrados) >= MAX_ARCHIVOS:
                    return encontrados
                ruta = base_path / nombre
                if (
                    nombre in ARCHIVOS_PRIVADOS
                    or nombre.startswith(".")
                    or ruta.is_symlink()
                    or not es_codigo_admitido(ruta)
                ):
                    continue
                try:
                    if ruta.stat().st_size > MAX_BYTES_ARCHIVO:
                        continue
                except OSError:
                    continue
                encontrados.append(ruta)
        return encontrados

    def _relativa(self, ruta: Path) -> str:
        try:
            return ruta.resolve().relative_to(self.root).as_posix()
        except (OSError, ValueError):
            return ruta.name

    def _resultado(
        self,
        ruta: Path,
        lenguaje: str,
        estado: str,
        detalle: str,
        validador: str,
    ) -> ResultadoCodigo:
        return ResultadoCodigo(
            self._relativa(ruta), lenguaje, estado, _detalle(detalle), validador
        )

    def _externo(
        self,
        ruta: Path,
        lenguaje: str,
        herramienta: str,
        argumentos: list[str],
        *,
        timeout: int = 30,
    ) -> ResultadoCodigo:
        ejecutable = shutil.which(herramienta)
        if not ejecutable:
            return self._resultado(
                ruta,
                lenguaje,
                "sin_validador",
                f"{herramienta} no está instalado; el archivo sigue disponible para Luna",
                herramienta,
            )
        entorno = os.environ.copy()
        entorno.update({"NO_COLOR": "1", "CI": "1"})
        try:
            proceso = self.ejecutor(
                [ejecutable, *argumentos],
                cwd=str(self.root),
                env=entorno,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            return self._resultado(ruta, lenguaje, "error", error, herramienta)
        salida = proceso.stderr or proceso.stdout or "sintaxis correcta"
        return self._resultado(
            ruta,
            lenguaje,
            "correcto" if proceso.returncode == 0 else "error",
            salida,
            herramienta,
        )

    def analizar_archivo(self, ruta: Path | str) -> ResultadoCodigo:
        archivo = Path(ruta).resolve()
        lenguaje = detectar_lenguaje(archivo) or "desconocido"
        try:
            archivo.relative_to(self.root)
        except ValueError:
            return self._resultado(archivo, lenguaje, "error", "ruta fuera del proyecto", "seguridad")
        if archivo.name in ARCHIVOS_PRIVADOS or archivo.is_symlink():
            return self._resultado(archivo, lenguaje, "omitido", "archivo privado o enlace", "seguridad")
        try:
            if archivo.stat().st_size > MAX_BYTES_ARCHIVO:
                return self._resultado(archivo, lenguaje, "omitido", "archivo demasiado grande", "seguridad")
            bruto = archivo.read_bytes()
            texto = bruto.decode("utf-8")
        except (OSError, UnicodeError) as error:
            return self._resultado(archivo, lenguaje, "error", error, "UTF-8")

        try:
            if lenguaje == "Python":
                ast.parse(texto, filename=self._relativa(archivo))
                return self._resultado(archivo, lenguaje, "correcto", "sintaxis correcta", "ast")
            if lenguaje == "JSON":
                json.loads(texto)
                return self._resultado(archivo, lenguaje, "correcto", "JSON válido", "json")
            if lenguaje == "JSONL":
                for numero, linea in enumerate(texto.splitlines(), 1):
                    if linea.strip():
                        try:
                            json.loads(linea)
                        except json.JSONDecodeError as error:
                            raise ValueError(f"línea {numero}: {error.msg}") from None
                return self._resultado(archivo, lenguaje, "correcto", "JSONL válido", "json")
            if lenguaje == "TOML":
                tomllib.loads(texto)
                return self._resultado(archivo, lenguaje, "correcto", "TOML válido", "tomllib")
            if lenguaje == "XML":
                ElementTree.fromstring(texto)
                return self._resultado(archivo, lenguaje, "correcto", "XML válido", "ElementTree")
            if lenguaje == "HTML":
                analizador = _HTMLSeguro(convert_charrefs=True)
                analizador.feed(texto)
                analizador.close()
                return self._resultado(archivo, lenguaje, "correcto", "HTML legible", "HTMLParser")
            if lenguaje == "INI":
                parser = configparser.ConfigParser(interpolation=None)
                parser.read_string(texto)
                return self._resultado(archivo, lenguaje, "correcto", "INI válido", "configparser")
            if lenguaje in {
                "CSS",
                "SCSS",
                "SQL",
                "Vue",
                "Svelte",
                "JSX",
                "TypeScript",
                "Java",
                "Kotlin",
                "C#",
            }:
                ok, detalle = _estructura_equilibrada(texto, {"{": "}", "(": ")", "[": "]"})
                return self._resultado(
                    archivo, lenguaje, "correcto" if ok else "error", detalle, "estructura"
                )
            if lenguaje in {"Markdown", "Dockerfile", "Makefile", "CMake", "Perl", "Haskell", "Scala", "Dart"}:
                ok, detalle = _estructura_equilibrada(texto, {"(": ")", "[": "]"})
                return self._resultado(
                    archivo, lenguaje, "correcto" if ok else "error", detalle, "estructura"
                )
        except (SyntaxError, ValueError, json.JSONDecodeError, tomllib.TOMLDecodeError, ElementTree.ParseError, configparser.Error) as error:
            return self._resultado(archivo, lenguaje, "error", error, "interno")

        ruta = str(archivo)
        if lenguaje == "Shell":
            return self._externo(archivo, lenguaje, "bash", ["-n", ruta])
        if lenguaje == "Zsh":
            return self._externo(archivo, lenguaje, "zsh", ["-n", ruta])
        if lenguaje == "Fish":
            return self._externo(archivo, lenguaje, "fish", ["-n", ruta])
        if lenguaje == "JavaScript":
            return self._externo(archivo, lenguaje, "node", ["--check", ruta])
        if lenguaje == "C":
            return self._externo(archivo, lenguaje, "clang", ["-fsyntax-only", "-Wno-everything", ruta])
        if lenguaje in {"C++", "C/C++"}:
            return self._externo(archivo, lenguaje, "clang++", ["-fsyntax-only", "-Wno-everything", ruta])
        if lenguaje == "Go":
            return self._externo(archivo, lenguaje, "gofmt", ["-e", "-d", ruta])
        if lenguaje == "Rust":
            return self._externo(archivo, lenguaje, "rustfmt", ["--emit", "stdout", ruta])
        if lenguaje == "PHP":
            return self._externo(archivo, lenguaje, "php", ["-l", ruta])
        if lenguaje == "Ruby":
            return self._externo(archivo, lenguaje, "ruby", ["-c", ruta])
        if lenguaje == "Lua":
            return self._externo(archivo, lenguaje, "luac", ["-p", ruta])
        if lenguaje == "Swift":
            return self._externo(archivo, lenguaje, "swiftc", ["-parse", ruta])
        if lenguaje == "R":
            return self._externo(
                archivo,
                lenguaje,
                "Rscript",
                ["--vanilla", "-e", "parse(file=commandArgs(TRUE)[1])", ruta],
            )
        if lenguaje == "PowerShell":
            comando = (
                "$e=$null;$t=$null;[System.Management.Automation.Language.Parser]"
                "::ParseFile($args[0],[ref]$t,[ref]$e)|Out-Null;"
                "if($e.Count){$e|ForEach-Object {$_.Message};exit 1}"
            )
            return self._externo(archivo, lenguaje, "pwsh", ["-NoProfile", "-Command", comando, ruta])
        return self._resultado(archivo, lenguaje, "sin_validador", "lenguaje reconocido", "ninguno")

    def analizar_proyecto(self) -> list[ResultadoCodigo]:
        return [self.analizar_archivo(ruta) for ruta in self.archivos()]

    def resumen(self) -> str:
        resultados = self.analizar_proyecto()
        errores = [item for item in resultados if item.estado == "error"]
        correctos = [item for item in resultados if item.estado == "correcto"]
        sin_validador = [item for item in resultados if item.estado == "sin_validador"]
        lenguajes = sorted({item.lenguaje for item in resultados})
        lineas = [
            f"🌐 Motor políglota {POLIGLOTA_VERSION}",
            f"✅ Lenguajes reconocidos: {len(LENGUAJES_SOPORTADOS)}",
            f"📁 Archivos revisados: {len(resultados)}",
            f"🧪 Validados: {len(correctos)}",
            f"🧰 Sin herramienta local: {len(sin_validador)}",
            f"❌ Errores reales: {len(errores)}",
        ]
        if lenguajes:
            lineas.append("🔤 Detectados: " + ", ".join(lenguajes[:14]))
        for error in errores[:5]:
            lineas.append(f"- {error.ruta} ({error.lenguaje}): {error.detalle}")
        return "\n".join(lineas)


def resumen_poliglota(root: Path | str | None = None) -> str:
    return MotorPoliglota(root or Path(__file__).resolve().parent).resumen()


if __name__ == "__main__":
    print(resumen_poliglota())
