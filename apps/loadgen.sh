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
#       bash ~/autodeploy/apps/loadgen.sh install|uninstall|status|urls
#       bash ~/autodeploy/apps/loadgen.sh scale <n>     changer la charge
#       bash ~/autodeploy/apps/loadgen.sh voyageurs     combien tournent vraiment
#       bash ~/autodeploy/apps/loadgen.sh bilan         les parcours passent-ils ?
#       bash ~/autodeploy/apps/loadgen.sh reset         compteurs de Locust à zéro
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
#     LG_ORIGINE       (défaut: demande)        qui demande le palier, dans le registre
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

    # Le palier de départ compte autant que les suivants : sans lui, un profil de
    # charge commencerait dans le vide et on ignorerait la charge initiale.
    local t0; t0=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    consigner_palier "$t0" "$t0" "$USERS" "$USERS" "demarrage"
    status_app
    urls_app
}

# ------------------------------------------------------------------------------
# Le registre des paliers
# ------------------------------------------------------------------------------
# Écrit dans un fichier MACHINE, en plus de l'affichage.
#
# Reconstituer un profil de charge en relisant l'affichage obligerait à analyser
# des phrases françaises : un mot changé, et l'analyse casse sans rien signaler.
# Ce fichier a un format fixe et ne contient que des données.
#
# DEUX INSTANTS, PAS UN. Une montée de 10 à 40 voyageurs prend une trentaine de
# secondes : Locust les démarre au rythme de spawn_rate par seconde. Entre les
# deux, la charge n'est ni l'ancienne ni la nouvelle. Les fenêtres de mesure qui
# tombent là sont ambiguës, et il faut pouvoir les écarter — d'où l'instant de la
# demande ET celui où la charge visée est réellement atteinte.
#
# DEUX NOMBRES, PAS UN. Ce qui est demandé, et ce qui est observé. Ils diffèrent
# quand la montée échoue en route, et c'est l'observé qui décrit l'expérience.
#
# L'ORIGINE dit qui a demandé le palier : « demarrage », « demande » (un
# palier du profil), « panne » et « retour_panne » (posés par panne.sh). Une
# hausse de charge injectée comme panne se distingue ainsi d'un palier ordinaire.
# ------------------------------------------------------------------------------
REGISTRE="$(cd "$SCRIPT_DIR/.." && pwd)/journaux/paliers.tsv"
COLONNES='# instant_demande\tinstant_effectif\tvoyageurs_observes\tvoyageurs_demandes\tspawn_rate\tcible\torigine'
ORIGINE="${LG_ORIGINE:-demande}"

consigner_palier() {
    local demande="$1" effectif="$2" observes="$3" vises="$4" origine="$5"
    if [ ! -f "$REGISTRE" ]; then
        mkdir -p "$(dirname "$REGISTRE")" 2>/dev/null
        printf "$COLONNES\n" > "$REGISTRE" 2>/dev/null
    fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$demande" "$effectif" "$observes" "$vises" "$SPAWN_RATE" "$TARGET_NS" "$origine" \
        >> "$REGISTRE" 2>/dev/null || warn "Palier appliqué mais non consigné dans $REGISTRE"
}

# ------------------------------------------------------------------------------
# locust_pod / voyageurs_actuels — parler à Locust
# ------------------------------------------------------------------------------
# L'image locustio/locust est bâtie sur python-slim : elle ne contient NI wget NI
# curl. Tout passe donc par python, seul interpréteur dont la présence est
# garantie. Une version antérieure appelait wget et échouait systématiquement,
# sans que rien ne le montre — la sortie partait dans /dev/null.
# ------------------------------------------------------------------------------
locust_pod() {
    kubectl get pods -n "$NAMESPACE" -l app=locust --no-headers \
        -o custom-columns=:metadata.name 2>/dev/null | head -1
}

voyageurs_actuels() {
    local pod="$1"
    kubectl exec -n "$NAMESPACE" "$pod" -- python -c "
import json, urllib.request
d = json.loads(urllib.request.urlopen('http://localhost:8089/stats/requests', timeout=10).read().decode())
print(d.get('user_count', ''))
" 2>/dev/null | tr -d '[:space:]'
}

