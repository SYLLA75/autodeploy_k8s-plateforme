#!/bin/bash
# ==============================================================================
#  campagne.sh — enregistrer les conditions d'une campagne de mesure
# ==============================================================================
#
#  POURQUOI CE SCRIPT
#
#  Les réglages d'ANALYSE sont déjà notés tout seuls : graphe_en écrit un
#  manifest.json complet, et origin.json donne la clé de chaque fichier brut.
#  Quelqu'un qui reçoit ces deux fichiers peut refaire exactement la même
#  analyse.
#
#  Ce qui n'était noté nulle part, c'est la CONDITION EXPÉRIMENTALE : cette
#  campagne est-elle la référence saine, ou une injection ? Quelle charge a été
#  appliquée, et à quels instants ? L'information vivait sur le master —
#  c'est-à-dire sur la machine que destroy.sh efface.
#
#  D'OÙ VIENT LE PROFIL DE CHARGE
#
#  D'un seul fichier : journaux/paliers.tsv, écrit par loadgen.sh à chaque
#  changement CONFIRMÉ par Locust. Format fixe, données seules.
#
#  Ce script ne lit AUCUN texte affiché. Reconstituer un profil en relisant des
#  phrases obligerait à en connaître la formulation exacte : un mot changé, et
#  l'analyse casse sans rien signaler.
#
#  Le registre s'accumule sur toute la vie du cluster. Seuls les paliers de la
#  fenêtre exploitable sont retenus, plus celui qui était en vigueur au début —
#  sans lui on ignorerait la charge de départ.
#
#  Usage (depuis le nœud de contrôle, à la fin d'une campagne) :
#      ./campagne.sh noter <nom> [--type saine|panne] [--cause <nom>]
#
#  Variables reconnues :
#    CAMPAGNE_SSH      (défaut: master)                cible ssh du master
#    CAMPAGNE_DISTANT  (défaut: /home/ubuntu/autodeploy) racine du projet là-bas
# ==============================================================================
set -uo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CIBLE_SSH="${CAMPAGNE_SSH:-master}"
DISTANT="${CAMPAGNE_DISTANT:-/home/ubuntu/autodeploy}"

say()  { echo "  [campagne] $*"; }
ok()   { echo "  [campagne] OK  $*"; }
warn() { echo "  [campagne] ATTENTION: $*" >&2; }
fail() { echo "  [campagne] ERREUR: $*" >&2; exit 1; }

# secondes depuis l'époque, ou rien si la date est illisible
epoque() { date -u -d "$1" +%s 2>/dev/null; }

usage() {
    cat <<EOF

  campagne.sh — enregistrer les conditions d'une campagne de mesure

    ./campagne.sh noter <nom> [--type saine|panne] [--cause <nom>]

  Exemples :
    ./campagne.sh noter saine-01
    ./campagne.sh noter panne-cpu-01 --type panne --cause machine_saturee

  Écrit campagnes/<nom>/campagne.yaml et y rapatrie les journaux du master,
  qui disparaîtraient avec le cluster.

EOF
}

