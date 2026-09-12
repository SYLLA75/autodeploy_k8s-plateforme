#!/bin/bash
# ==============================================================================
#  apps/consommateur.sh — dimensionner le consommateur pour sa charge
# ==============================================================================
#
#  POURQUOI
#
#  Une faute de coordination n'apparaît que si le consommateur est taillé pour
#  sa charge, avec peu de marge — c'est le cas de tout système réel. Or
#  ts-delivery-service ne fait presque rien par message : 6 ms, soit ~500
#  messages par seconde pour trois répliques, quand la file en reçoit 3. Avec
#  mille fois trop de marge, une réplique gelée ou un hôte saturé ne changent
#  rien à la file : les autres absorbent tout, le tas reste à zéro, et le
#  symptôme central de l'étude n'existe pas.
#
#  CE QUE FAIT CE SCRIPT
#
#  Deux réglages, posés une fois, AVANT la référence saine, et conservés à
#  l'identique pour toutes les campagnes :
#
#    temps de service   chaque échange entre une réplique et sa base est
#                       retardé de L millisecondes (Chaos Mesh NetworkChaos,
#                       sans durée : il reste tant qu'on ne le retire pas).
#                       Traiter un message coûte quelques échanges avec la base
#                       (lecture, insertion, validation, plus la gestion de la
#                       transaction) : le temps de service vaut environ 5 × L.
#                       Le retard est PROPRE À CHAQUE RÉPLIQUE : trois
#                       répliques traitent bien trois messages à la fois.
#
#    prefetch = 1       le courtier ne confie qu'un message à la fois à chaque
#                       réplique. Par défaut il en confie 250 d'avance : le tas
#                       visible (messages en attente) ne bougerait qu'après
#                       750 messages en souffrance, et une réplique gelée en
#                       emporterait 250 avec elle.
#
#  POURQUOI UN RETARD RÉSEAU ET PAS UN SOMMEIL DANS LA BASE
#
#  Un déclencheur SQL qui dort à chaque insertion a été essayé : la base
#  n'exécute qu'un sommeil à la fois, quel que soit le nombre de répliques
#  (mesuré : 1 sommeil actif en permanence, 1,3 message/s pour 3 répliques
#  à 0,7 s). La capacité ne dépendait plus du nombre de répliques, et une
#  réplique gelée n'aurait rien changé. Le retard réseau s'applique dans
#  chaque pod, indépendamment des autres.
#
#  COMMENT CHOISIR L
#
#  Capacité des N répliques = N / (5 × L) messages par seconde. On vise ~80 %
#  à la charge de base : L = 0,8 × N / (5 × débit_de_base). Avec 3 répliques
#  et 3,4 messages/s mesurés (25 voyageurs) : L ≈ 140 ms. Le facteur 5 se
#  vérifie sur la première référence (process_time_p50 des répliques dans les
#  figures) et sur le témoin : le tas ne doit pas grossir à la charge de base.
#
#  Usage (depuis le master) :
#      bash ~/autodeploy/apps/consommateur.sh dimensionner --retard 140 [--prefetch 1]
#      bash ~/autodeploy/apps/consommateur.sh etat
#      bash ~/autodeploy/apps/consommateur.sh retirer
#
#  Variables reconnues :
#      CONSO_NAMESPACE     (défaut: train-ticket)
#      CONSO_DEPLOY        (défaut: ts-delivery-service)   le consommateur
#      CONSO_MYSQL_LABEL   (défaut: app=tsdb-mysql)        les pods de sa base
#      CONSO_DB            (défaut: ts)                    la base
#      CONSO_TABLE         (défaut: delivery)              la table où il écrit
# ==============================================================================
set -uo pipefail

_ici="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Une simple lecture ne laisse pas de journal : il n'y a rien à garder, et
# un relevé répété toutes les 20 s en écrirait des centaines.
case "${1:-}" in etat) JOURNAL_OFF=1 ;; esac
[ -f "$_ici/journal.sh" ] && JOURNAL_NOM="consommateur" . "$_ici/journal.sh"

DEPLOY="${CONSO_DEPLOY:-ts-delivery-service}"
TABLE="${CONSO_TABLE:-delivery}"
DECLENCHEUR="temps_de_service"
ENV_PREFETCH="SPRING_RABBITMQ_LISTENER_SIMPLE_PREFETCH"

JOURNAUX="$(cd "$_ici/.." && pwd)/journaux"
REGISTRE="$JOURNAUX/consommateur.tsv"
COLONNES='# instant\taction\tretard_ms\tprefetch\tresultat'