# ------------------------------------------------------------------------------
# bilan — les parcours passent-ils, ou échouent-ils ?
# ------------------------------------------------------------------------------
# La question à poser AVANT de lancer une campagne d'une heure.
#
# Une campagne entière a été perdue faute de ce contrôle : le jeton de connexion
# avait expiré, tous les parcours s'arrêtaient à leur première ligne, et rien ne
# le montrait — l'application tournait, les pods étaient « Running », la collecte
# écrivait dans le magasin. Seul le taux d'échec par parcours l'aurait dit.
#
# Deux minutes de trafic suffisent à trancher.
# ------------------------------------------------------------------------------
bilan_app() {
    local pod; pod=$(locust_pod)
    [ -n "$pod" ] || fail "Générateur introuvable. Lance d'abord : $0 install"

    # Les parcours ATTENDUS viennent du fichier de scénarios, pas de Locust : un
    # parcours qui n'a jamais tourné n'a aucune ligne de statistiques, donc
    # comparer Locust à lui-même ne peut pas le voir.
    local attendus=""
    [ -f "$LOCUSTFILE" ] && attendus=$(grep -oP 'name="\K[^"]+' "$LOCUSTFILE" | sort -u | paste -sd'|')

    # Deux lectures par parcours : les TOTAUX depuis le dernier « reset », et
    # MAINTENANT — les dix dernières secondes. Un total dit ce qui s'est passé,
    # pas quand ; le verdict se prend sur maintenant dès qu'il y a du trafic.
    kubectl exec -n "$NAMESPACE" "$pod" -- env ATTENDUS="$attendus" python -c "
import json, os, urllib.request
d = json.loads(urllib.request.urlopen('http://localhost:8089/stats/requests', timeout=10).read().decode())
print()
print('  voyageurs actifs : %s' % d.get('user_count'))
print()
print('  %-30s %8s %8s %6s   %9s %9s %7s' % ('parcours', 'appels', 'échecs', 'taux', 'maintenant', 'échecs', 'p50'))
print('  %-30s %8s %8s %6s   %9s %9s %7s' % ('', 'total', 'total', '', '/s', '/s', 'ms'))
print('  ' + '-' * 84)
mauvais = 0
for s in sorted(d.get('stats', []), key=lambda x: x.get('name') or ''):
    nom = s.get('name') or ''
    if nom in ('', 'Aggregated'):
        continue
    n, e = s.get('num_requests', 0), s.get('num_failures', 0)
    rps, fps = s.get('current_rps') or 0.0, s.get('current_fail_per_sec') or 0.0
    p50 = s.get('median_response_time') or 0
    taux = (e / n) if n else 0
    # Le verdict porte sur maintenant quand le parcours tourne ; sur le total
    # sinon (un parcours rare peut n'avoir aucun appel dans les dix secondes).
    juge = (fps / rps) if rps > 0 else taux
    # Un parcours JAMAIS EXÉCUTÉ est aussi grave qu'un parcours qui échoue, et
    # bien plus discret : son taux d'échec vaut zéro.
    souci = '   <<< échoue' if juge > 0.05 else ('   <<< jamais exécuté' if n == 0 else '')
    if souci:
        mauvais += 1
    print('  %-30s %8d %8d %5.1f%%   %9.2f %9.2f %7d%s' % (nom[:30], n, e, 100 * taux, rps, fps, p50, souci))

attendus = [x for x in os.environ.get('ATTENDUS', '').split('|') if x]
vus = {(s.get('name') or '') for s in d.get('stats', [])}
for a in [a for a in attendus if a not in vus]:
    print('  %-30s %8s %8s %6s   %9s %9s %7s   <<< JAMAIS EXÉCUTÉ' % (a[:30], '-', '-', '-', '-', '-', '-'))
    mauvais += 1
# Le POURQUOI des échecs : Locust garde chaque message d'erreur et son nombre
# d'occurrences. « aucun train » et « 500 » n'appellent pas la même réponse.
erreurs = sorted(d.get('errors', []), key=lambda e: -(e.get('occurrences') or 0))
if erreurs:
    print()
    print('  échecs, par motif :')
    for e in erreurs[:6]:
        print('  %8d  %-30s %s' % (e.get('occurrences') or 0, (e.get('name') or '')[:30], (e.get('error') or '')[:70]))
print()
print('  totaux : depuis le dernier « reset » — le pilote en fait un au départ de chaque campagne.')
print('  maintenant : les dix dernières secondes.')
print()
if mauvais:
    print('  %d parcours en défaut — NE LANCE PAS DE CAMPAGNE.' % mauvais)
    print('  Un parcours jamais exécuté laisse une file vide et un graphe sans flèche.')
    print('  Regarde les journaux du service concerné avant toute mesure.')
else:
    print('  Tous les parcours passent. La campagne peut être lancée.')
print()
" 2>&1
}

