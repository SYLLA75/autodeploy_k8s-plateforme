#!/bin/bash
# ==============================================================================
# lib/cluster.sh — Installation du cluster Kubernetes (Kubespray) et préparation
#                  du nœud master (kubeconfig, Helm, StorageClass, capacité)
# ==============================================================================

KUBESPRAY_DIR="kubespray"
LOCAL_PATH_VERSION="${LOCAL_PATH_VERSION:-v0.0.37}"

# ------------------------------------------------------------------------------
# Récupération de Kubespray et de ses dépendances Python
# ------------------------------------------------------------------------------
kubespray_prepare() {
    require_cmd git "Installe-le : sudo apt install -y git"
    python3 -c "import venv" 2>/dev/null \
        || die "Le module python3-venv est absent. Installe-le : sudo apt install -y python3-venv python3-pip"

    if [ ! -d "$KUBESPRAY_DIR" ]; then
        info "Clonage de Kubespray (branche $KUBESPRAY_REF)…"
        git clone --depth=1 --branch "$KUBESPRAY_REF" \
            https://github.com/kubernetes-sigs/kubespray.git "$KUBESPRAY_DIR" \
            || die "Échec du clonage de Kubespray."
    else
        # Sans cela, changer KUBESPRAY_REF dans .env n'aurait aucun effet sur un
        # clone déjà présent : on resterait silencieusement sur l'ancienne version.
        local current
        current=$(git -C "$KUBESPRAY_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")
        if [ "$current" != "$KUBESPRAY_REF" ]; then
            log "Clone Kubespray sur « $current », bascule vers « $KUBESPRAY_REF »…"
            git -C "$KUBESPRAY_DIR" fetch --depth=1 origin "$KUBESPRAY_REF" \
                && git -C "$KUBESPRAY_DIR" checkout -B "$KUBESPRAY_REF" FETCH_HEAD \
                || warn "Bascule impossible, on garde « $current »."
        else
            log "Kubespray déjà présent sur « $KUBESPRAY_REF », réutilisation."
        fi
    fi

    info "Installation des dépendances Ansible (peut prendre 2-3 minutes)…"
    (
        cd "$KUBESPRAY_DIR" || exit 1
        [ -d venv-kubespray ] || python3 -m venv venv-kubespray
        # shellcheck disable=SC1091
        source venv-kubespray/bin/activate
        pip install -q -U pip
        pip install -q -r requirements.txt
    ) || die "Échec de l'installation des dépendances Kubespray."
    ok "Kubespray prêt."
}

# ------------------------------------------------------------------------------
# kubespray_configure <chemin_inventaire_source>
# Copie l'inventaire généré et active les addons dont nous avons besoin.
# ------------------------------------------------------------------------------
kubespray_configure() {
    local inv_src="$1"
    # Des faits mis en cache lors d'un déploiement précédent contiendraient les
    # adresses d'anciennes VMs portant les mêmes noms d'hôte.
    purge_ansible_facts "$inv_src"
    local cluster_dir="$KUBESPRAY_DIR/inventory/mycluster"
    local addons="$cluster_dir/group_vars/k8s_cluster/addons.yml"

    rm -rf "$cluster_dir"
    cp -rfp "$KUBESPRAY_DIR/inventory/sample" "$cluster_dir"
    cp "$inv_src" "$cluster_dir/inventory.ini"

    # StorageClass par défaut : indispensable pour train-ticket (PVC MySQL/Nacos),
    # inoffensif pour otel-demo.
    info "Activation du provisionneur de stockage local-path (StorageClass par défaut)…"
    sed -i 's/^local_path_provisioner_enabled:.*/local_path_provisioner_enabled: true/' "$addons"
    grep -q '^local_path_provisioner_is_default_storageclass:' "$addons" \
        || echo 'local_path_provisioner_is_default_storageclass: "true"' >> "$addons"

    if [ "${KUBESPRAY_METRICS_SERVER:-true}" = "true" ]; then
        info "Activation de metrics-server (permet « kubectl top »)…"
        sed -i 's/^metrics_server_enabled:.*/metrics_server_enabled: true/' "$addons"
    fi

    ok "Inventaire et addons Kubespray configurés."
}

