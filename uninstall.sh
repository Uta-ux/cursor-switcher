#!/usr/bin/env bash
# Remove o cursor-switcher do sistema.
set -euo pipefail

APP="cursor-switcher"
rm -f "$HOME/.local/bin/$APP" "$HOME/.local/share/applications/$APP.desktop"
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications" || true
fi
echo "Removido: $APP"
