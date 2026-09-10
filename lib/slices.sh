#!/bin/bash
# ==============================================================================
# lib/slices.sh — Interaction avec l'infrastructure de recherche SLICES-RI
# ==============================================================================
# Réservation des VMs via la CLI `slices bi`, puis génération de l'inventaire
# Ansible/Kubespray à partir des adresses IP réellement allouées.
# ==============================================================================

# ------------------------------------------------------------------------------
# Active l'environnement virtuel Python qui contient la CLI SLICES
# ------------------------------------------------------------------------------
slices_activate() {
    local activate="$SLICES_VENV/bin/activate"
    [ -f "$activate" ] || die "Environnement SLICES introuvable : $activate
   Crée-le puis installe la CLI :
     python3 -m venv $SLICES_VENV
     source $SLICES_VENV/bin/activate
     pip install slices-cli --extra-index-url=https://doc.slices-ri.eu/pypi/"
    # shellcheck disable=SC1090
    source "$activate"
    require_cmd slices "L'environnement $SLICES_VENV ne contient pas la CLI slices."
    log "CLI SLICES : $(slices --version 2>/dev/null | head -1)"
}

# ------------------------------------------------------------------------------
# Vérifie le jeton d'authentification, et relance `slices auth login` si besoin.
# Le jeton SLICES expire régulièrement : la présence de ~/.slices/auth.json ne
# suffit donc pas, on teste un appel réel.
# ------------------------------------------------------------------------------
slices_ensure_auth() {
    local out
    # Sonde volontairement indépendante de l'expérience : « slices bi list » peut
    # échouer simplement parce que l'expérience n'existe pas encore.
    if out=$(slices bi flavor list 2>&1) &&
       ! grep -qiE "credential|log in again|unauthor" <<<"$out"; then
        ok "Jeton d'authentification SLICES valide."
        return 0
    fi
    warn "Jeton SLICES absent ou expiré — authentification interactive requise."
    if [ ! -t 0 ]; then
        die "Pas de terminal interactif : lance d'abord « source $SLICES_VENV/bin/activate && slices auth login »."
    fi
    slices auth login || die "Échec de l'authentification SLICES."
    ok "Authentification SLICES réussie."
}

# ------------------------------------------------------------------------------
# Renvoie 0 si l'expérience possède déjà au moins un nœud master joignable
# ------------------------------------------------------------------------------
slices_infra_exists() {
    # La CLI intercale « ansible_ssh_port=22 » entre le nom et ansible_ssh_host :
    #   master ansible_ssh_port=22 ansible_ssh_host=1.2.3.4 ansible_ssh_user=ubuntu
    # Exiger ansible_ssh_host juste après le nom ne matchait donc jamais, et le
    # script recréait des VMs au lieu de réutiliser celles déjà réservées.
    # On capture d'abord la sortie : « … | grep -q » sortirait dès la première
    # correspondance, tuerait « slices » par SIGPIPE (141), et « set -o pipefail »
    # transformerait ce succès en échec silencieux.
    local out rc=0
    out=$(slices bi list --experiment "$EXPERIMENT_NAME" --format ansible 2>/dev/null) || rc=$?
    # Un listage EN ÉCHEC ne veut pas dire « aucune VM » : confondre les deux
    # ferait recréer toute l'infrastructure et doublerait le quota consommé.
    # Seule exception : « experiment has expired / not found », qui signifie
    # légitimement qu'il n'y a plus rien.
    if [ "$rc" -ne 0 ] && ! grep -qiE "expired|not found|no resources" <<<"$out"; then
        die "Impossible de lister les ressources de « $EXPERIMENT_NAME » (code $rc).
   Par sécurité, on n'en déduit PAS que l'expérience est vide.
   Vérifie :  slices bi list --experiment $EXPERIMENT_NAME"
    fi
    grep -qE "^master[0-9]*[[:space:]].*ansible_ssh_host=[0-9]" <<<"$out"
}

