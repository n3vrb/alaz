#!/bin/sh
# Removes the Alaz user install. Pass --purge to also delete ~/.config/alaz.
exec "$(cd "$(dirname "$0")" && pwd)/install.sh" --uninstall "$@"
