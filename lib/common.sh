#!/bin/bash
# ==============================================================================
# lib/common.sh — Fonctions utilitaires partagées
# ==============================================================================
# Ce fichier est sourcé par deploy.sh et destroy.sh. Il ne s'exécute pas seul.
# ==============================================================================

# ------------------------------------------------------------------------------
# Couleurs et journalisation
# ------------------------------------------------------------------------------
if [ -t 1 ]; then
    C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
    C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_BLUE=$'\033[34m'
else
    C_RESET=""; C_BOLD=""; C_DIM=""; C_RED=""; C_GREEN=""; C_YELLOW=""; C_BLUE=""
fi

log()   { echo "${C_DIM}   $*${C_RESET}"; }
info()  { echo "${C_BLUE}ℹ️  $*${C_RESET}"; }
ok()    { echo "${C_GREEN}✅ $*${C_RESET}"; }
warn()  { echo "${C_YELLOW}⚠️  $*${C_RESET}" >&2; }
err()   { echo "${C_RED}❌ $*${C_RESET}" >&2; }
die()   { err "$@"; exit 1; }

# step <numéro> <total> <titre>
step() {
    echo
    echo "${C_BOLD}${C_BLUE}━━━ [$1/$2] $3 ━━━${C_RESET}"
}

banner() {
    echo
    echo "${C_BOLD}=============================================================${C_RESET}"
    echo "${C_BOLD} $*${C_RESET}"
    echo "${C_BOLD}=============================================================${C_RESET}"
}

# ------------------------------------------------------------------------------
# Confirmation interactive (contournée par --yes / ASSUME_YES=1)
# ------------------------------------------------------------------------------
confirm() {
    local prompt="$1"
    if [ "${ASSUME_YES:-0}" = "1" ]; then
        log "(--yes) $prompt → oui"
        return 0
    fi
    if [ ! -t 0 ]; then
        die "Confirmation requise mais le terminal n'est pas interactif. Relance avec --yes."
    fi
    read -r -p "${C_YELLOW}❓ $prompt [o/N] ${C_RESET}" reply
    case "$reply" in
        [oOyY]|[oO][uU][iI]|[yY][eE][sS]) return 0 ;;
        *) return 1 ;;
    esac
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "Commande '$1' introuvable. $2"
}

