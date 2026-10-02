#!/bin/bash
# ==============================================================================
#  collecte-tmux.sh — les sessions tmux de la collecte : le gardien, et une vue
#  en lecture seule pour suivre sans rien risquer
# ==============================================================================
#
#  CE QUE FAIT CE SCRIPT
#
#  Il crée, si elles manquent, deux sessions tmux sur vms0 :
#    - « garde », sur un serveur tmux À PART (tmux -L garde) : une boucle qui
#      lance garde.py (le gardien) et le relance 10 s après chaque sortie ; sa
#      sortie va aussi dans <GARDE_DOSSIER>/sortie-tmux.log. Le verrou de garde.py
#      (garde.verrou) empêche deux gardiens : tant qu'un autre le tient, la boucle
#      attend (nouvel essai toutes les 60 s) et ne le note qu'une fois ;
#    - « collecte », sur le serveur tmux habituel : UNE fenêtre en 3 volets, à
#      regarder en lecture seule :
#          en haut     ./suivi.sh --boucle 30      (l'état en un écran, ~64 % de la hauteur)
#          au milieu   tail -F alertes.txt          (les alertes du gardien)
#          en bas      ./suivi.sh --journal         (le journal du pilote en cours)
#      remain-on-exit : un volet dont le programme s'arrête reste affiché, lisible.
#      Les proportions sont rétablies à chaque changement de taille (un client
#      qui s'attache avec un autre terminal), sinon tmux écrase les volets du bas.
#  Le pilote (campagne.sh, plus tard serie.sh) tourne dans SA PROPRE session :
#  ce script n'y touche pas.
#
#  POURQUOI
#
#  On veut suivre la collecte de 7 jours à tout moment sans risque de rien
#  casser :  tmux attach -r -t =collecte  (lecture seule ; le « = » impose le nom
#  exact : sans lui, tmux prendrait une session « collecte-vieille » si
#  « collecte » manquait). En lecture seule, tmux 3.4 n'accepte que les touches
#  liées à detach-client et switch-client : on ne peut pas changer de fenêtre,
#  d'où UNE fenêtre découpée en 3 volets.
#  Le gardien est sur un AUTRE serveur tmux : depuis « collecte », Ctrl-b ( ou )
#  ne peut pas l'atteindre, même attaché sans -r par erreur. Dans sa propre
#  session, Ctrl-C ne l'arrête pas non plus (il tourne hors du groupe de
#  processus du volet, et la boucle ignore Ctrl-C) ; Ctrl-b x ou & fermerait le
#  volet après une question y/n de tmux, et arrêterait alors proprement le
#  gardien. Pour l'arrêter : ./collecte-tmux.sh arreter-garde, jamais autrement.
#  Attention : attaché à « collecte » SANS -r, Ctrl-b ( / ) mène aux autres
#  sessions du serveur habituel (celle du pilote, les vieilles), où l'on peut
#  taper. Toujours -r.
#  Une liaison de touche vers « switch-client -r » ferait sortir de la lecture
#  seule : le script vérifie qu'il n'y en a pas.
#
#  Relancé, le script ne crée rien en double et ne tue rien qui tourne. Il ne
#  touche JAMAIS aux autres sessions tmux (vms0 en garde 9 vieilles, du 10 au
#  29/09) : « etat » les liste, à fermer à la main si elles sont inutiles.
#  Les sessions qu'il crée portent une marque (option @collecte_tmux) : une
#  session « garde » ou « collecte » qui ne la porte pas n'est ni reprise ni fermée.
#
#  Usage (sur vms0, dans le dépôt) :
#      ./collecte-tmux.sh demarrer           gardien SANS gestes (mode PROPOSE : essais K3)
#      ./collecte-tmux.sh demarrer --agir    gardien AVEC les gestes du niveau 1 (essai de
#                                            24 h, collecte)
#      ./collecte-tmux.sh etat               les sessions, le gardien (avec ou sans --agir),
#                                            l'âge de garde.tsv, les vieilles sessions
#      ./collecte-tmux.sh arreter-vue        ferme SEULEMENT la session « collecte »
#      ./collecte-tmux.sh arreter-garde      ferme SEULEMENT la session « garde » : signal
#                                            d'arrêt au gardien, qui finit sa minute (jusqu'à
#                                            2 min) ; si un pilote campagne.sh vit (ou si on
#                                            ne peut pas le savoir), demande « oui »
#  Pour regarder :   tmux attach -r -t =collecte       Pour partir :  Ctrl-b puis d
#  (En lecture seule, Ctrl-b ( et Ctrl-b ) passent aux autres sessions du serveur
#  habituel, toujours en lecture seule ; Ctrl-b d pour partir.)
#  La sortie du gardien :  tmux -L garde attach -r -t =garde   (ou sortie-tmux.log)
#  Pour changer de mode (PROPOSE → AGIR) : arreter-garde, puis demarrer --agir.
#
#  À LA REMISE À NEUF (K4) — les gestes à taper, dans l'ordre :
#    1. sur vms0 : pour que tmux et le gardien survivent à la déconnexion :
#           sudo loginctl enable-linger ubuntu
#       vérifier :
#           loginctl show-user ubuntu -p Linger          → Linger=yes
#    2. sur vms0 :
#       2a. aller dans le dépôt :
#           cd ~/autodeploy_k8s-plateforme
#       2b. pendant les essais K3 : le gardien SANS gestes (mode PROPOSE) :
#           ./collecte-tmux.sh demarrer
#       2c. avant l'essai de 24 h et la collecte : passer en mode AGIR.
#           # arrête le gardien PROPOSE (il finit sa minute : jusqu'à 2 min d'attente)
#           ./collecte-tmux.sh arreter-garde
#           # le relance AVEC les gestes du niveau 1
#           ./collecte-tmux.sh demarrer --agir
#       vérifier :
#           ./collecte-tmux.sh etat        → « garde.py tourne … AVEC --agir », garde.tsv récent
#           tmux attach -r -t =collecte    → la vue (Ctrl-b puis d pour partir)
#       2d. si vms0 redémarre : RIEN ne relance les sessions tout seul (linger garde
#           tmux en vie après la déconnexion, il ne le fait pas repartir). Retaper :
#           cd ~/autodeploy_k8s-plateforme && ./collecte-tmux.sh demarrer --agir
#    3. sur le master : la veille extérieure du gardien (apps/garde_veille_master.sh) :
#       3a. vérifier que le script est sur le master (sa copie date du dernier
#           déploiement : PROCEDURE.md, « Deux copies des scripts ») :
#           ls ~/autodeploy/apps/garde_veille_master.sh
#           s'il manque : depuis vms0, dans le dépôt :  ./deploy.sh --push-scripts
#       3b. crontab -e        et ajouter la ligne :
#           */5 * * * * bash $HOME/autodeploy/apps/garde_veille_master.sh >> $HOME/garde_veille.log 2>&1
#       vérifier :
#           crontab -l | grep garde_veille                          → la ligne est là
#           bash ~/autodeploy/apps/garde_veille_master.sh --etat
#                → « OK  gardien vivant » et « incident en cours : aucun »
#           ls -l ~/garde_veille.log      → après 5 min : présent ; vide = aucune erreur
#       pour relire plus tard les alertes de la veille, depuis vms0 :
#           ssh master cat ~/alertes-garde.txt
#
#  Variables reconnues :
#      GARDE_DOSSIER          (défaut: ~/journaux-hors-campagne/garde) le dossier du gardien
#      COLLECTE_TMUX_SOCKET   (défaut: vide = le serveur tmux habituel) le serveur de la vue
#                             (tmux -L <nom>) : pour les essais ; le gardien est alors sur
#                             « <nom>-garde » (sinon sur « garde »)
#      COLLECTE_ARRET_MAX     (défaut: 150) secondes d'attente de l'arrêt du gardien
#      COLLECTE_RELANCE       (défaut: 10)  secondes avant de relancer garde.py (essais)
#      COLLECTE_ATTENTE_VERROU (défaut: 60) secondes entre deux essais quand un autre
#                             gardien tient le verrou (essais)
#  Les variables GARDE_* et SUIVI_* du shell qui lance « demarrer » sont passées aux
#  sessions (tmux ne les transmet pas de lui-même à un serveur déjà démarré).
# ==============================================================================
set -uo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GARDE_DOSSIER="${GARDE_DOSSIER:-$HOME/journaux-hors-campagne/garde}"
SOCKET="${COLLECTE_TMUX_SOCKET:-}"
if [ -n "$SOCKET" ]; then SOCKET_GARDE="$SOCKET-garde"; else SOCKET_GARDE="garde"; fi
S_GARDE="garde"
S_VUE="collecte"
MARQUE="@collecte_tmux"
HAUT_PCT=64     # part de la hauteur pour l'état (volet du haut)
BAS_PCT=16      # part pour le journal (volet du bas) ; le milieu a le reste

