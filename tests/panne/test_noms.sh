#!/bin/bash
# ==============================================================================
#  tests/panne/test_noms.sh — les noms anglais des pannes, et la transition
# ==============================================================================
#
#  Aucun accès au cluster, aucun ssh : un FAUX kubectl, placé en tête du PATH,
#  joue Kubernetes et Chaos Mesh à partir d'un dossier d'état, et note chaque
#  geste qui écrit (apply, delete, exec STOP/CONT). De faux loadgen.sh et
#  consommateur.sh, posés à côté de la copie de panne.sh, notent leurs appels.
#
#  Ce qui est vérifié :
#    - pour CHAQUE cause, sous son nom anglais puis sous son ancien nom (alias) :
#      « injecter » crée les objets aux NOUVEAUX noms, écrit la cause en anglais
#      dans pannes.tsv et panne.etat ; « retirer » supprime les nouveaux ET les
#      anciens noms ; « etat » ne voit ensuite plus rien ;
#    - un panne.etat écrit par l'ancienne copie (cause en français, objets aux
#      anciens noms) est lu, traduit et retiré correctement ;
#    - des objets aux anciens noms laissés sans panne.etat sont vus par « etat »
#      et nettoyés par « retirer » ;
#    - un nom inconnu est refusé avec la liste des noms anglais.
#
#  Chaque cas travaille dans un dossier temporaire (copie de panne.sh et de
#  mysql.sh, sans journal.sh) : rien n'est écrit ailleurs. Chaque appel est borné
#  (60 s), le test entier aussi (300 s).
#
#  Usage :  bash tests/panne/test_noms.sh      (0 si tout passe)
# ==============================================================================
set -uo pipefail

# Le test entier sous un plafond : rien ne peut pendre.
if [ -z "${TEST_NOMS_BORNE:-}" ]; then
    TEST_NOMS_BORNE=1 exec timeout -k 5 300 bash "$0" "$@"
fi

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHANTIER="$(cd "$ICI/../.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/test_noms.XXXXXX")"
VRAI_SLEEP="$(command -v sleep)"
# Les minuteurs posés par panne.sh (nohup … sleep) vivent sous ce chemin : tués à la fin.
trap 'pkill -f "$TMP" 2>/dev/null; rm -rf "$TMP"' EXIT

NS=train-ticket
ECHECS=0
NB=0

# ------------------------------------------------------------------------------
# Le faux kubectl
# ------------------------------------------------------------------------------
#  $FAUX_ETAT/obj/<sorte>__<espace>__<nom>   un objet (contenu : sa latence, ou « - »)
#  $FAUX_ETAT/gel/<pod>                      la réplique est gelée (SIGSTOP)
#  $FAUX_ETAT/ecritures.log                  apply / delete / exec STOP|CONT, une ligne chacun
#  $FAUX_ETAT/applique.yaml                  tout le YAML reçu par apply
#  $FAUX_ETAT/inattendus.log                 les appels que le faux ne sait pas jouer
#
#  Le cluster joué : répliques ts-delivery-service-a (workers1), -b (workers2),
#  -c (workers3) ; ts-order-1 sur workers1 ; la base tsdb-mysql-0 (leader, workers3),
#  -1, -2 ; quatre machines workers1..4 de 4 cœurs, un démon Chaos Mesh sur chacune.
mkdir -p "$TMP/bin"
cat > "$TMP/bin/kubectl" <<'FAUX'
#!/bin/bash
E="$FAUX_ETAT"; NS=train-ticket
echo "$*" >> "$E/appels.log"
verbe="${1:-}"; shift
ns="" out="" sel="" fs="" tous=0 ignore=0 pos=() reste=()
while [ $# -gt 0 ]; do
    case "$1" in
        -n) ns="$2"; shift 2 ;;
        -o) out="$2"; shift 2 ;;
        -l) sel="$2"; shift 2 ;;
        -A) tous=1; shift ;;
        -f) shift 2 ;;
        --field-selector) fs="$2"; shift 2 ;;
        --field-selector=*) fs="${1#*=}"; shift ;;
        --ignore-not-found) ignore=1; shift ;;
        --sort-by=*|--no-headers|--timeout=*|--dry-run=*) shift ;;
        --) shift; reste=("$@"); break ;;
        *) pos+=("$1"); shift ;;
    esac
