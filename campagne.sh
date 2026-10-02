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
#      minute   0        5                              25       30
#               |--------|==============================|--------|
#               25 voyageurs panne « consumer-slowdown » retour   fin
#
#      ./campagne.sh consumer-slowdown-01 --profil "25:30" --panne consumer-slowdown --a 5 --duree 20
#
#  Les noms des causes sont anglais (ceux de apps/panne.sh). Les anciens noms
#  français sont encore acceptés pour --panne, traduits dès la lecture (une ligne
#  le dit) ; le compte rendu porte toujours le nom anglais :
#      charge → load-surge, lenteur → consumer-slowdown, blocage → replica-freeze,
#      hote → noisy-neighbor, base → database-slowdown, reseau → network-delay
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
#  courte, bornée par un plafond (variables plus bas). Si elle échoue ou ne
#  répond pas, l'échec est écrit dans le compte rendu au lieu d'être passé sous
#  silence. Et chaque injection expire d'elle-même sur le master :
#  un pilote qui meurt ne laisse pas la panne derrière lui.
#
#  Ctrl-C ne jette rien : l'injection en cours est retirée, la collecte est
#  close proprement, le compte rendu est écrit avec ce qui a eu lieu. De même
#  pour « kill -INT <pid du pilote> » (traité tout de suite, même pendant une
#  longue attente), TERM, HUP (terminal fermé) et PIPE (sortie coupée) ; la
#  suite du nettoyage s'écrit alors dans le journal. « kill -9 » ne se rattrape
#  pas : rien n'est retiré ni écrit, et la ligne FIN manque. Lancé en
#  arrière-plan par un script sans « set -m », le pilote ne peut pas rattraper
#  INT (bash l'ignore dès l'entrée) : il le dit au départ ; envoyer TERM.
#
#  Chaque sortie ajoute UNE ligne à journaux/fins.tsv (ici, sur le nœud de
#  contrôle ; tabulations) :
#      FIN_CAMPAGNE  <nom>  <code>  <instant UTC>  <motif>
#  motif : termine, depart_refuse, interrompu_<INT|TERM|HUP|PIPE>,
#          parcours_en_defaut, reglage_absent, erreur
#  Code de sortie : 0 terminée ; 1 erreur ou départ refusé ; 2 usage (-h,
#  arguments manquants, motif « erreur ») ; 3 close sans la panne, le retard
#  de base (140 ms) manquait juste avant une injection ; 130 interrompue
#  (signal, ou parcours en défaut à la minute 2).
#
#  À LANCER SOUS TMUX. La campagne dure des heures ; une session SSH qui tombe
#  emporterait le pilote avec elle.
#
#  Usage :
#      tmux new -s campagne
#      ./campagne.sh <nom> --profil "10:15,25:15,10:15,40:15"
#      ./campagne.sh <nom> --profil "25:30" --panne consumer-slowdown --a 5 --duree 20
#      ./campagne.sh <nom> --profil "25:135" --panne noisy-neighbor --a 5,50,95 --duree 20 \
#                          --cible workers5,workers2,workers0
#
#  Le profil se lit « voyageurs:minutes », séparés par des virgules.
#
#  Options :
#      --profil <p>       obligatoire — les paliers à appliquer
#      --panne <cause>    load-surge, consumer-slowdown, replica-freeze, noisy-neighbor,
#                         database-slowdown ou network-delay ; sans : campagne saine
#      --a <min[,min…]>   minute(s) où chaque injection commence, comptées
#                         depuis le premier palier
#      --duree <min>      durée de chaque injection
#      --intensite <n>    voyageurs (load-surge), millisecondes (consumer-slowdown,
#                         database-slowdown, network-delay), cœurs (noisy-neighbor)
#      --cible <x[,y…]>   nœud (noisy-neighbor), pod (replica-freeze) ou couple « X:Y »
#                         (network-delay, exigé :
#                         la règle de D.1, recalculée au départ par graphe_en/couples_d.py,
#                         doit donner les mêmes cibles, sinon départ refusé) ; sinon choisi par panne.sh.
#                         Une liste donne une cible par injection, dans l'ordre
#                         des --a (autant de cibles que d'injections) ; une
#                         seule cible vaut pour toutes les injections
#      --sans-collecte    ne pilote pas la collecte (elle est déjà en route)
#      --sans-purge       ne remet pas les tables de commandes à zéro au départ
#      --marge <min>      marge écartée de chaque côté (défaut : celle de collecte.sh)
#
#  Variables reconnues :
#      CAMPAGNE_SSH      (défaut: master)
#      CAMPAGNE_DISTANT  (défaut: /home/ubuntu/autodeploy)
#      CAMPAGNE_NAMESPACE (défaut: train-ticket) l'espace dont le placement est noté
#      FILE_VIDE_MAX     (défaut: 40) minutes d'attente, au départ, pour que la
#                        file laissée par la campagne précédente se vide
#
#  Plafonds, en secondes, de chaque appel au master (au moins le double de sa
#  pire durée normale). Une lecture est bornée aussi sur le master ; un geste
#  ne l'est jamais là-bas. Le plafond d'ici reste un dernier recours : s'il
#  tombe, le geste distant s'arrête à sa prochaine écriture — d'où leur largeur.
#      CAMPAGNE_PLAFOND_LECTURE  (défaut: 120)  états, bilans, vérifications
#      CAMPAGNE_PLAFOND_LONGUE   (défaut: 300)  témoin complet, copie des journaux
#      CAMPAGNE_PLAFOND_GESTE    (défaut: 360)  collecte, purge, reposer, reset
#      CAMPAGNE_PLAFOND_SCALE    (défaut: 4 × (30 + plus grand palier), au moins 600)
#      CAMPAGNE_PLAFOND_INJECTER (défaut: 1200)
#      CAMPAGNE_PLAFOND_RETIRER  (défaut: 2400)  « consumer-slowdown » repose le réglage,
#                                               rollout de 10 min compris
#      (« load-surge » passe par loadgen.sh scale : au moins 4 × (30 + --intensite,
#      ou plus grand palier sans elle), pour l'injection comme pour le retrait)
# ==============================================================================
set -uo pipefail