# ------------------------------------------------------------------------------
# Chargement et validation du fichier .env
# ------------------------------------------------------------------------------
load_env() {
    local root="$1"
    if [ ! -f "$root/.env" ]; then
        err "Le fichier .env est introuvable dans $root."
        die "Copie le modèle puis adapte-le :  cp .env.example .env"
    fi
    info "Chargement des paramètres depuis .env"
    # shellcheck disable=SC1090
    set -a; source "$root/.env"; set +a

    : "${EXPERIMENT_NAME:?EXPERIMENT_NAME manquant dans .env}"
    : "${SITE_ID:?SITE_ID manquant dans .env}"
    : "${OS_IMAGE:?OS_IMAGE manquant dans .env}"
    : "${DURATION:?DURATION manquant dans .env}"
    : "${WINDOWS_SSH_PRIV_KEY:?WINDOWS_SSH_PRIV_KEY manquant dans .env}"
    : "${WINDOWS_SSH_PUB_KEY:?WINDOWS_SSH_PUB_KEY manquant dans .env}"

    # Valeurs par défaut (rétro-compatibilité avec les anciens .env)
    MASTER_FLAVOR="${MASTER_FLAVOR:-medium}"
    WORKER_FLAVOR="${WORKER_FLAVOR:-medium}"
    WORKER_COUNT="${WORKER_COUNT:-auto}"
    APPS="${APPS:-otel-demo}"
    SLICES_VENV="${SLICES_VENV:-$HOME/slices-venv}"
    SSH_PRIV_KEY="${SSH_PRIV_KEY:-$HOME/.ssh/id_rsa_slices}"
    INVENTORY_FILE="${INVENTORY_FILE:-inventory.ini}"
    REMOTE_WORKDIR="${REMOTE_WORKDIR:-/home/ubuntu/autodeploy}"
    SSH_WAIT_TIMEOUT="${SSH_WAIT_TIMEOUT:-900}"
    SSH_POLL_INTERVAL="${SSH_POLL_INTERVAL:-20}"
    SSH_INITIAL_DELAY="${SSH_INITIAL_DELAY:-60}"
    # Le master met couramment plus de 2 minutes à ouvrir sshd : en dessous de
    # 300 s on abandonne une VM parfaitement saine.
    if [ "$SSH_WAIT_TIMEOUT" -lt 300 ] 2>/dev/null; then
        warn "SSH_WAIT_TIMEOUT=$SSH_WAIT_TIMEOUT s est trop court, relevé à 300 s."
        SSH_WAIT_TIMEOUT=300
    fi
    # Un intervalle nul ou négatif produirait une boucle de sondage infinie,
    # exactement le comportement qui fait blackholer une IP.
    if [ "$SSH_POLL_INTERVAL" -lt 5 ] 2>/dev/null; then
        warn "SSH_POLL_INTERVAL=$SSH_POLL_INTERVAL s est trop agressif, relevé à 5 s."
        SSH_POLL_INTERVAL=5
    fi
    [ "$SSH_INITIAL_DELAY" -ge 0 ] 2>/dev/null || SSH_INITIAL_DELAY=60

    OTEL_NAMESPACE="${OTEL_NAMESPACE:-otel-demo}"
    OTEL_RELEASE="${OTEL_RELEASE:-my-otel-demo}"
    OTEL_CHART_VERSION="${OTEL_CHART_VERSION:-}"
    OTEL_NODEPORT="${OTEL_NODEPORT:-30080}"

    TT_NAMESPACE="${TT_NAMESPACE:-train-ticket}"
    TT_REPO_URL="${TT_REPO_URL:-https://github.com/FudanSELab/train-ticket.git}"
    TT_REF="${TT_REF:-master}"
    TT_DEPLOY_ARGS="${TT_DEPLOY_ARGS:-}"
    TT_UI_NODEPORT="${TT_UI_NODEPORT:-32677}"
    TT_GATEWAY_NODEPORT="${TT_GATEWAY_NODEPORT:-30467}"

    HELM3_VERSION="${HELM3_VERSION:-}"
    HELM4_VERSION="${HELM4_VERSION:-}"
    KUBESPRAY_REF="${KUBESPRAY_REF:-master}"

    # Profil réseau : "original" reproduit le comportement du script initial,
    # qui fonctionnait ; "robust" ajoute sondage et multiplexage.
    NETWORK_PROFILE="${NETWORK_PROFILE:-original}"
    INITIAL_SLEEP="${INITIAL_SLEEP:-20}"
    USE_PUBLIC_IPV4="${USE_PUBLIC_IPV4:-false}"
    SSH_JUMP="${SSH_JUMP:-}"
    build_ssh_opts
}

# ------------------------------------------------------------------------------
# Profils de dimensionnement
# ------------------------------------------------------------------------------
# Renvoie le nombre de workers à créer pour la sélection d'applications donnée.
# Un WORKER_COUNT numérique dans .env (ou --workers) écrase toujours le profil.
resolve_worker_count() {
    local apps=" $1 "
    if [ "${WORKER_COUNT}" != "auto" ]; then
        echo "$WORKER_COUNT"; return
    fi
    local has_otel=0 has_tt=0
    [[ "$apps" == *" otel-demo "* ]]    && has_otel=1
    [[ "$apps" == *" train-ticket "* ]] && has_tt=1
    if [ "$has_otel" = 1 ] && [ "$has_tt" = 1 ]; then
        echo "${PROFILE_BOTH_WORKERS:-6}"
    elif [ "$has_tt" = 1 ]; then
        echo "${PROFILE_TT_WORKERS:-4}"
    else
        echo "${PROFILE_OTEL_WORKERS:-3}"
    fi
}

