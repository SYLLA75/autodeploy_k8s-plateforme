#!/bin/bash
# ------------------------------------------------------------------------------
# Compatibilité : l'ancien point d'entrée s'appelait test.sh.
# Le script officiel est désormais deploy.sh, qui accepte des options.
# ------------------------------------------------------------------------------
echo "ℹ️  test.sh est conservé pour compatibilité — utilise ./deploy.sh (voir --help)."
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/deploy.sh" "$@"
