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
#      injecter une panne à la minute dite, la retirer à l'heure dite
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
#     autour deviennent ambiguës. Une panne, plus encore : sa minute de début
#     est l'étiquette que le modèle doit apprendre.
#
#  2. On ne peut plus oublier. Le geste qui applique un palier est celui qui
#     l'enregistre. Il ne peut exister ni palier sans trace, ni trace sans
#     palier.
#
#  3. Une campagne d'injection dure des heures. Personne ne reste devant.
#
#  LES PANNES
#
#  Le pilote décide QUAND ; apps/panne.sh, sur le master, décide COMMENT et
#  consigne QUI a été touché. Une campagne de panne, c'est un profil de charge
#  ordinaire sur lequel une injection est posée à une minute donnée :
#
#      minute   0        5                        25       30
#               |--------|========================|--------|
#               25 voyageurs   panne « lenteur »   retour   fin
#
#      ./campagne.sh lenteur-01 --profil "25:30" --panne lenteur --a 5 --duree 20
#
#  Un témoin (file, consommateurs, charge des répliques et des hôtes) est relevé
#  juste avant, au milieu, et une minute après chaque injection. Il est recopié
#  tel quel dans le compte rendu.
#
#  Les instants sont calculés depuis un point de départ unique, pas cumulés
#  d'attente en attente : le temps que prend chaque geste ne décale pas les
#  suivants.
#
#  POURQUOI SUR LE NŒUD DE CONTRÔLE, ET PAS SUR LE MASTER
#
#  Parce que le compte rendu naît là où il doit vivre. Le master est jetable —
#  destroy.sh l'efface, et avec lui tout ce qu'il portait. Écrire ici supprime
#  l'étape « rapatrier à la fin », donc supprime l'oubli possible.
#
#  Le réseau n'est pas un risque : le pilote dort, puis lance une commande
#  courte. Si elle échoue, l'échec est écrit dans le compte rendu au lieu d'être
#  passé sous silence. Et chaque injection expire d'elle-même sur le master :
#  un pilote qui meurt ne laisse pas la panne derrière lui.
#
#  Ctrl-C ne jette rien : l'injection en cours est retirée, la collecte est
#  close proprement, le compte rendu est écrit avec ce qui a eu lieu.
#
#  À LANCER SOUS TMUX. La campagne dure des heures ; une session SSH qui tombe
#  emporterait le pilote avec elle.
#
#  Usage :
#      tmux new -s campagne
#      ./campagne.sh <nom> --profil "10:15,25:15,10:15,40:15"
#      ./campagne.sh <nom> --profil "25:30" --panne lenteur --a 5 --duree 20
#
#  Le profil se lit « voyageurs:minutes », séparés par des virgules.
#
#  Options :
#      --profil <p>       obligatoire — les paliers à appliquer
#      --panne <cause>    charge, lenteur, hote ou blocage ; sans : campagne saine
#      --a <min[,min…]>   minute(s) où chaque injection commence, comptées
#                         depuis le premier palier
#      --duree <min>      durée de chaque injection
#      --intensite <n>    voyageurs (charge), millisecondes (lenteur), cœurs (hote)
#      --cible <x>        nœud (hote) ou pod (blocage) ; sinon choisi par panne.sh
#      --sans-collecte    ne pilote pas la collecte (elle est déjà en route)
#      --sans-purge       ne remet pas les tables de commandes à zéro au départ
#      --marge <min>      marge écartée de chaque côté (défaut : celle de collecte.sh)
#
#  Variables reconnues :
#      CAMPAGNE_SSH      (défaut: master)
#      CAMPAGNE_DISTANT  (défaut: /home/ubuntu/autodeploy)
# ==============================================================================
set -uo pipefail

