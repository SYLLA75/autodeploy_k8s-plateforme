#!/bin/bash
# ==============================================================================
#  apps/donnees.sh — remettre les données de l'application à zéro
# ==============================================================================
#
#  POURQUOI
#
#  Le comportement de train-ticket dépend de ce que ses tables contiennent.
#  Chaque réservation ajoute une commande ; pour compter les places vendues,
#  le service des sièges demande au service des commandes TOUTES les commandes
#  du train à cette date, et celui-ci les charge en mémoire (tas Java limité à
#  200 Mo). Mesuré : à 5 000 commandes sur un même train et un même jour, il
#  se fige (« Thread starvation… 55 s »), le service des sièges attend, la
#  recherche attend le service des sièges en gardant ses 10 connexions à la
#  base, et toute recherche répond « 500 » après 30 s — même à 1 voyageur, même
#  après redémarrage des services du dessus.
#
#  Une campagne n'est donc comparable à une autre que si les deux partent des
#  mêmes tables. Ce script les vide, et le pilote l'appelle au départ de chaque
#  campagne.
#
#  CE QUI EST VIDÉ
#
#      orders, orders_other    les commandes (réservations)
#      food_order              les commandes de repas
#      delivery                les livraisons enregistrées par le consommateur
#                              (la table garde son déclencheur de temps de
#                              service : TRUNCATE ne touche pas aux triggers)
#
#  Les données de démonstration (gares, trains, comptes, contacts) ne sont pas
#  touchées : les parcours en ont besoin, et elles ne grossissent pas.
#
#  LA PURGE NE REDÉMARRE RIEN, SAUF DEMANDE
#
#  Un service des commandes déjà étouffé garde la trace de l'étouffement
#  (connexions, mémoire) : la table vide ne suffit pas, il faut le redémarrer.
#  Mais le redémarrer SEUL casse la chaîne de recherche : les services qui
#  l'appellent (sièges, recherche) gardent des connexions ouvertes vers le pod
#  disparu et y attendent sans limite — mesuré : recherche à 100 % d'échecs,
#  30 s, dans la minute qui suit. « --redemarrer » redémarre donc les trois,
#  dans l'ordre commandes, sièges, recherche. Sain, un service n'a pas besoin
#  de redémarrer : le pilote purge sans, et « loadgen.sh bilan » dit si la
#  chaîne va bien.
#
#  LE SERVICE DES COMMANDES A BESOIN DE PLUS D'UN DEMI-CŒUR
#
#  Même étalées sur l'année, les commandes coûtent : mesuré (charge-02), le
#  CPU du service des commandes croît avec leur TOTAL — 97 m à 1 900
#  commandes, 212 m à 4 700, 444 m à 5 900 — jusqu'à sa limite de 500 m, où
#  la réservation passe de 0,3 à 5 s et les voyageurs y restent coincés. Une
#  campagne de deux heures en produit 8 000. « dimensionner » relève sa
#  limite CPU (2 cœurs par défaut) ; une fois, après l'installation.
#
#  Usage (depuis le master) :
#      bash ~/autodeploy/apps/donnees.sh etat
#      bash ~/autodeploy/apps/donnees.sh purger [--redemarrer]
#      bash ~/autodeploy/apps/donnees.sh redemarrer          la chaîne seule
#      bash ~/autodeploy/apps/donnees.sh dimensionner [--cpu 2000m]
#
#  Variables reconnues : celles de apps/mysql.sh (CONSO_NAMESPACE, CONSO_DB…)
#      DONNEES_TABLES   (défaut: "orders orders_other food_order delivery")
#      DONNEES_CHAINE   (défaut: "ts-order-service ts-seat-service ts-travel-service")
#                       les services redémarrés, dans cet ordre, avec --redemarrer
#      DONNEES_CPU      (défaut: 2000m) limite CPU du service des commandes
# ==============================================================================
set -uo pipefail

_ici="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Une simple lecture ne laisse pas de journal : il n'y a rien à garder, et
# un relevé répété toutes les 20 s en écrirait des centaines.
case "${1:-}" in etat) JOURNAL_OFF=1 ;; esac
[ -f "$_ici/journal.sh" ] && JOURNAL_NOM="donnees" . "$_ici/journal.sh"
. "$_ici/mysql.sh"

TABLES="${DONNEES_TABLES:-orders orders_other food_order delivery}"
CHAINE="${DONNEES_CHAINE:-ts-order-service ts-seat-service ts-travel-service}"
CPU_COMMANDES="${DONNEES_CPU:-2000m}"
COMMANDES="${CHAINE%% *}"          # le premier de la chaîne : ts-order-service

JOURNAUX="$(cd "$_ici/.." && pwd)/journaux"
REGISTRE="$JOURNAUX/donnees.tsv"
COLONNES='# instant\taction\tlignes_avant\tresultat'

say()  { echo "  [donnees] $*"; }
ok()   { echo "  [donnees] OK  $*"; }
warn() { echo "  [donnees] ATTENTION: $*" >&2; }
fail() { echo "  [donnees] ERREUR: $*" >&2; exit 1; }
maintenant() { date -u +%Y-%m-%dT%H:%M:%SZ; }

