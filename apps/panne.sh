#!/bin/bash
# ==============================================================================
#  apps/panne.sh — injecter une panne, la retirer, consigner qui, quand, avec quoi
# ==============================================================================
#
#  Quatre causes, un même symptôme : le tas de la file grossit. Ce script sait
#  provoquer chacune, la retirer, et écrire QUI a été touché, QUAND, AVEC QUOI.
#
#     charge     plus de voyageurs : on dépose plus vite qu'on ne retire
#                → loadgen.sh scale
#
#     lenteur    les répliques du consommateur mettent plus longtemps par message
#                → Chaos Mesh NetworkChaos : un retard sur ce que ces pods
#                  envoient à leur base de données, EN PLUS du retard de base
#                  posé par consommateur.sh (un seul objet à la fois sur ce
#                  chemin ; « retirer » repose le réglage de base)
#
#     hote       un voisin brûle tout le CPU de l'hôte qui porte UNE réplique
#                → un pod « voisin bruyant » posé sur cet hôte, dans son propre
#                  espace ; Chaos Mesh StressChaos y injecte la charge. Le voisin
#                  n'est pas dans l'espace applicatif : le graphe ne le voit pas,
#                  il ne voit que l'hôte qui souffre.
#
#     blocage    une seule réplique ne répond plus, sans être tuée
#                → SIGSTOP sur son processus Java
#
#  POURQUOI SIGSTOP ET PAS CHAOS MESH POUR LE BLOCAGE
#
#  Chaos Mesh ne sait pas geler un processus : son « pod-failure » le tue et le
#  remplace par un conteneur inerte — une autre panne (la connexion au courtier
#  tombe à l'instant, la mémoire est rendue). Un processus gelé garde sa
#  mémoire et ses connexions, et Kubernetes le croit vivant : les pods de
#  train-ticket n'ont pas de sonde de vivacité, et leur sonde de disponibilité
#  est un simple test TCP que le noyau réussit à la place du processus gelé.
#
#  CHAQUE INJECTION EXPIRE D'ELLE-MÊME
#
#  La durée est portée par l'injection, pas par celui qui la lance : Chaos Mesh
#  lève la sienne à l'échéance, la levée du gel est programmée dans le conteneur
#  gelé, le retour de charge par un minuteur sur le master. Un pilote qui meurt
#  ne laisse pas la panne derrière lui. « retirer » lève tout de suite ; sans
#  injection en cours, il nettoie ce qui aurait pu rester.
#
#  Usage (depuis le master) :
#      bash ~/autodeploy/apps/panne.sh verifier <cause>
#      bash ~/autodeploy/apps/panne.sh injecter <cause> [--duree <min>] [--intensite <n>] [--cible <x>]
#      bash ~/autodeploy/apps/panne.sh retirer
#      bash ~/autodeploy/apps/panne.sh etat
#      bash ~/autodeploy/apps/panne.sh temoin
#
#  --intensite, selon la cause :
#      charge     voyageurs                      (défaut : 2 × la charge en cours)
#      lenteur    millisecondes de retard EN PLUS du réglage de base (défaut : 300)
#      hote       cœurs réclamés par le voisin   (défaut : la moitié de l'hôte)
#      blocage    sans objet
#
#  --cible, selon la cause :
#      hote       nom du nœud  (défaut : le moins chargé des hôtes portant une réplique)
#      blocage    nom du pod   (défaut : la première réplique par ordre alphabétique)
#
#  Registre : journaux/pannes.tsv — une ligne par injection et par retrait.
#
#  Variables reconnues :
#      PANNE_NAMESPACE      (défaut: train-ticket)
#      PANNE_CONSOMMATEUR   (défaut: ts-delivery-service)  déploiement qui retire de la file
#      PANNE_FILE           (défaut: food_delivery)        la file relevée par « temoin »
#      PANNE_BASE_LABEL     (défaut: app=tsdb-mysql)       les pods de la base du consommateur
#      PANNE_VOISIN_NS      (défaut: voisin)               espace du voisin bruyant
#      PANNE_VOISIN_IMAGE   (défaut: busybox:1.36)
# ==============================================================================
set -uo pipefail

_ici="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$_ici/journal.sh" ] && JOURNAL_NOM="panne" . "$_ici/journal.sh"

