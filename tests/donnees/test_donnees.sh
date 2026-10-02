#!/bin/bash
# ==============================================================================
#  tests/donnees/test_donnees.sh — etat --brut, redemarrer-reservation, et le reste inchangé
# ==============================================================================
#
#  Aucun accès au cluster : un FAUX kubectl, placé en tête du PATH (vérifié
#  par « command -v kubectl » avant chaque lancement), joue la base et les
#  déploiements. Il note chaque commande reçue, une par ligne.
#
#  Chaque lancement travaille dans un dossier temporaire avec une copie du
#  script et de mysql.sh (pas de journal.sh, sauf pour le cas qui le vérifie) :
#  le registre (journaux/donnees.tsv) y tombe aussi, rien n'est écrit ailleurs.
#
#  Pour « rien d'autre ne change », l'ORIGINAL (dépôt, lu seulement) et le
#  script du chantier sont lancés côte à côte avec le même faux kubectl : même
#  sortie, même code, mêmes commandes envoyées, même registre (sans l'instant).
#
#  Le faux se pilote par des variables :
#      FAUX_<table>      nombre de lignes de la table (défaut 0), ou « erreur »
#      FAUX_INJOIGNABLE  non vide : l'API ne répond plus (ni pods, ni exec, ni get)
#      FAUX_ECHEC        « restart:<deploy> status:<deploy> … » : ces appels échouent
#      FAUX_CPU          limite CPU de ts-order-service (défaut 500m)
#      FAUX_TAS          valeur de _JAVA_OPTIONS (défaut vide)
#
#  Usage :  bash tests/donnees/test_donnees.sh      (0 si tout passe)
# ==============================================================================
set -uo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHANTIER="$(cd "$ICI/../.." && pwd)"
ORIGINAL="$HOME/autodeploy_k8s-phases/apps/donnees.sh"
NEUF="$CHANTIER/apps/donnees.sh"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/test_donnees.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

ECHECS=0
NB=0

[ -f "$ORIGINAL" ] || { echo "Original introuvable : $ORIGINAL" >&2; exit 1; }

# ------------------------------------------------------------------------------
# Le faux kubectl
# ------------------------------------------------------------------------------
mkdir -p "$TMP/bin"
cat > "$TMP/bin/kubectl" <<'FAUX'
#!/bin/bash
E="$FAUX_ETAT"
# Une commande par ligne (le script sh -c de mysql.sh tient sur plusieurs).
{ printf '%s' "$*" | tr '\n' ' '; echo; } >> "$E/appels.log"
injoignable() { echo "Unable to connect to the server: dial tcp 10.0.0.10:6443: i/o timeout" >&2; exit 1; }
echoue() { local x; for x in ${FAUX_ECHEC:-}; do [ "$x" = "$1" ] && return 0; done; return 1; }

case "${1:-} ${2:-}" in
"get pods")
    [ -z "${FAUX_INJOIGNABLE:-}" ] || injoignable
    echo "tsdb-mysql-0"; exit 0 ;;
"get deploy")
    [ -z "${FAUX_INJOIGNABLE:-}" ] || injoignable
    case "$*" in
        *limits.cpu*)    printf '%s' "${FAUX_CPU:-500m}" ;;
        *_JAVA_OPTIONS*) printf '%s' "${FAUX_TAS:-}" ;;
        *) echo "NAME READY UP-TO-DATE AVAILABLE AGE"; echo "$3 1/1 1 1 3d" ;;
    esac
    exit 0 ;;
"rollout restart"|"rollout status")
    d="${3#deploy/}"
    [ -z "${FAUX_INJOIGNABLE:-}" ] || injoignable
    if echoue "$2:$d"; then
        echo "error: timed out waiting for the condition on deployments/$d" >&2; exit 1
    fi
    echo "deployment.apps/$d $2 ok"; exit 0 ;;