# ------------------------------------------------------------------------------
# reset — remettre les compteurs de Locust à zéro
# ------------------------------------------------------------------------------
# Les totaux de « bilan » comptent depuis ce point. Fait au départ de chaque
# campagne, pour que le bilan décrive la campagne et non la nuit d'avant.
# Les voyageurs continuent de tourner : seuls les compteurs repartent de zéro.
# ------------------------------------------------------------------------------
reset_app() {
    local pod; pod=$(locust_pod)
    [ -n "$pod" ] || fail "Générateur introuvable. Lance d'abord : $0 install"
    kubectl exec -n "$NAMESPACE" "$pod" -- python -c "
import urllib.request
urllib.request.urlopen('http://localhost:8089/stats/reset', timeout=10).read()
" 2>&1 || fail "Locust n'a pas remis ses compteurs à zéro."
    say "Compteurs de Locust remis à zéro à $(date -u +%Y-%m-%dT%H:%M:%SZ)."
}

# ------------------------------------------------------------------------------
# scale <n> — changer le nombre de voyageurs SANS redémarrer
# ------------------------------------------------------------------------------
# C'est le geste qui produit la première cause candidate : une hausse de charge
# parfaitement légitime, où la file se remplit alors que rien n'est en panne.
#
# Le changement n'est déclaré fait que lorsque Locust MONTRE le bon nombre de
# voyageurs. Qu'il réponde « Swarming started » prouve seulement que la requête a
# été acceptée.
# ------------------------------------------------------------------------------
scale_app() {
    local n="${1:-}"
    [ -n "$n" ] || fail "Indique un nombre de voyageurs : $0 scale 25"
    case "$n" in ''|*[!0-9]*) fail "Nombre de voyageurs invalide : « $n »" ;; esac
    local pod; pod=$(locust_pod)
    [ -n "$pod" ] || fail "Générateur introuvable. Lance d'abord : $0 install"

    local demande; demande=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    local sortie code=0
    if ! sortie=$(kubectl exec -n "$NAMESPACE" "$pod" -- python -c "
import json, urllib.parse, urllib.request
corps = urllib.parse.urlencode({'user_count': $n, 'spawn_rate': $SPAWN_RATE}).encode()
reponse = urllib.request.urlopen('http://localhost:8089/swarm', corps, timeout=15).read().decode()
try:
    print(json.loads(reponse).get('message', reponse))
except Exception:
    print(reponse[:200])
" 2>&1); then
        code=1
    fi
    if [ "$code" -ne 0 ]; then
        warn "Le changement a échoué, la charge est inchangée :"
        printf '%s\n' "$sortie" | sed 's/^/      /' >&2
        return 1
    fi
    say "Demande envoyée à $demande — Locust répond : $sortie"

    # La montée est progressive. On attend qu'elle aboutisse, avec une limite
    # large : n voyageurs au rythme de spawn_rate par seconde, plus une marge.
    local limite=$(( 30 + n )) reste observe="" effectif=""
    reste=$limite
    say "Vérification de la charge réelle (jusqu'à ${limite}s)…"
    while [ "$reste" -gt 0 ]; do
        observe=$(voyageurs_actuels "$pod")
        if [ "$observe" = "$n" ]; then
            effectif=$(date -u +%Y-%m-%dT%H:%M:%SZ)
            break
        fi
        sleep 5
        reste=$((reste - 5))
    done

    if [ -n "$effectif" ]; then
        consigner_palier "$demande" "$effectif" "$observe" "$n" "$ORIGINE"
        say "Charge confirmée : $n voyageurs à $effectif"
        say "Consigné dans $REGISTRE"
        return 0
    fi

    warn "Locust a accepté, mais la charge observée reste « ${observe:-illisible} »"
    warn "au lieu de $n après ${limite}s. Le palier est consigné avec la valeur"
    warn "OBSERVÉE : c'est elle qui décrit l'expérience, pas celle demandée."
    consigner_palier "$demande" "" "${observe:-inconnu}" "$n" "${ORIGINE}_non_aboutie"
    return 1
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
    voyageurs) voyageurs_actuels "$(locust_pod)" ;;
    bilan)     bilan_app ;;
    reset)     reset_app ;;
    isolate)   shift; isolate_app "${1:-}" ;;
    *) echo "Usage: $0 {install|uninstall|status|urls|scale <n>|voyageurs|bilan|reset|isolate <nœud>}" >&2; exit 2 ;;
esac
