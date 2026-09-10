#!/bin/bash
# ==============================================================================
# apps/instrument.sh — Attacher le mouchard OpenTelemetry à des services Java
#
#   Sans mouchard, un programme est muet : il fait son travail mais n'écrit
#   aucune note. Or les notes sont la SEULE source des quatre relations du
#   graphe, et la seule source des débits déposé et retiré d'une file — les
#   compteurs du courtier ne les portent pas par file.
#
#   Le mouchard est attaché SANS TOUCHER AU CODE de l'application : un conteneur
#   d'amorçage dépose le fichier de l'agent dans un dossier partagé, et la
#   machine virtuelle Java est lancée en le chargeant.
#
#   Usage (depuis le master) :
#       bash ~/autodeploy/apps/instrument.sh install ts-food-service ts-delivery-service
#       bash ~/autodeploy/apps/instrument.sh install --all
#       bash ~/autodeploy/apps/instrument.sh status
#       bash ~/autodeploy/apps/instrument.sh uninstall ts-food-service
#
#   Variables d'environnement reconnues :
#     INST_NAMESPACE      (défaut: train-ticket)   namespace applicatif
#     INST_PREFIX         (défaut: ts-)            motif des déploiements pour --all
#     INST_AGENT_IMAGE    (défaut: image officielle de l'agent Java)
#     INST_OTLP_PORT      (défaut: 4318)           port du collecteur sur la machine
#     INST_SEMCONV        (défaut: messaging)      jeu de noms des conventions
#     INST_SAMPLER        (défaut: parentbased_always_on)
#     INST_SERVICE_LABEL  (défaut: app)            étiquette qui porte le nom du service
#     INST_TIMEOUT        (défaut: 300)            attente du redémarrage, en secondes
# ==============================================================================
set -euo pipefail

NAMESPACE="${INST_NAMESPACE:-train-ticket}"
PREFIX="${INST_PREFIX:-ts-}"

# ------------------------------------------------------------------------------
# Comment l'agent arrive dans le pod : deux voies
# ------------------------------------------------------------------------------
# « download » (défaut) — un conteneur d'amorçage minuscule télécharge le fichier
#   de l'agent depuis le dépôt public de bibliothèques Java. Ne demande que
#   Docker Hub et ce dépôt. C'est la voie la plus portable, et c'est celle qui
#   marche sur SLICES-RI : le registre d'images de GitHub y répond « interdit ».
#
# « image » — un conteneur d'amorçage tiré d'une image qui contient déjà l'agent.
#   Plus rapide et sans accès réseau au démarrage, mais suppose que le registre
#   soit joignable. À utiliser sur une grappe qui l'autorise.
#
# La version est FIGÉE, pas « latest » : deux campagnes lancées à des mois
# d'écart doivent charger le même agent, sinon le dispositif expérimental change
# sans que rien ne le signale.
AGENT_MODE="${INST_AGENT_MODE:-download}"
AGENT_VERSION="${INST_AGENT_VERSION:-2.31.1}"
AGENT_URL="${INST_AGENT_URL:-https://repo1.maven.org/maven2/io/opentelemetry/javaagent/opentelemetry-javaagent/${AGENT_VERSION}/opentelemetry-javaagent-${AGENT_VERSION}.jar}"
DOWNLOAD_IMAGE="${INST_DOWNLOAD_IMAGE:-curlimages/curl:8.11.1}"
AGENT_IMAGE="${INST_AGENT_IMAGE:-ghcr.io/open-telemetry/opentelemetry-java-instrumentation/autoinstrumentation-java:${AGENT_VERSION}}"
OTLP_PORT="${INST_OTLP_PORT:-4318}"
SEMCONV="${INST_SEMCONV:-messaging}"
SAMPLER="${INST_SAMPLER:-parentbased_always_on}"
SERVICE_LABEL="${INST_SERVICE_LABEL:-app}"
TIMEOUT="${INST_TIMEOUT:-300}"