say()  { echo "  [collecte-tmux] $*"; }
ok()   { echo "  [collecte-tmux] OK  $*"; }
warn() { echo "  [collecte-tmux] ATTENTION: $*" >&2; }
fail() { echo "  [collecte-tmux] ERREUR: $*" >&2; exit 1; }

# tmux, sur le serveur de la vue (le serveur habituel, ou celui des essais) ;
# TG : sur le serveur du gardien.
T() {
    if [ -n "$SOCKET" ]; then tmux -L "$SOCKET" "$@"; else tmux "$@"; fi
}
TG() { tmux -L "$SOCKET_GARDE" "$@"; }
tmux_affiche() {   # la commande tmux à taper pour regarder la vue
    if [ -n "$SOCKET" ]; then echo "tmux -L $SOCKET"; else echo "tmux"; fi
}

# L'identifiant ($n) de la session qui porte EXACTEMENT ce nom (vide si aucune).
# <T ou TG> <nom>
session_id() {
    "$1" list-sessions -F '#{session_id}	#{session_name}' 2>/dev/null | awk -F'\t' -v n="$2" '$2 == n { print $1 }'
}
est_a_nous() {     # <T ou TG> <id> : la session a-t-elle été créée par ce lanceur ?
    [ "$("$1" show-options -t "$2" -qv "$MARQUE" 2>/dev/null)" = "1" ]
}

