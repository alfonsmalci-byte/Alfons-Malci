#!/usr/bin/env python3
"""Mantenimiento autónomo y seguro de Luna.

Los agentes de este módulo observan, diagnostican, reparan únicamente acciones
permitidas, verifican con pruebas y restauran la última versión buena cuando
una reparación no funciona. Nunca leen ni publican el valor de las claves.
"""

from __future__ import annotations

import argparse
import base64
import fcntl
import hashlib
import importlib.util
import json
import os
import py_compile
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from poliglota_luna import MotorPoliglota


AUTOMEJORA_VERSION = "6.0.0"
DEFAULT_REPO = "alfonsmalci-byte/Alfons-Malci"
CRITICAL_CODE = (
    "luna.py",
    "telegram_luna.py",
    "sabiduria_luna.py",
    "gestor_keys_luna.py",
    "automejora_luna.py",
    "poliglota_luna.py",
)
TEST_FILES = (
    "test_luna_busqueda.py",
    "test_telegram_luna.py",
    "test_sabiduria_luna.py",
    "test_gestor_keys_luna.py",
    "test_automejora_luna.py",
    "test_poliglota_luna.py",
)
PRIVATE_FILES = (
    ".env",
    ".telegram_owner",
    "memoria_privada.json",
    "memoria_telegram.json",
    "memoria_telegram_offset.json",
    "rendimiento_proveedores.json",
)
JSON_PRIVATE_FILES = (
    "memoria_privada.json",
    "memoria_telegram.json",
    "memoria_telegram_offset.json",
    "rendimiento_proveedores.json",
)
UPDATE_FILES = (
    "README.md",
    "GESTOR_KEYS.md",
    "luna.py",
    "telegram_luna.py",
    "sabiduria_luna.py",
    "gestor_keys_luna.py",
    "automejora_luna.py",
    "poliglota_luna.py",
    *TEST_FILES,
)
LOG_PATTERNS = (
    "Traceback (most recent call last)",
    "SyntaxError:",
    "NameError:",
    "ModuleNotFoundError:",
    "IndentationError:",
    "HTTP 409",
)
KEY_RE = re.compile(
    r"(?i)(bearer|token|api[_ -]?key|authorization)\s*[:=]?\s*[^\s,;}]+"
)
VERSION_RE = re.compile(r"NUCLEO_VERSION\s*=\s*[\"']([0-9]+(?:\.[0-9]+){1,3})[\"']")
MAX_BASELINE_BYTES = 25 * 1024 * 1024


def ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def limpiar_secreto(texto: object) -> str:
    limpio = re.sub(
        r"(?i)authorization\s*:\s*bearer\s+[^\s,;}]+",
        "Authorization: Bearer ***",
        str(texto),
    )
    return KEY_RE.sub(r"\1=***", limpio).replace("\x00", "")[:1_000]


def leer_json(ruta: Path, defecto):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return defecto


