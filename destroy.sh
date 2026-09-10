#!/bin/bash
# ==============================================================================
#  autodeploy_k8s — Destruction de l'expérience SLICES et nettoyage local
#
#  Usage :  ./destroy.sh [options]      (voir ./destroy.sh --help)
# ==============================================================================
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# shellcheck source=lib/common.sh
source "$ROOT/lib/common.sh"
# shellcheck source=lib/slices.sh
source "$ROOT/lib/slices.sh"
# shellcheck source=lib/cluster.sh
source "$ROOT/lib/cluster.sh"

usage() {
    cat <<'EOF'
autodeploy_k8s — destruction

USAGE
    ./destroy.sh [options]

OPTIONS
    --apps-only [--app <sél.>]  Désinstalle seulement les applications
                                (le cluster et les VMs restent en place)
    --keep-vms                  Ne détruit pas les VMs SLICES : nettoie
                                uniquement les fichiers locaux
    --master-ip <ip>            IP du master (pour --apps-only)
    -y, --yes                   Ne pose aucune question
    -h, --help                  Affiche cette aide

SANS OPTION
    Détruit les VMs de l'expérience SLICES puis nettoie intégralement le
    poste local (kubespray/, inventaire, clé temporaire, alias SSH, cache).
EOF
}

MODE="full"; ASSUME_YES=0; APPS_ARG=""; CLI_MASTER_IP=""
while [ $# -gt 0 ]; do
    case "$1" in
        --apps-only)  MODE="apps-only"; shift ;;
        --keep-vms)   MODE="local-only"; shift ;;
        --app|--apps) APPS_ARG="${APPS_ARG} $2"; shift 2 ;;
        --app=*)      APPS_ARG="${APPS_ARG} ${1#*=}"; shift ;;
        --master-ip)  CLI_MASTER_IP="$2"; shift 2 ;;
        -y|--yes)     ASSUME_YES=1; shift ;;
        -h|--help)    usage; exit 0 ;;
        *) echo "Option inconnue : $1" >&2; echo; usage; exit 2 ;;
    esac
done
export ASSUME_YES

load_env "$ROOT"

# ==============================================================================
# Mode « apps-only » : on retire les applications sans toucher au cluster
# ==============================================================================
if [ "$MODE" = "apps-only" ]; then
    APPS_TO_REMOVE=$(normalize_apps "${APPS_ARG:-$APPS}")
    [ -n "$APPS_TO_REMOVE" ] || die "Aucune application à désinstaller (--app otel-demo|train-ticket|both)."

    if [ -n "$CLI_MASTER_IP" ]; then
        MASTER_IP="$CLI_MASTER_IP"
    elif [ -f "$INVENTORY_FILE" ]; then
        MASTER_VM=$(awk '/^\[kube_control_plane\]/{getline; print $1; exit}' "$INVENTORY_FILE")
        MASTER_IP=$(awk -v m="$MASTER_VM" '$1==m {for(i=1;i<=NF;i++) if($i ~ /^ansible_ssh_host=/){sub(/^ansible_ssh_host=/,"",$i); print $i; exit}}' "$INVENTORY_FILE")
    fi
    [ -n "${MASTER_IP:-}" ] || die "IP du master introuvable : passe --master-ip <ip>."

    if [ ! -f "$SSH_PRIV_KEY" ]; then
        [ -f "$WINDOWS_SSH_PRIV_KEY" ] || die "Clé SSH introuvable ($SSH_PRIV_KEY et $WINDOWS_SSH_PRIV_KEY)."
        cp "$WINDOWS_SSH_PRIV_KEY" "$SSH_PRIV_KEY"; chmod 600 "$SSH_PRIV_KEY"
    fi

    banner "Désinstallation des applications : $APPS_TO_REMOVE"
    confirm "Supprimer ces applications sur le cluster $MASTER_IP ?" || die "Annulé."

    push_app_scripts "$MASTER_IP" "$ROOT/apps"
    for app in $APPS_TO_REMOVE; do
        run_app "$MASTER_IP" "$app" uninstall || warn "Échec de la désinstallation de $app."
    done
    ok "Applications désinstallées. Le cluster reste opérationnel."
    exit 0
fi

