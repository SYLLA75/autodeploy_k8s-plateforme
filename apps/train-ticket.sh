#!/bin/bash
# ==============================================================================
# apps/train-ticket.sh — Train Ticket (FudanSELab), benchmark 41 microservices
# ==============================================================================
# Ce script est copié sur le nœud master par deploy.sh puis exécuté là-bas.
# Il peut aussi être rejoué directement depuis le master :
#     ssh master
#     bash ~/autodeploy/apps/train-ticket.sh install|uninstall|status|urls
#
# Variables d'environnement reconnues :
#   TT_NAMESPACE        (défaut: train-ticket)   namespace Kubernetes
#   TT_REPO_URL         (défaut: dépôt GitHub officiel FudanSELab)
#   TT_REF              (défaut: master)         branche ou tag à cloner
#   TT_DEPLOY_ARGS      (défaut: vide = quick start)
#                       valeurs possibles : "--independent-db", "--with-tracing"
#                       (SkyWalking), "--with-monitoring" (Prometheus), "--all"
#   TT_UI_NODEPORT      (défaut: 32677)  NodePort de ts-ui-dashboard (fixé amont)
#   TT_GATEWAY_NODEPORT (défaut: 30467)  NodePort de ts-gateway-service
#   TT_HELM_BIN         (défaut: helm3)  Helm 3 OBLIGATOIRE (charts apiVersion v1)
#   TT_FORCE            (défaut: 0)      1 = supprime le namespace et réinstalle
# ==============================================================================
set -euo pipefail

# Journal d'exécution : la sortie est dupliquée dans un fichier, consultable
# depuis une autre connexion si celle-ci tombe. JOURNAL_OFF=1 désactive.
_ici="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$_ici/journal.sh" ] && JOURNAL_NOM="train-ticket" . "$_ici/journal.sh"


NAMESPACE="${TT_NAMESPACE:-train-ticket}"
REPO_URL="${TT_REPO_URL:-https://github.com/FudanSELab/train-ticket.git}"
REF="${TT_REF:-master}"
DEPLOY_ARGS="${TT_DEPLOY_ARGS:-}"
UI_NODEPORT="${TT_UI_NODEPORT:-32677}"
GW_NODEPORT="${TT_GATEWAY_NODEPORT:-30467}"
HELM="${TT_HELM_BIN:-helm3}"
FORCE="${TT_FORCE:-0}"
SRC_DIR="${TT_SRC_DIR:-$HOME/train-ticket}"

say()  { echo "  [train-ticket] $*"; }
fail() { echo "  [train-ticket] ERREUR: $*" >&2; exit 1; }

node_ip() {
    if [ -n "${MASTER_IP:-}" ]; then echo "$MASTER_IP"; return; fi
    kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}'
}

# ------------------------------------------------------------------------------
# Contrôles préalables : Helm 3 et StorageClass par défaut
# ------------------------------------------------------------------------------
preflight() {
    command -v "$HELM" >/dev/null 2>&1 || fail "Binaire Helm 3 « $HELM » introuvable.
    Les charts embarqués de train-ticket (nacos, rabbitmq) sont au format
    « apiVersion: v1 » que Helm 4 refuse : Helm 3 est indispensable."
    local hv; hv=$($HELM version --short 2>/dev/null || echo "?")
    case "$hv" in
        v3.*) say "Helm 3 détecté : $hv" ;;
        *)    say "AVERTISSEMENT : « $HELM » rapporte $hv, or Helm 3 est requis." ;;
    esac

    # « head » en fin de tube provoque un SIGPIPE que pipefail transforme en
    # échec : on filtre donc entièrement dans awk, sans head.
    local sc=""
    sc=$(kubectl get storageclass -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.metadata.annotations.storageclass\.kubernetes\.io/is-default-class}{"\n"}{end}' 2>/dev/null \
         | awk '$2=="true" && !seen++ {print $1}' || true)
    [ -n "$sc" ] || fail "Aucune StorageClass par défaut : les PVC de MySQL et Nacos resteraient en Pending.
    Relance ./deploy.sh (il installe local-path-provisioner), ou installe-la à la main :
      kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/v0.0.37/deploy/local-path-storage.yaml
      kubectl patch storageclass local-path -p '{\"metadata\":{\"annotations\":{\"storageclass.kubernetes.io/is-default-class\":\"true\"}}}'"
    say "StorageClass par défaut : $sc"
}