"set env"|"set resources")
    [ -z "${FAUX_INJOIGNABLE:-}" ] || injoignable
    echo "deployment.apps/${3#deploy/} updated"; exit 0 ;;
esac

if [ "${1:-}" = exec ]; then
    [ -z "${FAUX_INJOIGNABLE:-}" ] || injoignable
    req="${!#}"                       # la requête : dernier argument de sql()
    case "$req" in
        "SELECT COUNT(*) FROM "*)
            t="${req#SELECT COUNT(\*) FROM }"; t="${t%;}"
            var="FAUX_$t"; v="${!var:-0}"
            if [ "$v" = erreur ]; then
                echo "ERROR 1146 (42S02) at line 1: Table 'ts.$t' doesn't exist"
            else
                echo "$v"
            fi ;;
        "SELECT CONCAT"*) echo "42 sur G1234 le 2026-10-01" ;;
        TRUNCATE*) ;;                   # la base accepte, sans rien dire
        *) echo "$*" >> "$E/inattendus.log"; exit 1 ;;
    esac
    exit 0
fi
echo "$*" >> "$E/inattendus.log"
exit 1
FAUX
chmod +x "$TMP/bin/kubectl"

# ------------------------------------------------------------------------------
# Outils
# ------------------------------------------------------------------------------
# lancer <dossier> <script> [args…] — les variables FAUX_*/DONNEES_* passent par l'environnement
lancer() {
    local d="$1" src="$2"; shift 2
    mkdir -p "$d/apps" "$d/etat"
    cp "$src" "$d/apps/donnees.sh"
    cp "$CHANTIER/apps/mysql.sh" "$d/apps/mysql.sh"
    : > "$d/etat/appels.log"
    (
        export PATH="$TMP/bin:$PATH" FAUX_ETAT="$d/etat"
        [ "$(command -v kubectl)" = "$TMP/bin/kubectl" ] || { echo "FAUX kubectl pas en tête du PATH" >&2; exit 99; }
        cd "$d" && bash "$d/apps/donnees.sh" "$@" > "$d/out" 2> "$d/err"
    )
    echo $? > "$d/code"
    # Même depuis un sous-shell (« $(memes …) »), l'arrêt se voit : verdict lit ce fichier.
    [ "$(cat "$d/code")" != 99 ] || { : > "$TMP/ARRET"; echo "ARRÊT : le faux kubectl n'est pas celui qu'on appelle." >&2; exit 1; }
}

code()     { cat "$1/code"; }
registre() { [ -f "$1/journaux/donnees.tsv" ] && cut -f2- "$1/journaux/donnees.tsv"; }   # sans l'instant
rollouts() { grep '^rollout ' "$1/etat/appels.log"; }

verdict() {   # <nom du cas> <liste des problèmes, vide si aucun>
    [ ! -f "$TMP/ARRET" ] || { echo "  ARRÊT  le faux kubectl n'était pas en tête du PATH : aucun résultat n'est sûr."; exit 1; }
    NB=$((NB + 1))
    if [ -z "$2" ]; then
        echo "  OK     $1"
    else
        echo "  ÉCHEC  $1"
        printf '%s\n' "$2" | sed 's/^/           - /'
        ECHECS=$((ECHECS + 1))
    fi
}

# memes <cas> <args…> : l'original et le chantier, côte à côte → problèmes s'ils diffèrent
memes() {
    local c="$1"; shift
    local o="$TMP/$c-orig" n="$TMP/$c-neuf" pb="" f
    lancer "$o" "$ORIGINAL" "$@"
    lancer "$n" "$NEUF" "$@"
    [ "$(code "$o")" = "$(code "$n")" ] || pb+="code : original $(code "$o"), chantier $(code "$n")"$'\n'
    for f in out err etat/appels.log; do
        diff -q "$o/$f" "$n/$f" >/dev/null || pb+="$f diffère : $(diff "$o/$f" "$n/$f" | head -6 | tr '\n' '|')"$'\n'
    done
    [ "$(registre "$o")" = "$(registre "$n")" ] || pb+="registre diffère"$'\n'
    [ ! -s "$o/etat/inattendus.log" ] && [ ! -s "$n/etat/inattendus.log" ] || pb+="appels inattendus du faux kubectl"$'\n'
    printf '%s' "$pb"
}