# ------------------------------------------------------------------------------
# slices_create_infra <nombre_de_workers>
# ------------------------------------------------------------------------------
slices_create_infra() {
    local workers="$1"

    info "Réservation : 1 master ($MASTER_FLAVOR) + $workers workers ($WORKER_FLAVOR)"
    info "Site : $SITE_ID  |  Image : $OS_IMAGE  |  Durée : $DURATION"

    # Sans --public-ipv4, la VM ne reçoit qu'une adresse PRIVÉE et l'accès passe
    # par le jump host SSH de SLICES (bastion). C'est le chemin documenté, et il
    # évite d'exposer les machines sur Internet — donc aussi tout filtrage du
    # trafic entrant vers les adresses publiques.
    # --wait est le mécanisme officiel d'attente : il rend inutile tout sondage.
    local ip_opt=() ; [ "${USE_PUBLIC_IPV4:-false}" = "true" ] && ip_opt=(--public-ipv4)

    log "→ Création du nœud master…"
    if ! slices bi --site-id "$SITE_ID" create master \
            --experiment "$EXPERIMENT_NAME" \
            --image "$OS_IMAGE" --flavor "$MASTER_FLAVOR" \
            --duration "$DURATION" --count=1 --wait \
            "${ip_opt[@]}" --ssh-key-file "$WINDOWS_SSH_PUB_KEY"; then
        warn "La création du master a renvoyé une erreur (déjà existant ?). On poursuit."
    fi

    if [ "$workers" -gt 0 ]; then
        log "→ Création des $workers nœuds workers…"
        if ! slices bi --site-id "$SITE_ID" create workers \
                --experiment "$EXPERIMENT_NAME" \
                --image "$OS_IMAGE" --flavor "$WORKER_FLAVOR" \
                --duration "$DURATION" --count="$workers" --wait \
                "${ip_opt[@]}" --ssh-key-file "$WINDOWS_SSH_PUB_KEY"; then
            warn "La création des workers a renvoyé une erreur (déjà existants ?). On poursuit."
        fi
    fi

    log "Nettoyage du cache de connexions persistantes d'Ansible…"
    rm -rf "$HOME/.ansible/cp/"* 2>/dev/null || true
}

# ------------------------------------------------------------------------------
# slices_wait_for_vms <nombre_total_attendu> [timeout]
# Attend que SLICES ait attribué une IPv4 publique à toutes les VMs.
# ------------------------------------------------------------------------------
slices_wait_for_vms() {
    local expected="$1" timeout="${2:-600}" waited=0 found=0
    log "Attente de l'allocation des IPs pour $expected VMs (max ${timeout}s)…"
    while [ "$waited" -lt "$timeout" ]; do
        found=$(slices bi list --experiment "$EXPERIMENT_NAME" --format ansible 2>/dev/null \
                | grep -cE "ansible_ssh_host=[0-9]" || true)
        if [ "$found" -ge "$expected" ]; then
            ok "$found VMs disposent d'une adresse IP."
            return 0
        fi
        sleep 10; waited=$((waited + 10))
        log "  … $found/$expected VMs prêtes (${waited}s)"
    done
    warn "Seulement $found/$expected VMs ont une IP après ${timeout}s. On continue avec ce qui existe."
    [ "$found" -ge 2 ] || die "Pas assez de VMs pour construire un cluster."
}

