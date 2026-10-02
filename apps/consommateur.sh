#!/bin/bash
# ==============================================================================
#  apps/consommateur.sh — dimensionner le consommateur pour sa charge
# ==============================================================================
#
#  POURQUOI
#
#  Une faute de coordination n'apparaît que si le consommateur est taillé pour
#  sa charge, avec peu de marge — c'est le cas de tout système réel. Or
#  ts-delivery-service ne fait presque rien par message : 6 ms, soit ~500
#  messages par seconde pour trois répliques, quand la file en reçoit 3. Avec
#  mille fois trop de marge, une réplique gelée ou un hôte saturé ne changent
#  rien à la file : les autres absorbent tout, le tas reste à zéro, et le
#  symptôme central de l'étude n'existe pas.
#
#  CE QUE FAIT CE SCRIPT
#
#  Deux réglages, posés une fois, AVANT la référence saine, et conservés à
#  l'identique pour toutes les campagnes :
#
#    temps de service   chaque échange entre une réplique et sa base est
#                       retardé de L millisecondes (Chaos Mesh NetworkChaos,
#                       sans durée : il reste tant qu'on ne le retire pas).
#                       Traiter un message coûte quelques échanges avec la base
#                       (lecture, insertion, validation, plus la gestion de la
#                       transaction) : le temps de service vaut environ 5 × L.
#                       Le retard est PROPRE À CHAQUE RÉPLIQUE : trois
#                       répliques traitent bien trois messages à la fois.
#
#    prefetch = 1       le courtier ne confie qu'un message à la fois à chaque
#                       réplique. Par défaut il en confie 250 d'avance : le tas
#                       visible (messages en attente) ne bougerait qu'après
#                       750 messages en souffrance, et une réplique gelée en
#                       emporterait 250 avec elle.
#
#  POURQUOI UN RETARD RÉSEAU ET PAS UN SOMMEIL DANS LA BASE
#
#  Un déclencheur SQL qui dort à chaque insertion a été essayé : la base
#  n'exécute qu'un sommeil à la fois, quel que soit le nombre de répliques
#  (mesuré : 1 sommeil actif en permanence, 1,3 message/s pour 3 répliques
#  à 0,7 s). La capacité ne dépendait plus du nombre de répliques, et une
#  réplique gelée n'aurait rien changé. Le retard réseau s'applique dans
#  chaque pod, indépendamment des autres.
#
#  COMMENT CHOISIR L
#
#  Capacité des N répliques = N / (5 × L) messages par seconde. On vise ~80 %
#  à la charge de base : L = 0,8 × N / (5 × débit_de_base). Avec 3 répliques
#  et 3,4 messages/s mesurés (25 voyageurs) : L ≈ 140 ms. Le facteur 5 se
#  vérifie sur la première référence (process_time_p50 des répliques dans les
#  figures) et sur le témoin : le tas ne doit pas grossir à la charge de base.
#
#  LE RETARD NE SUIT PAS LES PODS
#
#  Chaos Mesh ne choisit ses cibles qu'au moment où l'objet est posé : une
#  réplique recréée ensuite (redémarrage, éviction, machine relancée) n'a PAS
#  le retard, et l'objet se dit pourtant toujours « appliqué ». Le 1/10, deux
#  répliques sur trois en ont été privées plus de huit heures sans alerte.
#  « verifier » lit donc le retard que porte réellement chaque réplique en
#  marche, et « reposer » recrée l'objet à sa valeur pour couvrir les nouvelles.
#
#  Usage (depuis le master) :
#      bash ~/autodeploy/apps/consommateur.sh dimensionner --retard 140 [--prefetch 1]
#      bash ~/autodeploy/apps/consommateur.sh etat
#      bash ~/autodeploy/apps/consommateur.sh verifier
#          0 = chaque réplique en marche a le retard,
#          1 = non (la marche à suivre est affichée),
#          3 = une panne « consumer-slowdown » le remplace (normal, rien à faire)
#      bash ~/autodeploy/apps/consommateur.sh reposer
#          recrée le retard à sa valeur actuelle, sans redémarrer de pod ;
#          3 = refusé, une panne « consumer-slowdown » est en cours
#      bash ~/autodeploy/apps/consommateur.sh retirer
#
#  Variables reconnues :
#      CONSO_NAMESPACE     (défaut: train-ticket)
#      CONSO_DEPLOY        (défaut: ts-delivery-service)   le consommateur
#      CONSO_MYSQL_LABEL   (défaut: app=tsdb-mysql)        les pods de sa base
#      CONSO_DB            (défaut: ts)                    la base
#      CONSO_TABLE         (défaut: delivery)              la table où il écrit
# ==============================================================================
set -uo pipefail