say()  { echo "  [consommateur] $*"; }
ok()   { echo "  [consommateur] OK  $*"; }
warn() { echo "  [consommateur] ATTENTION: $*" >&2; }
fail() { echo "  [consommateur] ERREUR: $*" >&2; exit 1; }
maintenant() { date -u +%Y-%m-%dT%H:%M:%SZ; }

consigner() {
    mkdir -p "$JOURNAUX" 2>/dev/null
    [ -f "$REGISTRE" ] || printf "$COLONNES\n" > "$REGISTRE" 2>/dev/null
    printf '%s\t%s\t%s\t%s\t%s\n' "$(maintenant)" "$1" "$2" "$3" "$4" >> "$REGISTRE" 2>/dev/null
}

. "$_ici/mysql.sh"

OBJET="consommateur-temps-de-service"   # l'objet Chaos Mesh du retard

retard_actuel() {   # la latence posée, en ms, vide s'il n'y a pas d'objet
    kubectl get networkchaos "$OBJET" -n "$NS" -o jsonpath='{.spec.delay.latency}' 2>/dev/null | tr -d 'ms'
}

retard_injecte() {   # Chaos Mesh l'a-t-il appliqué sur toutes les répliques ?
    [ "$(kubectl get networkchaos "$OBJET" -n "$NS" -o jsonpath='{.status.conditions[?(@.type=="AllInjected")].status}' 2>/dev/null)" = "True" ]
}

# Un sommeil dans la base ne doit pas coexister avec le retard : il retirerait
# le parallélisme des répliques.
declencheur_present() {
    [ -n "$(sql "SELECT 1 FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA='$DB' AND TRIGGER_NAME='$DECLENCHEUR';" 2>/dev/null | tail -1)" ]
}

repliques_pretes() {   # toutes les répliques voulues sont-elles prêtes ET à jour ?
    local v p m
    v=$(kubectl get deploy "$DEPLOY" -n "$NS" -o jsonpath='{.spec.replicas}' 2>/dev/null)
    p=$(kubectl get deploy "$DEPLOY" -n "$NS" -o jsonpath='{.status.readyReplicas}' 2>/dev/null)
    m=$(kubectl get deploy "$DEPLOY" -n "$NS" -o jsonpath='{.status.updatedReplicas}' 2>/dev/null)
    [ -n "$v" ] && [ "${p:-0}" = "$v" ] && [ "${m:-0}" = "$v" ]
}

prefetch_actuel() {   # la valeur portée par le déploiement, vide si absente
    kubectl get deploy "$DEPLOY" -n "$NS" \
        -o jsonpath="{.spec.template.spec.containers[0].env[?(@.name==\"$ENV_PREFETCH\")].value}" 2>/dev/null
}

# poser_retard <ms> — crée ou remplace l'objet, attend qu'il soit appliqué
poser_retard() {
    local ms="$1"
    kubectl delete networkchaos "$OBJET" -n "$NS" --ignore-not-found --timeout=90s >/dev/null 2>&1
    yaml_retard "$OBJET" "$DEPLOY" "$ms" "" "reglage=consommateur" | kubectl apply -f - >/dev/null || return 1
    local reste=60
    while [ "$reste" -gt 0 ]; do
        retard_injecte && return 0
        sleep 3; reste=$((reste - 3))
    done
    return 1
}

