#!/bin/bash
# ==============================================================================
#  tests/consommateur/test_verifier.sh — verifier, reposer, etat, dimensionner
# ==============================================================================
#
#  Aucun accès au cluster : un FAUX kubectl, placé en tête du PATH, joue
#  Chaos Mesh et le déploiement à partir d'un dossier d'état. Comme le vrai,
#  il ne pose le retard que sur les répliques vivantes AU MOMENT de la pose,
#  et l'oublie pour les pods recréés ensuite.
#
#  Les cas d'une panne consumer-slowdown en cours tournent deux fois : sous le nom
#  d'objet d'aujourd'hui (fault-consumer-slowdown) et sous l'ancien (panne-lenteur),
#  que consommateur.sh reconnaît encore (compat).
#
#  Chaque cas travaille dans un dossier temporaire avec une copie du script et
#  de mysql.sh (pas de journal.sh) : rien n'est écrit ailleurs.
#
#  Le faux kubectl note toute commande qui écrit (apply, delete, set, …) : le
#  test compare cette liste à celle attendue, pour qu'aucune ne passe inaperçue.
#
#  Usage :  bash tests/consommateur/test_verifier.sh      (0 si tout passe)
# ==============================================================================
set -uo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHANTIER="$(cd "$ICI/../.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/test_conso.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

NS=train-ticket
OBJ=consommateur-temps-de-service
PANNE_OBJ=fault-consumer-slowdown   # l'objet de la panne consumer-slowdown (panne.sh)
PANNE_ANCIEN=panne-lenteur          # son ancien nom (compat, à retirer après la collecte)
ECHECS=0
NB=0

# ------------------------------------------------------------------------------
# Le faux kubectl
# ------------------------------------------------------------------------------
#  $FAUX_ETAT/pods.tsv       nom <tab> machine <tab> phase <tab> date de suppression (- si aucune)
#  $FAUX_ETAT/nc/<objet>     un NetworkChaos et sa latence (« 140ms »)
#  $FAUX_ETAT/nc/<objet>.arret  l'objet est arrêté (échéance passée) : desiredPhase=Stop
#  $FAUX_ETAT/pnc/<pod>      ce que porte ce pod, une ligne par retard : « <ns>/<objet> 140ms »
#                            (plusieurs objets, ou deux fois le même, comme le vrai)
#  $FAUX_ETAT/prefetch       la variable de prefetch du déploiement (absente : rien)
#  $FAUX_ETAT/ignore         des pods que la pose ne touche pas : Chaos Mesh échoue, AllInjected faux
#  $FAUX_ETAT/neuf_apres_pose  des pods recréés juste après la pose : rien posé, AllInjected vrai
#  $FAUX_ETAT/apply_refuse   l'API refuse toute création (apply en échec)
#  $FAUX_ETAT/injoignable    l'API ne répond plus à aucune lecture
#  $FAUX_ETAT/ecritures.log  les commandes qui écrivent
#  $FAUX_ETAT/inattendus.log les appels que le faux ne sait pas jouer
mkdir -p "$TMP/bin"
cat > "$TMP/bin/kubectl" <<'FAUX'
#!/bin/bash
E="$FAUX_ETAT"
OBJ=consommateur-temps-de-service
DEPLOY=ts-delivery-service
echo "$*" >> "$E/appels.log"
verbe="${1:-}"; shift
ns="" out="" sel="" fs="" pos=() reste=()
while [ $# -gt 0 ]; do
    case "$1" in
        -n) ns="$2"; shift 2 ;;
        -o) out="$2"; shift 2 ;;
        -o*) out="${1#-o}"; shift ;;
        -l) sel="$2"; shift 2 ;;
        -c|-f) pos+=("$1" "$2"); shift 2 ;;
        --field-selector=*) fs="${1#*=}"; shift ;;
        --sort-by=*|--no-headers|--ignore-not-found|--timeout=*) shift ;;
        --) shift; reste=("$@"); break ;;
        *) pos+=("$1"); shift ;;
    esac