echo "== tests/donnees/test_donnees.sh"
echo "   faux kubectl : $(PATH="$TMP/bin:$PATH" command -v kubectl)"

# ------------------------------------------------------------------------------
# (a) etat --brut, base OK : une ligne exacte, code 0, registre inchangé
# ------------------------------------------------------------------------------
d="$TMP/a"; pb=""
mkdir -p "$d/journaux"; printf '# entete\tx\ty\tz\nancien\tpurger\t3\tok\n' > "$d/journaux/donnees.tsv"
cp "$d/journaux/donnees.tsv" "$TMP/a.registre.avant"
FAUX_orders=120 FAUX_orders_other=7 FAUX_food_order=0 FAUX_delivery=33 lancer "$d" "$NEUF" etat --brut
[ "$(code "$d")" = 0 ] || pb+="code $(code "$d") au lieu de 0"$'\n'
[ "$(cat "$d/out")" = "orders=120 orders_other=7 food_order=0 delivery=33 total=160" ] || pb+="sortie : « $(cat "$d/out") »"$'\n'
[ "$(wc -l < "$d/out")" = 1 ] || pb+="$(wc -l < "$d/out") lignes sur la sortie au lieu d'une"$'\n'
[ ! -s "$d/err" ] || pb+="sortie d'erreur non vide : $(head -2 "$d/err")"$'\n'
cmp -s "$d/journaux/donnees.tsv" "$TMP/a.registre.avant" || pb+="le registre a changé"$'\n'
! grep -qE '^(rollout|set) ' "$d/etat/appels.log" || pb+="une commande qui écrit a été envoyée"$'\n'
verdict "(a) etat --brut, base OK : ligne exacte, code 0, registre inchangé" "$pb"

# (a') même chose avec le vrai journal.sh : JOURNAL_OFF doit couvrir « etat --brut »
d="$TMP/a2"; pb=""
mkdir -p "$d/apps"; cp "$CHANTIER/apps/journal.sh" "$d/apps/journal.sh"
FAUX_orders=5 lancer "$d" "$NEUF" etat --brut
[ "$(cat "$d/out")" = "orders=5 orders_other=0 food_order=0 delivery=0 total=5" ] || pb+="sortie : « $(tr '\n' '|' < "$d/out") »"$'\n'
[ "$(code "$d")" = 0 ] || pb+="code $(code "$d")"$'\n'
[ -z "$(ls "$d/journaux" 2>/dev/null)" ] || pb+="fichiers créés dans journaux/ : $(ls "$d/journaux" | tr '\n' ' ')"$'\n'
verdict "(a') etat --brut avec journal.sh : pas d'en-tête de journal, aucun fichier écrit" "$pb"

# ------------------------------------------------------------------------------
# (b) une table illisible : « ? », total=?, code 1, avertissement sur stderr
# ------------------------------------------------------------------------------
d="$TMP/b"; pb=""
FAUX_orders=120 FAUX_orders_other=erreur FAUX_food_order=2 FAUX_delivery=3 lancer "$d" "$NEUF" etat --brut
[ "$(code "$d")" = 1 ] || pb+="code $(code "$d") au lieu de 1"$'\n'
[ "$(cat "$d/out")" = "orders=120 orders_other=? food_order=2 delivery=3 total=?" ] || pb+="sortie : « $(cat "$d/out") »"$'\n'
grep -q "ATTENTION.*orders_other" "$d/err" || pb+="pas d'avertissement nommant la table sur stderr"$'\n'
[ ! -f "$d/journaux/donnees.tsv" ] || pb+="un registre a été écrit"$'\n'
verdict "(b) etat --brut, une table illisible : ?, total=?, code 1" "$pb"

