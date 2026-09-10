#!/bin/bash
# ==============================================================================
#  campagne.sh — piloter et enregistrer une campagne de mesure
# ==============================================================================
#
#  CE QUE FAIT CE SCRIPT
#
#  Une campagne, c'est une suite d'actions datées appliquées à un système qu'on
#  mesure. Ce script les applique lui-même, au lieu qu'on les tape à la main :
#
#      démarrer la collecte
#      appliquer le profil de charge, palier par palier
#      arrêter la collecte
#      calculer la fenêtre exploitable
#      écrire le compte rendu
#
#  POURQUOI UN PILOTE PLUTÔT QUE DES COMMANDES À LA MAIN
#
#  Trois raisons, par ordre d'importance.
#
#  1. Les instants deviennent exacts. À la main, un palier dure « à peu près
#     quinze minutes ». La frontière entre deux niveaux de charge sert
#     d'étiquette aux fenêtres de mesure : floue de deux minutes, les fenêtres
#     autour deviennent ambiguës.
#
#  2. On ne peut plus oublier. Le geste qui applique un palier est celui qui
#     l'enregistre. Il ne peut exister ni palier sans trace, ni trace sans
#     palier.
#
#  3. Une campagne d'injection durera cinq heures. Personne ne reste devant.
#
#  POURQUOI SUR LE NŒUD DE CONTRÔLE, ET PAS SUR LE MASTER
#
#  Parce que le compte rendu naît là où il doit vivre. Le master est jetable —
#  destroy.sh l'efface, et avec lui tout ce qu'il portait. Écrire ici supprime
#  l'étape « rapatrier à la fin », donc supprime l'oubli possible.
#
#  Le réseau n'est pas un risque : le pilote dort, puis lance une commande
#  courte. Si elle échoue, l'échec est écrit dans le compte rendu au lieu d'être
#  passé sous silence.
#
#  À LANCER SOUS TMUX. La campagne dure des heures ; une session SSH qui tombe
#  emporterait le pilote avec elle.
#
#  Usage :
#      tmux new -s campagne
#      ./campagne.sh <nom> --profil "10:15,25:15,10:15,40:15"
#
#  Le profil se lit « voyageurs:minutes », séparés par des virgules.
#
#  Options :
#      --profil <p>      obligatoire — les paliers à appliquer
#      --type <t>        saine (défaut) ou panne
#      --cause <c>       obligatoire si --type panne
#      --sans-collecte   ne pilote pas la collecte (elle est déjà en route)
#      --marge <min>     marge écartée de chaque côté (défaut : celle de collecte.sh)
#
#  Variables reconnues :
#      CAMPAGNE_SSH      (défaut: master)
#      CAMPAGNE_DISTANT  (défaut: /home/ubuntu/autodeploy)
# ==============================================================================
set -uo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CIBLE="${CAMPAGNE_SSH:-master}"
DISTANT="${CAMPAGNE_DISTANT:-/home/ubuntu/autodeploy}"

[ -f "$RACINE/apps/journal.sh" ] && JOURNAL_NOM="campagne" . "$RACINE/apps/journal.sh"

say()  { echo "  [campagne] $*"; }
ok()   { echo "  [campagne] OK  $*"; }
warn() { echo "  [campagne] ATTENTION: $*" >&2; }
fail() { echo "  [campagne] ERREUR: $*" >&2; exit 1; }
maintenant() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# Chaque action du déroulé est ajoutée ici au fur et à mesure, jamais à la fin :
# si le pilote est interrompu, ce qui a déjà eu lieu reste écrit.
DEROULE=""
noter_action() { DEROULE="${DEROULE}  - { instant: $(maintenant), $* }
"; }

# ------------------------------------------------------------------------------
distant() { ssh "$CIBLE" "JOURNAL_OFF=1 bash '$DISTANT/apps/$1' ${*:2}" 2>&1; }

usage() {
    sed -n '/^#  Usage :/,/^# ===/p' "$0" | sed 's/^#\s\?//' | head -n -1
    exit 2
}

# ------------------------------------------------------------------------------
NOM=""; PROFIL=""; TYPE="saine"; CAUSE=""; COLLECTE=1; MARGE=""
[ $# -gt 0 ] || usage
NOM="$1"; shift
case "$NOM" in -*|'') usage ;; *[!A-Za-z0-9._-]*) fail "Nom invalide : « $NOM »" ;; esac

