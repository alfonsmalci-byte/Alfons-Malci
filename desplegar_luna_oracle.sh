#!/usr/bin/env bash
# Despliega Luna desde GitHub en Oracle y verifica el servicio antes de parar Termux.
set -Eeuo pipefail

REPO_URL="${LUNA_REPO_URL:-https://github.com/alfonsmalci-byte/Alfons-Malci.git}"
BRANCH="${LUNA_REPO_BRANCH:-main}"
LUNA_DIR="${LUNA_DIR:-$HOME/luna}"
HOST="${LUNA_CLOUD_HOST:-}"
REMOTE_USER="${LUNA_CLOUD_USER:-opc}"
PORT="${LUNA_CLOUD_PORT:-22}"
KEY="${LUNA_CLOUD_KEY:-}"
COPY_KEYS=0

uso() {
  printf '%s\n' \
    "Uso: bash desplegar_luna_oracle.sh --host IP --key RUTA.pem [opciones]" \
    "  --user USUARIO       Usuario SSH (por defecto: opc)" \
    "  --port PUERTO        Puerto SSH (por defecto: 22)" \
    "  --copiar-claves      Copia ~/luna/.env cifrado por SSH a Oracle" \
    "  --repo URL           Repositorio GitHub" \
    "  --branch RAMA        Rama GitHub (por defecto: main)"
}

while (($#)); do
  case "$1" in
    --host) HOST="${2:-}"; shift 2 ;;
    --user) REMOTE_USER="${2:-}"; shift 2 ;;
    --port) PORT="${2:-}"; shift 2 ;;
    --key) KEY="${2:-}"; shift 2 ;;
    --copiar-claves) COPY_KEYS=1; shift ;;
    --repo) REPO_URL="${2:-}"; shift 2 ;;
    --branch) BRANCH="${2:-}"; shift 2 ;;
    -h|--help) uso; exit 0 ;;
    *) printf '❌ Opción desconocida: %s\n' "$1" >&2; uso; exit 2 ;;
  esac
done

if [[ -z "$HOST" ]]; then
  read -r -p "IP pública de la instancia Oracle: " HOST
fi
if [[ -z "$KEY" ]]; then
  read -r -p "Ruta de la clave privada SSH (.pem): " KEY
fi
KEY="${KEY/#\~/$HOME}"

[[ "$HOST" =~ ^[A-Za-z0-9_.:-]+$ ]] || { printf '❌ Host inválido.\n' >&2; exit 2; }
[[ "$REMOTE_USER" =~ ^[A-Za-z_][A-Za-z0-9_.-]*$ ]] || { printf '❌ Usuario inválido.\n' >&2; exit 2; }
[[ "$PORT" =~ ^[0-9]+$ ]] && ((PORT >= 1 && PORT <= 65535)) || { printf '❌ Puerto inválido.\n' >&2; exit 2; }
[[ "$REPO_URL" =~ ^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(\.git)?$ ]] || { printf '❌ URL de GitHub inválida.\n' >&2; exit 2; }
[[ "$BRANCH" =~ ^[A-Za-z0-9._/-]+$ && "$BRANCH" != *".."* ]] || { printf '❌ Rama inválida.\n' >&2; exit 2; }
[[ -f "$KEY" ]] || { printf '❌ No existe la clave SSH: %s\n' "$KEY" >&2; exit 2; }
[[ -d "$LUNA_DIR/.git" ]] || { printf '❌ Falta el repositorio local en %s\n' "$LUNA_DIR" >&2; exit 2; }
chmod 600 "$KEY"

SSH=(ssh -o BatchMode=yes -o ConnectTimeout=12 -o StrictHostKeyChecking=accept-new -p "$PORT" -i "$KEY")
SCP=(scp -q -o BatchMode=yes -o ConnectTimeout=12 -o StrictHostKeyChecking=accept-new -P "$PORT" -i "$KEY")
DESTINO="$REMOTE_USER@$HOST"

