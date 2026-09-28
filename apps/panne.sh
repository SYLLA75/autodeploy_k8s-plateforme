#!/bin/bash
# ==============================================================================
#  apps/panne.sh — injecter une panne, la retirer, consigner qui, quand, avec quoi
# ==============================================================================
#
#  Six causes, un même symptôme : le tas de la file grossit. Ce script sait
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
#                → SIGSTOP sur son processus Java, envoyé depuis la machine
#                  par le démon Chaos Mesh (le processus 1 d'un conteneur
#                  ignore les signaux venus de l'intérieur)
#
#     base       la base de données répond plus lentement à TOUS ses clients
#                → Chaos Mesh NetworkChaos : un retard sur ce que le pod leader
#                  (tsdb-mysql-0) envoie aux pods de train-ticket, SAUF à ses
#                  suiveuses (la réplication est semi-synchrone : les retarder
#                  ralentirait chaque validation et les battements de xenon).
#                  Le réglage de base des répliques (retard sur LEUR sortie)
#                  n'est pas touché : les deux retards s'ajoutent sur leur
#                  chemin. Refusé si tsdb-mysql-0 n'est pas le leader.
#
#     reseau     phase D, les jumeaux : le réseau de la machine X (celle d'une
#                réplique) est ralenti, sans perte ; en même temps, une machine
#                leurre Y reçoit le voisin bruyant de la cause hote (même règle
#                de demande, stress sur tous ses cœurs)
#                → Chaos Mesh : NetworkChaos panne-reseau-replique, retard sur
#                  tout ce qu'envoie la réplique de X, et NetworkChaos
#                  panne-reseau, retard sur ce que les autres pods de l'espace
#                  applicatif sur X envoient à la base (écart 3, journal D.5 :
#                  retarder tout ce qu'envoient ces pods freinait les parcours
#                  et la file ne débordait pas) ; + pod voisin-leurre et StressChaos
#                  panne-leurre sur Y. Une seule ligne de registre, cible
#                  « X@leurre:Y » ; les trois objets confirmés dans les mêmes 60 s, sinon
#                  tout est retiré et l'injection est NON_CONFIRMEE.
#                  Pas la carte de la machine elle-même : Chaos Mesh refuse un pod
#                  au réseau de l'hôte (« dangerous »), et poser tc sur la carte
#                  par le démon a été refusé (journal, D.2).
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
#  lève la sienne à l'échéance, la levée du gel est programmée dans le démon
#  du nœud, le retour de charge par un minuteur sur le master. Un pilote qui meurt
#  ne laisse pas la panne derrière lui. « retirer » lève tout de suite ; sans
#  injection en cours, il nettoie ce qui aurait pu rester.
#
#  Usage (depuis le master) :
#      bash ~/autodeploy/apps/panne.sh verifier <cause> [--cible <x>]…
#      bash ~/autodeploy/apps/panne.sh injecter <cause> [--duree <min>] [--intensite <n>] [--cible <x>]
#      bash ~/autodeploy/apps/panne.sh retirer
#      bash ~/autodeploy/apps/panne.sh etat
#      bash ~/autodeploy/apps/panne.sh temoin [court]   (court : sans toucher le pod de la base)
#      bash ~/autodeploy/apps/panne.sh leader     tsdb-mysql-0 est-il le leader ? (code 1 sinon)
#      bash ~/autodeploy/apps/panne.sh libres     « machine millicœurs_libres » par machine
#
#  --intensite, selon la cause :
#      charge     voyageurs                      (défaut : 2 × la charge en cours)
#      lenteur    millisecondes de retard EN PLUS du réglage de base (défaut : 300)
#      hote       cœurs réclamés par le voisin   (défaut : la moitié de l'hôte)
#      blocage    sans objet
#      base       millisecondes de retard sur ce que la base envoie (défaut : 75)
#      reseau     millisecondes de retard sur ce qu'envoie chaque pod de X (exigée)
#
#  --cible, selon la cause :
#      hote       nom du nœud  (défaut : le moins chargé des hôtes portant une réplique)
#      blocage    nom du pod   (défaut : la première réplique par ordre alphabétique)
#      reseau     « X:Y », exigée : la machine au réseau ralenti, la machine leurre
#                 (choisies par graphe_en/couples_d.py, règle écrite avant D)
#  « verifier » accepte une ou plusieurs --cible et les contrôle toutes, pour
#  qu'une campagne à cibles tournantes soit refusée avant son départ.
#
#  « base » n'accepte pas --cible : elle vise toujours tsdb-mysql-0 (PANNE_BASE_POD).
#
#  Registre : journaux/pannes.tsv — une ligne par injection et par retrait.
#
#  Variables reconnues :
#      PANNE_NAMESPACE      (défaut: train-ticket)
#      PANNE_CONSOMMATEUR   (défaut: ts-delivery-service)  déploiement qui retire de la file
#      PANNE_FILE           (défaut: food_delivery)        la file relevée par « temoin »
#      PANNE_BASE_LABEL     (défaut: app=tsdb-mysql)       les pods de la base du consommateur
#      PANNE_BASE_POD       (défaut: tsdb-mysql-0)         le pod visé par « base » (le leader)
#      PANNE_BASE_SVC_LEADER (défaut: tsdb-mysql-leader)   le service par lequel les clients écrivent
#      PANNE_REGLAGE_ATTENDU (défaut: 140ms)              le réglage de base exigé par « verifier base »
#      PANNE_VOISIN_NS      (défaut: voisin)               espace du voisin bruyant
#      PANNE_VOISIN_IMAGE   (défaut: busybox:1.36)
#      CHAOS_NAMESPACE      (défaut: chaos-mesh)           où vivent les démons
#      PANNE_LEURRE_MIN_M   (défaut: 1400)                 demande minimale du leurre (la plus
#                                                          petite des voisins de la seconde série)
# ==============================================================================
set -uo pipefail

_ici="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Une simple lecture ne laisse pas de journal : il n'y a rien à garder, et
# un relevé répété toutes les 20 s en écrirait des centaines.
case "${1:-}" in etat|temoin|verifier|leader|libres) JOURNAL_OFF=1 ;; esac
[ -f "$_ici/journal.sh" ] && JOURNAL_NOM="panne" . "$_ici/journal.sh"

NS="${PANNE_NAMESPACE:-train-ticket}"
CONSO="${PANNE_CONSOMMATEUR:-ts-delivery-service}"
FILE="${PANNE_FILE:-food_delivery}"
BASE_LABEL="${PANNE_BASE_LABEL:-app=tsdb-mysql}"
BASE_POD="${PANNE_BASE_POD:-tsdb-mysql-0}"
BASE_SVC_LEADER="${PANNE_BASE_SVC_LEADER:-tsdb-mysql-leader}"
VOISIN_NS="${PANNE_VOISIN_NS:-voisin}"
VOISIN_IMAGE="${PANNE_VOISIN_IMAGE:-busybox:1.36}"
LEURRE_MIN_M="${PANNE_LEURRE_MIN_M:-1400}"
LOADGEN="$_ici/loadgen.sh"
CONSOMMATEUR="$_ici/consommateur.sh"
CONSO_MYSQL_LABEL="${PANNE_BASE_LABEL:-app=tsdb-mysql}" CONSO_NAMESPACE="$NS" . "$_ici/mysql.sh"
REGLAGE="consommateur-temps-de-service"   # l'objet du réglage de base (consommateur.sh)
REGLAGE_ATTENDU="${PANNE_REGLAGE_ATTENDU:-140ms}"   # sa valeur dans les deux séries et en C

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

# Le pod visé par « base » est-il le leader ? Deux preuves : son étiquette
# role=leader (posée par xenon) ET l'adresse derrière le service du leader, celle
# que les clients utilisent. Écrit ce qu'il a vu ; 0 si les deux concordent.
base_leader() {
    local role ip ep
    role=$(kubectl get pod "$BASE_POD" -n "$NS" -o jsonpath='{.metadata.labels.role}' 2>/dev/null)
    ip=$(kubectl get pod "$BASE_POD" -n "$NS" -o jsonpath='{.status.podIP}' 2>/dev/null)
    ep=$(kubectl get endpoints "$BASE_SVC_LEADER" -n "$NS" -o jsonpath='{.subsets[*].addresses[*].ip}' 2>/dev/null)
    echo "role=${role:-?}, adresse ${ip:-?}, $BASE_SVC_LEADER → ${ep:-?}"
    [ "$role" = "leader" ] && [ -n "$ip" ] && [ "$ep" = "$ip" ]
}

