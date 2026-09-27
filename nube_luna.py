#!/usr/bin/env python3
"""Comprobación real y segura de la conexión SSH con la nube de Luna.

Que una instancia aparezca como ``Running`` en Oracle confirma que la máquina
existe, pero no confirma que Termux pueda entrar por SSH ni que Luna esté
ejecutándose allí. Este módulo separa expresamente esos estados.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path


NUBE_VERSION = "8.0.0"
HOST_VARS = ("LUNA_CLOUD_HOST", "ORACLE_CLOUD_HOST", "CLOUD_HOST", "SSH_HOST")
USER_VARS = ("LUNA_CLOUD_USER", "ORACLE_CLOUD_USER", "CLOUD_USER", "SSH_USER")
PORT_VARS = ("LUNA_CLOUD_PORT", "ORACLE_CLOUD_PORT", "CLOUD_PORT", "SSH_PORT")
KEY_VARS = ("LUNA_CLOUD_KEY", "ORACLE_CLOUD_KEY", "CLOUD_KEY", "SSH_KEY")


def _primera(entorno: dict[str, str], nombres: tuple[str, ...], defecto: str = "") -> str:
    for nombre in nombres:
        valor = str(entorno.get(nombre, "")).strip()
        if valor:
            return valor
    return defecto


def configuracion_nube(entorno: dict[str, str] | None = None) -> dict[str, object]:
    entorno = entorno or dict(os.environ)
    host = _primera(entorno, HOST_VARS)
    usuario = _primera(entorno, USER_VARS, "opc")
    puerto_texto = _primera(entorno, PORT_VARS, "22")
    clave_texto = _primera(entorno, KEY_VARS)
    try:
        puerto = int(puerto_texto)
    except ValueError:
        puerto = 0
    clave = Path(clave_texto).expanduser() if clave_texto else None
    errores: list[str] = []
    if host and not re.fullmatch(r"[A-Za-z0-9_.:-]+", host):
        errores.append("host inválido")
    if usuario and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", usuario):
        errores.append("usuario inválido")
    if not 1 <= puerto <= 65535:
        errores.append("puerto inválido")
    if clave and not clave.is_file():
        errores.append("archivo de clave SSH no encontrado")
    return {
        "configurada": bool(host),
        "host": host,
        "usuario": usuario,
        "puerto": puerto,
        "clave": clave,
        "errores": errores,
    }


def comprobar_nube(
    entorno: dict[str, str] | None = None,
    *,
    ejecutor=subprocess.run,
    ssh: str | None = None,
) -> dict[str, object]:
    """Comprueba SSH y el servicio remoto sin revelar rutas o credenciales."""
    entorno = entorno or dict(os.environ)
    if str(entorno.get("LUNA_RUNNING_IN_CLOUD", "")).strip().lower() in {
        "1", "true", "yes", "si", "sí",
    }:
        try:
            resultado = ejecutor(
                ["systemctl", "is-active", "luna-telegram.service"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            servicio = (resultado.stdout or "").strip() or "desconocido"
        except (OSError, subprocess.SubprocessError, TimeoutError) as error:
            servicio = f"error-{type(error).__name__}"
        return {
            "configurada": True,
            "ssh": False,
            "en_nube": True,
            "servicio": servicio,
            "detalle": (
                "Luna se está ejecutando en Oracle y systemd confirma el servicio"
                if servicio == "active"
                else f"Luna está en Oracle; servicio: {servicio}"
            ),
        }
    config = configuracion_nube(entorno)
    salida: dict[str, object] = {
        "configurada": config["configurada"],
        "ssh": False,
        "servicio": "no comprobado",
        "detalle": "",
    }
    if not config["configurada"]:
        salida["detalle"] = (
            "la instancia existe, pero falta LUNA_CLOUD_HOST en .env para "
            "comprobar Termux → Oracle"
        )
        return salida
    if config["errores"]:
        salida["detalle"] = "; ".join(config["errores"])
        return salida
    binario = ssh or shutil.which("ssh")
    if not binario:
        salida["detalle"] = "falta el comando ssh"
        return salida

    destino = f"{config['usuario']}@{config['host']}"
    comando = [
        binario,
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=8",
        "-o", "StrictHostKeyChecking=yes",
        "-p", str(config["puerto"]),
    ]
    clave = config["clave"]
    if clave:
        comando.extend(["-i", str(clave)])
    comando.extend(
        [
            destino,
            "if command -v systemctl >/dev/null 2>&1; then "
            "s=$(systemctl is-active luna-telegram 2>/dev/null || true); "
            "else s=no-systemd; fi; printf 'LUNA_SSH_OK\\n%s\\n' \"$s\"",
        ]
    )
    try:
        resultado = ejecutor(
            comando,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, TimeoutError) as error:
        salida["detalle"] = f"SSH no comprobado: {type(error).__name__}"
        return salida
    lineas = (resultado.stdout or "").splitlines()
    if resultado.returncode != 0 or not lineas or lineas[0] != "LUNA_SSH_OK":
        detalle = (resultado.stderr or "SSH rechazado").strip().splitlines()
        salida["detalle"] = (detalle[-1] if detalle else "SSH rechazado")[:180]
        return salida
    salida["ssh"] = True
    servicio = lineas[1].strip() if len(lineas) > 1 else "desconocido"
    salida["servicio"] = servicio
    salida["detalle"] = (
        "SSH verificado y luna-telegram activo"
        if servicio == "active"
        else f"SSH verificado; servicio luna-telegram: {servicio}"
    )
    return salida


def formatear_estado_nube(estado: dict[str, object]) -> str:
    lineas = ["☁️ Estado real de la nube:"]
    if estado.get("en_nube"):
        lineas.append("✅ Ejecución: este proceso está en Oracle")
        icono = "✅" if estado.get("servicio") == "active" else "❌"
        lineas.append(f"{icono} Servicio local systemd: {estado.get('servicio')}")
    elif not estado.get("configurada"):
        lineas.append("✅ Instancia Oracle: confirmada por el propietario como Running")
        lineas.append("➖ SSH Termux → Oracle: NO CONFIGURADO")
    elif estado.get("ssh"):
        lineas.append("✅ SSH Termux → Oracle: VERIFICADO")
        icono = "✅" if estado.get("servicio") == "active" else "❌"
        lineas.append(f"{icono} Servicio remoto luna-telegram: {estado.get('servicio')}")
    else:
        lineas.append("✅ Datos SSH: configurados")
        lineas.append("❌ SSH Termux → Oracle: FALLA")
    detalle = str(estado.get("detalle") or "").strip()
    if detalle:
        lineas.append(f"📌 {detalle}")
    return "\n".join(lineas)


if __name__ == "__main__":
    print(formatear_estado_nube(comprobar_nube()))