# ------------------------------------------------------------------------------
# (c) base injoignable : tout « ? », code 1
# ------------------------------------------------------------------------------
d="$TMP/c"; pb=""
FAUX_INJOIGNABLE=1 lancer "$d" "$NEUF" etat --brut
[ "$(code "$d")" = 1 ] || pb+="code $(code "$d") au lieu de 1"$'\n'
[ "$(cat "$d/out")" = "orders=? orders_other=? food_order=? delivery=? total=?" ] || pb+="sortie : « $(cat "$d/out") »"$'\n'
[ -s "$d/err" ] || pb+="aucun avertissement sur stderr"$'\n'
verdict "(c) etat --brut, base injoignable : code 1" "$pb"

# ------------------------------------------------------------------------------
# (d) etat sans option : identique à l'original
# ------------------------------------------------------------------------------
pb="$(FAUX_orders=120 FAUX_orders_other=7 FAUX_food_order=0 FAUX_delivery=33 memes d1 etat)"
pb+="$(FAUX_orders=1 FAUX_orders_other=erreur FAUX_TAS=-Xmx1g FAUX_CPU=2 memes d2 etat)"
pb+="$(FAUX_INJOIGNABLE=1 memes d3 etat)"
pb+="$(FAUX_orders=9 memes d4)"                       # sans argument : etat aussi
verdict "(d) etat sans option : sortie, code, appels identiques à l'original (4 variantes)" "$pb"

# ------------------------------------------------------------------------------
# (e) redemarrer-reservation OK : security puis preserve, registre « ok », code 0
# ------------------------------------------------------------------------------
d="$TMP/e"; pb=""
lancer "$d" "$NEUF" redemarrer-reservation
[ "$(code "$d")" = 0 ] || pb+="code $(code "$d") au lieu de 0"$'\n'
attendu="rollout restart deploy/ts-security-service -n train-ticket
rollout status deploy/ts-security-service -n train-ticket --timeout=300s
rollout restart deploy/ts-preserve-service -n train-ticket
rollout status deploy/ts-preserve-service -n train-ticket --timeout=300s"
[ "$(cat "$d/etat/appels.log")" = "$attendu" ] || pb+="appels : $(tr '\n' '|' < "$d/etat/appels.log")"$'\n'
[ "$(registre "$d" | tail -1)" = "redemarrer-reservation	-	ok" ] || pb+="registre : $(registre "$d" | tail -1)"$'\n'
[ "$(registre "$d" | wc -l)" = 2 ] || pb+="registre : $(registre "$d" | wc -l) lignes au lieu de 2 (en-tête + 1)"$'\n'
verdict "(e) redemarrer-reservation OK : security puis preserve, registre ok, code 0" "$pb"

# (e') noms surchargeables par DONNEES_RESERVATION, ordre respecté
d="$TMP/e2"; pb=""
DONNEES_RESERVATION="svc-a svc-b svc-c" lancer "$d" "$NEUF" redemarrer-reservation
[ "$(code "$d")" = 0 ] || pb+="code $(code "$d")"$'\n'
[ "$(rollouts "$d" | awk '{print $2, $3}' | tr '\n' ' ')" = "restart deploy/svc-a status deploy/svc-a restart deploy/svc-b status deploy/svc-b restart deploy/svc-c status deploy/svc-c " ] \
    || pb+="appels : $(tr '\n' '|' < "$d/etat/appels.log")"$'\n'
verdict "(e') DONNEES_RESERVATION surcharge la liste, dans l'ordre" "$pb"