done
inattendu() { echo "$verbe ${pos[*]} | ns=$ns out=$out sel=$sel fs=$fs" >> "$E/inattendus.log"; exit 1; }
ecrit() { echo "$*" >> "$E/ecritures.log"; }
objet() { echo "$E/obj/$1__$2__$3"; }          # <sorte> <espace> <nom>
noeud_du_filtre() { sed -n 's/.*spec\.nodeName=\([^,]*\).*/\1/p' <<< "$fs"; }
# nom machine adresse : les pods de l'espace applicatif
PODS="ts-delivery-service-a workers1 10.1.0.1
ts-delivery-service-b workers2 10.1.0.2
ts-delivery-service-c workers3 10.1.0.3
ts-order-1 workers1 10.1.0.4
tsdb-mysql-0 workers3 10.0.0.9
tsdb-mysql-1 workers2 10.0.0.10
tsdb-mysql-2 workers4 10.0.0.11"
CLIENTS="10.1.0.1 10.1.0.2 10.1.0.3 10.1.0.4"
un_pod() { awk -v p="$1" '$1 == p' <<< "$PODS"; }

get_un_pod() {   # <nom>
    local p="$1" ligne
    if [ "$ns" = "$NS" ]; then
        ligne=$(un_pod "$p"); [ -n "$ligne" ] || { echo "Error from server (NotFound): pods \"$p\" not found" >&2; exit 1; }
        set -- $ligne
        case "$out" in
            "") echo "$1   1/1   Running   0   5d" ;;
            "jsonpath={.spec.nodeName}") printf '%s' "$2" ;;
            "jsonpath={.status.podIP}") printf '%s' "$3" ;;
            "jsonpath={.status.phase}") printf Running ;;
            "jsonpath={.metadata.labels.role}") [ "$1" = tsdb-mysql-0 ] && printf leader || printf follower ;;
            "jsonpath={.status.containerStatuses[0].containerID}") printf 'containerd://id-%s' "$1" ;;
            *) inattendu ;;
        esac
    else
        # Les pods des voisins : ceux que panne.sh (ou le test) a posés.
        [ -f "$(objet pod "$ns" "$p")" ] || { echo "Error from server (NotFound): pods \"$p\" not found" >&2; exit 1; }
        case "$out" in
            "") echo "$p   1/1   Running   0   1m" ;;
            "jsonpath={.status.phase}") printf Running ;;
            *) inattendu ;;
        esac
    fi
}

lister_pods() {
    local n; n=$(noeud_du_filtre)
    if [ "$tous" = 1 ]; then
        case "$sel" in
            app.kubernetes.io/component=controller-manager) echo "chaos-mesh   chaos-controller-manager-0   1/1   Running   0   5d" ;;
            app.kubernetes.io/component=chaos-daemon) echo "chaos-mesh   chaos-daemon-$n   1/1   Running   0   5d" ;;
            "") case "$out" in *requests.cpu*) printf '100m\n' ;; *) inattendu ;; esac ;;
            *) inattendu ;;
        esac
        return
    fi
    case "$ns" in
        chaos-mesh)
            case "$out" in
                custom-columns=:metadata.name) echo "chaos-daemon-$n" ;;
                custom-columns=:spec.nodeName) printf 'workers1\nworkers2\nworkers3\nworkers4\n' ;;
                *) inattendu ;;
            esac ;;
        "$NS")
            case "$sel" in
                app=ts-delivery-service)
                    awk '$1 ~ /^ts-delivery-service-/ {print $1 "   " $2}' <<< "$PODS" ;;
                "app notin (tsdb-mysql)")
                    awk '$1 !~ /^tsdb-mysql/ {print $3}' <<< "$PODS" ;;
                app=tsdb-mysql)
                    if [ -n "$n" ]; then awk -v n="$n" '$1 ~ /^tsdb-mysql/ && $2 == n {print $1}' <<< "$PODS"
                    elif [ "$out" = "custom-columns=:metadata.name,:status.podIP" ]; then awk '$1 ~ /^tsdb-mysql/ {print $1 "   " $3}' <<< "$PODS"
                    else awk '$1 ~ /^tsdb-mysql/ {print $1 "   2/2   Running   0   5d"}' <<< "$PODS"; fi ;;
                app=rabbitmq|app=ts-order-service) ;;
                "")
                    case "$out" in
                        custom-columns=:metadata.name) awk -v n="$n" '$2 == n {print $1}' <<< "$PODS" ;;
                        *containerID*) awk -v n="$n" '$2 == n {print "containerd://id-" $1}' <<< "$PODS" ;;
                        *) inattendu ;;
                    esac ;;
                *) inattendu ;;
            esac ;;
        *) inattendu ;;
    esac
}

