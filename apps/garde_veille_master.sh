#!/bin/bash
# ==============================================================================
#  garde_veille_master.sh — sur le master : le gardien donne-t-il encore signe
#  de vie ? (la garde surveillée de l'extérieur, C14)
# ==============================================================================
#
#  CE QUE FAIT CE SCRIPT
#
#  Lancé par cron toutes les 5 minutes sur le MASTER, il lit l'âge de
#  ~/garde.battement : l'heure UTC que la sonde du gardien (apps/garde_sonde.py,
#  lancée par garde.py depuis vms0) y écrit chaque minute.
#    - battement de plus de 3 min (ou absent) : au début de l'incident, UNE ligne
#          <instant> ALERTE gardien muet depuis N min (dernier battement : …)
#      dans ~/alertes-garde.txt ; puis, tant que ça dure, un rappel au plus une
#      fois par heure (« ALERTE (rappel) … ») ; rien d'autre entre-temps ;
#    - battement revenu : UNE ligne « <instant> FIN gardien de nouveau vivant … ».
#  L'incident en cours est noté dans un petit fichier à côté
#  (~/alertes-garde.etat : DEBUT, RAPPEL, en secondes depuis 1970), effacé à la FIN.
#
#  POURQUOI
#
#  Un gardien mort ne peut pas dire qu'il est mort : il faut un témoin
#  extérieur (C14). La sonde du gardien
#  passe sur le master chaque minute ; si le battement vieillit, c'est que le
#  gardien, vms0, le lien ssh ou la sonde ne tournent plus. Ce script ne fait
#  AUCUNE action sur le cluster (ni ssh, ni kubectl) et n'écrit que ses deux
#  fichiers : ~/alertes-garde.txt, ~/alertes-garde.etat (écrit d'un coup via
#  ~/alertes-garde.etat.tmp, aussitôt renommé). Tout le reste est lu (date,
#  stat, head). Une sortie sur l'écran seulement en cas d'erreur ; la ligne
#  cron ci-dessous l'ajoute à ~/garde_veille.log (c'est cron qui écrit ce
#  journal, pas le script).
#
#  LA LIGNE CRON (sur le master : crontab -e) :
#      */5 * * * * bash $HOME/autodeploy/apps/garde_veille_master.sh >> $HOME/garde_veille.log 2>&1
#  (cron passe la ligne à /bin/sh, qui remplace $HOME. Si le dépôt n'est pas
#  dans ~/autodeploy sur le master, adapter le chemin.)
#  Vérifier :  crontab -l | grep garde_veille
#              bash ~/autodeploy/apps/garde_veille_master.sh --etat
#
#  Usage :
#      bash apps/garde_veille_master.sh           une vérification (ce que fait cron)
#      bash apps/garde_veille_master.sh --etat    affiche l'âge du battement et
#                                                 l'incident en cours, sans rien écrire
#
#  Variables reconnues :
#      VEILLE_MAINTENANT  (essais seulement) l'heure de la veille, AAAA-MM-JJTHH:MM:SSZ
#      VEILLE_SEUIL_MIN   (défaut: 3)   minutes au-delà desquelles le gardien est muet
#      VEILLE_RAPPEL_MIN  (défaut: 60)  minutes entre deux rappels
# ==============================================================================
set -uo pipefail

BATTEMENT="$HOME/garde.battement"
ALERTES="$HOME/alertes-garde.txt"
ETAT="$HOME/alertes-garde.etat"
SEUIL_MIN="${VEILLE_SEUIL_MIN:-3}"
RAPPEL_MIN="${VEILLE_RAPPEL_MIN:-60}"

say()  { echo "  [veille] $*"; }
ok()   { echo "  [veille] OK  $*"; }
warn() { echo "  [veille] ATTENTION: $*" >&2; }
fail() { echo "  [veille] ERREUR: $*" >&2; exit 1; }

iso() { date -u -d "@$1" +%Y-%m-%dT%H:%M:%SZ; }
maintenant() {
    if [ -n "${VEILLE_MAINTENANT:-}" ]; then
        date -u -d "$VEILLE_MAINTENANT" +%s || fail "VEILLE_MAINTENANT illisible : $VEILLE_MAINTENANT"
    else
        date -u +%s
    fi
}