# ------------------------------------------------------------------------------
# Lancement du playbook cluster.yml
# ------------------------------------------------------------------------------
kubespray_run() {
    banner "Déploiement Kubernetes via Kubespray (15 à 30 minutes)"
    # Uniquement en profil "robust" : en profil "original" il n'y a aucune
    # connexion persistante à fermer, puisqu'on n'en ouvre pas.
    [ "${NETWORK_PROFILE:-original}" = "robust" ] && ssh_mux_close_all
    (
        cd "$KUBESPRAY_DIR" || exit 1
        # shellcheck disable=SC1091
        source venv-kubespray/bin/activate
        export ANSIBLE_HOST_KEY_CHECKING=False
        # En profil "original", on laisse Kubespray utiliser SA configuration
        # (son propre ansible.cfg), comme le faisait le script initial : aucune
        # variable d'environnement imposée.
        if [ "${NETWORK_PROFILE:-original}" = "robust" ]; then
            export ANSIBLE_SSH_ARGS='-C -o ControlMaster=auto -o ControlPersist=30m -o ConnectTimeout=30 -o ServerAliveInterval=30'
            export ANSIBLE_PIPELINING=True
            export ANSIBLE_SSH_RETRIES=5
            export ANSIBLE_FORKS="${ANSIBLE_FORKS:-3}"
            rm -rf "$HOME/.ansible/cp"; mkdir -p "$HOME/.ansible/cp"
        fi
        ansible-playbook -i inventory/mycluster/inventory.ini -b cluster.yml
    ) || die "Kubespray a échoué. Consulte la sortie ci-dessus, puis relance ./deploy.sh (le script est ré-entrant)."
    ok "Cluster Kubernetes installé."
}

# ------------------------------------------------------------------------------
# master_bootstrap <ip_master>
# kubeconfig utilisateur + Helm 3 ET Helm 4 sur le master.
#
# Pourquoi deux versions de Helm ?
#   - le chart opentelemetry-demo (>= 0.41) réclame Helm 4 ;
#   - les charts embarqués de train-ticket (nacos, rabbitmq) sont au format
#     « apiVersion: v1 », que Helm 4 ne sait plus lire → il faut Helm 3.
# On installe donc `helm` (v4) et `helm3`, chaque application utilisant le bon.
# ------------------------------------------------------------------------------
master_bootstrap() {
    local ip="$1"
    info "Préparation du nœud master ($ip) : kubeconfig, Helm 3 et Helm 4…"
    ssh -i "$SSH_PRIV_KEY" "${SSH_OPTS[@]}" "ubuntu@$ip" \
        "HELM3_VERSION='$HELM3_VERSION' HELM4_VERSION='$HELM4_VERSION' bash -s" <<'REMOTE_EOF'
set -euo pipefail

echo "[master] Configuration de kubectl pour l'utilisateur ubuntu…"
mkdir -p "$HOME/.kube"
sudo cp -f /etc/kubernetes/admin.conf "$HOME/.kube/config"
sudo chown "$(id -u):$(id -g)" "$HOME/.kube/config"
chmod 600 "$HOME/.kube/config"

echo "[master] Vérification de l'accès au cluster…"
kubectl get nodes -o wide

# git n'est pas garanti sur une image Ubuntu cloud, or train-ticket est cloné
# depuis le master. curl sert aux installateurs Helm.
for pkg in git curl; do
    command -v "$pkg" >/dev/null 2>&1 || MISSING="${MISSING:-} $pkg"
done
if [ -n "${MISSING:-}" ]; then
    echo "[master] Installation des paquets manquants :${MISSING}"
    sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ${MISSING}
fi

install_helm() {
    local script="$1" target="$2" version="$3"
    if [ -x "/usr/local/bin/$target" ]; then
        echo "[master] $target déjà installé ($(/usr/local/bin/$target version --short 2>/dev/null || echo '?'))"
        return 0
    fi
    echo "[master] Installation de $target…"
    local tmp; tmp=$(mktemp -d)
    curl -fsSL -o "$tmp/get-helm" "https://raw.githubusercontent.com/helm/helm/main/scripts/$script"
    chmod +x "$tmp/get-helm"
    if [ -n "$version" ]; then
        sudo HELM_INSTALL_DIR=/usr/local/bin "$tmp/get-helm" --version "$version" --no-sudo
    else
        sudo HELM_INSTALL_DIR=/usr/local/bin "$tmp/get-helm" --no-sudo
    fi
    if [ "$target" != "helm" ]; then
        sudo mv /usr/local/bin/helm "/usr/local/bin/$target"
    fi
    rm -rf "$tmp"
}

# Helm 3 d'abord (installé sous le nom `helm`, puis renommé `helm3`),
# Helm 4 ensuite (il reprend le nom `helm`).
install_helm get-helm-3 helm3 "${HELM3_VERSION:-}"
install_helm get-helm-4 helm  "${HELM4_VERSION:-}"

echo "[master] helm  → $(helm version --short 2>/dev/null || helm version 2>/dev/null | head -1)"
echo "[master] helm3 → $(helm3 version --short 2>/dev/null || true)"
REMOTE_EOF
    ok "Master prêt (kubectl + Helm 3 + Helm 4)."
}