# Ce que Chaos Mesh pose sur les pods, déduit des objets présents.
podnetworkchaos() {
    local nom="${pos[1]:-}" src o f
    src=$(sed -n 's/.*@\.source=="[^/]*\/\([^"]*\)".*/\1/p' <<< "$out")
    if [ -z "$nom" ]; then
        # La liste (retards de la panne network-delay) : « pod retard » par pod.
        f=$(objet networkchaos "$NS" "$src")
        awk '{print $1 " "}' <<< "$PODS"
        [ -f "$f" ] || return 0
        case "$src" in
            *-replica|*-replique) echo "ts-delivery-service-a $(cat "$f")" ;;
            *) echo "ts-order-1 $(cat "$f")" ;;
        esac
        return 0
    fi
    case "$out" in
        *failedMessage*|*generation*|*observedGeneration*) return 0 ;;
    esac
    f=$(objet networkchaos "$NS" "$src")
    [ -f "$f" ] && [ "$nom" = tsdb-mysql-0 ] || return 0
    case "$src" in *database-slowdown|panne-base) ;; *) return 0 ;; esac
    case "$out" in
        *delay.latency*) printf '%s' "$(cat "$f")" ;;
        *ipsets*) printf '%s' "$(for i in $CLIENTS; do printf '%s/32 ' "$i"; done | sed 's/ $//')" ;;
        *) inattendu ;;
    esac
}

case "$verbe" in
get)
    quoi="${pos[0]:-}"; nom="${pos[1]:-}"
    case "$quoi" in
        crd) exit 0 ;;
        nodes) printf 'workers1\nworkers2\nworkers3\nworkers4\n' ;;
        node)
            case "$nom" in workers[1-4]) ;; *) echo "Error from server (NotFound): nodes \"$nom\" not found" >&2; exit 1 ;; esac
            case "$out" in
                "") echo "$nom   Ready   <none>   9d   v1.30" ;;
                *capacity.cpu*|*allocatable.cpu*) printf 4 ;;
                *) inattendu ;;
            esac ;;
        endpoints) printf 10.0.0.9 ;;
        svc) echo "10.96.0.20   map[app:tsdb-mysql role:leader]" ;;
        pod|pods)
            if [ -n "$nom" ]; then get_un_pod "$nom"; else lister_pods; fi ;;
        networkchaos|stresschaos)
            f=$(objet "$quoi" "$ns" "$nom")
            [ -f "$f" ] || { echo "Error from server (NotFound): $quoi.chaos-mesh.org \"$nom\" not found" >&2; exit 1; }
            case "$out" in
                "") echo "$nom   1m" ;;
                *AllInjected*) printf True ;;
                *containerRecords*) printf 'c1 c2 c3' ;;
                *delay.latency*) printf '%s' "$(cat "$f")" ;;
                *) inattendu ;;
            esac ;;
        podnetworkchaos) podnetworkchaos ;;
        *) inattendu ;;
    esac ;;
top) exit 1 ;;   # pas de metrics-server : panne.sh choisit par ordre alphabétique
create)
    [ "${pos[0]:-}" = namespace ] || inattendu
    printf 'apiVersion: v1\nkind: Namespace\nmetadata:\n  name: %s\n' "${pos[1]}" ;;
apply)
    yaml=$(cat); printf '%s\n---\n' "$yaml" >> "$E/applique.yaml"
    printf '%s\n---\n' "$yaml" | awk -v E="$E" '
        function poser() {
            if (kind == "") return
            k = tolower(kind); n = (ns == "" ? "-" : ns)
            print (lat == "" ? "-" : lat) > (E "/obj/" k "__" n "__" name)
            print "apply " k " " n "/" name >> (E "/ecritures.log")
        }
        /^---$/ { poser(); kind = name = ns = lat = ""; next }
        /^kind: / && kind == "" { kind = $2 }
        /^  name: / && name == "" { name = $2 }
        /^  namespace: / && ns == "" { ns = $2 }
        /latency: "/ && lat == "" { lat = $2; gsub(/"/, "", lat) }' ;;
delete)
    sorte="${pos[0]}"; [ "$sorte" = pods ] && sorte=pod
    code=0
    for nom in "${pos[@]:1}"; do
        ecrit "delete $sorte $ns/$nom"
        f=$(objet "$sorte" "$ns" "$nom")
        if [ -f "$f" ]; then rm -f "$f"
        elif [ "$ignore" != 1 ]; then echo "Error from server (NotFound): $sorte \"$nom\" not found" >&2; code=1; fi
    done
    exit $code ;;
