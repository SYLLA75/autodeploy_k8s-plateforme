#!/bin/bash
# ==============================================================================
#  tests/suivi/test_suivi.sh — suivi.sh, collecte-tmux.sh et
#  apps/garde_veille_master.sh, sans cluster, sans ssh, sans le tmux habituel
# ==============================================================================
#
#  CE QUE FAIT CE SCRIPT
#
#  1. suivi.sh lit des fichiers écrits par le VRAI garde.py (--une-fois, horloge
#     factice), face au faux master de tests/garde/ (faux_kubectl.py, faux_s3,
#     modele.json, réutilisés tels quels) : chaque rubrique est comparée à
#     garde.tsv et alertes.txt lus autrement (lire.py, awk) ; au plus 40 lignes
#     et 110 colonnes ; gardien vieux de 5 min → « GARDIEN MUET » ; alertes
#     ouvertes ; bande des 30 minutes (avec des trous) ; fichiers absents, vides,
#     dernier.json et garde.tsv coupés → aucune erreur ; --journal passe au
#     journal d'une nouvelle campagne. Pendant tout le suivi, ssh et kubectl sont
#     des faux qui ÉCHOUENT BRUYAMMENT et notent l'appel : aucun ne doit l'être.
#  2. collecte-tmux.sh sur deux serveurs tmux ISOLÉS (tmux -L <socket du test>
#     pour la vue, <socket>-garde pour le gardien ; TMUX_TMPDIR dans le dossier
#     temporaire), avec un FAUX garde.py : sessions créées, rien en double, une
#     session étrangère intacte, « oui » demandé si un faux pilote vit (ou si on
#     ne peut pas le savoir), Ctrl-C dans « garde » n'arrête pas le gardien, la
#     boucle attend sans bavarder quand le verrou est pris, les proportions des
#     volets tiennent après un changement de taille, un client « attach -r »
#     (dans un pseudo-terminal donné par script) ne peut rien taper. Les deux
#     serveurs du test sont tués à la fin.
#  3. garde_veille_master.sh avec un HOME factice et une horloge factice.
#
#  POURQUOI
#
#  Ces trois scripts servent à regarder et à alerter pendant 7 jours : ils ne
#  doivent jamais casser, ni rien toucher. On le vérifie ici, sans cluster.
#
#  Usage :  bash tests/suivi/test_suivi.sh        (GARDER=1 garde le dossier)
#  Code 0 seulement si tout passe. Borné à 10 minutes ; chaque commande lancée
#  a en plus son propre plafond (timeout).
# ==============================================================================
set -uo pipefail

if [ -z "${_TEST_BORNE:-}" ]; then
    exec env _TEST_BORNE=1 timeout -k 10 600 bash "$0" "$@"
fi

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHANTIER="$(cd "$ICI/../.." && pwd)"
GARDE_TESTS="$CHANTIER/tests/garde"
PYTHON="$(command -v python3)"
export PYTHONDONTWRITEBYTECODE=1
export LANG=C.UTF-8 LC_ALL=C.UTF-8
BAC="$(mktemp -d "${TMPDIR:-/tmp}/test_suivi.XXXXXX")"
SOCK="test-suivi-$$"
export TMUX_TMPDIR="$BAC/tmux"; mkdir -p "$TMUX_TMPDIR"
unset TMUX TMUX_PANE
TT() { timeout 10 tmux -L "$SOCK" "$@"; }        # le serveur tmux DU TEST (la vue), jamais l'habituel
TTG() { timeout 10 tmux -L "$SOCK-garde" "$@"; } # le serveur du gardien, pour le test

PILOTES=()
nettoyer() {
    TT kill-server 2>/dev/null; TTG kill-server 2>/dev/null
    local p
    for p in "${PILOTES[@]}"; do kill -KILL $(descendants "$p") 2>/dev/null; done
    for p in $(jobs -pr); do kill "$p" 2>/dev/null; done
    if [ -n "${GARDER:-}" ]; then echo "dossier gardé : $BAC"; else rm -rf "$BAC"; fi
}
trap nettoyer EXIT

REUSSIS=0; RATES=0
ok()    { echo "  OK     $*"; REUSSIS=$((REUSSIS + 1)); }
echec() { echo "  ÉCHEC  $*"; RATES=$((RATES + 1)); }
titre() { echo; echo "── $*"; }
egal() {   # <description> <obtenu> <attendu>
    if [ "$2" = "$3" ]; then ok "$1 : $2"; else echec "$1 : attendu « $3 », obtenu « $2 »"; fi
}
contient() {   # <description> <texte> <motif grep -F>
    if printf '%s' "$2" | grep -qF -- "$3"; then ok "$1"; else echec "$1 (« $3 » absent)"; fi
}
contient_pas() {
    if printf '%s' "$2" | grep -qF -- "$3"; then echec "$1 (« $3 » présent)"; else ok "$1"; fi
}
attendre() {   # <secondes> <commande…> : jusqu'à ce que la commande réussisse
    local n=$(( $1 * 5 )); shift
    local i; for i in $(seq "$n"); do "$@" >/dev/null 2>&1 && return 0; sleep 0.2; done; return 1
}
descendants() {
    local p e
    for p in "$@"; do echo "$p"; for e in $(pgrep -P "$p"); do descendants "$e"; done; done
}
# Largeur et hauteur d'un écran (en caractères, pas en octets).
mesure() { "$PYTHON" -c 'import sys; l=open(sys.argv[1],encoding="utf-8").read().split("\n"); l=l[:-1] if l and l[-1]=="" else l; print(len(l), max((len(x) for x in l), default=0))' "$1"; }