NS="${PANNE_NAMESPACE:-train-ticket}"
CONSO="${PANNE_CONSOMMATEUR:-ts-delivery-service}"
FILE="${PANNE_FILE:-food_delivery}"
BASE_LABEL="${PANNE_BASE_LABEL:-app=tsdb-mysql}"
VOISIN_NS="${PANNE_VOISIN_NS:-voisin}"
VOISIN_IMAGE="${PANNE_VOISIN_IMAGE:-busybox:1.36}"
LOADGEN="$_ici/loadgen.sh"
CONSOMMATEUR="$_ici/consommateur.sh"
REGLAGE="consommateur-temps-de-service"   # l'objet du réglage de base (consommateur.sh)

JOURNAUX="$(cd "$_ici/.." && pwd)/journaux"
ETAT="$JOURNAUX/panne.etat"
REGISTRE="$JOURNAUX/pannes.tsv"
COLONNES='# instant_demande\tinstant_effectif\taction\tcause\tintensite\tcible\toutil\tresultat'

say()  { echo "  [panne] $*"; }
ok()   { echo "  [panne] OK  $*"; }
warn() { echo "  [panne] ATTENTION: $*" >&2; }
fail() { echo "  [panne] ERREUR: $*" >&2; exit 1; }
maintenant() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# ------------------------------------------------------------------------------
# Registre et état
# ------------------------------------------------------------------------------
# Le registre est le témoin durable : une ligne par geste, jamais réécrite.
# L'état décrit l'injection EN COURS, pour que « retirer » sache quoi défaire
# même lancé depuis une autre connexion, des heures plus tard.
# ------------------------------------------------------------------------------
consigner() {
    local demande="$1" effectif="$2" action="$3" cause="$4" intensite="$5" cible="$6" outil="$7" resultat="$8"
    mkdir -p "$JOURNAUX" 2>/dev/null
    [ -f "$REGISTRE" ] || printf "$COLONNES\n" > "$REGISTRE" 2>/dev/null
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$demande" "$effectif" "$action" "$cause" "$intensite" "$cible" "$outil" "$resultat" \
        >> "$REGISTRE" 2>/dev/null || warn "Non consigné dans $REGISTRE"
}

ecrire_etat() {
    mkdir -p "$JOURNAUX" 2>/dev/null
    printf '%s\n' "$@" | sed "s/=\(.*\)/='\1'/" > "$ETAT"
}

# ------------------------------------------------------------------------------
# Ce qu'on vise
# ------------------------------------------------------------------------------
repliques() {   # nom <tab> nœud — les répliques en marche, par ordre alphabétique
    kubectl get pods -n "$NS" -l "app=$CONSO" --field-selector=status.phase=Running \
        --sort-by=.metadata.name --no-headers \
        -o custom-columns=:metadata.name,:spec.nodeName 2>/dev/null \
        | awk 'NF==2 {print $1"\t"$2}'
}

# Le moins chargé des hôtes qui portent une réplique : c'est là que le contraste
# avant / pendant sera le plus net. Sans metrics-server, le premier par ordre
# alphabétique.
hote_le_moins_charge() {
    local hotes; hotes=$(repliques | cut -f2 | sort -u)
    [ -n "$hotes" ] || return 1
    local top; top=$(kubectl top nodes --no-headers 2>/dev/null)
    if [ -n "$top" ]; then
        printf '%s\n' "$top" \
            | awk -v h=" $(printf '%s ' $hotes)" 'index(h, " "$1" ") {print $3+0, $1}' \
            | sort -n | head -1 | cut -d' ' -f2
    else
        printf '%s\n' "$hotes" | head -1
    fi
}

pod_rabbitmq() {
    kubectl get pods -n "$NS" -l app=rabbitmq --no-headers -o custom-columns=:metadata.name 2>/dev/null | head -1
}

chaos_pret() {
    kubectl get crd networkchaos.chaos-mesh.org stresschaos.chaos-mesh.org >/dev/null 2>&1 || return 1
    kubectl get pods -A -l app.kubernetes.io/component=controller-manager --no-headers 2>/dev/null \
        | grep -q Running
}

demon_sur() {   # un démon Chaos Mesh tourne-t-il sur ce nœud ?
    kubectl get pods -A -l app.kubernetes.io/component=chaos-daemon \
        --field-selector="spec.nodeName=$1" --no-headers 2>/dev/null | grep -q Running
}

# Chaos Mesh ne dit « injecté » qu'une fois chaque conteneur visé touché.
attendre_injection() {   # <kind> <ns> <nom> <secondes>
    local kind="$1" ns="$2" nom="$3" reste="$4" s
    while [ "$reste" -gt 0 ]; do
        s=$(kubectl get "$kind" "$nom" -n "$ns" \
            -o jsonpath='{.status.conditions[?(@.type=="AllInjected")].status}' 2>/dev/null)
        [ "$s" = "True" ] && return 0
        sleep 3; reste=$((reste - 3))
    done
    return 1
}