# Le retard du réglage de base réellement posé sur une réplique (vide si rien).
reglage_pose() {
    kubectl get podnetworkchaos "$1" -n "$NS" \
        -o jsonpath="{.spec.tcs[?(@.source==\"$NS/$REGLAGE\")].delay.latency}" 2>/dev/null
}

# Les paquets jetés à la sortie du pod de la base (la file du netem peut en
# jeter : ce serait une perte, que la panne « base » exclut), lus par le démon
# Chaos Mesh du nœud dans l'espace réseau du pod.
jetes_base() {
    sur_la_machine "$BASE_POD" 'cid="$1"
for d in /proc/[0-9]*; do
    grep -qs "$cid" "$d/cgroup" || continue
    nsenter -t "${d#/proc/}" -n tc -s qdisc show dev eth0 2>/dev/null \
        | sed -n "s/.*dropped \([0-9]*\).*/\1/p" | awk "{s += \$1} END {print s + 0}"
    exit 0
done
exit 1'
}

# Les adresses que la panne « base » retarde, lues dans l'objet que Chaos Mesh
# a posé sur le pod de la base (vide si rien n'est posé).
adresses_retardees_base() {
    kubectl get podnetworkchaos "$BASE_POD" -n "$NS" \
        -o jsonpath="{.spec.ipsets[?(@.source==\"$NS/panne-base\")].cidrs[*]}" 2>/dev/null | tr ' ' '\n' | sed 's|/32$||' | grep .
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

# ------------------------------------------------------------------------------
# Geler une réplique : depuis la machine, jamais depuis le conteneur
# ------------------------------------------------------------------------------
# Java est le processus 1 de son conteneur, et le noyau fait ignorer au
# processus 1 les signaux envoyés depuis l'intérieur de son propre conteneur,
# STOP compris. Le signal doit venir de la machine. Le démon Chaos Mesh tourne
# sur chaque nœud avec les processus de la machine en vue : c'est par lui
# qu'on trouve le processus (par l'identifiant du conteneur dans son cgroup),
# qu'on le gèle, et qu'on programme la levée.
# ------------------------------------------------------------------------------
CHAOS_NS="${CHAOS_NAMESPACE:-chaos-mesh}"

demon_du_pod() {   # <pod> → le démon Chaos Mesh du nœud qui porte ce pod
    local noeud; noeud=$(kubectl get pod "$1" -n "$NS" -o jsonpath='{.spec.nodeName}' 2>/dev/null)
    [ -n "$noeud" ] || return 1
    kubectl get pods -n "$CHAOS_NS" -l app.kubernetes.io/component=chaos-daemon \
        --field-selector="spec.nodeName=$noeud,status.phase=Running" --no-headers \
        -o custom-columns=:metadata.name 2>/dev/null | head -1
}

id_conteneur() {   # <pod> → l'identifiant du premier conteneur, sans son préfixe
    kubectl get pod "$1" -n "$NS" -o jsonpath='{.status.containerStatuses[0].containerID}' 2>/dev/null | sed 's|^.*://||'
}

# sur_la_machine <pod> <script sh> [args…] — exécute le script dans le démon
# du nœud, avec $1 = identifiant du conteneur puis les args
sur_la_machine() {
    local pod="$1" script="$2"; shift 2
    local demon cid
    demon=$(demon_du_pod "$pod") || return 1
    [ -n "$demon" ] || return 1
    cid=$(id_conteneur "$pod"); [ -n "$cid" ] || return 1
    kubectl exec -n "$CHAOS_NS" "$demon" -- sh -c "$script" sh "$cid" "$@" 2>/dev/null
}

# Le script commun : les processus Java du conteneur, vus de la machine.
PIDS_JAVA='cid="$1"; p=""
for d in /proc/[0-9]*; do
    grep -qs "$cid" "$d/cgroup" || continue
    read -r c < "$d/comm" 2>/dev/null && [ "$c" = java ] && p="$p ${d#/proc/}"
done'

etat_java() {   # <pod> → une ligne « pid état » par processus Java
    sur_la_machine "$1" "$PIDS_JAVA"'
for i in $p; do read -r _ _ s _ < /proc/$i/stat 2>/dev/null && echo "$i $s"; done'
}

# ------------------------------------------------------------------------------
# Le réseau des pods d'une machine (cause reseau)
# ------------------------------------------------------------------------------
demon_du_noeud() {   # <nœud> → son démon Chaos Mesh en marche
    kubectl get pods -n "$CHAOS_NS" -l app.kubernetes.io/component=chaos-daemon \
        --field-selector="spec.nodeName=$1,status.phase=Running" --no-headers \
        -o custom-columns=:metadata.name 2>/dev/null | head -1
}

machines_de_travail() {   # les nœuds qui ont un démon Chaos Mesh, sauf le master
    kubectl get pods -n "$CHAOS_NS" -l app.kubernetes.io/component=chaos-daemon --no-headers \
        -o custom-columns=:spec.nodeName 2>/dev/null | grep -v '^master$' | sort -u
}

pods_de_la_machine() {   # <nœud> → les pods en marche de l'espace applicatif sur ce nœud
    kubectl get pods -n "$NS" --field-selector="spec.nodeName=$1,status.phase=Running" --no-headers \
        -o custom-columns=:metadata.name 2>/dev/null | grep . | sort
}

# « pod retard objet » pour chaque pod qui porte un retard de la panne reseau :
# panne-reseau-replique (la réplique de X, sans cible) ou panne-reseau (les
# autres pods de X, vers la base).
retards_reseau() {
    local o
    for o in panne-reseau-replique panne-reseau; do
        kubectl get podnetworkchaos -n "$NS" \
            -o jsonpath="{range .items[*]}{.metadata.name}{' '}{.spec.tcs[?(@.source==\"$NS/$o\")].delay.latency}{'\n'}{end}" \
            2>/dev/null | awk -v o="$o" 'NF >= 2 {print $1, $2, o}'
    done | sort
}

# Paquets jetés (files de sortie des pods) et segments TCP retransmis, sommés sur
# les pods d'une machine, lus par le démon de la machine dans l'espace réseau de
# chaque pod. Rien n'est modifié. Les jetés sont comptés depuis la dernière pose
# d'une file par Chaos Mesh (il refait la file de chaque pod à la pose et au
# retrait : le compte d'une panne se lit donc juste AVANT son retrait) ; les
# retransmissions, depuis le démarrage du pod.
reseau_de_la_machine() {   # <nœud> → « jetes=… retrans=… pods=… »
    local d cids; d=$(demon_du_noeud "$1"); [ -n "$d" ] || return 1
    cids=$(kubectl get pods -n "$NS" --field-selector="spec.nodeName=$1,status.phase=Running" \
        -o jsonpath='{range .items[*]}{.status.containerStatuses[0].containerID}{"\n"}{end}' 2>/dev/null \
        | sed 's|^.*://||' | grep .)
    [ -n "$cids" ] || { echo "aucun pod de $NS"; return 0; }
    kubectl exec -n "$CHAOS_NS" "$d" -- sh -c '
j=0; r=0; n=0
for cid in "$@"; do   # n : les pods dont la file a été lue
    f=$(grep -ls "$cid" /proc/[0-9]*/cgroup 2>/dev/null | head -1)
    [ -n "$f" ] || continue
    pid=${f#/proc/}; pid=${pid%/cgroup}
    q=$(nsenter -t "$pid" -n tc -s qdisc show dev eth0 2>/dev/null)
    [ -n "$q" ] || continue
    x=$(printf "%s\n" "$q" | sed -n "s/.*dropped \([0-9]*\).*/\1/p" | awk "{s += \$1} END {print s + 0}")
    y=$(awk "/^Tcp:/ {k++; if (k == 1) {for (i = 1; i <= NF; i++) if (\$i == \"RetransSegs\") c = i} else print \$c}" "/proc/$pid/net/snmp" 2>/dev/null)
    j=$((j + ${x:-0})); r=$((r + ${y:-0})); n=$((n + 1))
done
echo "jetes=$j retrans=$r pods=$n"' sh $cids 2>/dev/null
}

lire_couple() {   # « X:Y » → COUPLE_X, COUPLE_Y ; 1 si mal formé
    COUPLE_X="${1%%:*}"; COUPLE_Y="${1#*:}"
    [[ "$1" =~ ^[a-z0-9.-]+:[a-z0-9.-]+$ ]] && [ "$COUPLE_X" != "$COUPLE_Y" ]
}

# ------------------------------------------------------------------------------
# verifier — les préalables d'une cause, sans rien toucher
# ------------------------------------------------------------------------------
# Sans le réglage de base, à sa valeur et posé sur chaque réplique, la campagne
# ne serait pas comparable aux autres (causes base et reseau).
verifier_reglage() {
    local reglage r pose manquantes=""
    reglage=$(kubectl get networkchaos "$REGLAGE" -n "$NS" -o jsonpath='{.spec.delay.latency}' 2>/dev/null)
    if [ -z "$reglage" ]; then
        warn "réglage de base $REGLAGE absent — consommateur.sh dimensionner"; return 1
    elif [ "$reglage" != "$REGLAGE_ATTENDU" ]; then
        warn "réglage de base à $reglage, pas $REGLAGE_ATTENDU (PANNE_REGLAGE_ATTENDU) : campagne non comparable"; return 1
    fi
    for r in $(repliques | cut -f1); do
        pose=$(reglage_pose "$r")
        [ "$pose" = "$reglage" ] || manquantes="$manquantes $r(${pose:-rien})"
    done
    if [ -n "$manquantes" ]; then
        warn "réglage de base pas posé sur :$manquantes — consommateur.sh dimensionner"; return 1
    fi
    say "réglage de base des répliques : $reglage, posé sur chacune (sur leur sortie ; la panne s'y ajoute)"
}

verifier_app() {
    local cause="${1:-}" problemes=0 cibles=()
    [ $# -gt 0 ] && shift
    case "$cause" in
        charge|lenteur|hote|blocage|base|reseau) ;;
        *) fail "Cause inconnue « $cause » — charge, lenteur, hote, blocage, base ou reseau" ;;
    esac
    while [ $# -gt 0 ]; do
        case "$1" in
            --cible) [ -n "${2:-}" ] || fail "--cible : un nom"; cibles+=("$2"); shift 2 ;;
            *) fail "Option inconnue : $1" ;;
        esac
    done
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
            [ "$n" -ge 2 ] || { warn "$n réplique de $CONSO : « les autres vont bien » n'existe pas — étape 6, --replicas=3"; problemes=1; }
            for h in $(repliques | cut -f2 | sort -u); do
                demon_sur "$h" || { warn "pas de démon Chaos Mesh sur $h : le gel s'envoie depuis la machine, par lui — chaos.sh status"; problemes=1; }
            done ;;
        base)
            chaos_pret || { warn "Chaos Mesh absent ou sans contrôleur — chaos.sh install"; problemes=1; }
            local phase noeud vu
            phase=$(kubectl get pod "$BASE_POD" -n "$NS" -o jsonpath='{.status.phase}' 2>/dev/null)
            [ "$phase" = "Running" ] || { warn "$BASE_POD : ${phase:-introuvable}, pas en marche"; problemes=1; }
            if vu=$(base_leader); then
                say "$BASE_POD est le leader ($vu)"
            else
                warn "$BASE_POD n'est pas le leader ($vu) : la panne viserait une suiveuse"; problemes=1
            fi
            noeud=$(kubectl get pod "$BASE_POD" -n "$NS" -o jsonpath='{.spec.nodeName}' 2>/dev/null)
            if [ -n "$noeud" ] && demon_sur "$noeud"; then
                say "$BASE_POD sur $noeud, démon Chaos Mesh présent"
            else
                warn "pas de démon Chaos Mesh sur le nœud de $BASE_POD (${noeud:-?}) — chaos.sh status"; problemes=1
            fi
            verifier_reglage || problemes=1 ;;
        reseau)
            chaos_pret || { warn "Chaos Mesh absent ou sans contrôleur — chaos.sh install"; problemes=1; }
            [ "$n" -gt 0 ] || { warn "aucune réplique de $CONSO en marche dans $NS"; problemes=1; }
            local vu
            if vu=$(base_leader); then say "$BASE_POD est le leader ($vu)"
            else warn "$BASE_POD n'est pas le leader ($vu)"; problemes=1; fi
            [ "${#cibles[@]}" -gt 0 ] || { warn "« reseau » exige --cible X:Y (graphe_en/couples_d.py)"; problemes=1; }
            verifier_reglage || problemes=1 ;;
    esac
    [ "${#cibles[@]}" -eq 0 ] || verifier_cibles "$cause" "${cibles[@]}" || problemes=1
    [ "$problemes" = "0" ] && { ok "prêt pour « $cause »"; return 0; }
    warn "PAS prêt pour « $cause »"
    return 1
}

