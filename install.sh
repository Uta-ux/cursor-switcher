#!/usr/bin/env bash
# Instala o cursor-switcher em ~/.local/bin e cria o lançador no menu de aplicativos.
set -euo pipefail

APP="cursor-switcher"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"

install -Dm755 "$SRC/$APP" "$BIN_DIR/$APP"

mkdir -p "$APPS_DIR"
# O .desktop do repo traz "Exec=<app>"; aqui vira o caminho absoluto real.
sed "s|^Exec=$APP|Exec=$BIN_DIR/$APP|" "$SRC/$APP.desktop" > "$APPS_DIR/$APP.desktop"
chmod 644 "$APPS_DIR/$APP.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPS_DIR" || true
fi

echo "Instalado: $BIN_DIR/$APP"
case ":$PATH:" in
    *":$BIN_DIR:"*) echo "Rode com: $APP" ;;
    *) echo "Aviso: $BIN_DIR nao esta no PATH. Rode com: $BIN_DIR/$APP" ;;
esac