# ------------------------------------------------------------------------------
# ensure_default_storageclass <ip_master>
# Filet de sécurité : si aucune StorageClass par défaut n'existe (cluster
# préexistant, addon Kubespray désactivé…), on installe local-path-provisioner.
# ------------------------------------------------------------------------------
ensure_default_storageclass() {
    local ip="$1"
    info "Vérification de la présence d'une StorageClass par défaut…"
    ssh -i "$SSH_PRIV_KEY" "${SSH_OPTS[@]}" "ubuntu@$ip" \
        "LOCAL_PATH_VERSION='$LOCAL_PATH_VERSION' bash -s" <<'REMOTE_EOF'
set -euo pipefail
# Pas de « head » en fin de tube : le SIGPIPE qu'il provoque serait transformé
# en échec fatal par « set -o pipefail », et le filet de sécurité local-path
# ne s'installerait jamais — train-ticket resterait bloqué sur ses PVC.
default_sc=$(kubectl get storageclass -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.metadata.annotations.storageclass\.kubernetes\.io/is-default-class}{"\n"}{end}' 2>/dev/null \
             | awk '$2=="true" && !seen++ {print $1}' || true)
if [ -n "$default_sc" ]; then
    echo "[master] StorageClass par défaut déjà présente : $default_sc"
    exit 0
fi
echo "[master] Aucune StorageClass par défaut → installation de local-path-provisioner ${LOCAL_PATH_VERSION}…"
kubectl apply -f "https://raw.githubusercontent.com/rancher/local-path-provisioner/${LOCAL_PATH_VERSION}/deploy/local-path-storage.yaml"
kubectl -n local-path-storage rollout status deployment/local-path-provisioner --timeout=180s
kubectl patch storageclass local-path \
    -p '{"metadata":{"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'
echo "[master] StorageClass 'local-path' installée et définie par défaut."
REMOTE_EOF
    ok "StorageClass par défaut disponible."
}

# ------------------------------------------------------------------------------
# capacity_check <ip_master> <liste_apps>
# Compare la capacité allouable du cluster aux besoins des applications.
# Avertit sans bloquer (sauf refus explicite de l'utilisateur).
# ------------------------------------------------------------------------------
capacity_check() {
    local ip="$1" apps="$2"
    local need_ram=0 need_cpu=0 app
    for app in $apps; do
        need_ram=$(( need_ram + $(app_ram_mib "$app") ))
        need_cpu=$(( need_cpu + $(app_cpu_milli "$app") ))
    done

    # On mesure la capacité RÉELLEMENT LIBRE : allouable moins ce que les pods
    # déjà présents réservent. Comparer au seul « allouable » surestime la place
    # disponible — les pods système (Calico, kube-proxy, CoreDNS, provisionneur
    # de stockage, metrics-server) réservent à eux seuls plusieurs centaines de
    # milli-CPU par nœud, ce qui suffit à faire échouer l'ordonnancement.
    local caps
    caps=$(ssh -n -i "$SSH_PRIV_KEY" "${SSH_OPTS[@]}" "ubuntu@$ip" bash -s <<'REMOTE_EOF'
python3 - <<'PYEOF'
import json, subprocess

def q(cmd):
    return json.loads(subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout or "{}")

def cpu(v):
    if not v: return 0
    v = str(v)
    return int(float(v[:-1])) if v.endswith("m") else int(float(v) * 1000)

def ram(v):
    if not v: return 0
    v = str(v)
    for suf, mul in (("Ki", 1/1024), ("Mi", 1), ("Gi", 1024), ("K", 1/1024), ("M", 1), ("G", 1024)):
        if v.endswith(suf):
            return int(float(v[:-len(suf)]) * mul)
    return int(float(v) / 1048576)

nodes = q("kubectl get nodes -o json").get("items", [])
pods  = q("kubectl get pods -A -o json").get("items", [])

usable = {}
for n in nodes:
    name = n["metadata"]["name"]
    # Un nœud portant un taint NoSchedule/NoExecute n'accueillera pas nos pods.
    if any(t.get("effect") in ("NoSchedule", "NoExecute") for t in (n["spec"].get("taints") or [])):
        continue
    a = n["status"]["allocatable"]
    usable[name] = [cpu(a.get("cpu")), ram(a.get("memory"))]

for p in pods:
    nn = p["spec"].get("nodeName")
    if nn not in usable: continue
    if p["status"].get("phase") in ("Succeeded", "Failed"): continue
    for c in p["spec"].get("containers", []):
        r = (c.get("resources") or {}).get("requests") or {}
        usable[nn][0] -= cpu(r.get("cpu"))
        usable[nn][1] -= ram(r.get("memory"))

fc = sum(max(0, v[0]) for v in usable.values())
fr = sum(max(0, v[1]) for v in usable.values())
print(fc, fr, len(usable))
PYEOF
REMOTE_EOF
    ) || { warn "Impossible de mesurer la capacité du cluster, contrôle ignoré."; return 0; }

    local cpu_free ram_free nodes
    read -r cpu_free ram_free nodes <<<"$(tr -d '\r' <<<"$caps" | tail -1)"
    [ -n "${cpu_free:-}" ] || { warn "Mesure de capacité illisible, contrôle ignoré."; return 0; }

    echo
    info "Capacité LIBRE (hors pods déjà en place) : ${nodes} nœud(s) ordonnançable(s), ${cpu_free}m CPU, ${ram_free} Mio RAM"
    info "Besoin estimé pour « $apps » : ${need_cpu}m CPU, ${need_ram} Mio RAM"

    if [ "$ram_free" -lt "$need_ram" ] || [ "$cpu_free" -lt "$need_cpu" ]; then
        warn "La capacité libre est INFÉRIEURE au besoin estimé."
        [ "$cpu_free" -lt "$need_cpu" ] && warn "  → il manque $(( need_cpu - cpu_free ))m de CPU"
        [ "$ram_free" -lt "$need_ram" ] && warn "  → il manque $(( need_ram - ram_free )) Mio de RAM"
        warn "Des pods resteront en Pending (« Insufficient cpu » ou « Insufficient memory »)."
        warn "Solutions : augmenter WORKER_COUNT, WORKER_FLAVOR, ou ne déployer qu'une application."
        confirm "Continuer malgré tout ?" || die "Déploiement annulé. Ajuste le dimensionnement puis relance."
    else
        ok "Capacité libre suffisante pour la sélection demandée."
    fi
}