conteneurs_touches() {   # <kind> <ns> <nom>
    kubectl get "$1" "$3" -n "$2" -o jsonpath='{.status.experiment.containerRecords[*].id}' 2>/dev/null | wc -w
}

# L'état d'un processus se lit dans /proc : « T » veut dire gelé. Le script
# tourne dans le conteneur, avec le sh minimal qu'il contient.
etat_java() {   # <pod> → une ligne « pid état » par processus Java
    kubectl exec -n "$NS" "$1" -- sh -c '
for d in /proc/[0-9]*; do
    [ -r "$d/comm" ] && read -r c < "$d/comm" 2>/dev/null && [ "$c" = java ] || continue
    read -r _ _ s _ < "$d/stat" 2>/dev/null && echo "${d#/proc/} $s"
done' 2>/dev/null
}

# ------------------------------------------------------------------------------
# verifier — les préalables d'une cause, sans rien toucher
# ------------------------------------------------------------------------------
verifier_app() {
    local cause="${1:-}" problemes=0
    case "$cause" in
        charge|lenteur|hote|blocage) ;;
        *) fail "Cause inconnue « $cause » — charge, lenteur, hote ou blocage" ;;
    esac
    if [ -f "$ETAT" ]; then
        . "$ETAT"
        warn "une injection est déjà en cours (« $CAUSE » depuis $DEBUT) — d'abord : $0 retirer"
        problemes=1
    fi
    local n; n=$(repliques | wc -l)
    case "$cause" in
        charge)
            local v; v=$(JOURNAL_OFF=1 bash "$LOADGEN" voyageurs 2>/dev/null | tr -d '[:space:]')
            case "$v" in ''|*[!0-9]*) warn "charge en cours illisible — le générateur tourne-t-il ?"; problemes=1 ;;
                         *) say "charge en cours : $v voyageurs" ;; esac ;;
        lenteur)
            chaos_pret || { warn "Chaos Mesh absent ou sans contrôleur — chaos.sh install"; problemes=1; }
            [ "$n" -gt 0 ] || { warn "aucune réplique de $CONSO en marche dans $NS"; problemes=1; }
            kubectl get pods -n "$NS" -l "$BASE_LABEL" --no-headers 2>/dev/null | grep -q . \
                || { warn "aucun pod « $BASE_LABEL » : la base du consommateur est introuvable (PANNE_BASE_LABEL)"; problemes=1; }
            for h in $(repliques | cut -f2 | sort -u); do
                demon_sur "$h" || { warn "pas de démon Chaos Mesh sur $h — chaos.sh status"; problemes=1; }
            done ;;
        hote)
            chaos_pret || { warn "Chaos Mesh absent ou sans contrôleur — chaos.sh install"; problemes=1; }
            [ "$n" -gt 0 ] || { warn "aucune réplique de $CONSO en marche dans $NS"; problemes=1; }
            for h in $(repliques | cut -f2 | sort -u); do
                demon_sur "$h" || { warn "pas de démon Chaos Mesh sur $h — chaos.sh status"; problemes=1; }
            done
            kubectl top nodes >/dev/null 2>&1 \
                || warn "kubectl top nodes muet : l'hôte sera choisi par ordre alphabétique, pas par charge" ;;
        blocage)
            [ "$n" -ge 2 ] || { warn "$n réplique de $CONSO : « les autres vont bien » n'existe pas — étape 6, --replicas=3"; problemes=1; } ;;
    esac
    [ "$problemes" = "0" ] && { ok "prêt pour « $cause »"; return 0; }
    warn "PAS prêt pour « $cause »"
    return 1
}

