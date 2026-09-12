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
#    temps de service   chaque message coûte S secondes au consommateur. C'est
#                       un déclencheur SQL sur la table où le consommateur
#                       écrit : chaque insertion attend S. Le temps est passé
#                       dans l'appel à la base, là où un vrai service de
#                       livraison passerait le sien.
#
#    prefetch = 1       le courtier ne confie qu'un message à la fois à chaque
#                       réplique. Par défaut il en confie 250 d'avance : le tas
#                       visible (messages en attente) ne bougerait qu'après
#                       750 messages en souffrance, et une réplique gelée en
#                       emporterait 250 avec elle.
#
#  COMMENT CHOISIR S
#
#  Capacité des N répliques = N / S messages par seconde. On vise ~80 % à la
#  charge de base :  S = 0,8 × N / débit_de_base. Avec 3 répliques et 3
#  messages/s (25 voyageurs, générateur par défaut) : S = 0,8 s.
#
#  Usage (depuis le master) :
#      bash ~/autodeploy/apps/consommateur.sh dimensionner --temps 0.8 [--prefetch 1]
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
[ -f "$_ici/journal.sh" ] && JOURNAL_NOM="consommateur" . "$_ici/journal.sh"

NS="${CONSO_NAMESPACE:-train-ticket}"
DEPLOY="${CONSO_DEPLOY:-ts-delivery-service}"
MYSQL_LABEL="${CONSO_MYSQL_LABEL:-app=tsdb-mysql}"
DB="${CONSO_DB:-ts}"
TABLE="${CONSO_TABLE:-delivery}"
DECLENCHEUR="temps_de_service"
ENV_PREFETCH="SPRING_RABBITMQ_LISTENER_SIMPLE_PREFETCH"

JOURNAUX="$(cd "$_ici/.." && pwd)/journaux"
REGISTRE="$JOURNAUX/consommateur.tsv"
COLONNES='# instant\taction\ttemps_s\tprefetch\tresultat'

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

# ------------------------------------------------------------------------------
# La base : on parle au chef (les écritures y vont), avec le mot de passe que
# le pod porte lui-même dans son environnement.
# ------------------------------------------------------------------------------
pod_mysql() {
    local p
    p=$(kubectl get pods -n "$NS" -l "$MYSQL_LABEL,role=leader" --no-headers \
        -o custom-columns=:metadata.name 2>/dev/null | head -1)
    [ -n "$p" ] || p=$(kubectl get pods -n "$NS" -l "$MYSQL_LABEL" --no-headers \
        -o custom-columns=:metadata.name 2>/dev/null | head -1)
    echo "$p"
}

sql() {   # <requête> — sur la base $DB, sortie brute
    local pod; pod=$(pod_mysql)
    [ -n "$pod" ] || fail "Aucun pod « $MYSQL_LABEL » dans $NS : la base du consommateur est introuvable."
    # Sans mot de passe dans l'environnement du pod, « -p » seul demanderait le
    # mot de passe au terminal et son invite salirait la sortie.
    kubectl exec -n "$NS" "$pod" -c mysql -- sh -c \
        'mysql -uroot ${MYSQL_ROOT_PASSWORD:+-p"$MYSQL_ROOT_PASSWORD"} --database="$1" -N -B -e "$2" 2>&1 \
         | grep -v "Using a password" | sed "s/^Enter password: //"' \
        sh "$DB" "$1"
}

