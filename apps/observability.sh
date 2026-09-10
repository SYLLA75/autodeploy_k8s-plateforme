#!/bin/bash
# ==============================================================================
# apps/observability.sh — Pile d'observabilité AUTONOME
#
#   Objectif : rendre extractible l'ensemble des grandeurs nécessaires à la
#   construction du graphe hétérogène temporel (instances de service, files de
#   messages, machines hôtes, et les quatre relations).
#
#   Ce script est copié sur le nœud master par deploy.sh puis exécuté là-bas.
#   Il peut aussi être rejoué directement depuis le master :
#       ssh master
#       bash ~/autodeploy/apps/observability.sh install|uninstall|status|urls|verify
#
#   PORTABILITÉ — ce script ne suppose RIEN de particulier :
#     • aucune dépendance à otel-demo (qui fournissait jusqu'ici, par accident,
#       le collecteur, Prometheus et Jaeger) ;
#     • aucun nom de pod, aucune adresse IP, aucun nom de file en dur ;
#     • le courtier de messages est DÉCOUVERT par étiquette, pas deviné ;
#     • toutes les valeurs de réglage sont des variables d'environnement.
#
#   Variables d'environnement reconnues (toutes optionnelles) :
#     OBS_NAMESPACE            (défaut: observability)  namespace de la pile
#     OBS_HELM_BIN             (défaut: helm)           binaire Helm 3+
#     OBS_FORCE                (défaut: 0)              1 = réinstalle par-dessus
#     OBS_SCRAPE_INTERVAL      (défaut: 10s)            cadence de mesure
#     OBS_SCRAPE_TIMEOUT       (défaut: 8s)
#     OBS_RETENTION            (défaut: 15d)            conservation des métriques
#     OBS_PROM_STORAGE         (défaut: 20Gi)           disque des métriques
#     OBS_TRACE_STORAGE        (défaut: 20Gi)           disque des traces
#     OBS_PROM_CHART_VERSION   (défaut: vide = dernière)
#     OBS_COLLECTOR_CHART_VERSION (défaut: vide = dernière)
#     OBS_JAEGER_IMAGE         (défaut: jaegertracing/all-in-one:1.62.0)
#     OBS_MQ_NAMESPACE         (défaut: train-ticket)   où chercher le courtier
#     OBS_MQ_SELECTOR          (défaut: rabbit)         motif de recherche
#     OBS_MQ_METRICS_PORT      (défaut: 15692)
#     OBS_MQ_METRICS_PATH      (défaut: /metrics/per-object)
#     OBS_PROM_NODEPORT        (défaut: 30090)
#     OBS_JAEGER_NODEPORT      (défaut: 30686)
#     OBS_DEDICATED_NODE       (défaut: vide)  nœud réservé à la mesure
# ==============================================================================
set -euo pipefail

NAMESPACE="${OBS_NAMESPACE:-observability}"
HELM="${OBS_HELM_BIN:-helm}"
FORCE="${OBS_FORCE:-0}"

SCRAPE_INTERVAL="${OBS_SCRAPE_INTERVAL:-10s}"
SCRAPE_TIMEOUT="${OBS_SCRAPE_TIMEOUT:-8s}"
RETENTION="${OBS_RETENTION:-15d}"
# Plafond de TAILLE, en plus du plafond de durée. Sans lui, la base peut occuper
# tout le disque du nœud avant que les quinze jours ne soient atteints.
RETENTION_SIZE="${OBS_RETENTION_SIZE:-8GB}"
PROM_STORAGE="${OBS_PROM_STORAGE:-20Gi}"
TRACE_STORAGE="${OBS_TRACE_STORAGE:-20Gi}"

PROM_CHART_VERSION="${OBS_PROM_CHART_VERSION:-}"
COL_CHART_VERSION="${OBS_COLLECTOR_CHART_VERSION:-}"
JAEGER_IMAGE="${OBS_JAEGER_IMAGE:-jaegertracing/all-in-one:1.62.0}"
JAEGER_TTL="${OBS_JAEGER_TTL:-6h}"   # durée de vie des traces dans la visionneuse

MQ_NAMESPACE="${OBS_MQ_NAMESPACE:-train-ticket}"
MQ_SELECTOR="${OBS_MQ_SELECTOR:-rabbit}"
MQ_METRICS_PORT="${OBS_MQ_METRICS_PORT:-15692}"
MQ_METRICS_PATH="${OBS_MQ_METRICS_PATH:-/metrics/per-object}"

# Magasin d'objets externe. Vide = pas d'export, l'archive reste locale.
# Les identifiants ne sont JAMAIS écrits ici : ils viennent de .env.secrets,
# fichier ignoré par git, et transitent par un Secret Kubernetes.
S3_ENDPOINT="${OBS_S3_ENDPOINT:-}"
S3_BUCKET="${OBS_S3_BUCKET:-}"
S3_PREFIX="${OBS_S3_PREFIX:-otel-data}"
S3_REGION="${OBS_S3_REGION:-us-east-1}"
S3_ACCESS_KEY="${OBS_S3_ACCESS_KEY:-}"
S3_SECRET_KEY="${OBS_S3_SECRET_KEY:-}"
S3_SECRET_NAME="s3-credentials"

# Les compteurs exportés vers le magasin d'objets sont listés dans un fichier
# séparé, un nom par ligne : apps/metrics-keep.txt.
#
# Pourquoi un fichier plutôt qu'une variable : c'est une liste destinée à
# évoluer, et une expression régulière compressée est illisible et pénible à
# modifier. Le script la fabrique à partir de la liste, personne n'a à l'écrire.
METRICS_KEEP_FILE="${OBS_METRICS_KEEP_FILE:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/metrics-keep.txt}"

# Construit l'expression attendue par Prometheus à partir de la liste.
# Les lignes vides et les commentaires sont ignorés.
metrics_keep_regex() {
    [ -f "$METRICS_KEEP_FILE" ] || { echo ".*"; return; }
    sed -e 's/#.*//' -e 's/[[:space:]]//g' "$METRICS_KEEP_FILE" \
        | grep -v '^$' | paste -sd'|' -
}

# Nœud dédié à l'observabilité. Vide = pas d'isolement.
OBS_NODE="${OBS_DEDICATED_NODE:-}"
OBS_ROLE_LABEL="role=observability"
OBS_TAINT="dedicated=observability:NoSchedule"

PROM_NODEPORT="${OBS_PROM_NODEPORT:-30090}"
JAEGER_NODEPORT="${OBS_JAEGER_NODEPORT:-30686}"

REL_PROM="prom"
REL_AGENT="otel-agent"
REL_GATEWAY="otel-gateway"