# Chaque cible passe les contrôles que son injection fera, sans rien toucher.
# Pour hote, le nombre de cœurs est affiché : l'intensité par défaut en est la
# moitié, et des hôtes de tailles différentes ne recevraient pas la même panne.
verifier_cibles() {   # <cause> <cible>…
    local cause="$1" c problemes=0 liste; shift
    liste=$(repliques)
    case "$cause" in
        charge|lenteur|base) warn "--cible est sans objet pour « $cause »"; return 1 ;;
    esac
    for c in "$@"; do
        case "$cause" in
            reseau)
                if ! lire_couple "$c"; then
                    warn "cible $c : il faut « X:Y », deux machines différentes"; problemes=1; continue
                fi
                local x="$COUPLE_X" y="$COUPLE_Y" m n_x libre_y demande_y
                for m in "$x" "$y"; do
                    kubectl get node "$m" >/dev/null 2>&1 || { warn "cible $c : nœud $m introuvable"; problemes=1; continue 2; }
                    demon_sur "$m" || { warn "cible $c : pas de démon Chaos Mesh sur $m"; problemes=1; }
                done
                n_x=$(pods_de_la_machine "$x" | wc -l)
                [ "$n_x" -gt 0 ] || { warn "cible $c : aucun pod de $NS en marche sur $x"; problemes=1; }
                [ "$(printf '%s\n' "$liste" | awk -F'\t' -v h="$x" '$2 == h' | wc -l)" -eq 1 ] \
                    || { warn "cible $c : il faut exactement une réplique de $CONSO sur $x"; problemes=1; }
                [ -n "$(ips_devant_mysql)" ] || { warn "cible $c : adresses de service devant la base illisibles"; problemes=1; }
                [ -z "$(retards_reseau)" ] || { warn "cible $c : des pods portent déjà un retard de panne-reseau"; problemes=1; }
                libre_y=$(millicoeurs_libres "$y"); demande_y=2000
                [ -z "$libre_y" ] || [ "$demande_y" -le $((libre_y - 100)) ] || demande_y=$(( (libre_y - 100) / 100 * 100 ))
                [ "$demande_y" -ge "$LEURRE_MIN_M" ] \
                    || { warn "cible $c : ${libre_y:-?}m libres sur $y, le leurre ne réclamerait que ${demande_y}m (< ${LEURRE_MIN_M}m)"; problemes=1; }
                say "cible $c : $n_x pods de $NS sur $x ; leurre $y, ${libre_y:-?}m libres, demande ${demande_y}m" ;;
            hote)
                if ! kubectl get node "$c" >/dev/null 2>&1; then
                    warn "cible $c : nœud introuvable"; problemes=1; continue
                fi
                demon_sur "$c" || { warn "cible $c : pas de démon Chaos Mesh — chaos.sh status"; problemes=1; }
                local coeurs libre sur
                coeurs=$(kubectl get node "$c" -o jsonpath='{.status.capacity.cpu}' 2>/dev/null)
                case "$coeurs" in ''|*[!0-9]*) warn "cible $c : nombre de cœurs illisible"; problemes=1; continue ;; esac
                libre=$(millicoeurs_libres "$c")
                [ -z "$libre" ] || [ "$libre" -ge 200 ] \
                    || { warn "cible $c : ${libre}m allouables libres, pas de place pour un voisin"; problemes=1; }
                sur=$(printf '%s\n' "$liste" | awk -F'\t' -v h="$c" '$2==h {print $1}' | paste -sd, -)
                # La cause hote vise l'hôte d'une réplique : un autre nœud (une
                # faute d'un chiffre, ou workers6, celui de la mesure) est refusé.
                [ -n "$sur" ] || { warn "cible $c : aucune réplique de $CONSO dessus — pas une cible de la cause hote"; problemes=1; }
                say "cible $c : $coeurs cœurs (intensité par défaut $((coeurs / 2))), ${libre:-?}m libres, répliques : ${sur:-aucune}" ;;
            blocage)
                local hote; hote=$(printf '%s\n' "$liste" | awk -F'\t' -v p="$c" '$1==p {print $2}')
                if [ -z "$hote" ]; then
                    warn "cible $c : pas une réplique en marche de $CONSO"; problemes=1
                else
                    say "cible $c : réplique en marche sur $hote"
                fi ;;
        esac
    done
    [ "$problemes" = "0" ] || return 1
    ok "cibles vérifiées : $#"
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
                "INTENSITE=$intensite" "RETARD_BASE=${base:-}" "DEBUT=$demande" "DUREE=$duree" MINUTEUR=
    # La panne est posée AVANT que le réglage soit retiré : deux retards sur
    # les mêmes pods s'additionnent (mesuré : 140 + 1 → 143 ms), donc pendant
    # le recouvrement le consommateur est un peu plus lent, jamais sans retard.
    # Dans l'autre ordre, il serait mille fois trop rapide quelques secondes.
    yaml_retard panne-lenteur "$CONSO" "$total" "$duree" "panne=lenteur" | kubectl apply -f - >/dev/null \
        || fail "Chaos Mesh a refusé l'objet — voir ci-dessus."
    if attendre_injection networkchaos "$NS" panne-lenteur 60; then
        [ -z "$base" ] || kubectl delete networkchaos "$REGLAGE" -n "$NS" --ignore-not-found --timeout=90s >/dev/null 2>&1
        local t; t=$(conteneurs_touches networkchaos "$NS" panne-lenteur)
        consigner "$demande" "$(maintenant)" injection lenteur "$intensite" "$CONSO x$n -> $BASE_LABEL" chaos-mesh/networkchaos confirmee
        ok "injectée — $t conteneur(s) touché(s), expire dans $duree min"
        # Chaos Mesh lève la panne seul, mais ne repose pas le réglage de base :
        # sans lui, le consommateur serait mille fois trop rapide pour toute
        # campagne suivante. Le retrait est donc programmé ici même, comme pour
        # « charge » ; un pilote qui retire avant l'heure annule le minuteur.
        if [ -n "$base" ]; then
            nohup bash -c "sleep $((duree * 60 + 30)); [ -f '$ETAT' ] && JOURNAL_OFF=1 bash '$_ici/panne.sh' retirer" \
                >/dev/null 2>&1 < /dev/null &
            sed -i "s/^MINUTEUR=.*/MINUTEUR='$!'/" "$ETAT"
            say "le réglage de base ($base ms) sera reposé à l'expiration, par un minuteur sur le master"
        fi
        return 0
    fi
    consigner "$demande" "" injection lenteur "$intensite" "$CONSO x$n -> $BASE_LABEL" chaos-mesh/networkchaos NON_CONFIRMEE
    warn "Chaos Mesh n'a pas confirmé en 60 s :  kubectl describe networkchaos panne-lenteur -n $NS"
    return 1
}

