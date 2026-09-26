#!/usr/bin/env python3
"""Inventaría componentes de Luna descargados sin ejecutar código desconocido.

Los archivos compatibles se copian a un almacén local para revisión. Los
secretos y memorias privadas nunca se copian, imprimen ni publican.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


EXTENSIONES = {
    ".py", ".sh", ".json", ".md", ".txt", ".toml", ".yaml", ".yml",
}
PALABRAS_LUNA = (
    "luna", "alfons", "telegram", "termux", "sabiduria", "gestor_keys",
    "automejora", "poliglota", "reparador", "puente_total",
)
MARCADORES_NUBE = ("/opt/luna", "systemctl", "/home/opc", "sudo ")
PREFIJOS_HISTORICOS = (
    "instalar_", "activar_", "mejorar_", "actualizar_", "actualizador_",
)
NOMBRES_PRIVADOS = {
    ".env", ".telegram_owner", "memoria_privada.json",
    "memoria_telegram.json", "perfil_privado.json",
}
CLAVES_PRIVADAS = re.compile(
    r"^(?:export\s+)?[A-Z][A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD|PASS|CLAVE)"
    r"\s*=\s*(.+)$",
    re.MULTILINE,
)
MARCADORES_PLACEHOLDER = (
    "tu_clave", "your_key", "cambia_esto", "placeholder", "example",
    "os.environ", "os.getenv", "${", "$(", "getenv(", "********",
)
MAX_BYTES = 5 * 1024 * 1024


def ahora_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256(ruta: Path) -> str:
    digest = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(131_072), b""):
            digest.update(bloque)
    return digest.hexdigest()


def leer_texto_limitado(ruta: Path) -> str:
    try:
        return ruta.read_bytes()[:MAX_BYTES].decode("utf-8", errors="replace")
    except OSError:
        return ""


def contiene_datos_privados(ruta: Path, texto: str) -> bool:
    nombre = ruta.name.lower()
    if nombre in NOMBRES_PRIVADOS or nombre.startswith(".env"):
        return True
    if any(fragmento in nombre for fragmento in ("private_key", "credentials", "secreto")):
        return True
    for coincidencia in CLAVES_PRIVADAS.finditer(texto):
        valor = coincidencia.group(1).strip().strip("'\"").lower()
        if len(valor) >= 10 and not any(marca in valor for marca in MARCADORES_PLACEHOLDER):
            return True
    return False


def relacionado(ruta: Path, texto: str) -> bool:
    muestra = (ruta.name + "\n" + texto[:8_000]).lower()
    return any(palabra in muestra for palabra in PALABRAS_LUNA)


def validar_sintaxis(ruta: Path, texto: str) -> tuple[bool | None, str]:
    if ruta.suffix.lower() == ".py":
        try:
            compile(texto, str(ruta), "exec")
            return True, "Python válido"
        except SyntaxError as error:
            return False, f"Python inválido: línea {error.lineno}"
    if ruta.suffix.lower() == ".json":
        try:
            json.loads(texto)
            return True, "JSON válido"
        except json.JSONDecodeError as error:
            return False, f"JSON inválido: línea {error.lineno}"
    return None, "no requiere compilación local"


def hashes_activos(raiz: Path) -> dict[str, str]:
    resultado: dict[str, str] = {}
    for ruta in raiz.iterdir() if raiz.exists() else ():
        if not ruta.is_file() or ruta.name.startswith("."):
            continue
        try:
            if ruta.stat().st_size <= MAX_BYTES:
                resultado[sha256(ruta)] = ruta.name
        except OSError:
            continue
    return resultado


def directorios_predeterminados() -> list[Path]:
    configurados = os.environ.get("LUNA_DOWNLOADS_DIRS", "")
    if configurados:
        return [Path(valor).expanduser() for valor in configurados.split(os.pathsep) if valor]
    hogar = Path.home()
    return [
        hogar / "downloads",
        hogar / "storage" / "downloads",
        Path("/storage/emulated/0/Download"),
    ]


def rutas_candidatas(directorios: Iterable[Path], excluir: Path) -> Iterable[Path]:
    vistos: set[tuple[int, int]] = set()
    excluir_resuelta = excluir.resolve()
    for directorio in directorios:
        try:
            base = directorio.expanduser().resolve()
        except OSError:
            continue
        if not base.is_dir() or base == excluir_resuelta or excluir_resuelta in base.parents:
            continue
        try:
            rutas = sorted(base.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            continue
        for ruta in rutas:
            try:
                if ruta.is_symlink() or not ruta.is_file():
                    continue
                estado = ruta.stat()
            except OSError:
                continue
            identidad = (estado.st_dev, estado.st_ino)
            if identidad in vistos or estado.st_size > MAX_BYTES:
                continue
            vistos.add(identidad)
            if ruta.name.lower() in NOMBRES_PRIVADOS or ruta.name.lower().startswith(".env") or ruta.suffix.lower() in EXTENSIONES or any(
                palabra in ruta.name.lower() for palabra in PALABRAS_LUNA
            ):
                yield ruta


def destino_unico(carpeta: Path, ruta: Path, digest: str) -> Path:
    destino = carpeta / ruta.name
    if not destino.exists():
        return destino
    try:
        if sha256(destino) == digest:
            return destino
    except OSError:
        pass
    return carpeta / f"{ruta.stem}_{digest[:10]}{ruta.suffix}"


def inventariar(
    raiz: Path,
    directorios: Iterable[Path],
    integrar: bool = False,
) -> dict[str, object]:
    raiz = raiz.expanduser().resolve()
    almacen = raiz / "componentes_descargados"
    activos = hashes_activos(raiz)
    entradas: list[dict[str, object]] = []

    for ruta in rutas_candidatas(directorios, almacen):
        texto = leer_texto_limitado(ruta)
        es_privado = contiene_datos_privados(ruta, texto)
        if not es_privado and not relacionado(ruta, texto):
            continue
        entrada: dict[str, object] = {
            "archivo": ruta.name,
            "origen": str(ruta),
            "bytes": ruta.stat().st_size,
        }
        if es_privado:
            entrada.update(
                categoria="PRIVADO_NO_COPIADO",
                accion="omitido; permanece en su ubicación privada",
            )
            entradas.append(entrada)
            continue

        digest = sha256(ruta)
        entrada["sha256"] = digest
        sintaxis_ok, detalle = validar_sintaxis(ruta, texto)
        entrada["sintaxis"] = detalle
        if digest in activos:
            categoria = "DUPLICADO_ACTIVO"
            subcarpeta = "duplicados"
            accion = f"ya está activo como {activos[digest]}"
        elif any(marca in texto for marca in MARCADORES_NUBE):
            categoria = "SOLO_NUBE"
            subcarpeta = "solo_nube"
            accion = "archivado; no se ejecuta en Termux"
        elif ruta.name.lower().startswith(PREFIJOS_HISTORICOS):
            categoria = "INSTALADOR_HISTORICO"
            subcarpeta = "historicos"
            accion = "archivado; sustituido por el integrador actual"
        elif sintaxis_ok is False:
            categoria = "INCOMPATIBLE"
            subcarpeta = "incompatibles"
            accion = "archivado para revisión; no se ejecuta"
        else:
            categoria = "COMPONENTE_PARA_REVISAR"
            subcarpeta = "revisar"
            accion = "archivado para comparación; no se ejecuta automáticamente"

        entrada.update(categoria=categoria, accion=accion)
        if integrar and categoria != "DUPLICADO_ACTIVO":
            carpeta = almacen / subcarpeta
            carpeta.mkdir(parents=True, exist_ok=True)
            destino = destino_unico(carpeta, ruta, digest)
            if not destino.exists():
                shutil.copy2(ruta, destino)
                destino.chmod(0o600)
            entrada["copia_local"] = str(destino.relative_to(raiz))
        entradas.append(entrada)

    conteos = Counter(str(entrada["categoria"]) for entrada in entradas)
    informe: dict[str, object] = {
        "generado": ahora_iso(),
        "raiz_luna": str(raiz),
        "modo": "integrar_sin_ejecutar" if integrar else "solo_inventario",
        "resumen": dict(sorted(conteos.items())),
        "archivos": entradas,
        "seguridad": {
            "codigo_descargado_ejecutado": False,
            "secretos_copiados": False,
            "archivos_activos_reemplazados": False,
        },
    }
    raiz.mkdir(parents=True, exist_ok=True)
    ruta_json = raiz / "inventario_descargas_luna.json"
    ruta_json.write_text(json.dumps(informe, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ruta_json.chmod(0o600)

    lineas = [
        "# Informe de integración local de Luna",
        "",
        f"Generado: {informe['generado']}",
        "",
        "Los archivos descargados fueron inventariados sin ejecutarlos. Los secretos y",
        "memorias privadas no se copiaron. Los componentes de nube se mantuvieron separados",
        "porque usan `/opt/luna` y `systemd`, que no corresponden a Termux.",
        "",
        "## Resultado",
        "",
    ]
    if conteos:
        lineas.extend(f"- {categoria}: {cantidad}" for categoria, cantidad in sorted(conteos.items()))
    else:
        lineas.append("- No se encontraron descargas relacionadas adicionales.")
    lineas.extend([
        "",
        "El detalle técnico está en `inventario_descargas_luna.json` y ambos archivos",
        "permanecen solo en el móvil; `.gitignore` impide publicarlos.",
        "",
    ])
    ruta_md = raiz / "INFORME_INTEGRACION_LUNA.md"
    ruta_md.write_text("\n".join(lineas), encoding="utf-8")
    ruta_md.chmod(0o600)
    return informe


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inventaría archivos de Luna descargados sin ejecutarlos ni copiar secretos."
    )
    parser.add_argument("--integrar", action="store_true", help="guarda copias seguras para revisión")
    parser.add_argument("--root", type=Path, default=Path(os.environ.get("LUNA_DIR", Path(__file__).parent)))
    parser.add_argument("--directorio", action="append", type=Path, help="directorio de descargas")
    opciones = parser.parse_args(argv)
    directorios = opciones.directorio or directorios_predeterminados()
    informe = inventariar(opciones.root, directorios, integrar=opciones.integrar)
    resumen = informe["resumen"]
    total = len(informe["archivos"])
    print(f"✅ Inventario terminado: {total} archivo(s) relacionado(s).")
    for categoria, cantidad in resumen.items():
        print(f"- {categoria}: {cantidad}")
    print("🔒 Ningún secreto se copió y ningún archivo descargado se ejecutó.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
