#!/bin/bash
# ==============================================================================
#  autodeploy_k8s — Déploiement automatisé d'un cluster Kubernetes sur SLICES-RI
#                   et des applications de microservices de démonstration.
#
#  Usage :  ./deploy.sh [--app otel-demo|train-ticket|both] [options]
#  Aide  :  ./deploy.sh --help
# ==============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# shellcheck source=lib/common.sh
source "$ROOT/lib/common.sh"
# shellcheck source=lib/slices.sh
source "$ROOT/lib/slices.sh"
# shellcheck source=lib/cluster.sh
source "$ROOT/lib/cluster.sh"

# ------------------------------------------------------------------------------
# Journal d'exécution
# ------------------------------------------------------------------------------
# Un déploiement dure 45 à 60 minutes. Si la connexion tombe — et sur une machine
# distante elle tombe — tout ce qui s'est affiché est perdu, et il devient
# impossible de savoir où le script en était, ni pourquoi il s'est arrêté.
#
# Toute la sortie est donc dupliquée dans un fichier, consultable depuis une
# autre connexion :
#
#     tail -f ~/autodeploy_k8s/journaux/deploy-<horodatage>.log
#
# Cela ne remplace pas tmux, qui garde le PROCESSUS en vie ; c'est
# complémentaire : le journal garde la TRACE même si le processus meurt.
#
# La redirection n'est posée qu'une fois : DEPLOY_LOG marque le passage, sinon
# la relance à travers « tee » créerait une boucle infinie de processus.
if [ -z "${DEPLOY_LOG:-}" ] && [ "${DEPLOY_NO_LOG:-0}" != "1" ]; then
    mkdir -p "$ROOT/journaux"
    DEPLOY_LOG="$ROOT/journaux/deploy-$(date +%Y%m%d-%H%M%S).log"
    export DEPLOY_LOG
    echo "  journal : $DEPLOY_LOG"
    echo "  suivi depuis une autre connexion :  tail -f $DEPLOY_LOG"
    echo
    # exec redirige le script lui-même : pas de sous-processus, donc le code de
    # sortie et les signaux restent ceux du script.
    exec > >(tee -a "$DEPLOY_LOG") 2>&1
fi

# ------------------------------------------------------------------------------
# Aide
# ------------------------------------------------------------------------------
usage() {
    cat <<'EOF'
autodeploy_k8s — cluster Kubernetes + applications de microservices sur SLICES-RI

USAGE
    ./deploy.sh [--app <sélection>] [options]

SÉLECTION DE L'APPLICATION
    --app otel-demo         Déploie uniquement OpenTelemetry Demo
    --app train-ticket      Déploie uniquement Train Ticket
    --app both              Déploie les deux (alias : all, les-deux)
    (sans --app, la valeur APPS du fichier .env est utilisée)

MODES
    --check                 Ne crée RIEN et ne déploie RIEN : vérifie que tout
                            est en place (CLI, jeton, clés) et teste, avec UNE
                            seule connexion SSH, si les VMs existantes sont
                            joignables. À lancer avant d'engager des ressources.
    --vms-only              Réserve les VMs, génère l'inventaire et vérifie le
                            SSH, puis S'ARRÊTE (pas de Kubespray, pas d'appli).
                            Avec --workers 0, c'est le test de connectivité le
                            moins coûteux : une seule VM.
    --apps-only             Ne recrée rien : déploie les applications sur un
                            cluster déjà en place (utilise inventory.ini,
                            ou --master-ip)
    --infra-only            Crée les VMs et le cluster, sans aucune application
    --force-reinstall       Désinstalle l'application avant de la réinstaller

PARAMÈTRES D'INFRASTRUCTURE (écrasent le .env)
    --experiment <nom>      Nom de l'expérience SLICES
    --workers <n>           Nombre de nœuds workers (défaut : profil auto)
    --worker-flavor <f>     Gabarit des workers (ex. medium, large)
    --master-flavor <f>     Gabarit du master
    --duration <d>          Durée de réservation (ex. 3h, 1d)
    --master-ip <ip>        IP du master (utile avec --apps-only)

DIVERS
    --skip-capacity-check   N'analyse pas l'adéquation ressources/besoins
    -y, --yes               Répond « oui » à toutes les confirmations
    -h, --help              Affiche cette aide

EXEMPLES
    ./deploy.sh --app otel-demo
    ./deploy.sh --app both --workers 6 --duration 1d
    ./deploy.sh --apps-only --app train-ticket
    ./deploy.sh --apps-only --app otel-demo --force-reinstall