while [ $# -gt 0 ]; do
    case "$1" in
        --profil)        PROFIL="${2:-}"; shift 2 ;;
        --type)          TYPE="${2:-}"; shift 2 ;;
        --cause)         CAUSE="${2:-}"; shift 2 ;;
        --marge)         MARGE="${2:-}"; shift 2 ;;
        --sans-collecte) COLLECTE=0; shift ;;
        -h|--help)       usage ;;
        *) fail "Option inconnue : $1" ;;
    esac
done

[ -n "$PROFIL" ] || fail "Le profil est obligatoire : --profil \"10:15,25:15\""
case "$TYPE" in saine|panne) ;; *) fail "--type accepte « saine » ou « panne »" ;; esac
[ "$TYPE" != "panne" ] || [ -n "$CAUSE" ] || fail "--type panne exige --cause <nom>"

# ------------------------------------------------------ lecture du profil
# Refusé tôt et en entier : découvrir une faute de frappe à la troisième heure
# d'une campagne coûte la campagne.
PALIERS=(); TOTAL=0
IFS=',' read -ra MORCEAUX <<< "$PROFIL"
for m in "${MORCEAUX[@]}"; do
    m="${m// /}"
    [ -n "$m" ] || continue
    case "$m" in
        *:*) ;;
        *) fail "Palier « $m » : il faut « voyageurs:minutes », par exemple 25:15" ;;
    esac
    v="${m%%:*}"; d="${m##*:}"
    case "$v" in ''|*[!0-9]*) fail "Palier « $m » : « $v » n'est pas un nombre de voyageurs" ;; esac
    case "$d" in ''|*[!0-9]*) fail "Palier « $m » : « $d » n'est pas un nombre de minutes" ;; esac
    [ "$v" -gt 0 ] || fail "Palier « $m » : au moins un voyageur"
    [ "$d" -gt 0 ] || fail "Palier « $m » : au moins une minute"
    PALIERS+=("$v:$d"); TOTAL=$((TOTAL + d))
done
[ "${#PALIERS[@]}" -gt 0 ] || fail "Profil vide."

DOSSIER="$RACINE/campagnes/$NOM"
[ -d "$DOSSIER" ] && warn "« $NOM » existe déjà — son contenu sera remplacé."
mkdir -p "$DOSSIER/journaux" || fail "Impossible de créer $DOSSIER"

# ------------------------------------------------------------ le plan annoncé
echo
say "Campagne « $NOM »  ·  type : $TYPE${CAUSE:+  ·  cause : $CAUSE}"
say "Master : $CIBLE"
echo
say "Profil demandé :"
for p in "${PALIERS[@]}"; do
    printf "      %4s voyageurs pendant %3s minutes\n" "${p%%:*}" "${p##*:}"
done
say "Durée totale : $TOTAL minutes ($(printf '%dh%02d' $((TOTAL/60)) $((TOTAL%60))))"
[ "$COLLECTE" = "1" ] && say "La collecte sera démarrée puis arrêtée par ce script." \
                      || say "La collecte n'est PAS pilotée (--sans-collecte)."
echo
say "Départ dans 10 secondes — Ctrl-C pour annuler."
sleep 10
echo

# ------------------------------------------------------------------ préparation
ssh -o BatchMode=yes "$CIBLE" true 2>/dev/null \
    || fail "Master injoignable via « ssh $CIBLE ». Le cluster est-il debout ?"
etat_avant=$(distant collecte.sh etat)
noter_action "action: etat_initial"

if [ "$COLLECTE" = "1" ]; then
    say "Démarrage de la collecte…"
    if sortie=$(distant collecte.sh demarrer); then
        ok "collecte démarrée"
        noter_action "action: collecte_demarree"
    else
        printf '%s\n' "$sortie" | sed 's/^/      /' >&2
        fail "Impossible de démarrer la collecte."
    fi
fi

# --------------------------------------------------------------- les paliers
echo
rates=0; echoues=0; i=0
for p in "${PALIERS[@]}"; do
    i=$((i + 1)); v="${p%%:*}"; d="${p##*:}"
    say "[$i/${#PALIERS[@]}] $v voyageurs pendant $d minutes"
    if sortie=$(distant loadgen.sh scale "$v"); then
        printf '%s\n' "$sortie" | sed 's/^/      /'
        noter_action "action: charge, voyageurs: $v, resultat: confirme"
        rates=$((rates + 1))
    else
        printf '%s\n' "$sortie" | sed 's/^/      /' >&2
        warn "Palier $v non confirmé — la campagne continue, l'échec est enregistré."
        noter_action "action: charge, voyageurs: $v, resultat: NON_CONFIRME"
        echoues=$((echoues + 1))
    fi
    say "      … $d minutes d'attente (fin vers $(date -u -d "+$d minutes" '+%H:%M') UTC)"
    sleep $((d * 60))