# Besoins mémoire (Mio) et CPU (milli-cœurs) mesurés sur les manifestes amont.
# Utilisés pour l'avertissement de capacité, pas pour bloquer le déploiement.
app_ram_mib() {
    case "$1" in
        otel-demo)    echo 9000 ;;
        train-ticket) echo 17000 ;;
        *)            echo 0 ;;
    esac
}
app_cpu_milli() {
    case "$1" in
        otel-demo)    echo 3000 ;;
        train-ticket) echo 5000 ;;
        *)            echo 0 ;;
    esac
}

# ------------------------------------------------------------------------------
# Normalisation de la sélection d'applications
# ------------------------------------------------------------------------------
# Accepte « otel », « tt », « both », des listes séparées par virgules ou
# espaces, et renvoie une liste canonique : « otel-demo train-ticket ».
normalize_apps() {
    local raw="${1:-}" token out=""
    raw="${raw//,/ }"
    for token in $raw; do
        case "$(tr '[:upper:]' '[:lower:]' <<<"$token")" in
            otel|otel-demo|oteldemo|opentelemetry|opentelemetry-demo)
                out="$out otel-demo" ;;
            tt|train|trainticket|train-ticket|train_ticket)
                out="$out train-ticket" ;;
            both|all|les-deux|deux|tout)
                out="$out otel-demo train-ticket" ;;
            none|aucune|aucun)
                out="$out" ;;
            *) die "Application inconnue : « $token » (attendu : otel-demo, train-ticket ou both)" ;;
        esac
    done
    # déduplication en conservant l'ordre
    local seen="" app final=""
    for app in $out; do
        case " $seen " in *" $app "*) continue ;; esac
        seen="$seen $app"; final="$final $app"
    done
    echo "${final# }"
}


# ------------------------------------------------------------------------------
# purge_ansible_facts <fichier_inventaire>
# ------------------------------------------------------------------------------
# L'ansible.cfg de Kubespray active « fact_caching = jsonfile » vers /tmp, avec
# une validité de 24 h, et les fichiers sont indexés par NOM D'HÔTE. Kubespray y
# écrit des faits « cacheable » comme main_ip et main_access_ip.
#
# Nos VMs s'appelant toujours master, workers0, workers1…, des machines
# entièrement NEUVES héritent donc des adresses des précédentes. Kubespray
# échoue alors sur « Stop if access_ip is not pingable » en tentant de joindre
# une adresse qui n'existe plus. Ni destroy.sh, ni la suppression du dossier
# kubespray/, ni la destruction des VMs ne nettoyaient ce cache.
#
# On ne supprime QUE les fichiers correspondant aux hôtes de notre inventaire :
# jamais de purge globale de /tmp.
purge_ansible_facts() {
    local inv="${1:-}" cache_dir="${ANSIBLE_FACT_CACHE_DIR:-/tmp}" host n=0
    [ -f "$inv" ] || return 0
    while read -r host _; do
        case "$host" in ""|\[*|*=*) continue ;; esac
        if [ -f "$cache_dir/$host" ]; then
            rm -f "$cache_dir/$host" && n=$((n + 1))
        fi
    done < <(awk '/^\[all\]/{f=1;next} /^\[/{f=0} f' "$inv")
    [ "$n" -gt 0 ] && log "$n fichier(s) de cache de faits Ansible purgé(s) (adresses périmées)."
    return 0
}

# ------------------------------------------------------------------------------
# Aides SSH
# ------------------------------------------------------------------------------
SSH_MUX_DIR="${SSH_MUX_DIR:-$HOME/.ssh/mux-autodeploy}"

