#!/bin/bash
# ==============================================================================
#  apps/chaos.sh — l'injecteur de pannes
# ==============================================================================
#
#  POURQUOI UN OUTIL PLUTÔT QUE DES COMMANDES
#
#  Les quatre causes étudiées peuvent toutes s'injecter à la main. Deux le font
#  mal, et c'est ce qui décide :
#
#    ralentir un service    Baisser la limite CPU déclenche un redémarrage
#                           roulant. Nouveaux pods, nouveaux identifiants, donc
#                           NOUVEAUX NŒUDS dans le graphe : le redémarrage se
#                           mélange à la panne qu'on voulait mesurer. Chaos Mesh
#                           agit dans le pod existant — retard réseau, charge
#                           CPU — sans redémarrer quoi que ce soit.
#
#    saturer un hôte        Il faut une charge qui occupe TOUS les cœurs pour
#                           une durée exacte, et qui s'arrête d'elle-même.
#                           Chaos Mesh porte la durée dans l'objet injecté.
#
#  Et une raison qui n'est pas technique : « injecté avec Chaos Mesh 2.x » se
#  vérifie, « injecté par un script maison » se croit sur parole.
#
#  Le blocage d'une réplique, lui, n'a pas besoin de Chaos Mesh : un SIGSTOP
#  suffit, les pods de train-ticket n'ayant pas de sonde de vivacité. C'est
#  apps/panne.sh qui injecte les quatre causes ; ce script-ci installe l'outil.
#
#  À INSTALLER AVANT LA CAMPAGNE DE RÉFÉRENCE
#
#  Le démon tourne sur CHAQUE nœud, y compris ceux qu'on mesure. Son coût est
#  faible mais réel. Il doit donc être présent des deux côtés — référence saine
#  ET campagnes de panne — sinon la différence entre les deux contient son coût
#  à lui, mêlé à celui de la panne.
#
#  Usage (depuis le master) :
#      bash ~/autodeploy/apps/chaos.sh install
#      bash ~/autodeploy/apps/chaos.sh status
#      bash ~/autodeploy/apps/chaos.sh isolate <nœud>
#      bash ~/autodeploy/apps/chaos.sh uninstall
#
#  Variables reconnues :
#    CHAOS_NAMESPACE   (défaut: chaos-mesh)
#    CHAOS_VERSION     (défaut: la plus récente — le script affiche laquelle,
#                       à figer dans .env pour rendre l'expérience rejouable)
#    CHAOS_RUNTIME     (défaut: détecté sur le cluster)
#    CHAOS_SOCKET      (défaut: déduit du moteur détecté)
#    CHAOS_DASHBOARD   (défaut: 0 — le tableau de bord consomme pour rien,
#                       les injections étant pilotées par script)
#    CHAOS_NODEPORT    (défaut: 30333) port du tableau de bord, s'il est activé
#    OBS_DEDICATED_NODE  le nœud de mesure, où placer le contrôleur
# ==============================================================================
set -uo pipefail

_ici="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$_ici/journal.sh" ] && JOURNAL_NOM="chaos" . "$_ici/journal.sh"

NAMESPACE="${CHAOS_NAMESPACE:-chaos-mesh}"
VERSION="${CHAOS_VERSION:-}"
DASHBOARD="${CHAOS_DASHBOARD:-0}"
NODEPORT="${CHAOS_NODEPORT:-30333}"
OBS_NODE="${OBS_DEDICATED_NODE:-}"
HELM="${OBS_HELM_BIN:-helm}"
DEPOT="https://charts.chaos-mesh.org"

say()  { echo "  [chaos] $*"; }
ok()   { echo "  [chaos] OK  $*"; }
warn() { echo "  [chaos] ATTENTION: $*" >&2; }
fail() { echo "  [chaos] ERREUR: $*" >&2; exit 1; }

# ------------------------------------------------------------------------------
# moteur_de_conteneurs — détecté, jamais supposé
# ------------------------------------------------------------------------------
# Le démon parle directement au moteur de conteneurs du nœud. Si le chemin de la
# prise est faux, il démarre, se déclare prêt, et échoue à la première injection
# — un échec tardif, au milieu d'une campagne. On lit donc le moteur réellement
# utilisé plutôt que de parier sur containerd.
# ------------------------------------------------------------------------------
moteur_de_conteneurs() {
    kubectl get nodes -o jsonpath='{.items[0].status.nodeInfo.containerRuntimeVersion}' 2>/dev/null \
        | cut -d: -f1
}