# ------------------------------------------------------------------------------
# (f) security ne revient pas : preserve jamais touché, code non nul, ECHEC consigné
# ------------------------------------------------------------------------------
for mode in status restart; do
    d="$TMP/f-$mode"; pb=""
    FAUX_ECHEC="$mode:ts-security-service" lancer "$d" "$NEUF" redemarrer-reservation
    [ "$(code "$d")" != 0 ] || pb+="code 0"$'\n'
    ! grep -q preserve "$d/etat/appels.log" || pb+="ts-preserve-service a été touché"$'\n'
    [ "$(registre "$d" | tail -1)" = "redemarrer-reservation	-	ECHEC" ] || pb+="registre : $(registre "$d" | tail -1)"$'\n'
    grep -q "kubectl get pods -n train-ticket -l app=ts-security-service" "$d/err" || pb+="pas de marche à suivre nommant security"$'\n'
    grep -q "relancer" "$d/err" || pb+="pas de « relancer » dans la marche à suivre"$'\n'
    grep -q "s'il y en a" "$d/err" || pb+="le message ne dit pas que les suivants n'ont pas été touchés"$'\n'
    verdict "(f) security ne revient pas ($mode échoue) : preserve intact, ECHEC, code $(code "$d")" "$pb"
done

# ------------------------------------------------------------------------------
# (g) preserve ne revient pas : code non nul, ECHEC
# ------------------------------------------------------------------------------
d="$TMP/g"; pb=""
FAUX_ECHEC="status:ts-preserve-service" lancer "$d" "$NEUF" redemarrer-reservation
[ "$(code "$d")" != 0 ] || pb+="code 0"$'\n'
[ "$(rollouts "$d" | wc -l)" = 4 ] || pb+="$(rollouts "$d" | wc -l) appels rollout au lieu de 4"$'\n'
[ "$(registre "$d" | tail -1)" = "redemarrer-reservation	-	ECHEC" ] || pb+="registre : $(registre "$d" | tail -1)"$'\n'
grep -q "app=ts-preserve-service" "$d/err" || pb+="la marche à suivre ne nomme pas preserve"$'\n'
! grep -q "après celui-là" "$d/err" || pb+="le message parle de services après preserve, qui est le dernier"$'\n'
verdict "(g) preserve ne revient pas : ECHEC, code $(code "$d")" "$pb"

# ------------------------------------------------------------------------------
# (k) liste vide ou mal écrite : refus AVANT tout kubectl, rien de consigné
# ------------------------------------------------------------------------------
for cas in espace tab saut joker majuscules; do
    d="$TMP/k-$cas"; pb=""
    case "$cas" in
        espace)      v=" " ;;
        tab)         v=$'\t' ;;
        saut)        v=$'\n' ;;
        joker)       v="ts-o*"; mkdir -p "$d"; : > "$d/ts-order-service" ;;   # un fichier qui ressemble au nom
        majuscules)  v="TS-Security-Service" ;;
    esac
    DONNEES_RESERVATION="$v" lancer "$d" "$NEUF" redemarrer-reservation
    [ "$(code "$d")" = 1 ] || pb+="code $(code "$d") au lieu de 1"$'\n'
    [ ! -s "$d/etat/appels.log" ] || pb+="kubectl appelé : $(tr '\n' '|' < "$d/etat/appels.log")"$'\n'
    [ ! -f "$d/journaux/donnees.tsv" ] || pb+="registre écrit : $(registre "$d" | tail -1)"$'\n'
    grep -q "ERREUR: DONNEES_RESERVATION" "$d/err" || pb+="pas d'erreur nommant DONNEES_RESERVATION"$'\n'
    verdict "(k) DONNEES_RESERVATION mal écrite ($cas) : refus, aucun kubectl, rien consigné" "$pb"
done

# (l) etat suivi d'une autre option : refus, rien sur la sortie, aucun kubectl
d="$TMP/l"; pb=""
lancer "$d" "$NEUF" etat --bru
[ "$(code "$d")" = 1 ] || pb+="code $(code "$d") au lieu de 1"$'\n'
[ ! -s "$d/out" ] || pb+="texte sur la sortie standard"$'\n'
[ ! -s "$d/etat/appels.log" ] || pb+="kubectl appelé"$'\n'
grep -q "Option inconnue : --bru" "$d/err" || pb+="pas d'erreur nommant l'option"$'\n'
verdict "(l) etat --bru (faute de frappe) : code 1, sortie standard vide" "$pb"