EOF
}

# ------------------------------------------------------------------------------
# Analyse des arguments
# ------------------------------------------------------------------------------
APPS_ARG=""
MODE="full"                 # full | apps-only | infra-only
FORCE_REINSTALL=0
SKIP_CAPACITY=0
ASSUME_YES=0
CLI_WORKERS=""; CLI_WORKER_FLAVOR=""; CLI_MASTER_FLAVOR=""
CLI_DURATION=""; CLI_EXPERIMENT=""; CLI_MASTER_IP=""

# Sous « set -u », un « --workers » sans valeur provoquerait un « unbound
# variable » illisible au lieu d'un message d'aide.
need_value() { [ $# -ge 2 ] && [ -n "${2:-}" ] || { echo "Option $1 attend une valeur." >&2; exit 2; }; }

while [ $# -gt 0 ]; do
    case "$1" in
        --app|--apps)          need_value "$@"; APPS_ARG="${APPS_ARG} $2"; shift 2 ;;
        --app=*|--apps=*)      APPS_ARG="${APPS_ARG} ${1#*=}"; shift ;;
        --apps-only|--app-only) MODE="apps-only"; shift ;;
        --infra-only|--cluster-only) MODE="infra-only"; shift ;;
        --check|--preflight)   MODE="check"; shift ;;
        --vms-only)            MODE="vms-only"; shift ;;
        --force-reinstall)     FORCE_REINSTALL=1; shift ;;
        --skip-capacity-check) SKIP_CAPACITY=1; shift ;;
        --experiment) need_value "$@";          CLI_EXPERIMENT="$2"; shift 2 ;;
        --workers) need_value "$@";             CLI_WORKERS="$2"; shift 2 ;;
        --worker-flavor) need_value "$@";       CLI_WORKER_FLAVOR="$2"; shift 2 ;;
        --master-flavor) need_value "$@";       CLI_MASTER_FLAVOR="$2"; shift 2 ;;
        --duration) need_value "$@";            CLI_DURATION="$2"; shift 2 ;;
        --master-ip) need_value "$@";           CLI_MASTER_IP="$2"; shift 2 ;;
        -y|--yes)              ASSUME_YES=1; shift ;;
        -h|--help)             usage; exit 0 ;;
        *) echo "Option inconnue : $1" >&2; echo; usage; exit 2 ;;
    esac
done
export ASSUME_YES

# ------------------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------------------
load_env "$ROOT"

[ -n "$CLI_EXPERIMENT" ]    && EXPERIMENT_NAME="$CLI_EXPERIMENT"
[ -n "$CLI_WORKERS" ]       && WORKER_COUNT="$CLI_WORKERS"
[ -n "$CLI_WORKER_FLAVOR" ] && WORKER_FLAVOR="$CLI_WORKER_FLAVOR"
[ -n "$CLI_MASTER_FLAVOR" ] && MASTER_FLAVOR="$CLI_MASTER_FLAVOR"
[ -n "$CLI_DURATION" ]      && DURATION="$CLI_DURATION"

if [ -n "${APPS_ARG// /}" ]; then
    SELECTED_APPS=$(normalize_apps "$APPS_ARG")
else
    SELECTED_APPS=$(normalize_apps "$APPS")
fi
[ "$MODE" = "infra-only" ] && SELECTED_APPS=""

WORKERS=$(resolve_worker_count "$SELECTED_APPS")
[ "$MODE" = "vms-only" ] && SELECTED_APPS=""

banner "autodeploy_k8s — SLICES-RI + Kubernetes"
info "Expérience SLICES ...... $EXPERIMENT_NAME (site $SITE_ID)"
info "Mode ................... $MODE"
info "Applications ........... ${SELECTED_APPS:-aucune}"
[ "$MODE" != "apps-only" ] && \
info "Topologie .............. 1 master ($MASTER_FLAVOR) + $WORKERS workers ($WORKER_FLAVOR), durée $DURATION"
[ "$FORCE_REINSTALL" = "1" ] && warn "Réinstallation forcée des applications sélectionnées."

TOTAL_STEPS=8
[ "$MODE" = "apps-only" ] && TOTAL_STEPS=4