# ------------------------------------------------------------------------------
# Options SSH, selon NETWORK_PROFILE (voir .env)
# ------------------------------------------------------------------------------
#   "original" : strictement les options du script d'origine, qui fonctionnait.
#                Aucune connexion persistante, aucune option supplémentaire.
#   "robust"   : ajoute le multiplexage ControlMaster, qui réduit le nombre de
#                connexions TCP quand le script en ouvre beaucoup — mais laisse
#                des sockets ouverts, ce qu'un pare-feu peut compter comme des
#                connexions simultanées.
# Le profil est appliqué par build_ssh_opts(), appelé à la fin de load_env().
build_ssh_opts() {
    # Le jump host, quand il existe, doit être présent sur TOUTES nos connexions :
    # les VMs n'ont alors qu'une adresse privée, injoignable autrement.
    local jump=()
    [ -n "${SSH_JUMP:-}" ] && jump=(-J "$SSH_JUMP")

    if [ "${NETWORK_PROFILE:-original}" = "robust" ]; then
        mkdir -p "$SSH_MUX_DIR" 2>/dev/null || true
        chmod 700 "$SSH_MUX_DIR" 2>/dev/null || true
        SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
                  -o LogLevel=ERROR -o ConnectTimeout=15 -o ServerAliveInterval=30
                  -o ControlMaster=auto -o "ControlPath=$SSH_MUX_DIR/%r@%h:%p"
                  -o ControlPersist=60 "${jump[@]}")
    else
        # Exactement ce que faisait le script d'origine, rien de plus.
        SSH_OPTS=(-o StrictHostKeyChecking=no -o ServerAliveInterval=30 "${jump[@]}")
    fi
}

SSH_OPTS=(-o StrictHostKeyChecking=no -o ServerAliveInterval=30)