# ------------------------------------------------------------------------------
# slices_build_inventory <chemin_inventaire>
# Produit un inventaire Ansible au format attendu par Kubespray.
# Variables globales positionnées en sortie : MASTER_VM, MASTER_IP, ALL_VMS_FILE
# ------------------------------------------------------------------------------
slices_build_inventory() {
    local inv="$1"
    local raw="raw_inventory.txt" valid="valid_vms.txt"

    slices bi list --experiment "$EXPERIMENT_NAME" --format ansible > "$raw" \
        || die "Impossible de lister les ressources de l'expérience $EXPERIMENT_NAME."
    grep "ansible_ssh_host" "$raw" > "$valid" || die "Aucune VM avec une IP dans l'expérience $EXPERIMENT_NAME."

    # La CLI émet déjà, PAR HÔTE, un « ansible_ssh_common_args='-J proxy@… ' »
    # quand la VM n'a pas d'IP publique. Or en Ansible les variables d'hôte
    # l'emportent sur celles de groupe : un [all:vars] ansible_ssh_common_args
    # serait purement ignoré. On fusionne donc NOS options DANS la chaîne
    # existante de chaque hôte, plutôt que de les déclarer à part.
    local extra="-o StrictHostKeyChecking=no -o ServerAliveInterval=30"
    if [ "${NETWORK_PROFILE:-original}" = "robust" ]; then
        extra="$extra -o UserKnownHostsFile=/dev/null -o ControlMaster=auto -o ControlPath=~/.ansible/cp/%r@%h:%p -o ControlPersist=30m -o ConnectTimeout=30"
    fi
    awk -v extra="$extra" '
        /ansible_ssh_common_args=/ {
            sub(/ansible_ssh_common_args='"'"'/, "ansible_ssh_common_args='"'"'" extra " ")
            print; next
        }
        { print $0 " ansible_ssh_common_args='"'"'" extra "'"'"'" }
    ' "$valid" > "$valid.merged" && mv "$valid.merged" "$valid"

    # Jump host : on le déduit de l'inventaire, il vaut pour toutes nos propres
    # connexions (scp des scripts, exécution des applications sur le master).
    SSH_JUMP=$(grep -oP -- '-J \K[^ '"'"']+' "$valid" | head -1 || true)
    if [ -n "${SSH_JUMP:-}" ]; then
        ok "Accès par le jump host SLICES : $SSH_JUMP (aucune IP publique exposée)"
        build_ssh_opts
    fi

    {
        echo "[all]"
        cat "$valid"
        echo
        echo "[all:vars]"
        echo "ansible_user=ubuntu"
        echo "ansible_ssh_private_key_file=$SSH_PRIV_KEY"
        echo "ansible_ssh_pipelining=True"
        echo "ansible_become_flags='-H -S -n'"
    } > "$inv"

    # Le master est nommé « master » ou « master0 » suivant la version de la CLI.
    MASTER_VM=$({ grep -E "^master" "$valid" || true; } | awk '{print $1}' | head -1)
    [ -n "$MASTER_VM" ] || die "Impossible d'identifier le nœud master dans l'inventaire SLICES."

    {
        echo
        echo "[kube_control_plane]"
        echo "$MASTER_VM"
        echo
        echo "[etcd]"
        echo "$MASTER_VM"
        echo
        echo "[kube_node]"
        # « || true » indispensable : sans worker (--workers 0), grep sort en 1 et,
        # avec set -e + pipefail, le script s'arrêterait en pleine génération.
        { grep -E "^workers" "$valid" || true; } | awk '{print $1}'
        echo
        echo "[k8s_cluster:children]"
        echo "kube_control_plane"
        echo "kube_node"
    } >> "$inv"

    MASTER_IP=$(awk -v m="$MASTER_VM" '$1==m {for(i=1;i<=NF;i++) if($i ~ /^ansible_ssh_host=/) {sub(/^ansible_ssh_host=/,"",$i); print $i}}' "$valid")
    [ -n "$MASTER_IP" ] || die "Impossible d'extraire l'IP du master ($MASTER_VM)."
    ALL_VMS_FILE="$valid"

    local nb_workers; nb_workers=$(grep -cE "^workers" "$valid" || true)
    ok "Inventaire généré : $MASTER_VM ($MASTER_IP) + $nb_workers workers → $inv"
    rm -f "$raw"
}