# ==============================================================================
# MODE « check » : vérification préalable, sans engager la moindre ressource
# ==============================================================================
if [ "$MODE" = "check" ]; then
    banner "Vérification préalable — aucune ressource ne sera créée"
    CHECK_FAIL=0

    step 1 4 "Poste local"
    for f in "$SSH_SOURCE_PRIV_KEY" "$SSH_SOURCE_PUB_KEY"; do
        if [ -f "$f" ]; then ok "Clé présente : $f"
        else err "Clé manquante : $f"; CHECK_FAIL=1; fi
    done
    if ssh-keygen -l -f "$SSH_SOURCE_PUB_KEY" >/dev/null 2>&1; then
        ok "Clé publique valide : $(ssh-keygen -l -f "$SSH_SOURCE_PUB_KEY" 2>/dev/null | awk '{print $1, $4}')"
    else err "Clé publique illisible ou invalide."; CHECK_FAIL=1; fi
    python3 -c "import venv" 2>/dev/null && ok "python3-venv disponible" \
        || { err "python3-venv absent : sudo apt install -y python3-venv"; CHECK_FAIL=1; }

    step 2 4 "CLI SLICES et authentification"
    slices_activate
    slices_ensure_experiment
    if slices bi flavor list >/dev/null 2>&1; then ok "Jeton SLICES valide."
    else err "Jeton SLICES invalide ou expiré → slices auth login"; CHECK_FAIL=1; fi

    step 3 4 "Ressources existantes"
    if slices_infra_exists; then
        slices bi list --experiment "$EXPERIMENT_NAME" --format ansible 2>/dev/null \
            | grep "ansible_ssh_host" > .check_vms.txt || true
        ok "$(wc -l < .check_vms.txt) VM(s) déjà réservées dans « $EXPERIMENT_NAME »."
    else
        : > .check_vms.txt
        log "Aucune VM réservée — rien à tester côté réseau."
    fi

    step 4 4 "Joignabilité SSH (une seule connexion par VM)"
    # destroy.sh supprime $SSH_PRIV_KEY : sans cette recopie, --check testerait
    # avec une clé absente et conclurait à tort à un filtrage réseau.
    if [ ! -f "$SSH_PRIV_KEY" ] && [ -f "$SSH_SOURCE_PRIV_KEY" ]; then
        cp "$SSH_SOURCE_PRIV_KEY" "$SSH_PRIV_KEY"; chmod 600 "$SSH_PRIV_KEY"
        log "Clé privée recopiée dans $SSH_PRIV_KEY pour le test."
    fi
    NET_TESTED=0
    if [ ! -s .check_vms.txt ]; then
        warn "Pas de VM existante : la connectivité réseau n'a PAS pu être testée."
        warn "Pour la tester sans engager le cluster complet, crée une VM unique :"
        warn "    ./deploy.sh --infra-only --workers 1   puis   ./deploy.sh --check"
    else
        NET_TESTED=1
        while read -r line; do
            vm=$(awk '{print $1}' <<<"$line")
            ip=$(grep -oP 'ansible_ssh_host=\K[0-9.]+' <<<"$line" || true)
            [ -n "$ip" ] || continue
            # UNE seule tentative, avec une vraie connexion SSH — jamais de sonde de port.
            if ssh -n -i "$SSH_PRIV_KEY" "${SSH_OPTS[@]}" -o BatchMode=yes \
                   -o ConnectTimeout=15 "ubuntu@$ip" true >/dev/null 2>&1; then
                ok "$vm ($ip) : SSH joignable"
            else
                err "$vm ($ip) : SSH injoignable"
                CHECK_FAIL=1
            fi
        done < .check_vms.txt
    fi
    rm -f .check_vms.txt

    echo
    if [ "$CHECK_FAIL" = "0" ] && [ "${NET_TESTED:-0}" = "1" ]; then
        banner "✅ TOUT EST VERT — connectivité comprise"
        echo " Tu peux lancer :  ./deploy.sh --app otel-demo"
        exit 0
    elif [ "$CHECK_FAIL" = "0" ]; then
        banner "🟡 POSTE PRÊT — mais connectivité NON testée"
        echo " Les prérequis locaux et le jeton SLICES sont bons."
        echo " Il n'existait aucune VM : rien ne garantit encore que le réseau passe."
        echo " Test à moindre coût (1 seule VM) :"
        echo "   ./deploy.sh --infra-only --workers 1  &&  ./deploy.sh --check"
        exit 0
    else
        banner "❌ VÉRIFICATION EN ÉCHEC — ne lance pas le déploiement"
        echo " Corrige les points ci-dessus, puis relance : ./deploy.sh --check"
        exit 1
    fi
fi