VOL_NAME="otel-agent"
INIT_NAME="otel-agent-init"
AGENT_DIR="/otel"

say()  { echo "  [instrument] $*"; }
warn() { echo "  [instrument] ATTENTION: $*" >&2; }
fail() { echo "  [instrument] ERREUR: $*" >&2; exit 1; }

# ------------------------------------------------------------------------------
# Sélection des déploiements à traiter
# ------------------------------------------------------------------------------
list_targets() {
    if [ "${1:-}" = "--all" ]; then
        kubectl get deploy -n "$NAMESPACE" --no-headers -o custom-columns=:metadata.name \
            | grep "^${PREFIX}" || true
    else
        printf '%s\n' "$@"
    fi
}

# ------------------------------------------------------------------------------
# Contrôle préalable : le collecteur écoute-t-il bien sur les machines ?
# ------------------------------------------------------------------------------
# Les services enverront leurs notes à l'adresse de LEUR PROPRE machine. C'est ce
# qui rend l'opération portable : aucun nom de service à connaître, aucune
# adresse à coder en dur. Encore faut-il qu'un collecteur écoute sur chaque
# machine — sinon les notes partent dans le vide, sans erreur visible côté
# application.
# ------------------------------------------------------------------------------
preflight() {
    kubectl get namespace "$NAMESPACE" >/dev/null 2>&1 \
        || fail "Namespace « $NAMESPACE » introuvable."

    local ds
    ds=$(kubectl get daemonset -A --no-headers 2>/dev/null \
         | awk '$2 ~ /opentelemetry-collector/ {print $1"/"$2; exit}' || true)
    if [ -z "$ds" ]; then
        warn "Aucun collecteur en DaemonSet trouvé sur la grappe."
        warn "Les notes seraient émises sans destinataire. Lance d'abord :"
        warn "    bash \$(dirname \$0)/observability.sh install"
        fail "Interrompu avant de modifier quoi que ce soit."
    fi
    say "Collecteur détecté : $ds"
}