say()  { echo "  [observability] $*"; }
warn() { echo "  [observability] ATTENTION: $*" >&2; }
fail() { echo "  [observability] ERREUR: $*" >&2; exit 1; }

node_ip() {
    if [ -n "${MASTER_IP:-}" ]; then echo "$MASTER_IP"; return; fi
    kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}'
}

# Le nom du Service de Prometheus dépend de la version du chart
# (« <release>-server » puis « <release>-prometheus-server »). On le découvre
# plutôt que de le supposer : c'est la même règle que pour le courtier.
prom_svc() {
    kubectl get svc -n "$NAMESPACE" --no-headers -o custom-columns=:metadata.name 2>/dev/null \
        | grep -E "^${REL_PROM}(-prometheus)?-server$" | head -1
}

# ------------------------------------------------------------------------------
# Contrôles préalables
# ------------------------------------------------------------------------------
preflight() {
    command -v "$HELM" >/dev/null 2>&1 || fail "Binaire Helm « $HELM » introuvable sur le master."
    local hv; hv=$($HELM version --short 2>/dev/null || echo "?")
    say "Helm utilisé : $hv"

    # Trois volumes persistants sont demandés (métriques, traces brutes, traces
    # indexées). Sans StorageClass par défaut ils resteraient en Pending, et le
    # symptôme serait illisible : des pods qui ne démarrent jamais.
    local sc=""
    sc=$(kubectl get storageclass -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.metadata.annotations.storageclass\.kubernetes\.io/is-default-class}{"\n"}{end}' 2>/dev/null \
         | awk '$2=="true" && !seen++ {print $1}' || true)
    [ -n "$sc" ] || fail "Aucune StorageClass par défaut. Relance ./deploy.sh (il installe local-path-provisioner)."
    say "StorageClass par défaut : $sc"
}

# ------------------------------------------------------------------------------
# Découverte du courtier de messages
# ------------------------------------------------------------------------------
# On ne code en dur ni le nom du Service, ni le nom du Deployment, ni le nom des
# files. On cherche par motif dans le namespace applicatif, et on n'échoue pas si
# le courtier est absent : la pile reste utile pour tout le reste.
discover_broker() {
    MQ_SVC=""; MQ_SVC_NS=""
    kubectl get namespace "$MQ_NAMESPACE" >/dev/null 2>&1 || return 0
    MQ_SVC=$(kubectl get svc -n "$MQ_NAMESPACE" --no-headers -o custom-columns=:metadata.name 2>/dev/null \
             | grep -i "$MQ_SELECTOR" | head -1 || true)
    [ -n "$MQ_SVC" ] && MQ_SVC_NS="$MQ_NAMESPACE"
    return 0
}

# ------------------------------------------------------------------------------
# Dépôts Helm
# ------------------------------------------------------------------------------
repos_add() {
    say "Ajout des dépôts Helm…"
    $HELM repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
    $HELM repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts >/dev/null 2>&1 || true
    $HELM repo update prometheus-community open-telemetry >/dev/null
}

# ==============================================================================
# BRIQUES 2 et 3 — mouchard des machines et mouchard de Kubernetes
# ==============================================================================
# Le chart « prometheus » embarque les deux comme sous-charts. Ils sont activés
# ici EXPLICITEMENT : le chart d'otel-demo les désactivait, ce qui laissait sans
# aucune source les cinq composantes du nœud de machine et le compteur de
# redémarrages du nœud d'instance.
#
# Trois réglages ne sont pas cosmétiques :
#   • scrape_interval : la valeur par défaut du chart est 1 minute. Avec une
#     fenêtre d'observation de l'ordre de la minute, cela ne donne qu'UN point
#     par fenêtre — ni minimum, ni maximum, ni incrément, ni pente ne sont alors
#     calculables. La valeur retenue ici borne le biais de troncature de
#     l'opérateur « taux » à environ 1 - (intervalle / largeur de fenêtre).
#   • persistentVolume : sans lui, toute la campagne est perdue au moindre
#     redémarrage du pod.
#   • retention : la valeur par défaut de 7 jours est courte pour une campagne
#     qui compare plusieurs exécutions.
# ------------------------------------------------------------------------------
install_prometheus() {
    say "Installation du magasin de métriques (+ mouchard machines + mouchard Kubernetes)…"
    if [ -n "${MQ_SVC:-}" ]; then
        say "  courtier découvert : service « $MQ_SVC » dans « $MQ_SVC_NS »"
    else
        warn "  aucun courtier trouvé dans « $MQ_NAMESPACE » (motif « $MQ_SELECTOR ») — les composantes du nœud de file resteront sans source."
    fi

    # ATTENTION — PIÈGE VÉRIFIÉ EN CONDITIONS RÉELLES.
    # Le placement doit être inséré À L'INTÉRIEUR du bloc « server », jamais dans
    # un second bloc « server » ajouté plus bas. En YAML, une clé répétée au même
    # niveau ÉCRASE la précédente : une version antérieure de cette fonction
    # émettait deux fois « server: », et tous les réglages du premier bloc étaient
    # perdus en silence — cadence de mesure comprise, revenue à une minute alors
    # que le fichier annonçait dix secondes.
    # Rien ne le signalait : Helm rapportait « upgraded », les pods tournaient, et
    # seules les données étaient fausses.
    # Envoi des compteurs vers la passerelle, qui les dépose dans le magasin
    # d'objets. Sans cela, ils ne vivent que dans la base locale, qui disparaît
    # avec la réservation — et la moitié du graphe avec eux.
    # Le filtre ne laisse passer que les compteurs nommés en section 11.
    local rw=""
    if [ -n "$S3_BUCKET" ] && [ -n "$S3_ENDPOINT" ]; then
        rw=$(cat <<RW

  remoteWrite:
    - url: http://${REL_GATEWAY}-opentelemetry-collector:19291/api/v1/write
      # Prometheus 3 envoie l'ANCIEN format par défaut, que ce receveur refuse
      # (« unsupported proto version, rejecting »). Il faut demander le nouveau
      # explicitement — sans cela, tous les envois échouent en silence côté
      # Prometheus, et rien n'arrive dans le magasin.
      protobuf_message: io.prometheus.write.v2.Request
      write_relabel_configs:
        - source_labels: [__name__]
          regex: '$(metrics_keep_regex)'
          action: keep
RW
)
    fi

    local place=""
    if [ -n "$OBS_NODE" ]; then
        place=$(cat <<'PLACE'

  nodeSelector: { role: observability }
  tolerations:
    - { key: dedicated, operator: Equal, value: observability, effect: NoSchedule }
PLACE
)
    fi

    local vfile; vfile=$(mktemp)
    cat > "$vfile" <<EOF
server:
  global:
    scrape_interval: ${SCRAPE_INTERVAL}
    scrape_timeout: ${SCRAPE_TIMEOUT}
    evaluation_interval: 30s
  retention: "${RETENTION}"
  # Plafond de TAILLE, en plus du plafond de durée. Sans lui, la base peut
  # remplir le disque du nœud bien avant que les quinze jours ne soient atteints,
  # et un disque plein évince tous les pods de ce nœud.
  retentionSize: "${RETENTION_SIZE}"
  persistentVolume:
    enabled: true
    size: ${PROM_STORAGE}
  resources:
    requests:
      cpu: 200m
      memory: 1Gi
    limits:
      memory: 3Gi
  service:
    type: NodePort${rw}${place}

alertmanager:
  enabled: false
prometheus-pushgateway:
  enabled: false

# Le mouchard des machines : seule source de node_pressure_*, seule grandeur qui
# distingue une machine réellement en contention d'une machine simplement chargée.
# Il reste sur TOUS les nœuds, master compris — il mesure chaque machine.
prometheus-node-exporter:
  enabled: true

# Le mouchard de Kubernetes : compteur de redémarrages, ET surtout kube_pod_info
# qui porte à la fois l'identifiant unique du pod et le nom de la machine. C'est
# le seul pont entre les compteurs de conteneur (étiquetés namespace + nom de pod)
# et l'identité retenue pour le nœud d'instance (nom de service + identifiant).
kube-state-metrics:
  enabled: true${place}
EOF

    local args=(--namespace "$NAMESPACE" --create-namespace -f "$vfile" --timeout 15m)
    [ -n "$PROM_CHART_VERSION" ] && args+=(--version "$PROM_CHART_VERSION")
    $HELM upgrade --install "$REL_PROM" prometheus-community/prometheus "${args[@]}"
    rm -f "$vfile"
}