_ici="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Une simple lecture ne laisse pas de journal : il n'y a rien à garder, et
# un relevé répété toutes les 20 s en écrirait des centaines.
case "${1:-}" in etat|verifier) JOURNAL_OFF=1 ;; esac
[ -f "$_ici/journal.sh" ] && JOURNAL_NOM="consommateur" . "$_ici/journal.sh"

DEPLOY="${CONSO_DEPLOY:-ts-delivery-service}"
TABLE="${CONSO_TABLE:-delivery}"
DECLENCHEUR="temps_de_service"
ENV_PREFETCH="SPRING_RABBITMQ_LISTENER_SIMPLE_PREFETCH"

JOURNAUX="$(cd "$_ici/.." && pwd)/journaux"
REGISTRE="$JOURNAUX/consommateur.tsv"
COLONNES='# instant\taction\tretard_ms\tprefetch\tresultat'

say()  { echo "  [consommateur] $*"; }
ok()   { echo "  [consommateur] OK  $*"; }
warn() { echo "  [consommateur] ATTENTION: $*" >&2; }
fail() { echo "  [consommateur] ERREUR: $*" >&2; exit 1; }
maintenant() { date -u +%Y-%m-%dT%H:%M:%SZ; }

consigner() {
    mkdir -p "$JOURNAUX" 2>/dev/null
    [ -f "$REGISTRE" ] || printf "$COLONNES\n" > "$REGISTRE" 2>/dev/null
    printf '%s\t%s\t%s\t%s\t%s\n' "$(maintenant)" "$1" "$2" "$3" "$4" >> "$REGISTRE" 2>/dev/null
}

. "$_ici/mysql.sh"

OBJET="consommateur-temps-de-service"   # l'objet Chaos Mesh du retard
PANNE="fault-consumer-slowdown"         # l'objet de panne.sh qui le remplace pendant une panne
# COMPATIBILITÉ — à retirer après la collecte : le même objet posé par une
# copie de panne.sh d'avant K2.0a, sous son ancien nom. etat_panne regarde les
# deux noms ; verifier, reposer, etat et dimensionner passent tous par elle.
# Elle retient dans PANNE_VUE le nom de l'objet vu, pour les messages. Pour
# retirer la compat : cette ligne, et la boucle d'etat_panne sur un seul nom.
# Déploiement : panne.sh et consommateur.sh partent ENSEMBLE sur le master
# (deploy.sh --push-scripts) : un consommateur.sh ancien ne verrait pas
# fault-consumer-slowdown, et « reposer » écraserait la panne en cours.
PANNE_ANCIEN="panne-lenteur"

retard_actuel() {   # la latence posée, en ms, vide s'il n'y a pas d'objet
    kubectl get networkchaos "$OBJET" -n "$NS" -o jsonpath='{.spec.delay.latency}' 2>/dev/null | tr -d 'ms'
}

retard_injecte() {   # appliqué sur les répliques choisies à la pose ? (pas les suivantes : voir couverture)
    [ "$(kubectl get networkchaos "$OBJET" -n "$NS" -o jsonpath='{.status.conditions[?(@.type=="AllInjected")].status}' 2>/dev/null)" = "True" ]
}