# ==============================================================================
# Destruction complète
# ==============================================================================
banner "⚠️  DESTRUCTION"
info "Expérience SLICES ..... $EXPERIMENT_NAME"
if [ "$MODE" = "local-only" ]; then
    info "Portée ................ fichiers locaux uniquement (--keep-vms)"
else
    info "Portée ................ VMs SLICES + fichiers locaux"
fi
confirm "Confirmer la destruction ?" || die "Annulé — rien n'a été supprimé."

# --- [1/2] Infrastructure -----------------------------------------------------
if [ "$MODE" != "local-only" ]; then
    step 1 2 "Destruction de l'infrastructure SLICES"
    if [ -f "$SLICES_VENV/bin/activate" ]; then
        # shellcheck disable=SC1090
        source "$SLICES_VENV/bin/activate"
        slices_destroy || DESTROY_FAILED=1
    else
        err "Environnement SLICES introuvable ($SLICES_VENV) — destruction distante IMPOSSIBLE."
        err "Les VMs continueront de consommer ton quota jusqu'à expiration de la réservation."
        DESTROY_FAILED=1
    fi
else
    step 1 2 "Destruction de l'infrastructure SLICES (ignorée)"
    log "--keep-vms : les VMs sont conservées."
fi

# --- [2/2] Nettoyage local ----------------------------------------------------
step 2 2 "Nettoyage du poste local"

# Les alias SSH sont retirés en se basant sur l'inventaire réel, plus un filet
# de sécurité sur les motifs de nommage utilisés par les versions précédentes.
if [ -f "$INVENTORY_FILE" ]; then
    while read -r name _; do
        case "$name" in
            \[*|"") continue ;;
            *=*) continue ;;
        esac
        ssh_alias_remove "$name"
    done < <(awk '/^\[all\]/{f=1;next} /^\[/{f=0} f' "$INVENTORY_FILE")
fi
# Reliquat d'un ancien schéma de noms. Le projet crée aujourd'hui « master » et
# « workers », jamais « vms0 » : ces alias-là sont retirés à partir de
# l'inventaire, juste au-dessus.
#
# « vms0 » à « vms5 » ont été RETIRÉS de cette liste. Ils n'appartenaient plus au
# projet, et les effacer coupait l'accès à des VMs sans rapport avec lui —
# réservées à part, avec leur propre expérience et leur propre durée de vie.
# Un nettoyage ne doit toucher que ce qu'il a lui-même créé.
for legacy in master master0 \
              workers0 workers1 workers2 workers3 workers4 workers5; do
    ssh_alias_remove "$legacy"
done
sed -i '/^$/N;/^\n$/D' "$HOME/.ssh/config" 2>/dev/null || true
log "Alias SSH nettoyés dans ~/.ssh/config"

if [ -d kubespray ]; then
    log "Suppression du dossier kubespray/ (et de son venv Python)…"
    rm -rf kubespray
fi

# AVANT de supprimer l'inventaire : il seul contient la liste des hôtes dont
# le cache de faits doit être purgé.
purge_ansible_facts "$INVENTORY_FILE"

log "Suppression des fichiers d'inventaire…"
rm -f "$INVENTORY_FILE" raw_inventory.txt valid_vms.txt

log "Suppression de la clé SSH temporaire ($SSH_PRIV_KEY)…"
rm -f "$SSH_PRIV_KEY"

log "Vidage du cache de connexions d'Ansible…"
rm -rf "$HOME/.ansible/cp/"* 2>/dev/null || true

# Sockets ControlMaster de nos propres commandes : laissés en place, ils
# pointeraient vers des VMs détruites et feraient échouer les connexions
# suivantes vers une IP recyclée.
log "Suppression des sockets de multiplexage SSH…"
rm -rf "${SSH_MUX_DIR:-$HOME/.ssh/mux-autodeploy}/"* 2>/dev/null || true

if [ "${DESTROY_FAILED:-0}" = "1" ]; then
    banner "⚠️  NETTOYAGE LOCAL TERMINÉ — MAIS DES VMs SUBSISTENT"
    echo " Le poste local est propre, mais des ressources SLICES sont encore"
    echo " actives et consomment ton quota. Voir le message d'erreur ci-dessus."
    exit 1
fi

banner "✅ DESTRUCTION TERMINÉE"
echo " L'environnement est de nouveau vierge."
echo " Nouveau déploiement :  ./deploy.sh --app otel-demo"