done
inattendu() { echo "$verbe ${pos[*]} | ns=$ns out=$out sel=$sel" >> "$E/inattendus.log"; exit 1; }
ecrit() { echo "$*" >> "$E/ecritures.log"; }
vivants() { awk -F'\t' '$3=="Running" && $4=="-" {print $1}' "$E/pods.tsv" | sort; }
dans() { grep -qx "$1" "$E/$2" 2>/dev/null; }   # <pod> <fichier> : le pod y est-il listé ?
sans_source() { for f in "$E"/pnc/*; do [ -f "$f" ] && { grep -v "^$1 " "$f" > "$f.tmp"; mv "$f.tmp" "$f"; }; done; }

if [ "$verbe" = get ] && [ -f "$E/injoignable" ]; then
    echo "Unable to connect to the server: dial tcp 10.0.0.10:6443: i/o timeout" >&2; exit 1
fi

case "$verbe" in
get)
    quoi="${pos[0]:-}"; nom="${pos[1]:-}"
    case "$quoi" in
    pods)
        case "$sel" in
            app=tsdb-mysql*) echo "tsdb-mysql-0"; exit 0 ;;
            "app=$DEPLOY") ;;
            *) inattendu ;;
        esac
        [ "$ns" = train-ticket ] || inattendu
        filtre='1'; [ "$fs" = "status.phase=Running" ] && filtre='$3=="Running"'
        case "$out" in
            custom-columns=:metadata.name,:spec.nodeName,:metadata.deletionTimestamp)
                sort "$E/pods.tsv" | awk -F'\t' "$filtre"' {print $1"   "$2"   "($4=="-" ? "<none>" : $4)}' ;;
            custom-columns=:metadata.name,:spec.nodeName)
                sort "$E/pods.tsv" | awk -F'\t' "$filtre"' {print $1"   "$2}' ;;
            "") sort "$E/pods.tsv" | awk -F'\t' "$filtre"' {print $1"   1/1   "($4=="-" ? $3 : "Terminating")"   0   5m"}' ;;
            *) inattendu ;;
        esac ;;
    networkchaos)
        [ -f "$E/nc/$nom" ] || { echo "Error from server (NotFound): networkchaos.chaos-mesh.org \"$nom\" not found" >&2; exit 1; }
        case "$out" in
            "") echo "$nom   5m" ;;
            *delay.latency*) echo -n "$(cat "$E/nc/$nom")" ;;
            *metadata.name*) echo -n "$nom" ;;
            *desiredPhase*) if [ -f "$E/nc/$nom.arret" ]; then echo -n Stop; else echo -n Run; fi ;;
            *AllInjected*)
                # Un pod choisi à la pose mais pas touché : Chaos Mesh le dit.
                if [ "$nom" = "$OBJ" ] && [ -s "$E/ignore" ]; then echo -n False; else echo -n True; fi ;;
            *) inattendu ;;
        esac ;;
    podnetworkchaos)
        [ -f "$E/pnc/$nom" ] || { echo "Error from server (NotFound): podnetworkchaos.chaos-mesh.org \"$nom\" not found" >&2; exit 1; }
        case "$out" in
            *'@.source=="'*'")].delay.latency}')
                # Comme jsonpath : toutes les valeurs de cette source, séparées d'une espace.
                src=$(sed 's/.*@\.source=="\([^"]*\)".*/\1/' <<< "$out")
                echo -n "$(awk -v s="$src" '$1==s {print $2}' "$E/pnc/$nom" | paste -sd' ')" ;;
            *) inattendu ;;
        esac ;;
    deploy)
        [ "$nom" = "$DEPLOY" ] || exit 1
        n=$(vivants | wc -l)
        case "$out" in
            "") echo "$DEPLOY   $n/3" ;;
            "jsonpath={.spec.replicas}") echo -n 3 ;;
            "jsonpath={.status.readyReplicas}"|"jsonpath={.status.updatedReplicas}") echo -n "$n" ;;
            "jsonpath={.status.readyReplicas}/{.spec.replicas}") echo -n "$n/3" ;;
            *SPRING_RABBITMQ_LISTENER_SIMPLE_PREFETCH*) [ -f "$E/prefetch" ] && echo -n "$(cat "$E/prefetch")" ;;
            *) inattendu ;;
        esac ;;
    crd) [ "$nom" = networkchaos.chaos-mesh.org ] || inattendu ;;
    svc) echo "10.96.0.20   map[app:tsdb-mysql role:leader]" ;;
    *) inattendu ;;
    esac ;;