# Tout le script tient dans une fonction, lue en entier avant d'exécuter quoi
# que ce soit : un « git pull » pendant une campagne de trois heures ne peut
# pas changer le pilote sous ses pieds.
main() {

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
TEMOINS=""

# ------------------------------------------------------------------------------
distant() { ssh "$CIBLE" "JOURNAL_OFF=1 bash '$DISTANT/apps/$1' ${*:2}" 2>&1; }

usage() {
    sed -n '/^#  Usage :/,/^# ===/p' "$0" | sed 's/^#\s\?//' | head -n -1
    exit 2
}

# ------------------------------------------------------------------------------
NOM=""; PROFIL=""; PANNE=""; DEBUTS_BRUTS=""; DUREE=""; INTENSITE=""; CIBLE_PANNE=""
COLLECTE=1; PURGE=1; MARGE=""
[ $# -gt 0 ] || usage
NOM="$1"; shift
case "$NOM" in -*|'') usage ;; *[!A-Za-z0-9._-]*) fail "Nom invalide : « $NOM »" ;; esac

while [ $# -gt 0 ]; do
    case "$1" in
        --profil)        PROFIL="${2:-}"; shift 2 ;;
        --panne)         PANNE="${2:-}"; shift 2 ;;
        --a)             DEBUTS_BRUTS="${2:-}"; shift 2 ;;
        --duree)         DUREE="${2:-}"; shift 2 ;;
        --intensite)     INTENSITE="${2:-}"; shift 2 ;;
        --cible)         CIBLE_PANNE="${2:-}"; shift 2 ;;
        --marge)         MARGE="${2:-}"; shift 2 ;;
        --sans-collecte) COLLECTE=0; shift ;;
        --sans-purge)    PURGE=0; shift ;;
        -h|--help)       usage ;;
        *) fail "Option inconnue : $1" ;;
    esac
done

[ -n "$PROFIL" ] || fail "Le profil est obligatoire : --profil \"10:15,25:15\""

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

# ------------------------------------------------------ lecture de la panne
# Une injection tient entre deux bornes : elle commence après le premier
# palier, elle finit au moins une minute avant la fin (le retour se mesure
# aussi), et deux injections ne se chevauchent pas.
TYPE="saine"; DEBUTS=()
if [ -n "$PANNE" ]; then
    TYPE="panne"
    case "$PANNE" in charge|lenteur|hote|blocage) ;;
        *) fail "--panne accepte charge, lenteur, hote ou blocage — pas « $PANNE »" ;; esac
    [ -n "$DEBUTS_BRUTS" ] || fail "--panne exige --a <minute> : quand l'injection commence"
    [ -n "$DUREE" ]        || fail "--panne exige --duree <minutes>"
    case "$DUREE" in ''|*[!0-9]*) fail "--duree : un nombre de minutes" ;; esac
    [ "$DUREE" -gt 0 ] || fail "--duree : au moins une minute"
    case "$INTENSITE" in *[!0-9]*) fail "--intensite : un nombre entier" ;; esac
    IFS=',' read -ra MORCEAUX <<< "$DEBUTS_BRUTS"
    for m in "${MORCEAUX[@]}"; do
        m="${m// /}"; [ -n "$m" ] || continue
        case "$m" in ''|*[!0-9]*) fail "--a « $m » : une minute, par exemple 5" ;; esac
        DEBUTS+=("$m")
    done
    [ "${#DEBUTS[@]}" -gt 0 ] || fail "--a : aucune minute lisible"
    mapfile -t DEBUTS < <(printf '%s\n' "${DEBUTS[@]}" | sort -n)
    precedent=-1
    for a in "${DEBUTS[@]}"; do
        [ "$a" -ge 1 ] || fail "--a $a : une injection commence au plus tôt à la minute 1"
        [ $((a + DUREE)) -lt "$TOTAL" ] \
            || fail "--a $a + --duree $DUREE dépasse la campagne ($TOTAL min) : il faut au moins une minute de retour après"
        [ "$precedent" -lt 0 ] || [ "$a" -ge $((precedent + DUREE + 1)) ] \
            || fail "--a $precedent et $a se chevauchent : au moins $((DUREE + 1)) minutes entre deux débuts"
        precedent=$a
    done
else
    [ -z "$DEBUTS_BRUTS$DUREE$INTENSITE$CIBLE_PANNE" ] \
        || fail "--a, --duree, --intensite et --cible n'ont de sens qu'avec --panne <cause>"
fi