# ------------------------------------------------------------------------------
# injecter
# ------------------------------------------------------------------------------
# L'état est écrit AVANT d'agir : si l'injection échoue à moitié, « retirer »
# sait quand même quoi défaire.
# ------------------------------------------------------------------------------
injecter_charge() {
    local duree="$1" intensite="$2"
    local actuel; actuel=$(JOURNAL_OFF=1 bash "$LOADGEN" voyageurs 2>/dev/null | tr -d '[:space:]')
    case "$actuel" in ''|*[!0-9]*) fail "Charge en cours illisible — le générateur tourne-t-il ?" ;; esac
    [ -n "$intensite" ] || intensite=$((actuel * 2))
    [ "$intensite" -gt "$actuel" ] || fail "$intensite voyageurs n'est pas une hausse par rapport aux $actuel en cours"

    say "cause  : charge — $intensite voyageurs au lieu de $actuel, pendant $duree min"
    say "outil  : loadgen.sh scale"
    local demande; demande=$(maintenant)
    ecrire_etat CAUSE=charge OUTIL=loadgen "CIBLE=locust" "INTENSITE=$intensite" "RETOUR=$actuel" \
                "DEBUT=$demande" "DUREE=$duree" MINUTEUR=
    if LG_ORIGINE=panne JOURNAL_OFF=1 bash "$LOADGEN" scale "$intensite"; then
        # Le retour est programmé ici même : la panne expire sans pilote. Le
        # minuteur passe par « retirer », qui ne fait rien si l'état a disparu.
        nohup bash -c "sleep $((duree * 60)); [ -f '$ETAT' ] && JOURNAL_OFF=1 bash '$_ici/panne.sh' retirer" \
            >/dev/null 2>&1 < /dev/null &
        sed -i "s/^MINUTEUR=.*/MINUTEUR='$!'/" "$ETAT"
        consigner "$demande" "$(maintenant)" injection charge "$intensite" locust loadgen confirmee
        ok "injectée — retour à $actuel voyageurs dans $duree min, ou sur « retirer »"
        return 0
    fi
    consigner "$demande" "" injection charge "$intensite" locust loadgen NON_CONFIRMEE
    warn "la charge visée n'est pas atteinte ; l'injection est consignée NON_CONFIRMEE"
    return 1
}

injecter_lenteur() {
    local duree="$1" intensite="${2:-300}"
    local n; n=$(repliques | wc -l)
    [ "$n" -gt 0 ] || fail "Aucune réplique de $CONSO en marche dans $NS"
    local cle="${BASE_LABEL%%=*}" val="${BASE_LABEL#*=}"

    # Le retard de base (consommateur.sh) et la panne visent le même chemin :
    # un seul objet à la fois. La panne remplace le réglage par « base + panne »,
    # et « retirer » repose le réglage tel qu'il était.
    local base; base=$(kubectl get networkchaos "$REGLAGE" -n "$NS" -o jsonpath='{.spec.delay.latency}' 2>/dev/null | tr -d 'ms')
    case "$base" in *[!0-9]*) base="" ;; esac
    local total=$((intensite + ${base:-0}))

    say "cause  : lenteur — les $n répliques de $CONSO attendent $intensite ms de plus à chaque échange avec leur base${base:+ (réglage de base $base ms → $total ms)}"
    say "outil  : Chaos Mesh NetworkChaos $NS/panne-lenteur, durée ${duree}m"
    local demande; demande=$(maintenant)
    ecrire_etat CAUSE=lenteur OUTIL=chaos-mesh "CIBLE=$CONSO ($n répliques) -> $BASE_LABEL" \
                "INTENSITE=$intensite" "RETARD_BASE=${base:-}" "DEBUT=$demande" "DUREE=$duree"
    [ -z "$base" ] || kubectl delete networkchaos "$REGLAGE" -n "$NS" --ignore-not-found --timeout=90s >/dev/null 2>&1
    kubectl apply -f - >/dev/null <<EOF || fail "Chaos Mesh a refusé l'objet — voir ci-dessus."
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: panne-lenteur
  namespace: $NS
  labels: { panne: lenteur }
spec:
  action: delay
  mode: all
  selector:
    namespaces: [ "$NS" ]
    labelSelectors: { app: "$CONSO" }
  direction: to
  target:
    mode: all
    selector:
      namespaces: [ "$NS" ]
      labelSelectors: { $cle: "$val" }
  delay:
    latency: "${total}ms"
    jitter: "0ms"
    correlation: "0"
  duration: "${duree}m"
EOF
    if attendre_injection networkchaos "$NS" panne-lenteur 60; then
        local t; t=$(conteneurs_touches networkchaos "$NS" panne-lenteur)
        consigner "$demande" "$(maintenant)" injection lenteur "$intensite" "$CONSO x$n -> $BASE_LABEL" chaos-mesh/networkchaos confirmee
        ok "injectée — $t conteneur(s) touché(s), expire dans $duree min"
        [ -z "$base" ] || warn "à l'expiration, le réglage de base n'est PAS reposé tout seul : « retirer » le fait."
        return 0
    fi
    consigner "$demande" "" injection lenteur "$intensite" "$CONSO x$n -> $BASE_LABEL" chaos-mesh/networkchaos NON_CONFIRMEE
    warn "Chaos Mesh n'a pas confirmé en 60 s :  kubectl describe networkchaos panne-lenteur -n $NS"
    return 1
}