# Tout le script tient dans une fonction, lue en entier avant d'exécuter quoi
# que ce soit : un « git pull » pendant une campagne de trois heures ne peut
# pas changer le pilote sous ses pieds.
main() {

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CIBLE="${CAMPAGNE_SSH:-master}"
DISTANT="${CAMPAGNE_DISTANT:-/home/ubuntu/autodeploy}"
NS_APP="${CAMPAGNE_NAMESPACE:-train-ticket}"

[ -f "$RACINE/apps/journal.sh" ] && JOURNAL_NOM="campagne" . "$RACINE/apps/journal.sh"

say()  { echo "  [campagne] $*"; }
ok()   { echo "  [campagne] OK  $*"; }
warn() { echo "  [campagne] ATTENTION: $*" >&2; }
fail() { echo "  [campagne] ERREUR: $*" >&2; [ -n "${T0:-}" ] || MOTIF=depart_refuse; exit 1; }
maintenant() { date -u +%Y-%m-%dT%H:%M:%SZ; }
exec 3>&2   # l'écran (ou le journal), même quand un appel a sa sortie capturée ou jetée

# La ligne FIN, écrite à toute sortie, en dernier, directement dans le fichier :
# ni tee ni le terminal n'ont besoin d'être encore là. Une injection restée
# posée (sortie imprévue, hors interruption) est d'abord retirée.
MOTIF=""; NOM_FIN="?"; T0=""; INJECTION_ACTIVE=0; SOUSTRAIT=""
fin_de_campagne() {
    local code=$?
    trap '' PIPE; trap : INT TERM HUP     # plus rien ne coupe la fin
    [ "$INJECTION_ACTIVE" != "1" ] || retrait_en_cours "sortie_imprevue"
    # « termine » et « depart_refuse » sont posés là où ils arrivent : sans motif,
    # c'est une erreur imprévue (bash tué par un signal non rattrapé sort ici avec 0).
    [ -n "$MOTIF" ] || MOTIF=erreur
    mkdir -p "$RACINE/journaux" 2>/dev/null
    printf 'FIN_CAMPAGNE\t%s\t%s\t%s\t%s\n' "$NOM_FIN" "$code" "$(maintenant)" "$MOTIF" >> "$RACINE/journaux/fins.tsv"
}
trap fin_de_campagne EXIT
# Hors du déroulé, rien n'est à défaire : un signal arrête net, la ligne FIN le dit.
arret_simple() { local s; for s in INT TERM HUP PIPE; do trap "MOTIF=interrompu_$s; exit 130" "$s"; done; }
arret_simple
# Lancé en arrière-plan sans « set -m », bash ignore SIGINT dès l'entrée, sans
# pouvoir le rattraper : « kill -INT » ne ferait rien, en silence.
case "$(trap -p INT)" in *MOTIF=*) ;;
    *) warn "SIGINT ignoré dès le lancement (arrière-plan sans « set -m ») : « kill -INT » sera sans effet — envoyer TERM" ;; esac

# Chaque action du déroulé est ajoutée ici au fur et à mesure, jamais à la fin :
# si le pilote est interrompu, ce qui a déjà eu lieu reste écrit.
DEROULE=""
noter_action() { DEROULE="${DEROULE}  - { instant: $(maintenant), $* }
"; }
TEMOINS=""

# ------------------------------------------------------------------------------
# Un lien mort se voit en une minute environ, et ssh ne demande jamais rien.
SSH_OPTIONS=(-o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=4)

# ssh_master <plafond> <libellé> <commande> — un appel au master, borné ici.
# --foreground : timeout reste dans le groupe du pilote, sinon un Ctrl-C dans tmux n'atteindrait plus ssh.
ssh_master() {
    local code=0
    ${SOUSTRAIT:+setsid -w} timeout --foreground -k 30 "$1" ssh "${SSH_OPTIONS[@]}" "$CIBLE" "$3" || code=$?
    case "$code" in 124|137) echo "  [campagne] ATTENTION: « $2 » n'a pas répondu en $1 s" >&3 ;; esac
    return "$code"
}
# Une lecture est bornée aussi sur le master, sans --foreground : tout son
# groupe est tué, un kubectl exec pendu n'y reste pas orphelin. Jamais un geste.
borne() { echo "timeout -k 10 $1"; }

plafond_de() {   # <script> <action> [court] → « secondes lecture|geste »
    case "$1 ${2:-}" in
        "panne.sh injecter")  echo "$PLAFOND_INJECTER geste" ;;
        "panne.sh retirer")   echo "$PLAFOND_RETIRER geste" ;;
        "loadgen.sh scale")   echo "$PLAFOND_SCALE geste" ;;
        "loadgen.sh reset"|"collecte.sh demarrer"|"collecte.sh arreter"|"donnees.sh purger"|"consommateur.sh reposer")
                              echo "$PLAFOND_GESTE geste" ;;
        "panne.sh temoin")    if [ "${3:-}" = court ]; then echo "$PLAFOND_LECTURE lecture"
                              else echo "$PLAFOND_LONGUE lecture"; fi ;;
        "panne.sh etat"|"panne.sh leader"|"panne.sh verifier"|"panne.sh libres"|"loadgen.sh bilan"|\
        "collecte.sh etat"|"collecte.sh fenetre"|"consommateur.sh etat"|"consommateur.sh verifier"|"donnees.sh etat")
                              echo "$PLAFOND_LECTURE lecture" ;;
        *)                    echo "$PLAFOND_RETIRER geste" ;;   # inconnu : jamais coupé sur le master
    esac
}