noter() {
    local nom="${1:-}" type="saine" cause=""
    shift || true
    [ -n "$nom" ] || fail "Donne un nom : $0 noter saine-01"
    case "$nom" in *[!A-Za-z0-9._-]*) fail "Nom invalide : « $nom » (lettres, chiffres, . _ -)" ;; esac

    while [ $# -gt 0 ]; do
        case "$1" in
            --type)  type="${2:-}"; shift 2 ;;
            --cause) cause="${2:-}"; shift 2 ;;
            *) fail "Option inconnue : $1" ;;
        esac
    done
    case "$type" in saine|panne) ;; *) fail "--type accepte « saine » ou « panne »" ;; esac
    [ "$type" != "panne" ] || [ -n "$cause" ] || fail "--type panne exige --cause <nom>"

    local dossier="$RACINE/campagnes/$nom"
    [ -d "$dossier" ] && warn "« $nom » existe déjà — le contenu sera remplacé."
    mkdir -p "$dossier/journaux" || fail "Impossible de créer $dossier"

    ssh -o BatchMode=yes "$CIBLE_SSH" true 2>/dev/null \
        || fail "Master injoignable via « ssh $CIBLE_SSH ». Le cluster est-il debout ?"

    # ------------------------------------------------------- la fenêtre mesurée
    say "Lecture de la plage exploitable…"
    local fenetre etat
    fenetre=$(ssh "$CIBLE_SSH" "JOURNAL_OFF=1 bash '$DISTANT/apps/collecte.sh' fenetre" 2>&1)
    say "Lecture de l'état du cluster…"
    etat=$(ssh "$CIBLE_SSH" "JOURNAL_OFF=1 bash '$DISTANT/apps/collecte.sh' etat" 2>&1)

    local plage_date plage_de plage_a
    plage_date=$(printf '%s\n' "$fenetre" | grep -oP '^\s+date:\s+\K[0-9-]+'   | head -1)
    plage_de=$(printf '%s\n' "$fenetre"   | grep -oP '^\s+from:\s+"\K[0-9:]+' | head -1)
    plage_a=$(printf '%s\n' "$fenetre"    | grep -oP '^\s+to:\s+"\K[0-9:]+'   | head -1)

    local debut_s fin_s
    debut_s=$(epoque "${plage_date} ${plage_de}")
    fin_s=$(epoque "${plage_date} ${plage_a}")

    # ------------------------------------------------------- le profil de charge
    say "Lecture du registre des paliers…"
    local registre
    registre=$(ssh "$CIBLE_SSH" "cat '$DISTANT/journaux/paliers.tsv'" 2>/dev/null)

    local lignes=() avant="" retenus=0 hors=0
    if [ -n "$registre" ] && [ -n "$debut_s" ] && [ -n "$fin_s" ]; then
        while IFS=$'\t' read -r instant n _spawn _cible origine; do
            case "${instant:-}" in ''|'#'*) continue ;; esac
            local s; s=$(epoque "$instant") || continue
            [ -n "$s" ] || continue
            if [ "$s" -le "$debut_s" ]; then
                # Le dernier palier antérieur est la charge en vigueur au début.
                avant="  - { instant: $instant, voyageurs: $n, origine: ${origine:-inconnue}, note: en_vigueur_au_debut }"
            elif [ "$s" -le "$fin_s" ]; then
                lignes+=("  - { instant: $instant, voyageurs: $n, origine: ${origine:-inconnue} }")
            else
                hors=$((hors + 1))
            fi
        done <<< "$registre"
        [ -n "$avant" ] && retenus=$((retenus + 1))
        retenus=$((retenus + ${#lignes[@]}))
    fi

    # ----------------------------------------------------------------- le fichier
    local sortie="$dossier/campagne.yaml"
    {
        echo "# Conditions expérimentales — écrit par campagne.sh, ne pas éditer à la main."
        echo "# Les réglages d'analyse sont ailleurs : graphe_en/runs/<date>/graph/manifest.json"
        echo
        echo "campagne: $nom"
        echo "type: $type"
        [ -n "$cause" ] && echo "cause: $cause"
        echo "note_le: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
        echo
        echo "plage_exploitable:"
        echo "  date: ${plage_date:-inconnue}"
        echo "  from: \"${plage_de:-?}\""
        echo "  to:   \"${plage_a:-?}\""
        echo
        echo "# Source : journaux/paliers.tsv, écrit par loadgen.sh après confirmation"
        echo "# de Locust. Seuls les paliers de la fenêtre sont retenus, plus celui qui"
        echo "# était en vigueur au début."
        echo "profil_de_charge:"
        if [ -z "$registre" ]; then
            echo "  []   # registre absent sur le master"
        elif [ "$retenus" -eq 0 ]; then
            echo "  []   # aucun palier dans la fenêtre"
        else
            [ -n "$avant" ] && echo "$avant"
            printf '%s\n' "${lignes[@]}"
        fi
        echo
        echo "# Sortie verbatim de « collecte.sh fenetre » :"
        printf '%s\n' "$fenetre" | sed 's/^/#   /'
        echo
        echo "# Sortie verbatim de « collecte.sh etat » :"
        printf '%s\n' "$etat" | sed 's/^/#   /'
    } > "$sortie"

    # ------------------------------------------- les journaux, avant destroy.sh
    say "Rapatriement des journaux du master…"
    scp -q -r "$CIBLE_SSH:$DISTANT/journaux/." "$dossier/journaux/" 2>/dev/null \
        && ok "journaux copiés dans campagnes/$nom/journaux/" \
        || warn "Copie des journaux impossible — ils resteront sur le master."

    echo
    ok "campagne « $nom » enregistrée dans campagnes/$nom/campagne.yaml"
    say "  paliers retenus : $retenus"
    [ "$hors" -gt 0 ] && say "  paliers hors fenêtre, non retenus : $hors"
    [ -z "$registre" ] && warn "  registre des paliers absent : le générateur n'a jamais été installé,"
    [ -z "$registre" ] && warn "  ou loadgen.sh est antérieur au registre. Les journaux copiés restent"
    [ -z "$registre" ] && warn "  la seule trace de la charge appliquée."
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
        warn "Plage exploitable illisible — voir la sortie verbatim dans le fichier."
    fi
    say "Ce dossier est à committer : c'est la provenance de tes données."
}

case "${1:-}" in
    noter) shift; noter "$@" ;;
    *)     usage ;;
esac