# Les processus donnés et tous leurs descendants : « pid<TAB>ligne de commande ».
arbre() {
    ps -e -o pid=,ppid=,args= | awk -v racines="$*" '
        { pid = $1; ppid = $2; $1 = ""; $2 = ""; sub(/^ +/, ""); args[pid] = $0; enfants[ppid] = enfants[ppid] " " pid }
        END {
            n = split(racines, file, " ")
            for (i = 1; i <= n; i++) {
                p = file[i]
                if (p in args) print p "\t" args[p]
                m = split(enfants[p], e, " ")
                for (k = 1; k <= m; k++) file[++n] = e[k]
            }
        }'
}
pids_volets() { "$1" list-panes -s -t "$2" -F '#{pane_pid}' 2>/dev/null | tr '\n' ' '; }   # <T ou TG> <id>

# Le gardien (garde.py, hors sous-processus de retrait) qui tourne dans la session « garde ».
gardien_de() {
    arbre $(pids_volets TG "$1") | awk -F'\t' '$2 ~ /garde\.py/ && $2 !~ /--geste-retirer/ && $2 !~ /_boucle-garde/'
}

# Qui tient le verrou du gardien ? « pid<TAB>commande » s'il vit encore, rien sinon.
tient_le_verrou() {
    local f="$GARDE_DOSSIER/garde.verrou" pid
    pid=$(head -c 32 "$f" 2>/dev/null | tr -dc '0-9')
    [ -n "$pid" ] && [ -r "/proc/$pid/cmdline" ] || return 0
    local cmd; cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null)
    case "$cmd" in *garde.py*) printf '%s\t%s\n' "$pid" "$cmd" ;; esac
}

# Les pilotes vivants, cherchés comme le gardien les cherche (suivi.py --pilotes).
# Code de retour non nul : la recherche a échoué (on ne sait pas s'il y en a un).
pilotes_vivants() {
    PYTHONDONTWRITEBYTECODE=1 python3 "$ICI/suivi.py" --pilotes 2>/dev/null
}
texte_pilotes() {  # « nom<TAB>pid » par ligne → « nom (pid N), nom (pid M) »
    awk -F'\t' '{ printf "%s%s (pid %s)", (NR > 1 ? ", " : ""), $1, $2 }'
}

# Une liaison de touche vers « switch-client -r » ferait sortir un client de la
# lecture seule. Les tables de touches sont communes à tout le serveur tmux de la
# vue. Seuls les drapeaux sans argument (-E -l -n -p -Z, et -r) peuvent être
# collés à -r : « -Tprefix » ou « -c … » ne comptent pas.
verifier_touches() {
    local l
    l=$(T list-keys 2>/dev/null | grep -E '(switch-client|switchc)[^;{}]*[[:space:]]-[ElnpZ]*r[ElnpZ]*([[:space:]]|$)')
    if [ -n "$l" ]; then
        warn "une touche appelle « switch-client -r », qui fait SORTIR de la lecture seule"
        warn "(tables de touches communes à tout le serveur tmux, donc aussi à « $S_VUE ») :"
        printf '%s\n' "$l" | sed 's/^/        /' >&2
        warn "la retirer de la config tmux (~/.tmux.conf) : unbind-key <touche>"
        return 1
    fi
    ok "aucune touche n'appelle « switch-client -r » : « attach -r » reste en lecture seule"
}

