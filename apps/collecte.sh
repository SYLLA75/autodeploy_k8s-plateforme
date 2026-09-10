#!/bin/bash
# ==============================================================================
#  collecte.sh — allumer et éteindre l'envoi des mesures vers le magasin
# ==============================================================================
#
#  POURQUOI CE SCRIPT
#
#  Un cluster coûte cher à recréer — 45 à 60 minutes — mais laisser la collecte
#  tourner en continu remplit le magasin de données que personne ne regardera :
#  environ 107 Mo par heure une fois compressées. On veut donc garder la grappe
#  debout entre deux expériences, sans rien enregistrer, et n'enregistrer que
#  pendant les fenêtres qui comptent.
#
#  CE QUI S'ARRÊTE ET CE QUI CONTINUE
#
#    s'arrête      la passerelle de collecte, seule pièce qui écrit dans le
#                  magasin. Rien n'y arrive plus.
#
#    continue      les 56 microservices, l'instrumentation Java attachée à
#                  chacun, Prometheus et Jaeger en local, les relevés de
#                  machines. L'application reste dans le même état qu'en
#                  mesure — c'est important : redémarrer les services au moment
#                  d'une expérience ferait mesurer une montée en charge à froid
#                  au lieu du régime établi.
#
#  Les traces produites pendant l'arrêt sont perdues, et c'est le but.
#
#  POURQUOI ÉTEINDRE LA PASSERELLE PLUTÔT QUE L'INSTRUMENTATION
#
#  Détacher l'agent Java demanderait de redémarrer les 46 services, soit
#  plusieurs minutes et un régime transitoire à chaque bascule. La passerelle
#  s'éteint et se rallume en quelques secondes, sans toucher à l'application.
#
#  Usage (depuis le master) :
#      bash ~/autodeploy/apps/collecte.sh etat
#      bash ~/autodeploy/apps/collecte.sh demarrer [--avec-charge]
#      bash ~/autodeploy/apps/collecte.sh arreter  [--avec-charge]
#      bash ~/autodeploy/apps/collecte.sh fenetre  [--marge <min>]
#
#  Variables reconnues :
#    OBS_NAMESPACE   (défaut: observability)
#    LG_NAMESPACE    (défaut: loadgen)
# ==============================================================================
set -uo pipefail

NAMESPACE="${OBS_NAMESPACE:-observability}"
LG_NAMESPACE="${LG_NAMESPACE:-loadgen}"
GATEWAY="otel-gateway-opentelemetry-collector"
LOADGEN="locust"
# Le nombre d'exemplaires d'origine est mémorisé ici, pour que « demarrer » le
# rétablisse au lieu de supposer 1.
NOTE="autodeploy/collecte-repliques"

say()  { echo "  [collecte] $*"; }
warn() { echo "  [collecte] ATTENTION: $*" >&2; }
fail() { echo "  [collecte] ERREUR: $*" >&2; exit 1; }

kubectl version --client >/dev/null 2>&1 || fail "kubectl introuvable."

repliques() { kubectl get deploy "$1" -n "$2" -o jsonpath='{.spec.replicas}' 2>/dev/null; }
existe()    { kubectl get deploy "$1" -n "$2" >/dev/null 2>&1; }

# ------------------------------------------------------------------ arrêter
arreter_un() {
    local dep="$1" ns="$2" quoi="$3"
    existe "$dep" "$ns" || { warn "$quoi introuvable dans « $ns » — ignoré."; return 0; }
    local n; n=$(repliques "$dep" "$ns")
    if [ "${n:-0}" = "0" ]; then
        say "$quoi : déjà arrêté."
        return 0
    fi
    # On note combien il y en avait AVANT de descendre à zéro : sans ça, la
    # reprise ne saurait pas s'il en fallait un ou trois.
    kubectl annotate deploy "$dep" -n "$ns" "$NOTE=$n" --overwrite >/dev/null 2>&1
    kubectl scale deploy "$dep" -n "$ns" --replicas=0 >/dev/null \
        && say "$quoi : arrêté (était à $n)." \
        || warn "$quoi : arrêt impossible."
}

demarrer_un() {
    local dep="$1" ns="$2" quoi="$3"
    existe "$dep" "$ns" || { warn "$quoi introuvable dans « $ns » — ignoré."; return 0; }
    local n; n=$(repliques "$dep" "$ns")
    if [ "${n:-0}" != "0" ]; then
        say "$quoi : déjà en marche ($n)."
        return 0
    fi
    local avant; avant=$(kubectl get deploy "$dep" -n "$ns" \
        -o jsonpath="{.metadata.annotations.autodeploy/collecte-repliques}" 2>/dev/null)
    [ -n "$avant" ] || avant=1
    kubectl scale deploy "$dep" -n "$ns" --replicas="$avant" >/dev/null \
        && say "$quoi : redémarré ($avant)." \
        || warn "$quoi : redémarrage impossible."
}