millicoeurs_libres() {   # <nœud> → millicœurs allouables que personne ne demande encore
    local alloc; alloc=$(kubectl get node "$1" -o jsonpath='{.status.allocatable.cpu}' 2>/dev/null)
    [ -n "$alloc" ] || return 1
    { echo "$alloc"
      kubectl get pods -A --field-selector "spec.nodeName=$1,status.phase!=Succeeded,status.phase!=Failed" \
          -o jsonpath='{range .items[*]}{range .spec.containers[*]}{.resources.requests.cpu}{"\n"}{end}{end}' 2>/dev/null
    } | awk 'function m(v) { return v ~ /m$/ ? substr(v, 1, length(v) - 1) + 0 : v * 1000 }
             NR == 1 { a = m($1); next }  NF { u += m($1) }  END { print int(a - u) }'
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
    # nodeName contourne l'ordonnanceur : c'est le kubelet qui refuse un pod
    # dont la demande dépasse ce qui reste allouable (mesuré : 2 cœurs demandés,
    # 1,7 libres → « OutOfcpu »). La demande est donc plafonnée à ce qui reste,
    # moins une marge. Elle ne fixe que le poids du voisin face aux autres pods
    # quand tout le monde veut du CPU ; le stress occupe de toute façon les
    # $coeurs cœurs.
    local libre demande_m=$((intensite * 1000)); libre=$(millicoeurs_libres "$cible")
    if [ -n "$libre" ] && [ "$demande_m" -gt $((libre - 100)) ]; then
        demande_m=$(( (libre - 100) / 100 * 100 ))
        [ "$demande_m" -ge 100 ] || fail "« $cible » n'a plus de CPU allouable (${libre}m libres) : pas de place pour un voisin"
        warn "« $cible » n'a que ${libre}m allouables libres : le voisin en réclame ${demande_m}m au lieu de $intensite cœur(s)"
    fi
    local sur; sur=$(repliques | awk -F'\t' -v h="$cible" '$2==h {print $1}' | paste -sd, -)
    [ -n "$sur" ] || warn "aucune réplique de $CONSO sur « $cible » : la file ne sentira rien"

    say "cause  : hote — un voisin occupe les $coeurs cœurs de « $cible » en en réclamant ${demande_m}m, pendant $duree min"
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
        requests: { cpu: "${demande_m}m", memory: 64Mi }
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
    say "outil  : SIGSTOP sur le processus Java, envoyé depuis la machine par le démon Chaos Mesh ; levée programmée là aussi"
    local demande; demande=$(maintenant)
    ecrire_etat CAUSE=blocage OUTIL=sigstop "CIBLE=$cible" "POD=$cible" "HOTE=$hote" INTENSITE= \
                "DEBUT=$demande" "DUREE=$duree"
    local sortie
    sortie=$(sur_la_machine "$cible" "$PIDS_JAVA"'
[ -n "$p" ] || { echo "aucun processus java dans le conteneur $cid"; exit 1; }
kill -STOP $p || exit 1
nohup sh -c "sleep $2; kill -CONT $p" >/dev/null 2>&1 &
sleep 1
for i in $p; do read -r _ _ s _ < /proc/$i/stat && echo "$i $s"; done' "$((duree * 60))" 2>&1)
    if [ $? -eq 0 ] && printf '%s\n' "$sortie" | grep -q ' T$'; then
        consigner "$demande" "$(maintenant)" injection blocage "" "$cible@$hote" sigstop confirmee
        ok "injectée — processus $(printf '%s\n' "$sortie" | grep ' T$' | cut -d' ' -f1 | paste -sd, -) gelé(s), levée dans $duree min"
        return 0
    fi
    printf '%s\n' "$sortie" | sed 's/^/      /' >&2
    consigner "$demande" "" injection blocage "" "$cible@$hote" sigstop NON_CONFIRMEE
    warn "le gel n'est pas confirmé (aucun processus à l'état T) — le démon Chaos Mesh est-il sur $hote ? chaos.sh status"
    return 1
}

# Un objet NEUF, et pas yaml_retard (mysql.sh) : celui-ci retarde ce qu'un
# déploiement envoie VERS la base ; posé sur la base, il ne retarderait que son
# trafic vers elle-même. Ici le retard est sur la SORTIE du pod de la base, vers
# les pods de train-ticket qui ne sont pas des pods de la base : ses clients le
# voient à chaque échange, ses suiveuses non. Le pod est désigné par son nom, pas
# par role=leader, pour que la panne ne suive pas un nouveau leader.
injecter_base() {
    local duree="$1" intensite="${2:-75}" cible="$3"
    [ -z "$cible" ] || fail "--cible est sans objet pour « base » : la panne vise toujours $BASE_POD"
    [ "$intensite" -gt 0 ] || fail "--intensite : au moins 1 ms"
    local vu; vu=$(base_leader) || fail "$BASE_POD n'est pas le leader ($vu) : la panne viserait une suiveuse — refusé"
    local noeud; noeud=$(kubectl get pod "$BASE_POD" -n "$NS" -o jsonpath='{.spec.nodeName}' 2>/dev/null)
    demon_sur "$noeud" || fail "Pas de démon Chaos Mesh sur « $noeud », le nœud de $BASE_POD — chaos.sh status"
    local cle="${BASE_LABEL%%=*}" valeur="${BASE_LABEL#*=}"
    # Les adresses des clients en marche : ce que la cible doit contenir, en entier.
    local ips_clients clients
    ips_clients=$(kubectl get pods -n "$NS" -l "$cle notin ($valeur)" --field-selector=status.phase=Running \
        --no-headers -o custom-columns=:status.podIP 2>/dev/null | grep -v '<none>' | grep .)
    clients=$(printf '%s\n' "$ips_clients" | grep -c .)
    [ "$clients" -gt 0 ] || fail "Aucun pod client de la base en marche dans $NS"
    # Les suiveuses : il en faut au moins une avec son adresse, sinon le contrôle
    # « aucune suiveuse retardée » passerait à vide.
    local suiveuses; suiveuses=$(kubectl get pods -n "$NS" -l "$BASE_LABEL" --no-headers \
        -o custom-columns=:metadata.name,:status.podIP 2>/dev/null | awk -v b="$BASE_POD" '$1 != b && $2 ~ /^[0-9]/ {print $2}')
    [ -n "$suiveuses" ] || fail "Aucune suiveuse de la base lue (kubectl -l $BASE_LABEL) : contrôle impossible — refusé"

    say "cause  : base — $BASE_POD (sur $noeud) répond $intensite ms plus tard à ses $clients pods clients, pendant $duree min ; ses suiveuses ne sont pas retardées"
    say "outil  : Chaos Mesh NetworkChaos $NS/panne-base, durée ${duree}m"
    local demande; demande=$(maintenant)
    ecrire_etat CAUSE=base OUTIL=chaos-mesh "CIBLE=$BASE_POD@$noeud -> $clients clients" "INTENSITE=$intensite" \
                "DEBUT=$demande" "DUREE=$duree"
    kubectl apply -f - >/dev/null <<EOF || fail "Chaos Mesh a refusé l'objet — voir ci-dessus."
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: panne-base
  namespace: $NS
  labels: { panne: base }
spec:
  action: delay
  mode: all
  selector:
    pods:
      $NS: [ "$BASE_POD" ]
  direction: to
  target:
    mode: all
    selector:
      namespaces: [ "$NS" ]
      expressionSelectors:
        - { key: "$cle", operator: NotIn, values: [ "$valeur" ] }
      podPhaseSelectors: [ "Running" ]
  delay:
    latency: "${intensite}ms"
    correlation: "0"
    jitter: "0ms"
  duration: "${duree}m"
EOF
    local registre_cible="$BASE_POD@$noeud -> $clients clients"
    if attendre_injection networkchaos "$NS" panne-base 60; then
        # Ce que Chaos Mesh a vraiment posé : le retard, et la liste des adresses,
        # qui doit contenir chaque client et aucune suiveuse (relue une fois après
        # 5 s si un client manque : la liste peut arriver un peu après).
        local retard adresses n_adr s fuite="" manque="" essai
        for essai in 1 2; do
            retard=$(kubectl get podnetworkchaos "$BASE_POD" -n "$NS" \
                -o jsonpath="{.spec.tcs[?(@.source==\"$NS/panne-base\")].delay.latency}" 2>/dev/null)
            adresses=$(adresses_retardees_base); n_adr=$(printf '%s\n' "$adresses" | grep -c .)
            fuite=""; manque=""
            for s in $suiveuses; do printf '%s\n' "$adresses" | grep -qxF "$s" && fuite="$fuite $s"; done
            for s in $ips_clients; do printf '%s\n' "$adresses" | grep -qxF "$s" || manque="$manque $s"; done
            [ -n "$manque" ] && [ "$essai" = "1" ] && { sleep 5; continue; }
            break
        done
        registre_cible="$BASE_POD@$noeud -> $clients clients, $n_adr adresses"
        if [ -n "$fuite" ] || [ -n "$manque" ] || [ "$retard" != "${intensite}ms" ]; then
            kubectl delete networkchaos panne-base -n "$NS" --ignore-not-found --timeout=90s >/dev/null 2>&1
            consigner "$demande" "" injection base "$intensite" "$registre_cible" chaos-mesh/networkchaos NON_CONFIRMEE
            warn "objet posé mais pas comme prévu (retard « ${retard:-aucun} », $n_adr adresse(s)${fuite:+, suiveuse(s) retardée(s) :$fuite}${manque:+, client(s) non retardé(s) :$manque}) : retiré"
            return 1
        fi
        consigner "$demande" "$(maintenant)" injection base "$intensite" "$registre_cible" chaos-mesh/networkchaos confirmee
        ok "injectée — $retard sur ce que $BASE_POD envoie à $n_adr adresses (les $clients pods clients, aucune suiveuse), expire dans $duree min"
        return 0
    fi
    # Non confirmée : l'objet est retiré, pour qu'aucune panne non vérifiée ne
    # reste en place pendant des minutes notées « non confirmées ».
    kubectl delete networkchaos panne-base -n "$NS" --ignore-not-found --timeout=90s >/dev/null 2>&1
    consigner "$demande" "" injection base "$intensite" "$registre_cible" chaos-mesh/networkchaos NON_CONFIRMEE
    warn "Chaos Mesh n'a pas confirmé en 60 s : objet retiré (kubectl get events -n $NS pour la raison)"
    return 1
}

# Le leurre et le réseau, défaits ensemble (échec, retrait, restes).
# Tente les trois retraits, 1 si l'un a échoué : le stress du leurre, puis le
# retard de X (les deux finissent ensemble), puis le pod leurre, le plus lent à
# partir (son sh ignore SIGTERM : 30 s de délai de grâce) et qui ne fait rien.
defaire_reseau() {
    local r=0
    kubectl delete stresschaos panne-leurre -n "$VOISIN_NS" --ignore-not-found --timeout=90s >/dev/null 2>&1 || r=1
    kubectl delete networkchaos panne-reseau-replique panne-reseau -n "$NS" --ignore-not-found --timeout=90s >/dev/null 2>&1 || r=1
    kubectl delete pod voisin-leurre -n "$VOISIN_NS" --ignore-not-found --timeout=90s >/dev/null 2>&1 || r=1
    return $r
}
defaire_reseau_dit() {   # la même, avec ce qu'on peut en dire à l'écran
    defaire_reseau && return 0
    warn "un objet de la panne résiste au retrait — $0 etat ; chaos.sh status"
    return 1
}

# Le chemin de X vers les données (écart 3, journal D.5) : la réplique de X est
# retardée sur tout ce qu'elle envoie (sans cible) ; les autres pods de l'espace
# applicatif sur X, hors de la base, seulement vers la base (pods et adresses de
# service). Sans perte ni gigue. Le trafic entre pods de X n'est pas retardé,
# sauf celui qui part de la réplique.
injecter_reseau() {
    local duree="$1" intensite="$2" cible="$3"
    [ -n "$intensite" ] || fail "--intensite est exigée pour « reseau » (millisecondes)"
    [ "$intensite" -gt 0 ] || fail "--intensite : au moins 1 ms"
    lire_couple "$cible" || fail "--cible « $cible » : il faut « X:Y », deux machines différentes"
    local x="$COUPLE_X" y="$COUPLE_Y"
    local vu; vu=$(base_leader) || fail "$BASE_POD n'est pas le leader ($vu) — refusé"
    demon_sur "$x" || fail "Pas de démon Chaos Mesh sur « $x »"
    demon_sur "$y" || fail "Pas de démon Chaos Mesh sur « $y »"
    local sur_x; sur_x=$(pods_de_la_machine "$x")
    [ -n "$sur_x" ] || fail "Aucun pod de $NS en marche sur « $x »"
    [ -z "$(retards_reseau)" ] || fail "Des pods portent déjà un retard de panne-reseau — d'abord : $0 retirer"
    local coeurs libre demande_m=2000
    coeurs=$(kubectl get node "$y" -o jsonpath='{.status.capacity.cpu}' 2>/dev/null)
    case "$coeurs" in ''|*[!0-9]*) fail "Nombre de cœurs de « $y » illisible" ;; esac
    libre=$(millicoeurs_libres "$y")
    [ -z "$libre" ] || [ "$demande_m" -le $((libre - 100)) ] || demande_m=$(( (libre - 100) / 100 * 100 ))
    [ "$demande_m" -ge "$LEURRE_MIN_M" ] \
        || fail "« $y » n'a que ${libre}m libres : le leurre ne réclamerait que ${demande_m}m (< ${LEURRE_MIN_M}m)"
    local rep_x rep_y n_x
    rep_x=$(repliques | awk -F'\t' -v h="$x" '$2==h {print $1}' | paste -sd, -)
    rep_y=$(repliques | awk -F'\t' -v h="$y" '$2==h {print $1}' | paste -sd, -)
    n_x=$(printf '%s\n' "$sur_x" | wc -l)
    case "$rep_x" in ''|*,*) fail "il faut exactement une réplique de $CONSO sur « $x » (lu : ${rep_x:-aucune})" ;; esac
    [ -z "$rep_y" ] || warn "le leurre « $y » porte une réplique ($rep_y)"
    local ips_base; ips_base=$(ips_devant_mysql)
    [ -n "$ips_base" ] || fail "adresses de service devant la base illisibles"

    say "cause  : reseau — la réplique $rep_x (sur « $x ») envoie tout avec $intensite ms de retard ; les $((n_x - 1)) autres pods de $NS sur « $x » envoient à la base avec $intensite ms de retard ; pendant $duree min"
    say "         leurre : un voisin occupe les $coeurs cœurs de « $y » en en réclamant ${demande_m}m"
    say "outil  : Chaos Mesh NetworkChaos $NS/panne-reseau-replique (la réplique de $x, tout) + $NS/panne-reseau (les autres pods de $x, vers la base) + pod $VOISIN_NS/voisin-leurre + StressChaos $VOISIN_NS/panne-leurre"
    local demande registre_cible="$x@leurre:$y"; demande=$(maintenant)
    # Un objet refusé : tout retirer, une ligne au registre, sortir en échec.
    refus_reseau() {
        defaire_reseau_dit
        consigner "$demande" "" injection reseau "$intensite" "$registre_cible" chaos-mesh/networkchaos+stresschaos NON_CONFIRMEE
        fail "$1"
    }
    ecrire_etat CAUSE=reseau OUTIL=chaos-mesh "CIBLE=$registre_cible" "HOTE=$x" "LEURRE=$y" \
                "INTENSITE=$intensite" "DEBUT=$demande" "DUREE=$duree"
    kubectl create namespace "$VOISIN_NS" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
    kubectl apply -f - >/dev/null <<EOF || refus_reseau "Le pod voisin-leurre a été refusé — voir ci-dessus."