injecter_hote() {
    local duree="$1" intensite="$2" cible="$3"
    [ -n "$cible" ] || cible=$(hote_le_moins_charge) || fail "Aucune réplique de $CONSO en marche : pas d'hôte à viser"
    kubectl get node "$cible" >/dev/null 2>&1 || fail "Nœud « $cible » introuvable"
    demon_sur "$cible" || fail "Pas de démon Chaos Mesh sur « $cible » — chaos.sh status"
    local coeurs; coeurs=$(kubectl get node "$cible" -o jsonpath='{.status.capacity.cpu}' 2>/dev/null)
    case "$coeurs" in ''|*[!0-9]*) fail "Nombre de cœurs de « $cible » illisible" ;; esac
    [ -n "$intensite" ] || intensite=$((coeurs / 2))
    [ "$intensite" -ge 1 ] || intensite=1
    local sur; sur=$(repliques | awk -F'\t' -v h="$cible" '$2==h {print $1}' | paste -sd, -)
    [ -n "$sur" ] || warn "aucune réplique de $CONSO sur « $cible » : la file ne sentira rien"

    say "cause  : hote — un voisin occupe les $coeurs cœurs de « $cible » en en réclamant $intensite, pendant $duree min"
    say "         répliques de $CONSO sur cet hôte : ${sur:-aucune}"
    say "outil  : pod $VOISIN_NS/voisin-bruyant + Chaos Mesh StressChaos $VOISIN_NS/panne-hote"
    local demande; demande=$(maintenant)
    ecrire_etat CAUSE=hote OUTIL=chaos-mesh "CIBLE=$cible" "HOTE=$cible" "INTENSITE=$intensite" \
                "DEBUT=$demande" "DUREE=$duree"
    kubectl create namespace "$VOISIN_NS" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
    # nodeName, pas nodeSelector : c'est CET hôte, sans passer par l'ordonnanceur.
    kubectl apply -f - >/dev/null <<EOF || fail "Le pod voisin a été refusé — voir ci-dessus."
apiVersion: v1
kind: Pod
metadata:
  name: voisin-bruyant
  namespace: $VOISIN_NS
  labels: { app: voisin-bruyant, panne: hote }
spec:
  nodeName: $cible
  restartPolicy: Never
  containers:
    - name: voisin
      image: $VOISIN_IMAGE
      command: ["sh", "-c", "while true; do sleep 3600; done"]
      resources:
        requests: { cpu: "$intensite", memory: 64Mi }
EOF
    local reste=90 phase=""
    while [ "$reste" -gt 0 ]; do
        phase=$(kubectl get pod voisin-bruyant -n "$VOISIN_NS" -o jsonpath='{.status.phase}' 2>/dev/null)
        [ "$phase" = "Running" ] && break
        sleep 3; reste=$((reste - 3))
    done
    if [ "$phase" != "Running" ]; then
        consigner "$demande" "" injection hote "$intensite" "$cible" chaos-mesh/stresschaos NON_CONFIRMEE
        warn "le voisin n'a pas démarré sur « $cible » (phase : ${phase:-absent})."
        warn "  kubectl describe pod voisin-bruyant -n $VOISIN_NS   — image introuvable, ou $intensite cœur(s) de trop ?"
        return 1
    fi
    kubectl apply -f - >/dev/null <<EOF || fail "Chaos Mesh a refusé l'objet — voir ci-dessus."
apiVersion: chaos-mesh.org/v1alpha1
kind: StressChaos
metadata:
  name: panne-hote
  namespace: $VOISIN_NS
  labels: { panne: hote }
spec:
  mode: all
  selector:
    namespaces: [ "$VOISIN_NS" ]
    labelSelectors: { app: voisin-bruyant }
  stressors:
    cpu:
      workers: $coeurs
      load: 100
  duration: "${duree}m"
EOF
    if attendre_injection stresschaos "$VOISIN_NS" panne-hote 60; then
        consigner "$demande" "$(maintenant)" injection hote "$intensite" "$cible" chaos-mesh/stresschaos confirmee
        ok "injectée — $coeurs cœurs occupés sur « $cible », expire dans $duree min"
        return 0
    fi
    consigner "$demande" "" injection hote "$intensite" "$cible" chaos-mesh/stresschaos NON_CONFIRMEE
    warn "Chaos Mesh n'a pas confirmé en 60 s :  kubectl describe stresschaos panne-hote -n $VOISIN_NS"
    return 1
}