# ------------------------------------------------------------------------------
# push_app_scripts <ip_master> <répertoire_apps>
# Copie les scripts d'application sur le master pour pouvoir les rejouer là-bas.
# ------------------------------------------------------------------------------
push_app_scripts() {
    local ip="$1" dir="$2"
    # On copie les fichiers un à un : « scp -r apps dest/ » créerait dest/apps/apps
    # au deuxième passage, puisque le dossier existe déjà côté master.
    ssh_exec "$ip" "mkdir -p '$REMOTE_WORKDIR/apps'"
    scp_to "$ip" "$dir/." "$REMOTE_WORKDIR/apps/" || die "Impossible de copier les scripts d'application sur le master."
    ssh_exec "$ip" "chmod +x '$REMOTE_WORKDIR'/apps/*.sh"
    log "Scripts d'application copiés dans $REMOTE_WORKDIR/apps/ sur le master."
}

# ------------------------------------------------------------------------------
# run_app <ip_master> <nom_app> <action>
# ------------------------------------------------------------------------------
# run_app <cible_ssh> <app> <action>
# MASTER_PUBLIC_IP permet de dissocier la cible de connexion de l'adresse
# affichée dans les URLs — indispensable quand on passe par une redirection
# (labo local) où la cible SSH n'est pas l'adresse du navigateur.
run_app() {
    local ip="$1" app="$2" action="$3"
    local env_prefix
    env_prefix=$(cat <<EOF
OTEL_NAMESPACE='$OTEL_NAMESPACE' OTEL_RELEASE='$OTEL_RELEASE' \
OTEL_CHART_VERSION='$OTEL_CHART_VERSION' OTEL_NODEPORT='$OTEL_NODEPORT' \
OTEL_HELM_BIN='${OTEL_HELM_BIN:-helm}' OTEL_FORCE='${FORCE_REINSTALL:-0}' \
TT_NAMESPACE='$TT_NAMESPACE' TT_REPO_URL='$TT_REPO_URL' TT_REF='$TT_REF' \
TT_DEPLOY_ARGS='$TT_DEPLOY_ARGS' TT_UI_NODEPORT='$TT_UI_NODEPORT' \
TT_GATEWAY_NODEPORT='$TT_GATEWAY_NODEPORT' TT_HELM_BIN='${TT_HELM_BIN:-helm3}' \
TT_FORCE='${FORCE_REINSTALL:-0}' TT_READY_TIMEOUT='${TT_READY_TIMEOUT:-1800}' \
MASTER_IP='${MASTER_PUBLIC_IP:-$ip}'
EOF
)
    ssh -i "$SSH_PRIV_KEY" "${SSH_OPTS[@]}" "ubuntu@$ip" \
        "$env_prefix bash '$REMOTE_WORKDIR/apps/$app.sh' '$action'"
}