prise_du_moteur() {
    case "$1" in
        containerd) echo "/run/containerd/containerd.sock" ;;
        cri-o)      echo "/var/run/crio/crio.sock" ;;
        docker)     echo "/var/run/docker.sock" ;;
        *)          echo "" ;;
    esac
}

# ------------------------------------------------------------------------------
install_app() {
    command -v "$HELM" >/dev/null 2>&1 || fail "Binaire Helm « $HELM » introuvable sur le master."

    local moteur prise
    moteur="${CHAOS_RUNTIME:-$(moteur_de_conteneurs)}"
    [ -n "$moteur" ] || fail "Moteur de conteneurs indétectable. Force-le : CHAOS_RUNTIME=containerd"
    prise="${CHAOS_SOCKET:-$(prise_du_moteur "$moteur")}"
    [ -n "$prise" ] || fail "Moteur « $moteur » inconnu. Donne CHAOS_SOCKET=<chemin>."
    say "Moteur de conteneurs détecté : $moteur  (prise : $prise)"

    kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - >/dev/null

    $HELM repo add chaos-mesh "$DEPOT" >/dev/null 2>&1 || true
    $HELM repo update chaos-mesh >/dev/null 2>&1 || true

    local args=(
        --namespace "$NAMESPACE"
        --set "chaosDaemon.runtime=$moteur"
        --set "chaosDaemon.socketPath=$prise"
        --set "controllerManager.replicaCount=1"
        --wait --timeout 10m
    )
    [ -n "$VERSION" ] && args+=(--version "$VERSION")

    if [ "$DASHBOARD" = "1" ]; then
        args+=(--set "dashboard.create=true"
               --set "dashboard.service.type=NodePort"
               --set "dashboard.service.nodePort=$NODEPORT"
               --set "dashboard.securityMode=false")
        say "Tableau de bord activé sur le port $NODEPORT."
        warn "securityMode=false : le tableau de bord n'exige aucun jeton."
        warn "  Acceptable sur un banc de mesure fermé, jamais ailleurs."
    else
        args+=(--set "dashboard.create=false")
        say "Tableau de bord désactivé (CHAOS_DASHBOARD=1 pour l'activer)."
    fi

    # Le contrôleur sur le nœud de mesure : il n'appartient pas au système
    # étudié et n'a pas à consommer les ressources qui le portent. Le DÉMON, lui,
    # doit rester partout — il ne peut agir que sur le nœud où il tourne.
    if [ -n "$OBS_NODE" ] && kubectl get node "$OBS_NODE" >/dev/null 2>&1; then
        args+=(--set "controllerManager.nodeSelector.role=observability"
               --set "controllerManager.tolerations[0].key=dedicated"
               --set "controllerManager.tolerations[0].operator=Equal"
               --set "controllerManager.tolerations[0].value=observability"
               --set "controllerManager.tolerations[0].effect=NoSchedule"
               )
        say "Contrôleur placé sur le nœud de mesure « $OBS_NODE »."
    fi

    # Le démon tolère tout : il ne peut agir que sur la machine où il tourne, et
    # une liste de tolérances remplace celle du chart au lieu de s'y ajouter.
    args+=(--set "chaosDaemon.tolerations[0].operator=Exists")

    say "Installation…"
    $HELM upgrade --install chaos-mesh chaos-mesh/chaos-mesh "${args[@]}" || \
        fail "L'installation a échoué. Voir la sortie ci-dessus."

    local v; v=$($HELM list -n "$NAMESPACE" -o json 2>/dev/null \
                 | grep -o '"chart":"chaos-mesh-[^"]*"' | head -1 | cut -d- -f3- | tr -d '"')
    ok "Chaos Mesh installé — version du chart : ${v:-inconnue}"
    [ -z "$VERSION" ] && [ -n "$v" ] && \
        say "Fige-la pour rendre l'expérience rejouable :  CHAOS_VERSION=$v  dans .env"
    echo
    status_app
}