# L'objet ne dit que si Chaos Mesh a touché les pods qu'il a choisis à la pose :
# une réplique née après n'y figure pas. Seul ce que porte chaque réplique fait foi.
retard_pose() {   # <pod> → le retard de l'objet réellement posé sur cette réplique, vide si rien
    kubectl get podnetworkchaos "$1" -n "$NS" \
        -o jsonpath="{.spec.tcs[?(@.source==\"$NS/$OBJET\")].delay.latency}" 2>/dev/null \
        | tr ' ' '\n' | sort -u | paste -sd' '
}

# nom <tab> machine — les répliques en marche. Un pod qui s'arrête reste
# « Running » jusqu'à sa fin : il est écarté (il porte une date de suppression).
repliques_en_marche() {
    kubectl get pods -n "$NS" -l "app=$DEPLOY" --field-selector=status.phase=Running \
        --sort-by=.metadata.name --no-headers \
        -o custom-columns=:metadata.name,:spec.nodeName,:metadata.deletionTimestamp 2>/dev/null \
        | awk 'NF==3 && $3=="<none>" {print $1"\t"$2}'
}

# lire_nc <objet> <jsonpath> — la valeur lue ; rend 0 si lue, 1 si l'objet
# n'existe pas, 2 si l'API ne répond pas (à ne pas prendre pour une absence).
lire_nc() {
    local sortie
    if sortie=$(kubectl get networkchaos "$1" -n "$NS" -o jsonpath="$2" 2>&1); then
        printf '%s' "$sortie"; return 0
    fi
    case "$sortie" in *NotFound*|*"not found"*) return 1 ;; *) return 2 ;; esac
}

# La panne consumer-slowdown de panne.sh remplace le réglage. Chaos Mesh l'arrête
# seul à son échéance mais ne supprime pas l'objet : c'est le minuteur de panne.sh
# qui le fait, et qui repose le réglage. S'il est mort, l'objet reste, arrêté.
# L'objet est cherché sous son nom puis sous son ancien nom (compat) : une panne
# en cours l'emporte sur une panne arrêtée, et arrête la recherche.
# etat_panne pose PANNE_ETAT (absente | en_cours | arretee | injoignable) et
# PANNE_VUE (le nom de l'objet vu ; $PANNE si aucun). Appelée sans $( ) pour
# que les deux restent dans le shell.
etat_panne() {
    local nom phase c
    PANNE_ETAT=absente; PANNE_VUE="$PANNE"
    for nom in "$PANNE" "$PANNE_ANCIEN"; do   # compat : "$PANNE_ANCIEN"
        c=0; phase=$(lire_nc "$nom" '{.status.experiment.desiredPhase}') || c=$?
        case "$c" in
            0) if [ "$phase" != Stop ]; then PANNE_ETAT=en_cours; PANNE_VUE="$nom"; return 0; fi
               [ "$PANNE_ETAT" = arretee ] || { PANNE_ETAT=arretee; PANNE_VUE="$nom"; } ;;
            1) ;;
            *) PANNE_ETAT=injoignable; PANNE_VUE="$PANNE"; return 0 ;;
        esac
    done
    return 0
}