consigner() {
    mkdir -p "$JOURNAUX" 2>/dev/null
    [ -f "$REGISTRE" ] || printf "$COLONNES\n" > "$REGISTRE" 2>/dev/null
    printf '%s\t%s\t%s\t%s\n' "$(maintenant)" "$1" "$2" "$3" >> "$REGISTRE" 2>/dev/null
}

lignes() {   # <table> → nombre de lignes, ou « ? »
    local n; n=$(sql "SELECT COUNT(*) FROM $1;" 2>/dev/null | tail -1)
    case "$n" in ''|*[!0-9]*) echo "?" ;; *) echo "$n" ;; esac
}

etat_app() {
    local t n total=0
    for t in $TABLES; do
        n=$(lignes "$t")
        printf "  %-14s %8s lignes\n" "$t" "$n"
        case "$n" in *[!0-9]*) ;; *) total=$((total + n)) ;; esac
    done
    # La concentration décide, pas le total : c'est « ce train, ce jour » qui
    # est chargé en mémoire à chaque recherche.
    local pire; pire=$(sql "SELECT CONCAT(n, ' sur ', train_number, ' le ', travel_date) FROM (SELECT travel_date, train_number, COUNT(*) n FROM orders GROUP BY 1,2 ORDER BY n DESC LIMIT 1) x;" 2>/dev/null | tail -1)
    [ -n "$pire" ] && echo "  commandes les plus concentrées : $pire"
    echo "  total : $total lignes"
    echo "  limite CPU de $COMMANDES : $(limite_cpu_commandes)"
    return 0
}

limite_cpu_commandes() {
    kubectl get deploy "$COMMANDES" -n "$NS" -o jsonpath='{.spec.template.spec.containers[0].resources.limits.cpu}' 2>/dev/null || echo "?"
}

dimensionner_app() {
    local cpu="$CPU_COMMANDES"
    while [ $# -gt 0 ]; do
        case "$1" in --cpu) cpu="${2:-}"; shift 2 ;; *) fail "Option inconnue : $1" ;; esac
    done
    case "$cpu" in ''|*[!0-9m]*) fail "--cpu : une quantité Kubernetes, par exemple 2000m" ;; esac
    kubectl get deploy "$COMMANDES" -n "$NS" >/dev/null 2>&1 || fail "Déploiement « $COMMANDES » introuvable dans $NS."
    local avant; avant=$(limite_cpu_commandes)
    if [ "$avant" = "$cpu" ]; then
        say "$COMMANDES a déjà une limite CPU de $cpu — rien à faire"
        return 0
    fi
    say "Limite CPU de $COMMANDES : $avant → $cpu (redémarrage roulant, puis la chaîne)…"
    kubectl set resources deploy/"$COMMANDES" -n "$NS" --limits=cpu="$cpu" >/dev/null         || { consigner dimensionner "$avant" ECHEC; fail "kubectl set resources a échoué."; }
    # Le service redémarre seul ; les deux du dessus gardent des connexions
    # vers le pod disparu (voir plus haut) : on redémarre la chaîne entière.
    redemarrer_chaine || { consigner dimensionner "$avant" ECHEC; fail "La chaîne n'est pas revenue."; }
    consigner dimensionner "$avant->$cpu" ok
    ok "$COMMANDES limité à $cpu — à faire une fois, avant la référence saine"
}

redemarrer_chaine() {   # commandes, sièges, recherche — l'un après l'autre
    local d
    for d in $CHAINE; do
        say "Redémarrage de $d…"
        kubectl rollout restart deploy/"$d" -n "$NS" >/dev/null 2>&1 \
            && kubectl rollout status deploy/"$d" -n "$NS" --timeout=300s >/dev/null 2>&1 \
            && say "$d redémarré" \
            || { warn "$d n'est pas revenu en 5 min :  kubectl get pods -n $NS -l app=$d"; return 1; }
    done
}

purger_app() {
    local redemarrage=0
    case "${1:-}" in
        --redemarrer) redemarrage=1 ;;
        --sans-redemarrage|'') ;;
        *) fail "Option inconnue : $1" ;;
    esac
    local avant=0 t n
    for t in $TABLES; do
        n=$(lignes "$t"); case "$n" in *[!0-9]*) ;; *) avant=$((avant + n)) ;; esac
    done
    say "Purge de : $TABLES  ($avant lignes)"
    local sortie; sortie=$(sql "$(for t in $TABLES; do printf 'TRUNCATE TABLE %s; ' "$t"; done)")
    if [ -n "$sortie" ]; then
        printf '%s\n' "$sortie" | sed 's/^/      /' >&2
        consigner purger "$avant" ECHEC
        fail "La base a refusé la purge."
    fi
    [ "$redemarrage" = "0" ] || redemarrer_chaine || { consigner purger "$avant" ECHEC; fail "La chaîne n'est pas revenue."; }
    consigner purger "$avant" ok
    ok "données remises à zéro"
    etat_app
}

case "${1:-etat}" in
    etat)   etat_app ;;
    purger) shift; purger_app "${1:-}" ;;
    redemarrer) redemarrer_chaine && ok "chaîne redémarrée" ;;
    dimensionner) shift; dimensionner_app "$@" ;;
    *) echo "Usage: $0 {etat|purger [--redemarrer]|redemarrer|dimensionner [--cpu <q>]}" >&2; exit 2 ;;
esac