# ==============================================================================
# ------------------------------------------------------------------------------
# Réserver le nœud de mesure AVANT de déployer l'application
# ------------------------------------------------------------------------------
# Un volume local-path est attaché à la machine qui l'a créé. Si l'application
# s'installe d'abord sur ce nœud, ses volumes y restent et les pods qui les
# utilisent ne peuvent plus être déplacés : ils restent Pending indéfiniment.
# Poser la marque avant supprime la situation par construction.
#
# Sans OBS_DEDICATED_NODE, rien n'est réservé et le comportement est l'ancien.
reserve_obs_node() {
    local ip="$1" node="${OBS_DEDICATED_NODE:-}"
    [ -n "$node" ] || return 0
    log "Réservation du nœud de mesure « $node » (avant l'application)…"
    if ssh -n -i "$SSH_PRIV_KEY" "${SSH_OPTS[@]}" "ubuntu@$ip" \
         "kubectl get node '$node'" >/dev/null 2>&1; then
        ssh -n -i "$SSH_PRIV_KEY" "${SSH_OPTS[@]}" "ubuntu@$ip" \
            "kubectl label node '$node' role=observability --overwrite >/dev/null && \
             kubectl taint node '$node' dedicated=observability:NoSchedule --overwrite >/dev/null" \
            && ok "Nœud « $node » réservé : l'application ne s'y installera pas." \
            || warn "Réservation de « $node » impossible — l'application pourra s'y installer."
    else
        warn "OBS_DEDICATED_NODE=« $node » : ce nœud n'existe pas dans le cluster."
        warn "  Nœuds disponibles :"
        ssh -n -i "$SSH_PRIV_KEY" "${SSH_OPTS[@]}" "ubuntu@$ip" \
            "kubectl get nodes --no-headers | awk '{print \"    \" \$1}'" 2>/dev/null || true
        warn "  Aucune réservation faite. Corrige .env, ou isole après coup :"
        warn "    bash ~/autodeploy/apps/observability.sh isolate <nœud>"
    fi
}

# MODE « apps-only » : on se raccroche à un cluster existant
# ==============================================================================
if [ "$MODE" = "apps-only" ]; then
    [ -n "$SELECTED_APPS" ] || die "Aucune application sélectionnée. Utilise --app otel-demo|train-ticket|both."

    step 1 "$TOTAL_STEPS" "Localisation du cluster existant"
    if [ -n "$CLI_MASTER_IP" ]; then
        MASTER_IP="$CLI_MASTER_IP"
    elif [ -f "$INVENTORY_FILE" ]; then
        MASTER_VM=$(awk '/^\[kube_control_plane\]/{getline; print $1; exit}' "$INVENTORY_FILE")
        MASTER_IP=$(awk -v m="$MASTER_VM" '$1==m {for(i=1;i<=NF;i++) if($i ~ /^ansible_ssh_host=/){sub(/^ansible_ssh_host=/,"",$i); print $i; exit}}' "$INVENTORY_FILE")
    elif [ -n "${MASTER_IP:-}" ]; then
        : # fourni par le .env
    fi
    [ -n "${MASTER_IP:-}" ] || die "IP du master introuvable. Passe --master-ip <ip> ou conserve $INVENTORY_FILE."
    ok "Master ciblé : $MASTER_IP"

    # Le bastion. En mode complet il est déduit de la sortie de la CLI SLICES,
    # qui n'est pas appelée ici. Sans lui toutes les connexions échouent en
    # « Connection timed out » : les VMs SLICES n'ont qu'une adresse privée.
    # L'inventaire le porte déjà, sous la forme « -J proxy@bastion… ».
    if [ -z "${SSH_JUMP:-}" ] && [ -f "$INVENTORY_FILE" ]; then
        SSH_JUMP=$(grep -oP -- "-J \\K[^ '\"]+" "$INVENTORY_FILE" | head -1 || true)
        if [ -n "$SSH_JUMP" ]; then
            build_ssh_opts
            ok "Bastion repris de l'inventaire : $SSH_JUMP"
        fi
    fi

    [ -f "$SSH_PRIV_KEY" ] || {
        [ -f "$SSH_SOURCE_PRIV_KEY" ] || die "Clé SSH introuvable ($SSH_PRIV_KEY et $SSH_SOURCE_PRIV_KEY)."
        cp "$SSH_SOURCE_PRIV_KEY" "$SSH_PRIV_KEY"; chmod 600 "$SSH_PRIV_KEY"
    }
    wait_for_ssh "$MASTER_IP" 120 || die "Le master $MASTER_IP est injoignable."

    step 2 "$TOTAL_STEPS" "Préparation du master (kubectl, Helm 3 et 4, stockage)"
    master_bootstrap "$MASTER_IP"
    ensure_default_storageclass "$MASTER_IP"

    step 3 "$TOTAL_STEPS" "Contrôle de capacité"
    if [ "$SKIP_CAPACITY" = "0" ]; then capacity_check "$MASTER_IP" "$SELECTED_APPS"; else log "Ignoré (--skip-capacity-check)."; fi

    step 4 "$TOTAL_STEPS" "Déploiement des applications"
    push_app_scripts "$MASTER_IP" "$ROOT/apps"
    reserve_obs_node "$MASTER_IP"
    for app in $SELECTED_APPS; do
        banner "Application : $app"
        run_app "$MASTER_IP" "$app" install
    done

    banner "TERMINÉ"
    for app in $SELECTED_APPS; do run_app "$MASTER_IP" "$app" urls; done
    exit 0