DOSSIER="$RACINE/campagnes/$NOM"
[ -d "$DOSSIER" ] && warn "« $NOM » existe déjà — son contenu sera remplacé."
mkdir -p "$DOSSIER/journaux" || fail "Impossible de créer $DOSSIER"

# ------------------------------------------------------------ les événements
# Tout ce qui doit arriver, en secondes depuis le premier palier. Le second
# nombre ordonne ce qui tombe à la même seconde : palier, témoin, injection,
# retrait, témoin d'après.
EVENEMENTS=(); depuis=0
for p in "${PALIERS[@]}"; do
    EVENEMENTS+=("$((depuis * 60)) 0 palier $p")
    depuis=$((depuis + ${p##*:}))
done
# Deux minutes après le premier palier, les parcours sont contrôlés : une
# campagne dont un parcours échoue ou ne tourne pas ne vaut rien, et mieux
# vaut le savoir à la minute 2 qu'à la minute 60.
[ "$TOTAL" -ge 3 ] && EVENEMENTS+=("120 2 controle -")
for a in "${DEBUTS[@]}"; do
    EVENEMENTS+=("$((a * 60)) 1 temoin avant")
    EVENEMENTS+=("$((a * 60)) 2 injecter -")
    EVENEMENTS+=("$((a * 60 + DUREE * 30)) 1 temoin pendant")
    EVENEMENTS+=("$(((a + DUREE) * 60)) 3 retirer -")
    EVENEMENTS+=("$(((a + DUREE) * 60 + 60)) 4 temoin apres")
done
mapfile -t EVENEMENTS < <(printf '%s\n' "${EVENEMENTS[@]}" | sort -n -k1,1 -k2,2)

# ------------------------------------------------------------ le plan annoncé
echo
say "Campagne « $NOM »  ·  type : $TYPE${PANNE:+  ·  cause : $PANNE}"
say "Master : $CIBLE"
echo
say "Déroulé prévu (minutes depuis le premier palier) :"
for ev in "${EVENEMENTS[@]}"; do
    read -r sec _ genre arg <<< "$ev"
    case "$genre" in
        palier)   printf "      %4d   %s voyageurs\n" $((sec / 60)) "${arg%%:*}" ;;
        injecter) printf "      %4d   injection « %s »%s%s, pendant %s min\n" $((sec / 60)) "$PANNE" \
                      "${INTENSITE:+ · intensité $INTENSITE}" "${CIBLE_PANNE:+ · cible $CIBLE_PANNE}" "$DUREE" ;;
        retirer)  printf "      %4d   retrait\n" $((sec / 60)) ;;
        controle) printf "      %4d   contrôle des parcours\n" $((sec / 60)) ;;
    esac
done
printf "      %4d   fin\n" "$TOTAL"
say "Durée totale : $TOTAL minutes ($(printf '%dh%02d' $((TOTAL/60)) $((TOTAL%60))))"
[ "$COLLECTE" = "1" ] && say "La collecte sera démarrée puis arrêtée par ce script." \
                      || say "La collecte n'est PAS pilotée (--sans-collecte)."
echo

# ------------------------------------------------------------- vérifications
# Avant le compte à rebours : ce qui peut être refusé doit l'être avant que
# l'utilisateur s'en aille.
ssh -o BatchMode=yes "$CIBLE" true 2>/dev/null \
    || fail "Master injoignable via « ssh $CIBLE ». Le cluster est-il debout ?"

# Une référence saine enregistrée avec une panne encore en place serait fausse
# sans que rien ne le montre.
if ! sortie=$(distant panne.sh etat); then
    printf '%s\n' "$sortie" | sed 's/^/      /' >&2
    fail "Une panne est encore en place, ou la copie du master n'est pas à jour.
             Retirer :  ssh $CIBLE 'bash $DISTANT/apps/panne.sh retirer'
             À jour :   ./deploy.sh --push-scripts"
fi
if [ -n "$PANNE" ]; then
    if sortie=$(distant panne.sh verifier "$PANNE"); then
        printf '%s\n' "$sortie" | sed 's/^/      /'
    else
        printf '%s\n' "$sortie" | sed 's/^/      /' >&2
        fail "Les préalables de « $PANNE » ne sont pas réunis."
    fi
fi