# Les variables passées aux sessions : un serveur tmux déjà démarré ne voit pas
# l'environnement du shell qui lance « demarrer ».
ENV_ARGS=()
preparer_env() {
    ENV_ARGS=(-e "PATH=$PATH" -e "GARDE_DOSSIER=$GARDE_DOSSIER")
    [ -z "${LANG:-}" ] || ENV_ARGS+=(-e "LANG=$LANG")
    local v
    for v in $(compgen -e); do
        case "$v" in
            GARDE_DOSSIER) ;;
            GARDE_*|SUIVI_*|COLLECTE_RELANCE|COLLECTE_ATTENTE_VERROU) ENV_ARGS+=(-e "$v=${!v}") ;;
        esac
    done
}

# Une session déjà là lit-elle le même dossier du gardien que celui de ce shell ?
# <T ou TG> <id> <nom>
comparer_dossier() {
    local d
    d=$("$1" show-environment -t "$2" GARDE_DOSSIER 2>/dev/null) || return 0
    d="${d#GARDE_DOSSIER=}"
    if [ -n "$d" ] && [ "$d" != "$GARDE_DOSSIER" ]; then
        warn "la session « $3 » déjà là utilise GARDE_DOSSIER=$d"
        warn "mais ce shell dit GARDE_DOSSIER=$GARDE_DOSSIER : la vue et le gardien ne liraient pas les mêmes fichiers"
        warn "(pour changer : arreter-vue / arreter-garde, puis demarrer avec le bon GARDE_DOSSIER)"
    fi
}

# ------------------------------------------------------------------ la boucle du gardien
# Lancée par « demarrer » DANS la session « garde » : c'est
#     while :; do python3 garde.py [--agir]; sleep 10; done
# avec quelques soins de plus :
#   - la sortie va aussi dans un journal (sortie-tmux.log) ;
#   - garde.py tourne dans sa propre session Unix (setsid) : un Ctrl-C tapé dans
#     le volet ne l'atteint pas ; la boucle, elle, ignore Ctrl-C (INT) ;
#   - un TERM ou un HUP reçu par la boucle (arreter-garde, volet fermé) est passé
#     au gardien, qui finit sa minute ; la boucle s'arrête alors sans relancer ;
#   - si un autre gardien tient le verrou, garde.py n'est pas lancé : la boucle
#     le note UNE fois, puis réessaie toutes les 60 s sans rien écrire (sinon :
#     une ligne toutes les 10 s, 26 000 par jour).
boucle_garde() {
    local args=()
    case "${1:-}" in
        --agir) args=(--agir) ;;
        "") ;;
        *) fail "_boucle-garde : option inconnue « $1 »" ;;
    esac
    mkdir -p "$GARDE_DOSSIER" || fail "impossible de créer $GARDE_DOSSIER"
    local journal="$GARDE_DOSSIER/sortie-tmux.log" verrou="$GARDE_DOSSIER/garde.verrou"
    local relance="${COLLECTE_RELANCE:-10}" attente_verrou="${COLLECTE_ATTENTE_VERROU:-60}"
    local arret="" enfant="" code=0 pause bloque="" lanceur=()
    command -v setsid >/dev/null 2>&1 && lanceur=(setsid -w)
    trap '' INT    # hérité par tee et sleep ; garde.py, lui, est hors du groupe du volet
    trap 'arret=1; [ -z "$enfant" ] || kill -TERM "$enfant" 2>/dev/null' TERM HUP
    noter() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)  [boucle] $*" | tee -a "$journal"; }
    say "boucle du gardien : python3 garde.py ${args[*]} — relancé ${relance} s après chaque sortie"
    say "sortie aussi dans $journal ; pour arrêter : ./collecte-tmux.sh arreter-garde"
    while [ -z "$arret" ]; do
        # Le verrou est-il libre ? (flock -n le prend et le rend aussitôt.)
        if command -v flock >/dev/null 2>&1 && ! flock -n "$verrou" true 2>/dev/null; then
            if [ -z "$bloque" ]; then
                local v; v=$(tient_le_verrou)
                noter "un autre gardien tient le verrou${v:+ (pid ${v%%$'\t'*})} : garde.py n'est pas lancé ;" \
                      "nouvel essai toutes les ${attente_verrou} s, sans le redire"
                bloque=1
            fi
            pause="$attente_verrou"
        else
            [ -z "$bloque" ] || noter "le verrou est libre : départ du gardien"
            bloque=""
            noter "départ : python3 garde.py ${args[*]}"
            ( trap '' HUP; exec "${lanceur[@]}" python3 -u "$ICI/garde.py" "${args[@]}" ) \
                > >(trap '' HUP; exec tee -a --output-error=warn "$journal") 2>&1 &
            enfant=$!
            wait "$enfant"; code=$?
            while kill -0 "$enfant" 2>/dev/null; do wait "$enfant"; code=$?; done
            enfant=""
            if [ "$code" = 3 ]; then
                noter "garde.py sorti (code 3 : une autre garde tourne déjà) — nouvel essai dans ${attente_verrou} s"
                pause="$attente_verrou"
            else
                noter "garde.py sorti (code $code)"
                pause="$relance"
            fi
        fi
        [ -z "$arret" ] || break
        sleep "$pause" & enfant=$!
        wait "$enfant" 2>/dev/null
        enfant=""
    done
    noter "arrêtée (signal reçu) : pas de relance"
}