declencheur_actuel() {   # la définition posée, vide s'il n'y en a pas
    sql "SELECT ACTION_STATEMENT FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA='$DB' AND TRIGGER_NAME='$DECLENCHEUR';" 2>/dev/null
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

# ------------------------------------------------------------------------------
dimensionner_app() {
    local temps="" prefetch=1
    while [ $# -gt 0 ]; do
        case "$1" in
            --temps)    temps="${2:-}"; shift 2 ;;
            --prefetch) prefetch="${2:-}"; shift 2 ;;
            *) fail "Option inconnue : $1" ;;
        esac
    done
    case "$temps" in
        ''|*[!0-9.]*|.|*.*.*) fail "--temps : un nombre de secondes, par exemple 0.8" ;;
    esac
    case "$prefetch" in ''|*[!0-9]*) fail "--prefetch : un entier" ;; esac
    [ "$prefetch" -ge 1 ] || fail "--prefetch : au moins 1"
    kubectl get deploy "$DEPLOY" -n "$NS" >/dev/null 2>&1 || fail "Déploiement « $DEPLOY » introuvable dans $NS."

    say "Temps de service : $temps s par message, sur la table $DB.$TABLE"
    local tables; tables=$(sql "SHOW TABLES LIKE '$TABLE';")
    if [ "$tables" != "$TABLE" ]; then
        [ -z "$tables" ] || printf '%s\n' "$tables" | sed 's/^/      /' >&2
        warn "table « $TABLE » introuvable dans la base « $DB ». Tables dont le nom contient « $TABLE », toutes bases :"
        sql "SELECT CONCAT(table_schema, '.', table_name) FROM information_schema.tables WHERE table_name LIKE '%$TABLE%';" \
            | sed 's/^/      /' >&2
        fail "Donne la bonne base et la bonne table :  CONSO_DB=… CONSO_TABLE=… bash $0 dimensionner --temps $temps"
    fi
    local sortie
    sortie=$(sql "DROP TRIGGER IF EXISTS $DECLENCHEUR; CREATE TRIGGER $DECLENCHEUR BEFORE INSERT ON $TABLE FOR EACH ROW SET @attente = SLEEP($temps);")
    [ -z "$sortie" ] || { printf '%s\n' "$sortie" | sed 's/^/      /' >&2; consigner dimensionner "$temps" "$prefetch" ECHEC; fail "La base a refusé le déclencheur."; }
    local pose; pose=$(declencheur_actuel)
    case "$pose" in *"SLEEP($temps)"*) ok "déclencheur posé : $pose" ;;
        *) consigner dimensionner "$temps" "$prefetch" ECHEC; fail "Déclencheur non retrouvé après pose (lu : « ${pose:-rien} »)." ;;
    esac

    say "Prefetch : $prefetch message(s) d'avance par réplique"
    local avant; avant=$(prefetch_actuel)
    if [ "$avant" = "$prefetch" ]; then
        say "déjà en place, pas de redémarrage"
    else
        kubectl set env deploy/"$DEPLOY" -n "$NS" "$ENV_PREFETCH=$prefetch" >/dev/null \
            || { consigner dimensionner "$temps" "$prefetch" ECHEC; fail "kubectl set env a échoué."; }
        say "redémarrage roulant des répliques (nouveaux pods, donc nouveaux nœuds dans le graphe — d'où « avant la référence »)…"
        # Trois services Java qui redémarrent l'un après l'autre : compter
        # jusqu'à dix minutes, et regarder l'état réel avant de conclure.
        kubectl rollout status deploy/"$DEPLOY" -n "$NS" --timeout=600s >/dev/null 2>&1 \
            || repliques_pretes \
            || { consigner dimensionner "$temps" "$prefetch" ECHEC; fail "Les répliques ne sont pas revenues en 10 min :  kubectl get pods -n $NS -l app=$DEPLOY"; }
    fi
    consigner dimensionner "$temps" "$prefetch" ok
    ok "consommateur dimensionné — à conserver tel quel pour toutes les campagnes"
    echo
    etat_app
}

etat_app() {
    local pose; pose=$(declencheur_actuel)
    local pf; pf=$(prefetch_actuel)
    local repl; repl=$(kubectl get deploy "$DEPLOY" -n "$NS" -o jsonpath='{.status.readyReplicas}/{.spec.replicas}' 2>/dev/null)
    echo "  consommateur : $DEPLOY ($repl répliques prêtes)"
    if [ -n "$pose" ]; then
        local s; s=$(printf '%s' "$pose" | grep -oP 'SLEEP\(\K[0-9.]+')
        echo "  temps de service : ${s:-?} s par message   (déclencheur $DB.$TABLE.$DECLENCHEUR)"
    else
        echo "  temps de service : aucun   (pas de déclencheur — 6 ms par message, marge × 1000)"
    fi
    echo "  prefetch : ${pf:-250 (défaut du courtier)}"
    return 0
}

retirer_app() {
    say "Retrait du déclencheur…"
    local sortie; sortie=$(sql "DROP TRIGGER IF EXISTS $DECLENCHEUR;")
    [ -z "$sortie" ] && ok "déclencheur retiré" || { printf '%s\n' "$sortie" | sed 's/^/      /' >&2; warn "la base a répondu quelque chose"; }
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
    *) echo "Usage: $0 {dimensionner --temps <s> [--prefetch <n>]|etat|retirer}" >&2; exit 2 ;;
esac