attendre_pret() {
    local dep="$1" ns="$2" quoi="$3" t
    for t in $(seq 1 30); do
        local pret
        pret=$(kubectl get deploy "$dep" -n "$ns" -o jsonpath='{.status.readyReplicas}' 2>/dev/null)
        [ "${pret:-0}" -gt 0 ] && { say "$quoi : prêt après $((t*4))s."; return 0; }
        sleep 4
    done
    warn "$quoi : toujours pas prêt après 2 minutes."
    return 1
}

# -------------------------------------------------------------------- état
etat_app() {
    local g l
    g=$(repliques "$GATEWAY" "$NAMESPACE")
    l=$(repliques "$LOADGEN" "$LG_NAMESPACE")

    echo
    if [ "${g:-0}" = "0" ]; then
        echo "     COLLECTE ARRÊTÉE — rien n'arrive dans le magasin"
    else
        echo "     COLLECTE EN MARCHE — les mesures partent vers le magasin"
    fi
    echo "     ────────────────────────────────────────────────────────"
    echo
    printf "     %-34s %s\n" "passerelle vers le magasin" \
        "$([ "${g:-0}" = "0" ] && echo "arrêtée" || echo "$g exemplaire(s)")"
    printf "     %-34s %s\n" "générateur de charge" \
        "$([ "${l:-0}" = "0" ] && echo "arrêté" || echo "${l:-absent} exemplaire(s)")"

    local svc pods
    svc=$(kubectl get pods -n "${OBS_MQ_NAMESPACE:-train-ticket}" --no-headers 2>/dev/null \
          | awk '{split($2,a,"/"); if (a[2]>0 && a[1]==a[2]) n++} END{print n+0}')
    pods=$(kubectl get pods -n "${OBS_MQ_NAMESPACE:-train-ticket}" --no-headers 2>/dev/null | wc -l)
    printf "     %-34s %s\n" "microservices" "$svc/$pods prêts"

    local agents
    agents=$(kubectl get daemonset -n "$NAMESPACE" --no-headers 2>/dev/null \
             | awk '/collector-agent/ {print $4}')
    printf "     %-34s %s\n" "collecteurs locaux (traces)" "${agents:-0} en marche"
    printf "     %-34s %s\n" "relevés de machines" \
        "$(kubectl get daemonset -n "$NAMESPACE" --no-headers 2>/dev/null | awk '/node-exporter/ {print $4}') en marche"
    echo
    if [ "${g:-0}" = "0" ]; then
        echo "     L'application tourne et reste instrumentée. Les traces produites"
        echo "     pendant l'arrêt sont perdues — c'est le but."
        echo "     Pour enregistrer :  bash $0 demarrer"
    else
        echo "     Pour connaître la plage à rapatrier :  bash $0 fenetre"
    fi
    echo
}