distant() {
    local plafond sorte b=""
    read -r plafond sorte <<< "$(plafond_de "$@")"
    [ "$sorte" = geste ] || b="$(borne "$plafond") "
    ssh_master "$plafond" "$1 ${2:-}" "JOURNAL_OFF=1 ${b}bash '$DISTANT/apps/$1' ${*:2}" 2>&1
}

usage() {
    sed -n '/^#  Usage :/,/^# ===/p' "$0" | sed 's/^#\s\?//' | head -n -1
    exit 2
}

# Les noms des causes, ceux de apps/panne.sh.
CAUSES="load-surge consumer-slowdown replica-freeze noisy-neighbor database-slowdown network-delay"
LISTE_CAUSES="load-surge, consumer-slowdown, replica-freeze, noisy-neighbor, database-slowdown ou network-delay"

# COMPATIBILITÉ — à retirer après la collecte : les anciens noms français de
# --panne, traduits dès la lecture des arguments ; ensuite seul le nom anglais
# circule (déroulé, compte rendu, appels au master).
alias_de_cause() {   # <ancien nom> → le nom anglais ; 1 si inconnu
    case "$1" in
        charge)  echo load-surge ;;
        lenteur) echo consumer-slowdown ;;
        blocage) echo replica-freeze ;;
        hote)    echo noisy-neighbor ;;
        base)    echo database-slowdown ;;
        reseau)  echo network-delay ;;
        *) return 1 ;;
    esac
}

# ------------------------------------------------------------------------------
NOM=""; PROFIL=""; PANNE=""; DEBUTS_BRUTS=""; DUREE=""; INTENSITE=""; CIBLE_PANNE=""; CIBLES=()
COLLECTE=1; PURGE=1; MARGE=""
[ $# -gt 0 ] || usage
NOM="$1"; shift
case "$NOM" in -*|'') usage ;; *[!A-Za-z0-9._-]*) fail "Nom invalide : « $NOM »" ;; esac
NOM_FIN="$NOM"

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

# Le nom de la cause, traduit tout de suite s'il est ancien (compat).
if [ -n "$PANNE" ]; then
    case " $CAUSES " in
        *" $PANNE "*) ;;
        *) if anglais=$(alias_de_cause "$PANNE"); then
               say "$PANNE → $anglais"
               PANNE="$anglais"
           fi ;;
    esac
fi