apply)
    yaml=$(cat); echo "$yaml" > "$E/dernier.yaml"
    if [ -f "$E/apply_refuse" ]; then
        echo "Error from server (InternalError): error when creating \"STDIN\": admission webhook refused" >&2; exit 1
    fi
    nom=$(awk '/^  name:/ {print $2; exit}' <<< "$yaml")
    lat=$(sed -n 's/^ *latency: "\(.*\)"/\1/p' <<< "$yaml")
    ecrit "apply networkchaos $nom $lat"
    echo "$lat" > "$E/nc/$nom"; rm -f "$E/nc/$nom.arret"
    # Comme Chaos Mesh : les cibles sont choisies MAINTENANT, parmi les vivants.
    sans_source "train-ticket/$nom"
    for p in $(vivants); do
        dans "$p" ignore || dans "$p" neuf_apres_pose || echo "train-ticket/$nom $lat" >> "$E/pnc/$p"
    done ;;
delete)
    ecrit "delete ${pos[*]}"
    [ "${pos[0]}" = networkchaos ] || exit 0
    rm -f "$E/nc/${pos[1]}" "$E/nc/${pos[1]}.arret"
    sans_source "train-ticket/${pos[1]}"
    exit 0 ;;
set)
    ecrit "set ${pos[*]}"
    case "${pos[2]:-}" in
        *-) rm -f "$E/prefetch" ;;
        *=*) echo "${pos[2]#*=}" > "$E/prefetch" ;;
    esac
    # Redémarrage roulant : de nouveaux pods, sans le retard.
    awk -F'\t' 'BEGIN{OFS="\t"} $3=="Running" && $4=="-" {$1=$1"-neuf"} {print}' "$E/pods.tsv" > "$E/pods.tmp"
    mv "$E/pods.tmp" "$E/pods.tsv" ;;
rollout)
    [ "${pos[0]:-}" = status ] || ecrit "rollout ${pos[*]}" ;;
exec)
    case "${reste[*]}" in *DROP*|*CREATE*|*INSERT*|*UPDATE*|*"DELETE "*) ecrit "exec sql ${reste[*]: -1}" ;; esac
    exit 0 ;;
*)
    ecrit "$verbe ${pos[*]}"; inattendu ;;
esac
FAUX
# Les attentes de Chaos Mesh (60 s) ne doivent pas ralentir le test.
printf '#!/bin/bash\nexit 0\n' > "$TMP/bin/sleep"; chmod +x "$TMP/bin/sleep"
chmod +x "$TMP/bin/kubectl"
export PATH="$TMP/bin:$PATH"

if [ "$(command -v kubectl)" != "$TMP/bin/kubectl" ] || [ "$(command -v sleep)" != "$TMP/bin/sleep" ]; then
    echo "ÉCHEC : kubectl n'est pas le faux ($(command -v kubectl)) — arrêt, rien n'est lancé"
    exit 1
fi
echo "kubectl utilisé : $(command -v kubectl) (le faux)"