exec)
    [ "$ns" = chaos-mesh ] || inattendu
    script="${reste[2]:-}"; pod="${reste[4]#id-}"
    case "$script" in
        *"kill -STOP"*) mkdir -p "$E/gel"; : > "$E/gel/$pod"; ecrit "exec STOP $pod"; echo "4242 T" ;;
        *'kill -CONT $p'*) rm -f "$E/gel/$pod"; ecrit "exec CONT $pod" ;;
        *'/proc/$i/stat'*) if [ -f "$E/gel/$pod" ]; then echo "4242 T"; else echo "4242 S"; fi ;;
        *"jetes="*) echo "jetes=0 retrans=0 pods=2" ;;
        *dropped*) echo 0 ;;
        *) inattendu ;;
    esac ;;
*) inattendu ;;
esac
exit 0
FAUX
# Faux sleep : les attentes courtes passent tout de suite ; celle d'un minuteur
# (au moins une minute) devient un vrai sommeil, sous le chemin du test pour
# être tuée à la fin.
ln -s "$VRAI_SLEEP" "$TMP/vrai_sleep"
cat > "$TMP/bin/sleep" <<EOF
#!/bin/bash
s="\${1%%[!0-9]*}"
[ "\${s:-0}" -lt 60 ] || exec "$TMP/vrai_sleep" 600
exit 0
EOF
chmod +x "$TMP/bin/kubectl" "$TMP/bin/sleep"
export PATH="$TMP/bin:$PATH"

if [ "$(command -v kubectl)" != "$TMP/bin/kubectl" ] || [ "$(command -v sleep)" != "$TMP/bin/sleep" ]; then
    echo "ÉCHEC : kubectl ou sleep n'est pas le faux ($(command -v kubectl), $(command -v sleep)) — arrêt, rien n'est lancé"
    exit 1
fi
if command -v ssh >/dev/null 2>&1; then
    # panne.sh n'appelle jamais ssh ; un faux qui échoue le garantit quand même.
    printf '#!/bin/bash\necho "faux ssh : appel interdit dans ce test" >&2\nexit 255\n' > "$TMP/bin/ssh"; chmod +x "$TMP/bin/ssh"
fi
echo "kubectl utilisé : $(command -v kubectl) (le faux)"

# ------------------------------------------------------------------------------
# Outils des cas
# ------------------------------------------------------------------------------
# nouveau_cas <nom> — dossier neuf : panne.sh, mysql.sh, faux loadgen.sh et
# consommateur.sh ; le réglage de base (140 ms) est posé, comme sur le cluster.
nouveau_cas() {
    CAS="$1"; NB=$((NB + 1))
    W="$TMP/$NB"; mkdir -p "$W/apps" "$W/etat/obj" "$W/journaux"
    cp "$CHANTIER/apps/panne.sh" "$CHANTIER/apps/mysql.sh" "$W/apps/"
    cat > "$W/apps/loadgen.sh" <<'LG'
#!/bin/bash
case "$1" in
    voyageurs) echo 25 ;;
    scale) echo "loadgen scale $2 ${LG_ORIGINE:-}" >> "$FAUX_ETAT/ecritures.log" ;;
    *) exit 1 ;;
esac
LG
    cat > "$W/apps/consommateur.sh" <<'CO'
#!/bin/bash
echo "consommateur $*" >> "$FAUX_ETAT/ecritures.log"
CO
    : > "$W/etat/ecritures.log"; : > "$W/etat/inattendus.log"; : > "$W/etat/appels.log"
    export FAUX_ETAT="$W/etat"
    echo 140ms > "$FAUX_ETAT/obj/networkchaos__${NS}__consommateur-temps-de-service"
    PROBLEMES=""
}
poser() { echo "${4:-50ms}" > "$FAUX_ETAT/obj/$1__$2__$3"; }   # <sorte> <espace> <nom> [latence]
present() { [ -f "$FAUX_ETAT/obj/$1__$2__$3" ]; }