fi

# ==============================================================================
# MODE COMPLET
# ==============================================================================

# --- [1/8] Clé SSH ------------------------------------------------------------
step 1 "$TOTAL_STEPS" "Préparation de la clé SSH"
mkdir -p "$HOME/.ssh"
manque_cle() {
    err "Clé $1 introuvable : $2"
    err ""
    err "  Le script a besoin d'une paire de clés pour se connecter aux machines"
    err "  qu'il va créer. Il enregistre la partie publique sur chacune d'elles."
    err ""
    err "  Si vous n'en avez pas encore, créez-en une ici même :"
    err "      ssh-keygen -t ed25519 -f ~/.ssh/id_rsa -N \"\""
    err ""
    err "  Puis dans .env :"
    err "      SSH_SOURCE_PRIV_KEY=\"$HOME/.ssh/id_rsa\""
    err "      SSH_SOURCE_PUB_KEY=\"$HOME/.ssh/id_rsa.pub\""
    err ""
    err "  La clé PRIVÉE est le fichier SANS .pub."
    exit 1
}
[ -f "$SSH_SOURCE_PRIV_KEY" ] || manque_cle "privée"  "$SSH_SOURCE_PRIV_KEY"
[ -f "$SSH_SOURCE_PUB_KEY" ]  || manque_cle "publique" "$SSH_SOURCE_PUB_KEY"

# Une clé publique passée comme clé privée est une confusion fréquente, et elle
# se manifesterait bien plus loin par un « Permission denied » incompréhensible.
case "$SSH_SOURCE_PRIV_KEY" in
    *.pub) die "SSH_SOURCE_PRIV_KEY pointe sur un fichier .pub — c'est la clé PUBLIQUE.
  La clé privée est le même chemin SANS le .pub : ${SSH_SOURCE_PRIV_KEY%.pub}" ;;
esac
head -1 "$SSH_SOURCE_PRIV_KEY" | grep -q "PRIVATE KEY" \
    || die "SSH_SOURCE_PRIV_KEY ne contient pas une clé privée : $SSH_SOURCE_PRIV_KEY"
# On travaille sur une COPIE, en 0600. OpenSSH refuse une clé privée dont les
# droits sont trop ouverts, et l'originale n'est pas forcément modifiable.
cp "$SSH_SOURCE_PRIV_KEY" "$SSH_PRIV_KEY"
chmod 600 "$SSH_PRIV_KEY"
ok "Clé privée sécurisée dans $SSH_PRIV_KEY"

# --- [2/8] Authentification SLICES -------------------------------------------
step 2 "$TOTAL_STEPS" "Environnement et authentification SLICES"
slices_activate
slices_ensure_auth