# ------------------------------------------------------------------------------
# status — prêt à injecter, ou seulement démarré ?
# ------------------------------------------------------------------------------
# Trois conditions, toutes nécessaires : les définitions d'injection, le
# contrôleur, et un démon sur chaque nœud — un nœud sans démon est inatteignable.
# ------------------------------------------------------------------------------
status_app() {
    echo
    kubectl get namespace "$NAMESPACE" >/dev/null 2>&1 || {
        say "Chaos Mesh n'est pas installé."
        say "  bash $0 install"
        return 0
    }

    local crds noeuds demons ctrl
    crds=$(kubectl get crd 2>/dev/null | grep -c "chaos-mesh.org")
    noeuds=$(kubectl get nodes --no-headers 2>/dev/null | wc -l)
    demons=$(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/component=chaos-daemon \
             --no-headers 2>/dev/null | grep -c "Running")
    ctrl=$(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/component=controller-manager \
           --no-headers 2>/dev/null | grep -c "Running")

    # La valeur d'abord : « printf » aligne sur les octets, et un libellé accentué
    # en compte plus qu'il n'affiche de caractères.
    printf "     %-7s %s\n" "$crds"              "types d'injection disponibles"
    printf "     %-7s %s\n" "$ctrl"              "contrôleur(s) en marche"
    printf "     %-7s %s\n" "$demons/$noeuds"    "démons — un par nœud"
    echo

    local pret=1
    [ "$crds" -gt 0 ]        || { warn "aucune définition d'injection — Chaos Mesh ne peut rien faire"; pret=0; }
    [ "$ctrl" -gt 0 ]        || { warn "le contrôleur ne tourne pas"; pret=0; }
    [ "$demons" = "$noeuds" ] || { warn "un démon manque : les nœuds sans démon ne peuvent pas être touchés"; pret=0; }
    [ "$pret" = "1" ] && ok "prêt à injecter" || warn "PAS prêt — n'injecte rien avant d'avoir corrigé."
    echo
    return 0
}

isolate_app() {
    local node="${1:-$OBS_NODE}"
    [ -n "$node" ] || fail "Indique le nœud : $0 isolate <nœud>"
    kubectl get node "$node" >/dev/null 2>&1 || fail "Nœud « $node » introuvable."
    local tol='[{"key":"dedicated","operator":"Equal","value":"observability","effect":"NoSchedule"}]'
    local sel='{"role":"observability"}'

    kubectl -n "$NAMESPACE" patch deploy chaos-controller-manager \
        -p "{\"spec\":{\"template\":{\"spec\":{\"nodeSelector\":$sel,\"tolerations\":$tol}}}}" >/dev/null 2>&1 \
        && say "contrôleur épinglé sur « $node »" \
        || warn "contrôleur introuvable — Chaos Mesh est-il installé ?"

    # Le démon reste sur tous les nœuds. « Exists » sans clé, car un patch de
    # tolérances remplace la liste au lieu de s'y ajouter.
    kubectl -n "$NAMESPACE" patch daemonset chaos-daemon \
        -p '{"spec":{"template":{"spec":{"tolerations":[{"operator":"Exists"}]}}}}' >/dev/null 2>&1 \
        && say "démon : tolère tous les nœuds"
    echo
    status_app
}

uninstall_app() {
    say "Suppression de Chaos Mesh…"
    $HELM uninstall chaos-mesh -n "$NAMESPACE" >/dev/null 2>&1 || true
    kubectl delete namespace "$NAMESPACE" --ignore-not-found --timeout=180s >/dev/null 2>&1 || true
    # Les définitions survivent à la désinstallation du chart et bloqueraient une
    # réinstallation propre.
    kubectl get crd -o name 2>/dev/null | grep "chaos-mesh.org" \
        | xargs -r kubectl delete --ignore-not-found >/dev/null 2>&1 || true
    ok "supprimé"
}

case "${1:-status}" in
    install)   install_app ;;
    status)    status_app ;;
    isolate)   shift; isolate_app "${1:-}" ;;
    uninstall) uninstall_app ;;
    *) echo "Usage: $0 {install|status|isolate <nœud>|uninstall}" >&2; exit 2 ;;
esac