[ -n "$PROFIL" ] || fail "Le profil est obligatoire : --profil \"10:15,25:15\""
case "${MARGE:-2}" in ''|*[!0-9]*) fail "--marge : un nombre de minutes" ;; esac

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
    case " $CAUSES " in *" $PANNE "*) ;;
        *) fail "--panne accepte $LISTE_CAUSES — pas « $PANNE »" ;; esac
    [ -n "$DEBUTS_BRUTS" ] || fail "--panne exige --a <minute> : quand l'injection commence"
    [ "$PANNE" != "network-delay" ] || [ -n "$CIBLE_PANNE" ] || fail "--panne network-delay exige --cible X:Y (graphe_en/couples_d.py)"
    [ "$PANNE" != "network-delay" ] || [ -n "$INTENSITE" ] || fail "--panne network-delay exige --intensite <ms>"
    [ -n "$DUREE" ]        || fail "--panne exige --duree <minutes>"
    case "$DUREE" in ''|*[!0-9]*) fail "--duree : un nombre de minutes" ;; esac
    [ "$DUREE" -gt 0 ] || fail "--duree : au moins une minute"
    case "$INTENSITE" in *[!0-9]*) fail "--intensite : un nombre entier" ;; esac
    [ "$PANNE" != "network-delay" ] || [ "$INTENSITE" -ge 1 ] || fail "--panne network-delay : --intensite d'au moins 1 ms"
    IFS=',' read -ra MORCEAUX <<< "$DEBUTS_BRUTS"
    for m in "${MORCEAUX[@]}"; do
        m="${m// /}"; [ -n "$m" ] || continue
        case "$m" in ''|*[!0-9]*) fail "--a « $m » : une minute, par exemple 5" ;; esac
        DEBUTS+=("$m")
    done
    [ "${#DEBUTS[@]}" -gt 0 ] || fail "--a : aucune minute lisible"

    # Les cibles, une par injection, dans l'ordre où les --a sont écrits. Elles
    # partent au master dans une ligne de commande : seuls les caractères d'un
    # nom Kubernetes sont admis.
    if [ -n "$CIBLE_PANNE" ]; then
        case "$PANNE" in noisy-neighbor|replica-freeze|network-delay) ;;
            *) fail "--cible est sans objet pour « $PANNE » : seules noisy-neighbor (un nœud), replica-freeze (un pod) et network-delay (X:Y) visent un composant" ;; esac
        # La chaîne entière d'abord : un retour à la ligne (liste collée depuis
        # kubectl) couperait la lecture après le premier nom, sans erreur.
        [[ "${CIBLE_PANNE// /}" =~ ^[a-z0-9.,:-]+$ ]] \
            || fail "--cible « $CIBLE_PANNE » : des noms séparés par des virgules (minuscules, chiffres, « - » et « . »)"
        case "${CIBLE_PANNE// /}" in ,*|*,|*,,*) fail "--cible « $CIBLE_PANNE » : une cible vide dans la liste" ;; esac
        IFS=',' read -ra MORCEAUX <<< "${CIBLE_PANNE// /}"
        for c in "${MORCEAUX[@]}"; do
            if [ "$PANNE" = "network-delay" ]; then
                [[ "$c" =~ ^[a-z0-9.-]+:[a-z0-9.-]+$ ]] \
                    || fail "--cible « $c » : pour network-delay, « X:Y » (deux noms de nœud)"
            else
                [[ "$c" =~ ^[a-z0-9]([-a-z0-9.]*[a-z0-9])?$ ]] \
                    || fail "--cible « $c » : pas un nom de nœud ou de pod (minuscules, chiffres, « - » et « . »)"
            fi
            CIBLES+=("$c")
        done
        if [ "${#CIBLES[@]}" -eq 1 ]; then
            for ((i = 1; i < ${#DEBUTS[@]}; i++)); do CIBLES+=("${CIBLES[0]}"); done
        elif [ "${#CIBLES[@]}" -ne "${#DEBUTS[@]}" ]; then
            fail "--cible donne ${#CIBLES[@]} cibles pour ${#DEBUTS[@]} injections : une seule, ou une par injection"
        fi
    fi

    # Les débuts sont remis dans l'ordre du temps, chacun avec SA cible :
    # « --a 95,5 --cible x,y » vise y à la minute 5 et x à la minute 95.
    if [ "${#CIBLES[@]}" -gt 0 ]; then
        mapfile -t PAIRES < <(for i in "${!DEBUTS[@]}"; do echo "${DEBUTS[$i]} ${CIBLES[$i]}"; done | sort -n -k1,1)
        DEBUTS=(); CIBLES=()
        for p in "${PAIRES[@]}"; do DEBUTS+=("${p%% *}"); CIBLES+=("${p#* }"); done
    else
        mapfile -t DEBUTS < <(printf '%s\n' "${DEBUTS[@]}" | sort -n)
    fi
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

# Les plafonds des appels au master (voir l'en-tête). Celui de « scale » suit le
# plus grand palier : Locust ajoute ou retire un voyageur par seconde. « load-surge »
# passe aussi par scale, à l'injection comme au retrait.
v_max=$(printf '%s\n' "${PALIERS[@]%%:*}" | sort -n | tail -1)
c=$(( 4 * (30 + 10#$v_max) )); PLAFOND_SCALE="${CAMPAGNE_PLAFOND_SCALE:-$(( c > 600 ? c : 600 ))}"
[ "$PANNE" != load-surge ] || c=$(( 4 * (30 + 10#${INTENSITE:-$v_max}) ))
PLAFOND_INJECTER="${CAMPAGNE_PLAFOND_INJECTER:-$(( c > 1200 ? c : 1200 ))}"
PLAFOND_RETIRER="${CAMPAGNE_PLAFOND_RETIRER:-$(( c > 2400 ? c : 2400 ))}"
PLAFOND_LECTURE="${CAMPAGNE_PLAFOND_LECTURE:-120}"
PLAFOND_LONGUE="${CAMPAGNE_PLAFOND_LONGUE:-300}"
PLAFOND_GESTE="${CAMPAGNE_PLAFOND_GESTE:-360}"
for p in LECTURE LONGUE GESTE SCALE INJECTER RETIRER; do
    v="PLAFOND_$p"
    [[ "${!v}" =~ ^[1-9][0-9]*$ ]] || fail "CAMPAGNE_PLAFOND_$p : un nombre de secondes, pas « ${!v} »"
done

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
# Puis toutes les dix minutes, une veille : le même bilan, noté dans le
# déroulé mais sans arrêt. Une campagne de deux heures tourne sans personne
# devant ; si l'application se casse à la minute 70, il faut pouvoir le lire.
for ((m = 10; m < TOTAL; m += 10)); do EVENEMENTS+=("$((m * 60)) 5 veille -"); done
for i in "${!DEBUTS[@]}"; do
    a=${DEBUTS[$i]}
    EVENEMENTS+=("$((a * 60)) 1 temoin avant")
    EVENEMENTS+=("$((a * 60)) 2 injecter $i")
    EVENEMENTS+=("$((a * 60 + DUREE * 30)) 1 temoin pendant")
    EVENEMENTS+=("$(((a + DUREE) * 60)) 3 retirer -")
    EVENEMENTS+=("$(((a + DUREE) * 60 + 60)) 4 temoin apres")
    # Pendant l'injection, une veille toutes les cinq minutes (en plus de celles
    # des dizaines) : le critère d'effondrement de C se lit sur deux relevés de
    # suite PENDANT la panne.
    for ((m = 5; m < DUREE; m += 5)); do
        [ $(((a + m) % 10)) -eq 0 ] || EVENEMENTS+=("$(((a + m) * 60)) 5 veille -")
    done
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
                      "${INTENSITE:+ · intensité $INTENSITE}" "${CIBLES[$arg]:+ · cible ${CIBLES[$arg]}}" "$DUREE" ;;
        retirer)  printf "      %4d   retrait\n" $((sec / 60)) ;;
        controle) printf "      %4d   contrôle des parcours\n" $((sec / 60)) ;;
        veille)   [ "$sec" -eq 600 ] && printf "      %4d   veille des parcours, puis toutes les 10 min\n" $((sec / 60)) ;;
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
ssh_master "$PLAFOND_LECTURE" "ssh $CIBLE true" true 2>/dev/null \
    || fail "Master injoignable via « ssh $CIBLE ». Le cluster est-il debout ?"

# Une référence saine enregistrée avec une panne encore en place serait fausse
# sans que rien ne le montre.
if ! sortie=$(distant panne.sh etat); then
    printf '%s\n' "$sortie" | sed 's/^/      /' >&2
    fail "Une panne est encore en place, ou la copie du master n'est pas à jour.
             Retirer :  ssh $CIBLE 'bash $DISTANT/apps/panne.sh retirer'
             À jour :   ./deploy.sh --push-scripts"
fi
# Le graphe figé envoie les flèches queries vers tsdb-mysql-0, le leader lors du
# gel (graphe_fige.json, « bases ») ; gel.py ne verrait pas un changement de
# leader. Une campagne dont la base a changé de leader aurait des flèches fausses.
if leader_avant=$(distant panne.sh leader); then
    ok "leader de la base : $leader_avant"
else
    fail "tsdb-mysql-0 n'est pas le leader de la base, ou la copie du master n'est pas à jour :
             $leader_avant
             Le graphe figé suppose tsdb-mysql-0 (graphe_fige.json) : départ refusé.
             À jour :   ./deploy.sh --push-scripts"
fi

if [ -n "$PANNE" ]; then
    # Chaque cible est vérifiée maintenant : une faute de frappe découverte à
    # la troisième injection coûterait la campagne.
    options_cibles=""
    [ "${#CIBLES[@]}" -eq 0 ] \
        || options_cibles=$(printf '%s\n' "${CIBLES[@]}" | sort -u | sed 's/^/--cible /' | paste -sd' ' -)
    if sortie=$(distant panne.sh verifier "$PANNE" $options_cibles); then
        printf '%s\n' "$sortie" | sed 's/^/      /'
    else
        printf '%s\n' "$sortie" | sed 's/^/      /' >&2
        fail "Les préalables de « $PANNE » ne sont pas réunis."
    fi
    # Une copie ancienne de panne.sh ignorerait les cibles sans rien dire.
    [ "${#CIBLES[@]}" -eq 0 ] || printf '%s\n' "$sortie" | grep -q "cibles vérifiées" \
        || fail "Le master n'a pas vérifié les cibles : sa copie de panne.sh n'est pas à jour.
             À jour :   ./deploy.sh --push-scripts"
fi

# Les parcours doivent déjà passer AVANT le départ : un service laissé
# cassé par la campagne précédente (mesuré : le service des commandes à court
# de mémoire, recherche à 100 % d'échecs) ferait purger, collecter, puis
# abandonner à la minute 2. Le bilan juge les dix dernières secondes.
if ! sortie=$(distant loadgen.sh bilan); then
    printf '%s\n' "$sortie" | grep -E "^\s+[0-9]{2} |motif|défaut" | sed 's/^/      /' >&2
    fail "Un parcours échoue avant même le départ.
             Remède habituel :  ssh $CIBLE 'bash $DISTANT/apps/donnees.sh redemarrer'  (puis 2 min)"
fi

say "Départ dans 10 secondes — Ctrl-C pour annuler."
sleep 10
echo

# -------------------------------------------------------------- le compte rendu
# Écrit à la fin, et aussi sur interruption : le fichier décrit toujours ce qui
# a réellement eu lieu.
rates=0; echoues=0; injectees=0; non_injectees=0; INJECTION_ACTIVE=0; INTERROMPUE=0
MARGE_S=$(( ${MARGE:-2} * 60 )); T_COLLECTE=""; T0=""
T_PILOTE=$(date +%s)          # tout journal du master écrit après cet instant est à cette campagne
etat_avant=""; etat_apres=""; fenetre=""; registre=""; registre_pannes=""; reglage_consommateur=""; etat_donnees=""
leader_apres=""; leader_depart=""; placement_depart=""; placement_fin=""; reglage_fin=""; couples_lus=""
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
            if [ "${#CIBLES[@]}" -gt 0 ]; then echo "  cible: [$(IFS=,; echo "${CIBLES[*]}")]"
            else echo "  cible: automatique"; fi
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
        echo "# Le même réglage relu à la fin : une panne ne doit pas l'avoir changé."
        echo "reglage_consommateur_a_la_fin: |"
        printf '%s\n' "${reglage_fin:-(non lu)}" | sed 's/^/  /'
        echo
        echo "# Données de l'application au départ (donnees.sh etat), après remise à zéro"
        echo "# sauf --sans-purge : le comportement de train-ticket en dépend."
        echo "donnees_au_depart: |"
        printf '%s\n' "${etat_donnees:-(non lu)}" | sed 's/^/  /'
        echo
        echo "# Leader de la base (panne.sh leader) : le graphe figé suppose tsdb-mysql-0."
        echo "leader_base:"
        echo "  au_depart: \"${leader_avant:-non lu}\""
        echo "  a_la_fin: \"${leader_apres:-non lu}\""
        echo
        echo "# Placement pod → machine dans $NS_APP (pod, machine, phase, redémarrages par conteneur,"
        echo "# arrêt en cours), relu juste avant"
        echo "# la collecte et à la fin : une panne dépend de qui partage sa machine avec qui."
        echo "placement_au_depart: |"
        printf '%s\n' "${placement_depart:-(non lu)}" | sed 's/^/  /'
        echo "placement_a_la_fin: |"
        printf '%s\n' "${placement_fin:-(non lu)}" | sed 's/^/  /'
        echo
        if [ -n "$couples_lus" ]; then
            echo "# Phase D : la règle des couples (X, Y), graphe_en/couples_d.py, sur le placement de départ."
            echo "couples_d: |"
            printf '%s\n' "$couples_lus" | sed 's/^/  /'
            echo
        fi
        echo "# Calculée par le pilote : mise en route de la collecte + marge → fin − marge."
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

lire_placement() {   # « pod machine phase redémarrages arrêt » par pod de l'espace applicatif
    ssh_master "$PLAFOND_LECTURE" "kubectl get pods" "$(borne "$PLAFOND_LECTURE") kubectl get pods -n '$NS_APP' --no-headers -o custom-columns=:metadata.name,:spec.nodeName,:status.phase,:status.containerStatuses[*].restartCount,:metadata.deletionTimestamp" 2>/dev/null \
        | awk 'NF {print $1, $2, $3, "redemarrages=" $4, ($5 == "<none>" ? "" : "en_arret=" $5)}' | sed 's/ *$//' | sort
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

    # La plage est calculée par le pilote, depuis ses propres instants : le
    # début est celui où IL a mis la collecte en route (ou le premier palier,
    # sans collecte pilotée), la fin est maintenant, chacun rogné de la marge.
    # « collecte.sh fenetre » déduit le début de la date du pod de collecte,
    # qui peut dater d'une campagne précédente ; sa sortie reste dans le compte
    # rendu, à titre de recoupement.
    local origine=$(( ${T_COLLECTE:-${T0:-$(date +%s)}} + MARGE_S )) fin=$(( $(date +%s) - MARGE_S ))
    origine=$(( (origine + 59) / 60 * 60 ))          # à la minute pleine suivante
    fin=$(( fin / 60 * 60 ))                         # à la minute pleine précédente
    plage_date=$(date -u -d "@$origine" +%Y-%m-%d)
    plage_de=$(date -u -d "@$origine" +%H:%M)
    plage_a=$(date -u -d "@$fin" +%H:%M)
    [ "$(date -u -d "@$fin" +%Y-%m-%d)" = "$plage_date" ] \
        || say "La campagne a traversé minuit : « to » est le lendemain de « date » — run.py le comprend (fin ≤ début)."
    [ "$fin" -gt "$origine" ] || { warn "Plage vide : campagne trop courte pour la marge de $((MARGE_S / 60)) min."; plage_de=""; }

    placement_fin=$(lire_placement)
    [ -n "$placement_fin" ] || warn "Placement de fin illisible."
    reglage_fin=$(distant consommateur.sh etat) || reglage_fin="(non lu : $reglage_fin)"
    if leader_apres=$(distant panne.sh leader); then
        [ "$leader_apres" = "$leader_avant" ] || warn "Le leader de la base a changé d'adresse pendant la campagne : $leader_avant → $leader_apres"
    else
        warn "À la fin, tsdb-mysql-0 n'est plus le leader : $leader_apres — les flèches queries de cette campagne sont à vérifier."
    fi

    say "Rapatriement des registres et des journaux…"
    registre=$(ssh_master "$PLAFOND_LECTURE" "cat paliers.tsv" "$(borne "$PLAFOND_LECTURE") cat '$DISTANT/journaux/paliers.tsv'" 2>/dev/null)
    registre_pannes=$(ssh_master "$PLAFOND_LECTURE" "cat pannes.tsv" "$(borne "$PLAFOND_LECTURE") cat '$DISTANT/journaux/pannes.tsv'" 2>/dev/null)
    # Les registres (.tsv) en entier : ils portent l'historique. Les journaux
    # (.log) seulement ceux écrits depuis le départ du pilote : le dossier du
    # master garde ceux de toutes les campagnes précédentes, qui n'ont rien à
    # faire dans la provenance de celle-ci.
    local b; b=$(borne "$PLAFOND_LONGUE")
    ssh_master "$PLAFOND_LONGUE" "copie des journaux" "cd '$DISTANT/journaux' && $b find . -maxdepth 1 -type f \\( -name '*.tsv' -o -newermt '@$T_PILOTE' \\) -print0 | $b tar -c --null -T -" 2>/dev/null \
        | tar -x -C "$DOSSIER/journaux" 2>/dev/null \
        && ok "journaux copiés ($(ls "$DOSSIER/journaux" | wc -l) fichiers)" || warn "copie des journaux impossible"

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
        warn "Pas de plage exploitable — campagne trop courte pour la marge."
    fi
    say "Ce dossier est à committer : c'est la provenance de tes données."
}

retrait_en_cours() {   # <motif> — l'injection encore posée est retirée tout de suite
    say "Retrait de l'injection en cours…"
    # Hors du groupe du terminal (setsid) : un second Ctrl-C ne coupe pas ce
    # retrait, qui commence par annuler le minuteur de la panne sur le master.
    local code=0 sortie; sortie=$(SOUSTRAIT=1 distant panne.sh retirer) || code=$?
    printf '%s\n' "$sortie" | sed 's/^/      /'
    if [ "$code" = 0 ]; then
        noter_action "action: retrait, motif: $1"
    else
        warn "Retrait non confirmé — à vérifier :  ssh $CIBLE 'bash $DISTANT/apps/panne.sh etat'"
        noter_action "action: retrait, resultat: ECHEC, motif: $1"
    fi
    INJECTION_ACTIVE=0
}

# Le pilote dort en arrière-plan et l'attend : un signal envoyé à lui seul
# (kill -INT <pid>) interrompt l'attente au lieu d'attendre le réveil.
SOMMEIL=""
dormir() { sleep "$1" </dev/null >/dev/null 2>&1 3>&- & SOMMEIL=$!; wait "$SOMMEIL"; SOMMEIL=""; }

NETTOYAGE=0
interrompu() {   # [signal] — sans signal : arrêt décidé par le pilote (MOTIF déjà posé)
    [ "$NETTOYAGE" = "0" ] || return 0   # un second signal pendant le nettoyage : ignoré
    NETTOYAGE=1
    trap '' PIPE
    if [ -n "${1:-}" ]; then
        # La sortie a pu disparaître (Ctrl-C tue aussi le tee du journal, terminal
        # fermé) : y écrire tuerait le nettoyage, ou le rendrait muet. Il
        # continue dans le fichier du journal.
        local f=""; [ -f "${JOURNAL_FICHIER:-}" ] && f="$JOURNAL_FICHIER"
        case "$1" in HUP|PIPE) f="${f:-/dev/null}" ;; esac
        if [ -n "$f" ]; then
            [ "$f" = /dev/null ] || echo "  [campagne] nettoyage en cours — suite dans $f" 2>/dev/null
            exec >>"$f" 2>&1 3>&2
        fi
    fi
    [ -z "${1:-}" ] || MOTIF="interrompu_$1"
    [ -z "$SOMMEIL" ] || kill "$SOMMEIL" 2>/dev/null
    echo; warn "Interrompu."
    INTERROMPUE=1
    noter_action "action: interrompu"
    [ "$INJECTION_ACTIVE" != "1" ] || retrait_en_cours interruption
    retour_au_premier_palier
    cloturer
    [ "$MOTIF" != reglage_absent ] || exit 3
    exit 130
}
for s in INT TERM HUP PIPE; do trap "interrompu $s" "$s"; done

# ------------------------------------------------------------------ préparation
etat_avant=$(distant collecte.sh etat)
noter_action "action: etat_initial"
# Le réglage du consommateur fait partie des conditions expérimentales : il est
# relu et recopié dans le compte rendu, pour qu'aucune campagne ne soit
# comparée à une autre sans qu'on sache si elles partagent le même.
reglage_consommateur=$(distant consommateur.sh etat) || reglage_consommateur="(non lu : $reglage_consommateur)"

# La file doit être vide : une campagne qui part sur le tas laissé par la
# précédente porterait dès ses premières fenêtres une panne sans cause. Le tas
# fond de lui-même sous la charge de base ; on attend, en le notant. Avant la
# purge : les messages encore en file s'écrivent dans les tables purgées.
attendre_file_vide() {
    local reste=$(( ${FILE_VIDE_MAX:-40} * 60 )) n attendu=0
    while :; do
        n=$(distant panne.sh temoin court | sed -n 's/.*file [^:]*: \([0-9]*\) en attente.*/\1/p' | head -1)
        [ -n "$n" ] || { warn "File illisible (panne.sh temoin) — on part sans l'avoir vue vide."; return 0; }
        if [ "$n" -eq 0 ]; then [ "$attendu" = "1" ] && ok "file vide"; return 0; fi
        if [ "$attendu" = "0" ]; then
            say "La file porte encore $n message(s) : attente qu'elle se vide (au plus ${FILE_VIDE_MAX:-40} min)…"
            noter_action "action: attente_file_vide, en_attente: $n"; attendu=1
        fi
        [ "$reste" -gt 0 ] || fail "La file ne s'est pas vidée en ${FILE_VIDE_MAX:-40} min ($n restants) : départ refusé."
        dormir 30; reste=$((reste - 30))
    done
}
attendre_file_vide

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
placement_depart=$(lire_placement)
[ -n "$placement_depart" ] && noter_action "action: placement_lu, pods: $(printf '%s\n' "$placement_depart" | wc -l)" \
    || warn "Placement de départ illisible."
# Le leader relu au départ réel : l'attente de la file et la purge ont pu durer.
if ! leader_depart=$(distant panne.sh leader) || [ "$leader_depart" != "$leader_avant" ]; then
    fail "Le leader de la base a changé avant la collecte : « $leader_avant » puis « $leader_depart ». Départ refusé."
fi
# Phase D : les couples (X, Y) sont fixés par la règle écrite avant D (journal,
# D.1) sur le placement relu ici même, après la purge. Des cibles fournies qui
# ne sont plus celles de la règle refusent le départ, avant toute collecte.
if [ "$PANNE" = "network-delay" ]; then
    f_pl=$(mktemp); f_li=$(mktemp)
    printf '%s\n' "$placement_depart" > "$f_pl"
    distant panne.sh libres > "$f_li" || { rm -f "$f_pl" "$f_li"; fail "CPU libre des machines illisible (panne.sh libres)."; }
    couples_lus=$(cd "$RACINE/graphe_en" && ./.venv/bin/python couples_d.py --placement "$f_pl" --libres "$f_li" \
        --injections "${#DEBUTS[@]}" 2>&1)
    rm -f "$f_pl" "$f_li"
    printf '%s\n' "$couples_lus" | sed 's/^/      /'
    # Écart 4 (journal, D.5) : chaque cible doit être UN des couples de la règle ;
    # l'ordre tournant de D.1 n'est plus imposé (sur workers2, la panne ralentit
    # « réserver » au point que le dépôt baisse autant que la capacité).
    autorises=$(printf '%s\n' "$couples_lus" | sed -n 's/^couples : //p' | tr -d ' ')
    fournies=$(IFS=,; echo "${CIBLES[*]}")
    [ -n "$autorises" ] && [ "$autorises" != "AUCUN" ] \
        || fail "Aucun couple selon la règle de D.1 sur le placement relu : départ refusé."
    for c in "${CIBLES[@]}"; do
        case ",$autorises," in
            *",$c,"*) ;;
            *) fail "Cible « $c » hors des couples de la règle de D.1 (« $autorises ») : départ refusé." ;;
        esac
    done
    noter_action "action: couples_verifies, cibles: \"$fournies\", couples_de_la_regle: \"$autorises\""
fi

# Toutes les machines prêtes : une machine absente, ou fermée à l'ordonnanceur,
# déplacerait des pods pendant la mesure.
machines=$(ssh_master "$PLAFOND_LECTURE" "kubectl get nodes" "$(borne "$PLAFOND_LECTURE") kubectl get nodes --no-headers") \
    && [ -n "$(printf '%s\n' "$machines" | awk 'NF >= 2')" ] \
    || fail "Aucune machine lue (kubectl get nodes) : départ refusé."
pas_pretes=$(printf '%s\n' "$machines" | awk 'NF >= 2 && $2 != "Ready" {print $1 " (" $2 ")"}' | paste -sd' ' -)
[ -z "$pas_pretes" ] || fail "Machine(s) pas prête(s) : $pas_pretes — départ refusé."
noter_action "action: machines_pretes, machines: $(printf '%s\n' "$machines" | awk 'NF >= 2' | wc -l)"

# Le retard de base (140 ms) doit être porté par CHAQUE réplique en marche :
# Chaos Mesh ne le pose pas sur une réplique recréée (consommateur.sh). Il est
# reposé ici s'il manque, avant la collecte — jamais pendant la mesure.
code=0; reglage_lu=""; sortie=$(distant consommateur.sh verifier) || code=$?
if [ "$code" = "1" ]; then
    printf '%s\n' "$sortie" | sed 's/^/      /'
    say "Le retard de base manque : nouvelle pose (consommateur.sh reposer)…"
    distant consommateur.sh reposer | sed 's/^/      /'
    code=0; sortie=$(distant consommateur.sh verifier) || code=$?
    reglage_lu=repose
fi
case "$code" in
    0) ok "retard de base sur chaque réplique${reglage_lu:+ (reposé)}"
       noter_action "action: reglage_verifie, resultat: ${reglage_lu:-ok}" ;;
    3) printf '%s\n' "$sortie" | sed 's/^/      /' >&2
       fail "Une panne « consumer-slowdown » remplace le retard de base (consommateur.sh verifier, code 3) : départ refusé." ;;
    *) printf '%s\n' "$sortie" | sed 's/^/      /' >&2
       fail "Le retard de base n'est pas sur chaque réplique${reglage_lu:+, même après consommateur.sh reposer} (consommateur.sh verifier, code $code) : départ refusé." ;;
