# ==============================================================================
#  journal.sh — dupliquer la sortie d'un script dans un fichier
# ==============================================================================
#
#  À SOURCER, pas à exécuter :
#
#      ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#      JOURNAL_NOM="observability" . "$ICI/journal.sh"
#
#  POURQUOI
#
#  Ces scripts tournent sur le nœud de contrôle, à travers une connexion SSH,
#  et certains durent trois quarts d'heure. Si la connexion tombe, tout ce qui
#  s'est affiché disparaît : impossible de savoir où le script en était, ni
#  pourquoi il s'est arrêté. Un journal garde la trace même quand le processus
#  meurt — ce qu'aucune session persistante ne fait.
#
#  Il est complémentaire de tmux, qui garde le PROCESSUS en vie là où le journal
#  garde la TRACE.
#
#  COMMENT
#
#  La redirection passe par « exec » et une substitution de processus, et non
#  par un tube : le script garde son propre code de sortie. Un tube le
#  remplacerait par celui de « tee », et un échec passerait pour un succès.
#
#  La variable de garde empêche une seconde pose si un script en source un
#  autre : deux « tee » enchaînés doubleraient chaque ligne.
#
#  JOURNAL_OFF=1 désactive.
# ==============================================================================

# Accepte 1, true, yes, on — en majuscules ou non. Se limiter à « 1 » laisserait
# JOURNAL_OFF=true sans effet, en silence : l'utilisateur croirait avoir coupé le
# journal alors qu'il continue d'être écrit.
_journal_coupe=0
case "$(printf %s "${JOURNAL_OFF:-0}" | tr 'A-Z' 'a-z')" in
    1|true|yes|on|oui) _journal_coupe=1 ;;
esac
if [ -z "${JOURNAL_FICHIER:-}" ] && [ "$_journal_coupe" != "1" ]; then
    _journal_base="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/journaux"
    mkdir -p "$_journal_base" 2>/dev/null || _journal_base="/tmp"
    JOURNAL_FICHIER="$_journal_base/${JOURNAL_NOM:-script}-$(date +%Y%m%d-%H%M%S).log"
    export JOURNAL_FICHIER
    echo "  journal : $JOURNAL_FICHIER"
    echo "  suivi depuis une autre connexion :  tail -f $JOURNAL_FICHIER"
    echo
    exec > >(tee -a "$JOURNAL_FICHIER") 2>&1
    unset _journal_base
fi