# Le dernier battement, en secondes : l'heure écrite dans le fichier ; à défaut
# (contenu abîmé), la date du fichier. Vide si le fichier manque.
# TEXTE_BATTEMENT : ce qu'on en dit dans les lignes d'alerte.
lire_battement() {
    BAT=""; TEXTE_BATTEMENT="aucun (fichier ~/garde.battement absent)"
    [ -f "$BATTEMENT" ] || return 0
    local contenu
    contenu=$(head -c 64 "$BATTEMENT" 2>/dev/null | head -n 1 | tr -d '\r\n ')
    if [[ "$contenu" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] \
        && BAT=$(date -u -d "$contenu" +%s 2>/dev/null); then
        TEXTE_BATTEMENT="$contenu"
    elif BAT=$(stat -c %Y "$BATTEMENT" 2>/dev/null); then
        TEXTE_BATTEMENT="$(iso "$BAT") (date du fichier, contenu illisible)"
    else
        BAT=""
    fi
}

# L'incident en cours : DEBUT et RAPPEL (secondes), lus sans exécuter le fichier.
lire_etat() {
    DEBUT=""; RAPPEL=""
    [ -f "$ETAT" ] || return 0
    local k v
    while IFS='=' read -r k v; do
        case "$k" in
            DEBUT)  [[ "$v" =~ ^[0-9]+$ ]] && DEBUT="$v" ;;
            RAPPEL) [[ "$v" =~ ^[0-9]+$ ]] && RAPPEL="$v" ;;
        esac
    done < "$ETAT"
    [ -n "$DEBUT" ] || DEBUT="$(stat -c %Y "$ETAT" 2>/dev/null || echo 0)"   # fichier abîmé : sa date
    [ -n "$RAPPEL" ] || RAPPEL="$DEBUT"
}
ecrire_etat() {   # <debut> <rappel> — d'un coup (temporaire puis renommage)
    printf 'DEBUT=%s\nRAPPEL=%s\n' "$1" "$2" > "$ETAT.tmp" && mv -f "$ETAT.tmp" "$ETAT" \
        || fail "impossible d'écrire $ETAT"
}
alerter() { echo "$*" >> "$ALERTES" || fail "impossible d'écrire dans $ALERTES"; }

NOW=$(maintenant) || exit 1
lire_battement
lire_etat
AGE_MIN=""; age_s=0
if [ -n "$BAT" ]; then
    age_s=$((NOW - BAT)); [ "$age_s" -ge 0 ] || age_s=0
    AGE_MIN=$((age_s / 60))
fi
MUET=0
if [ -z "$BAT" ] || [ "$age_s" -gt $((SEUIL_MIN * 60)) ]; then MUET=1; fi

if [ "${1:-}" = "--etat" ]; then
    say "maintenant           : $(iso "$NOW")"
    say "dernier battement    : $TEXTE_BATTEMENT${AGE_MIN:+ (il y a $AGE_MIN min)}"
    if [ "$MUET" = 1 ]; then warn "gardien MUET (plus de $SEUIL_MIN min ou battement absent)"; else ok "gardien vivant"; fi
    if [ -f "$ETAT" ]; then
        say "incident en cours    : depuis $(iso "$DEBUT"), dernier rappel $(iso "$RAPPEL")"
    else
        say "incident en cours    : aucun"
    fi
    say "alertes              : $ALERTES ($( [ -f "$ALERTES" ] && grep -c . "$ALERTES" || echo 0) ligne(s))"
    exit 0
elif [ $# -gt 0 ]; then
    echo "Usage : $0 [--etat]" >&2; exit 2
fi

h=$(iso "$NOW")
if [ "$MUET" = 1 ]; then
    if [ -n "$AGE_MIN" ]; then quoi="gardien muet depuis $AGE_MIN min"; else quoi="gardien muet : aucun battement"; fi
    if [ ! -f "$ETAT" ]; then
        alerter "$h ALERTE $quoi (dernier battement : $TEXTE_BATTEMENT)"
        ecrire_etat "$NOW" "$NOW"
    elif [ $((NOW - RAPPEL)) -ge $((RAPPEL_MIN * 60)) ]; then
        alerter "$h ALERTE (rappel) $quoi (dernier battement : $TEXTE_BATTEMENT ; incident ouvert à $(iso "$DEBUT"))"
        ecrire_etat "$DEBUT" "$NOW"
    fi
elif [ -f "$ETAT" ]; then
    alerter "$h FIN gardien de nouveau vivant (battement : $TEXTE_BATTEMENT ; incident ouvert à $(iso "$DEBUT"), $(( (NOW - DEBUT) / 60 )) min)"
    rm -f "$ETAT"
fi
exit 0