esac

if [ "$COLLECTE" = "1" ]; then
    say "Démarrage de la collecte…"
    if sortie=$(distant collecte.sh demarrer); then
        ok "collecte démarrée"
        T_COLLECTE=$(date +%s)
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

injecter() {   # <rang de l'injection, depuis 0>
    local cible="${CIBLES[$1]:-}"
    # Le retard de base relu juste avant, sans le reposer : le reposer pendant
    # la mesure changerait les conditions. Sans lui, la panne n'est pas posée et
    # la campagne est close (code 3).
    local code=0 lu; lu=$(distant consommateur.sh verifier) || code=$?
    if [ "$code" != "0" ]; then
        printf '%s\n' "$lu" | sed 's/^/      /' >&2
        noter_action "action: injection, cause: $PANNE, resultat: REFUSEE_REGLAGE${cible:+, cible: $cible}"
        non_injectees=$((non_injectees + 1))
        case "$code" in
            1) lu="retard de base absent sur une réplique" ;;
            3) lu="une panne « consumer-slowdown » est encore en place" ;;
            *) lu="réglage non vérifiable" ;;
        esac
        warn "Injection « $PANNE » refusée : $lu (consommateur.sh verifier, code $code) — panne NON posée, campagne close."
        MOTIF=reglage_absent
        interrompu
    fi
    say "Injection « $PANNE » pendant $DUREE minutes${cible:+ sur $cible}"
    INJECTION_ACTIVE=1
    # La cible est notée APRÈS le résultat : ligne_de_base.py lit « cause »
    # puis « resultat », dans cet ordre et sans rien entre les deux.
    if sortie=$(distant panne.sh injecter "$PANNE" --duree "$DUREE" \
                    ${INTENSITE:+--intensite "$INTENSITE"} ${cible:+--cible "$cible"}); then
        printf '%s\n' "$sortie" | sed 's/^/      /'
        noter_action "action: injection, cause: $PANNE, resultat: confirme${cible:+, cible: $cible}"
        injectees=$((injectees + 1))
    else
        printf '%s\n' "$sortie" | sed 's/^/      /' >&2
        warn "Injection non confirmée — la campagne continue, l'échec est enregistré."
        noter_action "action: injection, cause: $PANNE, resultat: NON_CONFIRME${cible:+, cible: $cible}"
        non_injectees=$((non_injectees + 1))
    fi
}

