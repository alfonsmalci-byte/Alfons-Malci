#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
umask 077

REPO_DIR="$HOME/luna"
SERVICIO="luna-telegram"
SVDIR="${PREFIX}/var/service"
LOGDIR="${PREFIX}/var/log"
SERVICE_DIR="$SVDIR/$SERVICIO"
SERVICE_LOG_DIR="$LOGDIR/sv/$SERVICIO"
BOOT_DIR="$HOME/.termux/boot"
PID_FILE="${PREFIX}/var/run/service-daemon.pid"

if [ ! -d "$REPO_DIR/.git" ] || [ ! -f "$REPO_DIR/telegram_luna.py" ]; then
  echo "❌ Falta el repositorio o telegram_luna.py en $REPO_DIR"
  exit 1
fi

if [ ! -f "$REPO_DIR/.env" ]; then
  echo "❌ Falta $REPO_DIR/.env con las claves privadas."
  exit 1
fi
chmod 600 "$REPO_DIR/.env"

echo "📦 Preparando servicio permanente de Luna..."
pkg install termux-services -y

mkdir -p "$SERVICE_DIR/log" "$SERVICE_LOG_DIR" "$BOOT_DIR"

printf '%s\n' \
  '#!/data/data/com.termux/files/usr/bin/sh' \
  'cd "$HOME/luna" || exit 1' \
  'exec "$PREFIX/bin/python" "$HOME/luna/telegram_luna.py" 2>&1' \
  > "$SERVICE_DIR/run"

printf '%s\n' \
  '#!/data/data/com.termux/files/usr/bin/sh' \
  'mkdir -p "$PREFIX/var/log/sv/luna-telegram"' \
  'exec "$PREFIX/bin/svlogd" -tt "$PREFIX/var/log/sv/luna-telegram"' \
  > "$SERVICE_DIR/log/run"

printf '%s\n' \
  '#!/data/data/com.termux/files/usr/bin/sh' \
  'termux-wake-lock 2>/dev/null || true' \
  'export SVDIR="$PREFIX/var/service"' \
  'export LOGDIR="$PREFIX/var/log"' \
  'pid_file="$PREFIX/var/run/service-daemon.pid"' \
  'daemon_ok=0' \
  'if [ -r "$pid_file" ]; then' \
  '  IFS= read -r daemon_pid < "$pid_file" || true' \
  '  if [ -n "${daemon_pid:-}" ] && kill -0 "$daemon_pid" 2>/dev/null; then daemon_ok=1; fi' \
  'fi' \
  'if [ "$daemon_ok" -eq 0 ]; then' \
  '  rm -f "$pid_file"' \
  '  service-daemon start' \
  'fi' \
  'rm -f "$SVDIR/luna-telegram/down"' \
  'sv up luna-telegram' \
  > "$BOOT_DIR/00-luna-telegram"

chmod 700 "$SERVICE_DIR/run" "$SERVICE_DIR/log/run" "$BOOT_DIR/00-luna-telegram"

# Detiene únicamente una copia anterior verificada de telegram_luna.py.
if [ -r "$REPO_DIR/.luna_telegram.lock" ]; then
  IFS= read -r old_pid < "$REPO_DIR/.luna_telegram.lock" || true
  case "${old_pid:-}" in
    ''|*[!0-9]*) ;;
    *)
      if kill -0 "$old_pid" 2>/dev/null; then
        old_cmd="$(tr '\000' ' ' < "/proc/$old_pid/cmdline" 2>/dev/null || true)"
        case "$old_cmd" in
          *telegram_luna.py*)
            kill "$old_pid" 2>/dev/null || true
            sleep 2
            ;;
        esac
      fi
      ;;
  esac
fi

export SVDIR LOGDIR
daemon_ok=0
if [ -r "$PID_FILE" ]; then
  IFS= read -r daemon_pid < "$PID_FILE" || true
  if [ -n "${daemon_pid:-}" ] && kill -0 "$daemon_pid" 2>/dev/null; then
    daemon_ok=1
  fi
fi
if [ "$daemon_ok" -eq 0 ]; then
  rm -f "$PID_FILE"
  service-daemon start
fi

termux-wake-lock 2>/dev/null || true
rm -f "$SERVICE_DIR/down"
sv up "$SERVICIO"
sleep 4

estado="$(sv status "$SERVICIO" 2>&1 || true)"
echo "$estado"
case "$estado" in
  run:*)
    echo "✅ Luna quedó funcionando como servicio permanente."
    echo "✅ Puedes cerrar la ventana de Termux normalmente."
    echo "📄 Registro: $SERVICE_LOG_DIR/current"
    ;;
  *)
    echo "❌ El servicio no quedó activo."
    echo "Últimas líneas del registro:"
    tail -n 20 "$SERVICE_LOG_DIR/current" 2>/dev/null || true
    exit 1
    ;;
esac

echo
echo "IMPORTANTE PARA ANDROID:"
echo "1. Pon Termux en Batería → Sin restricciones."
echo "2. Instala Termux:Boot y ábrelo una sola vez para activar el arranque automático."
echo "3. No uses Forzar detención; Android impide que cualquier servicio se reinicie después de eso."