# ------------------------------------------------------------------------------
# Attacher le mouchard à un déploiement
# ------------------------------------------------------------------------------
# Trois ajouts, tous par fusion : un dossier partagé, un conteneur d'amorçage qui
# y dépose l'agent, et les variables qui disent à Java de le charger.
#
# Deux choix méritent d'être expliqués.
#
#   • Le nom du service est lu sur l'étiquette du pod, pas écrit en dur. C'est
#     exactement ce que faisait déjà le manifeste SkyWalking du dépôt amont, et
#     ça rend la fonction utilisable sur n'importe quelle application.
#
#   • Le jeu de noms des conventions est forcé. Sans ce réglage, un producteur
#     qui publie sur l'échange par défaut — ce que fait train-ticket — fait
#     écrire au mouchard le mot « <default> » à la place du nom de la file. Les
#     deux files du système porteraient alors la même clé et fusionneraient en un
#     seul nœud du graphe, sans le moindre message d'erreur.
# ------------------------------------------------------------------------------
instrument_one() {
    local dep="$1"
    kubectl get deploy -n "$NAMESPACE" "$dep" >/dev/null 2>&1 \
        || { warn "Déploiement « $dep » introuvable — ignoré."; return 0; }

    local cname
    cname=$(kubectl get deploy -n "$NAMESPACE" "$dep" \
            -o jsonpath='{.spec.template.spec.containers[0].name}' 2>/dev/null)
    [ -n "$cname" ] || { warn "Conteneur introuvable dans « $dep » — ignoré."; return 0; }

    local already
    already=$(kubectl get deploy -n "$NAMESPACE" "$dep" \
              -o jsonpath="{.spec.template.spec.initContainers[?(@.name=='${INIT_NAME}')].name}" 2>/dev/null || true)
    if [ -n "$already" ]; then
        say "$dep : déjà instrumenté — ignoré."
        return 0
    fi

    local init_image init_cmd
    if [ "$AGENT_MODE" = "image" ]; then
        init_image="$AGENT_IMAGE"
        init_cmd="[\"cp\", \"/javaagent.jar\", \"${AGENT_DIR}/javaagent.jar\"]"
    else
        init_image="$DOWNLOAD_IMAGE"
        init_cmd="[\"sh\", \"-c\", \"curl -fsSL -o ${AGENT_DIR}/javaagent.jar '${AGENT_URL}' && ls -l ${AGENT_DIR}/javaagent.jar\"]"
    fi

    local pf; pf=$(mktemp)
    cat > "$pf" <<EOF
spec:
  template:
    spec:
      volumes:
        - name: ${VOL_NAME}
          emptyDir: {}
      initContainers:
        - name: ${INIT_NAME}
          image: ${init_image}
          command: ${init_cmd}
          volumeMounts:
            - name: ${VOL_NAME}
              mountPath: ${AGENT_DIR}
      containers:
        - name: ${cname}
          volumeMounts:
            - name: ${VOL_NAME}
              mountPath: ${AGENT_DIR}
          env:
            # L'adresse de la machine qui héberge ce pod. C'est là qu'écoute le
            # collecteur, et c'est ce qui évite de coder une adresse en dur.
            - name: OTEL_NODE_IP
              valueFrom:
                fieldRef:
                  fieldPath: status.hostIP
            - name: OTEL_SERVICE_NAME
              valueFrom:
                fieldRef:
                  fieldPath: "metadata.labels['${SERVICE_LABEL}']"
            - name: OTEL_EXPORTER_OTLP_ENDPOINT
              value: "http://\$(OTEL_NODE_IP):${OTLP_PORT}"
            - name: OTEL_EXPORTER_OTLP_PROTOCOL
              value: "http/protobuf"
            # Sans ceci, les deux files du système fusionnent en une seule.
            - name: OTEL_SEMCONV_STABILITY_OPT_IN
              value: "${SEMCONV}"
            # Aucune note n'est jetée : le taux d'échantillonnage vaut donc un.
            # C'est un choix de dispositif, à déclarer tel quel : il rend la
            # correction d'échantillonnage inutile, au prix du volume.
            - name: OTEL_TRACES_SAMPLER
              value: "${SAMPLER}"
            # On ne veut que les notes, pas les compteurs ni les journaux : les
            # compteurs viennent déjà d'ailleurs, et les faire remonter deux fois
            # ne ferait qu'ajouter du bruit.
            - name: OTEL_METRICS_EXPORTER
              value: "none"
            - name: OTEL_LOGS_EXPORTER
              value: "none"
            - name: JAVA_TOOL_OPTIONS
              value: "-javaagent:${AGENT_DIR}/javaagent.jar"
EOF
    kubectl patch deploy -n "$NAMESPACE" "$dep" --patch-file "$pf" >/dev/null \
        && say "$dep : mouchard attaché (conteneur « $cname »)" \
        || warn "$dep : le patch a échoué."
    rm -f "$pf"
}

# ------------------------------------------------------------------------------
retirer_one() {
    local dep="$1"
    kubectl get deploy -n "$NAMESPACE" "$dep" >/dev/null 2>&1 || return 0
    local cname
    cname=$(kubectl get deploy -n "$NAMESPACE" "$dep" \
            -o jsonpath='{.spec.template.spec.containers[0].name}' 2>/dev/null)

    kubectl patch deploy -n "$NAMESPACE" "$dep" -p \
      "{\"spec\":{\"template\":{\"spec\":{
          \"initContainers\":[{\"name\":\"${INIT_NAME}\",\"\$patch\":\"delete\"}],
          \"volumes\":[{\"name\":\"${VOL_NAME}\",\"\$patch\":\"delete\"}],
          \"containers\":[{\"name\":\"${cname}\",\"volumeMounts\":[{\"name\":\"${VOL_NAME}\",\"mountPath\":\"${AGENT_DIR}\",\"\$patch\":\"delete\"}]}]}}}}" \
      >/dev/null 2>&1 || true

    kubectl set env deploy -n "$NAMESPACE" "$dep" \
        OTEL_NODE_IP- OTEL_SERVICE_NAME- OTEL_EXPORTER_OTLP_ENDPOINT- \
        OTEL_EXPORTER_OTLP_PROTOCOL- OTEL_SEMCONV_STABILITY_OPT_IN- \
        OTEL_TRACES_SAMPLER- OTEL_METRICS_EXPORTER- OTEL_LOGS_EXPORTER- \
        JAVA_TOOL_OPTIONS- >/dev/null 2>&1 || true
    say "$dep : mouchard retiré."
}