# couverture [malgre_panne] — une ligne par réplique en marche, avec le retard
# qu'elle porte. 0 : l'objet existe et chaque réplique (au moins une) porte sa
# valeur ; 1 : non, RAISON dit pourquoi ; 3 : une panne consumer-slowdown remplace le
# réglage, il n'y a rien à juger. « malgre_panne » juge quand même : c'est le
# cas de dimensionner, que panne.sh retirer appelle pour reposer le réglage
# AVANT de lever la panne (la lecture ne regarde que la source $OBJET).
couverture() {
    RAISON="" VOULU=""
    etat_panne
    case "$PANNE_ETAT" in
        injoignable)
            echo "  retard par réplique : l'API Kubernetes ne répond pas, rien n'est lu"
            RAISON=injoignable; return 1 ;;
        en_cours)
            if [ "${1:-}" != malgre_panne ]; then
                echo "  retard par réplique : panne consumer-slowdown en cours ($PANNE_VUE remplace le réglage — c'est normal)"
                return 3
            fi ;;
        arretee)
            echo "  $PANNE_VUE est arrêtée mais toujours là : son retrait (panne.sh) n'a pas eu lieu" ;;
    esac
    local c=0; VOULU=$(lire_nc "$OBJET" '{.spec.delay.latency}') || c=$?
    if [ "$c" -eq 2 ]; then
        echo "  retard par réplique : l'API Kubernetes ne répond pas, rien n'est lu"
        RAISON=injoignable; return 1
    fi
    local liste; liste=$(repliques_en_marche)
    local r noeud pose n=0 manque=0
    if [ -n "$VOULU" ]; then
        echo "  retard par réplique (attendu : $VOULU) :"
    else
        echo "  retard par réplique (attendu : rien, il n'y a pas d'objet $OBJET) :"
    fi
    while IFS=$'\t' read -r r noeud; do
        [ -n "$r" ] || continue
        n=$((n + 1))
        pose=$(retard_pose "$r")
        if [ -n "$VOULU" ] && [ "$pose" = "$VOULU" ]; then
            printf '      %-40s sur %-16s %s\n' "$r" "$noeud" "$pose"
        elif [ -z "$pose" ]; then
            printf '      %-40s sur %-16s rien   <- MANQUE\n' "$r" "$noeud"
            manque=$((manque + 1))
        else
            printf '      %-40s sur %-16s %s   <- AUTRE VALEUR\n' "$r" "$noeud" "$pose"
            manque=$((manque + 1))
        fi
    done <<< "$liste"
    [ "$n" -gt 0 ] || echo "      aucune réplique de $DEPLOY en marche"
    [ -n "$VOULU" ] && [ "$n" -gt 0 ] && [ "$manque" -eq 0 ] && return 0
    if   [ "$PANNE_ETAT" = arretee ]; then RAISON=arretee
    elif [ -z "$VOULU" ];             then RAISON=absent
    elif [ "$n" -eq 0 ];              then RAISON=aucune
    else                                   RAISON=manque
    fi
    return 1
}

marche_a_suivre() {   # le remède, d'après RAISON (posée par couverture)
    case "$RAISON" in
        injoignable) echo "l'API Kubernetes ne répond pas, rien n'est jugé :  kubectl get networkchaos -n $NS" ;;
        arretee)     echo "$PANNE_VUE arrêtée mais pas retirée, le réglage n'est pas reposé :  panne.sh retirer   (puis consommateur.sh verifier)" ;;
        absent)      echo "aucun réglage $OBJET dans $NS — à poser :  consommateur.sh dimensionner --retard 140" ;;
        aucune)      echo "aucune réplique de $DEPLOY en marche :  kubectl get pods -n $NS -l app=$DEPLOY" ;;
        *) if [ "$PANNE_ETAT" = en_cours ]; then
               # reposer est refusé pendant la panne : seul dimensionner pose le réglage.
               echo "des répliques en marche n'ont pas le bon retard (panne consumer-slowdown en cours) — à reprendre :  consommateur.sh dimensionner --retard $(tr -d 'ms' <<< "$VOULU")"
           else
               echo "des répliques en marche n'ont pas le bon retard — le reposer (quelques secondes sans retard, aucun redémarrage) :  consommateur.sh reposer"
           fi ;;
    esac
}

# Un sommeil dans la base ne doit pas coexister avec le retard : il retirerait
# le parallélisme des répliques.
declencheur_present() {
    [ -n "$(sql "SELECT 1 FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA='$DB' AND TRIGGER_NAME='$DECLENCHEUR';" 2>/dev/null | tail -1)" ]
}