# ------------------------------------------------------------------ demarrer
creer_garde() {   # <--agir ou vide>
    local sortie sid
    local v; v=$(tient_le_verrou)
    if [ -n "$v" ]; then
        warn "un gardien tient déjà le verrou (pid ${v%%$'\t'*}) hors de cette session :"
        warn "la boucle attendra qu'il le rende (nouvel essai toutes les 60 s) sans lancer de second gardien"
    fi
    sortie=$(TG new-session -d -s "$S_GARDE" -n garde -c "$ICI" "${ENV_ARGS[@]}" -P -F '#{session_id}' \
        bash "$ICI/collecte-tmux.sh" _boucle-garde $1) || fail "tmux n'a pas créé la session « $S_GARDE »"
    sid="$sortie"
    TG set-option -t "$sid" "$MARQUE" 1
    # Quand la boucle s'arrête (arreter-garde), la session doit se fermer d'elle-même,
    # même si la config tmux pose remain-on-exit partout.
    TG set-option -w -t "$sid" remain-on-exit off
    if [ -n "$1" ]; then
        ok "session « $S_GARDE » créée (serveur tmux -L $SOCKET_GARDE) : garde.py --agir (mode AGIR : gestes du niveau 1)"
    else
        ok "session « $S_GARDE » créée (serveur tmux -L $SOCKET_GARDE) : garde.py sans --agir (mode PROPOSE : aucun geste)"
    fi
}

creer_vue() {
    local sortie sid haut milieu bas
    # remain-on-exit est posé dans la MÊME commande tmux que la création : un
    # volet qui s'arrêterait tout de suite reste quand même affiché.
    sortie=$(T new-session -d -s "$S_VUE" -n suivi -c "$ICI" -x 110 -y 50 "${ENV_ARGS[@]}" \
        -P -F '#{session_id} #{pane_id}' bash "$ICI/suivi.sh" --boucle 30 \; set-option -w remain-on-exit on) \
        || fail "tmux n'a pas créé la session « $S_VUE »"
    sid="${sortie%% *}"; haut="${sortie##* }"
    T set-option -t "$sid" "$MARQUE" 1
    T set-option -w -t "$haut" remain-on-exit on
    milieu=$(T split-window -v -d -t "$haut" -l $((100 - HAUT_PCT))% -c "$ICI" "${ENV_ARGS[@]}" -P -F '#{pane_id}' \
        tail -n 30 -F "$GARDE_DOSSIER/alertes.txt") || warn "volet du milieu (alertes) non créé"
    bas=$(T split-window -v -d -t "${milieu:-$haut}" -l 50% -c "$ICI" "${ENV_ARGS[@]}" -P -F '#{pane_id}' \
        bash "$ICI/suivi.sh" --journal) || warn "volet du bas (journal) non créé"
    T select-pane -t "$haut" -T "état (suivi.sh --boucle 30)"
    [ -z "$milieu" ] || T select-pane -t "$milieu" -T "alertes (tail -F alertes.txt)"
    [ -z "$bas" ] || T select-pane -t "$bas" -T "journal du pilote (suivi.sh --journal)"
    T set-option -w -t "$haut" pane-border-status top
    T set-option -w -t "$haut" pane-border-format ' #{pane_title} '
    # Les proportions : tmux, quand la fenêtre change de taille (un client qui
    # s'attache), prend ou donne les lignes surtout aux volets du bas. Ce crochet,
    # posé sur CETTE fenêtre seulement, rétablit ~64 % / 20 % / 16 %.
    if [ -n "$bas" ]; then
        local regle="resize-pane -t $haut -y ${HAUT_PCT}% ; resize-pane -t $bas -y ${BAS_PCT}%"
        T set-hook -w -t "$haut" window-resized "$regle"
        T resize-pane -t "$haut" -y "${HAUT_PCT}%"; T resize-pane -t "$bas" -y "${BAS_PCT}%"
    fi
    T select-pane -t "$haut"
    ok "session « $S_VUE » créée : 1 fenêtre, 3 volets (état, alertes, journal du pilote)"
}

