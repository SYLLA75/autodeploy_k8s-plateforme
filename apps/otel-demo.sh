#!/bin/bash
# ==============================================================================
# apps/otel-demo.sh — OpenTelemetry Demo (boutique « Astronomy Shop »)
# ==============================================================================
# Ce script est copié sur le nœud master par deploy.sh puis exécuté là-bas.
# Il peut aussi être rejoué directement depuis le master :
#     ssh master
#     bash ~/autodeploy/apps/otel-demo.sh install|uninstall|status|urls
#
# Variables d'environnement reconnues :
#   OTEL_NAMESPACE      (défaut: otel-demo)      namespace Kubernetes
#   OTEL_RELEASE        (défaut: my-otel-demo)   nom de la release Helm
#   OTEL_CHART_VERSION  (défaut: vide = dernière version du chart)
#   OTEL_NODEPORT       (défaut: 30080)          port exposé sur les nœuds
#   OTEL_HELM_BIN       (défaut: helm)           binaire Helm (v4 requis)
#   OTEL_FORCE          (défaut: 0)              1 = réinstalle par-dessus
# ==============================================================================
set -euo pipefail

NAMESPACE="${OTEL_NAMESPACE:-otel-demo}"
RELEASE="${OTEL_RELEASE:-my-otel-demo}"
CHART_VERSION="${OTEL_CHART_VERSION:-}"
NODEPORT="${OTEL_NODEPORT:-30080}"
HELM="${OTEL_HELM_BIN:-helm}"
FORCE="${OTEL_FORCE:-0}"
REPO_NAME="open-telemetry"
REPO_URL="https://open-telemetry.github.io/opentelemetry-helm-charts"
CHART="$REPO_NAME/opentelemetry-demo"

say()  { echo "  [otel-demo] $*"; }
fail() { echo "  [otel-demo] ERREUR: $*" >&2; exit 1; }

node_ip() {
    # IP publique du master : c'est celle qui sert d'entrée NodePort.
    if [ -n "${MASTER_IP:-}" ]; then echo "$MASTER_IP"; return; fi
    kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}'
}

install_app() {
    command -v "$HELM" >/dev/null 2>&1 || fail "Binaire Helm « $HELM » introuvable sur le master."
    say "Helm utilisé : $($HELM version --short 2>/dev/null || echo "$HELM")"

    local rel_state=""
    rel_state=$($HELM status "$RELEASE" -n "$NAMESPACE" -o json 2>/dev/null \
                | grep -o '"status":"[a-z-]*"' | head -1 | cut -d'"' -f4 || true)
    case "$rel_state" in
        failed|pending-install|pending-upgrade|pending-rollback|unknown)
            say "Release « $RELEASE » dans l'état « $rel_state » → réinstallation propre."
            FORCE=1 ;;
    esac

    if [ -n "$rel_state" ]; then
        if [ "$FORCE" = "1" ]; then
            say "Release « $RELEASE » déjà présente → désinstallation avant réinstallation propre."
            uninstall_app
        else
            say "Release « $RELEASE » déjà installée dans le namespace « $NAMESPACE » — rien à faire."
            say "Pour repartir de zéro : ./deploy.sh --apps-only --app otel-demo --force-reinstall"
            status_app
            return 0
        fi
    fi

    say "Ajout du dépôt Helm OpenTelemetry…"
    $HELM repo add "$REPO_NAME" "$REPO_URL" >/dev/null 2>&1 || true
    $HELM repo update "$REPO_NAME" >/dev/null

    local version_args=()
    [ -n "$CHART_VERSION" ] && version_args=(--version "$CHART_VERSION")

    say "Installation du chart (namespace: $NAMESPACE, NodePort: $NODEPORT)…"
    # frontend-proxy est le point d'entrée unique (Envoy) : il route vers la
    # boutique, Grafana, Jaeger, flagd-ui, etc. On le bascule en NodePort pour
    # pouvoir l'atteindre depuis l'extérieur du cluster.
    $HELM upgrade --install "$RELEASE" "$CHART" \
        --namespace "$NAMESPACE" --create-namespace \
        "${version_args[@]}" \
        --set components.frontend-proxy.service.type=NodePort \
        --set components.frontend-proxy.service.nodePort="$NODEPORT" \
        --timeout 20m

    fix_flagd_ui

    say "Attente du démarrage du point d'entrée web (frontend-proxy)…"
    kubectl -n "$NAMESPACE" rollout status deployment/frontend-proxy --timeout=900s || \
        say "AVERTISSEMENT : frontend-proxy n'est pas encore prêt, vérifie « kubectl get pods -n $NAMESPACE »."

    # À ce stade flagd est disponible depuis un moment : on relève les services
    # qui avaient renoncé pendant son redéploiement.
    recover_crashloops

    status_app
    urls_app
}