# ==============================================================================
# Magasin de traces — Jaeger tout-en-un, avec disque
# ==============================================================================
# Écrit en manifeste brut plutôt qu'en chart : le schéma de valeurs du chart
# Jaeger change souvent, alors qu'un Deployment de quarante lignes est stable et
# entièrement sous notre contrôle. Le stockage « badger » écrit sur disque, à la
# différence du stockage mémoire d'otel-demo qui perdait tout au-delà de
# vingt-cinq mille traces.
# ------------------------------------------------------------------------------
install_jaeger() {
    say "Installation du magasin de traces (Jaeger + disque)…"

    # Le placement doit figurer DÈS L'INSTALLATION, pas être ajouté ensuite par
    # « isolate ». Jaeger est posé par manifeste brut, contrairement à
    # Prometheus et aux collecteurs qui sont des charts recevant leur placement
    # à l'installation. Sans lui, le planificateur pose le pod n'importe où, le
    # volume local-path se crée sur CETTE machine, et l'épinglage ultérieur
    # devient contradictoire : le pod est exigé sur le nœud de mesure alors que
    # ses données sont ailleurs. Constaté deux fois — volume sur workers3 puis
    # sur workers4, pod Pending définitif avec « didn't match PersistentVolume's
    # node affinity ». Étiqueter le nœud ne suffit pas : encore faut-il que le
    # pod demande cette étiquette avant que son volume ne soit créé.
    local place=""
    if [ -n "$OBS_NODE" ]; then
        # Le bloc COMMENCE par un retour à la ligne et n'en porte pas à la fin :
        # $( ) supprime les retours finaux, donc il s'insère APRÈS « spec: » et
        # non avant « containers: », sinon les deux se colleraient.
        place=$(cat <<'PLACE'

      nodeSelector: { role: observability }
      tolerations:
        - { key: dedicated, operator: Equal, value: observability, effect: NoSchedule }
PLACE
)
    fi

    kubectl apply -n "$NAMESPACE" -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: jaeger-badger
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: ${TRACE_STORAGE}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: jaeger
  labels: { app: jaeger }
spec:
  replicas: 1
  strategy: { type: Recreate }
  selector:
    matchLabels: { app: jaeger }
  template:
    metadata:
      labels: { app: jaeger }
    spec:${place}
      containers:
        - name: jaeger
          image: ${JAEGER_IMAGE}
          env:
            - { name: COLLECTOR_OTLP_ENABLED, value: "true" }
            - { name: SPAN_STORAGE_TYPE,      value: "badger" }
            - { name: BADGER_EPHEMERAL,       value: "false" }
            - { name: BADGER_DIRECTORY_VALUE, value: "/badger/data" }
            - { name: BADGER_DIRECTORY_KEY,   value: "/badger/key" }
            # Sans durée de vie, l'index de Jaeger grossit sans limite et le pod
            # finit tué pour dépassement mémoire, puis évincé du nœud. Constaté
            # après une dizaine d'heures de trafic. L'archive sur disque, elle,
            # n'est pas concernée : c'est elle le jeu de données, Jaeger n'est
            # qu'une visionneuse.
            - { name: BADGER_SPAN_STORE_TTL,  value: "${JAEGER_TTL}" }
          ports:
            - { name: otlp-grpc, containerPort: 4317 }
            - { name: otlp-http, containerPort: 4318 }
            - { name: ui,        containerPort: 16686 }
          volumeMounts:
            - { name: badger, mountPath: /badger }
          resources:
            requests: { cpu: 100m, memory: 512Mi }
            limits:   { memory: 2Gi }
      volumes:
        - name: badger
          persistentVolumeClaim: { claimName: jaeger-badger }
---
apiVersion: v1
kind: Service
metadata:
  name: jaeger
  labels: { app: jaeger }
spec:
  type: NodePort
  selector: { app: jaeger }
  ports:
    - { name: otlp-grpc, port: 4317, targetPort: 4317 }
    - { name: otlp-http, port: 4318, targetPort: 4318 }
    - { name: ui,        port: 16686, targetPort: 16686, nodePort: ${JAEGER_NODEPORT} }
EOF
}