def guardar_json_atomico(ruta: Path, datos, modo: int = 0o600) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(f".{ruta.name}.tmp-{os.getpid()}")
    temporal.write_text(
        json.dumps(datos, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.chmod(temporal, modo)
    os.replace(temporal, ruta)
    os.chmod(ruta, modo)


def sha256(ruta: Path) -> str:
    digest = hashlib.sha256()
    with ruta.open("rb") as entrada:
        for bloque in iter(lambda: entrada.read(128 * 1024), b""):
            digest.update(bloque)
    return digest.hexdigest()


def version_tuple(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(parte) for parte in version.split("."))
    except ValueError:
        return (0,)


def version_directorio(root: Path) -> str:
    try:
        texto = (root / "sabiduria_luna.py").read_text(encoding="utf-8")
    except OSError:
        return "0.0.0"
    coincidencia = VERSION_RE.search(texto)
    return coincidencia.group(1) if coincidencia else "0.0.0"


@dataclass(frozen=True)
class Hallazgo:
    codigo: str
    nivel: str
    detalle: str
    reparacion: str = ""


@dataclass(frozen=True)
class ResultadoReparacion:
    codigo: str
    ok: bool
    detalle: str


class NotificadorTelegram:
    def __init__(self, root: Path):
        self.root = root

    def _credenciales(self) -> tuple[str, str]:
        token = ""
        env = self.root / ".env"
        if env.exists():
            for linea in env.read_text(encoding="utf-8", errors="replace").splitlines():
                linea = linea.strip()
                if linea.startswith("export "):
                    linea = linea[7:].lstrip()
                if linea.startswith("TELEGRAM_TOKEN="):
                    token = linea.split("=", 1)[1].strip().strip("\"'")
                    break
        try:
            chat_id = (self.root / ".telegram_owner").read_text(encoding="utf-8").strip()
        except OSError:
            chat_id = ""
        return token, chat_id

    def enviar(self, texto: str) -> bool:
        token, chat_id = self._credenciales()
        if not token or not chat_id:
            return False
        cuerpo = json.dumps(
            {"chat_id": chat_id, "text": limpiar_secreto(texto)[:3_900]},
            ensure_ascii=False,
        ).encode("utf-8")
        peticion = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=cuerpo,
            headers={"Content-Type": "application/json", "User-Agent": "Luna-Automejora/3"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(peticion, timeout=20) as respuesta:
                datos = json.loads(respuesta.read().decode("utf-8", errors="replace"))
            return bool(datos.get("ok"))
        except (OSError, ValueError, urllib.error.URLError):
            return False


class SistemaAutomejora:
    """Coordina siete agentes con acciones limitadas y reversibles."""

    def __init__(
        self,
        root: Path | str | None = None,
        *,
        prefix: Path | str | None = None,
        python: str | None = None,
        ejecutor=subprocess.run,
        notificador: NotificadorTelegram | None = None,
    ):
        self.root = Path(root or Path(__file__).resolve().parent).resolve()
        self.prefix = Path(prefix or os.environ.get("PREFIX", "/data/data/com.termux/files/usr"))
        self.python = python or sys.executable
        self.ejecutor = ejecutor
        self.state_file = self.root / "estado_automejora.json"
        self.events_file = self.root / "eventos_automejora.jsonl"
        self.lock_file = self.root / ".luna_automejora.lock"
        self.baseline = self.root / ".luna_last_good"
        self.backups = self.root / ".luna_backups" / "automejora"
        self.notificador = notificador or NotificadorTelegram(self.root)
        self.estado = leer_json(self.state_file, {})

    def _evento(self, tipo: str, detalle: str) -> None:
        registro = {
            "timestamp": ahora_iso(),
            "tipo": tipo,
            "detalle": limpiar_secreto(detalle),
        }
        if self.events_file.exists() and self.events_file.stat().st_size > 768 * 1024:
            anterior = self.events_file.with_suffix(".jsonl.1")
            os.replace(self.events_file, anterior)
        with self.events_file.open("a", encoding="utf-8") as salida:
            salida.write(json.dumps(registro, ensure_ascii=False) + "\n")
        os.chmod(self.events_file, 0o600)

    def _ejecutar(self, args: list[str], *, cwd: Path | None = None, timeout: int = 120):
        entorno = os.environ.copy()
        entorno["PYTHONDONTWRITEBYTECODE"] = "1"
        return self.ejecutor(
            args,
            cwd=str(cwd or self.root),
            env=entorno,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def verificar_directorio(self, root: Path, con_pruebas: bool = True) -> tuple[bool, str]:
        faltan = [nombre for nombre in CRITICAL_CODE if not (root / nombre).is_file()]
        if faltan:
            return False, "faltan archivos: " + ", ".join(faltan)
        try:
            for script in root.glob("*.py"):
                if script.is_file() and not script.name.startswith("."):
                    py_compile.compile(str(script), doraise=True)
        except py_compile.PyCompileError as error:
            return False, limpiar_secreto(error.msg)

        for script in root.glob("*.sh"):
            resultado = self._ejecutar(["bash", "-n", str(script)], cwd=root, timeout=30)
            if resultado.returncode:
                return False, f"shell inválido en {script.name}: {limpiar_secreto(resultado.stderr)}"

        resultados_codigo = MotorPoliglota(root, ejecutor=self.ejecutor).analizar_proyecto()
        errores_codigo = [item for item in resultados_codigo if item.estado == "error"]
        if errores_codigo:
            primero = errores_codigo[0]
            return False, limpiar_secreto(
                f"{primero.lenguaje} inválido en {primero.ruta}: {primero.detalle}"
            )

        if con_pruebas:
            resultado = self._ejecutar(
                [self.python, "-m", "unittest", "discover", "-q"],
                cwd=root,
                timeout=180,
            )
            if resultado.returncode:
                detalle = resultado.stderr or resultado.stdout or "pruebas fallidas"
                return False, limpiar_secreto(detalle)[-900:]
        return True, f"sintaxis políglota y pruebas correctas ({len(resultados_codigo)} archivos)"

    @staticmethod
    def _relativa_segura(nombre: str) -> bool:
        ruta = Path(nombre)
        return bool(nombre) and not ruta.is_absolute() and ".." not in ruta.parts

    def _archivos_codigo(self) -> list[tuple[str, Path]]:
        salida: list[tuple[str, Path]] = []
        total = 0
        for ruta in MotorPoliglota(self.root, ejecutor=self.ejecutor).archivos():
            try:
                relativa = ruta.resolve().relative_to(self.root).as_posix()
            except (OSError, ValueError):
                continue
            try:
                tamano = ruta.stat().st_size
            except OSError:
                continue
            if total + tamano > MAX_BASELINE_BYTES:
                break
            if self._relativa_segura(relativa):
                salida.append((relativa, ruta))
                total += tamano
        return salida

    def _estado_codigo_actual(self) -> dict[str, str]:
        return {nombre: sha256(ruta) for nombre, ruta in self._archivos_codigo()}

    def _cambios_frente_baseline(self) -> list[str]:
        manifiesto = leer_json(self.baseline / "manifest.json", {})
        esperados = manifiesto.get("files", {}) if isinstance(manifiesto, dict) else {}
        if not isinstance(esperados, dict):
            return []
        actuales = self._estado_codigo_actual()
        nombres = set(esperados) | set(actuales)
        return sorted(
            nombre for nombre in nombres if esperados.get(nombre) != actuales.get(nombre)
        )

    def _observar_evolucion(self, hay_error_runtime: bool) -> str:
        cambios = self._cambios_frente_baseline()
        if not cambios:
            self.estado.pop("candidato_codigo_huella", None)
            self.estado.pop("candidato_codigo_ciclos", None)
            return "sin cambios pendientes"
        if hay_error_runtime:
            self.estado["candidato_codigo_ciclos"] = 0
            return "cambios no promovidos porque apareció un error de ejecución"
        huella = hashlib.sha256(
            json.dumps(self._estado_codigo_actual(), sort_keys=True).encode("utf-8")
        ).hexdigest()
        if self.estado.get("candidato_codigo_huella") == huella:
            ciclos = int(self.estado.get("candidato_codigo_ciclos", 0) or 0) + 1
        else:
            ciclos = 1
        self.estado["candidato_codigo_huella"] = huella
        self.estado["candidato_codigo_ciclos"] = ciclos
        if ciclos < 3:
            return f"cambio válido en observación {ciclos}/3 ({len(cambios)} archivos)"
        ok, detalle = self.sellar_version_buena()
        if ok:
            self.estado.pop("candidato_codigo_huella", None)
            self.estado.pop("candidato_codigo_ciclos", None)
            self._evento("evolucion", f"cambio promovido tras 3 ciclos: {len(cambios)} archivos")
            return f"cambio promovido como versión buena: {detalle}"
        return f"cambio rechazado durante el sellado: {detalle}"

    def sellar_version_buena(self) -> tuple[bool, str]:
        ok, detalle = self.verificar_directorio(self.root, con_pruebas=True)
        if not ok:
            return False, detalle
        temporal = self.root / f".luna_last_good.tmp-{os.getpid()}"
        if temporal.exists():
            shutil.rmtree(temporal)
        temporal.mkdir(mode=0o700)
        manifiesto = {"version": version_directorio(self.root), "creado": ahora_iso(), "files": {}}
        candidatos = self._archivos_codigo()
        for nombre, origen in candidatos:
            destino = temporal / nombre
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origen, destino)
            manifiesto["files"][nombre] = sha256(destino)
        guardar_json_atomico(temporal / "manifest.json", manifiesto)
        anterior = self.root / ".luna_last_good.previous"
        if anterior.exists():
            shutil.rmtree(anterior)
        if self.baseline.exists():
            os.replace(self.baseline, anterior)
        os.replace(temporal, self.baseline)
        self._evento("sellado", f"versión buena {manifiesto['version']}")
        return True, f"versión {manifiesto['version']} sellada como última buena"

    def _baseline_valida(self) -> bool:
        manifiesto = leer_json(self.baseline / "manifest.json", {})
        archivos = manifiesto.get("files", {}) if isinstance(manifiesto, dict) else {}
        if not isinstance(archivos, dict) or not archivos:
            return False
        for nombre, esperado in archivos.items():
            if not isinstance(nombre, str) or not self._relativa_segura(nombre):
                return False
            ruta = self.baseline / nombre
            if not ruta.is_file() or sha256(ruta) != esperado:
                return False
        return True

    def restaurar_codigo(self) -> tuple[bool, str]:
        if not self._baseline_valida():
            return False, "no existe una última versión buena válida"
        manifiesto = leer_json(self.baseline / "manifest.json", {})
        restaurados = []
        for nombre in manifiesto["files"]:
            if not self._relativa_segura(nombre):
                return False, "la copia contiene una ruta no segura"
            origen = self.baseline / nombre
            destino = self.root / nombre
            destino.parent.mkdir(parents=True, exist_ok=True)
            temporal = destino.with_name(f".{destino.name}.restore-{os.getpid()}")
            shutil.copy2(origen, temporal)
            os.replace(temporal, destino)
            restaurados.append(nombre)
        ok, detalle = self.verificar_directorio(self.root, con_pruebas=True)
        self._evento("restauracion_codigo", f"ok={ok}; {detalle}")
        return ok, f"restaurados {len(restaurados)} archivos; {detalle}"

    def _baseline_contiene(self, nombre: str) -> bool:
        manifiesto = leer_json(self.baseline / "manifest.json", {})
        archivos = manifiesto.get("files", {}) if isinstance(manifiesto, dict) else {}
        return isinstance(archivos, dict) and nombre in archivos

    def _cuarentenar_codigo(self, nombre: str) -> tuple[bool, str]:
        if not self._relativa_segura(nombre):
            return False, "ruta no segura; no se movió"
        origen = self.root / nombre
        if not origen.is_file() or origen.is_symlink():
            return False, "el archivo nuevo inválido ya no existe"
        destino = (
            self.backups
            / f"cuarentena-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
            / nombre
        )
        destino.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.replace(origen, destino)
        return True, f"{nombre} movido a cuarentena recuperable"

    def snapshot_memoria(self) -> None:
        fecha = datetime.now(timezone.utc).strftime("%Y%m%d")
        destino = self.backups / f"memoria-{fecha}"
        destino.mkdir(parents=True, exist_ok=True, mode=0o700)
        for nombre in PRIVATE_FILES:
            if nombre in {".env", ".telegram_owner"}:
                continue
            origen = self.root / nombre
            if not origen.is_file() or origen.stat().st_size > 2 * 1024 * 1024:
                continue
            if nombre.endswith(".json"):
                try:
                    json.loads(origen.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    continue
            copia = destino / nombre
            if not copia.exists():
                shutil.copy2(origen, copia)
                os.chmod(copia, 0o600)

    def _restaurar_memoria(self, nombre: str) -> tuple[bool, str]:
        candidatos = sorted(self.backups.glob("memoria-*/" + nombre), reverse=True)
        for candidato in candidatos:
            try:
                json.loads(candidato.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            roto = self.root / nombre
            cuarentena = self.backups / f"corrupto-{int(time.time())}-{nombre}"
            if roto.exists():
                shutil.copy2(roto, cuarentena)
            temporal = roto.with_name(f".{roto.name}.restore-{os.getpid()}")
            shutil.copy2(candidato, temporal)
            os.chmod(temporal, 0o600)
            os.replace(temporal, roto)
            return True, f"{nombre} restaurado desde una copia válida"
        return False, f"{nombre} está dañado y no hay copia válida; no se borró"

    def _servicio_estado(self) -> tuple[bool | None, str]:
        if shutil.which("sv") is None:
            return None, "sv no está disponible en este entorno"
        entorno = os.environ.copy()
        entorno["SVDIR"] = str(self.prefix / "var/service")
        try:
            resultado = self.ejecutor(
                ["sv", "status", "luna-telegram"],
                env=entorno,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            return False, limpiar_secreto(error)
        texto = (resultado.stdout or resultado.stderr).strip()
        return texto.startswith("run:"), limpiar_secreto(texto)

    def _reiniciar_servicio(self) -> tuple[bool, str]:
        if shutil.which("sv") is None:
            return False, "sv no está disponible"
        entorno = os.environ.copy()
        entorno["SVDIR"] = str(self.prefix / "var/service")
        for accion in ("up",):
            try:
                self.ejecutor(
                    ["sv", accion, "luna-telegram"],
                    env=entorno,
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                pass
        time.sleep(1)
        activo, detalle = self._servicio_estado()
        return bool(activo), detalle

    def inspeccionar(self) -> list[Hallazgo]:
        hallazgos: list[Hallazgo] = []
        for nombre in CRITICAL_CODE:
            ruta = self.root / nombre
            if not ruta.is_file():
                hallazgos.append(Hallazgo("codigo_faltante", "critico", nombre, "restaurar_codigo"))
                continue
            try:
                py_compile.compile(str(ruta), doraise=True)
            except py_compile.PyCompileError as error:
                hallazgos.append(
                    Hallazgo(
                        "codigo_invalido",
                        "critico",
                        f"{nombre}: {limpiar_secreto(error.msg)}",
                        "restaurar_codigo",
                    )
                )

        for ruta in self.root.glob("*.py"):
            if not ruta.is_file() or ruta.name in CRITICAL_CODE or ruta.name.startswith("."):
                continue
            try:
                py_compile.compile(str(ruta), doraise=True)
            except py_compile.PyCompileError as error:
                hallazgos.append(
                    Hallazgo(
                        "codigo_invalido",
                        "critico",
                        f"{ruta.name}: {limpiar_secreto(error.msg)}",
                        "restaurar_codigo",
                    )
                )

        for resultado in MotorPoliglota(
            self.root, ejecutor=self.ejecutor
        ).analizar_proyecto():
            if resultado.estado != "error":
                continue
            hallazgos.append(
                Hallazgo(
                    "codigo_poliglota_invalido",
                    "critico",
                    f"{resultado.ruta} ({resultado.lenguaje}): {resultado.detalle}",
                    "restaurar_codigo",
                )
            )

        manifiesto = leer_json(self.baseline / "manifest.json", {})
        archivos_buenos = manifiesto.get("files", {}) if isinstance(manifiesto, dict) else {}
        if isinstance(archivos_buenos, dict):
            cambiados = []
            for nombre, esperado in archivos_buenos.items():
                if not isinstance(nombre, str) or not self._relativa_segura(nombre):
                    continue
                ruta = self.root / nombre
                if not ruta.is_file():
                    hallazgos.append(
                        Hallazgo(
                            "codigo_poliglota_faltante",
                            "critico",
                            nombre,
                            "restaurar_codigo",
                        )
                    )
                elif sha256(ruta) != esperado:
                    cambiados.append(nombre)
            if cambiados:
                hallazgos.append(
                    Hallazgo(
                        "codigo_modificado",
                        "info",
                        ", ".join(cambiados[:8]),
                        "verificar_cambios",
                    )
                )

        for nombre in PRIVATE_FILES:
            ruta = self.root / nombre
            if ruta.is_file() and stat.S_IMODE(ruta.stat().st_mode) & 0o077:
                hallazgos.append(
                    Hallazgo("permisos_privados", "alto", nombre, "proteger_permisos")
                )

        for nombre in JSON_PRIVATE_FILES:
            ruta = self.root / nombre
            if not ruta.is_file() or ruta.stat().st_size > 2 * 1024 * 1024:
                continue
            try:
                json.loads(ruta.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                hallazgos.append(
                    Hallazgo(
                        "json_corrupto",
                        "alto",
                        f"{nombre}: {type(error).__name__}",
                        "restaurar_memoria",
                    )
                )

        lock = self.root / ".luna_telegram.lock"
        if lock.is_file():
            try:
                pid = int(lock.read_text(encoding="utf-8").strip())
                cmdline = Path(f"/proc/{pid}/cmdline")
                vivo = cmdline.exists() and b"telegram_luna.py" in cmdline.read_bytes()
            except (OSError, ValueError):
                vivo = False
            if not vivo:
                hallazgos.append(Hallazgo("lock_obsoleto", "medio", str(lock.name), "borrar_lock"))

        try:
            libre = shutil.disk_usage(self.root).free
            if libre < 200 * 1024 * 1024:
                hallazgos.append(
                    Hallazgo("espacio_bajo", "alto", f"quedan {libre // (1024 * 1024)} MB")
                )
        except OSError:
            pass

        activo, detalle = self._servicio_estado()
        if activo is False:
            hallazgos.append(Hallazgo("servicio_caido", "critico", detalle, "reiniciar_servicio"))

        registro = self.prefix / "var/log/sv/luna-telegram/current"
        ultima_revision_epoch = float(self.estado.get("ultima_revision_epoch", 0) or 0)
        if registro.is_file() and registro.stat().st_mtime >= ultima_revision_epoch:
            try:
                with registro.open("rb") as entrada:
                    entrada.seek(max(0, registro.stat().st_size - 128 * 1024))
                    cola = entrada.read().decode("utf-8", errors="replace")
                encontrados = [patron for patron in LOG_PATTERNS if patron in cola]
                if encontrados:
                    hallazgos.append(
                        Hallazgo("error_en_registro", "alto", ", ".join(encontrados))
                    )
            except OSError:
                pass

        ultimo_intento_pdf = float(self.estado.get("ultimo_intento_pypdf", 0) or 0)
        if (
            importlib.util.find_spec("pypdf") is None
            and time.time() - ultimo_intento_pdf >= 24 * 3600
        ):
            hallazgos.append(
                Hallazgo("dependencia_pdf", "medio", "pypdf no está instalado", "instalar_pypdf")
            )
        return hallazgos

    def reparar(self, hallazgos: list[Hallazgo]) -> list[ResultadoReparacion]:
        resultados: list[ResultadoReparacion] = []
        codigo_roto = any(
            h.codigo
            in {
                "codigo_faltante",
                "codigo_invalido",
                "codigo_poliglota_invalido",
                "codigo_poliglota_faltante",
            }
            for h in hallazgos
        )
        codigo_restaurado = False
        for hallazgo in hallazgos:
            if hallazgo.reparacion == "proteger_permisos":
                ruta = self.root / hallazgo.detalle
                try:
                    os.chmod(ruta, 0o600)
                    resultado = ResultadoReparacion(hallazgo.codigo, True, f"{ruta.name} protegido")
                except OSError as error:
                    resultado = ResultadoReparacion(hallazgo.codigo, False, limpiar_secreto(error))
            elif hallazgo.reparacion == "borrar_lock":
                try:
                    (self.root / ".luna_telegram.lock").unlink(missing_ok=True)
                    resultado = ResultadoReparacion(hallazgo.codigo, True, "lock obsoleto eliminado")
                except OSError as error:
                    resultado = ResultadoReparacion(hallazgo.codigo, False, limpiar_secreto(error))
            elif (
                hallazgo.codigo == "codigo_poliglota_invalido"
                and not self._baseline_contiene(hallazgo.detalle.split(" (", 1)[0])
            ):
                ok, detalle = self._cuarentenar_codigo(
                    hallazgo.detalle.split(" (", 1)[0]
                )
                codigo_restaurado = codigo_restaurado or ok
                resultado = ResultadoReparacion(hallazgo.codigo, ok, detalle)
            elif hallazgo.reparacion == "restaurar_codigo" and not codigo_restaurado:
                ok, detalle = self.restaurar_codigo()
                codigo_restaurado = ok
                resultado = ResultadoReparacion(hallazgo.codigo, ok, detalle)
            elif hallazgo.reparacion == "restaurar_codigo":
                resultado = ResultadoReparacion(
                    hallazgo.codigo,
                    codigo_restaurado,
                    "incluido en la restauración conjunta"
                    if codigo_restaurado
                    else "la restauración conjunta no se completó",
                )
            elif hallazgo.reparacion == "restaurar_memoria":
                nombre = hallazgo.detalle.split(":", 1)[0]
                ok, detalle = self._restaurar_memoria(nombre)
                resultado = ResultadoReparacion(hallazgo.codigo, ok, detalle)
            elif hallazgo.reparacion == "instalar_pypdf":
                self.estado["ultimo_intento_pypdf"] = time.time()
                ejecucion = self._ejecutar(
                    [
                        self.python,
                        "-m",
                        "pip",
                        "install",
                        "--disable-pip-version-check",
                        "--no-input",
                        "--quiet",
                        "pypdf>=5",
                    ],
                    timeout=180,
                )
                resultado = ResultadoReparacion(
                    hallazgo.codigo,
                    ejecucion.returncode == 0,
                    "pypdf instalado" if ejecucion.returncode == 0 else "pypdf no pudo instalarse",
                )
            elif hallazgo.reparacion == "reiniciar_servicio":
                if codigo_roto and not codigo_restaurado:
                    resultado = ResultadoReparacion(
                        hallazgo.codigo,
                        False,
                        "no se reinició porque el código sigue inválido",
                    )
                else:
                    ok, detalle = self._reiniciar_servicio()
                    resultado = ResultadoReparacion(hallazgo.codigo, ok, detalle)
            elif hallazgo.reparacion == "verificar_cambios":
                ok, detalle = self.verificar_directorio(self.root, con_pruebas=True)
                resultado = ResultadoReparacion(
                    hallazgo.codigo,
                    ok,
                    "cambios externos válidos; esperan sellado o actualización segura"
                    if ok
                    else detalle,
                )
            else:
                continue
            resultados.append(resultado)
            self._evento("reparacion", f"{resultado.codigo}: ok={resultado.ok}; {resultado.detalle}")
        return resultados

    def _http_bytes(self, url: str, limite: int) -> bytes:
        peticion = urllib.request.Request(
            url,
            headers={"User-Agent": "Luna-Automejora/3", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(peticion, timeout=30) as respuesta:
            tamano = respuesta.headers.get("Content-Length")
            if tamano and int(tamano) > limite:
                raise RuntimeError("descarga demasiado grande")
            datos = respuesta.read(limite + 1)
        if len(datos) > limite:
            raise RuntimeError("descarga demasiado grande")
        return datos

    def _extraer_actualizacion(self, archivo_zip: Path, destino: Path) -> Path:
        with zipfile.ZipFile(archivo_zip) as archivo:
            miembros = archivo.infolist()
            if len(miembros) > 500 or sum(item.file_size for item in miembros) > 25 * 1024 * 1024:
                raise RuntimeError("paquete de actualización fuera de límites")
            raices = set()
            for item in miembros:
                ruta = Path(item.filename)
                partes = ruta.parts
                if not partes or ruta.is_absolute() or ".." in partes:
                    raise RuntimeError("ruta no segura en actualización")
                raices.add(partes[0])
                modo = (item.external_attr >> 16) & 0o170000
                if modo == stat.S_IFLNK:
                    raise RuntimeError("la actualización contiene enlaces simbólicos")
            if len(raices) != 1:
                raise RuntimeError("estructura de actualización inesperada")
            archivo.extractall(destino)
        return destino / next(iter(raices))

    def _validar_candidato(self, candidato: Path) -> tuple[bool, str]:
        requeridos = {
            "luna.py": ("def search_web",),
            "telegram_luna.py": ("def responder_imagen", "def transcribir_audio", "/automejora"),
            "automejora_luna.py": ("class SistemaAutomejora", "sellar_version_buena"),
            "poliglota_luna.py": ("class MotorPoliglota", "LENGUAJES_SOPORTADOS"),
        }
        for nombre, marcas in requeridos.items():
            ruta = candidato / nombre
            if not ruta.is_file():
                return False, f"el candidato no contiene {nombre}"
            texto = ruta.read_text(encoding="utf-8", errors="replace")
            if any(marca not in texto for marca in marcas):
                return False, f"el candidato pierde capacidades de {nombre}"
        for prohibido in (".env", "memoria_privada.json", "memoria_telegram.json"):
            if (candidato / prohibido).exists():
                return False, f"el candidato contiene el archivo privado {prohibido}"
        return self.verificar_directorio(candidato, con_pruebas=True)

    def comprobar_actualizacion(self, forzar: bool = False) -> tuple[str, str]:
        if os.environ.get("LUNA_AUTO_UPDATE", "1").strip().lower() in {"0", "no", "false"}:
            return "desactivada", "LUNA_AUTO_UPDATE está desactivado"
        ahora = time.time()
        ultima = float(self.estado.get("ultima_revision_actualizacion_epoch", 0) or 0)
        if not forzar and ahora - ultima < 24 * 3600:
            return "sin_revision", "todavía no toca la revisión diaria"
        self.estado["ultima_revision_actualizacion_epoch"] = ahora
        repo = os.environ.get("LUNA_UPDATE_REPO", DEFAULT_REPO).strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            return "error", "LUNA_UPDATE_REPO no es válido"
        try:
            bruto = self._http_bytes(
                f"https://api.github.com/repos/{repo}/contents/sabiduria_luna.py?ref=main",
                2 * 1024 * 1024,
            )
            datos = json.loads(bruto.decode("utf-8"))
            remoto_texto = base64.b64decode(datos["content"]).decode("utf-8")
            coincidencia = VERSION_RE.search(remoto_texto)
            version_remota = coincidencia.group(1) if coincidencia else "0.0.0"
            version_local = version_directorio(self.root)
            if version_tuple(version_remota) <= version_tuple(version_local):
                return "actual", f"local {version_local}; remota {version_remota}"

            temporal_base = self.root / ".luna_tmp"
            temporal_base.mkdir(mode=0o700, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=temporal_base, prefix="update-") as temporal:
                temporal_path = Path(temporal)
                zip_path = temporal_path / "update.zip"
                zip_path.write_bytes(
                    self._http_bytes(
                        f"https://github.com/{repo}/archive/refs/heads/main.zip",
                        12 * 1024 * 1024,
                    )
                )
                candidato = self._extraer_actualizacion(zip_path, temporal_path / "extraido")
                ok, detalle = self._validar_candidato(candidato)
                if not ok:
                    return "rechazada", detalle
                backup = self.backups / f"update-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
                backup.mkdir(parents=True, mode=0o700)
                instalados = []
                existentes = set()
                for nombre in UPDATE_FILES:
                    origen = candidato / nombre
                    if not origen.is_file():
                        continue
                    actual = self.root / nombre
                    if actual.is_file():
                        existentes.add(nombre)
                        shutil.copy2(actual, backup / nombre)
                    temporal_archivo = actual.with_name(f".{actual.name}.update-{os.getpid()}")
                    shutil.copy2(origen, temporal_archivo)
                    os.replace(temporal_archivo, actual)
                    instalados.append(nombre)
                ok, detalle = self.verificar_directorio(self.root, con_pruebas=True)
                if not ok:
                    for nombre in instalados:
                        copia = backup / nombre
                        if nombre in existentes and copia.is_file():
                            shutil.copy2(copia, self.root / nombre)
                        elif nombre not in existentes:
                            (self.root / nombre).unlink(missing_ok=True)
                    return "revertida", detalle
                self.sellar_version_buena()
                self._reiniciar_servicio()
                self.estado["ultima_version_instalada"] = version_remota
                self._evento("actualizacion", f"{version_local} -> {version_remota}")
                return "instalada", f"{version_local} -> {version_remota}; {len(instalados)} archivos"
        except (OSError, ValueError, KeyError, RuntimeError, urllib.error.URLError, zipfile.BadZipFile) as error:
            return "error", limpiar_secreto(f"{type(error).__name__}: {error}")

    def ciclo(self, *, forzar_actualizacion: bool = False, avisar: bool = True) -> dict:
        self.root.mkdir(parents=True, exist_ok=True)
        bloqueo = self.lock_file.open("a+", encoding="utf-8")
        try:
            fcntl.flock(bloqueo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            bloqueo.close()
            return {"ok": True, "omitido": "otro ciclo ya está trabajando"}
        inicio = time.monotonic()
        try:
            if not self._baseline_valida():
                sellado_ok, sellado_detalle = self.sellar_version_buena()
            else:
                sellado_ok, sellado_detalle = True, "última versión buena disponible"
            hallazgos = self.inspeccionar()
            reparaciones = self.reparar(hallazgos)
            verificado, detalle_verificacion = self.verificar_directorio(
                self.root, con_pruebas=True
            )
            if (
                not verificado
                and any(item.codigo == "codigo_modificado" for item in hallazgos)
                and self._baseline_valida()
            ):
                restaurado, detalle_restauracion = self.restaurar_codigo()
                reparaciones.append(
                    ResultadoReparacion(
                        "regresion_pruebas",
                        restaurado,
                        detalle_restauracion,
                    )
                )
                verificado, detalle_verificacion = self.verificar_directorio(
                    self.root, con_pruebas=True
                )
            if verificado:
                detalle_evolucion = self._observar_evolucion(
                    any(item.codigo == "error_en_registro" for item in hallazgos)
                )
                self.snapshot_memoria()
            else:
                detalle_evolucion = "detenida porque la verificación no pasó"
            estado_update, detalle_update = self.comprobar_actualizacion(
                forzar=forzar_actualizacion
            )
            pendientes = []
            for hallazgo in hallazgos:
                if hallazgo.nivel == "info":
                    continue
                coincidentes = [
                    reparacion
                    for reparacion in reparaciones
                    if reparacion.codigo == hallazgo.codigo
                ]
                if not coincidentes or not all(item.ok for item in coincidentes):
                    pendientes.append(asdict(hallazgo))
            informe = {
                "version_automejora": AUTOMEJORA_VERSION,
                "version_luna": version_directorio(self.root),
                "ultima_revision": ahora_iso(),
                "ultima_revision_epoch": time.time(),
                "duracion_segundos": round(time.monotonic() - inicio, 2),
                "ok": bool(verificado and sellado_ok and not pendientes),
                "agentes": {
                    "centinela": "activo",
                    "diagnostico": "activo",
                    "reparacion": "activo",
                    "verificacion": "activo",
                    "poliglota": "activo",
                    "evolucion": detalle_evolucion,
                    "actualizacion": estado_update,
                },
                "hallazgos": [asdict(item) for item in hallazgos],
                "reparaciones": [asdict(item) for item in reparaciones],
                "pendientes": pendientes,
                "verificacion": detalle_verificacion,
                "sellado": sellado_detalle,
                "evolucion": detalle_evolucion,
                "actualizacion": detalle_update,
            }
            self.estado.update(informe)
            guardar_json_atomico(self.state_file, self.estado)
            self._evento(
                "ciclo",
                f"ok={informe['ok']}; hallazgos={len(hallazgos)}; reparaciones={len(reparaciones)}",
            )
            huella = hashlib.sha256(
                json.dumps(
                    {
                        "reparaciones": [asdict(item) for item in reparaciones],
                        "pendientes": pendientes,
                        "update": estado_update,
                    },
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            ultima_huella = str(self.estado.get("ultima_huella_aviso", ""))
            importantes = [item for item in reparaciones if item.ok] or pendientes
            if avisar and importantes and huella != ultima_huella:
                reparadas = sum(1 for item in reparaciones if item.ok)
                texto = (
                    "🛠️ Automejora de Luna terminó.\n"
                    f"✅ Reparaciones: {reparadas}\n"
                    f"⚠️ Pendientes: {len(pendientes)}\n"
                    f"🧪 Verificación: {'correcta' if verificado else 'falló'}"
                )
                self.notificador.enviar(texto)
                self.estado["ultima_huella_aviso"] = huella
                guardar_json_atomico(self.state_file, self.estado)
            return informe
        finally:
            bloqueo.close()


def resumen_estado(root: Path | str | None = None) -> str:
    raiz = Path(root or Path(__file__).resolve().parent)
    estado = leer_json(raiz / "estado_automejora.json", {})
    if not estado:
        return "⏳ Automejora instalada; todavía no terminó su primer ciclo."
    agentes = estado.get("agentes", {})
    lineas = [
        "🧠 Automejora de Luna:",
        f"{'✅' if estado.get('ok') else '⚠️'} Último ciclo: {estado.get('ultima_revision', 'sin fecha')}",
        f"🤖 Versión Luna: {estado.get('version_luna', 'desconocida')}",
        f"🔎 Centinela: {agentes.get('centinela', 'sin datos')}",
        f"🩺 Diagnóstico: {agentes.get('diagnostico', 'sin datos')}",
        f"🛠️ Reparación: {agentes.get('reparacion', 'sin datos')}",
        f"🧪 Verificación: {agentes.get('verificacion', 'sin datos')}",
        f"🌐 Políglota: {agentes.get('poliglota', 'sin datos')}",
        f"🧬 Evolución: {agentes.get('evolucion', 'sin datos')}",
        f"♻️ Actualización: {agentes.get('actualizacion', 'sin datos')}",
        f"✅ Reparaciones últimas: {len(estado.get('reparaciones', []))}",
        f"⚠️ Pendientes: {len(estado.get('pendientes', []))}",
    ]
    return "\n".join(lineas)


def main() -> int:
    parser = argparse.ArgumentParser(description="Agentes de mantenimiento seguro de Luna")
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--once", action="store_true", help="ejecuta un ciclo")
    grupo.add_argument("--daemon", action="store_true", help="vigila continuamente")
    grupo.add_argument("--status", action="store_true", help="muestra el último estado")
    grupo.add_argument("--seal", action="store_true", help="guarda la versión buena actual")
    grupo.add_argument("--update", action="store_true", help="fuerza la revisión de actualización")
    parser.add_argument("--no-notify", action="store_true", help="no avisa por Telegram")
    opciones = parser.parse_args()
    sistema = SistemaAutomejora()
    if opciones.status:
        print(resumen_estado(sistema.root))
        return 0
    if opciones.seal:
        ok, detalle = sistema.sellar_version_buena()
        print(("✅ " if ok else "❌ ") + detalle)
        return 0 if ok else 1
    if opciones.daemon:
        try:
            intervalo = int(os.environ.get("LUNA_AUTOMEJORA_INTERVAL", "300"))
        except ValueError:
            intervalo = 300
        intervalo = max(60, min(intervalo, 3_600))
        while True:
            try:
                informe = sistema.ciclo(avisar=not opciones.no_notify)
                print(
                    f"{ahora_iso()} ciclo ok={informe.get('ok')} "
                    f"pendientes={len(informe.get('pendientes', []))}",
                    flush=True,
                )
            except Exception as error:
                sistema._evento("error_controlado", f"{type(error).__name__}: {error}")
                print(f"⚠️ Error controlado: {type(error).__name__}", file=sys.stderr, flush=True)
            time.sleep(intervalo)
    informe = sistema.ciclo(
        forzar_actualizacion=opciones.update,
        avisar=not opciones.no_notify,
    )
    print(resumen_estado(sistema.root))
    return 0 if informe.get("ok", False) else 1


if __name__ == "__main__":
    raise SystemExit(main())
