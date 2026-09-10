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
#  campagne est-elle la référence saine, ou une injection ? Quel profil de charge
#  a été appliqué, et à quels instants ? L'information vivait en texte libre dans
#  les journaux du master — c'est-à-dire sur la machine que destroy.sh efface.
#
#  Ce script la rassemble, la range à côté du dépôt, et rapatrie les journaux.
#
#  UNE LIGNE DE JOURNAL N'EST PAS UNE PREUVE
#
#  Avant le correctif du 2026-09-10, loadgen.sh écrivait « Passage à N
#  voyageurs — instant : … » AVANT de tenter le changement, et l'appel échouait
#  systématiquement (wget absent de l'image). Les journaux d'alors contiennent
#  donc des changements qui n'ont pas eu lieu. Un changement n'est retenu ici que
#  si le même journal porte la confirmation de Locust ; les autres sont signalés
#  et écartés, jamais silencieusement recopiés.
#
#  Usage (depuis le nœud de contrôle, à la fin d'une campagne) :
#      ./campagne.sh noter <nom> [--type saine|panne] [--cause <nom>]
#
#  Exemples :
#      ./campagne.sh noter saine-01
#      ./campagne.sh noter panne-cpu-01 --type panne --cause machine_saturee
# ==============================================================================
set -uo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CIBLE_SSH="${CAMPAGNE_SSH:-master}"
DISTANT="${CAMPAGNE_DISTANT:-/home/ubuntu/autodeploy}"

say()  { echo "  [campagne] $*"; }
ok()   { echo "  [campagne] ✅ $*"; }
warn() { echo "  [campagne] ATTENTION: $*" >&2; }
fail() { echo "  [campagne] ERREUR: $*" >&2; exit 1; }

# ------------------------------------------------------------------------------
# profil_de_charge — les changements de charge RÉELLEMENT appliqués
# ------------------------------------------------------------------------------
# Chaque appel à « loadgen.sh scale » écrit son propre journal. On les lit tous,
# et on ne garde un changement que si Locust l'a confirmé dans le même fichier.
# ------------------------------------------------------------------------------
profil_de_charge() {
    # Le script distant part par stdin plutôt que dans une chaîne : sans cela il
    # faudrait échapper trois niveaux de guillemets, et la moindre erreur passe
    # inaperçue puisque ssh renvoie la sortie du shell, pas celle du script.
    ssh "$CIBLE_SSH" "DISTANT='$DISTANT' bash -s" 2>/dev/null <<'DISTANTEOF'
for f in "$DISTANT"/journaux/loadgen-*.log; do
    [ -f "$f" ] || continue
    ligne=$(grep -h 'Passage à' "$f" 2>/dev/null | head -1)
    [ -n "$ligne" ] || continue
    if grep -q 'Locust répond' "$f" 2>/dev/null; then
        echo "CONFIRME|$ligne"
    else
        echo "ECHOUE|$ligne"
    fi
done
DISTANTEOF
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

    say "Interrogation du master ($CIBLE_SSH)…"
    ssh -o BatchMode=yes "$CIBLE_SSH" true 2>/dev/null \
        || fail "Master injoignable via « ssh $CIBLE_SSH ». Le cluster est-il debout ?"

    # La plage exploitable, telle que collecte.sh la calcule. Capturée verbatim :
    # c'est ce texte qui sera recopié dans graphe_en/config.yaml.
    say "Lecture de la plage exploitable…"
    local fenetre
    fenetre=$(ssh "$CIBLE_SSH" "JOURNAL_OFF=1 bash $DISTANT/apps/collecte.sh fenetre" 2>&1)

    say "Lecture de l'état du cluster…"
    local etat
    etat=$(ssh "$CIBLE_SSH" "JOURNAL_OFF=1 bash $DISTANT/apps/collecte.sh etat" 2>&1)

    say "Lecture du profil de charge…"
    local profil retenus=0 ecartes=0
    # Trié sur l'instant, qui termine chaque ligne. Le glob distant les rend
    # déjà dans l'ordre des noms de fichier, mais on ne s'y fie pas.
    profil=$(profil_de_charge | sort -t'|' -k2)

    local plage_date plage_de plage_a
    plage_date=$(printf '%s\n' "$fenetre" | grep -oP 'date:\s+\K[0-9-]+' | head -1)
    plage_de=$(printf '%s\n' "$fenetre"  | grep -oP 'from:\s+"\K[0-9:]+' | head -1)
    plage_a=$(printf '%s\n' "$fenetre"   | grep -oP '^\s+to:\s+"\K[0-9:]+'   | head -1)

    # ---------------------------------------------------------------- le fichier
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
        echo "profil_de_charge:"
    } > "$sortie"

    if [ -z "$profil" ]; then
        echo "  []   # aucun changement de charge trouvé dans les journaux" >> "$sortie"
        warn "Aucun changement de charge trouvé — profil constant, ou journaux effacés."
    else
        while IFS='|' read -r etiquette ligne; do
            local n instant
            n=$(printf '%s' "$ligne" | grep -oP 'Passage à \K[0-9]+')
            instant=$(printf '%s' "$ligne" | grep -oP 'instant : \K\S+')
            if [ "$etiquette" = "CONFIRME" ]; then
                printf '  - { instant: %s, voyageurs: %s }\n' "$instant" "$n" >> "$sortie"
                retenus=$((retenus + 1))
            else
                printf '  # ÉCARTÉ — non confirmé par Locust : %s voyageurs à %s\n' \
                       "$n" "$instant" >> "$sortie"
                ecartes=$((ecartes + 1))
            fi
        done <<< "$profil"
    fi

    {
        echo
        echo "# Sortie verbatim de « collecte.sh fenetre » :"
        printf '%s\n' "$fenetre" | sed 's/^/#   /'
        echo
        echo "# Sortie verbatim de « collecte.sh etat » :"
        printf '%s\n' "$etat" | sed 's/^/#   /'
    } >> "$sortie"

    # ------------------------------------------- les journaux, avant destroy.sh
    say "Rapatriement des journaux du master…"
    scp -q -r "$CIBLE_SSH:$DISTANT/journaux/." "$dossier/journaux/" 2>/dev/null \
        && ok "Journaux copiés dans campagnes/$nom/journaux/" \
        || warn "Copie des journaux impossible — ils resteront sur le master."

    echo
    ok "Campagne « $nom » enregistrée."
    say "  fichier   : campagnes/$nom/campagne.yaml"
    say "  paliers   : $retenus retenu(s), $ecartes écarté(s)"
    [ "$ecartes" -gt 0 ] && warn "  $ecartes changement(s) non confirmé(s) — écartés, voir les commentaires du fichier."
    echo
    if [ -n "$plage_de" ]; then
        say "À recopier dans graphe_en/config.yaml :"
        echo
        echo "    range:"
        echo "      date:       $plage_date"
        echo "      from:       \"$plage_de\""
        echo "      to:         \"$plage_a\""
        echo
    fi
    say "Ce dossier est à committer : c'est la provenance de tes données."
}

case "${1:-}" in
    noter) shift; noter "$@" ;;
    *)
        cat <<EOF

  campagne.sh — enregistrer les conditions d'une campagne de mesure

    ./campagne.sh noter <nom> [--type saine|panne] [--cause <nom>]

  Exemples :
    ./campagne.sh noter saine-01
    ./campagne.sh noter panne-cpu-01 --type panne --cause machine_saturee

  Écrit campagnes/<nom>/campagne.yaml et y rapatrie les journaux du master,
  qui disparaîtraient avec le cluster.

EOF
        ;;
esac