# ==============================================================================
# BRIQUE 1 — la passerelle de collecte (écrivain unique)
# ==============================================================================
# Un seul exemplaire, pour une raison précise : c'est lui qui écrit l'archive de
# traces sur disque. Si l'écriture était faite par le collecteur qui tourne sur
# chaque nœud, on obtiendrait autant d'archives partielles que de nœuds, et il
# faudrait les recoller. Un écrivain unique donne un fichier unique.
#
# Cette archive est le vrai livrable reproductible : elle contient ce que le
# collecteur a vu, sans transformation. Un tiers peut donc reconstruire le graphe
# des mois plus tard, sans grappe et sans base de données.
# ------------------------------------------------------------------------------
install_gateway() {
    say "Installation de la passerelle de collecte (écrivain unique des traces)…"
    kubectl apply -n "$NAMESPACE" -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: otel-traces-archive
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: ${TRACE_STORAGE}
EOF

    # ---- magasin d'objets externe, si configuré -------------------------
    # C'est la seule chose qui survit à la fin de la réservation : les volumes
    # vivent sur les disques des machines réservées et disparaissent avec elles.
    # L'export se fait EN CONTINU, pas au moment de la destruction — sinon un
    # arrêt imprévu emporte la campagne.
    local s3_exp="" s3_env="" s3_pipe=""
    if [ -n "$S3_BUCKET" ] && [ -n "$S3_ENDPOINT" ]; then
        [ -n "$S3_ACCESS_KEY" ] && [ -n "$S3_SECRET_KEY" ] \
            || fail "OBS_S3_ACCESS_KEY et OBS_S3_SECRET_KEY sont requis (voir .env.secrets)."
        say "Magasin d'objets : ${S3_ENDPOINT}/${S3_BUCKET}/${S3_PREFIX}"
        kubectl create secret generic "$S3_SECRET_NAME" -n "$NAMESPACE" \
            --from-literal=access_key="$S3_ACCESS_KEY" \
            --from-literal=secret_key="$S3_SECRET_KEY" \
            --dry-run=client -o yaml | kubectl apply -f - >/dev/null
        s3_env=$(cat <<EOF
extraEnvs:
  - name: AWS_ACCESS_KEY_ID
    valueFrom:
      secretKeyRef: { name: ${S3_SECRET_NAME}, key: access_key }
  - name: AWS_SECRET_ACCESS_KEY
    valueFrom:
      secretKeyRef: { name: ${S3_SECRET_NAME}, key: secret_key }
EOF
)
        s3_exp=$(cat <<EOF
    awss3:
      s3uploader:
        region: ${S3_REGION}
        s3_bucket: ${S3_BUCKET}
        s3_prefix: ${S3_PREFIX}
        endpoint: ${S3_ENDPOINT}
        s3_force_path_style: true
        # Le format JSON répète toutes les étiquettes à chaque point de mesure —
        # mesuré à environ un kilo-octet par échantillon, soit deux gigaoctets
        # par heure pour les deux signaux réunis.
        # La compression ne touche QUE l'encodage : décompressé, le fichier est
        # identique caractère pour caractère. Aucune série, aucune cadence,
        # aucune étiquette n'est perdue — le graphe reconstruit est le même.
        compression: gzip
      marshaler: otlp_json
EOF
)
        s3_pipe=", awss3"
    fi

    # ---- placement, si un nœud est réservé ------------------------------
    # Second chemin vers le magasin : les COMPTEURS.
    # Ils n'y allaient pas — seules les traces étaient exportées. Or les
    # compteurs portent les cinq grandeurs de chaque machine, celles des
    # conteneurs et l'état des files : la moitié du graphe. Ils ne vivaient que
    # dans la base locale, qui disparaît avec la réservation.
    local s3_recv="" s3_metrics_pipe="      metrics: null
" s3_port=""
    if [ -n "$s3_exp" ]; then
        s3_recv=$(cat <<'RECV'
    # « prometheus_remote_write », pas « prometheusremotewrite » : l'ancien nom
    # est déprécié et le collecteur le signale à chaque démarrage.
    prometheus_remote_write:
      endpoint: 0.0.0.0:19291
RECV
)
        s3_metrics_pipe=$(cat <<'MPIPE'
      metrics:
        receivers: [prometheus_remote_write]
        processors: [memory_limiter, batch]
        exporters: [awss3]
MPIPE
)
        s3_metrics_pipe="${s3_metrics_pipe}
"
        s3_port=$(cat <<'PORT'
ports:
  promrw:
    enabled: true
    containerPort: 19291
    servicePort: 19291
    protocol: TCP
PORT
)
    fi

    local placement=""
    if [ -n "$OBS_NODE" ]; then
        placement=$(cat <<EOF
nodeSelector:
  role: observability
tolerations:
  - key: dedicated
    operator: Equal
    value: observability
    effect: NoSchedule
EOF
)
    fi

    local vfile; vfile=$(mktemp)
    cat > "$vfile" <<EOF
mode: deployment
replicaCount: 1
image:
  repository: otel/opentelemetry-collector-contrib
command:
  name: otelcol-contrib

resources:
  requests: { cpu: 200m, memory: 512Mi }
  limits:   { memory: 2Gi }

${placement}
${s3_env}
${s3_port}

extraVolumes:
  - name: archive
    persistentVolumeClaim:
      claimName: otel-traces-archive
extraVolumeMounts:
  - name: archive
    mountPath: /archive

config:
  receivers:
${s3_recv}
  processors:
    # Le regroupement par défaut envoie toutes les 200 millisecondes, ce qui
    # convient à une base de données mais pas à un magasin d'objets : mesuré,
    # cela produisait 1500 fichiers en deux minutes. Sur une campagne de
    # plusieurs heures, ce sont des centaines de milliers de petits objets,
    # longs à lister et pénibles à relire.
    # Un regroupement de 30 secondes ramène cela à quelques fichiers par minute.
    # Le seul coût est que la visionneuse affiche les traces avec ce retard.
    batch:
      timeout: 30s
      send_batch_size: 100000
      send_batch_max_size: 200000

  exporters:
    # (a) L'archive locale : lecture immédiate, sans réseau.
    # Depuis que l'export vers le magasin d'objets fonctionne, l'archive locale
    # n'est plus qu'un TAMPON de secours : elle sert à relire les dernières
    # minutes sans réseau, pas à conserver la campagne.
    #
    # La limite d'origine (200 fichiers de 128 Mo) autorisait 25 Go, alors que le
    # stockage local N'APPLIQUE PAS la taille annoncée du volume — c'est un simple
    # répertoire sur le disque du nœud. Avec Prometheus et la visionneuse, on
    # frôlait la capacité du disque, et un disque plein évince tous les pods du
    # nœud. Six fichiers suffisent, soit environ 750 Mo.
    file:
      path: /archive/spans.jsonl
      format: json
      rotation:
        max_megabytes: 128
        max_backups: 5
    # (b) Le magasin interrogeable, pour regarder à l'œil pendant les essais.
    otlp_grpc/jaeger:
      endpoint: jaeger:4317
      tls:
        insecure: true
${s3_exp}
  service:
    pipelines:
      traces:
        exporters: [file, otlp_grpc/jaeger${s3_pipe}]
${s3_metrics_pipe}      logs: null
EOF
    local args=(--namespace "$NAMESPACE" -f "$vfile" --timeout 10m)
    [ -n "$COL_CHART_VERSION" ] && args+=(--version "$COL_CHART_VERSION")
    $HELM upgrade --install "$REL_GATEWAY" open-telemetry/opentelemetry-collector "${args[@]}"
    rm -f "$vfile"
}

