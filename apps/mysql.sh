# ==============================================================================
#  apps/mysql.sh — parler à la base de train-ticket
# ==============================================================================
#
#  À SOURCER, pas à exécuter. Fournit :
#
#      pod_mysql          le pod chef de la base (les écritures y vont)
#      sql <requête>      exécute la requête sur la base $DB, sortie brute
#
#  Le mot de passe est celui que le pod porte dans son environnement ; s'il n'y
#  en a pas, « -p » n'est pas passé (il demanderait le mot de passe au terminal
#  et son invite salirait la sortie).
#
#  Variables reconnues :
#      CONSO_NAMESPACE     (défaut: train-ticket)
#      CONSO_MYSQL_LABEL   (défaut: app=tsdb-mysql)
#      CONSO_DB            (défaut: ts)
# ==============================================================================
NS="${CONSO_NAMESPACE:-train-ticket}"
MYSQL_LABEL="${CONSO_MYSQL_LABEL:-app=tsdb-mysql}"
DB="${CONSO_DB:-ts}"

pod_mysql() {
    local p
    p=$(kubectl get pods -n "$NS" -l "$MYSQL_LABEL,role=leader" --no-headers \
        -o custom-columns=:metadata.name 2>/dev/null | head -1)
    [ -n "$p" ] || p=$(kubectl get pods -n "$NS" -l "$MYSQL_LABEL" --no-headers \
        -o custom-columns=:metadata.name 2>/dev/null | head -1)
    echo "$p"
}

sql() {
    local pod; pod=$(pod_mysql)
    [ -n "$pod" ] || { echo "Aucun pod « $MYSQL_LABEL » dans $NS : la base est introuvable." >&2; return 1; }
    kubectl exec -n "$NS" "$pod" -c mysql -- sh -c \
        'mysql -uroot ${MYSQL_ROOT_PASSWORD:+-p"$MYSQL_ROOT_PASSWORD"} --database="$1" -N -B -e "$2" 2>&1 \
         | grep -v "Using a password" | sed "s/^Enter password: //"' \
        sh "$DB" "$1"
}

# ------------------------------------------------------------------------------
# Retarder ce que les pods d'un déploiement envoient à la base
# ------------------------------------------------------------------------------
# Les pods parlent à la base par une adresse de SERVICE (tsdb-mysql-leader),
# traduite en adresse de pod après la sortie du pod. Un filtre posé sur les
# seules adresses des pods de la base ne voit donc jamais passer ce trafic :
# les adresses des services qui les précèdent sont ajoutées explicitement.
# ------------------------------------------------------------------------------
ips_devant_mysql() {   # les adresses de service devant les pods de la base
    kubectl get svc -n "$NS" --no-headers -o custom-columns=IP:.spec.clusterIP,SEL:.spec.selector 2>/dev/null \
        | awk -v k="${MYSQL_LABEL%%=*}:${MYSQL_LABEL#*=}" 'index($0, k) && $1 != "None" && $1 != "<none>" {print $1}'
}

# yaml_retard <nom> <deploiement> <ms> [durée] [étiquette=valeur]
yaml_retard() {
    local nom="$1" deploy="$2" ms="$3" duree="${4:-}" etiquette="${5:-}"
    local cle="${MYSQL_LABEL%%=*}" val="${MYSQL_LABEL#*=}" ip
    cat <<EOF2
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata:
  name: $nom
  namespace: $NS
${etiquette:+  labels: { ${etiquette%%=*}: ${etiquette#*=} }}
spec:
  action: delay
  mode: all
  selector:
    namespaces: [ "$NS" ]
    labelSelectors: { app: "$deploy" }
  direction: to
  target:
    mode: all
    selector:
      namespaces: [ "$NS" ]
      labelSelectors: { $cle: "$val" }
  externalTargets:
EOF2
    for ip in $(ips_devant_mysql); do echo "    - \"$ip\""; done
    cat <<EOF2
  delay:
    latency: "${ms}ms"
    jitter: "0ms"
    correlation: "0"
${duree:+  duration: "${duree}m"}
EOF2
}