apiVersion: v1
kind: Pod
metadata:
  name: voisin-leurre
  namespace: $VOISIN_NS
  labels: { app: voisin-leurre, panne: reseau }
spec:
  nodeName: $y
  restartPolicy: Never
  containers:
    - name: voisin
      image: $VOISIN_IMAGE
      command: ["sh", "-c", "while true; do sleep 3600; done"]
      resources:
        requests: { cpu: "${demande_m}m", memory: 64Mi }
EOF
    local reste=90 phase=""
    while [ "$reste" -gt 0 ]; do
        phase=$(kubectl get pod voisin-leurre -n "$VOISIN_NS" -o jsonpath='{.status.phase}' 2>/dev/null)
        [ "$phase" = "Running" ] && break
        sleep 3; reste=$((reste - 3))
    done
    if [ "$phase" != "Running" ]; then
        defaire_reseau_dit
        consigner "$demande" "" injection reseau "$intensite" "$registre_cible" chaos-mesh/networkchaos+stresschaos NON_CONFIRMEE
        warn "le voisin-leurre n'a pas démarré sur « $y » (phase : ${phase:-absent}) : injection abandonnée"
        return 1
    fi
    # L'instant de la panne est la pose des deux objets (le pod leurre attendait
    # sans rien faire) : la ligne du registre reste ainsi à moins de 120 s du
    # déroulé (fautifs.injections), même si le leurre a mis 90 s à démarrer.
    demande=$(maintenant)
    ecrire_etat CAUSE=reseau OUTIL=chaos-mesh "CIBLE=$registre_cible" "HOTE=$x" "LEURRE=$y" \
                "INTENSITE=$intensite" "DEBUT=$demande" "DUREE=$duree"
    # Les trois objets partent ensemble ; ils doivent être confirmés dans les mêmes 60 s.
    # La réplique de X : tout ce qu'elle envoie (sans cible : ce retard s'ajoute à
    # son réglage de 140 ms vers la base, comme pour M0). Les autres pods de X :
    # vers la base seulement (avec cible ; jamais sur la réplique, où deux règles à
    # cible sur les mêmes adresses ne s'additionnent pas : une seule s'appliquerait).
    kubectl apply -f - >/dev/null <<EOF || refus_reseau "Chaos Mesh a refusé un objet — voir ci-dessus."
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: panne-reseau-replique
  namespace: $NS
  labels: { panne: reseau }