# ==============================================================================
# BRIQUE 1 (suite) — le collecteur présent sur chaque nœud
# ==============================================================================
# Son rôle unique et irremplaçable : POSER L'IDENTITÉ KUBERNETES sur chaque note
# émise par les programmes. Une note brute dit « j'ai traité un message en 18 ms ».
# Elle ne dit pas QUI l'a traité. Le processeur d'attributs Kubernetes ajoute le
# nom de service, l'identifiant unique du pod et le nom de la machine — c'est-à-dire
# exactement les clés d'identité du nœud d'instance et du nœud de machine, et la
# seule source de la relation « exécuter sur ».
#
# Il écoute sur le port de la MACHINE (hostPort), pour que les applications
# puissent lui parler par l'adresse de leur propre nœud, sans avoir à connaître
# le moindre nom de service. C'est ce qui rend l'instrumentation portable.
# ------------------------------------------------------------------------------
install_agent() {
    say "Installation du collecteur sur chaque nœud (pose l'identité Kubernetes)…"
    local vfile; vfile=$(mktemp)
    cat > "$vfile" <<EOF
mode: daemonset
image:
  repository: otel/opentelemetry-collector-contrib
command:
  name: otelcol-contrib

presets:
  kubernetesAttributes:
    enabled: true

ports:
  otlp:
    enabled: true
    containerPort: 4317
    hostPort: 4317
    protocol: TCP
  otlp-http:
    enabled: true
    containerPort: 4318
    hostPort: 4318
    protocol: TCP
  jaeger-compact:
    enabled: false
  jaeger-thrift:
    enabled: false
  jaeger-grpc:
    enabled: false
  zipkin:
    enabled: false

resources:
  requests: { cpu: 100m, memory: 256Mi }
  limits:   { memory: 1Gi }

config:
  exporters:
    # « otlp_grpc » et non « otlp » : le chart a renommé cet exportateur. Il
    # réécrit l'ancien nom automatiquement, en avertissant que la réécriture
    # disparaîtra. On écrit donc directement le nom actuel.
    otlp_grpc:
      endpoint: ${REL_GATEWAY}-opentelemetry-collector:4317
      tls:
        insecure: true
  service:
    pipelines:
      traces:
        exporters: [otlp_grpc]
      metrics: null
      logs: null
EOF
    local args=(--namespace "$NAMESPACE" -f "$vfile" --timeout 10m)
    [ -n "$COL_CHART_VERSION" ] && args+=(--version "$COL_CHART_VERSION")
    $HELM upgrade --install "$REL_AGENT" open-telemetry/opentelemetry-collector "${args[@]}"
    rm -f "$vfile"
}

# ==============================================================================
# BRIQUE 4 — ouvrir le port de mesure du courtier de messages
# ==============================================================================
# Constat fait sur la grappe : le greffon de métriques est DÉJÀ actif dans
# l'image, et il répond bien sur le port prévu. Le seul manque est que ce port
# n'est déclaré nulle part dans le Service : personne ne peut donc l'atteindre.
#
# On ne touche PAS au Deployment. Déclarer un port de conteneur est purement
# informatif — le processus écoute déjà — et modifier le gabarit provoquerait un
# redémarrage du pod, donc un nouvel identifiant, donc une rupture de trajectoire
# dans le graphe. On se contente du Service, qui suffit.
#
# Le point d'accès retenu est celui « par objet » : c'est le seul qui porte une
# étiquette de file. Le point d'accès par défaut agrège à l'échelle du courtier
# et ne permettrait pas de distinguer deux files.
# ------------------------------------------------------------------------------
expose_broker_metrics() {
    if [ -z "${MQ_SVC:-}" ]; then
        warn "Courtier introuvable : port de mesure non exposé (étape ignorée, non bloquante)."
        return 0
    fi
    say "Ouverture du port de mesure du courtier « $MQ_SVC »…"

    # Les annotations se posent par fusion simple, sans risque : ce sont des
    # clés, pas une liste.
    kubectl -n "$MQ_SVC_NS" annotate --overwrite svc "$MQ_SVC" \
        "prometheus.io/scrape=true" \
        "prometheus.io/port=${MQ_METRICS_PORT}" \
        "prometheus.io/path=${MQ_METRICS_PATH}" >/dev/null 2>&1 || true

    # --- Le port, en revanche, demande de la prudence ---------------------
    # ATTENTION, piège vérifié en conditions réelles : « patch --type=merge »
    # REMPLACE une liste au lieu de la compléter. Ajouter le port de mesure de
    # cette façon SUPPRIME le port applicatif, et le courtier devient
    # injoignable — les producteurs et les consommateurs échouent tous, sans que
    # le lien avec l'opération soit évident.
    #
    # On procède donc par ajout explicite en fin de liste (« --type=json »), qui
    # ne touche à aucune entrée existante.
    if kubectl -n "$MQ_SVC_NS" get svc "$MQ_SVC" \
         -o jsonpath="{.spec.ports[?(@.port==${MQ_METRICS_PORT})].port}" 2>/dev/null | grep -q .; then
        say "  port ${MQ_METRICS_PORT} déjà exposé — rien à faire."
        return 0
    fi

    # Kubernetes impose que TOUS les ports soient nommés dès qu'il y en a
    # plusieurs. Un Service qui n'en avait qu'un seul peut l'avoir laissé sans
    # nom : on le nomme d'abord, sinon l'ajout est refusé.
    local i=0
    while read -r nm; do
        if [ -z "$nm" ]; then
            kubectl -n "$MQ_SVC_NS" patch svc "$MQ_SVC" --type=json -p \
              "[{\"op\":\"add\",\"path\":\"/spec/ports/${i}/name\",\"value\":\"port-${i}\"}]" >/dev/null 2>&1 || true
            say "  port existant n°${i} nommé « port-${i} » (Kubernetes l'exige au-delà d'un port)"
        fi
        i=$((i+1))
    done < <(kubectl -n "$MQ_SVC_NS" get svc "$MQ_SVC" \
             -o jsonpath='{range .spec.ports[*]}{.name}{"\n"}{end}' 2>/dev/null)

    kubectl -n "$MQ_SVC_NS" patch svc "$MQ_SVC" --type=json -p \
      "[{\"op\":\"add\",\"path\":\"/spec/ports/-\",\"value\":{\"name\":\"metrics\",\"port\":${MQ_METRICS_PORT},\"targetPort\":${MQ_METRICS_PORT},\"protocol\":\"TCP\"}}]" \
      >/dev/null && say "  port ${MQ_METRICS_PORT} ajouté, point d'accès ${MQ_METRICS_PATH}" \
      || warn "  ajout du port refusé — à vérifier à la main."

    say "  ports du Service : $(kubectl -n "$MQ_SVC_NS" get svc "$MQ_SVC" \
         -o jsonpath='{range .spec.ports[*]}{.name}:{.port} {end}' 2>/dev/null)"
    return 0
}