# --- [3/8] Réservation des VMs -----------------------------------------------
step 3 "$TOTAL_STEPS" "Réservation de l'infrastructure"
# L'expérience doit exister avant qu'on puisse y lister ou créer quoi que ce soit.
slices_ensure_experiment
if slices_infra_exists; then
    # Réutiliser n'a de sens que si la topologie existante correspond au besoin.
    # Sinon on partirait sur un cluster amputé (ex. 0 worker) sans le voir.
    EXISTING=$(slices bi list --experiment "$EXPERIMENT_NAME" --format ansible 2>/dev/null || true)
    HAVE_WORKERS=$(grep -cE "^workers[0-9]*[[:space:]].*ansible_ssh_host=[0-9]" <<<"$EXISTING" || true)
    warn "L'expérience « $EXPERIMENT_NAME » possède déjà des VMs : 1 master + ${HAVE_WORKERS:-0} worker(s)."

    if [ "${HAVE_WORKERS:-0}" -ge "$WORKERS" ]; then
        ok "Topologie existante suffisante ($HAVE_WORKERS ≥ $WORKERS workers) — réutilisation."
    else
        err "Topologie insuffisante : $HAVE_WORKERS worker(s) réservé(s), $WORKERS demandé(s)."
        err "Poursuivre installerait un cluster amputé. Deux options :"
        err "  • repartir proprement :  ./destroy.sh --yes  puis relancer cette commande"
        err "  • ou t'aligner sur l'existant :  ./deploy.sh --workers $HAVE_WORKERS …"
        die "Déploiement interrompu avant toute action destructrice."
    fi
else
    slices_create_infra "$WORKERS"
    slices_wait_for_vms $((WORKERS + 1))
fi

# --- [4/8] Inventaire Ansible -------------------------------------------------
step 4 "$TOTAL_STEPS" "Génération de l'inventaire Kubespray"
slices_build_inventory "$INVENTORY_FILE"
slices_write_ssh_aliases "$ALL_VMS_FILE"

info "Vérification de l'accessibilité SSH de toutes les VMs…"
while read -r line; do
    vm_ip=$(awk '{for(i=1;i<=NF;i++) if($i ~ /^ansible_ssh_host=/){sub(/^ansible_ssh_host=/,"",$i); print $i; exit}}' <<<"$line")
    if [ -n "$vm_ip" ]; then
        if ! wait_for_ssh "$vm_ip" "$SSH_WAIT_TIMEOUT"; then
            diagnose_unreachable "$vm_ip"
            die "VM $vm_ip injoignable après ${SSH_WAIT_TIMEOUT}s — voir le diagnostic ci-dessus."
        fi
    fi
done < "$ALL_VMS_FILE"
rm -f "$ALL_VMS_FILE"

if [ "$MODE" = "vms-only" ]; then
    banner "✅ VMs PRÊTES ET JOIGNABLES — arrêt demandé (--vms-only)"
    cat <<EOF
 Toutes les VMs répondent en SSH : le chemin réseau est bon.
 Master : $MASTER_VM — $MASTER_IP   (ssh $MASTER_VM)
 Inventaire : $ROOT/$INVENTORY_FILE

 Pour enchaîner sur le cluster et les applications :
   ./deploy.sh --app otel-demo
 Pour libérer les VMs :
   ./destroy.sh
EOF
    exit 0
fi

# --- [5/8] Kubespray ----------------------------------------------------------
step 5 "$TOTAL_STEPS" "Installation de Kubernetes (Kubespray)"
kubespray_prepare
kubespray_configure "$INVENTORY_FILE"
kubespray_run

# --- [6/8] Préparation du master ---------------------------------------------
step 6 "$TOTAL_STEPS" "Préparation du master (kubectl, Helm 3 et 4, stockage)"
master_bootstrap "$MASTER_IP"
ensure_default_storageclass "$MASTER_IP"

# --- [7/8] Applications -------------------------------------------------------
step 7 "$TOTAL_STEPS" "Déploiement des applications"
if [ -z "$SELECTED_APPS" ]; then
    log "Aucune application demandée (--infra-only)."
else
    if [ "$SKIP_CAPACITY" = "0" ]; then capacity_check "$MASTER_IP" "$SELECTED_APPS"; fi
    push_app_scripts "$MASTER_IP" "$ROOT/apps"
    reserve_obs_node "$MASTER_IP"
    for app in $SELECTED_APPS; do
        banner "Application : $app"
        run_app "$MASTER_IP" "$app" install
    done
fi

# --- [8/8] Récapitulatif ------------------------------------------------------
step 8 "$TOTAL_STEPS" "Récapitulatif"
banner "DÉPLOIEMENT TERMINÉ"
cat <<EOF
 Cluster      : 1 master + $WORKERS workers  (expérience « $EXPERIMENT_NAME »)
 Master       : $MASTER_VM — $MASTER_IP
 Inventaire   : $ROOT/$INVENTORY_FILE

 Connexion    : ssh $MASTER_VM        (alias créés dans ~/.ssh/config)
 Cluster      : ssh $MASTER_VM 'kubectl get nodes -o wide'
 Destruction  : ./destroy.sh
EOF
for app in $SELECTED_APPS; do run_app "$MASTER_IP" "$app" urls; done