# ------------------------------------------------------------------ les faux
FG="$BAC/bin-garde"; FI="$BAC/bin-interdit"; mkdir -p "$FG" "$FI"
# Pour le VRAI garde.py : un faux ssh qui exécute la sonde ici, un faux kubectl
# qui rejoue le master (ceux de tests/garde). Toute autre commande ssh est refusée.
cat > "$FG/kubectl" <<EOF
#!/bin/bash
exec "$PYTHON" "$GARDE_TESTS/faux_kubectl.py" "\$@"
EOF
cat > "$FG/ssh" <<'EOF'
#!/bin/bash
while [ $# -gt 0 ]; do case "$1" in -o) shift 2 ;; -*) shift ;; *) break ;; esac; done
shift; cmd="$*"
echo "$cmd" >> "$FAUX_LOG_SSH"
if [[ "$cmd" =~ ^python3\ [^\ ]+/apps/garde_sonde\.py(\ --commandes)?$ ]]; then
    exec env HOME="$FAUX_HOME_MASTER" bash -c "$cmd"
fi
echo "INTERDIT $cmd" >> "$FAUX_LOG_SSH"; echo "faux ssh : refusé : $cmd" >&2; exit 99
EOF
# Pour le suivi, la vue et la veille : ssh et kubectl ÉCHOUENT BRUYAMMENT.
for c in ssh kubectl; do
    cat > "$FI/$c" <<EOF
#!/bin/bash
echo "APPEL INTERDIT : $c \$*" >> "$BAC/interdit.log"
echo "APPEL INTERDIT : $c \$* (le suivi ne doit lancer ni ssh ni kubectl)" >&2
exit 97
EOF
done
chmod +x "$FG"/* "$FI"/*
PATH_GARDE="$FG:$PATH"
PATH_SUIVI="$FI:$PATH"

cat > "$BAC/campagne.sh" <<'EOF'
#!/bin/bash
# Faux pilote : « bash …/campagne.sh <nom> … » qui dort.
sleep 100000 & enfant=$!
trap 'kill $enfant 2>/dev/null; exit 0' TERM
wait $enfant
EOF
pilote_on() {   # <dépôt> <nom> <dossier proc> : un faux pilote vivant, visible dans le faux /proc
    bash "$1/campagne.sh" "$2" --profil 25:30 > /dev/null 2>&1 &
    local p=$!; PILOTES+=("$p")
    attendre 4 grep -q campagne.sh "/proc/$p/cmdline"
    local q; for q in $(descendants "$p"); do ln -sfn "/proc/$q" "$3/$q"; done
    PILOTE=$p
}
pilote_off() {   # <pid> <dossier proc>
    kill -KILL $(descendants "$1") 2>/dev/null; wait "$1" 2>/dev/null
    rm -f "$2"/*
}

titre "les faux sont en place"
[ "$(PATH="$PATH_SUIVI" command -v ssh)" = "$FI/ssh" ] && [ "$(PATH="$PATH_SUIVI" command -v kubectl)" = "$FI/kubectl" ] \
    && ok "pour le suivi, ssh et kubectl sont des faux qui échouent" || { echo "  ÉCHEC  faux absents — arrêt"; exit 2; }
[ "$(PATH="$PATH_GARDE" command -v ssh)" = "$FG/ssh" ] && ok "pour garde.py, ssh est le faux master" \
    || { echo "  ÉCHEC  faux ssh absent — arrêt"; exit 2; }

# ==============================================================================
titre "1. des fichiers écrits par le VRAI garde.py (11:50 → 12:03, trou 11:58-11:59, panne, pause)"
# ==============================================================================
D="$BAC/garde-cas"; DOSSIER="$D/garde"; TSV="$DOSSIER/garde.tsv"
MASTER="$D/master/autodeploy"; DEPOT="$D/depot"; PROCF="$D/proc"
mkdir -p "$MASTER/apps" "$MASTER/journaux" "$D/master/home" "$DEPOT/journaux" "$DEPOT/graphe_en" "$PROCF"
cp "$CHANTIER/apps/garde_sonde.py" "$MASTER/apps/"
cat > "$MASTER/apps/consommateur.sh" <<'EOF'
#!/bin/bash
[ "${1:-}" = verifier ] || exit 2
echo "  [consommateur] OK  chaque réplique en marche de ts-delivery-service porte le retard"; exit 0
EOF
cat > "$MASTER/apps/donnees.sh" <<'EOF'
#!/bin/bash
[ "${1:-} ${2:-}" = "etat --brut" ] || exit 2
n="${FAUX_COMMANDES:-1200}"
echo "orders=$n orders_other=12 food_order=$((n * 3 / 4)) delivery=$((n / 2)) total=$((n + 12 + n * 3 / 4 + n / 2))"
EOF
# Le dépôt de vms0 : copies de suivi.sh, suivi.py, garde.py (suivi.py y réutilise
# la recherche du pilote), le faux pilote.
cp "$CHANTIER/suivi.sh" "$CHANTIER/suivi.py" "$CHANTIER/garde.py" "$DEPOT/"
cp "$BAC/campagne.sh" "$DEPOT/campagne.sh"
printf '# instant_demande\tinstant_effectif\tvoyageurs_observes\tvoyageurs_demandes\tspawn_rate\tcible\torigine\n2026-10-01T11:00:00Z\t2026-10-01T11:00:00Z\t25\t25\t1\ttrain-ticket\tdemande\n' > "$MASTER/journaux/paliers.tsv"
printf '# instant_demande\tinstant_effectif\taction\tcause\tintensite\tcible\toutil\tresultat\n' > "$MASTER/journaux/pannes.tsv"
printf '# instant\taction\tlignes_avant\tresultat\n' > "$MASTER/journaux/donnees.tsv"
printf 'source:\n  endpoint: http://faux:9000\n  bucket: faux\n  prefix: otel-data\n  access_key: A\n  secret_key: B\n' > "$DEPOT/graphe_en/config.yaml"
printf 'FIN_CAMPAGNE\tessai-hier\t0\t2026-09-30T22:10:00Z\ttermine\nFIN_CAMPAGNE\tessai-matin\t130\t2026-10-01T09:15:00Z\tinterrompu_TERM\nFIN_CAMPAGNE\tessai-avant\t0\t2026-10-01T11:40:00Z\ttermine\n' > "$DEPOT/journaux/fins.tsv"
echo '{}' > "$D/scenario.json"
export GARDE_SSH=master GARDE_PYTHON_S3="$PYTHON" PYTHONPATH="$GARDE_TESTS/faux_s3" GARDE_DISTANT="$MASTER" \
       GARDE_DEPOT="$DEPOT" GARDE_S3_CONFIG="$DEPOT/graphe_en/config.yaml" GARDE_PROC="$PROCF" \
       FAUX_HOME_MASTER="$D/master/home" FAUX_SCENARIO="$D/scenario.json" FAUX_S3_OBJETS="$D/s3.json" \
       FAUX_S3_LOG="$D/s3.log" FAUX_LOG_SSH="$D/ssh.log" FAUX_LOG_KUBECTL="$D/kubectl.log" \
       FAUX_T0="$(date -u -d 2026-10-01T11:00:00Z +%s)"
JOURNAL="$DEPOT/journaux/campagne-20261001-114500.log"
pilote_on "$DEPOT" essai-suivi "$PROCF"; PILOTE_1=$PILOTE
printf '  journal : %s\n  [campagne] OK  palier 25 appliqué\n' "$JOURNAL" > "$JOURNAL"

garde_minute() {   # <HH:MM> [options de garde.py] — une minute du VRAI gardien à HH:MM:30
    local h="$1"; shift
    echo "  [campagne] veille $h : palier 25, minute $h" >> "$JOURNAL"
    touch -d "2026-10-01T$h:10Z" "$JOURNAL"
    PATH="$PATH_GARDE" GARDE_MAINTENANT="2026-10-01T$h:30Z" timeout 60 "$PYTHON" "$CHANTIER/garde.py" --une-fois \
        --dossier "$DOSSIER" "$@" >> "$D/sortie.txt" 2>&1 || echo "garde.py code $? à $h" >> "$D/sortie.txt"
}
val() { "$PYTHON" "$GARDE_TESTS/lire.py" "$TSV" "$1" "$2"; }
scenario() { echo "$1" > "$D/scenario.json"; }
debut_1=$(date +%s)
garde_minute 11:50 --sans-s3
garde_minute 11:51 --sans-s3
scenario '{"locust": {"req_s": 5.5}}'
garde_minute 11:52 --sans-s3
scenario '{}'
for m in 11:53 11:54 11:55 11:56 11:57; do garde_minute "$m" --sans-s3; done
# 11:58 et 11:59 : la garde ne passe pas (trou) ; à 12:00 une panne est déclarée,
# et la table des commandes dépasse 7 000 (drapeau de pause).
printf "CAUSE='consumer-slowdown'\nOUTIL='chaos-mesh'\nCIBLE='x'\nINTENSITE='300'\nDEBUT='2026-10-01T11:59:00Z'\nDUREE='20'\nMINUTEUR=''\n" > "$MASTER/journaux/panne.etat"
export FAUX_COMMANDES=7100
garde_minute 12:00 --sans-s3
garde_minute 12:01 --sans-s3
garde_minute 12:02 --sans-s3
T=$(date -u -d "2026-10-01T12:03:20Z" +%Y-%m-%dT%H:%M:%SZ)
printf '[{"Key": "otel-data/year=2026/month=10/day=01/hour=12/minute=03/traces_1.json.gz", "LastModified": "%s"}]\n' "$T" > "$D/s3.json"
garde_minute 12:03 --agir
unset FAUX_COMMANDES
egal "garde.py : 14 lignes écrites (11:50 → 12:03, trou compris)" "$("$PYTHON" "$GARDE_TESTS/lire.py" "$TSV" --lignes)" "14"
egal "garde.py : le trou 11:58 est écrit MEASURE_GAP au retour" "$(val 11:58 causes)" "MEASURE_GAP"
egal "garde.py : aucune commande ssh refusée" "$(grep -c '^INTERDIT' "$D/ssh.log")" "0"
contient "garde.py : drapeau de pause posé" "$(cat "$DOSSIER/pause" 2>/dev/null)" "POSE_PAR=garde"
echo "  (garde.py : 12 minutes en $(( $(date +%s) - debut_1 )) s)"

# suivi_ecran <dépôt> <dossier> <maintenant HH:MM:SS> <fichier> [options] — un écran du suivi,
# avec les faux ssh et kubectl qui échouent ; rend le code de suivi.sh.
suivi_ecran() {
    local dep="$1" dos="$2" h="$3" f="$4"; shift 4
    PATH="$PATH_SUIVI" GARDE_DOSSIER="$dos" SUIVI_MAINTENANT="2026-10-01T${h}Z" \
        timeout 20 bash "$dep/suivi.sh" "$@" > "$f" 2> "$f.err"
}

# ==============================================================================
titre "2. suivi.sh à 12:03:45 : chaque rubrique comparée aux fichiers du gardien"
# ==============================================================================
E="$BAC/ecran-1203.txt"
suivi_ecran "$DEPOT" "$DOSSIER" 12:03:45 "$E"; code=$?
S="$(cat "$E")"
egal "code de sortie" "$code" "0"
egal "rien sur la sortie d'erreur" "$(cat "$E.err")" ""
read -r nl larg <<< "$(mesure "$E")"
[ "$nl" -le 40 ] && ok "hauteur $nl ≤ 40 lignes" || echec "hauteur $nl > 40"
[ "$larg" -le 110 ] && ok "largeur $larg ≤ 110 colonnes" || echec "largeur $larg > 110"
echo "  ┌──── l'écran (copie exacte) ────"
sed 's/^/  │/' "$E"
echo "  └────"
# 1. heure, âge, mode
contient "(1) heure UTC" "$S" "2026-10-01 12:03:45 UTC"
contient "(1) âge de la dernière ligne" "$S" "dernière minute écrite 12:03 (il y a 0 min)"
contient "(1) mode AGIR (12:03 lancé avec --agir)" "$S" "mode AGIR"
contient_pas "(1) pas de GARDIEN MUET" "$S" "GARDIEN MUET"
# 2. campagne
contient "(2) pilote vivant, nom et pid" "$S" "campagne   : essai-suivi (pid $PILOTE_1) VIVANTE"
contient "(2) journal du pilote, son âge, sa dernière ligne" "$S" "journal    : campagne-20261001-114500.log (il y a 0 min) : « [campagne] veille 12:03 : palier 25"
# 3. panne
contient "(3) panne déclarée, depuis, durée" "$S" "panne      : « consumer-slowdown » depuis 11:59 (4 min), durée déclarée 20 min → fin prévue 12:19"
# 4. dernière minute
etat=$(val 12:03 etat); causes=$(val 12:03 causes); notes=$(val 12:03 notes)
contient "(4) état de la dernière minute ($etat)" "$S" "── dernière minute 12:03 : $etat "
for c in ${causes//,/ }; do contient "(4) cause $c" "$(grep '── dernière minute' "$E")" "$c"; done
for c in ${notes//,/ }; do contient "(4) note $c" "$(grep '   notes  :' "$E")" "$c"; done
[ -n "$causes$notes" ] || ok "(4) ni cause ni note"
contient "(4) voyageurs, req/s, échecs" "$S" "voyageurs $(val 12:03 voyageurs_demandes) demandés / $(val 12:03 voyageurs_reels) réels   req/s $(val 12:03 req_s) (seuil $(val 12:03 req_s_min))   échecs $(val 12:03 echecs_pct) %"
contient "(4) dépôt, retrait, tas, consommateurs" "$S" "dépôt $(val 12:03 depot) msg/s   retrait $(val 12:03 retrait) msg/s   tas $(val 12:03 tas)   consommateurs $(val 12:03 consommateurs)"
contient "(4) CPU commandes, commandes, 140 ms" "$S" "CPU $(val 12:03 cpu_commandes) cœur   $(val 12:03 commandes) en table (lue il y a $(val 12:03 commandes_age_min) min)   140 ms : $(val 12:03 reglage_140ms)"
contient "(4) leader, nœuds, S3, place sur vms0" "$S" "leader $(val 12:03 leader)   nœuds prêts $(val 12:03 noeuds_prets)   âge S3 $(val 12:03 s3_age_s) s   vms0 libre $(val 12:03 vms0_libre_go) Go"
[ "$(val 12:03 s3_age_s)" != "" ] && ok "(4) âge S3 mesuré à 12:03 : $(val 12:03 s3_age_s) s" || echec "(4) âge S3 vide"
# 5. la bande : calculée minute par minute avec lire.py
bande_attendue() {   # <fichier garde.tsv> <première minute en secondes> — 30 lettres
    local t0="$1" i h e res=""
    for i in $(seq 0 29); do
        h=$(date -u -d "@$(( t0 + i * 60 ))" +%H:%M)
        e=$("$PYTHON" "$GARDE_TESTS/lire.py" "$2" "$h" etat)
        case "$e" in OK) res+="O" ;; MALADE) res+="M" ;; DOUTEUX) res+="D" ;; ABSENTE) res+="·" ;; *) res+="?" ;; esac
    done
    echo "${res:0:10} ${res:10:10} ${res:20:10}"
}
b=$(bande_attendue "$(date -u -d 2026-10-01T11:34:00Z +%s)" "$TSV")
contient "(5) bande 11:34 → 12:03 : $b" "$S" "── 30 min  11:34 $b 12:03  (O=OK"
egal "(5) 16 trous avant le départ du gardien (11:34-11:49)" "${b:0:10}${b:11:6}" "················"
egal "(5) le trou 11:58-11:59, comblé MEASURE_GAP, est MALADE" "${b:26:2}" "MM"
# 6. alertes ouvertes : DEBUT sans FIN, relu avec awk
ouvertes=$(awk '$2 == "DEBUT" { o[$4] = 1 } $2 == "FIN" { delete o[$4] } END { for (c in o) print c }' "$DOSSIER/alertes.txt" | sort | tr '\n' ' ')
fermees=$(awk '$2 == "FIN" { print $4 }' "$DOSSIER/alertes.txt" | sort -u | tr '\n' ' ')
vues=$(sed -n '/^── alertes ouvertes/,/^── /p' "$E" | grep '^   ' | awk '{ print $2 }' | sort | tr '\n' ' ')
egal "(6) alertes ouvertes = DEBUT sans FIN" "$vues" "$ouvertes"
egal "(6) la plus grave d'abord (MALADE avant NOTE)" "$(sed -n '/^── alertes ouvertes/,/^── /p' "$E" | grep '^   ' | head -1 | awk '{ print $1 }')" "MALADE"
[ -n "$fermees" ] && ok "(6) des alertes fermées existent ($fermees) et ne sont pas listées" || echec "(6) aucune alerte fermée : cas trop pauvre"
for c in $fermees; do
    case " $ouvertes " in *" $c "*) ;; *) contient_pas "(6) $c (fermée) absente des ouvertes" "$(sed -n '/^── alertes ouvertes/,/^── /p' "$E")" " $c " ;; esac
done
n=0; while IFS= read -r l; do
    contient "(6) ligne récente d'alertes.txt : ${l:0:50}…" "$S" "   ${l:0:90}"; n=$((n + 1))
done < <(grep -v '^#' "$DOSSIER/alertes.txt" | tail -5)
egal "(6) 5 lignes récentes vérifiées" "$n" "5"
# 7. pause et actions
contient "(7) drapeau posé par la garde, motif" "$S" "── pause : POSÉE par la garde depuis 12:00 — motifs ORDERS_HIGH"
while IFS= read -r l; do
    attendu=$(echo "$l" | awk -F'\t' '{ for (i = 1; i <= 6; i++) { x = $i; if (i == 1) x = substr(x, 12, 8);
        if (i == 4 && x ~ /\//) sub(/.*\//, "", x); if (x == "") x = "-"; printf "%s%s", (i > 1 ? "  " : "   "), x } }')
    contient "(7) action, colonnes à leur place : $attendu" "$S" "$attendu"
done < <(tail -n +2 "$DOSSIER/actions.tsv" | tail -3)
contient "(7) l'en-tête des actions" "$S" "── actions, 3 dernières (heure  geste  motif  cible  résultat  durée en s) :"
# 8. fins et bilan du jour
contient "(8) bilan du jour : 2 campagnes finies (pas celle d'hier)" "$S" "── depuis 00:00 UTC : 2 campagne(s) finie(s) (interrompu_TERM 1, termine 1)"
malades=$("$PYTHON" "$GARDE_TESTS/lire.py" "$TSV" --compte etat=MALADE)
contient "(8) minutes MALADE depuis minuit : $malades sur 14" "$S" "; $malades min MALADE sur 14 écrites"
contient "(8) ligne FIN d'hier listée (jour et heure)" "$S" "   30/09 22:10  essai-hier                       code 0    motif termine"
contient "(8) ligne FIN de 09:15 listée" "$S" "   09:15        essai-matin                      code 130  motif interrompu_TERM"
contient "(8) ligne FIN de 11:40 listée" "$S" "   11:40        essai-avant"

# ==============================================================================
titre "3. gardien vieux de 5 min, pilote arrêté, trou au milieu, fichiers coupés ou absents"
# ==============================================================================
suivi_ecran "$DEPOT" "$DOSSIER" 12:08:45 "$BAC/muet.txt"; code=$?
M="$(cat "$BAC/muet.txt")"
egal "muet : code" "$code" "0"
contient "muet : « GARDIEN MUET depuis 5 min »" "$M" "GARDIEN MUET depuis 5 min (dernière minute écrite : 12:03)"
contient "muet : la bande finit par 4 trous (12:04-12:07)" "$M" "···· 12:07"
read -r nl larg <<< "$(mesure "$BAC/muet.txt")"
[ "$nl" -le 40 ] && [ "$larg" -le 110 ] && ok "muet : $nl lignes, $larg colonnes" || echec "muet : $nl lignes, $larg colonnes"

pilote_off "$PILOTE_1" "$PROCF"
suivi_ecran "$DEPOT" "$DOSSIER" 12:03:45 "$BAC/sans-pilote.txt"
contient "pilote arrêté : « aucun pilote vivant » et la dernière fin" "$(cat "$BAC/sans-pilote.txt")" \
    "campagne   : aucun pilote vivant ; dernière fin : essai-avant (termine, code 0) à 11:40"

# Un trou au MILIEU (une ligne retirée à la main) : un « · » à sa place.
cp -r "$DOSSIER" "$BAC/trou"
grep -v '^2026-10-01T11:51Z' "$DOSSIER/garde.tsv" > "$BAC/trou/garde.tsv"
suivi_ecran "$DEPOT" "$BAC/trou" 12:03:45 "$BAC/trou.txt"
b2=$(bande_attendue "$(date -u -d 2026-10-01T11:34:00Z +%s)" "$BAC/trou/garde.tsv")
egal "trou au milieu : 11:51 devient « · »" "${b2:18:1}" "·"
contient "trou au milieu : bande juste ($b2)" "$(cat "$BAC/trou.txt")" "11:34 $b2 12:03"

# dernier.json coupé en cours d'écriture, garde.tsv avec une ligne coupée à la fin.
cp -r "$DOSSIER" "$BAC/coupe"
head -c 300 "$DOSSIER/dernier.json" > "$BAC/coupe/dernier.json"
printf '2026-10-01T12:04Z\tMALADE\tLOCUST_' >> "$BAC/coupe/garde.tsv"
suivi_ecran "$DEPOT" "$BAC/coupe" 12:04:45 "$BAC/coupe.txt"; code=$?
C="$(cat "$BAC/coupe.txt")"
egal "coupés : code" "$code" "0"
egal "coupés : rien sur la sortie d'erreur" "$(cat "$BAC/coupe.txt.err")" ""
contient "coupés : la ligne coupée est ignorée (dernière minute 12:03)" "$C" "── dernière minute 12:03"
contient "coupés : le mode est relu dans memoire.json" "$C" "mode AGIR"
contient_pas "coupés : pas de trace d'erreur Python" "$C" "Traceback"

# La dernière ligne est un MEASURE_GAP (le gardien revient : il a écrit les
# trous, pas encore la minute en cours) : l'avertissement a sa propre ligne.
cp -r "$DOSSIER" "$BAC/gap"
awk -F'\t' 'NR == 1 || $1 <= "2026-10-01T11:59Z"' "$DOSSIER/garde.tsv" > "$BAC/gap/garde.tsv"
rm -f "$BAC/gap/dernier.json"
suivi_ecran "$DEPOT" "$BAC/gap" 12:00:10 "$BAC/gap.txt"; code=$?
G="$(cat "$BAC/gap.txt")"
egal "MEASURE_GAP en dernier : code" "$code" "0"
contient "MEASURE_GAP en dernier : la minute 11:59 et sa cause" "$G" "── dernière minute 11:59 : MALADE   causes : MEASURE_GAP"
contient "MEASURE_GAP en dernier : avertissement entier, sur sa ligne" "$G" "   ATTENTION : valeurs de 11:57, dernière minute mesurée (le master n'a rien rendu depuis) :"
contient "MEASURE_GAP en dernier : panne lue à 11:57" "$G" "panne      : aucune (à la dernière minute mesurée, 11:57)"
read -r nl larg <<< "$(mesure "$BAC/gap.txt")"
[ "$nl" -le 40 ] && [ "$larg" -le 110 ] && ok "MEASURE_GAP : $nl lignes, $larg colonnes" || echec "MEASURE_GAP : $nl lignes, $larg colonnes"

# Master injoignable : une minute MEASURE_FAILED:ssh n'a que les colonnes de vms0.
# Les valeurs du cluster restent celles de 12:03 (avec leur heure), la place
# libre est celle de 12:04.
cp -r "$DOSSIER" "$BAC/ssh"
"$PYTHON" - "$BAC/ssh/garde.tsv" <<'PY'
import sys
f = sys.argv[1]
entete = open(f).readline().rstrip("\n").split("\t")
l = {c: "" for c in entete}
l.update(minute="2026-10-01T12:04Z", etat="MALADE", causes="MEASURE_FAILED:ssh", pilote="essai-suivi(1)",
         vms0_libre_go="999.5", pause_proposee="0")
open(f, "a").write("\t".join(l[c] for c in entete) + "\n")
PY
suivi_ecran "$DEPOT" "$BAC/ssh" 12:04:40 "$BAC/ssh.txt"; code=$?
H="$(cat "$BAC/ssh.txt")"
egal "ssh en échec : code" "$code" "0"
contient "ssh en échec : la panne reste connue (12:03)" "$H" "panne      : « consumer-slowdown » depuis 11:59"
contient "ssh en échec : valeurs de 12:03 annoncées" "$H" "ATTENTION : valeurs de 12:03, dernière minute mesurée"
contient "ssh en échec : voyageurs de 12:03, pas « ? »" "$H" "voyageurs $(val 12:03 voyageurs_demandes) demandés"
contient "ssh en échec : place libre de 12:04" "$H" "vms0 libre 999.5 Go (à 12:04)"

# Le mode quand dernier.json manque.
cp -r "$DOSSIER" "$BAC/mode"; rm -f "$BAC/mode/dernier.json"
echo '{"contamine": false}' > "$BAC/mode/memoire.json"
suivi_ecran "$DEPOT" "$BAC/mode" 12:03:45 "$BAC/mode1.txt"
contient "mode : memoire.json sans clé mode → PROPOSE déduit" "$(cat "$BAC/mode1.txt")" "mode PROPOSE (déduit de memoire.json, sans clé mode)"
echo '{"contamine": true, "repartie_a": "2026-10-01T12:02Z"}' > "$BAC/mode/memoire.json"
suivi_ecran "$DEPOT" "$BAC/mode" 12:03:45 "$BAC/mode2.txt"
contient "mode : mémoire remise à neuf → inconnu" "$(cat "$BAC/mode2.txt")" "mode inconnu (dernier.json illisible, memoire.json remise à neuf sans mode)"
echo '{"contamine": true}' > "$BAC/mode/memoire.json"; : > "$BAC/mode/memoire.json.20261001T120200Z.casse"
suivi_ecran "$DEPOT" "$BAC/mode" 12:03:45 "$BAC/mode3.txt"
contient "mode : un memoire.json.*.casse à côté → inconnu" "$(cat "$BAC/mode3.txt")" "mode inconnu (dernier.json illisible, memoire.json remise à neuf"
rm -f "$BAC/mode/memoire.json"*
suivi_ecran "$DEPOT" "$BAC/mode" 12:03:45 "$BAC/mode4.txt"
contient "mode : ni dernier.json ni memoire.json → inconnu, dit pourquoi" "$(cat "$BAC/mode4.txt")" "mode inconnu (dernier.json et memoire.json absents ou illisibles)"

# Un écran bas (le volet du haut de la vue) : le bilan du jour reste toujours.
ecran_de() {   # <hauteur> : l'écran de 12:03:45 à cette hauteur, par suivi.ecran()
    PATH="$PATH_SUIVI" SUIVI_MAINTENANT=2026-10-01T12:03:45Z timeout 20 "$PYTHON" -c '
import sys; sys.path.insert(0, sys.argv[1]); import suivi
print("\n".join(suivi.ecran(sys.argv[2], int(sys.argv[3]))))' "$DEPOT" "$DOSSIER" "$1"
}
for h in 28 24 21; do
    e=$(ecran_de "$h")
    n=$(printf '%s\n' "$e" | wc -l)
    [ "$n" -le "$h" ] && ok "écran de $h lignes : $n lignes" || echec "écran de $h lignes : $n lignes"
    contient "écran de $h lignes : le bilan du jour reste" "$e" "── depuis 00:00 UTC : 2 campagne(s) finie(s)"
    contient "écran de $h lignes : les 2 alertes ouvertes" "$e" "── alertes ouvertes (DEBUT sans FIN) : 2"
    contient_pas "écran de $h lignes : pas d'alerte ouverte cachée" "$e" "… et "
done
contient "écran de 40 lignes : tout y est (5 lignes d'alertes.txt, liste des fins)" "$(ecran_de 40)" "── alertes.txt, 5 dernières"
contient_pas "écran de 28 lignes : les 5 lignes d'alertes.txt ont sauté d'abord" "$(ecran_de 28)" "── alertes.txt, 5 dernières"
contient "écran de 28 lignes : la liste des fins est encore là" "$(ecran_de 28)" "── fins de campagne, 5 dernières"
contient_pas "écran de 21 lignes : la liste des fins a sauté" "$(ecran_de 21)" "── fins de campagne, 5 dernières"

# Rien du tout (première installation) : dossier du gardien absent, dépôt sans journaux.
mkdir -p "$BAC/vide/depot"; cp "$CHANTIER/suivi.sh" "$CHANTIER/suivi.py" "$BAC/vide/depot/"
suivi_ecran "$BAC/vide/depot" "$BAC/vide/garde-absent" 12:00:00 "$BAC/vide.txt"; code=$?
V="$(cat "$BAC/vide.txt")"
egal "absents : code" "$code" "0"
egal "absents : rien sur la sortie d'erreur" "$(cat "$BAC/vide.txt.err")" ""
n=$(grep -c "(pas encore de données)" "$BAC/vide.txt")
[ "$n" -ge 8 ] && ok "absents : « (pas encore de données) » dans $n rubriques" || echec "absents : seulement $n rubriques vides"
contient "absents : pas de pilote" "$V" "aucun pilote vivant"

# Fichiers présents mais vides, et garde.tsv réduit à son en-tête.
mkdir -p "$BAC/vides/garde" "$BAC/vides/depot/journaux"; cp "$CHANTIER/suivi.sh" "$CHANTIER/suivi.py" "$BAC/vides/depot/"
for f in garde.tsv alertes.txt dernier.json actions.tsv memoire.json; do : > "$BAC/vides/garde/$f"; done
: > "$BAC/vides/depot/journaux/fins.tsv"; : > "$BAC/vides/depot/journaux/campagne-20261001-120000.log"
suivi_ecran "$BAC/vides/depot" "$BAC/vides/garde" 12:00:00 "$BAC/vides.txt"; code=$?
egal "vides : code" "$code" "0"
egal "vides : rien sur la sortie d'erreur" "$(cat "$BAC/vides.txt.err")" ""
contient "vides : journal vide dit « (vide) »" "$(cat "$BAC/vides.txt")" "« (vide) »"
head -1 "$TSV" > "$BAC/vides/garde/garde.tsv"
suivi_ecran "$BAC/vides/depot" "$BAC/vides/garde" 12:00:00 "$BAC/vides2.txt"; code=$?
egal "en-tête seul : code" "$code" "0"
contient "en-tête seul : « (pas encore de données) »" "$(cat "$BAC/vides2.txt")" "gardien    : (pas encore de données)"

# --boucle : deux écrans, puis arrêt par TERM.
PATH="$PATH_SUIVI" GARDE_DOSSIER="$DOSSIER" SUIVI_MAINTENANT="2026-10-01T12:03:45Z" \
    timeout 20 bash "$DEPOT/suivi.sh" --boucle 1 > "$BAC/boucle.txt" 2>&1 &
PB=$!
attendre 10 sh -c "[ \$(grep -c '^SUIVI DE LA COLLECTE' '$BAC/boucle.txt') -ge 2 ]" \
    && ok "--boucle 1 : l'écran est redessiné" || echec "--boucle : $(grep -c '^SUIVI' "$BAC/boucle.txt") écran(s)"
kill -TERM "$PB" 2>/dev/null; wait "$PB" 2>/dev/null
kill -0 "$PB" 2>/dev/null && echec "--boucle : toujours vivant après TERM" || ok "--boucle : arrêté par TERM"
egal "--boucle --une-fois mal formé : code 2" "$(bash "$DEPOT/suivi.sh" --boucle 0 >/dev/null 2>&1; echo $?)" "2"

# ==============================================================================
titre "4. suivi.sh --journal passe au journal d'une nouvelle campagne"
# ==============================================================================
DJ="$BAC/journal/depot"; mkdir -p "$DJ/journaux"; cp "$CHANTIER/suivi.sh" "$CHANTIER/suivi.py" "$DJ/"
printf 'ancienne campagne : ligne V1\n' > "$DJ/journaux/campagne-20260930-100000.log"
touch -d "2026-09-30T10:30:00Z" "$DJ/journaux/campagne-20260930-100000.log"
JO="$BAC/journal/sortie.txt"
PATH="$PATH_SUIVI" SUIVI_ATTENTE=0.2 GARDE_DOSSIER="$BAC/journal/garde" timeout 60 bash "$DJ/suivi.sh" --journal > "$JO" 2>&1 &
PJ=$!
attendre 5 grep -q "ancienne campagne : ligne V1" "$JO" && ok "--journal : montre la fin du journal le plus récent au départ" || echec "--journal : départ ($(cat "$JO"))"
A="$DJ/journaux/campagne-20261001-120000.log"; B="$DJ/journaux/campagne-20261001-130000.log"
printf 'campagne A : ligne A1\n' > "$A"
attendre 5 grep -q "ligne A1" "$JO" && ok "--journal : nouvelle campagne A suivie" || echec "--journal : A1 absent"
printf 'campagne A : ligne A2\n' >> "$A"
attendre 5 grep -q "ligne A2" "$JO" && ok "--journal : la suite de A s'affiche" || echec "--journal : A2 absent"
printf 'campagne B : ligne B1\n' > "$B"
attendre 5 grep -q "ligne B1" "$JO" && ok "--journal : passe au journal de B" || echec "--journal : B1 absent"
printf 'campagne A : ligne A3 (après le départ de B)\n' >> "$A"
printf 'campagne B : ligne B2\n' >> "$B"
attendre 5 grep -q "ligne B2" "$JO" && ok "--journal : la suite de B s'affiche" || echec "--journal : B2 absent"
sleep 0.6
contient_pas "--journal : l'ancien journal A n'est plus suivi" "$(cat "$JO")" "ligne A3"
egal "--journal : deux annonces « nouvelle campagne »" "$(grep -c '════ nouvelle campagne' "$JO")" "2"
kill -TERM "$PJ" 2>/dev/null; wait "$PJ" 2>/dev/null
kill -0 "$PJ" 2>/dev/null && echec "--journal : vivant après TERM" || ok "--journal : arrêté par TERM"
egal "aucune trace d'erreur Python dans --journal" "$(grep -c Traceback "$JO")" "0"

titre "5. le suivi n'a lancé ni ssh ni kubectl"
if [ -s "$BAC/interdit.log" ]; then echec "appels interdits : $(cat "$BAC/interdit.log")"; else ok "aucun appel à ssh ni à kubectl"; fi
egal "rien d'écrit dans le dépôt par le suivi (pas de __pycache__)" "$(find "$DEPOT" "$CHANTIER" -maxdepth 1 -name __pycache__ | wc -l)" "0"

# ==============================================================================
titre "6. collecte-tmux.sh sur des serveurs tmux isolés (-L $SOCK et -L $SOCK-garde), avec un faux garde.py"
# ==============================================================================
TD="$BAC/t/depot"; TG="$BAC/t/garde"; TP="$BAC/t/proc"; mkdir -p "$TD/journaux" "$TG" "$TP" "$BAC/t/home"
cp "$CHANTIER/collecte-tmux.sh" "$CHANTIER/suivi.sh" "$CHANTIER/suivi.py" "$BAC/campagne.sh" "$TD/"
cat > "$TD/garde.py" <<'EOF'
#!/usr/bin/env python3
# Faux gardien : note son départ et ses arguments, attend ; TERM ou INT : note et sort.
# GARDE_FAUX_CODE=<n> : sort tout de suite avec ce code (3 = verrou déjà pris).
import os, signal, sys, time
def noter(t):
    with open(os.environ["GARDE_FAUX_LOG"], "a") as f:
        f.write(t + "\n")
if __name__ == "__main__":
    noter(f"DEPART {os.getpid()} {' '.join(sys.argv[1:])}".rstrip())
    if os.environ.get("GARDE_FAUX_CODE"):
        sys.exit(int(os.environ["GARDE_FAUX_CODE"]))
    def fin(s, _):
        noter(f"SIGNAL {s} {os.getpid()}")
        sys.exit(0)
    signal.signal(signal.SIGTERM, fin)
    signal.signal(signal.SIGINT, fin)
    while True:
        time.sleep(0.2)
EOF
FGL="$BAC/t/faux-garde.log"; : > "$FGL"
CT() {   # collecte-tmux.sh du test : serveur isolé, HOME factice, faux ssh/kubectl qui échouent
    env -u GARDE_SSH -u GARDE_DISTANT -u GARDE_S3_CONFIG -u GARDE_PYTHON_S3 \
        HOME="$BAC/t/home" PATH="$PATH_SUIVI" COLLECTE_TMUX_SOCKET="$SOCK" COLLECTE_ARRET_MAX=20 \
        GARDE_DOSSIER="${CT_DOSSIER:-$TG}" GARDE_DEPOT="$TD" GARDE_PROC="${CT_PROC:-$TP}" GARDE_FAUX_LOG="$FGL" \
        SUIVI_ATTENTE=0.5 \
        timeout 60 bash "$TD/collecte-tmux.sh" "$@"
}
sessions() { TT list-sessions -F '#{session_name}' 2>/dev/null | sort | tr '\n' ' '; }          # serveur de la vue
sessions_g() { TTG list-sessions -F '#{session_name}' 2>/dev/null | sort | tr '\n' ' '; }       # serveur du gardien
volets() {   # du haut vers le bas : « id pid mort commande » (la position seule peut changer :
             # un client qui s'attache redimensionne la fenêtre)
    TT list-panes -s -t "$1" -F '#{pane_top} #{pane_id} #{pane_pid} #{pane_dead} #{pane_start_command}' 2>/dev/null \
        | sort -n | cut -d' ' -f2-
}
sid_de() { TT list-sessions -F '#{session_id} #{session_name}' | awk -v n="$1" '$2 == n { print $1 }'; }
departs() { grep -c '^DEPART' "$FGL"; }

# Une session étrangère, comme les 9 vieilles de vms0.
HOME="$BAC/t/home" TT new-session -d -s etrangere -x 80 -y 20 sleep 100000
ETR_AVANT=$(TT list-panes -t etrangere -F '#{session_id} #{session_created} #{pane_id} #{pane_pid}')
etrangere_intacte() {   # <moment>
    local apres; apres=$(TT list-panes -t etrangere -F '#{session_id} #{session_created} #{pane_id} #{pane_pid}' 2>/dev/null)
    if [ "$apres" = "$ETR_AVANT" ] && kill -0 "${ETR_AVANT##* }" 2>/dev/null; then ok "session étrangère intacte $1"
    else echec "session étrangère touchée $1 : avant « $ETR_AVANT », après « $apres »"; fi
}

CT demarrer > "$BAC/t/demarrer1.txt" 2>&1; code=$?
egal "demarrer : code" "$code" "0"
egal "demarrer : sessions du serveur de la vue" "$(sessions)" "collecte etrangere "
egal "demarrer : « garde » sur le serveur à part" "$(sessions_g)" "garde "
attendre 5 test "$(departs)" -ge 1 && ok "demarrer : le faux garde.py est parti dans « garde »" || echec "demarrer : faux garde.py pas lancé"
egal "demarrer : garde.py SANS --agir" "$(grep '^DEPART' "$FGL" | head -1 | awk '{ print $3 }')" ""
egal "collecte : 1 fenêtre" "$(TT list-windows -t "$(sid_de collecte)" | wc -l)" "1"
egal "collecte : 3 volets" "$(TT list-panes -s -t "$(sid_de collecte)" | wc -l)" "3"
V1="$(volets "$(sid_de collecte)")"
echo "  disposition (list-panes) :"
TT list-panes -s -t "$(sid_de collecte)" -F '#{window_index}.#{pane_index} #{pane_id} haut=#{pane_top} #{pane_width}x#{pane_height} remain-on-exit=#{remain-on-exit} « #{pane_title} » : #{pane_start_command}' | sed 's/^/      /'
contient "collecte : en haut, suivi.sh --boucle 30" "$(echo "$V1" | sed -n 1p)" "suivi.sh --boucle 30"
contient "collecte : au milieu, tail -F alertes.txt" "$(echo "$V1" | sed -n 2p)" "tail -n 30 -F $TG/alertes.txt"
contient "collecte : en bas, suivi.sh --journal" "$(echo "$V1" | sed -n 3p)" "suivi.sh --journal"
egal "collecte : remain-on-exit" "$(TT show-options -w -t "$(sid_de collecte)" -v remain-on-exit)" "on"
D1=$(cat "$BAC/t/demarrer1.txt")
contient "demarrer : dit comment regarder (nom exact)" "$D1" "tmux -L $SOCK attach -r -t =collecte"
contient "demarrer : dit comment partir" "$D1" "Ctrl-b puis d"
contient "demarrer : aucune touche switch-client -r" "$D1" "aucune touche n'appelle « switch-client -r »"
haut=$(echo "$V1" | sed -n 1p | awk '{ print $1 }'); bas=$(echo "$V1" | sed -n 3p | awk '{ print $1 }')
attendre 10 sh -c "tmux -L $SOCK capture-pane -p -t $haut | grep -q 'SUIVI DE LA COLLECTE'" \
    && ok "volet du haut : l'écran du suivi s'affiche" || echec "volet du haut : $(TT capture-pane -p -t "$haut" | head -3)"
attendre 10 sh -c "tmux -L $SOCK capture-pane -p -t $bas | grep -q 'journal du pilote'" \
    && ok "volet du bas : le suivi du journal s'affiche" || echec "volet du bas : $(TT capture-pane -p -t "$bas" | head -3)"
etrangere_intacte "après demarrer"

# Les proportions : un client de 40 lignes (simulé par resize-window) → l'état
# garde ~64 %, le milieu et le bas gardent quelques lignes chacun.
hauteurs() { TT list-panes -t "$(sid_de collecte)" -F '#{pane_top} #{pane_height}' | sort -n | awk '{ printf "%s ", $2 }'; }
echo "  hauteurs des volets à la création (fenêtre de 50) : $(hauteurs)"
TT resize-window -t "$(sid_de collecte)" -y 40
attendre 3 sh -c "[ \"\$(tmux -L $SOCK list-panes -t '$(sid_de collecte)' -F '#{pane_top} #{pane_height}' | sort -n | head -1 | cut -d' ' -f2)\" -ge 24 ]"
read -r h1 h2 h3 <<< "$(hauteurs)"
echo "  hauteurs après passage à 40 lignes : $h1 $h2 $h3"
[ "$h1" -ge 24 ] && [ "$h1" -le 27 ] && ok "40 lignes : l'état garde $h1 lignes (~64 %)" || echec "40 lignes : état $h1 lignes"
[ "$h2" -ge 4 ] && [ "$h3" -ge 4 ] && ok "40 lignes : alertes $h2, journal $h3 (≥ 4)" || echec "40 lignes : alertes $h2, journal $h3"
attendre 5 sh -c "tmux -L $SOCK capture-pane -p -t $haut | grep -q '── depuis 00:00 UTC'" \
    && ok "40 lignes : redessiné tout de suite, le bilan du jour est visible" || echec "40 lignes : bilan absent du volet du haut"
TT set-option -w -u -t "$(sid_de collecte)" window-size 2>/dev/null
contient_pas "le serveur de la vue n'a pas de « garde » : Ctrl-b ( ne peut pas l'atteindre" "$(sessions)" "garde"

# Un autre GARDE_DOSSIER que celui des sessions déjà là : averti.
CT_DOSSIER="$BAC/t/autre-garde" CT demarrer > "$BAC/t/demarrer-autre.txt" 2>&1
contient "demarrer, autre GARDE_DOSSIER : averti" "$(cat "$BAC/t/demarrer-autre.txt")" "la session « garde » déjà là utilise GARDE_DOSSIER=$TG"
contient "demarrer, autre GARDE_DOSSIER : averti pour la vue aussi" "$(cat "$BAC/t/demarrer-autre.txt")" "la session « collecte » déjà là utilise GARDE_DOSSIER=$TG"
egal "demarrer, autre GARDE_DOSSIER : rien créé" "$(sessions)$(sessions_g)" "collecte etrangere garde "
rm -rf "$BAC/t/autre-garde"

CT demarrer > "$BAC/t/demarrer2.txt" 2>&1; code=$?
egal "demarrer relancé : code" "$code" "0"
egal "demarrer relancé : mêmes sessions" "$(sessions)$(sessions_g)" "collecte etrangere garde "
egal "demarrer relancé : mêmes volets, mêmes processus" "$(volets "$(sid_de collecte)")" "$V1"
sleep 1
egal "demarrer relancé : un seul garde.py lancé" "$(departs)" "1"
contient "demarrer relancé : « déjà là »" "$(cat "$BAC/t/demarrer2.txt")" "session « collecte » déjà là"

CT etat > "$BAC/t/etat1.txt" 2>&1
E1=$(cat "$BAC/t/etat1.txt")
contient "etat : gardien SANS --agir" "$E1" "garde.py tourne (pid"
contient "etat : mode PROPOSE dit" "$E1" "SANS --agir (mode PROPOSE"
contient "etat : la session étrangère listée comme ancienne" "$E1" "anciennes, à fermer à la main si inutiles"
contient "etat : son nom" "$E1" "etrangere (créée"
contient "etat : âge de garde.tsv (absent ici)" "$E1" "garde.tsv : (pas encore de données)"
echo "  sortie de « etat » :"; sed 's/^/      /' "$BAC/t/etat1.txt"

# Une liaison vers « switch-client -r » est signalée ; « -Tprefix » (un r dans un argument) ne l'est pas.
TT bind-key -T prefix R switch-client -r
CT etat > "$BAC/t/etat2.txt" 2>&1
contient "etat : liaison « switch-client -r » signalée" "$(cat "$BAC/t/etat2.txt")" "fait SORTIR de la lecture seule"
TT unbind-key -T prefix R
TT bind-key -T prefix R switch-client -Tprefix
CT etat > "$BAC/t/etat3.txt" 2>&1
contient "etat : « switch-client -Tprefix » n'est pas un -r" "$(cat "$BAC/t/etat3.txt")" "aucune touche n'appelle « switch-client -r »"
TT unbind-key -T prefix R

# Ctrl-C dans la session « garde » : le gardien et sa boucle continuent.
GP=$(grep '^DEPART' "$FGL" | tail -1 | awk '{ print $2 }')
# Témoin : la même frappe dans une session qui note SIGINT prouve que Ctrl-C arrive.
TTG new-session -d -s temoin-int -x 80 -y 10 "$PYTHON" -c "
import signal, time
signal.signal(signal.SIGINT, lambda *_: open('$BAC/t/int.txt', 'a').write('INT\\n'))
while True: time.sleep(0.1)"
sleep 0.5
TTG send-keys -t '=temoin-int:' C-c; sleep 0.5
egal "témoin : Ctrl-C envoyé par send-keys arrive bien (SIGINT)" "$(cat "$BAC/t/int.txt" 2>/dev/null)" "INT"
TTG kill-session -t '=temoin-int'
TTG send-keys -t '=garde:' C-c && ok "Ctrl-C tapé dans « garde »" || echec "send-keys vers « garde » refusé"
sleep 0.5; TTG send-keys -t '=garde:' C-c; sleep 1
egal "Ctrl-C dans « garde » : le gardien n'a reçu aucun signal" "$(grep -c '^SIGNAL' "$FGL")" "0"
kill -0 "$GP" 2>/dev/null && ok "Ctrl-C dans « garde » : le même garde.py tourne (pid $GP)" || echec "Ctrl-C : garde.py $GP arrêté"
egal "Ctrl-C dans « garde » : aucun nouveau départ" "$(departs)" "1"
egal "Ctrl-C dans « garde » : la session est toujours là" "$(sessions_g)" "garde "

# Un volet arrêté reste lisible (remain-on-exit), et demarrer le relance sans toucher aux autres.
milieu_pid=$(echo "$V1" | sed -n 2p | awk '{ print $2 }'); milieu=$(echo "$V1" | sed -n 2p | awk '{ print $1 }')
kill -TERM "$milieu_pid"
attendre 5 test "$(TT display -p -t "$milieu" '#{pane_dead}')" = 1 && ok "volet arrêté : reste affiché (mort)" || echec "volet arrêté : disparu ?"
egal "volet arrêté : toujours 3 volets" "$(TT list-panes -s -t "$(sid_de collecte)" | wc -l)" "3"
CT demarrer > /dev/null 2>&1
V2="$(volets "$(sid_de collecte)")"
egal "demarrer : le volet arrêté est relancé" "$(echo "$V2" | sed -n 2p | awk '{ print $3 }')" "0"
egal "demarrer : les deux autres volets n'ont pas bougé" "$(echo "$V2" | sed -n '1p;3p')" "$(echo "$V1" | sed -n '1p;3p')"

# ------------------------------------------------------------------ lecture seule
titre "7. un client « attach -r » ne peut rien taper (pseudo-terminal donné par script)"
if command -v script > /dev/null; then
    # Témoin : une session qui écrit dans un fichier ce qu'on y tape.
    TT new-session -d -s essai-ro -x 80 -y 20 "cat > $BAC/t/tape.txt"
    tape() {   # <-r ou rien> <session> <texte à taper>
        local fifo="$BAC/t/fifo.$RANDOM"; mkfifo "$fifo"
        ( sleep 1; printf '%b' "$3"; sleep 1; printf '\002d'; sleep 1 ) > "$fifo" &
        TERM=xterm timeout 15 script -qfec "tmux -L $SOCK attach $1 -t $2" /dev/null < "$fifo" > "$BAC/t/script.out" 2>&1
        local c=$?; rm -f "$fifo"; return $c
    }
    tape -r essai-ro 'abc\r'; c=$?
    egal "attach -r : Ctrl-b d détache le client (script sort seul)" "$c" "0"
    egal "attach -r : rien n'est arrivé au programme" "$(cat "$BAC/t/tape.txt")" ""
    tape "" essai-ro 'xyz\r'
    egal "témoin, attach sans -r : la frappe arrive (la méthode marche)" "$(cat "$BAC/t/tape.txt")" "xyz"
    TT kill-session -t essai-ro
    # Dans « collecte » : Ctrl-b c (fenêtre), Ctrl-b % (volet), Ctrl-b x y (fermer), Ctrl-b & y, q, Ctrl-C.
    tape -r collecte '\002c\002%\002xy\002&yq\003\r'
    egal "attach -r collecte : toujours 1 fenêtre" "$(TT list-windows -t "$(sid_de collecte)" | wc -l)" "1"
    egal "attach -r collecte : mêmes 3 volets, vivants, mêmes processus" "$(volets "$(sid_de collecte)")" "$V2"
else
    echo "  NON TESTÉ  « script » (util-linux) absent : pas de pseudo-terminal pour attacher un client"
fi

# ------------------------------------------------------------------ arrêts
titre "8. arreter-garde (avec un faux pilote vivant : « oui » demandé), arreter-vue"
pilote_on "$TD" essai-t "$TP"; PILOTE_T=$PILOTE
echo non | CT arreter-garde > "$BAC/t/ag1.txt" 2>&1; code=$?
[ "$code" != 0 ] && ok "arreter-garde, réponse « non » : refusé (code $code)" || echec "arreter-garde « non » : code 0"
contient "arreter-garde : demande de taper « oui »" "$(cat "$BAC/t/ag1.txt")" "Taper « oui »"
contient "arreter-garde : nomme le pilote vivant" "$(cat "$BAC/t/ag1.txt")" "essai-t (pid $PILOTE_T)"
egal "arreter-garde « non » : « garde » toujours là" "$(sessions)$(sessions_g)" "collecte etrangere garde "
CT etat > "$BAC/t/etat-pil.txt" 2>&1
contient "etat : le pilote vivant est nommé" "$(cat "$BAC/t/etat-pil.txt")" "pilote(s) vivant(s) : essai-t (pid $PILOTE_T)"
# Recherche du pilote impossible (dossier proc absent) : « oui » demandé quand même.
echo non | CT_PROC="$BAC/t/proc-absent" CT arreter-garde > "$BAC/t/ag0.txt" 2>&1; code=$?
[ "$code" != 0 ] && ok "arreter-garde, pilote introuvable, « non » : refusé (code $code)" || echec "arreter-garde, recherche en échec : code 0"
contient "arreter-garde, recherche en échec : le dit et demande « oui »" "$(cat "$BAC/t/ag0.txt")" "impossible de savoir si un pilote campagne.sh tourne"
egal "arreter-garde, recherche en échec : « garde » toujours là" "$(sessions_g)" "garde "
egal "arreter-garde « non » : le gardien n'a reçu aucun signal" "$(grep -c '^SIGNAL' "$FGL")" "0"
echo oui | CT arreter-garde > "$BAC/t/ag2.txt" 2>&1; code=$?
egal "arreter-garde « oui » : code" "$code" "0"
egal "arreter-garde « oui » : seule « garde » est fermée" "$(sessions)$(sessions_g)" "collecte etrangere "
contient "arreter-garde : le gardien a reçu TERM (il finit sa minute)" "$(cat "$FGL")" "SIGNAL 15"
contient_pas "arreter-garde : la session s'est fermée d'elle-même (pas de kill-session)" "$(cat "$BAC/t/ag2.txt")" "fermée de force"
etrangere_intacte "après arreter-garde"
CT etat > "$BAC/t/etat-sans.txt" 2>&1
contient "etat, garde absente et pilote vivant : dit FORT" "$(cat "$BAC/t/etat-sans.txt")" "un PILOTE tourne SANS GARDIEN : essai-t (pid $PILOTE_T)"
pilote_off "$PILOTE_T" "$TP"

CT arreter-vue > "$BAC/t/av.txt" 2>&1; code=$?
egal "arreter-vue : code" "$code" "0"
egal "arreter-vue : seule « collecte » est fermée" "$(sessions)$(sessions_g)" "etrangere "
etrangere_intacte "après arreter-vue"

titre "9. demarrer --agir, puis arreter-garde sans pilote (aucune question)"
: > "$FGL"
CT demarrer --agir > /dev/null 2>&1
attendre 5 grep -q '^DEPART' "$FGL" && ok "demarrer --agir : garde.py relancé" || echec "demarrer --agir : pas de départ"
egal "demarrer --agir : garde.py reçoit --agir" "$(grep '^DEPART' "$FGL" | head -1 | awk '{ print $3 }')" "--agir"
contient "etat : gardien AVEC --agir" "$(CT etat 2>&1)" "AVEC --agir (mode AGIR"
CT arreter-garde < /dev/null > "$BAC/t/ag3.txt" 2>&1; code=$?
egal "arreter-garde sans pilote : code" "$code" "0"
contient_pas "arreter-garde sans pilote : aucune question" "$(cat "$BAC/t/ag3.txt")" "Taper « oui »"
CT arreter-vue > /dev/null 2>&1
egal "fin : seule la session étrangère reste" "$(sessions)$(sessions_g)" "etrangere "
etrangere_intacte "à la fin"
egal "aucun faux garde.py ne reste" "$(pgrep -fc "$TD/garde.py")" "0"

titre "9b. la boucle du gardien : verrou pris par un autre, garde.py qui sort avec le code 3"
boucle_essai() {   # <secondes> [variables…] : la boucle seule, arrêtée par TERM au bout du temps
    local duree="$1"; shift
    env HOME="$BAC/t/home" PATH="$PATH_SUIVI" GARDE_DOSSIER="$TG" GARDE_FAUX_LOG="$FGL" \
        COLLECTE_RELANCE=0.1 COLLECTE_ATTENTE_VERROU=0.5 "$@" \
        timeout 30 bash "$TD/collecte-tmux.sh" _boucle-garde > "$BAC/t/boucle.txt" 2>&1 &
    local pb=$!
    sleep "$duree"; kill -TERM "$pb" 2>/dev/null; wait "$pb" 2>/dev/null
}
: > "$FGL"; : > "$TG/sortie-tmux.log"
flock "$TG/garde.verrou" sleep 4 & PV=$!
sleep 0.3
boucle_essai 2.5
egal "verrou pris : garde.py n'est pas lancé" "$(departs)" "0"
egal "verrou pris : noté UNE fois dans sortie-tmux.log (5 essais)" "$(grep -c 'tient le verrou' "$TG/sortie-tmux.log")" "1"
wait "$PV" 2>/dev/null
: > "$FGL"; : > "$TG/sortie-tmux.log"
flock "$TG/garde.verrou" sleep 1 & PV=$!
sleep 0.3
boucle_essai 3
egal "verrou rendu : garde.py part, une seule fois" "$(departs)" "1"
contient "verrou rendu : noté" "$(cat "$TG/sortie-tmux.log")" "le verrou est libre : départ du gardien"
contient "boucle arrêtée par TERM : le gardien a reçu TERM" "$(cat "$FGL")" "SIGNAL 15"
wait "$PV" 2>/dev/null
: > "$FGL"
boucle_essai 1.4 GARDE_FAUX_CODE=3
n=$(departs)
[ "$n" -ge 1 ] && [ "$n" -le 3 ] && ok "code 3 : nouvel essai après l'attente du verrou, pas toutes les 0,1 s ($n départs en 1,4 s)" \
    || echec "code 3 : $n départs en 1,4 s"
contient "code 3 : expliqué" "$(cat "$TG/sortie-tmux.log")" "code 3 : une autre garde tourne déjà"
egal "aucune boucle ni faux garde.py ne reste" "$(pgrep -fc "$TD/(garde.py|collecte-tmux.sh)")" "0"

TT kill-server 2>/dev/null; TTG kill-server 2>/dev/null
attendre 5 sh -c "! tmux -L $SOCK list-sessions && ! tmux -L $SOCK-garde list-sessions" \
    && ok "kill-server des deux serveurs du test : plus aucune session" || echec "serveur du test encore là"
egal "aucun processus du test ne reste (suivi, tail, boucle)" "$(pgrep -fc "$BAC/t/")" "0"
if [ -s "$BAC/interdit.log" ]; then echec "appels interdits (tmux) : $(cat "$BAC/interdit.log")"; else ok "ni ssh ni kubectl appelés par la vue"; fi

# ==============================================================================
titre "10. garde_veille_master.sh avec un HOME factice"
# ==============================================================================
VH="$BAC/veille/home"; mkdir -p "$VH"
VEILLE="$CHANTIER/apps/garde_veille_master.sh"
veille() {   # <HH:MM:SS>
    HOME="$VH" PATH="$PATH_SUIVI" VEILLE_MAINTENANT="2026-10-01T$1Z" timeout 10 bash "$VEILLE"
}
battement() { echo "2026-10-01T$1Z" > "$VH/garde.battement"; }
lignes() { grep -c "$1" "$VH/alertes-garde.txt" 2>/dev/null || true; }
battement 11:59:30; veille 12:00:00; code=$?
egal "battement frais : code" "$code" "0"
[ ! -e "$VH/alertes-garde.txt" ] && [ ! -e "$VH/alertes-garde.etat" ] && ok "battement frais : rien écrit" || echec "battement frais : écrit quelque chose"
battement 11:56:00; veille 12:00:00
egal "vieux de 4 min : une ALERTE" "$(lignes ' ALERTE gardien muet depuis 4 min')" "1"
contient "ALERTE : instant et dernier battement" "$(cat "$VH/alertes-garde.txt")" "2026-10-01T12:00:00Z ALERTE gardien muet depuis 4 min (dernier battement : 2026-10-01T11:56:00Z)"
veille 12:05:00
egal "5 min plus tard : pas de doublon" "$(grep -c . "$VH/alertes-garde.txt")" "1"
veille 12:55:00
egal "55 min plus tard : pas encore de rappel" "$(grep -c . "$VH/alertes-garde.txt")" "1"
veille 13:00:00
egal "une heure plus tard : un rappel" "$(lignes 'ALERTE (rappel) gardien muet depuis 64 min')" "1"
veille 13:05:00
egal "après le rappel : rien de plus" "$(grep -c . "$VH/alertes-garde.txt")" "2"
battement 13:09:30; veille 13:10:00
egal "battement revenu : une FIN" "$(lignes ' FIN gardien de nouveau vivant')" "1"
[ ! -e "$VH/alertes-garde.etat" ] && ok "FIN : l'état de l'incident est effacé" || echec "FIN : état encore là"
battement 13:14:30; veille 13:15:00
egal "battement frais ensuite : rien de plus" "$(grep -c . "$VH/alertes-garde.txt")" "3"
rm -f "$VH/garde.battement"; veille 13:20:00
egal "battement absent : une ALERTE" "$(lignes 'ALERTE gardien muet : aucun battement')" "1"
echo "garbage" > "$VH/garde.battement"; touch -d "2026-10-01T13:24:00Z" "$VH/garde.battement"; veille 13:25:00
egal "contenu illisible, fichier récent : FIN (date du fichier)" "$(lignes 'FIN gardien de nouveau vivant (battement : 2026-10-01T13:24:00Z (date du fichier')" "1"
contient "--etat : lisible, sans écrire" "$(HOME="$VH" VEILLE_MAINTENANT=2026-10-01T13:26:00Z bash "$VEILLE" --etat 2>&1)" "gardien vivant"
egal "--etat n'écrit rien" "$(grep -c . "$VH/alertes-garde.txt")" "5"
echo "  alertes-garde.txt :"; sed 's/^/      /' "$VH/alertes-garde.txt"
if [ -s "$BAC/interdit.log" ]; then echec "appels interdits (veille) : $(cat "$BAC/interdit.log")"; else ok "la veille n'appelle ni ssh ni kubectl"; fi

# ==============================================================================
echo
echo "══ $REUSSIS réussis, $RATES ratés"
[ "$RATES" = 0 ]