repliques_pretes() {   # toutes les répliques voulues sont-elles prêtes ET à jour ?
    local v p m
    v=$(kubectl get deploy "$DEPLOY" -n "$NS" -o jsonpath='{.spec.replicas}' 2>/dev/null)
    p=$(kubectl get deploy "$DEPLOY" -n "$NS" -o jsonpath='{.status.readyReplicas}' 2>/dev/null)
    m=$(kubectl get deploy "$DEPLOY" -n "$NS" -o jsonpath='{.status.updatedReplicas}' 2>/dev/null)
    [ -n "$v" ] && [ "${p:-0}" = "$v" ] && [ "${m:-0}" = "$v" ]
}

prefetch_actuel() {   # la valeur portée par le déploiement, vide si absente
    kubectl get deploy "$DEPLOY" -n "$NS" \
        -o jsonpath="{.spec.template.spec.containers[0].env[?(@.name==\"$ENV_PREFETCH\")].value}" 2>/dev/null
}

# poser_retard <ms> — crée ou remplace l'objet, attend qu'il soit appliqué
poser_retard() {
    local ms="$1"
    kubectl delete networkchaos "$OBJET" -n "$NS" --ignore-not-found --timeout=90s >/dev/null 2>&1
    yaml_retard "$OBJET" "$DEPLOY" "$ms" "" "reglage=consommateur" | kubectl apply -f - >/dev/null || return 1
    local reste=60
    while [ "$reste" -gt 0 ]; do
        retard_injecte && return 0
        sleep 3; reste=$((reste - 3))
    done
    return 1
}

# ------------------------------------------------------------------------------
dimensionner_app() {
    local retard="" prefetch=1
    while [ $# -gt 0 ]; do
        case "$1" in
            --retard)   retard="${2:-}"; shift 2 ;;
            --prefetch) prefetch="${2:-}"; shift 2 ;;
            *) fail "Option inconnue : $1" ;;
        esac
    done
    case "$retard" in ''|*[!0-9]*) fail "--retard : un nombre de millisecondes, par exemple 140" ;; esac
    [ "$retard" -ge 1 ] || fail "--retard : au moins 1 ms"
    case "$prefetch" in ''|*[!0-9]*) fail "--prefetch : un entier" ;; esac
    [ "$prefetch" -ge 1 ] || fail "--prefetch : au moins 1"
    kubectl get deploy "$DEPLOY" -n "$NS" >/dev/null 2>&1 || fail "Déploiement « $DEPLOY » introuvable dans $NS."
    kubectl get crd networkchaos.chaos-mesh.org >/dev/null 2>&1 || fail "Chaos Mesh absent — étape 6 bis : chaos.sh install"
    local n; n=$(kubectl get pods -n "$NS" -l "app=$DEPLOY" --field-selector=status.phase=Running --no-headers 2>/dev/null | wc -l)
    [ "$n" -gt 0 ] || fail "Aucune réplique de $DEPLOY en marche."

    if declencheur_present; then
        say "Un sommeil dans la base est en place : retiré (il sérialise les répliques)."
        sql "DROP TRIGGER IF EXISTS $DECLENCHEUR;" >/dev/null
    fi

    say "Temps de service : $retard ms de retard à chaque échange des $n répliques avec leur base (≈ $((retard * 5)) ms par message)"
    if poser_retard "$retard"; then
        ok "retard posé sur $n réplique(s)"
    else
        consigner dimensionner "$retard" "$prefetch" ECHEC
        fail "Chaos Mesh n'a pas confirmé en 60 s :  kubectl describe networkchaos $OBJET -n $NS"
    fi

    say "Prefetch : $prefetch message(s) d'avance par réplique"
    local avant; avant=$(prefetch_actuel)
    if [ "$avant" = "$prefetch" ]; then
        say "déjà en place, pas de redémarrage"
    else
        kubectl set env deploy/"$DEPLOY" -n "$NS" "$ENV_PREFETCH=$prefetch" >/dev/null \
            || { consigner dimensionner "$retard" "$prefetch" ECHEC; fail "kubectl set env a échoué."; }
        say "redémarrage roulant des répliques (nouveaux pods, donc nouveaux nœuds dans le graphe — d'où « avant la référence »)…"
        # Trois services Java qui redémarrent l'un après l'autre : compter
        # jusqu'à dix minutes, et regarder l'état réel avant de conclure.
        kubectl rollout status deploy/"$DEPLOY" -n "$NS" --timeout=600s >/dev/null 2>&1 \
            || repliques_pretes \
            || { consigner dimensionner "$retard" "$prefetch" ECHEC; fail "Les répliques ne sont pas revenues en 10 min :  kubectl get pods -n $NS -l app=$DEPLOY"; }
        # Chaos Mesh ne choisit ses cibles qu'à la pose : les répliques neuves
        # n'ont pas le retard posé plus haut. Il est reposé pour elles, ce qui
        # laisse quelques secondes sans retard — seulement quand le prefetch
        # change, donc au premier dimensionnement, avant la référence.
        say "les répliques neuves n'ont pas le retard (Chaos Mesh ne suit pas les pods) : il est reposé"
        poser_retard "$retard" || warn "Chaos Mesh n'a pas confirmé en 60 s :  kubectl describe networkchaos $OBJET -n $NS"
    fi
    # Le contrôle porte sur chaque réplique, pas sur l'état global de l'objet,
    # et même pendant une panne consumer-slowdown : le réglage vient d'être posé.
    local code=0
    verifier_app malgre_panne || code=$?
    if [ "$code" -ne 0 ]; then
        consigner dimensionner "$retard" "$prefetch" ECHEC
        warn "consommateur PAS dimensionné sur toutes ses répliques — voir ci-dessus"
        return "$code"
    fi
    consigner dimensionner "$retard" "$prefetch" ok
    ok "consommateur dimensionné — à conserver tel quel pour toutes les campagnes"
    echo
    etat_app sans_couverture   # la couverture vient d'être affichée
}