# ------------------------------------------------------------------------------
# Outils des cas
# ------------------------------------------------------------------------------
# nouveau_cas <nom> — dossier neuf : copie du script et de mysql.sh, état vide
nouveau_cas() {
    CAS="$1"; NB=$((NB + 1))
    W="$TMP/$NB"; mkdir -p "$W/apps" "$W/etat/nc" "$W/etat/pnc"
    cp "$CHANTIER/apps/consommateur.sh" "$CHANTIER/apps/mysql.sh" "$W/apps/"
    : > "$W/etat/pods.tsv"; : > "$W/etat/ecritures.log"; : > "$W/etat/inattendus.log"
    export FAUX_ETAT="$W/etat"
    PROBLEMES=""
}
pod()      { printf '%s\t%s\t%s\t%s\n' "$1" "$2" "${3:-Running}" "${4:--}" >> "$FAUX_ETAT/pods.tsv"; }
porte()    { echo "$NS/${3:-$OBJ} $2" >> "$FAUX_ETAT/pnc/$1"; }   # <pod> <retard> [objet]
objet()    { echo "$2" > "$FAUX_ETAT/nc/$1"; }
arreter()  { : > "$FAUX_ETAT/nc/$1.arret"; }
pnc_de()   { awk -v s="$NS/${2:-$OBJ}" '$1==s {print $2}' "$FAUX_ETAT/pnc/$1" 2>/dev/null | paste -sd' '; }   # <pod> [objet]

# lancer <commande…> — sortie dans $SORTIE, code dans $CODE
lancer() {
    SORTIE=$(cd "$W" && timeout 60 bash "$W/apps/consommateur.sh" "$@" 2>&1); CODE=$?
}
attendre_code() { [ "$CODE" = "$1" ] || PROBLEMES="$PROBLEMES\n    code $CODE, attendu $1"; }
contient()      { grep -qF -- "$1" <<< "$SORTIE" || PROBLEMES="$PROBLEMES\n    la sortie ne contient pas « $1 »"; }
ne_contient()   { grep -qF -- "$1" <<< "$SORTIE" && PROBLEMES="$PROBLEMES\n    la sortie contient « $1 »"; }
ecritures()     {   # les écritures attendues, une par argument, dans l'ordre
    local voulu; voulu=$(printf '%s\n' "$@" | sed '/^$/d')
    local vu; vu=$(cat "$FAUX_ETAT/ecritures.log")
    [ "$vu" = "$voulu" ] || PROBLEMES="$PROBLEMES\n    écritures reçues :\n$(sed 's/^/      /' <<< "${vu:-(aucune)}")\n    attendues :\n$(sed 's/^/      /' <<< "${voulu:-(aucune)}")"
}
verdict() {
    [ -s "$FAUX_ETAT/inattendus.log" ] && PROBLEMES="$PROBLEMES\n    appels non prévus :\n$(sed 's/^/      /' "$FAUX_ETAT/inattendus.log")"
    if [ -z "$PROBLEMES" ]; then
        echo "OK     $CAS"
    else
        echo "ÉCHEC  $CAS"; echo -e "$PROBLEMES"
        echo "    --- sortie du script ---"; sed 's/^/    | /' <<< "$SORTIE"
        ECHECS=$((ECHECS + 1))
    fi
}

trois_couvertes() {
    objet "$OBJ" 140ms
    pod ts-delivery-service-a worker1; porte ts-delivery-service-a 140ms
    pod ts-delivery-service-b worker2; porte ts-delivery-service-b 140ms
    pod ts-delivery-service-c worker3; porte ts-delivery-service-c 140ms
}
deux_neuves() {   # le 1/10 : une ancienne couverte, deux recréées sans retard
    objet "$OBJ" 140ms
    pod ts-delivery-service-a worker1; porte ts-delivery-service-a 140ms
    pod ts-delivery-service-x worker2
    pod ts-delivery-service-y worker3
}

# ------------------------------------------------------------------------------
# Les cas
# ------------------------------------------------------------------------------
nouveau_cas "(a) 3 répliques couvertes → verifier 0"
trois_couvertes
lancer verifier
attendre_code 0; contient "ts-delivery-service-c"; contient "(attendu : 140ms)"; ne_contient "MANQUE"; ecritures
verdict

nouveau_cas "(b) 2 pods neufs sans retard → verifier 1, avec leurs noms"
deux_neuves
lancer verifier
attendre_code 1
contient "ts-delivery-service-x"; contient "ts-delivery-service-y"
grep -q "ts-delivery-service-x .*rien   <- MANQUE" <<< "$SORTIE" || PROBLEMES="$PROBLEMES\n    x n'est pas marqué « rien <- MANQUE »"
grep -q "ts-delivery-service-a .*MANQUE" <<< "$SORTIE" && PROBLEMES="$PROBLEMES\n    a est marqué MANQUE à tort"
contient "consommateur.sh reposer"; ecritures
verdict

