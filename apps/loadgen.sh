#!/bin/bash
# ==============================================================================
# apps/loadgen.sh — Générateur de trafic pour train-ticket
#
#   Sans trafic, l'application ne fait rien : les services ne s'appellent pas,
#   les files restent vides, et le graphe reste un ensemble de ronds sans traits.
#   Ce script déploie un générateur qui simule des voyageurs.
#
#   DEUX CHOIX DE FOND, ET LEURS RAISONS
#
#   1. Le générateur tourne DANS la grappe, pas depuis le poste local.
#      Il ne s'arrête donc pas quand on ferme son portable — indispensable, car
#      la grandeur centrale du travail est une pente, qui demande des dizaines de
#      minutes de trafic régulier. Un tunnel depuis l'extérieur ajouterait en
#      outre sa propre irrégularité, exactement le bruit qu'on cherche à écarter.
#
#   2. Il vit dans SON PROPRE espace, et il n'est PAS instrumenté.
#      Le générateur est le monde extérieur, pas un service du système étudié.
#      Le laisser hors de l'espace applicatif l'exclut automatiquement de toutes
#      les mesures, qui filtrent déjà sur l'espace « train-ticket ». Et ne pas
#      l'instrumenter lui évite d'apparaître comme un nœud du graphe, où il ne
#      correspondrait à rien de réel.
#
#   Usage (depuis le master) :
#       bash ~/autodeploy/apps/loadgen.sh install|uninstall|status|urls|scale <n>
#
#   Variables d'environnement reconnues :
#     LG_NAMESPACE     (défaut: loadgen)        espace du générateur
#     LG_TARGET_NS     (défaut: train-ticket)   espace de l'application visée
#     LG_TARGET_SVC    (défaut: ts-gateway-service)
#     LG_TARGET_PORT   (défaut: 18888)
#     LG_USERS         (défaut: 10)             nombre de voyageurs au démarrage
#     LG_SPAWN_RATE    (défaut: 1)              voyageurs ajoutés par seconde
#     LG_PACING        (défaut: 5)              secondes entre deux parcours
#     LG_IMAGE         (défaut: locustio/locust:2.32.4)
#     LG_NODEPORT      (défaut: 30089)          port de la page de pilotage
# ==============================================================================
set -euo pipefail

# Journal d'exécution : la sortie est dupliquée dans un fichier, consultable
# depuis une autre connexion si celle-ci tombe. JOURNAL_OFF=1 désactive.
_ici="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$_ici/journal.sh" ] && JOURNAL_NOM="loadgen" . "$_ici/journal.sh"


NAMESPACE="${LG_NAMESPACE:-loadgen}"
TARGET_NS="${LG_TARGET_NS:-train-ticket}"
TARGET_SVC="${LG_TARGET_SVC:-ts-gateway-service}"
TARGET_PORT="${LG_TARGET_PORT:-18888}"
USERS="${LG_USERS:-10}"
SPAWN_RATE="${LG_SPAWN_RATE:-1}"
PACING="${LG_PACING:-5}"
IMAGE="${LG_IMAGE:-locustio/locust:2.32.4}"
NODEPORT="${LG_NODEPORT:-30089}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCUSTFILE="${LG_LOCUSTFILE:-$SCRIPT_DIR/loadgen/locustfile.py}"

say()  { echo "  [loadgen] $*"; }
warn() { echo "  [loadgen] ATTENTION: $*" >&2; }
fail() { echo "  [loadgen] ERREUR: $*" >&2; exit 1; }

node_ip() {
    if [ -n "${MASTER_IP:-}" ]; then echo "$MASTER_IP"; return; fi
    kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}'
}

target_url() { echo "http://${TARGET_SVC}.${TARGET_NS}.svc.cluster.local:${TARGET_PORT}"; }

# ------------------------------------------------------------------------------
preflight() {
    [ -f "$LOCUSTFILE" ] || fail "Fichier de parcours introuvable : $LOCUSTFILE"
    kubectl get namespace "$TARGET_NS" >/dev/null 2>&1 \
        || fail "L'application visée est absente : espace « $TARGET_NS »."
    kubectl get svc -n "$TARGET_NS" "$TARGET_SVC" >/dev/null 2>&1 \
        || fail "Point d'entrée introuvable : service « $TARGET_SVC » dans « $TARGET_NS »."
    say "Application visée : $(target_url)"
}