injecter_blocage() {
    local duree="$1" cible="$3"
    [ -z "${2:-}" ] || warn "--intensite est sans objet pour « blocage », ignoré"
    local liste; liste=$(repliques)
    [ -n "$liste" ] || fail "Aucune réplique de $CONSO en marche dans $NS"
    [ "$(printf '%s\n' "$liste" | wc -l)" -ge 2 ] \
        || fail "Une seule réplique de $CONSO : « les autres vont bien » n'existe pas — étape 6, --replicas=3"
    [ -n "$cible" ] || cible=$(printf '%s\n' "$liste" | head -1 | cut -f1)
    local hote; hote=$(printf '%s\n' "$liste" | awk -F'\t' -v p="$cible" '$1==p {print $2}')
    [ -n "$hote" ] || fail "« $cible » n'est pas une réplique en marche de $CONSO"

    say "cause  : blocage — la réplique $cible (sur $hote) est gelée pendant $duree min, les autres continuent"
    say "outil  : SIGSTOP sur le processus Java, levée programmée dans le conteneur"
    local demande; demande=$(maintenant)
    ecrire_etat CAUSE=blocage OUTIL=sigstop "CIBLE=$cible" "POD=$cible" "HOTE=$hote" INTENSITE= \
                "DEBUT=$demande" "DUREE=$duree"
    local sortie
    sortie=$(kubectl exec -n "$NS" "$cible" -- sh -c '
secondes="$1"; p=""
for d in /proc/[0-9]*; do
    [ -r "$d/comm" ] && read -r c < "$d/comm" 2>/dev/null && [ "$c" = java ] && p="$p ${d#/proc/}"
done
[ -n "$p" ] || p=1
kill -STOP $p || exit 1
nohup sh -c "sleep $secondes; kill -CONT $p" >/dev/null 2>&1 &
sleep 1
for i in $p; do read -r _ _ s _ < /proc/$i/stat && echo "$i $s"; done
' sh "$((duree * 60))" 2>&1)
    if [ $? -eq 0 ] && printf '%s\n' "$sortie" | grep -q ' T$'; then
        consigner "$demande" "$(maintenant)" injection blocage "" "$cible@$hote" sigstop confirmee
        ok "injectée — processus $(printf '%s\n' "$sortie" | grep ' T$' | cut -d' ' -f1 | paste -sd, -) gelé(s), levée dans $duree min"
        return 0
    fi
    printf '%s\n' "$sortie" | sed 's/^/      /' >&2
    consigner "$demande" "" injection blocage "" "$cible@$hote" sigstop NON_CONFIRMEE
    warn "le gel n'est pas confirmé (aucun processus à l'état T)"
    return 1
}

injecter_app() {
    local cause="${1:-}"; [ $# -gt 0 ] && shift
    local duree=20 intensite="" cible=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --duree)     duree="${2:-}"; shift 2 ;;
            --intensite) intensite="${2:-}"; shift 2 ;;
            --cible)     cible="${2:-}"; shift 2 ;;
            *) fail "Option inconnue : $1" ;;
        esac
    done
    case "$cause" in
        charge|lenteur|hote|blocage) ;;
        *) fail "Cause inconnue « $cause » — charge, lenteur, hote ou blocage" ;;
    esac
    case "$duree" in ''|*[!0-9]*) fail "--duree : un nombre de minutes" ;; esac
    [ "$duree" -gt 0 ] || fail "--duree : au moins une minute"
    case "$intensite" in *[!0-9]*) fail "--intensite : un nombre entier" ;; esac
    if [ -f "$ETAT" ]; then
        . "$ETAT"
        fail "Une injection est déjà en cours (« $CAUSE » depuis $DEBUT). D'abord : $0 retirer"
    fi
    "injecter_$cause" "$duree" "$intensite" "$cible"
}

# ------------------------------------------------------------------------------
# retirer — lever l'injection en cours ; sans état, nettoyer ce qui traîne
# ------------------------------------------------------------------------------
degeler() {   # <pod> — CONT, puis vérifie qu'aucun processus Java n'est resté en T
    kubectl exec -n "$NS" "$1" -- sh -c '
p=""
for d in /proc/[0-9]*; do
    [ -r "$d/comm" ] && read -r c < "$d/comm" 2>/dev/null && [ "$c" = java ] && p="$p ${d#/proc/}"
done
[ -n "$p" ] || p=1
kill -CONT $p' >/dev/null 2>&1 || return 1
    ! etat_java "$1" | grep -q ' T$'
}