nouveau_cas "(c) un pod en Terminating sans retard + 3 vivants couverts → verifier 0"
trois_couvertes
pod ts-delivery-service-old worker1 Running 2026-10-01T08:00:00Z
lancer verifier
attendre_code 0; ne_contient "ts-delivery-service-old"; ecritures
verdict

nouveau_cas "(d) objet absent → verifier 1, reposer refuse"
pod ts-delivery-service-a worker1; pod ts-delivery-service-b worker2
lancer verifier
attendre_code 1; contient "consommateur.sh dimensionner --retard 140"
contient "(attendu : rien, il n'y a pas d'objet $OBJ)"
lancer reposer
attendre_code 1
contient "consommateur.sh dimensionner --retard 140"; ecritures
[ -e "$W/journaux/consommateur.tsv" ] && PROBLEMES="$PROBLEMES\n    un refus a été consigné comme une action"
verdict

for P in "$PANNE_OBJ" "$PANNE_ANCIEN"; do
    nouveau_cas "(e) [$P] la panne active + réglage → verifier 3, reposer 3 sans rien supprimer"
    trois_couvertes; objet $P 440ms   # le réglage pas encore retiré : le cas le plus risqué
    lancer verifier
    attendre_code 3; contient "panne consumer-slowdown en cours ($P remplace le réglage"
    lancer reposer
    attendre_code 3
    contient "panne consumer-slowdown en cours ($P)"; ecritures
    [ -f "$FAUX_ETAT/nc/$OBJ" ] && [ -f "$FAUX_ETAT/nc/$P" ] || PROBLEMES="$PROBLEMES\n    un objet a disparu"
    verdict

    nouveau_cas "(e2) [$P] la panne seule (réglage déjà retiré par panne.sh) → verifier 3, reposer 3"
    objet $P 440ms; pod ts-delivery-service-a worker1; porte ts-delivery-service-a 440ms $P
    lancer verifier
    attendre_code 3
    lancer reposer
    attendre_code 3
    contient "panne consumer-slowdown en cours"; ecritures
    [ -e "$W/journaux/consommateur.tsv" ] && PROBLEMES="$PROBLEMES\n    un refus a été consigné comme une action"
    verdict
done

nouveau_cas "(e3) compat : ancien nom ARRÊTÉ + nouveau nom actif → verifier 3 (le nouveau l'emporte)"
trois_couvertes; objet "$PANNE_ANCIEN" 440ms; arreter "$PANNE_ANCIEN"; objet "$PANNE_OBJ" 440ms
lancer verifier
attendre_code 3; contient "panne consumer-slowdown en cours ($PANNE_OBJ remplace le réglage"; ecritures
verdict

nouveau_cas "(e4) compat : nouveau nom ARRÊTÉ + ancien nom actif → verifier 3, le message nomme l'objet vu"
trois_couvertes; objet "$PANNE_OBJ" 440ms; arreter "$PANNE_OBJ"; objet "$PANNE_ANCIEN" 440ms
lancer verifier
attendre_code 3; contient "panne consumer-slowdown en cours ($PANNE_ANCIEN remplace le réglage"; ecritures
lancer reposer
attendre_code 3; contient "panne consumer-slowdown en cours ($PANNE_ANCIEN)"; ecritures
verdict

nouveau_cas "(f) reposer depuis (b) → objet recréé à 140ms, verifier 0, ni redémarrage ni set env"
deux_neuves; echo 1 > "$FAUX_ETAT/prefetch"
lancer reposer
attendre_code 0; contient "chaque réplique en marche de ts-delivery-service porte le retard"
contient "Nouvelle pose du retard de 140 ms"
ecritures "delete networkchaos $OBJ" "apply networkchaos $OBJ 140ms"
[ "$(cat "$FAUX_ETAT/nc/$OBJ" 2>/dev/null)" = 140ms ] || PROBLEMES="$PROBLEMES\n    l'objet n'est pas à 140ms"
for p in a x y; do
    [ "$(pnc_de ts-delivery-service-$p)" = 140ms ] || PROBLEMES="$PROBLEMES\n    $p sans retard (ou en double)"