# ------------------------------------------------------------------------------
# Écrit les alias SSH locaux (~/.ssh/config) pour toutes les VMs de l'expérience
# ------------------------------------------------------------------------------
slices_write_ssh_aliases() {
    local vms_file="$1" cfg="$HOME/.ssh/config"
    mkdir -p "$HOME/.ssh"; touch "$cfg"; chmod 600 "$cfg"

    # Bloc dédié au jump host. Sans lui, la première connexion demande
    # « Are you sure you want to continue connecting (yes/no)? » : les options
    # « -o » de la ligne de commande s'appliquent à la DESTINATION, pas au
    # rebond, qui est une connexion distincte. En exécution non interactive
    # (tâche de fond, CI), cette question fige le déploiement indéfiniment.
    # ssh, scp ET Ansible lisent tous ~/.ssh/config : un seul bloc suffit.
    if [ -n "${SSH_JUMP:-}" ]; then
        local jhost="${SSH_JUMP#*@}"
        ssh_alias_remove "$jhost"
        cat >> "$cfg" <<EOF
Host $jhost
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    LogLevel ERROR

EOF
        log "Jump host $jhost déclaré dans ~/.ssh/config (aucune question de clé d'hôte)."
    fi

    while read -r line; do
        local name ip
        name=$(awk '{print $1}' <<<"$line")
        ip=$(awk '{for(i=1;i<=NF;i++) if($i ~ /^ansible_ssh_host=/) {sub(/^ansible_ssh_host=/,"",$i); print $i}}' <<<"$line")
        [ -n "$name" ] && [ -n "$ip" ] || continue
        ssh_alias_remove "$name"
        cat >> "$cfg" <<EOF
Host $name
    HostName $ip
    User ubuntu
    IdentityFile $SSH_PRIV_KEY
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    LogLevel ERROR
$([ -n "${SSH_JUMP:-}" ] && printf '    ProxyJump %s\n' "$SSH_JUMP")

EOF
    done < "$vms_file"

    sed -i '/^$/N;/^\n$/D' "$cfg" 2>/dev/null || true
    ok "Alias SSH écrits dans $cfg"
}

# Supprime proprement le bloc « Host <nom> » du ~/.ssh/config
ssh_alias_remove() {
    local name="$1" cfg="$HOME/.ssh/config"
    [ -f "$cfg" ] || return 0
    awk -v target="$name" '
        /^Host[ \t]+/ { inblock = ($2 == target) }
        !inblock { print }
    ' "$cfg" > "$cfg.tmp" && mv "$cfg.tmp" "$cfg"
    chmod 600 "$cfg"
}

# ------------------------------------------------------------------------------
# Destruction de l'expérience côté SLICES
# ------------------------------------------------------------------------------
slices_destroy() {
    info "Destruction des VMs de l'expérience « $EXPERIMENT_NAME »…"
    # --yes-all-of-them SÉLECTIONNE toutes les ressources mais demande quand même
    # une confirmation par ressource : sans --force, la commande s'interrompt dès
    # qu'aucun terminal n'est disponible, en laissant les VMs actives.
    slices bi destroy --experiment "$EXPERIMENT_NAME" --yes-all-of-them --force \
        || warn "La commande de destruction a renvoyé une erreur."

    # On ne se fie pas au code de retour : on vérifie que plus rien ne subsiste.
    local remaining
    remaining=$(slices bi list --experiment "$EXPERIMENT_NAME" --format ansible 2>/dev/null \
                | grep -cE "ansible_ssh_host=[0-9]" || true)
    if [ "${remaining:-0}" -gt 0 ]; then
        err "$remaining ressource(s) subsistent dans l'expérience « $EXPERIMENT_NAME » !"
        err "Elles consomment toujours ton quota. Détruis-les à la main :"
        err "  slices bi destroy --experiment $EXPERIMENT_NAME --yes-all-of-them --force"
        return 1
    fi
    ok "Toutes les ressources SLICES ont été détruites."
}