relancer_volets_morts() {   # <id> : relance les volets ARRÊTÉS (jamais un volet vivant)
    local p mort n=0
    while read -r p mort; do
        [ "$mort" = 1 ] || continue
        T respawn-pane -t "$p" && n=$((n + 1))
    done < <(T list-panes -s -t "$1" -F '#{pane_id} #{pane_dead}' 2>/dev/null)
    [ "$n" = 0 ] || ok "$n volet(s) arrêté(s) relancé(s) dans « $S_VUE »"
}

demarrer() {
    local agir=""
    case "${1:-}" in
        --agir) agir="--agir" ;;
        "") ;;
        *) fail "demarrer : option inconnue « $1 » (seule --agir est admise)" ;;
    esac
    [ $# -le 1 ] || fail "demarrer : trop d'arguments"
    command -v tmux >/dev/null 2>&1 || fail "tmux introuvable"
    command -v python3 >/dev/null 2>&1 || fail "python3 introuvable"
    [ -f "$ICI/garde.py" ] || fail "garde.py manque dans $ICI"
    [ -f "$ICI/suivi.sh" ] && [ -f "$ICI/suivi.py" ] || fail "suivi.sh ou suivi.py manque dans $ICI"
    mkdir -p "$GARDE_DOSSIER" || fail "impossible de créer $GARDE_DOSSIER"
    if [ -z "${GARDE_DEPOT:-}" ] && [ "$ICI" != "$HOME/autodeploy_k8s-plateforme" ]; then
        warn "garde.py lira le dépôt ~/autodeploy_k8s-plateforme (GARDE_DEPOT non posé), suivi.sh lit $ICI"
    fi
    preparer_env

    local sid g
    sid=$(session_id TG "$S_GARDE")
    if [ -z "$sid" ]; then
        creer_garde "$agir"
    elif ! est_a_nous TG "$sid"; then
        warn "une session « $S_GARDE » existe (tmux -L $SOCKET_GARDE) mais n'a pas été créée par ce lanceur :"
        warn "laissée telle quelle, aucun gardien n'est lancé (la renommer ou la fermer à la main, puis relancer)"
    else
        comparer_dossier TG "$sid" "$S_GARDE"
        g=$(gardien_de "$sid")
        if [ -z "$g" ]; then
            ok "session « $S_GARDE » déjà là (garde.py entre deux tours de boucle) : rien n'est relancé"
        else
            ok "session « $S_GARDE » déjà là, garde.py tourne (pid ${g%%$'\t'*}) : rien n'est relancé"
            case "$g" in
                *--agir*) [ -n "$agir" ] || warn "il tourne AVEC --agir ; pour PROPOSE : arreter-garde, puis demarrer" ;;
                *) [ -z "$agir" ] || warn "il tourne SANS --agir ; pour AGIR : arreter-garde, puis demarrer --agir" ;;
            esac
        fi
    fi

    sid=$(session_id T "$S_VUE")
    if [ -z "$sid" ]; then
        creer_vue
    elif ! est_a_nous T "$sid"; then
        warn "une session « $S_VUE » existe mais n'a pas été créée par ce lanceur : laissée telle quelle"
    else
        ok "session « $S_VUE » déjà là : rien n'est recréé"
        comparer_dossier T "$sid" "$S_VUE"
        relancer_volets_morts "$sid"
    fi

    verifier_touches
    echo
    say "Pour regarder (lecture seule, sans risque) :   $(tmux_affiche) attach -r -t =$S_VUE"
    say "Pour partir sans rien arrêter :                 Ctrl-b puis d"
    say "Pour voir l'état :                              ./collecte-tmux.sh etat"
}