fetch_sources() {
    if [ -d "$SRC_DIR/.git" ]; then
        say "Sources déjà présentes dans $SRC_DIR."
    else
        say "Clonage de $REPO_URL (réf. $REF)…"
        git clone --depth=1 --branch "$REF" "$REPO_URL" "$SRC_DIR" \
            || fail "Échec du clonage du dépôt train-ticket."
    fi
}

# Les scripts amont appellent « helm » sans préciser la version. On place donc
# un lien helm → helm3 en tête de PATH le temps du déploiement.
helm3_shim() {
    local shim="$HOME/.tt-helm-shim"
    mkdir -p "$shim"
    ln -sf "$(command -v "$HELM")" "$shim/helm"
    echo "$shim"
}

# ------------------------------------------------------------------------------
# Correctif : MySQL RadonDB inaccessible en IPv6
# ------------------------------------------------------------------------------
# Le sidecar « xenon » de RadonDB — celui qui mène l'élection du leader — se
# connecte à « localhost:3306 ». Or /etc/hosts d'un pod contient à la fois
# « 127.0.0.1 localhost » et « ::1 localhost », et la résolution glibc privilégie
# l'IPv6 (RFC 6724). MySQL voit donc arriver root@::1, un compte que le chart ne
# crée pas : il ne déclare que root@localhost et root@127.0.0.1.
#
# Conséquence en cascade : authentification refusée → aucune élection → aucun pod
# ne porte le label role=leader → le service *-mysql-leader n'a aucun endpoint →
# l'init de Nacos échoue en boucle, et les 41 services ne trouvent pas leur base.
#
# On ne peut pas corriger avant, car les pods n'existent pas encore ; ni après,
# car le script amont se bloque sur « kubectl rollout status ». D'où cette boucle
# lancée EN PARALLÈLE du déploiement : elle applique le correctif à chaque pod
# MySQL dès qu'il accepte les connexions, puis s'arrête avec le déploiement.
MYSQL_IPV6_SQL="CREATE USER IF NOT EXISTS 'root'@'::1' IDENTIFIED WITH mysql_native_password BY ''; GRANT ALL PRIVILEGES ON *.* TO 'root'@'::1' WITH GRANT OPTION; FLUSH PRIVILEGES;"
MYSQL_IPV6_CHECK="SELECT 1 FROM mysql.user WHERE user='root' AND host='::1'"