# ------------------------------------------------------------------------------
install_cmd() {
    [ $# -gt 0 ] || fail "Indique un ou plusieurs services, ou --all."
    preflight
    say "Agent : version $AGENT_VERSION, mode « $AGENT_MODE »"
    local targets; targets=$(list_targets "$@")
    [ -n "$targets" ] || fail "Aucun déploiement sélectionné."
    local n=0
    while read -r d; do [ -n "$d" ] || continue; instrument_one "$d"; n=$((n+1)); done <<<"$targets"

    say "Attente du redémarrage des $n déploiement(s)…"
    while read -r d; do
        [ -n "$d" ] || continue
        kubectl rollout status deploy -n "$NAMESPACE" "$d" --timeout="${TIMEOUT}s" >/dev/null 2>&1 \
            && say "  $d : redémarré" \
            || warn "  $d : n'a pas convergé en ${TIMEOUT}s — regarde « kubectl logs »."
    done <<<"$targets"
    status_cmd
}

uninstall_cmd() {
    [ $# -gt 0 ] || fail "Indique un ou plusieurs services, ou --all."
    local targets; targets=$(list_targets "$@")
    while read -r d; do [ -n "$d" ] || continue; retirer_one "$d"; done <<<"$targets"
}

status_cmd() {
    echo
    say "Déploiements instrumentés dans « $NAMESPACE » :"
    local found=0
    while read -r d; do
        [ -n "$d" ] || continue
        local i
        i=$(kubectl get deploy -n "$NAMESPACE" "$d" \
            -o jsonpath="{.spec.template.spec.initContainers[?(@.name=='${INIT_NAME}')].image}" 2>/dev/null || true)
        if [ -n "$i" ]; then printf "    %-34s %s\n" "$d" "$i"; found=$((found+1)); fi
    done < <(kubectl get deploy -n "$NAMESPACE" --no-headers -o custom-columns=:metadata.name 2>/dev/null)
    [ "$found" = "0" ] && say "    aucun."
    echo
    # « grep -m1 » ferme le tube dès la première correspondance, ce qui envoie un
    # SIGPIPE à kubectl. Sous « pipefail », le tube entier est alors compté en
    # échec ALORS QUE la version a bien été trouvée, et le message de repli
    # s'affichait juste après le résultat. On capture donc d'abord, on teste
    # ensuite. C'est le même piège que celui déjà signalé dans train-ticket.sh.
    say "Version réellement chargée (à figer dans INST_AGENT_VERSION) :"
    local v=""
    v=$(kubectl logs -n "$NAMESPACE" -l "${SERVICE_LABEL}" --tail=400 --prefix=false 2>/dev/null \
        | grep -oE "opentelemetry-javaagent - version: [0-9.]+" | head -1 || true)
    if [ -n "$v" ]; then say "    $v"; else say "    (pas encore visible dans les journaux)"; fi
    return 0
}

case "${1:-status}" in
    install)   shift; install_cmd "$@" ;;
    uninstall) shift; uninstall_cmd "$@" ;;
    status)    status_cmd ;;
    *) echo "Usage: $0 {install|uninstall|status} [service... | --all]" >&2; exit 2 ;;
esac