nettoyer_residus() {
    local trouve=0
    if kubectl get networkchaos panne-lenteur -n "$NS" >/dev/null 2>&1; then
        kubectl delete networkchaos panne-lenteur -n "$NS" --timeout=90s >/dev/null 2>&1 \
            && say "objet networkchaos/panne-lenteur supprimé" || warn "networkchaos/panne-lenteur résiste"
        trouve=1
    fi
    if kubectl get stresschaos panne-hote -n "$VOISIN_NS" >/dev/null 2>&1; then
        kubectl delete stresschaos panne-hote -n "$VOISIN_NS" --timeout=90s >/dev/null 2>&1 \
            && say "objet stresschaos/panne-hote supprimé" || warn "stresschaos/panne-hote résiste"
        trouve=1
    fi
    if kubectl get pod voisin-bruyant -n "$VOISIN_NS" >/dev/null 2>&1; then
        kubectl delete pod voisin-bruyant -n "$VOISIN_NS" --timeout=90s >/dev/null 2>&1 \
            && say "pod voisin-bruyant supprimé" || warn "le pod voisin-bruyant résiste"
        trouve=1
    fi
    local pod
    for pod in $(repliques | cut -f1); do
        if etat_java "$pod" | grep -q ' T$'; then
            degeler "$pod" && say "réplique $pod dégelée" || warn "réplique $pod toujours gelée"
            trouve=1
        fi
    done
    [ "$trouve" = "1" ] && ok "nettoyé" || ok "rien à retirer"
    return 0
}

retirer_app() {
    if [ ! -f "$ETAT" ]; then
        say "Aucune injection en cours — recherche de restes…"
        nettoyer_residus
        return 0
    fi
    . "$ETAT"
    local demande resultat=ok; demande=$(maintenant)
    say "Retrait de « $CAUSE » (injectée à $DEBUT)…"
    case "$CAUSE" in
        charge)
            [ -n "${MINUTEUR:-}" ] && [ "$MINUTEUR" != "$PPID" ] && kill "$MINUTEUR" >/dev/null 2>&1
            LG_ORIGINE=retour_panne JOURNAL_OFF=1 bash "$LOADGEN" scale "$RETOUR" || resultat=ECHEC ;;
        lenteur)
            kubectl delete networkchaos panne-lenteur -n "$NS" --ignore-not-found --timeout=90s >/dev/null 2>&1 \
                || resultat=ECHEC
            if [ -n "${RETARD_BASE:-}" ]; then
                say "Retour au réglage de base ($RETARD_BASE ms)…"
                JOURNAL_OFF=1 bash "$CONSOMMATEUR" dimensionner --retard "$RETARD_BASE" >/dev/null 2>&1 \
                    && say "réglage de base reposé" || { warn "réglage de base NON reposé :  consommateur.sh dimensionner --retard $RETARD_BASE"; resultat=ECHEC; }
            fi ;;
        hote)
            kubectl delete stresschaos panne-hote -n "$VOISIN_NS" --ignore-not-found --timeout=90s >/dev/null 2>&1 \
                || resultat=ECHEC
            kubectl delete pod voisin-bruyant -n "$VOISIN_NS" --ignore-not-found --timeout=90s >/dev/null 2>&1 \
                || resultat=ECHEC ;;
        blocage)
            if kubectl get pod "$POD" -n "$NS" >/dev/null 2>&1; then
                degeler "$POD" || resultat=ECHEC
            else
                warn "la réplique $POD n'existe plus — rien à dégeler"
            fi ;;
    esac
    consigner "$demande" "$(maintenant)" retrait "$CAUSE" "${INTENSITE:-}" "$CIBLE" "$OUTIL" "$resultat"
    rm -f "$ETAT"
    [ "$resultat" = "ok" ] && { ok "retirée"; return 0; }
    warn "le retrait a échoué — vérifie à la main, puis :  $0 etat"
    return 1
}