# lancer <commande…> — sortie dans $SORTIE, code dans $CODE ; ecritures depuis ce lancer dans $GESTES
lancer() {
    local avant; avant=$(wc -l < "$FAUX_ETAT/ecritures.log")
    SORTIE=$(cd "$W" && timeout -k 5 60 bash "$W/apps/panne.sh" "$@" 2>&1); CODE=$?
    GESTES=$(tail -n +"$((avant + 1))" "$FAUX_ETAT/ecritures.log")
}
probleme()      { PROBLEMES="$PROBLEMES\n    $*"; }
attendre_code() { [ "$CODE" = "$1" ] || probleme "code $CODE, attendu $1"; }
contient()      { grep -qF -- "$1" <<< "$SORTIE" || probleme "la sortie ne contient pas « $1 »"; }
ne_contient()   { grep -qF -- "$1" <<< "$SORTIE" && probleme "la sortie contient « $1 »"; }
geste()         { grep -qxF -- "$1" <<< "$GESTES" || probleme "geste manquant : « $1 »"; }
gestes_apply()  {   # les apply attendus, exactement (dans n'importe quel ordre)
    local vu voulu
    vu=$(grep '^apply ' <<< "$GESTES" | sort); voulu=$(printf '%s\n' "$@" | sed '/^$/d' | sort)
    [ "$vu" = "$voulu" ] || probleme "apply reçus :\n$(sed 's/^/      /' <<< "${vu:-(aucun)}")\n    attendus :\n$(sed 's/^/      /' <<< "${voulu:-(aucun)}")"
}
derniere_ligne() {   # <action> <cause> <resultat> — la dernière ligne de pannes.tsv
    local l; l=$(tail -1 "$W/journaux/pannes.tsv" 2>/dev/null)
    [ "$(cut -f3 <<< "$l")" = "$1" ] && [ "$(cut -f4 <<< "$l")" = "$2" ] && [ "$(cut -f8 <<< "$l")" = "$3" ] \
        || probleme "dernière ligne de pannes.tsv : « $(tr '\t' '|' <<< "$l") », attendu action $1, cause $2, resultat $3"
    [ "$(awk -F'\t' '{print NF}' <<< "$l")" = 8 ] || probleme "pannes.tsv : pas 8 champs"
}
etat_cause() {   # <cause> — panne.etat porte CAUSE='<cause>'
    grep -qx "CAUSE='$1'" "$W/journaux/panne.etat" 2>/dev/null \
        || probleme "panne.etat : $(grep '^CAUSE=' "$W/journaux/panne.etat" 2>/dev/null || echo absent), attendu CAUSE='$1'"
}
plus_d_etat()   { [ ! -e "$W/journaux/panne.etat" ] || probleme "panne.etat toujours là"; }
plus_d_objets() {   # seuls restent le réglage de base et les espaces de noms
    local r; r=$(ls "$FAUX_ETAT/obj" | grep -vE '^(namespace__|networkchaos__train-ticket__consommateur-temps-de-service$)')
    [ -z "$r" ] || probleme "objets restés : $(paste -sd' ' <<< "$r")"
}
anciens_absents_du_yaml() {
    if grep -nE 'panne-(lenteur|hote|base|reseau|leurre)|voisin-(bruyant|leurre)|namespace: voisin$|panne: (charge|lenteur|blocage|hote|base|reseau)\b|@leurre' \
            "$FAUX_ETAT/applique.yaml" 2>/dev/null; then
        probleme "un ancien nom dans le YAML appliqué (ci-dessus)"
    fi
}
verdict() {
    [ -s "$FAUX_ETAT/inattendus.log" ] && probleme "appels non prévus par le faux :\n$(sed 's/^/      /' "$FAUX_ETAT/inattendus.log")"
    if [ -z "$PROBLEMES" ]; then
        echo "OK     $CAS"
    else
        echo "ÉCHEC  $CAS"; echo -e "$PROBLEMES"
        echo "    --- dernière sortie de panne.sh ---"; sed 's/^/    | /' <<< "$SORTIE"
        ECHECS=$((ECHECS + 1))
    fi
}

# ------------------------------------------------------------------------------
# Chaque cause : ce qu'on lui passe, ce qu'elle doit poser, ce que retirer supprime
# ------------------------------------------------------------------------------
TT="$NS"; FN=fault-neighbors
options_de() {
    case "$1" in
        load-surge)     echo "--intensite 40" ;;
        noisy-neighbor) echo "--cible workers1" ;;
        network-delay)  echo "--intensite 50 --cible workers1:workers4" ;;
        *) echo "" ;;
    esac
}
applies_de() {
    case "$1" in
        consumer-slowdown) echo "apply networkchaos $TT/fault-consumer-slowdown" ;;
        noisy-neighbor)    printf '%s\n' "apply namespace -/$FN" "apply pod $FN/noisy-neighbor" "apply stresschaos $FN/fault-noisy-neighbor" ;;
        database-slowdown) echo "apply networkchaos $TT/fault-database-slowdown" ;;
        network-delay)     printf '%s\n' "apply namespace -/$FN" "apply pod $FN/decoy" "apply networkchaos $TT/fault-network-delay-replica" \
                                         "apply networkchaos $TT/fault-network-delay" "apply stresschaos $FN/fault-decoy" ;;
    esac
}
retraits_de() {   # les gestes de « retirer » : nouveaux noms, puis anciens
    case "$1" in
        load-surge)        echo "loadgen scale 25 retour_panne" ;;
        consumer-slowdown) printf '%s\n' "consommateur dimensionner --retard 140" "delete networkchaos $TT/fault-consumer-slowdown" \
                                         "delete networkchaos $TT/panne-lenteur" ;;
        noisy-neighbor)    printf '%s\n' "delete stresschaos $FN/fault-noisy-neighbor" "delete pod $FN/noisy-neighbor" \
                                         "delete stresschaos voisin/panne-hote" "delete pod voisin/voisin-bruyant" ;;
        replica-freeze)    echo "exec CONT ts-delivery-service-a" ;;
        database-slowdown) printf '%s\n' "delete networkchaos $TT/fault-database-slowdown" "delete networkchaos $TT/panne-base" ;;
        network-delay)     printf '%s\n' "delete stresschaos $FN/fault-decoy" "delete networkchaos $TT/fault-network-delay-replica" \
                                         "delete networkchaos $TT/fault-network-delay" "delete pod $FN/decoy" \
                                         "delete stresschaos voisin/panne-leurre" "delete networkchaos $TT/panne-reseau-replique" \
                                         "delete networkchaos $TT/panne-reseau" "delete pod voisin/voisin-leurre" ;;
    esac
}
label_de() {   # l'étiquette « panne: … » attendue dans le YAML (vide : pas d'objet Chaos Mesh)
    case "$1" in load-surge|replica-freeze) ;; *) echo "panne: $1" ;; esac
}