# Le compte ne se pose PAS une fois pour toutes. Constaté sur un déploiement
# réel : appliqué aux trois pods pendant leur démarrage, il avait disparu de deux
# d'entre eux une heure plus tard. L'entrée en service de RadonDB réécrit sa
# table de comptes après le premier démarrage, et efface ce qu'on y a ajouté trop
# tôt. Une pose unique est donc une pose non fiable.
#
# La boucle vérifie donc l'existence du compte à chaque passage au lieu de faire
# confiance à un premier succès, et ne s'arrête que lorsque le service leader a
# réellement une adresse — c'est-à-dire quand l'élection a abouti, seule preuve
# que le correctif a tenu.
mysql_ipv6_fixer() {
    local p deadline annonces="" annonce_elus=""
    # La fenêtre couvre le déploiement ET l'attente qui le suit : c'est pendant
    # cette seconde phase que RadonDB réécrit sa table de comptes.
    deadline=$(( $(date +%s) + ${TT_DEPLOY_TIMEOUT:-2400} + ${TT_READY_TIMEOUT:-1800} ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        for p in $(kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null \
                   | cut -d' ' -f1 | grep -E -- '-mysql-[0-9]+$' || true); do
            # Déjà présent ? On ne réécrit rien.
            if kubectl exec -n "$NAMESPACE" "$p" -c mysql -- \
                 mysql -uroot -N -S /run/mysqld/mysqld.sock \
                 -e "$MYSQL_IPV6_CHECK" 2>/dev/null | grep -q 1; then
                continue
            fi
            if kubectl exec -n "$NAMESPACE" "$p" -c mysql -- \
                 mysql -uroot -S /run/mysqld/mysqld.sock \
                 -e "$MYSQL_IPV6_SQL" >/dev/null 2>&1; then
                case " $annonces " in
                    *" $p "*) say "correctif IPv6 REPOSÉ sur $p (il avait été effacé)" ;;
                    *) annonces="$annonces $p"
                       say "correctif IPv6 appliqué à $p (compte root@::1 créé)" ;;
                esac
            fi
        done
        # AUCUNE SORTIE ANTICIPÉE. Une version précédente s'arrêtait dès que
        # tous les services leader connus étaient adressés — piège vérifié : à
        # l'étape 1/3 seul nacosdb existe, il est élu, la condition « tous » est
        # satisfaite avec un seul, et le correcteur meurt. tsdb est créé à
        # l'étape 2/3, sans personne pour le corriger, et les 41 services
        # échouent. On ne peut pas savoir combien de bases seront déployées
        # avant qu'elles ne le soient.
        #
        # Le correcteur tourne donc jusqu'au bout de sa fenêtre, et c'est
        # install_app qui l'arrête quand l'application est prête. Un contrôle
        # toutes les dix secondes ne coûte rien.
        local total prets
        total=$(kubectl get svc -n "$NAMESPACE" --no-headers 2>/dev/null \
                | grep -c -- '-mysql-leader' || true)
        prets=$(kubectl get endpoints -n "$NAMESPACE" --no-headers 2>/dev/null \
                | grep -- '-mysql-leader' | grep -vc '<none>' || true)
        if [ "${total:-0}" -gt 0 ] && [ "${prets:-0}" -eq "${total:-0}" ]; then
            if [ "$annonce_elus" != "$total" ]; then
                say "élection MySQL aboutie sur $total base(s) — surveillance maintenue."
                annonce_elus="$total"
            fi
        else
            annonce_elus=""
        fi
        sleep 10
    done
    # Fin de fenêtre. Ce n'est un problème que s'il reste une base sans chef.
    local reste
    reste=$(kubectl get endpoints -n "$NAMESPACE" --no-headers 2>/dev/null \
            | grep -- '-mysql-leader' | grep -c '<none>' || true)
    [ "${reste:-0}" -eq 0 ] && return 0
    say "AVERTISSEMENT : ${reste} base(s) MySQL sans chef élu à la fin de la fenêtre."
    say "  vérifier :  kubectl get endpoints -n $NAMESPACE | grep leader"
    say "  et         kubectl exec -n $NAMESPACE nacosdb-mysql-0 -c xenon -- xenoncli cluster status"
}