done
grep -q "neuf" "$FAUX_ETAT/pods.tsv" && PROBLEMES="$PROBLEMES\n    des pods ont été recréés"
grep -qP "\treposer\t140\t1\tok$" "$W/journaux/consommateur.tsv" 2>/dev/null || PROBLEMES="$PROBLEMES\n    reposer absent du registre"
lancer verifier; attendre_code 0
verdict

nouveau_cas "(g) etat montre la couverture, donne le remède et rend 0"
deux_neuves
lancer etat
attendre_code 0
contient "ts-delivery-service-x"; contient "rien   <- MANQUE"; contient "→ des répliques en marche n'ont pas le bon retard"
contient "consommateur.sh reposer"; ecritures
verdict

for P in "$PANNE_OBJ" "$PANNE_ANCIEN"; do
    nouveau_cas "(g2) [$P] etat pendant une panne consumer-slowdown → le dit, sans « aucun », rend 0"
    objet $P 440ms; pod ts-delivery-service-a worker1
    lancer etat
    attendre_code 0; contient "panne consumer-slowdown en cours ($P remplace"; contient "celui de la panne consumer-slowdown ($P)"
    ne_contient "temps de service : aucun"; ne_contient "→"; ecritures
    verdict
done

nouveau_cas "(h) dimensionner sur (b), prefetch déjà en place → verifier = 0, couverture affichée une fois"
deux_neuves; echo 1 > "$FAUX_ETAT/prefetch"
lancer dimensionner --retard 140 --prefetch 1
attendre_code 0; contient "déjà en place, pas de redémarrage"; contient "porte le retard"
[ "$(grep -c "retard par réplique" <<< "$SORTIE")" = 1 ] || PROBLEMES="$PROBLEMES\n    la couverture n'est pas affichée une seule fois"
ecritures "delete networkchaos $OBJ" "apply networkchaos $OBJ 140ms"
grep -qP "\tdimensionner\t140\t1\tok$" "$W/journaux/consommateur.tsv" 2>/dev/null || PROBLEMES="$PROBLEMES\n    dimensionner ok absent du registre"
verdict

nouveau_cas "(i) aucune réplique en marche → verifier 1"
objet "$OBJ" 140ms
pod ts-delivery-service-old worker1 Running 2026-10-01T08:00:00Z; porte ts-delivery-service-old 140ms
pod ts-delivery-service-p worker2 Pending
lancer verifier
attendre_code 1; contient "aucune réplique de ts-delivery-service en marche"; ecritures
verdict

nouveau_cas "(j) dimensionner avec changement de prefetch → retard reposé sur les pods neufs, verifier 0"
trois_couvertes
lancer dimensionner --retard 140 --prefetch 1
attendre_code 0; contient "les répliques neuves n'ont pas le retard"
ecritures "delete networkchaos $OBJ" "apply networkchaos $OBJ 140ms" \
          "set env deploy/ts-delivery-service SPRING_RABBITMQ_LISTENER_SIMPLE_PREFETCH=1" \
          "delete networkchaos $OBJ" "apply networkchaos $OBJ 140ms"
for p in a b c; do
    [ "$(pnc_de ts-delivery-service-$p-neuf)" = 140ms ] || PROBLEMES="$PROBLEMES\n    $p-neuf sans retard"
done
verdict

nouveau_cas "(k) dimensionner, une réplique recréée juste après la pose (objet « appliqué ») → code 1, ECHEC"
deux_neuves; echo 1 > "$FAUX_ETAT/prefetch"; echo ts-delivery-service-y > "$FAUX_ETAT/neuf_apres_pose"
lancer dimensionner --retard 140 --prefetch 1
attendre_code 1; contient "PAS dimensionné"; contient "consommateur.sh reposer"
grep -q "ts-delivery-service-y .*rien   <- MANQUE" <<< "$SORTIE" || PROBLEMES="$PROBLEMES\n    y n'est pas marqué MANQUE"
grep -qP "\tdimensionner\t140\t1\tECHEC$" "$W/journaux/consommateur.tsv" 2>/dev/null || PROBLEMES="$PROBLEMES\n    ECHEC absent du registre"
ecritures "delete networkchaos $OBJ" "apply networkchaos $OBJ 140ms"
verdict