# ------------------------------------------------------------------------------
# Les cas
# ------------------------------------------------------------------------------
for paire in load-surge:charge consumer-slowdown:lenteur replica-freeze:blocage \
             noisy-neighbor:hote database-slowdown:base network-delay:reseau; do
    anglais="${paire%%:*}"; ancien="${paire#*:}"
    for nom in "$anglais" "$ancien"; do
        nouveau_cas "$anglais, donnée comme « $nom » : injecter, etat, retirer, etat"
        # shellcheck disable=SC2046
        lancer injecter "$nom" --duree 20 $(options_de "$anglais")
        attendre_code 0; contient "OK  injectée"
        if [ "$nom" = "$ancien" ]; then
            contient "$ancien → $anglais"
            [ "$(grep -c -- "$ancien → " <<< "$SORTIE")" = 1 ] || probleme "la ligne d'alias n'apparaît pas une seule fois"
        else
            ne_contient " → $anglais"
        fi
        contient "cause  : $anglais"
        derniere_ligne injection "$anglais" confirmee
        etat_cause "$anglais"
        mapfile -t attendus < <(applies_de "$anglais"); gestes_apply "${attendus[@]}"
        anciens_absents_du_yaml
        l=$(label_de "$anglais")
        [ -z "$l" ] || grep -q "labels: {.*$l }" "$FAUX_ETAT/applique.yaml" || probleme "étiquette « $l » absente du YAML"
        [ "$anglais" != replica-freeze ] || geste "exec STOP ts-delivery-service-a"
        [ "$anglais" != load-surge ] || geste "loadgen scale 40 panne"
        [ "$anglais" != network-delay ] || [ "$(tail -1 "$W/journaux/pannes.tsv" | cut -f6)" = "workers1@decoy:workers4" ] \
            || probleme "cible du registre : $(tail -1 "$W/journaux/pannes.tsv" | cut -f6), attendu workers1@decoy:workers4"

        lancer etat
        attendre_code 3; contient "Injection en cours : $anglais"

        lancer retirer
        attendre_code 0; contient "OK  retirée"
        while read -r g; do [ -n "$g" ] && geste "$g"; done < <(retraits_de "$anglais")
        derniere_ligne retrait "$anglais" ok
        plus_d_etat; plus_d_objets

        lancer etat
        attendre_code 0; contient "rien d'injecté, rien de résiduel"
        grep -qwE 'charge|lenteur|blocage|hote|base|reseau' <<< "$(cut -f4 "$W/journaux/pannes.tsv")" \
            && probleme "un ancien nom dans la colonne cause de pannes.tsv"
        verdict
    done
done