# ------------------------------------------------------------------------------
# (h) purger, purger --redemarrer, redemarrer (et le reste) : comme l'original
# ------------------------------------------------------------------------------
pb="$(FAUX_orders=300 FAUX_delivery=4 memes h1 purger)"
verdict "(h) purger : comme l'original" "$pb"
pb="$(FAUX_orders=300 FAUX_delivery=4 memes h2 purger --redemarrer)"
pb+="$(FAUX_orders=300 FAUX_ECHEC=status:ts-seat-service memes h3 purger --redemarrer)"
verdict "(h) purger --redemarrer (chaîne OK, puis seat bloqué) : comme l'original" "$pb"
pb="$(memes h4 redemarrer)"
pb+="$(FAUX_ECHEC=restart:ts-order-service memes h5 redemarrer)"
verdict "(h) redemarrer (OK, puis order en échec) : comme l'original" "$pb"
pb="$(memes h6 purger --nimporte)"
pb+="$(FAUX_CPU=500m memes h7 dimensionner)"
pb+="$(FAUX_CPU=2 FAUX_TAS=-Xmx200m memes h8 dimensionner --tas 1g)"
pb+="$(memes h9 tas-de-l-image)"
verdict "(h) en plus : purger --nimporte, dimensionner (×2), tas-de-l-image : comme l'original" "$pb"
pb=""
grep -q '^rollout restart deploy/ts-order-service' "$TMP/h2-neuf/etat/appels.log" || pb+="chaîne absente de purger --redemarrer"$'\n'
! grep -qE 'security|preserve' "$TMP"/h*-neuf/etat/appels.log || pb+="security ou preserve touché"$'\n'
verdict "(h) aucune de ces commandes ne touche security ni preserve" "$pb"

# ------------------------------------------------------------------------------
# (i) commande inconnue : code 2 et usage à jour
# ------------------------------------------------------------------------------
d="$TMP/i"; pb=""
lancer "$d" "$NEUF" nimporte
[ "$(code "$d")" = 2 ] || pb+="code $(code "$d") au lieu de 2"$'\n'
grep -q "etat \[--brut\]" "$d/err" || pb+="usage sans « etat [--brut] »"$'\n'
grep -q "|redemarrer-reservation|" "$d/err" || pb+="usage sans redemarrer-reservation"$'\n'
grep -q "une fois par cycle" "$d/err" || pb+="usage sans « quand » pour redemarrer-reservation"$'\n'
[ ! -s "$d/out" ] || pb+="texte sur la sortie standard"$'\n'
[ ! -s "$d/etat/appels.log" ] || pb+="kubectl appelé"$'\n'
verdict "(i) commande inconnue : code 2, usage à jour" "$pb"

# ------------------------------------------------------------------------------
# (j) le script ne lance jamais redemarrer-reservation de lui-même
# ------------------------------------------------------------------------------
appels="$(grep -n 'redemarrer_reservation' "$NEUF" | grep -v '^[0-9]*:redemarrer_reservation() {' | grep -vc 'redemarrer-reservation) redemarrer_reservation ;;')"
verdict "(j) redemarrer_reservation appelé seulement depuis le case" \
    "$([ "$appels" = 0 ] || echo "$appels appel(s) ailleurs : $(grep -n 'redemarrer_reservation' "$NEUF")")"

# ------------------------------------------------------------------------------
echo
if [ "$ECHECS" = 0 ]; then
    echo "== $NB/$NB cas OK"
    exit 0
fi
echo "== $ECHECS cas en ÉCHEC sur $NB"
exit 1