say "Départ dans 10 secondes — Ctrl-C pour annuler."
sleep 10
echo

# -------------------------------------------------------------- le compte rendu
# Écrit à la fin, et aussi sur interruption : le fichier décrit toujours ce qui
# a réellement eu lieu.
rates=0; echoues=0; injectees=0; non_injectees=0; INJECTION_ACTIVE=0; INTERROMPUE=0
etat_avant=""; etat_apres=""; fenetre=""; registre=""; registre_pannes=""; reglage_consommateur=""; etat_donnees=""
plage_date=""; plage_de=""; plage_a=""

ecrire_compte_rendu() {
    local sortie_yaml="$DOSSIER/campagne.yaml"
    {
        echo "# Conditions expérimentales — écrit par campagne.sh, ne pas éditer à la main."
        echo "# Les réglages d'analyse sont ailleurs : graphe_en/runs/<date>/graph/manifest.json"
        echo
        echo "campagne: $NOM"
        echo "type: $TYPE"
        echo "pilote_le: $(maintenant)"
        [ "$INTERROMPUE" = "1" ] && echo "interrompue: oui"
        echo
        echo "profil_demande: \"$PROFIL\""
        echo "duree_prevue_min: $TOTAL"
        echo "paliers_confirmes: $rates"
        echo "paliers_non_confirmes: $echoues"
        if [ -n "$PANNE" ]; then
            echo
            echo "panne:"
            echo "  cause: $PANNE"
            echo "  intensite: ${INTENSITE:-defaut}"
            echo "  cible: ${CIBLE_PANNE:-automatique}"
            echo "  debuts_min: [$(IFS=,; echo "${DEBUTS[*]}")]"
            echo "  duree_min: $DUREE"
            echo "  injections_confirmees: $injectees"
            echo "  injections_non_confirmees: $non_injectees"
        fi
        echo
        echo "# Réglage du consommateur (consommateur.sh etat), identique pour toutes les"
        echo "# campagnes comparées entre elles."
        echo "reglage_consommateur: |"
        printf '%s\n' "${reglage_consommateur:-(non lu)}" | sed 's/^/  /'
        echo
        echo "# Données de l'application au départ (donnees.sh etat), après remise à zéro"
        echo "# sauf --sans-purge : le comportement de train-ticket en dépend."
        echo "donnees_au_depart: |"
        printf '%s\n' "${etat_donnees:-(non lu)}" | sed 's/^/  /'
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
        if [ -n "$PANNE" ]; then
            echo
            echo "# Registre écrit par panne.sh : qui a été touché, quand, avec quoi."
            echo "pannes_mesurees: |"
            if [ -n "$registre_pannes" ]; then printf '%s\n' "$registre_pannes" | sed 's/^/  /'
            else echo "  (registre absent sur le master)"; fi
            echo
            echo "# Témoins relevés par panne.sh, verbatim :"
            printf '%s' "$TEMOINS" | sed 's/^/#   /'
        fi
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
}

# La charge ne reste pas au dernier palier : un étalonnage qui finit à 320
# voyageurs laisserait l'application saturée jusqu'à la campagne suivante. On
# revient au premier palier, celui qui décrit le régime de base.
retour_au_premier_palier() {
    local base="${PALIERS[0]%%:*}" dernier="${PALIERS[-1]%%:*}"
    [ "$base" != "$dernier" ] || return 0
    say "Retour à $base voyageurs (premier palier)…"
    if sortie=$(distant loadgen.sh scale "$base"); then
        noter_action "action: retour_charge_de_base, voyageurs: $base, resultat: confirme"
    else
        printf '%s\n' "$sortie" | sed 's/^/      /' >&2
        warn "Retour à $base voyageurs non confirmé — la charge reste celle du dernier palier."
        noter_action "action: retour_charge_de_base, voyageurs: $base, resultat: NON_CONFIRME"
    fi
}

# La fenêtre AVANT l'arrêt : collecte.sh fenetre lit la date de démarrage de la
# passerelle ; passerelle arrêtée, il n'a plus rien à lire.
cloturer() {
    echo
    say "Calcul de la fenêtre exploitable…"
    fenetre=$(distant collecte.sh fenetre ${MARGE:+--marge "$MARGE"})
    if [ "$COLLECTE" = "1" ]; then
        say "Arrêt de la collecte…"
        distant collecte.sh arreter >/dev/null && ok "collecte arrêtée" \
            || warn "L'arrêt de la collecte a échoué — vérifie avec collecte.sh etat."
        noter_action "action: collecte_arretee"
    fi
    etat_apres=$(distant collecte.sh etat)

    plage_date=$(printf '%s\n' "$fenetre" | grep -oP '^\s+date:\s+\K[0-9-]+'   | head -1)
    plage_de=$(printf '%s\n' "$fenetre"   | grep -oP '^\s+from:\s+"\K[0-9:]+' | head -1)
    plage_a=$(printf '%s\n' "$fenetre"    | grep -oP '^\s+to:\s+"\K[0-9:]+'   | head -1)

    say "Rapatriement des registres et des journaux…"
    registre=$(ssh "$CIBLE" "cat '$DISTANT/journaux/paliers.tsv'" 2>/dev/null)
    registre_pannes=$(ssh "$CIBLE" "cat '$DISTANT/journaux/pannes.tsv'" 2>/dev/null)
    scp -q -r "$CIBLE:$DISTANT/journaux/." "$DOSSIER/journaux/" 2>/dev/null \
        && ok "journaux copiés" || warn "copie des journaux impossible"

    ecrire_compte_rendu
    echo
    if [ "$INTERROMPUE" = "1" ]; then warn "campagne « $NOM » INTERROMPUE — compte rendu écrit quand même"
    else ok "campagne « $NOM » terminée"; fi
    say "  compte rendu : campagnes/$NOM/campagne.yaml"
    say "  paliers      : $rates confirmé(s), $echoues non confirmé(s)"
    [ -n "$PANNE" ] && say "  injections   : $injectees confirmée(s), $non_injectees non confirmée(s)"
    [ "$echoues" -gt 0 ] && warn "  des paliers n'ont pas abouti — voir « deroule » dans le compte rendu"
    [ "$non_injectees" -gt 0 ] && warn "  des injections n'ont pas abouti — voir « pannes_mesurees »"
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
        warn "Repli : la plage se calcule depuis « deroule » du compte rendu,"
        warn "  collecte_demarree + 2 min  →  collecte_arretee − 2 min."
    fi
    say "Ce dossier est à committer : c'est la provenance de tes données."
}

interrompu() {
    trap - INT TERM
    echo; warn "Interrompu."
    INTERROMPUE=1
    noter_action "action: interrompu"
    if [ "$INJECTION_ACTIVE" = "1" ]; then
        say "Retrait de l'injection en cours…"
        distant panne.sh retirer | sed 's/^/      /'
        noter_action "action: retrait, motif: interruption"
        INJECTION_ACTIVE=0
    fi
    retour_au_premier_palier
    cloturer
    exit 130
}
trap interrompu INT TERM

# ------------------------------------------------------------------ préparation
etat_avant=$(distant collecte.sh etat)
noter_action "action: etat_initial"
# Le réglage du consommateur fait partie des conditions expérimentales : il est
# relu et recopié dans le compte rendu, pour qu'aucune campagne ne soit
# comparée à une autre sans qu'on sache si elles partagent le même.
reglage_consommateur=$(distant consommateur.sh etat) || reglage_consommateur="(non lu : $reglage_consommateur)"

# Les tables de commandes aussi : deux campagnes ne se comparent que si elles
# partent des mêmes données. On les vide, AVANT la collecte, pour que le
# redémarrage du service des commandes reste hors de la fenêtre mesurée.
if [ "$PURGE" = "1" ]; then
    say "Remise à zéro des données de l'application…"
    if sortie=$(distant donnees.sh purger); then   # sans redémarrage : voir donnees.sh
        printf '%s\n' "$sortie" | sed 's/^/      /'
        noter_action "action: donnees_remises_a_zero"
    else
        printf '%s\n' "$sortie" | sed 's/^/      /' >&2
        fail "La remise à zéro des données a échoué (--sans-purge pour s'en passer, en connaissance de cause)."
    fi
fi
etat_donnees=$(distant donnees.sh etat) || etat_donnees="(non lu : $etat_donnees)"

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

# Les compteurs de Locust repartent de zéro : « loadgen.sh bilan » décrira
# cette campagne, pas ce qui a tourné avant.
if sortie=$(distant loadgen.sh reset); then
    noter_action "action: compteurs_locust_remis_a_zero"
else
    printf '%s\n' "$sortie" | sed 's/^/      /' >&2
    warn "Compteurs de Locust non remis à zéro — le bilan cumulera avec ce qui précède."
fi

# ------------------------------------------------------------------ les gestes
appliquer_palier() {
    local v="${1%%:*}" d="${1##*:}"
    say "$v voyageurs pendant $d minutes"
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
}

injecter() {
    say "Injection « $PANNE » pendant $DUREE minutes"
    INJECTION_ACTIVE=1
    if sortie=$(distant panne.sh injecter "$PANNE" --duree "$DUREE" \
                    ${INTENSITE:+--intensite "$INTENSITE"} ${CIBLE_PANNE:+--cible "$CIBLE_PANNE"}); then
        printf '%s\n' "$sortie" | sed 's/^/      /'
        noter_action "action: injection, cause: $PANNE, resultat: confirme"
        injectees=$((injectees + 1))
    else
        printf '%s\n' "$sortie" | sed 's/^/      /' >&2
        warn "Injection non confirmée — la campagne continue, l'échec est enregistré."
        noter_action "action: injection, cause: $PANNE, resultat: NON_CONFIRME"
        non_injectees=$((non_injectees + 1))
    fi
}

retirer() {
    say "Retrait de « $PANNE »"
    if sortie=$(distant panne.sh retirer); then
        printf '%s\n' "$sortie" | sed 's/^/      /'
        noter_action "action: retrait, cause: $PANNE, resultat: ok"
    else
        printf '%s\n' "$sortie" | sed 's/^/      /' >&2
        warn "Retrait en échec — à vérifier :  ssh $CIBLE 'bash $DISTANT/apps/panne.sh etat'"
        noter_action "action: retrait, cause: $PANNE, resultat: ECHEC"
    fi
    INJECTION_ACTIVE=0
}

temoin() {
    local moment="$1"
    sortie=$(distant panne.sh temoin)
    TEMOINS="${TEMOINS}
--- témoin « $moment » à $(maintenant)
$sortie
"
    noter_action "action: temoin, moment: $moment"
    say "témoin « $moment » relevé"
}

controle_des_parcours() {
    say "Contrôle des parcours (loadgen.sh bilan)…"
    if sortie=$(distant loadgen.sh bilan); then
        printf '%s\n' "$sortie" | grep -E "^\s+[0-9]{2} " | sed 's/^/      /'
        noter_action "action: controle_parcours, resultat: ok"
        return 0
    fi
    printf '%s\n' "$sortie" | sed 's/^/      /' >&2
    noter_action "action: controle_parcours, resultat: EN_DEFAUT"
    warn "Un parcours échoue ou ne tourne pas : la campagne ne vaudrait rien. Arrêt."
    interrompu
}

attendre_jusqua() {   # <epoch> — dort jusqu'à cet instant, sans dérive
    local n; n=$(date +%s)
    [ "$1" -gt "$n" ] || return 0
    [ $(($1 - n)) -lt 60 ] \
        || say "      … $(( ($1 - n + 30) / 60 )) min d'attente (jusqu'à $(date -u -d "@$1" '+%H:%M') UTC)"
    sleep $(($1 - n))
}

# ------------------------------------------------------------------ le déroulé
echo
T0=$(date +%s)
for ev in "${EVENEMENTS[@]}"; do
    read -r sec _ genre arg <<< "$ev"
    attendre_jusqua $((T0 + sec))
    case "$genre" in
        palier)   appliquer_palier "$arg" ;;
        injecter) injecter ;;
        retirer)  retirer ;;
        temoin)   temoin "$arg" ;;
        controle) controle_des_parcours ;;
    esac
done
attendre_jusqua $((T0 + TOTAL * 60))

trap - INT TERM
retour_au_premier_palier
cloturer

}

main "$@"