nouveau_cas "(k2) dimensionner, Chaos Mesh ne touche pas une réplique (AllInjected faux) → code 1, ECHEC"
deux_neuves; echo 1 > "$FAUX_ETAT/prefetch"; echo ts-delivery-service-y > "$FAUX_ETAT/ignore"
lancer dimensionner --retard 140 --prefetch 1
attendre_code 1; contient "Chaos Mesh n'a pas confirmé en 60 s"
grep -qP "\tdimensionner\t140\t1\tECHEC$" "$W/journaux/consommateur.tsv" 2>/dev/null || PROBLEMES="$PROBLEMES\n    ECHEC absent du registre"
ecritures "delete networkchaos $OBJ" "apply networkchaos $OBJ 140ms"
verdict

nouveau_cas "(l) retard posé à une autre valeur que l'objet → verifier 1, « AUTRE VALEUR »"
objet "$OBJ" 140ms
pod ts-delivery-service-a worker1; porte ts-delivery-service-a 140ms
pod ts-delivery-service-b worker2; porte ts-delivery-service-b 300ms
lancer verifier
attendre_code 1; contient "300ms   <- AUTRE VALEUR"; contient "n'ont pas le bon retard"; ecritures
verdict

nouveau_cas "(l2) même valeur posée deux fois sur une réplique → couverte ; deux valeurs → AUTRE VALEUR"
trois_couvertes; porte ts-delivery-service-a 140ms
lancer verifier
attendre_code 0
porte ts-delivery-service-b 300ms
lancer verifier
attendre_code 1; contient "140ms 300ms   <- AUTRE VALEUR"; ecritures
verdict

for P in "$PANNE_OBJ" "$PANNE_ANCIEN"; do
    nouveau_cas "(m) [$P] panne.sh retirer : $P active, réglage absent, dimensionner --retard 140 → 0"
    objet $P 580ms; echo 1 > "$FAUX_ETAT/prefetch"
    for p in a b c; do pod ts-delivery-service-$p worker1; porte ts-delivery-service-$p 580ms $P; done
    lancer dimensionner --retard 140
    attendre_code 0; contient "porte le retard"; ne_contient "PAS dimensionné"
    ecritures "delete networkchaos $OBJ" "apply networkchaos $OBJ 140ms"
    for p in a b c; do
        [ "$(pnc_de ts-delivery-service-$p)" = 140ms ] || PROBLEMES="$PROBLEMES\n    $p sans le réglage"
        [ "$(pnc_de ts-delivery-service-$p $P)" = 580ms ] || PROBLEMES="$PROBLEMES\n    $p a perdu la panne"
    done
    [ -f "$FAUX_ETAT/nc/$P" ] || PROBLEMES="$PROBLEMES\n    $P a disparu"
    grep -qP "\tdimensionner\t140\t1\tok$" "$W/journaux/consommateur.tsv" 2>/dev/null || PROBLEMES="$PROBLEMES\n    dimensionner ok absent du registre"
    verdict

    nouveau_cas "(m2) [$P] même cas, une réplique reste sans réglage → 1, ECHEC, remède = dimensionner (reposer est refusé)"
    objet $P 580ms; echo 1 > "$FAUX_ETAT/prefetch"
    for p in a b c; do pod ts-delivery-service-$p worker1; porte ts-delivery-service-$p 580ms $P; done
    echo ts-delivery-service-c > "$FAUX_ETAT/neuf_apres_pose"
    lancer dimensionner --retard 140
    attendre_code 1; contient "PAS dimensionné"; contient "à reprendre :  consommateur.sh dimensionner --retard 140"
    grep -qP "\tdimensionner\t140\t1\tECHEC$" "$W/journaux/consommateur.tsv" 2>/dev/null || PROBLEMES="$PROBLEMES\n    ECHEC absent du registre"
    ecritures "delete networkchaos $OBJ" "apply networkchaos $OBJ 140ms"
    verdict

    nouveau_cas "(n) [$P] la panne ARRÊTÉE (minuteur mort), réglage absent → verifier 1 « panne.sh retirer », reposer refuse"
    objet $P 580ms; arreter $P
    pod ts-delivery-service-a worker1; pod ts-delivery-service-b worker2
    lancer verifier
    attendre_code 1; contient "$P est arrêtée mais toujours là"; contient "$P arrêtée mais pas retirée, le réglage"
    contient "panne.sh retirer"; ne_contient "c'est normal"
    lancer reposer
    attendre_code 1; contient "$P arrêtée mais pas retirée, rien n'est touché"; contient "panne.sh retirer"
    lancer etat
    attendre_code 0; contient "panne.sh retirer"; contient "temps de service : aucun"
    ecritures
    verdict

    nouveau_cas "(n2) [$P] la panne arrêtée mais réglage posé partout → verifier 0 (le réglage est là), le signale"
    trois_couvertes; objet $P 580ms; arreter $P
    lancer verifier
    attendre_code 0; contient "arrêtée mais toujours là"; ecritures
    verdict
