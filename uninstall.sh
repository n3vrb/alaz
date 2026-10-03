#!/bin/sh
# Removes the ROG Control user install. Pass --purge to also delete ~/.config/rog-control.
exec "$(cd "$(dirname "$0")" && pwd)/install.sh" --uninstall "$@"