# ---------------------------------------------- un panne.etat de l'ancienne copie
# Le format n'a pas changé : CLE='valeur' ; seule la cause est en français, et
# les objets portent leurs anciens noms (dans l'espace « voisin » pour les voisins).
ancien_etat() {   # <cause française> <lignes KEY='valeur' en plus…>
    local c="$1"; shift
    { echo "CAUSE='$c'"; printf '%s\n' "$@"; echo "DEBUT='2026-10-01T10:00:00Z'"; echo "DUREE='20'"; } > "$W/journaux/panne.etat"
}
for paire in load-surge:charge consumer-slowdown:lenteur replica-freeze:blocage \
             noisy-neighbor:hote database-slowdown:base network-delay:reseau; do
    anglais="${paire%%:*}"; ancien="${paire#*:}"
    nouveau_cas "panne.etat ancien (CAUSE='$ancien') et objets aux anciens noms → etat le traduit, retirer lève tout"
    vu=""   # ce que « etat » doit dire de l'objet ancien
    case "$ancien" in
        charge)  ancien_etat charge "OUTIL='loadgen'" "CIBLE='locust'" "INTENSITE='50'" "RETOUR='25'" "MINUTEUR=''" ;;
        lenteur) ancien_etat lenteur "OUTIL='chaos-mesh'" "CIBLE='ts-delivery-service (3 répliques) -> app=tsdb-mysql'" \
                     "INTENSITE='300'" "RETARD_BASE='140'" "MINUTEUR=''"
                 rm -f "$FAUX_ETAT/obj/networkchaos__${NS}__consommateur-temps-de-service"
                 poser networkchaos "$NS" panne-lenteur 440ms; vu="Chaos Mesh : injectée" ;;
        blocage) ancien_etat blocage "OUTIL='sigstop'" "CIBLE='ts-delivery-service-a'" "POD='ts-delivery-service-a'" \
                     "HOTE='workers1'" "INTENSITE=''"
                 mkdir -p "$FAUX_ETAT/gel"; : > "$FAUX_ETAT/gel/ts-delivery-service-a"; vu="processus : gelé" ;;
        hote)    ancien_etat hote "OUTIL='chaos-mesh'" "CIBLE='workers1'" "HOTE='workers1'" "INTENSITE='2'"
                 poser stresschaos voisin panne-hote; poser pod voisin voisin-bruyant; vu="Chaos Mesh : injectée" ;;
        base)    ancien_etat base "OUTIL='chaos-mesh'" "CIBLE='tsdb-mysql-0@workers3 -> 4 clients'" "INTENSITE='75'"
                 poser networkchaos "$NS" panne-base 75ms; vu="Chaos Mesh : injectée" ;;
        reseau)  ancien_etat reseau "OUTIL='chaos-mesh'" "CIBLE='workers1@leurre:workers4'" "HOTE='workers1'" \
                     "LEURRE='workers4'" "INTENSITE='50'"
                 poser networkchaos "$NS" panne-reseau-replique; poser networkchaos "$NS" panne-reseau
                 poser stresschaos voisin panne-leurre; poser pod voisin voisin-leurre; vu="leurre sur workers4 : injecté" ;;
    esac
    lancer etat
    attendre_code 3; contient "Injection en cours : $anglais"; [ -z "$vu" ] || contient "$vu"
    [ "$ancien" != reseau ] || contient "pods retardés par fault-network-delay : 2"
    lancer retirer
    attendre_code 0; contient "Retrait de « $anglais »"; contient "OK  retirée"
    derniere_ligne retrait "$anglais" ok
    plus_d_etat; plus_d_objets
    case "$ancien" in
        charge)  geste "loadgen scale 25 retour_panne" ;;
        lenteur) geste "consommateur dimensionner --retard 140"; geste "delete networkchaos $NS/panne-lenteur" ;;
        blocage) geste "exec CONT ts-delivery-service-a" ;;
        hote)    geste "delete stresschaos voisin/panne-hote"; geste "delete pod voisin/voisin-bruyant" ;;
        base)    geste "delete networkchaos $NS/panne-base" ;;
        reseau)  geste "delete networkchaos $NS/panne-reseau-replique"; geste "delete networkchaos $NS/panne-reseau"
                 geste "delete stresschaos voisin/panne-leurre"; geste "delete pod voisin/voisin-leurre" ;;
    esac
    lancer etat
    attendre_code 0; contient "rien d'injecté, rien de résiduel"
    verdict
done

# ---------------------------------------------- des restes aux anciens noms, sans panne.etat
nouveau_cas "objets aux anciens noms sans panne.etat → etat les signale (code 3), retirer les nettoie"
poser networkchaos "$NS" panne-lenteur 440ms; poser networkchaos "$NS" panne-base 75ms
poser stresschaos voisin panne-hote; poser pod voisin voisin-bruyant
poser networkchaos "$NS" panne-reseau-replique; poser networkchaos "$NS" panne-reseau
poser stresschaos voisin panne-leurre; poser pod voisin voisin-leurre
lancer etat
attendre_code 3
for o in "networkchaos/panne-lenteur ($NS, ancien nom)" "networkchaos/panne-base ($NS, ancien nom)" \
         "stresschaos/panne-hote (voisin, ancien nom)" "pod/voisin-bruyant (voisin, ancien nom)" \
         "networkchaos/panne-reseau-replique ($NS, ancien nom)" "networkchaos/panne-reseau ($NS, ancien nom)" \
         "stresschaos/panne-leurre (voisin, ancien nom)" "pod/voisin-leurre (voisin, ancien nom)"; do
    contient "reste : $o"