# ------------------------------------------------------------------------------
# etat — 0 si rien n'est injecté ni résiduel, 3 sinon
# ------------------------------------------------------------------------------
# Une campagne de référence lancée avec une panne encore en place serait fausse
# sans que rien ne le montre : c'est le code de retour qui protège le pilote.
# ------------------------------------------------------------------------------
etat_app() {
    local residus=0
    if [ -f "$ETAT" ]; then
        . "$ETAT"
        say "Injection en cours : $CAUSE"
        echo "     outil      $OUTIL"
        echo "     cible      $CIBLE"
        echo "     intensité  ${INTENSITE:-sans objet}"
        echo "     depuis     $DEBUT"
        echo "     durée      $DUREE min"
        case "$CAUSE" in
            lenteur) [ "$(kubectl get networkchaos panne-lenteur -n "$NS" -o jsonpath='{.status.conditions[?(@.type=="AllInjected")].status}' 2>/dev/null)" = "True" ] \
                         && say "Chaos Mesh : injectée" || say "Chaos Mesh : pas (ou plus) injectée — expirée ?" ;;
            hote)    [ "$(kubectl get stresschaos panne-hote -n "$VOISIN_NS" -o jsonpath='{.status.conditions[?(@.type=="AllInjected")].status}' 2>/dev/null)" = "True" ] \
                         && say "Chaos Mesh : injectée" || say "Chaos Mesh : pas (ou plus) injectée — expirée ?" ;;
            blocage) etat_java "$POD" | grep -q ' T$' && say "processus : gelé" || say "processus : pas (ou plus) gelé — levée programmée passée ?" ;;
            charge)  say "charge en cours : $(JOURNAL_OFF=1 bash "$LOADGEN" voyageurs 2>/dev/null | tr -d '[:space:]') voyageurs (retour prévu : $RETOUR)" ;;
        esac
        say "Pour lever :  $0 retirer"
        return 3
    fi
    say "Aucune injection en cours."
    kubectl get networkchaos panne-lenteur -n "$NS" >/dev/null 2>&1 && { warn "reste : networkchaos/panne-lenteur"; residus=1; }
    kubectl get stresschaos panne-hote -n "$VOISIN_NS" >/dev/null 2>&1 && { warn "reste : stresschaos/panne-hote"; residus=1; }
    kubectl get pod voisin-bruyant -n "$VOISIN_NS" >/dev/null 2>&1 && { warn "reste : pod voisin-bruyant"; residus=1; }
    local pod
    for pod in $(repliques | cut -f1); do
        etat_java "$pod" | grep -q ' T$' && { warn "reste : réplique $pod gelée"; residus=1; }
    done
    [ "$residus" = "0" ] && { ok "rien d'injecté, rien de résiduel"; return 0; }
    warn "des restes — pour nettoyer :  $0 retirer"
    return 3
}

# ------------------------------------------------------------------------------
# temoin — un relevé court, à lire avant / pendant / après une injection
# ------------------------------------------------------------------------------
temoin_app() {
    echo "  instant : $(maintenant)"
    local r; r=$(pod_rabbitmq)
    if [ -n "$r" ]; then
        kubectl exec -n "$NS" "$r" -- rabbitmqctl list_queues name messages_ready messages_unacknowledged consumers 2>/dev/null \
            | awk -v f="$FILE" '$1==f {printf "  file %s : %s en attente, %s non acquitté(s), %s consommateur(s)\n", $1, $2, $3, $4}'
    else
        echo "  file : courtier introuvable (label app=rabbitmq)"
    fi
    echo "  voyageurs : $(JOURNAL_OFF=1 bash "$LOADGEN" voyageurs 2>/dev/null | tr -d '[:space:]')"
    echo "  répliques de $CONSO :"
    local liste top; liste=$(repliques); top=$(kubectl top pods -n "$NS" -l "app=$CONSO" --no-headers 2>/dev/null)
    printf '%s\n' "$liste" | while IFS=$'\t' read -r pod noeud; do
        [ -n "$pod" ] || continue
        printf "      %-45s %-10s %s\n" "$pod" "$noeud" \
            "$(printf '%s\n' "$top" | awk -v p="$pod" '$1==p {print "cpu " $2 "  mém " $3}')"
    done
    echo "  hôtes :"
    local hotes; hotes=$(printf '%s\n' "$liste" | cut -f2 | sort -u)
    kubectl top nodes --no-headers 2>/dev/null \
        | awk -v h=" $(printf '%s ' $hotes)" 'index(h, " "$1" ") {printf "      %-10s cpu %s (%s)  mém %s (%s)\n", $1, $2, $3, $4, $5}'
    if [ -f "$ETAT" ]; then . "$ETAT"; echo "  injection : $CAUSE depuis $DEBUT"; else echo "  injection : aucune"; fi
}

# ------------------------------------------------------------------------------
case "${1:-etat}" in
    verifier) verifier_app "${2:-}" ;;
    injecter) shift; injecter_app "$@" ;;
    retirer)  retirer_app ;;
    etat)     etat_app ;;
    temoin)   temoin_app ;;
    *) echo "Usage: $0 {verifier <cause>|injecter <cause> [--duree <min>] [--intensite <n>] [--cible <x>]|retirer|etat|temoin}" >&2; exit 2 ;;
esac