printf '🔌 Comprobando SSH con Oracle...\n'
REMOTE_HOME="$("${SSH[@]}" "$DESTINO" 'printf %s "$HOME"')"
[[ "$REMOTE_HOME" == /* ]] || { printf '❌ Oracle no devolvió un HOME válido.\n' >&2; exit 1; }
printf '✅ SSH verificado: %s@%s\n' "$REMOTE_USER" "$HOST"

printf '📦 Preparando Git y Python en Oracle...\n'
"${SSH[@]}" -t "$DESTINO" \
  'if command -v dnf >/dev/null; then sudo dnf install -y git python3.11 python3.11-pip; elif command -v apt-get >/dev/null; then sudo apt-get update && sudo apt-get install -y git python3 python3-pip; else echo "No hay gestor compatible" >&2; exit 1; fi'
REMOTE_PYTHON="$("${SSH[@]}" "$DESTINO" 'for p in python3.12 python3.11 python3.10 python3; do command -v "$p" >/dev/null 2>&1 || continue; "$p" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" && { command -v "$p"; exit 0; }; done; exit 1')" || {
  printf '❌ Oracle no tiene Python 3.10 o superior.\n' >&2
  exit 1
}
[[ "$REMOTE_PYTHON" == /* ]] || { printf '❌ Ruta de Python remota inválida.\n' >&2; exit 1; }

printf '⬇️ Instalando el código desde GitHub...\n'
"${SSH[@]}" "$DESTINO" sh -s -- "$REPO_URL" "$BRANCH" "$REMOTE_HOME" "$REMOTE_PYTHON" <<'REMOTE_INSTALL'
set -eu
repo=$1
branch=$2
remote_home=$3
remote_python=$4
if [ -d "$remote_home/luna/.git" ]; then
  git -C "$remote_home/luna" fetch origin "$branch"
  git -C "$remote_home/luna" checkout "$branch"
  git -C "$remote_home/luna" pull --ff-only origin "$branch"
else
  git clone --branch "$branch" --single-branch "$repo" "$remote_home/luna"
fi
"$remote_python" -m unittest discover -s "$remote_home/luna" -q
"$remote_python" -m pip install --user --disable-pip-version-check --quiet 'pypdf>=5' || true
REMOTE_INSTALL

if ((COPY_KEYS)); then
  [[ -f "$LUNA_DIR/.env" ]] || { printf '❌ Falta %s/.env\n' "$LUNA_DIR" >&2; exit 1; }
  [[ "$(stat -c '%a' "$LUNA_DIR/.env" 2>/dev/null || stat -f '%Lp' "$LUNA_DIR/.env")" == "600" ]] || chmod 600 "$LUNA_DIR/.env"
  printf '🔐 Copiando .env por SSH (nunca a GitHub)...\n'
  "${SCP[@]}" "$LUNA_DIR/.env" "$DESTINO:$REMOTE_HOME/luna/.env.nueva"
  "${SSH[@]}" "$DESTINO" sh -s -- "$REMOTE_HOME" <<'REMOTE_ENV'
set -eu
remote_home=$1
chmod 600 "$remote_home/luna/.env.nueva"
mv "$remote_home/luna/.env.nueva" "$remote_home/luna/.env"
REMOTE_ENV
else
  printf '❌ Falta --copiar-claves: sin .env el bot de la nube no puede arrancar.\n' >&2
  exit 2
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "$TMP_DIR"' EXIT
SERVICE_LOCAL="$TMP_DIR/luna-telegram.service"
cat >"$SERVICE_LOCAL" <<SERVICE
[Unit]
Description=Luna Telegram en Oracle
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=$REMOTE_USER
WorkingDirectory=$REMOTE_HOME/luna
ExecStart=$REMOTE_PYTHON $REMOTE_HOME/luna/telegram_luna.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
Environment=LUNA_RUNNING_IN_CLOUD=1

[Install]
WantedBy=multi-user.target
SERVICE

"${SCP[@]}" "$SERVICE_LOCAL" "$DESTINO:/tmp/luna-telegram.service"
printf '⚙️ Activando el servicio permanente en Oracle...\n'
"${SSH[@]}" -t "$DESTINO" \
  'sudo install -m 644 /tmp/luna-telegram.service /etc/systemd/system/luna-telegram.service && rm -f /tmp/luna-telegram.service && sudo systemctl daemon-reload && sudo systemctl enable --now luna-telegram.service'

ESTADO="$("${SSH[@]}" "$DESTINO" 'systemctl is-active luna-telegram.service 2>/dev/null || true')"
if [[ "$ESTADO" != "active" ]]; then
  printf '❌ El servicio remoto no está activo. Termux NO se detuvo.\n' >&2
  "${SSH[@]}" "$DESTINO" 'sudo systemctl status luna-telegram.service --no-pager -l || true'
  exit 1
fi

python - "$LUNA_DIR/.env" "$HOST" "$REMOTE_USER" "$PORT" "$KEY" <<'PY_ENV'
import os
import sys
from pathlib import Path

ruta = Path(sys.argv[1])
nuevos = {
    "LUNA_CLOUD_HOST": sys.argv[2],
    "LUNA_CLOUD_USER": sys.argv[3],
    "LUNA_CLOUD_PORT": sys.argv[4],
    "LUNA_CLOUD_KEY": sys.argv[5],
}
lineas = ruta.read_text(encoding="utf-8").splitlines()
salida = []
vistos = set()
for linea in lineas:
    limpio = linea.strip().removeprefix("export ").lstrip()
    nombre = limpio.split("=", 1)[0].strip() if "=" in limpio else ""
    if nombre in nuevos:
        if nombre not in vistos:
            valor = nuevos[nombre].replace("'", "'\"'\"'")
            salida.append(f"{nombre}='{valor}'")
            vistos.add(nombre)
    else:
        salida.append(linea)
for nombre, valor_original in nuevos.items():
    if nombre not in vistos:
        valor = valor_original.replace("'", "'\"'\"'")
        salida.append(f"{nombre}='{valor}'")
temporal = ruta.with_name(".env.cloud.tmp")
temporal.write_text("\n".join(salida).rstrip() + "\n", encoding="utf-8")
os.chmod(temporal, 0o600)
os.replace(temporal, ruta)
PY_ENV
chmod 600 "$LUNA_DIR/.env"

# Dos bots con el mismo token causan HTTP 409. Se para el local solo después
# de confirmar que Oracle está activo.
if command -v sv >/dev/null 2>&1; then
  sv down luna-telegram >/dev/null 2>&1 || true
fi

printf '%s\n' \
  '✅ NUBE VERIFICADA: SSH funciona.' \
  '✅ SERVICIO VERIFICADO: luna-telegram está active en Oracle.' \
  '✅ La copia de Termux se detuvo para evitar HTTP 409.' \
  '📌 Comprueba en Telegram con /nube y después envía Hola.'