retirer() {
    say "Retrait de « $PANNE »"
    local ok_retrait=0 avant_retrait; avant_retrait=$(maintenant)
    sortie=$(distant panne.sh retirer) || ok_retrait=1
    # « network-delay » : les paquets jetés de la panne ne se lisent que juste avant son
    # retrait (Chaos Mesh refait la file des pods) ; gardés avec les témoins.
    [ "$PANNE" != "network-delay" ] || TEMOINS="${TEMOINS}
--- relevé « avant le retrait », demandé à $avant_retrait
$(printf '%s\n' "$sortie" | grep -F 'avant le retrait')
"
    if [ "$ok_retrait" = 0 ]; then
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
    MOTIF=parcours_en_defaut
    interrompu
}

# Même bilan, mais seulement noté : une panne « load-surge » ou « consumer-slowdown » peut
# faire échouer un parcours pendant l'injection sans que la campagne soit à
# jeter — c'est justement ce qu'on mesure. Le déroulé dit quand ça a commencé.
veille_des_parcours() {
    local file
    local t leader
    t=$(distant panne.sh temoin court)
    file=$(printf '%s\n' "$t" | sed -n 's/.*file [^:]*: \([0-9]*\) en attente.*/\1/p' | head -1)
    # Le leader, à chaque veille : un changement est un effondrement pour C.
    case "$(printf '%s\n' "$t" | grep '^  base :')" in
        *"est le leader"*) leader=ok ;;
        *ATTENTION*) leader=PERDU; warn "veille : tsdb-mysql-0 n'est plus le leader" ;;
        *) leader="?" ;;
    esac
    if sortie=$(distant loadgen.sh bilan); then
        noter_action "action: veille_parcours, resultat: ok, file: ${file:-?}, leader: $leader"
        say "veille : parcours ok, file ${file:-?}, leader $leader"
    else
        printf '%s\n' "$sortie" | grep -E "^\s+[0-9]{2} |échou|jamais" | sed 's/^/      /' >&2
        noter_action "action: veille_parcours, resultat: EN_DEFAUT, file: ${file:-?}, leader: $leader"
        warn "veille : un parcours échoue ou ne tourne pas — noté, la campagne continue."
    fi
}

attendre_jusqua() {   # <epoch> — dort jusqu'à cet instant, sans dérive
    local n; n=$(date +%s)
    [ "$1" -gt "$n" ] || return 0
    [ $(($1 - n)) -lt 60 ] \
        || say "      … $(( ($1 - n + 30) / 60 )) min d'attente (jusqu'à $(date -u -d "@$1" '+%H:%M') UTC)"
    dormir $(($1 - n))
}

# ------------------------------------------------------------------ le déroulé
echo
T0=$(date +%s)
for ev in "${EVENEMENTS[@]}"; do
    read -r sec _ genre arg <<< "$ev"
    attendre_jusqua $((T0 + sec))
    case "$genre" in
        palier)   appliquer_palier "$arg" ;;
        injecter) injecter "$arg" ;;
        retirer)  retirer ;;
        temoin)   temoin "$arg" ;;
        controle) controle_des_parcours ;;
        veille)   veille_des_parcours ;;
    esac
done
attendre_jusqua $((T0 + TOTAL * 60))

arret_simple   # interrompu n'est plus posé : la fin n'a plus rien à retirer
retour_au_premier_palier
cloturer
MOTIF=termine

}

main "$@"