# ------------------------------------------------------------------------------
# Contournement d'un défaut de l'image amont flagd-ui
# ------------------------------------------------------------------------------
# Le Dockerfile de flagd-ui contient :
#     CMD ["sh", "-c", "ulimit -n 65536 && exec /app/bin/server"]
# Or containerd accorde aux conteneurs une limite HAUTE de 65535 descripteurs :
# la demande de 65536 échoue avec « Operation not permitted », le « && »
# court-circuite, et le conteneur sort en erreur — boucle de plantage.
# La limite SOUPLE valant déjà 65535, l'appel à ulimit est de toute façon
# inutile : on lance donc le serveur directement.
#
# On procède par patch stratégique plutôt que par « --set » Helm, car Helm
# REMPLACE les listes au lieu de les fusionner : surcharger
# components.flagd.sidecarContainers[0] effacerait env, ports et volumes.
# Le patch stratégique, lui, fusionne les conteneurs par nom.
fix_flagd_ui() {
    kubectl get deployment flagd -n "$NAMESPACE" >/dev/null 2>&1 || return 0
    local cmd
    cmd=$(kubectl get deployment flagd -n "$NAMESPACE" \
          -o jsonpath='{.spec.template.spec.containers[?(@.name=="flagd-ui")].command}' 2>/dev/null || true)
    case "$cmd" in
        *"/app/bin/server"*) return 0 ;;   # déjà corrigé
    esac
    say "Correction de flagd-ui (ulimit 65536 refusé par containerd)…"
    kubectl -n "$NAMESPACE" patch deployment flagd \
        -p '{"spec":{"template":{"spec":{"containers":[{"name":"flagd-ui","command":["/app/bin/server"]}]}}}}' >/dev/null \
        && kubectl -n "$NAMESPACE" rollout status deployment/flagd --timeout=180s >/dev/null 2>&1 \
        && say "flagd-ui corrigé — l'interface /feature est opérationnelle." \
        || say "AVERTISSEMENT : correction de flagd-ui impossible, /feature restera indisponible."
    return 0
}

# ------------------------------------------------------------------------------
# Reprise des services qui ont abandonné pendant une indisponibilité de flagd
# ------------------------------------------------------------------------------
# Plusieurs services de la démo (shipping en Rust, notamment) se connectent au
# gRPC de flagd au démarrage, ne réessaient que 5 fois, puis PANIQUENT au lieu
# d'attendre. Toute interruption de flagd — dont le redéploiement provoqué par
# fix_flagd_ui — les laisse en CrashLoopBackOff avec un délai exponentiel qui
# peut durer plusieurs minutes.
# On les relance donc une fois, après que flagd est redevenu disponible.
recover_crashloops() {
    local stuck
    stuck=$(kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null \
            | awk '$3=="CrashLoopBackOff" || $3=="Error" {print $1}' || true)
    [ -n "$stuck" ] || return 0
    say "Reprise des pods bloqués : $(tr '\n' ' ' <<<"$stuck")"
    xargs -r kubectl delete pod -n "$NAMESPACE" --wait=false <<<"$stuck" >/dev/null 2>&1 || true
    return 0
}

uninstall_app() {
    say "Désinstallation de la release « $RELEASE »…"
    $HELM uninstall "$RELEASE" -n "$NAMESPACE" 2>/dev/null || say "Release absente."
    say "Suppression du namespace « $NAMESPACE »…"
    kubectl delete namespace "$NAMESPACE" --ignore-not-found --timeout=300s || true
    say "Désinstallation terminée."
}

status_app() {
    echo
    say "État des pods dans « $NAMESPACE » :"
    kubectl get pods -n "$NAMESPACE" -o wide 2>/dev/null || say "Namespace absent."
    echo
    say "Services exposés :"
    kubectl get svc -n "$NAMESPACE" 2>/dev/null | grep -E "NAME|NodePort" || true
    # « || true » : sous set -e + pipefail, un hoquet de l'API kubectl ferait
    # échouer cette simple lecture d'état et tuerait tout le déploiement.
    local not_ready=0
    not_ready=$(kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null \
                | awk '$3!="Running" && $3!="Completed" {c++} END {print c+0}' || true)
    [ "${not_ready:-0}" -gt 0 ] && say "$not_ready pod(s) pas encore prêts — le démarrage complet prend 5 à 10 minutes."
    return 0
}

urls_app() {
    local ip; ip=$(node_ip)
    local port
    port=$(kubectl -n "$NAMESPACE" get svc frontend-proxy \
           -o jsonpath='{.spec.ports[0].nodePort}' 2>/dev/null || echo "$NODEPORT")
    cat <<EOF

  ┌──────────────────────────────────────────────────────────────────────────┐
  │  OpenTelemetry Demo — accès aux interfaces web                           │
  └──────────────────────────────────────────────────────────────────────────┘
   Point d'entrée unique (Envoy « frontend-proxy ») : http://$ip:$port

     Boutique Astronomy Shop ........ http://$ip:$port/
     Grafana (tableaux de bord) ..... http://$ip:$port/grafana/
     Jaeger (traces distribuées) .... http://$ip:$port/jaeger/ui
     Feature flags (flagd-ui) ....... http://$ip:$port/feature
     Documentation télémétrie ....... http://$ip:$port/telemetry/
     Générateur de charge ........... http://$ip:$port/loadgen/
     Endpoint OTLP/HTTP ............. http://$ip:$port/otlp-http/v1/traces

   Si le port $port n'est pas joignable depuis ton poste, ouvre un tunnel SSH :
     ssh -N -L 8080:localhost:$port master
   puis navigue sur http://localhost:8080/
EOF
}

case "${1:-status}" in
    install)   install_app ;;
    uninstall) uninstall_app ;;
    status)    status_app ;;
    urls)      urls_app ;;
    *) echo "Usage: $0 {install|uninstall|status|urls}" >&2; exit 2 ;;
esac