# ------------------------------------------------------------------------------
install_app() {
    preflight
    discover_broker

    # Étiqueter le nœud AVANT d'installer quoi que ce soit.
    # Les composants sont déployés avec « nodeSelector: role=observability » dès
    # que OBS_DEDICATED_NODE est posé. Sans l'étiquette ils restent Pending, et
    # surtout leurs volumes local-path sont créés là où le planificateur les
    # place par défaut — c'est-à-dire ailleurs. Le volume étant attaché à sa
    # machine, l'épinglage ultérieur devient contradictoire et le pod ne démarre
    # jamais. Constaté sur jaeger : volume sur workers3, pod exigé sur workers1.
    #
    # L'étiquette seule n'interdit rien à personne : c'est le marquage
    # « dedicated » posé par « isolate » qui écarte les autres pods. La poser ici
    # est donc sans effet de bord.
    if [ -n "$OBS_NODE" ]; then
        if kubectl get node "$OBS_NODE" >/dev/null 2>&1; then
            kubectl label node "$OBS_NODE" $OBS_ROLE_LABEL --overwrite >/dev/null
            say "Nœud « $OBS_NODE » étiqueté pour la mesure (les volumes y seront créés)."
        else
            fail "OBS_DEDICATED_NODE=« $OBS_NODE » : ce nœud n'existe pas."
        fi
    fi

    if $HELM status "$REL_PROM" -n "$NAMESPACE" >/dev/null 2>&1 && [ "$FORCE" != "1" ]; then
        say "Pile déjà installée dans « $NAMESPACE » — rien à faire."
        say "Pour repartir de zéro : OBS_FORCE=1 bash $0 install"
        status_app
        return 0
    fi
    [ "$FORCE" = "1" ] && { say "Réinstallation forcée."; uninstall_app; }

    repos_add
    kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - >/dev/null

    install_prometheus
    install_jaeger
    install_gateway
    install_agent
    expose_broker_metrics

    say "Attente du démarrage…"
    kubectl -n "$NAMESPACE" rollout status deployment/jaeger --timeout=300s >/dev/null 2>&1 || true
    kubectl -n "$NAMESPACE" rollout status "deployment/${REL_GATEWAY}-opentelemetry-collector" --timeout=300s >/dev/null 2>&1 || true

    status_app
    urls_app
    echo
    say "Étape suivante : instrumenter les services applicatifs (voir OBSERVABILITE.md)."
    say "Point d'envoi des traces, à poser sur chaque service :"
    say "    OTEL_EXPORTER_OTLP_ENDPOINT=http://\$(NODE_IP):4318"
}

uninstall_app() {
    say "Désinstallation de la pile d'observabilité…"
    for r in "$REL_AGENT" "$REL_GATEWAY" "$REL_PROM"; do
        $HELM uninstall "$r" -n "$NAMESPACE" 2>/dev/null || true
    done
    kubectl delete namespace "$NAMESPACE" --ignore-not-found --timeout=300s || true

    # On retire aussi l'annotation posée sur le courtier, pour laisser
    # l'application applicative dans l'état où on l'a trouvée.
    discover_broker
    if [ -n "${MQ_SVC:-}" ]; then
        kubectl -n "$MQ_SVC_NS" annotate svc "$MQ_SVC" \
            prometheus.io/scrape- prometheus.io/port- prometheus.io/path- >/dev/null 2>&1 || true
    fi
    say "Désinstallation terminée."
}

status_app() {
    echo
    say "État des pods dans « $NAMESPACE » :"
    kubectl get pods -n "$NAMESPACE" -o wide 2>/dev/null || say "Namespace absent."
    echo
    say "Volumes persistants :"
    kubectl get pvc -n "$NAMESPACE" 2>/dev/null || true
    return 0
}

urls_app() {
    local ip; ip=$(node_ip)
    local pp jp
    pp=$(kubectl -n "$NAMESPACE" get svc "$(prom_svc)" -o jsonpath='{.spec.ports[0].nodePort}' 2>/dev/null || echo "?")
    jp=$(kubectl -n "$NAMESPACE" get svc jaeger -o jsonpath='{.spec.ports[?(@.name=="ui")].nodePort}' 2>/dev/null || echo "$JAEGER_NODEPORT")
    cat <<EOF

  ┌──────────────────────────────────────────────────────────────────────────┐
  │  Pile d'observabilité — accès                                            │
  └──────────────────────────────────────────────────────────────────────────┘
     Métriques (Prometheus) ......... http://$ip:$pp
     Traces (Jaeger) ................ http://$ip:$jp

     Archive brute des traces ....... volume « otel-traces-archive »,
                                      fichier /archive/spans.jsonl

   Sur SLICES-RI les VMs n'ont pas d'adresse publique : ouvre un tunnel SSH.
   ATTENTION, la cible du tunnel est l'ADRESSE DU NŒUD, pas « localhost » —
   kube-proxy ne s'attache pas à l'interface locale, et la forme habituelle
   « -L 9090:localhost:$pp » échoue silencieusement ici.

     ssh -N -L 16686:$ip:$jp -L 9090:$ip:$pp master

   puis, dans le navigateur :
     Traces ...... http://localhost:16686
     Métriques ... http://localhost:9090
EOF
}