# ------------------------------------------------------------------ etat
etat() {
    command -v tmux >/dev/null 2>&1 || fail "tmux introuvable"
    local serveur="serveur tmux habituel"; [ -z "$SOCKET" ] || serveur="serveur tmux « -L $SOCKET »"
    local sid g p code_p
    p=$(pilotes_vivants); code_p=$?
    sid=$(session_id TG "$S_GARDE")
    say "gardien (serveur tmux « -L $SOCKET_GARDE ») :"
    if [ -z "$sid" ]; then
        warn "  $S_GARDE      : ABSENTE — aucun gardien lancé (./collecte-tmux.sh demarrer [--agir])"
        [ -z "$p" ] || warn "  !!! un PILOTE tourne SANS GARDIEN : $(printf '%s\n' "$p" | texte_pilotes) !!!"
    elif ! est_a_nous TG "$sid"; then
        warn "  $S_GARDE      : présente mais PAS créée par ce lanceur (laissée telle quelle)"
    else
        g=$(gardien_de "$sid")
        if [ -z "$g" ]; then
            warn "  $S_GARDE      : présente, mais garde.py ne tourne pas en ce moment (entre deux essais : voir sortie-tmux.log)"
        else
            case "$g" in
                *--agir*) say "  $S_GARDE      : garde.py tourne (pid ${g%%$'\t'*}) AVEC --agir (mode AGIR : gestes du niveau 1)" ;;
                *)        say "  $S_GARDE      : garde.py tourne (pid ${g%%$'\t'*}) SANS --agir (mode PROPOSE : aucun geste)" ;;
            esac
        fi
    fi
    say "vue ($serveur) :"
    if ! T list-sessions >/dev/null 2>&1; then
        say "  aucune session (le serveur tmux ne tourne pas)"
    fi
    sid=$(session_id T "$S_VUE")
    if [ -z "$sid" ]; then
        say "  $S_VUE   : absente"
    elif ! est_a_nous T "$sid"; then
        warn "  $S_VUE   : présente mais PAS créée par ce lanceur (laissée telle quelle)"
    else
        say "  $S_VUE   : $(T list-windows -t "$sid" 2>/dev/null | wc -l) fenêtre(s), $(T list-panes -s -t "$sid" 2>/dev/null | wc -l) volet(s) :"
        T list-panes -s -t "$sid" -F '      #{?pane_dead,ARRÊTÉ (code #{pane_dead_status}),vivant} : #{pane_start_command}' 2>/dev/null
        T list-clients -t "$sid" -F '      client #{client_tty}#{?client_readonly, (lecture seule), (LECTURE-ÉCRITURE)}' 2>/dev/null
    fi
    # Les autres sessions (des deux serveurs) : listées, jamais fermées.
    local autres
    autres=$( { T list-sessions -F 'T	#{session_id}	#{session_name}	#{session_created}	#{session_windows}	#{session_attached}' 2>/dev/null \
                    | awk -F'\t' -v b="$S_VUE" '$3 != b'
                TG list-sessions -F 'TG	#{session_id}	#{session_name}	#{session_created}	#{session_windows}	#{session_attached}' 2>/dev/null \
                    | awk -F'\t' -v a="$S_GARDE" '$3 != a'; } )
    if [ -n "$autres" ]; then
        say "  autres sessions — anciennes, à fermer à la main si inutiles ($(tmux_affiche) kill-session -t '=<nom>') :"
        local srv id nom cree fen att note quand
        while IFS=$'\t' read -r srv id nom cree fen att; do
            note=""
            if arbre $(pids_volets "$srv" "$id") | awk -F'\t' '$2 ~ /campagne\.sh|serie\.sh/' | grep -q .; then
                note="   <- un PILOTE y tourne : NE PAS fermer"
            fi
            quand=$(date -u -d "@$cree" '+%d/%m %H:%M UTC' 2>/dev/null || echo "?")
            [ "$srv" = T ] || note="$note   (serveur tmux -L $SOCKET_GARDE)"
            say "      $nom (créée le $quand, $fen fenêtre(s)$([ "$att" -gt 0 ] 2>/dev/null && echo ", attachée"))$note"
        done <<< "$autres"
    fi
    local v; v=$(tient_le_verrou)
    if [ -n "$v" ]; then
        say "verrou du gardien : tenu par le pid ${v%%$'\t'*} (${v#*$'\t'})"
    else
        say "verrou du gardien : libre (aucun garde.py vivant ne le tient)"
    fi
    say "garde.tsv : $(PYTHONDONTWRITEBYTECODE=1 python3 "$ICI/suivi.py" --age-garde 2>&1)"
    if [ "$code_p" != 0 ]; then
        warn "pilote : recherche impossible (suivi.py --pilotes, code $code_p)"
    elif [ -n "$p" ]; then
        say "pilote(s) vivant(s) : $(printf '%s\n' "$p" | texte_pilotes)"
    else
        say "pilote : aucun campagne.sh vivant"
    fi
    verifier_touches
}