spec:
  action: delay
  mode: all
  selector:
    namespaces: [ "$NS" ]
    nodes: [ "$x" ]
    labelSelectors: { app: "$CONSO" }
    podPhaseSelectors: [ "Running" ]
  direction: to
  delay:
    latency: "${intensite}ms"
    correlation: "0"
    jitter: "0ms"
  duration: "${duree}m"
---
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: panne-reseau
  namespace: $NS
  labels: { panne: reseau }
spec:
  action: delay
  mode: all
  selector:
    namespaces: [ "$NS" ]
    nodes: [ "$x" ]
    expressionSelectors:
      - { key: app, operator: NotIn, values: [ "$CONSO", "${MYSQL_LABEL#*=}" ] }
    podPhaseSelectors: [ "Running" ]
  direction: to
  target:
    mode: all
    selector:
      namespaces: [ "$NS" ]
      labelSelectors: { ${MYSQL_LABEL%%=*}: "${MYSQL_LABEL#*=}" }
  externalTargets:
$(for ip in $ips_base; do echo "    - \"$ip\""; done)
  delay:
    latency: "${intensite}ms"
    correlation: "0"
    jitter: "0ms"
  duration: "${duree}m"
---
apiVersion: chaos-mesh.org/v1alpha1
kind: StressChaos
metadata:
  name: panne-leurre
  namespace: $VOISIN_NS
  labels: { panne: reseau }
spec:
  mode: all
  selector:
    namespaces: [ "$VOISIN_NS" ]
    labelSelectors: { app: voisin-leurre }
  stressors:
    cpu:
      workers: $coeurs
      load: 100
  duration: "${duree}m"