# ==============================================================================
# isolate <nœud> — réserver un nœud à la chaîne de mesure
# ==============================================================================
# POURQUOI. Le nœud « machine » du graphe porte l'état de la machine ENTIÈRE,
# tous pods confondus. C'est voulu : la troisième cause candidate est justement
# un voisin qui sature la machine, et ce voisin n'est pas forcément modélisé.
#
# Mais cela crée un problème de méthode : la chaîne de mesure devient elle-même
# un voisin bruyant. Constaté sur la grappe — la visionneuse de traces a atteint
# deux gigaoctets, s'est fait tuer, et a fait passer son nœud en pression
# mémoire, ce qui a empêché son propre replacement. L'instrument perturbait la
# mesure, et au pire moment : une injection de saturation aurait tué le magasin
# de métriques juste quand on en avait besoin.
#
# On réserve donc un nœud aux composants lourds. Deux exceptions, par nature :
# le relevé de machine et le collecteur de spans restent sur TOUS les nœuds —
# le premier parce qu'il mesure chaque machine, le second parce que les
# applications lui parlent à l'adresse de leur propre nœud.
#
# ATTENTION, le stockage local cloue un volume à un nœud. Isoler après coup
# oblige donc à recréer les volumes qui étaient ailleurs, et l'historique qu'ils
# contenaient est perdu. À faire AVANT une campagne, jamais pendant.
# ------------------------------------------------------------------------------
# ------------------------------------------------------------------------------
# Réserver le nœud de mesure AVANT de déployer l'application
# ------------------------------------------------------------------------------
# Tous les ennuis d'isolement viennent du même point : on isole trop tard. Un
# nœud qui a déjà hébergé l'application porte ses volumes, et un volume
# local-path est attaché à sa machine — on ne peut plus déplacer le pod qui
# l'utilise. D'où des pods bloqués en Pending, des chefs MySQL coincés sur le
# nœud de mesure, et des volumes de mesure créés au mauvais endroit.
#
# Poser la marque avant le déploiement supprime ces quatre situations par
# construction : l'application ne s'installe jamais sur ce nœud, donc il n'y a
# rien à en retirer ensuite.
#
# « isolate » reste utile pour rattraper un nœud déjà occupé, mais devient un
# filet de sécurité au lieu d'un passage obligé.
reserve_app() {
    local node="${1:-$OBS_NODE}"
    [ -n "$node" ] || fail "Indique le nœud à réserver : $0 reserve <nœud>"
    kubectl get node "$node" >/dev/null 2>&1 || fail "Nœud « $node » introuvable."

    # Refuser si c'est déjà trop tard : le dire vaut mieux que de laisser croire
    # que la réservation est propre.
    local occupants
    occupants=$(kubectl get pods -A -o wide --no-headers 2>/dev/null \
                | awk -v x="$node" -v ns="$MQ_NAMESPACE" '$1==ns && $8==x {print $2}')
    if [ -n "$occupants" ]; then
        say "ATTENTION : « $node » héberge déjà des pods de « $MQ_NAMESPACE » :"
        echo "$occupants" | while read -r o; do say "    $o"; done
        say "La réservation aurait dû précéder le déploiement de l'application."
        say "Utilise « $0 isolate $node » : il évacue ce qui peut l'être et"
        say "laisse en place ce qui ne peut pas bouger, en le nommant."
        return 1
    fi

    kubectl label node "$node" $OBS_ROLE_LABEL --overwrite >/dev/null
    kubectl taint node "$node" $OBS_TAINT --overwrite >/dev/null
    say "Nœud « $node » réservé à la mesure, avant tout déploiement applicatif."
    say "  étiquette : $OBS_ROLE_LABEL"
    say "  marque    : $OBS_TAINT"
    say "Déploie maintenant l'application : elle évitera ce nœud d'elle-même."
    return 0
}

isolate_app() {
    local node="${1:-$OBS_NODE}"
    [ -n "$node" ] || fail "Indique le nœud à réserver : $0 isolate <nœud>"
    kubectl get node "$node" >/dev/null 2>&1 || fail "Nœud « $node » introuvable."

    local tol='[{"key":"dedicated","operator":"Equal","value":"observability","effect":"NoSchedule"}]'
    local sel='{"role":"observability"}'

    say "Réservation du nœud « $node »…"
    kubectl label node "$node" $OBS_ROLE_LABEL --overwrite >/dev/null
    kubectl taint node "$node" $OBS_TAINT --overwrite >/dev/null

    for d in jaeger "${REL_PROM}-prometheus-server" "${REL_PROM}-kube-state-metrics" \
             "${REL_GATEWAY}-opentelemetry-collector"; do
        kubectl get deploy "$d" -n "$NAMESPACE" >/dev/null 2>&1 || continue
        kubectl patch deploy "$d" -n "$NAMESPACE" \
            -p "{\"spec\":{\"template\":{\"spec\":{\"nodeSelector\":$sel,\"tolerations\":$tol}}}}" >/dev/null
        say "  épinglé : $d"
    done

    # Le collecteur doit rester sur le nœud réservé, sinon les composants qui y
    # tournent n'ont plus de destinataire local.
    kubectl patch daemonset "${REL_AGENT}-opentelemetry-collector-agent" -n "$NAMESPACE" \
        -p "{\"spec\":{\"template\":{\"spec\":{\"tolerations\":$tol}}}}" >/dev/null 2>&1 \
        && say "  tolérance ajoutée au collecteur (il reste sur tous les nœuds)"

    say "Évacuation des pods applicatifs de « $node »…"

    # Un pod dont le volume local-path se trouve SUR ce nœud ne peut aller nulle
    # part : le volume est attaché à la machine, et le nœud vient d'être
    # interdit. L'expulser le laisse Pending indéfiniment — constaté sur
    # nacosdb-mysql-0, bloqué jusqu'à suppression manuelle de son volume.
    # On les laisse donc en place, avec une tolérance, et on le dit.
    local ancres="" p pvc pv hote
    for p in $(kubectl get pods -n "$MQ_NAMESPACE" -o wide --no-headers 2>/dev/null \
               | awk -v x="$node" '$7==x {print $1}'); do
        for pvc in $(kubectl get pod "$p" -n "$MQ_NAMESPACE" -o \
                     jsonpath='{range .spec.volumes[*]}{.persistentVolumeClaim.claimName}{"\n"}{end}' \
                     2>/dev/null); do
            [ -n "$pvc" ] || continue
            pv=$(kubectl get pvc "$pvc" -n "$MQ_NAMESPACE" -o jsonpath='{.spec.volumeName}' 2>/dev/null)
            [ -n "$pv" ] || continue
            hote=$(kubectl get pv "$pv" -o \
                   jsonpath='{.spec.nodeAffinity.required.nodeSelectorTerms[0].matchExpressions[0].values[0]}' \
                   2>/dev/null)
            if [ "$hote" = "$node" ]; then
                case " $ancres " in *" $p "*) ;; *) ancres="$ancres $p" ;; esac
            fi
        done
    done

    local n=0
    for p in $(kubectl get pods -n "$MQ_NAMESPACE" -o wide --no-headers 2>/dev/null \
               | awk -v x="$node" '$7==x {print $1}'); do
        case " $ancres " in *" $p "*) continue ;; esac
        kubectl delete pod "$p" -n "$MQ_NAMESPACE" --wait=false >/dev/null 2>&1 && n=$((n+1))
    done
    say "  $n pod(s) relancé(s) ailleurs"

    if [ -n "$ancres" ]; then
        say "  $(echo $ancres | wc -w) pod(s) NON expulsé(s) : leur volume est sur « $node »."
        for p in $ancres; do say "    $p"; done
        # Une tolérance sur leur contrôleur, sinon ils seront expulsés au premier
        # redémarrage et resteront Pending.
        local owner kind
        for p in $ancres; do
            kind=$(kubectl get pod "$p" -n "$MQ_NAMESPACE" -o jsonpath='{.metadata.ownerReferences[0].kind}' 2>/dev/null)
            owner=$(kubectl get pod "$p" -n "$MQ_NAMESPACE" -o jsonpath='{.metadata.ownerReferences[0].name}' 2>/dev/null)
            if [ "$kind" = "StatefulSet" ] && [ -n "$owner" ]; then
                kubectl patch statefulset "$owner" -n "$MQ_NAMESPACE" \
                    -p "{\"spec\":{\"template\":{\"spec\":{\"tolerations\":$tol}}}}" >/dev/null 2>&1 \
                    && say "    tolérance posée sur $kind/$owner"
            fi
        done
        say "  Pour les déplacer vraiment, supprimer leur volume — les données y passent."
    fi

    warn "Le générateur de charge s'épingle séparément : bash apps/loadgen.sh isolate $node"
    return 0
}

