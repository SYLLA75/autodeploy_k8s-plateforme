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