etat_app() {   # [sans_couverture]
    local ms; ms=$(retard_actuel)
    local pf; pf=$(prefetch_actuel)
    etat_panne; local panne="$PANNE_ETAT"
    local repl; repl=$(kubectl get deploy "$DEPLOY" -n "$NS" -o jsonpath='{.status.readyReplicas}/{.spec.replicas}' 2>/dev/null)
    echo "  consommateur : $DEPLOY ($repl répliques prêtes)"
    if [ -n "$ms" ]; then
        echo "  temps de service : $ms ms de retard par échange avec la base, ≈ $((ms * 5)) ms par message"
    elif [ "$panne" = en_cours ]; then
        echo "  temps de service : celui de la panne consumer-slowdown ($PANNE_VUE), qui remplace le réglage le temps de la panne"
    else
        echo "  temps de service : aucun   (pas de retard — 6 ms par message, marge × 150)"
    fi
    # Réplique par réplique ; une absence n'est qu'affichée ici (verifier la juge).
    if [ "${1:-}" != sans_couverture ] && { [ -n "$ms" ] || [ "$panne" != absente ]; }; then
        local c=0; couverture || c=$?
        [ "$c" -ne 1 ] || echo "  → $(marche_a_suivre)"
    fi
    declencheur_present && echo "  ATTENTION : un sommeil dans la base est encore en place ($DECLENCHEUR) — dimensionner le retire"
    echo "  prefetch : ${pf:-250 (défaut du courtier)}"
    return 0
}

# verifier [malgre_panne] — lecture seule ; rend le code de couverture et dit quoi faire.
verifier_app() {
    local code=0
    couverture "${1:-}" || code=$?
    case "$code" in
        0) ok "chaque réplique en marche de $DEPLOY porte le retard" ;;
        3) say "rien à reposer pendant la panne : « panne.sh retirer » (ou son minuteur) repose le réglage" ;;
        *) warn "$(marche_a_suivre)"; code=1 ;;
    esac
    return "$code"
}