# ==============================================================================
# verify — l'inventaire d'extraction
# ==============================================================================
# Répond à une seule question, pour chaque grandeur dont le graphe a besoin :
# « existe-t-elle réellement sur cette grappe, maintenant ? »
#
# C'est la mise en œuvre du protocole de vérification des attributs. Il ne s'agit
# pas de vérifier que la documentation promet une métrique, mais de constater
# qu'elle est effectivement produite. Le résultat se lit comme une fiche de relevé.
# ------------------------------------------------------------------------------
probe() {   # probe <libellé> <requête PromQL>
    local label="$1" q="$2" n
    n=$(kubectl run "obsprobe-$RANDOM" --rm -i --restart=Never --quiet \
          --image=curlimages/curl:8.11.1 -n "$NAMESPACE" -- \
          -s --max-time 20 --get "http://$(prom_svc)/api/v1/query" \
          --data-urlencode "query=$q" 2>/dev/null \
        | grep -o '"metric"' | wc -l || echo 0)
    if [ "${n:-0}" -gt 0 ]; then printf "  %-52s PRESENT  (%s series)\n" "$label" "$n"
    else                         printf "  %-52s ABSENT\n" "$label"; fi
}

verify_app() {
    kubectl get ns "$NAMESPACE" >/dev/null 2>&1 || fail "Pile absente. Lance d'abord : bash $0 install"
    echo
    say "INVENTAIRE D'EXTRACTION — ce que la grappe produit réellement"
    echo
    echo "  --- Noeud MACHINE (5 composantes) ---"
    probe "attente processeur (pression noyau)"      'node_pressure_cpu_waiting_seconds_total'
    probe "attente memoire (pression noyau)"         'node_pressure_memory_waiting_seconds_total'
    probe "attente entrees-sorties (pression noyau)" 'node_pressure_io_waiting_seconds_total'
    probe "memoire disponible"                       'node_memory_MemAvailable_bytes'
    probe "occupation processeur"                    'node_cpu_seconds_total'
    echo
    echo "  --- Noeud INSTANCE, etat des ressources ---"
    probe "etranglement processeur (numerateur)"     'container_cpu_cfs_throttled_periods_total'
    probe "etranglement processeur (denominateur)"   'container_cpu_cfs_periods_total'
    probe "usage processeur"                         'container_cpu_usage_seconds_total'
    probe "memoire occupee"                          'container_memory_working_set_bytes'
    probe "limite memoire declaree"                  'container_spec_memory_limit_bytes'
    probe "redemarrages"                             'kube_pod_container_status_restarts_total'
    echo
    echo "  --- Noeud INSTANCE, signal de transport ---"
    probe "paquets perdus en reception"              'container_network_receive_packets_dropped_total'
    probe "paquets perdus en emission"               'container_network_transmit_packets_dropped_total'
    probe "erreurs de reception"                     'container_network_receive_errors_total'
    probe "octets recus"                             'container_network_receive_bytes_total'
    echo
    echo "  --- Pont entre les traces et les metriques ---"
    probe "identifiant de pod + machine"             'kube_pod_info'
    echo
    echo "  --- Noeud FILE (famille file classique) ---"
    probe "niveau d'accumulation par file"           'rabbitmq_queue_messages_ready'
    probe "nombre de consommateurs par file"         'rabbitmq_queue_consumers'
    probe "messages delivres non acquittes"          'rabbitmq_queue_messages_unacked'
    echo
    echo "  --- Traces (la seule source des flux par file et des quatre relations) ---"
    # On lit le champ « total » rendu par Jaeger, et on retire Jaeger lui-même,
    # qui se trace toujours et ne dit rien sur les applications.
    local raw n
    raw=$(kubectl run "obstr-$RANDOM" --rm -i --restart=Never --quiet \
          --image=curlimages/curl:8.11.1 -n "$NAMESPACE" -- \
          -s --max-time 20 "http://jaeger:16686/api/services" 2>/dev/null || true)
    n=$(sed -n 's/.*"total":\([0-9]*\).*/\1/p' <<<"$raw")
    n=${n:-0}
    grep -q '"jaeger-all-in-one"' <<<"$raw" && n=$((n - 1))
    if [ "$n" -gt 0 ]; then
        printf "  %-52s PRESENT  (%s service(s))\n" "services applicatifs qui emettent des traces" "$n"
    else
        printf "  %-52s ABSENT   (aucun service equipe)\n" "services applicatifs qui emettent des traces"
    fi
    echo
    say "Rappel : les debits publie et consomme d'une file n'ont AUCUNE source"
    say "cote courtier. Ils se reconstruisent uniquement depuis les traces."
    echo
}

case "${1:-status}" in
    install)   install_app ;;
    uninstall) uninstall_app ;;
    status)    status_app ;;
    urls)      urls_app ;;
    verify)    verify_app ;;
    reserve)   shift; reserve_app "${1:-}" ;;
    isolate)   shift; isolate_app "${1:-}" ;;
    s3)        discover_broker; install_gateway ;;
    tune)      discover_broker; install_prometheus; install_gateway ;;
    *) echo "Usage: $0 {install|uninstall|status|urls|verify|reserve <nœud>|isolate <nœud>|s3|tune}" >&2; exit 2 ;;
esac