EOF
    local s0="" s1="" s2=""; reste=60
    while [ "$reste" -gt 0 ]; do
        s0=$(kubectl get networkchaos panne-reseau-replique -n "$NS" -o jsonpath='{.status.conditions[?(@.type=="AllInjected")].status}' 2>/dev/null)
        s1=$(kubectl get networkchaos panne-reseau -n "$NS" -o jsonpath='{.status.conditions[?(@.type=="AllInjected")].status}' 2>/dev/null)
        s2=$(kubectl get stresschaos panne-leurre -n "$VOISIN_NS" -o jsonpath='{.status.conditions[?(@.type=="AllInjected")].status}' 2>/dev/null)
        [ "$s0" = "True" ] && [ "$s1" = "True" ] && [ "$s2" = "True" ] && break
        sleep 3; reste=$((reste - 3))
    done
    # Ce que Chaos Mesh a vraiment posé : la réplique de X par panne-reseau-replique,
    # chaque autre pod de X par panne-reseau, au retard demandé et une seule fois ;
    # aucun pod d'une autre machine (relu une fois après 5 s si un pod manque).
    local poses manque="" fuite="" essai p o attendu base_x
    base_x=$(kubectl get pods -n "$NS" -l "$MYSQL_LABEL" --field-selector="spec.nodeName=$x" --no-headers \
        -o custom-columns=:metadata.name 2>/dev/null)
    for essai in 1 2; do
        poses=$(retards_reseau); manque=""; fuite=""
        for p in $sur_x; do
            attendu="$p ${intensite}ms panne-reseau"
            [ "$p" = "$rep_x" ] && attendu="$p ${intensite}ms panne-reseau-replique"
            printf '%s\n' "$base_x" | grep -qx "$p" && attendu=""   # la base : rien
            [ "$(printf '%s\n' "$poses" | awk -v p="$p" '$1 == p' )" = "$attendu" ] || manque="$manque $p"
        done
        for p in $(printf '%s\n' "$poses" | cut -d' ' -f1); do
            printf '%s\n' "$sur_x" | grep -qx "$p" || fuite="$fuite $p"
        done
        [ -n "$manque" ] && [ "$essai" = "1" ] && { sleep 5; continue; }
        break
    done
    if [ "$s0" = "True" ] && [ "$s1" = "True" ] && [ "$s2" = "True" ] && [ -z "$manque" ] && [ -z "$fuite" ]; then
        consigner "$demande" "$(maintenant)" injection reseau "$intensite" "$registre_cible" chaos-mesh/networkchaos+stresschaos confirmee
        ok "injectée — $intensite ms : tout ce qu'envoie $rep_x, et ce que les $((n_x - 1)) autres pods de « $x » envoient à la base ; leurre sur « $y » ; expire dans $duree min"
        return 0
    fi
    local retire="tout est retiré"; defaire_reseau_dit || retire="le retrait a échoué en partie"
    consigner "$demande" "" injection reseau "$intensite" "$registre_cible" chaos-mesh/networkchaos+stresschaos NON_CONFIRMEE
    warn "pas confirmée en 60 s (réplique : ${s0:-?}, autres pods : ${s1:-?}, leurre : ${s2:-?}${manque:+, pods sans le retard :$manque}${fuite:+, pods hors de $x retardés :$fuite}) : $retire"
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
        charge|lenteur|hote|blocage|base|reseau) ;;
        *) fail "Cause inconnue « $cause » — charge, lenteur, hote, blocage, base ou reseau" ;;
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
degeler() {   # <pod> — CONT depuis la machine, puis vérifie qu'aucun processus Java n'est resté en T
    sur_la_machine "$1" "$PIDS_JAVA"'
[ -n "$p" ] && kill -CONT $p' >/dev/null || return 1
    ! etat_java "$1" | grep -q ' T$'
}