# ----------------------------------------------------------------- fenêtre
# Rend la plage exploitable, en heure UTC — celle du magasin, pas celle du poste.
# C'est l'erreur qui coûte une campagne : rapatrier une plage qui précède le
# démarrage de la collecte, et conclure que le code est cassé parce qu'il ne
# trouve aucune flèche.
fenetre_app() {
    local marge="${1:-2}"
    local g; g=$(repliques "$GATEWAY" "$NAMESPACE")
    if [ "${g:-0}" = "0" ]; then
        warn "La collecte est arrêtée : il n'y a pas de plage à rapatrier."
        say "  bash $0 demarrer"
        return 1
    fi

    local maintenant; maintenant=$(date -u +%s)

    # Deux dates comptent, et c'est LA PLUS TARDIVE qui ouvre la fenêtre :
    #
    #   la passerelle    avant elle, rien n'arrive dans le magasin
    #   la charge        avant elle, l'application ne fait que bavarder
    #                    (annuaire, sondes) et le graphe n'a aucune flèche
    #
    # Prendre la première mènerait à rapatriser une plage d'apparence valide mais
    # vide de trafic — l'erreur coûte une campagne, et se présente comme un bug
    # du constructeur de graphe : « 0 publishes, 0 consumes », alors que tout
    # fonctionne.
    local d_passerelle d_charge origine quoi
    d_passerelle=$(kubectl get pods -n "$NAMESPACE" \
                   -l "app.kubernetes.io/name=opentelemetry-collector" \
                   --no-headers -o custom-columns=":.status.startTime" 2>/dev/null \
                   | grep -v '^$' | sort | tail -1)
    [ -n "$d_passerelle" ] || d_passerelle=$(kubectl get deploy "$GATEWAY" -n "$NAMESPACE" \
                                 -o jsonpath='{.metadata.creationTimestamp}' 2>/dev/null)
    d_charge=$(kubectl get pods -n "$LG_NAMESPACE" --no-headers \
               -o custom-columns=":.status.startTime" 2>/dev/null \
               | grep -v '^$' | sort | tail -1)

    local s_passerelle s_charge
    s_passerelle=$(date -u -d "$d_passerelle" +%s 2>/dev/null || echo "$maintenant")
    origine=$s_passerelle; quoi="démarrage de la passerelle"
    if [ -n "$d_charge" ]; then
        s_charge=$(date -u -d "$d_charge" +%s 2>/dev/null || echo 0)
        if [ "$s_charge" -gt "$origine" ]; then
            origine=$s_charge; quoi="démarrage du générateur de charge"
        fi
    else
        warn "Aucun générateur de charge : l'application ne produira que du"
        warn "  bavardage de fond, et le graphe n'aura aucune flèche."
    fi

    local debut_s fin_s
    debut_s=$(( origine + marge*60 ))
    fin_s=$(( maintenant - marge*60 ))

    # Il faut au moins quelques fenêtres, pas quelques secondes. Une plage plus
    # courte que le minimum passerait le contrôle « fin > début » tout en
    # produisant zéro fenêtre exploitable : le découpeur écarte les bords, et il
    # ne resterait rien. Autant le dire ici plutôt que de laisser découvrir
    # « no usable window » après un téléchargement.
    local MINI=300
    if [ $(( fin_s - debut_s )) -lt "$MINI" ]; then
        local manque=$(( (MINI - (fin_s - debut_s) + 59) / 60 ))
        warn "Plage trop courte : $(( (fin_s - debut_s) / 60 )) minute(s) exploitable(s),"
        warn "  il en faut au moins $(( MINI / 60 )) pour que le découpage donne quelque chose."
        say "  Attends encore $manque minute(s), puis relance cette commande."
        say "  (les mesures partent par lots de 30 s, et $marge min sont écartées de chaque côté)"
        return 1
    fi

    echo
    say "Passerelle démarrée à  $(date -u -d "@$s_passerelle" '+%H:%M:%S') UTC"
    [ -n "$d_charge" ] && say "Charge démarrée à      $(date -u -d "@$s_charge" '+%H:%M:%S') UTC"
    say "Origine retenue        $(date -u -d "@$origine" '+%H:%M:%S') UTC  ($quoi)"
    say "Il est $(date -u '+%H:%M:%S') UTC — $(( (maintenant - origine) / 60 )) minutes exploitables"
    say "Marge de $marge minute(s) écartée de chaque côté (montée en charge, latence d'écriture)."

    # Une reprise après pause laisse un TROU dans le magasin. La plage rendue
    # est celle de la session en cours, jamais à cheval sur le trou : une
    # fenêtre qui l'enjamberait mélangerait deux régimes séparés par un blanc,
    # et le découpeur y verrait une chute de trafic qui n'a pas eu lieu.
    local creation s_creation
    creation=$(kubectl get deploy "$GATEWAY" -n "$NAMESPACE" \
               -o jsonpath='{.metadata.creationTimestamp}' 2>/dev/null)
    s_creation=$(date -u -d "$creation" +%s 2>/dev/null || echo "$s_passerelle")
    if [ $(( s_passerelle - s_creation )) -gt 300 ]; then
        echo
        say "La collecte a déjà été interrompue au moins une fois."
        say "  Le magasin contient aussi des mesures antérieures, séparées de"
        say "  celles-ci par un blanc. La plage ci-dessous s'arrête au bord du"
        say "  blanc : ne l'élargis pas vers le passé sans le savoir."
    fi
    echo
    echo "  À recopier dans graphe_en/config.yaml :"
    echo
    echo "    range:"
    echo "      date:       $(date -u -d "@$fin_s" '+%Y-%m-%d')"
    echo "      from:       \"$(date -u -d "@$debut_s" '+%H:%M')\""
    echo "      to:         \"$(date -u -d "@$fin_s" '+%H:%M')\""
    echo
}

# ------------------------------------------------------------------ actions
AVEC_CHARGE=0
MARGE=2
ACTION="${1:-etat}"; shift || true
while [ $# -gt 0 ]; do
    case "$1" in
        --avec-charge) AVEC_CHARGE=1; shift ;;
        --marge) MARGE="${2:-2}"; shift 2 ;;
        *) fail "Option inconnue : $1" ;;
    esac
done

case "$ACTION" in
    arreter|stop)
        arreter_un "$GATEWAY" "$NAMESPACE" "passerelle vers le magasin"
        [ "$AVEC_CHARGE" = "1" ] && arreter_un "$LOADGEN" "$LG_NAMESPACE" "générateur de charge"
        say "L'application continue de tourner, instrumentée, sans rien enregistrer."
        etat_app
        ;;
    demarrer|start)
        demarrer_un "$GATEWAY" "$NAMESPACE" "passerelle vers le magasin"
        [ "$AVEC_CHARGE" = "1" ] && demarrer_un "$LOADGEN" "$LG_NAMESPACE" "générateur de charge"
        attendre_pret "$GATEWAY" "$NAMESPACE" "passerelle vers le magasin"
        say "Enregistrement repris à $(date -u '+%H:%M:%S') UTC."
        say "Attends 2 à 3 minutes avant de rapatrier : les mesures partent par lots de 30 s."
        say "  bash $0 fenetre     donnera la plage exacte."
        ;;
    etat|status)   etat_app ;;
    fenetre|window) fenetre_app "$MARGE" ;;
    *) echo "Usage: $0 {etat|demarrer|arreter|fenetre} [--avec-charge] [--marge <min>]" >&2; exit 2 ;;
esac