# ------------------------------------------------------------------------------
dimensionner_app() {
    local retard="" prefetch=1
    while [ $# -gt 0 ]; do
        case "$1" in
            --retard)   retard="${2:-}"; shift 2 ;;
            --prefetch) prefetch="${2:-}"; shift 2 ;;
            *) fail "Option inconnue : $1" ;;
        esac
    done
    case "$retard" in ''|*[!0-9]*) fail "--retard : un nombre de millisecondes, par exemple 140" ;; esac
    [ "$retard" -ge 1 ] || fail "--retard : au moins 1 ms"
    case "$prefetch" in ''|*[!0-9]*) fail "--prefetch : un entier" ;; esac
    [ "$prefetch" -ge 1 ] || fail "--prefetch : au moins 1"
    kubectl get deploy "$DEPLOY" -n "$NS" >/dev/null 2>&1 || fail "Déploiement « $DEPLOY » introuvable dans $NS."
    kubectl get crd networkchaos.chaos-mesh.org >/dev/null 2>&1 || fail "Chaos Mesh absent — étape 6 bis : chaos.sh install"
    local n; n=$(kubectl get pods -n "$NS" -l "app=$DEPLOY" --field-selector=status.phase=Running --no-headers 2>/dev/null | wc -l)
    [ "$n" -gt 0 ] || fail "Aucune réplique de $DEPLOY en marche."

    if declencheur_present; then
        say "Un sommeil dans la base est en place : retiré (il sérialise les répliques)."
        sql "DROP TRIGGER IF EXISTS $DECLENCHEUR;" >/dev/null
    fi

    say "Temps de service : $retard ms de retard à chaque échange des $n répliques avec leur base (≈ $((retard * 5)) ms par message)"
    if poser_retard "$retard"; then
        ok "retard posé sur $n réplique(s)"
    else
        consigner dimensionner "$retard" "$prefetch" ECHEC
        fail "Chaos Mesh n'a pas confirmé en 60 s :  kubectl describe networkchaos $OBJET -n $NS"
    fi

    say "Prefetch : $prefetch message(s) d'avance par réplique"
    local avant; avant=$(prefetch_actuel)
    if [ "$avant" = "$prefetch" ]; then
        say "déjà en place, pas de redémarrage"
    else
        kubectl set env deploy/"$DEPLOY" -n "$NS" "$ENV_PREFETCH=$prefetch" >/dev/null \
            || { consigner dimensionner "$retard" "$prefetch" ECHEC; fail "kubectl set env a échoué."; }
        say "redémarrage roulant des répliques (nouveaux pods, donc nouveaux nœuds dans le graphe — d'où « avant la référence »)…"
        # Trois services Java qui redémarrent l'un après l'autre : compter
        # jusqu'à dix minutes, et regarder l'état réel avant de conclure.
        kubectl rollout status deploy/"$DEPLOY" -n "$NS" --timeout=600s >/dev/null 2>&1 \
            || repliques_pretes \
            || { consigner dimensionner "$retard" "$prefetch" ECHEC; fail "Les répliques ne sont pas revenues en 10 min :  kubectl get pods -n $NS -l app=$DEPLOY"; }
        # Le retard vise des pods par étiquette : les nouveaux sont couverts,
        # mais on le vérifie plutôt que de le supposer.
        retard_injecte || { sleep 15; retard_injecte; } || warn "Chaos Mesh ne confirme pas le retard sur les nouvelles répliques :  kubectl describe networkchaos $OBJET -n $NS"
    fi
    consigner dimensionner "$retard" "$prefetch" ok
    ok "consommateur dimensionné — à conserver tel quel pour toutes les campagnes"
    echo
    etat_app
}

etat_app() {
    local ms; ms=$(retard_actuel)
    local pf; pf=$(prefetch_actuel)
    local repl; repl=$(kubectl get deploy "$DEPLOY" -n "$NS" -o jsonpath='{.status.readyReplicas}/{.spec.replicas}' 2>/dev/null)
    echo "  consommateur : $DEPLOY ($repl répliques prêtes)"
    if [ -n "$ms" ]; then
        local app="appliqué"; retard_injecte || app="PAS appliqué — kubectl describe networkchaos $OBJET -n $NS"
        echo "  temps de service : $ms ms de retard par échange avec la base, ≈ $((ms * 5)) ms par message   ($app)"
    else
        echo "  temps de service : aucun   (pas de retard — 6 ms par message, marge × 150)"
    fi
    declencheur_present && echo "  ATTENTION : un sommeil dans la base est encore en place ($DECLENCHEUR) — dimensionner le retire"
    echo "  prefetch : ${pf:-250 (défaut du courtier)}"
    return 0
}

retirer_app() {
    say "Retrait du retard…"
    kubectl delete networkchaos "$OBJET" -n "$NS" --ignore-not-found --timeout=90s >/dev/null 2>&1 \
        && ok "retard retiré" || warn "l'objet $OBJET résiste"
    declencheur_present && { sql "DROP TRIGGER IF EXISTS $DECLENCHEUR;" >/dev/null; ok "sommeil dans la base retiré"; }
    if [ -n "$(prefetch_actuel)" ]; then
        say "Retrait du prefetch (redémarrage roulant)…"
        kubectl set env deploy/"$DEPLOY" -n "$NS" "$ENV_PREFETCH-" >/dev/null \
            && { kubectl rollout status deploy/"$DEPLOY" -n "$NS" --timeout=600s >/dev/null 2>&1 || repliques_pretes; } \
            && ok "prefetch retiré" || warn "le prefetch n'a pas pu être retiré"
    fi
    consigner retirer "" "" ok
    echo
    etat_app
}

case "${1:-etat}" in
    dimensionner) shift; dimensionner_app "$@" ;;
    etat)         etat_app ;;
    retirer)      retirer_app ;;
    *) echo "Usage: $0 {dimensionner --retard <ms> [--prefetch <n>]|etat|retirer}" >&2; exit 2 ;;
esac