done

nouveau_cas "(o) apply refusé pendant reposer → objet perdu dit avec SA valeur et le prefetch, ECHEC"
objet "$OBJ" 150ms; echo 2 > "$FAUX_ETAT/prefetch"
pod ts-delivery-service-a worker1; porte ts-delivery-service-a 150ms
pod ts-delivery-service-x worker2
: > "$FAUX_ETAT/apply_refuse"
lancer reposer
attendre_code 1
contient "PAS recréé (valeur perdue : 150 ms)"; contient "consommateur.sh dimensionner --retard 150 --prefetch 2"
ne_contient "n'a pas confirmé"; ne_contient "--retard 140"
ecritures "delete networkchaos $OBJ"
grep -qP "\treposer\t150\t2\tECHEC$" "$W/journaux/consommateur.tsv" 2>/dev/null || PROBLEMES="$PROBLEMES\n    ECHEC absent du registre"
verdict

nouveau_cas "(o2) reposer, Chaos Mesh ne confirme pas (objet recréé) → avertit, verifier 1, ECHEC"
deux_neuves; echo 1 > "$FAUX_ETAT/prefetch"; echo ts-delivery-service-y > "$FAUX_ETAT/ignore"
lancer reposer
attendre_code 1; contient "n'a pas confirmé en 60 s"; ne_contient "PAS recréé"
grep -q "ts-delivery-service-y .*rien   <- MANQUE" <<< "$SORTIE" || PROBLEMES="$PROBLEMES\n    y n'est pas marqué MANQUE"
ecritures "delete networkchaos $OBJ" "apply networkchaos $OBJ 140ms"
grep -qP "\treposer\t140\t1\tECHEC$" "$W/journaux/consommateur.tsv" 2>/dev/null || PROBLEMES="$PROBLEMES\n    ECHEC absent du registre"
verdict

nouveau_cas "(q) API injoignable → verifier 1 « ne répond pas » (pas « aucun réglage »), reposer ne touche à rien"
trois_couvertes; : > "$FAUX_ETAT/injoignable"
lancer verifier
attendre_code 1; contient "ne répond pas"; ne_contient "dimensionner"
lancer reposer
attendre_code 1; contient "rien n'est touché"; ne_contient "dimensionner"
lancer etat
attendre_code 0; contient "ne répond pas"
ecritures
[ -e "$W/journaux/consommateur.tsv" ] && PROBLEMES="$PROBLEMES\n    un refus a été consigné comme une action"
verdict

echo
if [ "$ECHECS" -eq 0 ]; then echo "TOUS LES CAS PASSENT ($NB)"; exit 0; fi
echo "$ECHECS cas en ÉCHEC sur $NB"; exit 1