install_app() {
    preflight

    if kubectl get namespace "$NAMESPACE" >/dev/null 2>&1; then
        if [ "$FORCE" = "1" ]; then
            say "Namespace « $NAMESPACE » existant → suppression avant réinstallation."
            uninstall_app
        elif [ -n "$($HELM list -q -n "$NAMESPACE" 2>/dev/null || true)" ]; then
            # Un déploiement peut s'être arrêté en cours de route : l'amont pose
            # d'abord MySQL et Nacos, puis seulement les 41 services. Si les
            # releases existent mais que les services manquent, l'installation
            # est INCOMPLÈTE, et refuser de continuer laisserait l'utilisateur
            # sans autre issue que tout détruire. On reprend là où c'est arrêté ;
            # l'amont utilise « helm upgrade --install », donc repasser sur ce
            # qui existe déjà ne casse rien.
            local deployes
            deployes=$(kubectl get deploy -n "$NAMESPACE" --no-headers 2>/dev/null \
                       | grep -c '^ts-' || true)
            if [ "${deployes:-0}" -ge "${TT_EXPECTED_SERVICES:-40}" ]; then
                say "Train Ticket semble déjà déployé dans « $NAMESPACE » — rien à faire."
                say "Pour repartir de zéro : ./deploy.sh --apps-only --app train-ticket --force-reinstall"
                status_app
                return 0
            fi
            say "Déploiement INCOMPLET détecté : $deployes service(s) sur ${TT_EXPECTED_SERVICES:-40} attendus."
            say "Reprise là où le déploiement s'était arrêté."
        fi
    fi

    fetch_sources
    kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -

    local shim; shim=$(helm3_shim)
    say "Déploiement en cours (infrastructure MySQL/Nacos/RabbitMQ puis 41 services)…"
    say "Compte 15 à 30 minutes : ~46 images Docker doivent être téléchargées."
    # Correcteur IPv6 en tâche de fond, arrêté dès que le déploiement rend la main.
    mysql_ipv6_fixer &
    local fixer_pid=$!
    trap 'kill "$fixer_pid" 2>/dev/null || true' RETURN

    (
        cd "$SRC_DIR"
        export PATH="$shim:$PATH"
        # « timeout » indispensable : le script amont enchaîne des
        # « kubectl rollout status » SANS délai maximal. Si un StatefulSet ne
        # converge jamais, il attend indéfiniment, sans le moindre message —
        # le déploiement paraît figé et rien n'indique où ni pourquoi.
        if [ -n "$DEPLOY_ARGS" ]; then
            # Le script amont fait « for arg in $args » : il attend bien une
            # chaîne unique contenant les options séparées par des espaces.
            timeout "${TT_DEPLOY_TIMEOUT:-2400}" bash hack/deploy/deploy.sh "$NAMESPACE" "$DEPLOY_ARGS"
        else
            timeout "${TT_DEPLOY_TIMEOUT:-2400}" bash hack/deploy/deploy.sh "$NAMESPACE"
        fi
    ) || { rc=$?
           kill "$fixer_pid" 2>/dev/null || true
           if [ "$rc" = 124 ]; then
               say "Le script amont a dépassé ${TT_DEPLOY_TIMEOUT:-2400}s — il attendait un StatefulSet qui ne converge pas."
               say "Pods en anomalie :"
               kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null \
                   | awk '{split($2,a,"/"); if (!(a[2]>0 && a[1]==a[2])) print "    " $1, $2, $3}' | head -10
               say "Vérifie aussi les services leader :  kubectl get endpoints -n $NAMESPACE | grep leader"
           fi
           fail "Le déploiement amont a échoué (code $rc)."; }

    # NE PAS arrêter le correcteur ici. Le script amont rend la main dès que ses
    # « rollout status » sont satisfaits — or un pod RadonDB devient Ready sans
    # que l'élection Raft ait abouti : la sonde interroge MySQL, pas Raft.
    # Constaté : nacosdb corrigé pendant le déploiement, tsdb réécrit APRÈS le
    # retour du script amont, correcteur déjà tué, aucun chef élu, et les 41
    # services en échec pendant les trente minutes d'attente qui suivent.
    # Le correcteur s'arrête de lui-même dès que tous les services leader sont
    # adressés ; sinon il couvre toute l'attente.
    if ! wait_ready; then
        kill "$fixer_pid" 2>/dev/null || true
        status_app
        fail "Train Ticket n'est pas complètement démarré (voir les pods ci-dessus)."
    fi
    kill "$fixer_pid" 2>/dev/null || true
    status_app
    urls_app
}