done
echo

# ----------------------------------------------------------------- clôture
if [ "$COLLECTE" = "1" ]; then
    say "Arrêt de la collecte…"
    distant collecte.sh arreter >/dev/null && ok "collecte arrêtée" \
        || warn "L'arrêt de la collecte a échoué — vérifie avec collecte.sh etat."
    noter_action "action: collecte_arretee"
fi

say "Calcul de la fenêtre exploitable…"
fenetre=$(distant collecte.sh fenetre ${MARGE:+--marge "$MARGE"})
etat_apres=$(distant collecte.sh etat)

plage_date=$(printf '%s\n' "$fenetre" | grep -oP '^\s+date:\s+\K[0-9-]+'   | head -1)
plage_de=$(printf '%s\n' "$fenetre"   | grep -oP '^\s+from:\s+"\K[0-9:]+' | head -1)
plage_a=$(printf '%s\n' "$fenetre"    | grep -oP '^\s+to:\s+"\K[0-9:]+'   | head -1)

say "Rapatriement du registre des paliers et des journaux…"
registre=$(ssh "$CIBLE" "cat '$DISTANT/journaux/paliers.tsv'" 2>/dev/null)
scp -q -r "$CIBLE:$DISTANT/journaux/." "$DOSSIER/journaux/" 2>/dev/null \
    && ok "journaux copiés" || warn "copie des journaux impossible"

# ------------------------------------------------------------- le compte rendu
sortie_yaml="$DOSSIER/campagne.yaml"
{
    echo "# Conditions expérimentales — écrit par campagne.sh, ne pas éditer à la main."
    echo "# Les réglages d'analyse sont ailleurs : graphe_en/runs/<date>/graph/manifest.json"
    echo
    echo "campagne: $NOM"
    echo "type: $TYPE"
    [ -n "$CAUSE" ] && echo "cause: $CAUSE"
    echo "pilote_le: $(maintenant)"
    echo
    echo "profil_demande: \"$PROFIL\""
    echo "duree_prevue_min: $TOTAL"
    echo "paliers_confirmes: $rates"
    echo "paliers_non_confirmes: $echoues"
    echo
    echo "plage_exploitable:"
    echo "  date: ${plage_date:-inconnue}"
    echo "  from: \"${plage_de:-?}\""
    echo "  to:   \"${plage_a:-?}\""
    echo
    echo "# Ce que le pilote a fait, dans l'ordre."
    echo "deroule:"
    printf '%s' "$DEROULE"
    echo
    echo "# Registre écrit par loadgen.sh après vérification de la charge RÉELLE."
    echo "# instant_demande / instant_effectif encadrent la montée, pendant laquelle"
    echo "# la charge n'est ni l'ancienne ni la nouvelle."
    echo "paliers_mesures: |"
    if [ -n "$registre" ]; then printf '%s\n' "$registre" | sed 's/^/  /'
    else echo "  (registre absent sur le master)"; fi
    echo
    echo "# Sortie verbatim de « collecte.sh fenetre » :"
    printf '%s\n' "$fenetre" | sed 's/^/#   /'
    echo
    echo "# État du cluster AVANT :"
    printf '%s\n' "$etat_avant" | sed 's/^/#   /'
    echo
    echo "# État du cluster APRÈS :"
    printf '%s\n' "$etat_apres" | sed 's/^/#   /'
} > "$sortie_yaml"

echo
ok "campagne « $NOM » terminée"
say "  compte rendu : campagnes/$NOM/campagne.yaml"
say "  paliers      : $rates confirmé(s), $echoues non confirmé(s)"
[ "$echoues" -gt 0 ] && warn "  des paliers n'ont pas abouti — voir « deroule » dans le compte rendu"
echo
if [ -n "$plage_de" ]; then
    say "À recopier dans graphe_en/config.yaml :"
    echo
    echo "    range:"
    echo "      date:       $plage_date"
    echo "      from:       \"$plage_de\""
    echo "      to:         \"$plage_a\""
    echo
else
    warn "Plage exploitable illisible — voir la sortie verbatim dans le compte rendu."
fi
say "Ce dossier est à committer : c'est la provenance de tes données."