# Ferme toutes nos connexions multiplexées encore ouvertes.
# Indispensable avant de lancer Ansible : nos sockets persistants s'ajoutent
# sinon à ceux d'Ansible, et le total de connexions TCP simultanées vers le
# site peut dépasser sa limite par IP source — ce qui rend des hôtes
# « unreachable » en plein milieu de Kubespray.
ssh_mux_close_all() {
    local s closed=0
    for s in "$SSH_MUX_DIR"/* "$HOME/.ansible/cp"/*; do
        [ -S "$s" ] || continue
        ssh -O exit -o ControlPath="$s" x >/dev/null 2>&1 || rm -f "$s"
        closed=$((closed + 1))
    done
    [ "$closed" -gt 0 ] && log "$closed connexion(s) SSH persistante(s) fermée(s)."
    return 0
}

# ssh_exec <ip> <commande...>
ssh_exec() {
    local ip="$1"; shift
    ssh -i "$SSH_PRIV_KEY" "${SSH_OPTS[@]}" "ubuntu@$ip" "$@"
}

# ssh_stdin <ip>  — exécute le script fourni sur stdin
ssh_stdin() {
    local ip="$1"
    ssh -i "$SSH_PRIV_KEY" "${SSH_OPTS[@]}" "ubuntu@$ip" "bash -s"
}

scp_to() {
    local ip="$1" src="$2" dest="$3"
    scp -i "$SSH_PRIV_KEY" "${SSH_OPTS[@]}" -q -r "$src" "ubuntu@$ip:$dest"
}

# diagnose_unreachable <ip>
# Traduit un échec de connexion en cause probable. Distinguer « la VM n'a pas
# fini de démarrer » d'un « filtrage réseau » change complètement la marche à
# suivre, et ces deux cas produisent le même timeout côté ssh.
diagnose_unreachable() {
    local ip="$1" icmp="KO" tcp22="KO"

    # IMPORTANT : ne JAMAIS sonder avec « /dev/tcp » (ni nc -z, ni nmap).
    # Ouvrir une connexion TCP puis la refermer sans échanger d'octet est la
    # signature exacte d'un « connect scan » : les IDS des infrastructures de
    # recherche la détectent et blackholent l'IP source. On teste donc avec un
    # vrai SSH, qui mène un échange de protocole complet et légitime.
    ping -c2 -W2 "$ip" >/dev/null 2>&1 && icmp="OK"
    ssh -n -i "$SSH_PRIV_KEY" "${SSH_OPTS[@]}" -o BatchMode=yes \
        "ubuntu@$ip" true >/dev/null 2>&1 && tcp22="OK"

    echo
    err "Diagnostic de $ip :  ICMP=$icmp  SSH=$tcp22"

    if [ "$icmp" = "KO" ]; then
        err "La VM ne répond pas du tout : elle n'a pas fini de démarrer, ou elle est en panne."
        err "  → slices bi show <nom> --experiment $EXPERIMENT_NAME"
        err "  → slices bi reset <nom> --experiment $EXPERIMENT_NAME   (redémarrage forcé)"
    elif [ "$tcp22" = "OK" ]; then
        err "Le port 22 répond maintenant : il s'agissait d'un simple retard de démarrage."
        err "  → relance ./deploy.sh (les VMs seront réutilisées), ou augmente SSH_WAIT_TIMEOUT."
    else
        err "La VM répond au ping mais le port 22 est jeté (timeout, pas « refused »)."
        err "C'est la signature d'un filtrage réseau, pas d'un problème de clé SSH"
        err "(une mauvaise clé donnerait « Permission denied », pas un timeout)."
        err "Vérifications à faire, dans cet ordre :"
        err "  1. sshd tourne-t-il ? Si « slices bi show <nom> » affiche des"
        err "     « SSH Hostkey fingerprints », c'est que oui → le blocage est réseau."
        err "  2. Ton TCP sortant est-il libre ?  ssh -o BatchMode=yes git@github.com"
        err "     (n'utilise pas « nc -z » ni « /dev/tcp » : ce sont des scans)"
        err "  3. Connecte-toi par la console web, qui n'utilise pas SSH :"
        err "       slices bi console <nom> --experiment $EXPERIMENT_NAME"
        err "     puis, dans la VM :  ss -tlnp | grep :22   et   sudo iptables -L -n"
        err "  4. Si la VM est saine, le filtrage est côté site : signale-le au support"
        err "     SLICES en précisant ton IP publique ($(timeout 8 curl -s https://ifconfig.me 2>/dev/null || echo inconnue))."
    fi
    echo
}

# wait_for_ssh <ip> [timeout_secondes]
# Remplace le « sleep 20 » aveugle : on attend que sshd réponde vraiment.
wait_for_ssh() {
    local ip="$1" timeout="${2:-300}" waited=0

    # Profil "original" : on reproduit le script initial — une seule temporisation,
    # puis UNE vérification. Si elle échoue, on avertit sans bloquer : Kubespray
    # sait retenter, et c'est ainsi que le script d'origine fonctionnait.
    if [ "${NETWORK_PROFILE:-original}" != "robust" ]; then
        log "Attente de ${INITIAL_SLEEP}s puis vérification de $ip (profil réseau : original)…"
        sleep "$INITIAL_SLEEP"
        if ssh -n -i "$SSH_PRIV_KEY" "${SSH_OPTS[@]}" -o BatchMode=yes \
               -o ConnectTimeout=15 "ubuntu@$ip" true >/dev/null 2>&1; then
            ok "SSH opérationnel sur $ip"
            return 0
        fi
        warn "$ip ne répond pas encore — on poursuit, Kubespray retentera."
        return 0
    fi

    # Profil "robust" : sondage espacé, avec délai de grâce.
    local grace="${SSH_INITIAL_DELAY:-60}"
    log "Attente de SSH sur $ip (max ${timeout}s, première tentative dans ${grace}s)…"
    sleep "$grace"
    while [ "$waited" -lt "$timeout" ]; do
        if ssh -n -i "$SSH_PRIV_KEY" "${SSH_OPTS[@]}" -o BatchMode=yes \
               "ubuntu@$ip" true >/dev/null 2>&1; then
            ok "SSH opérationnel sur $ip (après ${waited}s)"
            return 0
        fi
        sleep "$SSH_POLL_INTERVAL"; waited=$((waited + SSH_POLL_INTERVAL))
        [ $((waited % 60)) -lt "$SSH_POLL_INTERVAL" ] && log "  … toujours en attente de $ip (${waited}s)"
    done
    err "SSH injoignable sur $ip après ${timeout}s."
    return 1
}