# ------------------------------------------------------------------ arreter
arreter_vue() {
    local sid; sid=$(session_id T "$S_VUE")
    if [ -z "$sid" ]; then ok "session « $S_VUE » déjà absente : rien à faire"; return 0; fi
    est_a_nous T "$sid" || fail "la session « $S_VUE » n'a pas été créée par ce lanceur : rien n'est fermé"
    T kill-session -t "$sid" || fail "tmux n'a pas fermé « $S_VUE »"
    ok "session « $S_VUE » fermée (le gardien et le pilote continuent)"
}

arreter_garde() {
    local sid; sid=$(session_id TG "$S_GARDE")
    if [ -z "$sid" ]; then ok "session « $S_GARDE » déjà absente : rien à faire"; return 0; fi
    est_a_nous TG "$sid" || fail "la session « $S_GARDE » n'a pas été créée par ce lanceur : rien n'est fermé"
    local p code_p demander=""
    p=$(pilotes_vivants); code_p=$?
    if [ "$code_p" != 0 ]; then
        warn "impossible de savoir si un pilote campagne.sh tourne (suivi.py --pilotes, code $code_p)"
        demander=1
    elif [ -n "$p" ]; then
        warn "un pilote campagne.sh est VIVANT : $(printf '%s\n' "$p" | texte_pilotes)"
        demander=1
    fi
    if [ -n "$demander" ]; then
        warn "sans gardien, la collecte n'est plus surveillée (ni minutes MALADE, ni gestes, ni pause)"
        local rep=""
        printf '  [collecte-tmux] Taper « oui » pour arrêter quand même le gardien : '
        read -r rep || rep=""
        echo
        [ "$rep" = "oui" ] || { say "réponse « $rep » : rien n'est arrêté"; return 1; }
    fi
    # Signal d'arrêt (TERM) à la boucle : elle le passe au gardien, qui finit sa
    # minute ; la session se ferme d'elle-même. kill-session seulement en dernier recours.
    local boucle; boucle=$(pids_volets TG "$sid")
    local max="${COLLECTE_ARRET_MAX:-150}" i=0
    say "signal d'arrêt (TERM) envoyé à la boucle du gardien (pid ${boucle% }) :"
    say "garde.py finit sa minute, puis s'arrête — jusqu'à 2 min d'attente…"
    kill -TERM $boucle 2>/dev/null
    while [ -n "$(session_id TG "$S_GARDE")" ] && [ "$i" -lt $((max * 5)) ]; do sleep 0.2; i=$((i + 1)); done
    if [ -n "$(session_id TG "$S_GARDE")" ]; then
        warn "le gardien ne s'est pas arrêté en $max s : session fermée de force (kill-session)"
        TG kill-session -t "$sid"
    fi
    ok "session « $S_GARDE » fermée : plus de gardien (relancer : ./collecte-tmux.sh demarrer [--agir])"
}

# ------------------------------------------------------------------ main
case "${1:-}" in
    demarrer)       shift; demarrer "$@" ;;
    etat)           etat ;;
    arreter-vue)    arreter_vue ;;
    arreter-garde)  arreter_garde ;;
    _boucle-garde)  shift; boucle_garde "$@" ;;
    -h|--help)      awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0" ;;
    *)              echo "Usage : $0 {demarrer [--agir]|etat|arreter-vue|arreter-garde}   (-h pour l'aide)" >&2; exit 2 ;;
esac