nettoyer_residus() {
    local trouve=0
    if kubectl get networkchaos panne-lenteur -n "$NS" >/dev/null 2>&1; then
        kubectl delete networkchaos panne-lenteur -n "$NS" --timeout=90s >/dev/null 2>&1 \
            && say "objet networkchaos/panne-lenteur supprimé" || warn "networkchaos/panne-lenteur résiste"
        trouve=1
    fi
    if kubectl get networkchaos panne-base -n "$NS" >/dev/null 2>&1; then
        kubectl delete networkchaos panne-base -n "$NS" --timeout=90s >/dev/null 2>&1 \
            && say "objet networkchaos/panne-base supprimé" || warn "networkchaos/panne-base résiste"
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
    if kubectl get networkchaos panne-reseau -n "$NS" >/dev/null 2>&1 \
            || kubectl get networkchaos panne-reseau-replique -n "$NS" >/dev/null 2>&1 \
            || kubectl get stresschaos panne-leurre -n "$VOISIN_NS" >/dev/null 2>&1 \
            || kubectl get pod voisin-leurre -n "$VOISIN_NS" >/dev/null 2>&1; then
        defaire_reseau && say "panne-reseau(-replique), panne-leurre, voisin-leurre supprimés" || warn "un objet de « reseau » résiste"
        trouve=1
    fi
    local pod
    for pod in $(repliques | cut -f1); do
        if etat_java "$pod" | grep -q ' T$'; then
            degeler "$pod" && say "réplique $pod dégelée" || warn "réplique $pod toujours gelée"
            trouve=1
        fi
    done
    # Des adresses encore retardées sur la base alors que l'objet a disparu :
    # Chaos Mesh ne les a pas retirées, rien ici ne sait le faire sans risque.
    if [ -n "$(adresses_retardees_base)" ]; then
        warn "$BASE_POD porte encore un retard de panne-base sans objet pour le porter :"
        warn "  kubectl get podnetworkchaos $BASE_POD -n $NS -o yaml ; chaos.sh status — à régler à la main"
        return 1
    fi
    # Des pods encore retardés par panne-reseau alors que l'objet a disparu.
    if [ -n "$(retards_reseau)" ]; then
        warn "des pods portent encore un retard de panne-reseau sans objet pour le porter :"
        warn "  kubectl get podnetworkchaos -n $NS ; chaos.sh status — à régler à la main"
        return 1
    fi
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
            [ -n "${MINUTEUR:-}" ] && [ "$MINUTEUR" != "$PPID" ] && kill "$MINUTEUR" >/dev/null 2>&1
            # Le réglage de base est reposé AVANT de lever la panne : même
            # raison qu'à l'injection, jamais un instant sans retard.
            if [ -n "${RETARD_BASE:-}" ]; then
                say "Retour au réglage de base ($RETARD_BASE ms)…"
                JOURNAL_OFF=1 bash "$CONSOMMATEUR" dimensionner --retard "$RETARD_BASE" >/dev/null 2>&1 \
                    && say "réglage de base reposé" || { warn "réglage de base NON reposé :  consommateur.sh dimensionner --retard $RETARD_BASE"; resultat=ECHEC; }
            fi
            kubectl delete networkchaos panne-lenteur -n "$NS" --ignore-not-found --timeout=90s >/dev/null 2>&1 \
                || resultat=ECHEC ;;
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
        base)
            # Le réglage de base des répliques n'est jamais touché ici.
            kubectl delete networkchaos panne-base -n "$NS" --ignore-not-found --timeout=90s >/dev/null 2>&1 \
                || resultat=ECHEC
            # Chaos Mesh retire le retard du pod de la base peu après l'objet.
            local reste=30
            while [ "$reste" -gt 0 ] && [ -n "$(adresses_retardees_base)" ]; do sleep 3; reste=$((reste - 3)); done
            [ -z "$(adresses_retardees_base)" ] || { warn "$BASE_POD porte encore le retard de panne-base"; resultat=ECHEC; } ;;
        reseau)
            # Les paquets jetés de la panne se lisent maintenant : Chaos Mesh
            # refait la file de chaque pod au retrait, compteur compris.
            # Si Chaos Mesh a déjà levé la panne (plus aucun pod retardé), la file
            # est déjà refaite : ce relevé ne compte pas.
            say "réseau de $HOTE avant le retrait : $(reseau_de_la_machine "$HOTE" || echo illisible) ; pods encore retardés : $(retards_reseau | wc -l)"
            defaire_reseau_dit || resultat=ECHEC
            # Chaos Mesh retire le retard des pods peu après l'objet.
            local reste=30
            while [ "$reste" -gt 0 ] && [ -n "$(retards_reseau)" ]; do sleep 3; reste=$((reste - 3)); done
            [ -z "$(retards_reseau)" ] || { warn "des pods portent encore le retard de panne-reseau"; resultat=ECHEC; } ;;
        *)
            # L'état reste : « etat » continue de bloquer le départ suivant.
            consigner "$demande" "$(maintenant)" retrait "$CAUSE" "${INTENSITE:-}" "$CIBLE" "$OUTIL" ECHEC
            warn "cause « $CAUSE » inconnue de cette copie de panne.sh : rien n'a été retiré, l'état est gardé"
            return 1 ;;
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
            base)    [ "$(kubectl get networkchaos panne-base -n "$NS" -o jsonpath='{.status.conditions[?(@.type=="AllInjected")].status}' 2>/dev/null)" = "True" ] \
                         && say "Chaos Mesh : injectée" || say "Chaos Mesh : pas (ou plus) injectée — expirée ?" ;;
            reseau)  say "pods retardés par panne-reseau : $(retards_reseau | wc -l) (sur $HOTE : $(pods_de_la_machine "$HOTE" | wc -l) pods)"
                     [ "$(kubectl get stresschaos panne-leurre -n "$VOISIN_NS" -o jsonpath='{.status.conditions[?(@.type=="AllInjected")].status}' 2>/dev/null)" = "True" ] \
                         && say "leurre sur $LEURRE : injecté" || say "leurre sur $LEURRE : pas (ou plus) injecté — expiré ?" ;;
            charge)  say "charge en cours : $(JOURNAL_OFF=1 bash "$LOADGEN" voyageurs 2>/dev/null | tr -d '[:space:]') voyageurs (retour prévu : $RETOUR)" ;;
        esac
        say "Pour lever :  $0 retirer"
        return 3
    fi
    say "Aucune injection en cours."
    kubectl get networkchaos panne-lenteur -n "$NS" >/dev/null 2>&1 && { warn "reste : networkchaos/panne-lenteur"; residus=1; }
    kubectl get networkchaos panne-base -n "$NS" >/dev/null 2>&1 && { warn "reste : networkchaos/panne-base"; residus=1; }
    [ -z "$(adresses_retardees_base)" ] || { warn "reste : $BASE_POD porte encore un retard de panne-base"; residus=1; }
    local echec gen obs
    echec=$(kubectl get podnetworkchaos "$BASE_POD" -n "$NS" -o jsonpath='{.status.failedMessage}' 2>/dev/null)
    gen=$(kubectl get podnetworkchaos "$BASE_POD" -n "$NS" -o jsonpath='{.metadata.generation}' 2>/dev/null)
    obs=$(kubectl get podnetworkchaos "$BASE_POD" -n "$NS" -o jsonpath='{.status.observedGeneration}' 2>/dev/null)
    [ -z "$echec" ] || { warn "reste possible : le démon n'a pas appliqué l'objet réseau de $BASE_POD ($echec)"; residus=1; }
    [ -z "$gen" ] || [ -z "$obs" ] || [ "$gen" = "$obs" ] \
        || { warn "reste possible : l'objet réseau de $BASE_POD n'est pas encore appliqué (génération $gen, vue $obs)"; residus=1; }
    kubectl get stresschaos panne-hote -n "$VOISIN_NS" >/dev/null 2>&1 && { warn "reste : stresschaos/panne-hote"; residus=1; }
    kubectl get pod voisin-bruyant -n "$VOISIN_NS" >/dev/null 2>&1 && { warn "reste : pod voisin-bruyant"; residus=1; }
    kubectl get networkchaos panne-reseau -n "$NS" >/dev/null 2>&1 && { warn "reste : networkchaos/panne-reseau"; residus=1; }
    kubectl get networkchaos panne-reseau-replique -n "$NS" >/dev/null 2>&1 && { warn "reste : networkchaos/panne-reseau-replique"; residus=1; }
    kubectl get stresschaos panne-leurre -n "$VOISIN_NS" >/dev/null 2>&1 && { warn "reste : stresschaos/panne-leurre"; residus=1; }
    kubectl get pod voisin-leurre -n "$VOISIN_NS" >/dev/null 2>&1 && { warn "reste : pod voisin-leurre"; residus=1; }
    [ -z "$(retards_reseau)" ] || { warn "reste : des pods portent encore un retard de panne-reseau"; residus=1; }
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
temoin_app() {   # [court] : sans rien demander à la base elle-même (les veilles)
    local court="${1:-}"
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
    kubectl top nodes --no-headers 2>/dev/null \
        | awk '{printf "      %-10s cpu %s (%s)  mém %s (%s)\n", $1, $2, $3, $4, $5}'
    # Le leader de la base (la panne « base » le suppose), et la dérive : le cpu du
    # service des commandes monte avec la taille de sa table.
    local vu; if vu=$(base_leader); then echo "  base : $BASE_POD est le leader ($vu)"
    else echo "  base : ATTENTION, $BASE_POD n'est pas le leader ($vu)"; fi
    echo "  ts-order-service : $(kubectl top pods -n "$NS" -l app=ts-order-service --no-headers 2>/dev/null \
        | awk '{printf "cpu %s  mém %s ", $2, $3}')"
    # Compter les commandes et lire les paquets jetés touchent le pod de la base :
    # seulement aux témoins (avant, pendant, après), jamais aux veilles.
    [ "$court" = "court" ] || echo "  commandes : $(sql "SELECT COUNT(*) FROM orders;" 2>/dev/null | tail -1) lignes dans orders"
    # Ce qui est réellement posé sur le chemin des répliques et à la sortie de la base.
    local r p poses="" reglage pb jetes
    for r in $(printf '%s\n' "$liste" | cut -f1); do p=$(reglage_pose "$r"); poses="$poses ${p:-rien}"; done
    reglage=$(kubectl get networkchaos "$REGLAGE" -n "$NS" -o jsonpath='{.spec.delay.latency}' 2>/dev/null)
    echo "  réglage de base : ${reglage:-absent} ; posé sur les répliques :$poses"
    pb=$(kubectl get podnetworkchaos "$BASE_POD" -n "$NS" \
        -o jsonpath="{.spec.tcs[?(@.source==\"$NS/panne-base\")].delay.latency}" 2>/dev/null)
    if [ "$court" = "court" ]; then jetes="non lus (veille)"; else jetes=$(jetes_base) || jetes="illisible"; fi
    echo "  panne-base posée : ${pb:-rien} vers $(adresses_retardees_base | grep -c .) adresses ; paquets jetés à la sortie de la base : ${jetes:-illisible}"
    # Le réseau des pods, par machine (retard de panne-reseau posé, paquets jetés,
    # retransmissions) : aux témoins complets seulement, une lecture par machine.
    echo "  panne-reseau posée sur $(retards_reseau | wc -l) pod(s)"
    if [ "$court" != "court" ]; then
        local m
        echo "  réseau des pods, par machine (jetés : depuis la dernière pose d'une file par Chaos Mesh ; retrans : depuis le démarrage des pods) :"
        for m in $(machines_de_travail); do echo "      $m $(reseau_de_la_machine "$m" || echo illisible)"; done
    fi
    if [ -f "$ETAT" ]; then . "$ETAT"; echo "  injection : $CAUSE depuis $DEBUT"; else echo "  injection : aucune"; fi
}

libres_app() {   # « machine millicœurs_libres » pour chaque nœud
    local m
    for m in $(kubectl get nodes --no-headers -o custom-columns=:metadata.name 2>/dev/null); do
        echo "$m $(millicoeurs_libres "$m")"
    done
}

# ------------------------------------------------------------------------------
case "${1:-etat}" in
    verifier) shift; verifier_app "$@" ;;
    injecter) shift; injecter_app "$@" ;;
    retirer)  retirer_app ;;
    etat)     etat_app ;;
    temoin)   shift; temoin_app "$@" ;;
    leader)   base_leader ;;
    libres)   libres_app ;;
    *) echo "Usage: $0 {verifier <cause> [--cible <x>]…|injecter <cause> [--duree <min>] [--intensite <n>] [--cible <x>]|retirer|etat|temoin|leader|libres}" >&2; exit 2 ;;
esac