# ------------------------------------------------------------------------------
install_app() {
    preflight
    kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - >/dev/null

    # Les parcours vivent dans une ressource de configuration plutôt que dans
    # l'image : on peut donc les modifier sans reconstruire quoi que ce soit.
    say "Envoi des parcours…"
    kubectl create configmap locust-scenarios -n "$NAMESPACE" \
        --from-file=locustfile.py="$LOCUSTFILE" \
        --dry-run=client -o yaml | kubectl apply -f - >/dev/null

    say "Déploiement du générateur…"
    kubectl apply -n "$NAMESPACE" -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: locust
  labels: { app: locust }
spec:
  replicas: 1
  selector:
    matchLabels: { app: locust }
  template:
    metadata:
      labels: { app: locust }
    spec:
      containers:
        - name: locust
          image: ${IMAGE}
          args:
            - "-f"
            - "/scenarios/locustfile.py"
            - "--host"
            - "$(target_url)"
            - "--users"
            - "${USERS}"
            - "--spawn-rate"
            - "${SPAWN_RATE}"
            - "--autostart"
          env:
            - { name: TT_PACING_SECONDS, value: "${PACING}" }
          ports:
            - { name: web, containerPort: 8089 }
          volumeMounts:
            - { name: scenarios, mountPath: /scenarios }
          resources:
            requests: { cpu: 100m, memory: 256Mi }
            limits:   { memory: 1Gi }
      volumes:
        - name: scenarios
          configMap: { name: locust-scenarios }
---
apiVersion: v1
kind: Service
metadata:
  name: locust
  labels: { app: locust }
spec:
  type: NodePort
  selector: { app: locust }
  ports:
    - { name: web, port: 8089, targetPort: 8089, nodePort: ${NODEPORT} }
EOF

    kubectl -n "$NAMESPACE" rollout status deployment/locust --timeout=180s >/dev/null 2>&1 \
        || warn "Le générateur n'est pas encore prêt."
    status_app
    urls_app
}

# ------------------------------------------------------------------------------
# scale <n> — changer le nombre de voyageurs SANS redémarrer
# ------------------------------------------------------------------------------
# C'est le geste qui produit la première cause candidate : une hausse de charge
# parfaitement légitime, où la file se remplit alors que rien n'est en panne.
# L'instant du changement doit être noté : c'est lui qui sert d'étiquette.
# ------------------------------------------------------------------------------
scale_app() {
    local n="${1:-}"
    [ -n "$n" ] || fail "Indique un nombre de voyageurs : $0 scale 25"
    local pod
    pod=$(kubectl get pods -n "$NAMESPACE" -l app=locust --no-headers -o custom-columns=:metadata.name | head -1)
    [ -n "$pod" ] || fail "Générateur introuvable. Lance d'abord : $0 install"
    say "Passage à $n voyageurs — instant : $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    kubectl exec -n "$NAMESPACE" "$pod" -- \
        sh -c "wget -qO- --post-data='user_count=${n}&spawn_rate=${SPAWN_RATE}' http://localhost:8089/swarm" \
        >/dev/null 2>&1 && say "Fait." || warn "Le changement a échoué — vérifie la page web."
}

uninstall_app() {
    say "Suppression du générateur…"
    kubectl delete namespace "$NAMESPACE" --ignore-not-found --timeout=180s || true
    say "Terminé."
}

status_app() {
    echo
    say "État du générateur :"
    kubectl get pods -n "$NAMESPACE" -o wide 2>/dev/null || say "Espace absent."
    return 0
}

urls_app() {
    local ip; ip=$(node_ip)
    local p
    p=$(kubectl -n "$NAMESPACE" get svc locust -o jsonpath='{.spec.ports[0].nodePort}' 2>/dev/null || echo "$NODEPORT")
    cat <<EOF

  ┌──────────────────────────────────────────────────────────────────────────┐
  │  Générateur de trafic — pilotage                                         │
  └──────────────────────────────────────────────────────────────────────────┘
     Page de pilotage ............... http://$ip:$p

   Tunnel SSH (la cible est l'adresse du nœud, pas « localhost ») :
     ssh -N -L 8089:$ip:$p master
   puis http://localhost:8089

   Changer le nombre de voyageurs en ligne de commande :
     bash $0 scale 25

   Le rythme est réglé à un parcours toutes les ${PACING} s par voyageur.
   Avec ${USERS} voyageurs, cela fait environ $(awk "BEGIN{printf \"%.1f\", ${USERS}/${PACING}}") parcours par seconde.
EOF
}

# ------------------------------------------------------------------------------
# isolate <nœud> — placer le générateur sur le nœud réservé à la mesure
# ------------------------------------------------------------------------------
# Le générateur n'appartient pas au système étudié : il ne doit pas consommer
# les ressources des nœuds qui portent l'application, sous peine de fausser les
# mesures de contention.
# ------------------------------------------------------------------------------
isolate_app() {
    local node="${1:-}"
    [ -n "$node" ] || fail "Indique le nœud : $0 isolate <nœud>"
    kubectl patch deploy locust -n "$NAMESPACE" -p \
      '{"spec":{"template":{"spec":{"nodeSelector":{"role":"observability"},"tolerations":[{"key":"dedicated","operator":"Equal","value":"observability","effect":"NoSchedule"}]}}}}' \
      >/dev/null && say "générateur épinglé sur « $node »" || warn "épinglage refusé."
}

case "${1:-status}" in
    install)   install_app ;;
    uninstall) uninstall_app ;;
    status)    status_app ;;
    urls)      urls_app ;;
    scale)     shift; scale_app "${1:-}" ;;
    isolate)   shift; isolate_app "${1:-}" ;;
    *) echo "Usage: $0 {install|uninstall|status|urls|scale <n>|isolate <nœud>}" >&2; exit 2 ;;
esac