# reposer ne touche à rien pendant une panne consumer-slowdown, ni quand on ne peut pas
# savoir s'il y en a une. Une panne en cours rend 3, comme verifier.
refuser_si_panne() {
    etat_panne
    case "$PANNE_ETAT" in
        en_cours)    warn "panne consumer-slowdown en cours ($PANNE_VUE) : elle remplace le réglage, rien n'est touché — « panne.sh retirer » le reposera"
                     exit 3 ;;
        arretee)     fail "$PANNE_VUE arrêtée mais pas retirée, rien n'est touché :  panne.sh retirer   (il repose le réglage)" ;;
        injoignable) fail "l'API Kubernetes ne répond pas, rien n'est touché :  kubectl get networkchaos -n $NS" ;;
    esac
}

# reposer — recrée l'objet à sa valeur actuelle pour couvrir les répliques
# nées depuis sa pose. Supprimer puis recréer laisse quelques secondes sans
# retard ; jamais pendant une panne consumer-slowdown, qui a remplacé le réglage.
reposer_app() {
    refuser_si_panne
    local ms c=0; ms=$(lire_nc "$OBJET" '{.spec.delay.latency}') || c=$?
    [ "$c" -ne 2 ] || fail "l'API Kubernetes ne répond pas, rien n'est touché :  kubectl get networkchaos -n $NS"
    ms=$(tr -d 'ms' <<< "$ms")
    [ -n "$ms" ] || fail "aucun réglage $OBJET à reposer — à poser :  consommateur.sh dimensionner --retard 140"
    case "$ms" in *[!0-9]*) fail "valeur du réglage illisible ($ms) :  kubectl get networkchaos $OBJET -n $NS -o yaml" ;; esac
    local pf; pf=$(prefetch_actuel)
    refuser_si_panne   # relu juste avant de toucher : une panne a pu commencer entre-temps
    say "Nouvelle pose du retard de $ms ms sur les répliques en marche (prefetch inchangé, aucun redémarrage)…"
    if ! poser_retard "$ms"; then
        c=0; lire_nc "$OBJET" '{.metadata.name}' >/dev/null || c=$?
        if [ "$c" -eq 0 ]; then
            warn "Chaos Mesh n'a pas confirmé en 60 s :  kubectl describe networkchaos $OBJET -n $NS"
        else
            # La valeur n'est plus nulle part ailleurs que dans ce message et le registre.
            consigner reposer "$ms" "$pf" ECHEC
            fail "$OBJET supprimé mais PAS recréé (valeur perdue : $ms ms) — à reposer :  consommateur.sh dimensionner --retard $ms${pf:+ --prefetch $pf}"
        fi
    fi
    local code=0
    verifier_app || code=$?
    if [ "$code" -eq 0 ]; then consigner reposer "$ms" "$pf" ok; else consigner reposer "$ms" "$pf" ECHEC; fi
    return "$code"
}

retirer_app() {
    say "Retrait du retard…"
    kubectl delete networkchaos "$OBJET" -n "$NS" --ignore-not-found --timeout=90s >/dev/null 2>&1 \
        && ok "retard retiré" || warn "l'objet $OBJET résiste"
    declencheur_present && { sql "DROP TRIGGER IF EXISTS $DECLENCHEUR;" >/dev/null; ok "sommeil dans la base retiré"; }
    if [ -n "$(prefetch_actuel)" ]; then
        say "Retrait du prefetch (redémarrage roulant)…"
        kubectl set env deploy/"$DEPLOY" -n "$NS" "$ENV_PREFETCH-" >/dev/null \
            && { kubectl rollout status deploy/"$DEPLOY" -n "$NS" --timeout=600s >/dev/null 2>&1 || repliques_pretes; } \
            && ok "prefetch retiré" || warn "le prefetch n'a pas pu être retiré"
    fi
    consigner retirer "" "" ok
    echo
    etat_app
}

case "${1:-etat}" in
    dimensionner) shift; dimensionner_app "$@" ;;
    etat)         etat_app ;;
    verifier)     verifier_app ;;
    reposer)      reposer_app ;;
    retirer)      retirer_app ;;
    *) echo "Usage: $0 {dimensionner --retard <ms> [--prefetch <n>]|etat|verifier|reposer|retirer}" >&2; exit 2 ;;
esac