done
contient "retard de fault-database-slowdown"   # l'ancien objet base retarde encore la base
lancer retirer
attendre_code 0; contient "OK  nettoyé"; contient "objets aux anciens noms supprimés"; plus_d_objets
[ -e "$W/journaux/pannes.tsv" ] && probleme "un nettoyage sans panne.etat a écrit au registre"
lancer etat
attendre_code 0; contient "rien d'injecté, rien de résiduel"
verdict

nouveau_cas "objets aux NOUVEAUX noms sans panne.etat → etat les signale, retirer les nettoie"
poser networkchaos "$NS" fault-consumer-slowdown 440ms; poser stresschaos "$FN" fault-noisy-neighbor
poser pod "$FN" noisy-neighbor; poser stresschaos "$FN" fault-decoy; poser pod "$FN" decoy
lancer etat
attendre_code 3; contient "reste : networkchaos/fault-consumer-slowdown"; contient "reste : pod decoy"
contient "reste : stresschaos/fault-noisy-neighbor"
lancer retirer
attendre_code 0; contient "OK  nettoyé"; ne_contient "anciens noms"; plus_d_objets
verdict

# ---------------------------------------------- etat et temoin : l'objet ancien juste
nouveau_cas "panne.etat ancien (reseau), StressChaos panne-leurre absent → etat ne dit PAS le leurre injecté"
ancien_etat reseau "OUTIL='chaos-mesh'" "CIBLE='workers1@leurre:workers4'" "HOTE='workers1'" "LEURRE='workers4'" "INTENSITE='50'"
poser networkchaos "$NS" panne-reseau-replique; poser networkchaos "$NS" panne-reseau
lancer etat
attendre_code 3; contient "Injection en cours : network-delay"
contient "leurre sur workers4 : pas (ou plus) injecté"; ne_contient "leurre sur workers4 : injecté"
verdict

for o in fault-database-slowdown panne-base; do
    nouveau_cas "temoin court, $o posée (75ms) → le retard ET les 4 adresses sont lus"
    poser networkchaos "$NS" "$o" 75ms
    lancer temoin court
    attendre_code 0; contient "fault-database-slowdown posée : 75ms vers 4 adresses"
    verdict
done
nouveau_cas "temoin court, rien de posé → « rien vers 0 adresses »"
lancer temoin court
attendre_code 0; contient "fault-database-slowdown posée : rien vers 0 adresses"
verdict

# ---------------------------------------------- noms inconnus, verifier par alias
nouveau_cas "nom inconnu → refusé (injecter et verifier), avec la liste des noms anglais, rien d'écrit"
lancer injecter lenteurr --duree 20
attendre_code 1
contient "Cause inconnue « lenteurr » — load-surge, consumer-slowdown, replica-freeze, noisy-neighbor, database-slowdown ou network-delay"
lancer verifier consumer_slowdown
attendre_code 1; contient "Cause inconnue « consumer_slowdown »"; contient "load-surge, consumer-slowdown"
lancer injecter
attendre_code 1; contient "Cause inconnue «  »"
[ -e "$W/journaux/pannes.tsv" ] && probleme "un refus a été consigné"
[ -e "$W/journaux/panne.etat" ] && probleme "un refus a laissé un panne.etat"
[ -z "$(grep -v '^$' "$FAUX_ETAT/ecritures.log")" ] || probleme "un refus a écrit dans le cluster"
verdict

nouveau_cas "verifier charge → traduit en load-surge, prêt"
lancer verifier charge
attendre_code 0; contient "charge → load-surge"; contient "prêt pour « load-surge »"
lancer verifier load-surge
attendre_code 0; ne_contient "→"; contient "prêt pour « load-surge »"
verdict

nouveau_cas "verifier avec un panne.etat ancien → la cause en cours est dite en anglais"
ancien_etat lenteur "OUTIL='chaos-mesh'" "CIBLE='x'" "INTENSITE='300'" "RETARD_BASE='140'" "MINUTEUR=''"
lancer verifier load-surge
attendre_code 1; contient "une injection est déjà en cours (« consumer-slowdown »"
lancer injecter load-surge --duree 5
attendre_code 1; contient "Une injection est déjà en cours (« consumer-slowdown »"
verdict

echo
if [ "$ECHECS" -eq 0 ]; then echo "TOUS LES CAS PASSENT ($NB)"; exit 0; fi
echo "$ECHECS cas en ÉCHEC sur $NB"; exit 1