# Attente active : on suit la proportion de pods prêts plutôt qu'un rollout unique.
wait_ready() {
    local timeout="${TT_READY_TIMEOUT:-1800}" waited=0 total=0 ready=0
    say "Attente du démarrage des microservices (max $((timeout / 60)) minutes)…"
    while [ "$waited" -lt "$timeout" ]; do
        # Chaque lecture est protégée : une erreur transitoire de l'API ne doit
        # pas tuer une attente de 30 minutes.
        total=$(kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l || true)
        # awk ne gère PAS les références arrière : « /^([0-9]+)\/\1$/ » y traite
        # \1 comme un « 1 » littéral et ne reconnaît donc que « X/1 », jamais
        # « 3/3 ». Ce faux zéro faisait échouer un déploiement qui progressait.
        # On découpe et on compare les deux membres.
        ready=$(kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null \
                | awk '{split($2,a,"/"); if ((a[2]>0 && a[1]==a[2]) || $3=="Completed") c++} END {print c+0}' || true)
        total=${total:-0}; ready=${ready:-0}
        if [ "$total" -gt 0 ] && [ "$ready" -eq "$total" ]; then
            say "Tous les pods sont prêts ($ready/$total)."
            return 0
        fi
        sleep 20; waited=$((waited + 20))
        [ $((waited % 120)) -eq 0 ] && say "  … $ready/$total pods prêts (${waited}s)"
    done
    say "ÉCHEC : délai dépassé, seulement $ready/$total pods prêts."
    say "Pods en anomalie :"
    kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null \
        | awk '$3!="Running" && $3!="Completed" {print "    " $1, $2, $3}' || true
    return 1
}

uninstall_app() {
    say "Suppression du namespace « $NAMESPACE » (releases Helm et PVC compris)…"
    kubectl delete namespace "$NAMESPACE" --ignore-not-found --timeout=600s || true
    say "Désinstallation terminée. Les sources restent dans $SRC_DIR."
}

status_app() {
    echo
    say "État des pods dans « $NAMESPACE » :"
    kubectl get pods -n "$NAMESPACE" 2>/dev/null | awk 'NR<=60' || say "Namespace absent."
    echo
    say "Services de type NodePort :"
    kubectl get svc -n "$NAMESPACE" 2>/dev/null | grep -E "NAME|NodePort" || true
    echo
    say "Volumes persistants :"
    kubectl get pvc -n "$NAMESPACE" 2>/dev/null || true
    return 0
}

urls_app() {
    local ip; ip=$(node_ip)
    local ui gw
    ui=$(kubectl -n "$NAMESPACE" get svc ts-ui-dashboard -o jsonpath='{.spec.ports[0].nodePort}' 2>/dev/null || echo "$UI_NODEPORT")
    gw=$(kubectl -n "$NAMESPACE" get svc ts-gateway-service -o jsonpath='{.spec.ports[0].nodePort}' 2>/dev/null || echo "$GW_NODEPORT")
    cat <<EOF

  ┌──────────────────────────────────────────────────────────────────────────┐
  │  Train Ticket — accès aux interfaces web                                 │
  └──────────────────────────────────────────────────────────────────────────┘
     Interface de réservation ....... http://$ip:$ui
     Passerelle API (ts-gateway) .... http://$ip:$gw

   Comptes de démonstration fournis par le benchmark :
     utilisateur : fdse_microservice   mot de passe : 111111
     administrateur : admin            mot de passe : 222222

   Si le port $ui n'est pas joignable depuis ton poste, ouvre un tunnel SSH :
     ssh -N -L 8081:localhost:$ui master
   puis navigue sur http://localhost:8081
EOF
}

case "${1:-status}" in
    install)   install_app ;;
    uninstall) uninstall_app ;;
    status)    status_app ;;
    urls)      urls_app ;;
    *) echo "Usage: $0 {install|uninstall|status|urls}" >&2; exit 2 ;;
esac
