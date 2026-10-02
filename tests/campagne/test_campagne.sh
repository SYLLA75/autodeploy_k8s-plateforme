#!/bin/bash
# ==============================================================================
#  tests/campagne/test_campagne.sh — le pilote face à un faux master
# ==============================================================================
#
#  Aucun vrai ssh, aucun cluster : un FAUX ssh, en tête du PATH du pilote, note
#  chaque commande reçue (une ligne par appel) et répond selon le script et
#  l'action appelés. Un faux « date » fait passer le temps plus vite (FAUX_VITESSE
#  fois) et un faux « sleep » dort d'autant moins : une campagne de quelques
#  minutes dure quelques secondes, et le sommeil en arrière-plan + wait du
#  pilote reste un vrai processus qu'on peut tuer.
#
#  Chaque campagne de test tourne depuis une COPIE (campagne.sh + apps/journal.sh)
#  dans un dossier temporaire : campagnes/ et journaux/ s'écrivent là. Chaque
#  campagne est bornée : un pilote qui pend est un ÉCHEC, tué au bout du délai.
#
#  Usage :  bash tests/campagne/test_campagne.sh
#  Code 0 seulement si tout passe.
#
#  Variables reconnues :
#      CAMPAGNE_ORIGINAL  (défaut: ~/autodeploy_k8s-phases/campagne.sh) la référence, lue seulement
#      GARDER=1           garde le dossier temporaire à la fin
#
#  Noms des causes : le nouveau pilote reçoit les noms anglais (consumer-slowdown…),
#  l'original les anciens (lenteur…). Pour comparer les deux, la suite d'appels et
#  le compte rendu de l'original sont traduits (lenteur → consumer-slowdown) avant
#  la comparaison. Les anciens noms passés au nouveau pilote (alias) sont testés en (q).
# ==============================================================================
set -uo pipefail
set -m   # chaque pilote dans son propre groupe : on le tue en entier s'il pend

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHANTIER="$(cd "$ICI/../.." && pwd)"
ORIGINAL="${CAMPAGNE_ORIGINAL:-$HOME/autodeploy_k8s-phases/campagne.sh}"
VRAI_DATE="$(command -v date)"; VRAI_SLEEP="$(command -v sleep)"
export VRAI_DATE VRAI_SLEEP
BAC="$(mktemp -d "${TMPDIR:-/tmp}/test_campagne.XXXXXX")"
FAUX="$BAC/bin"; mkdir -p "$FAUX" "$BAC/master_journaux"

REUSSIS=0; RATES=0
ok()    { echo "  OK     $*"; REUSSIS=$((REUSSIS + 1)); }
echec() { echo "  ÉCHEC  $*"; RATES=$((RATES + 1)); }
verifie() {   # <description> <commande…> — OK si la commande réussit
    local d="$1"; shift
    if "$@"; then ok "$d"; else echec "$d"; fi
}
titre() { echo; echo "── $*"; }

# ------------------------------------------------------------------ les faux
cat > "$FAUX/ssh" <<'EOF'
#!/bin/bash
# Faux ssh : note la commande, répond selon le script et l'action appelés.
# À côté (FAUX_LOG.env) : ses options, la commande qui l'a lancé, sa session.
opts=""
while [ $# -gt 0 ]; do case "$1" in -o) opts="$opts $2"; shift 2 ;; -*) opts="$opts $1"; shift ;; *) break ;; esac; done
hote="$1"; shift; cmd="$*"
printf '%s\t%s\n' "$("$VRAI_DATE" +%s.%N)" "$cmd" >> "$FAUX_LOG"
printf '%s\t%s\t%s\t%s\n' "${opts# }" "$(ps -o args= -p "$PPID")" "$(ps -o sid= -p $$ | tr -d ' ')" "$cmd" >> "$FAUX_LOG.env"
if [ -n "${FAUX_INJOIGNABLE:-}" ]; then echo "ssh: connect to host $hote port 22: Connection refused" >&2; exit 255; fi
# Un appel qui pend : le processus EST le sommeil, un TERM de timeout le tue.
if [ -n "${FAUX_PEND:-}" ] && [[ "$cmd" =~ $FAUX_PEND ]]; then exec "$VRAI_SLEEP" 100000; fi
suivant() {   # <nom> <suite de codes> → le code suivant de la suite, 0 une fois épuisée
    local f="$FAUX_ETAT/$1.n" n=0; [ -f "$f" ] && n=$(cat "$f"); echo $((n + 1)) > "$f"
    local codes=($2); echo "${codes[$n]:-0}"
}
case "$cmd" in
    true) exit 0 ;;
    *"panne.sh' etat"*)    echo "  [panne] Aucune injection en cours."; echo "  [panne] OK  rien d'injecté, rien de résiduel" ;;
    *"panne.sh' leader"*)  echo "role=leader, adresse 10.0.0.9, tsdb-mysql-leader → 10.0.0.9" ;;
    *"panne.sh' verifier"*) echo "  [panne] OK  prêt pour « x »" ;;
    *"panne.sh' temoin court"*)
        echo "  file food_delivery : 0 en attente, 0 non acquitté(s), 3 consommateur(s)"
        echo "  base : tsdb-mysql-0 est le leader (role=leader)" ;;
    *"panne.sh' temoin"*)  echo "  instant : faux"; echo "  file food_delivery : 0 en attente" ;;
    *"panne.sh' injecter"*) echo "  [panne] OK  injectée" ;;
    *"panne.sh' retirer"*) [ -z "${FAUX_LENT_RETIRER:-}" ] || "$VRAI_SLEEP" "$FAUX_LENT_RETIRER"
                           touch "$FAUX_ETAT/retrait.fini"
                           [ -z "${FAUX_RETIRER_ECHEC:-}" ] || { echo "  [panne] ATTENTION: le retrait a échoué"; exit 1; }
                           echo "  [panne] OK  retirée" ;;
    *"loadgen.sh' bilan"*)
        c=$(suivant bilan "${FAUX_BILAN:-}")
        [ "$c" = 0 ] && echo "  Tous les parcours passent." || echo "  1 parcours en défaut — NE LANCE PAS DE CAMPAGNE."
        exit "$c" ;;
    *"loadgen.sh' "*)      echo "  [loadgen] Charge confirmée" ;;
    *"collecte.sh' fenetre"*) echo "  range: faux" ;;
    *"collecte.sh' "*)     echo "     COLLECTE EN MARCHE" ;;
    *"consommateur.sh' verifier"*)
        c=$(suivant verifier "${FAUX_VERIFIER:-}")
        echo "  retard par réplique (attendu : 140ms) : faux, code $c"; exit "$c" ;;
    *"consommateur.sh' reposer"*) echo "  [consommateur] Nouvelle pose du retard de 140 ms" ;;
    *"consommateur.sh' etat"*) echo "  temps de service : 140 ms de retard par échange" ;;
    *"donnees.sh' "*)      echo "  orders                0 lignes" ;;
    *"kubectl get nodes"*)
        if [ -n "${FAUX_NOEUDS:-}" ]; then printf '%b\n' "$FAUX_NOEUDS"
        else printf 'master Ready control-plane 9d v1.30\nworkers1 Ready <none> 9d v1.30\nworkers2 Ready <none> 9d v1.30\n'; fi ;;
    *"kubectl get pods"*)  printf 'ts-delivery-1 workers1 Running 0 <none>\nts-delivery-2 workers2 Running 0 <none>\n' ;;
    *"find ."*)            tar -c -C "$FAUX_MASTER_JOURNAUX" . ;;
    *"cat "*)              printf '# instant\tfaux\n' ;;
    *) echo "faux ssh : commande inconnue : $cmd" >&2; exit 99 ;;
esac
exit 0
EOF
cat > "$FAUX/date" <<'EOF'
#!/bin/bash
# Faux date : depuis FAUX_T0, le temps passe FAUX_VITESSE fois plus vite.
for a in "$@"; do case "$a" in -d|-d*|--date*) exec "$VRAI_DATE" "$@" ;; esac; done
n=$("$VRAI_DATE" +%s%N)
exec "$VRAI_DATE" -d "@$(( FAUX_T0 + (n / 1000000 - FAUX_T0 * 1000) * FAUX_VITESSE / 1000 ))" "$@"
EOF
cat > "$FAUX/sleep" <<'EOF'
#!/bin/bash
# Faux sleep : FAUX_VITESSE fois plus court ; le processus EST le sommeil.
exec "$VRAI_SLEEP" "$(awk -v s="$1" -v k="$FAUX_VITESSE" 'BEGIN { printf "%.3f", s / k }')"
EOF
chmod +x "$FAUX/ssh" "$FAUX/date" "$FAUX/sleep"
printf '# instant\tpalier\n' > "$BAC/master_journaux/paliers.tsv"
echo "journal du master" > "$BAC/master_journaux/panne-faux.log"

# ------------------------------------------------------------------ les outils
# preparer <cas> [script] — un dossier neuf avec sa copie du pilote ; pose D.
preparer() {
    D="$BAC/$1"; mkdir -p "$D/apps" "$D/faux"
    cp "${2:-$CHANTIER/campagne.sh}" "$D/campagne.sh"
    cp "$CHANTIER/apps/journal.sh" "$D/apps/journal.sh"
    : > "$D/appels.log"
}

# lancer <args du pilote…> — en arrière-plan, depuis D, avec les faux ; pose PID.
# Les FAUX_* et CAMPAGNE_PLAFOND_* sont lus dans l'environnement du moment.
lancer() {
    PATH="$FAUX:$PATH" command -v ssh | grep -qx "$FAUX/ssh" \
        || { echo "  ÉCHEC  le faux ssh n'est pas en tête du PATH : arrêt"; exit 1; }
    (
        cd "$D" || exit 99
        export FAUX_LOG="$D/appels.log" FAUX_ETAT="$D/faux" FAUX_MASTER_JOURNAUX="$BAC/master_journaux"
        export FAUX_T0; FAUX_T0=$("$VRAI_DATE" +%s)
        export FAUX_VITESSE="${VITESSE:-60}"
        # SANS_SET_M=1 : lancé comme le ferait un script sans « set -m » (« … & »)
        [ -z "${SANS_SET_M:-}" ] || exec env -u JOURNAL_FICHIER -u JOURNAL_OFF PATH="$FAUX:$PATH" \
            bash -c 'bash "$0" "$@" & wait $!' "$D/campagne.sh" "$@"
        exec env -u JOURNAL_FICHIER -u JOURNAL_OFF PATH="$FAUX:$PATH" bash "$D/campagne.sh" "$@"
    ) > "$D/sortie.txt" 2>&1 &
    PID=$!
    T_LANCE=$("$VRAI_DATE" +%s.%N)
}

# attendre_fin <secondes> — attend le pilote ; pose CODE (« pend » s'il a fallu le tuer)
# et T_FIN. Tout ce qui reste de son groupe est tué ensuite.
attendre_fin() {
    local i=0 lim=$(( $1 * 20 ))
    while kill -0 "$PID" 2>/dev/null && [ "$(ps -o stat= -p "$PID" 2>/dev/null | cut -c1)" != Z ]; do
        if [ "$i" -ge "$lim" ]; then
            kill -9 -- "-$PID" 2>/dev/null; wait "$PID" 2>/dev/null; CODE=pend
            T_FIN=$("$VRAI_DATE" +%s.%N); return 1
        fi
        "$VRAI_SLEEP" 0.05; i=$((i + 1))
    done
    wait "$PID" 2>/dev/null; CODE=$?
    T_FIN=$("$VRAI_DATE" +%s.%N)
    kill -9 -- "-$PID" 2>/dev/null
    return 0
}

attendre_appel() {   # <regex> <secondes> — jusqu'à ce que le faux master ait reçu cet appel
    local i=0
    until grep -qE -- "$1" "$D/appels.log" 2>/dev/null; do
        [ "$i" -lt $(( $2 * 20 )) ] || return 1
        "$VRAI_SLEEP" 0.05; i=$((i + 1))
    done
}

appels() { cut -f2- "$D/appels.log"; }
enveloppes() { cat "$D/appels.log.env" 2>/dev/null; }                 # options <tab> lanceur <tab> session <tab> commande                               # les commandes seules
sans_enveloppe() { sed -E 's/timeout -k 10 [0-9]+ //g'; }            # le timeout côté master retiré
sans_instant() { sed -E "s/-newermt '@[0-9]+'/-newermt '@<T_PILOTE>'/"; }   # l'heure de départ du pilote
nb_appels() { appels | grep -cE -- "$1"; }
duree() { awk -v a="$1" -v b="$2" 'BEGIN { printf "%.1f", b - a }'; }
instant_appel() { grep -E -- "$1" "$D/appels.log" | head -1 | cut -f1; }
instant_apres() { awk -F'\t' -v m="$1" 'f { print $1; exit } $2 ~ m { f = 1 }' "$D/appels.log"; }

# fin_unique <nom> <code> <motif> — le pilote est sorti avec ce code, et une seule
# ligne FIN, 5 champs séparés par des tabulations, dit le même code et ce motif
fin_unique() {
    local f="$D/journaux/fins.tsv"
    [ "$CODE" = "$2" ] && [ -f "$f" ] && [ "$(wc -l < "$f")" -eq 1 ] \
        && awk -F'\t' -v n="$1" -v c="$2" -v m="$3" \
               'NF == 5 && $1 == "FIN_CAMPAGNE" && $2 == n && $3 == c && $5 == m \
                && $4 ~ /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$/ {ok = 1}
                END {exit !ok}' "$f" && return 0
    echo "         code du pilote : $CODE ; fins.tsv :"; sed 's/\t/<TAB>/g; s/^/           /' "$f" 2>/dev/null
    return 1
}
# fin_ligne <nom> <code> <motif> — une seule ligne FIN, avec ce code-là (pas celui du processus)
fin_ligne() {
    local f="$D/journaux/fins.tsv"
    [ -f "$f" ] && [ "$(wc -l < "$f")" -eq 1 ] \
        && awk -F'\t' -v n="$1" -v c="$2" -v m="$3" 'NF == 5 && $2 == n && $3 == c && $5 == m {ok = 1} END {exit !ok}' "$f" && return 0
    sed 's/\t/<TAB>/g; s/^/           /' "$f" 2>/dev/null; return 1
}
egal() { [ "$1" = "$2" ] || { echo "         lu     : $1"; echo "         attendu: $2"; return 1; }; }
appel_avec() { grep -E -- "$1" "$D/appels.log" | grep -qF -- "$2"; }     # <regex de l'appel> <texte exact>
appel_sans_timeout() { grep -qE -- "$1" "$D/appels.log" && ! grep -E -- "$1" "$D/appels.log" | grep -q timeout; }
groupe_vide() { ! pgrep -g "$1" >/dev/null; }
dans_sortie() { grep -qF -- "$1" "$D/sortie.txt"; }
dans_journal() { cat "$D"/journaux/campagne-*.log 2>/dev/null | grep -qF -- "$1"; }
dans_yaml() { grep -qE -- "$2" "$D/campagnes/$1/campagne.yaml" 2>/dev/null; }   # <nom> <regex>
yaml_existe() { [ -s "$D/campagnes/$1/campagne.yaml" ]; }
plus_petit() { awk -v a="$1" -v b="$2" 'BEGIN { exit !(a < b) }'; }
entre() { awk -v x="$1" -v a="$2" -v b="$3" 'BEGIN { exit !(x >= a && x < b) }'; }
montrer() { echo "         --- fin de la sortie du pilote ($D/sortie.txt) :"; tail -n "${1:-15}" "$D/sortie.txt" | sed 's/^/         | /'; }

remise_a_zero() {
    unset FAUX_INJOIGNABLE FAUX_PEND FAUX_VERIFIER FAUX_NOEUDS FAUX_LENT_RETIRER FAUX_BILAN FAUX_RETIRER_ECHEC SANS_SET_M
    unset CAMPAGNE_PLAFOND_LECTURE CAMPAGNE_PLAFOND_LONGUE CAMPAGNE_PLAFOND_GESTE \
          CAMPAGNE_PLAFOND_SCALE CAMPAGNE_PLAFOND_INJECTER CAMPAGNE_PLAFOND_RETIRER
    VITESSE=60
}

echo "dossier de test : $BAC"
echo "faux ssh        : $(PATH="$FAUX:$PATH" command -v ssh)"
[ -r "$ORIGINAL" ] || { echo "ÉCHEC : original illisible ($ORIGINAL)"; exit 1; }
bash -n "$CHANTIER/campagne.sh" || { echo "ÉCHEC : bash -n campagne.sh"; exit 1; }

PANNE_COURTE=(--profil "10:2,25:4" --panne consumer-slowdown --a 3 --duree 2)   # deux paliers : le retour au premier aussi
PANNE_COURTE_ORIGINAL=(--profil "10:2,25:4" --panne lenteur --a 3 --duree 2)     # la même, sous l'ancien nom
# Ce que l'original écrit, avec le nom anglais de la cause (pour comparer au nouveau).
traduire_original() { sed -E "s/(panne\.sh' (injecter|verifier)) lenteur/\1 consumer-slowdown/; s/cause: lenteur/cause: consumer-slowdown/"; }
VERIF="JOURNAL_OFF=1 bash '/home/ubuntu/autodeploy/apps/consommateur.sh' verifier"

# ============================================================== (a) nominal
titre "(a) campagne nominale courte (deux paliers, une panne) : original puis nouveau, mêmes conditions"
remise_a_zero
preparer a-original "$ORIGINAL"; lancer a1 "${PANNE_COURTE_ORIGINAL[@]}"; attendre_fin 60
D_ORIG="$D"; CODE_ORIG="$CODE"
preparer a-nouveau; lancer a1 "${PANNE_COURTE[@]}"; attendre_fin 60
verifie "original : code 0 (référence valable)" egal "$CODE_ORIG" 0
verifie "nouveau : code 0 (lu : $CODE)" egal "$CODE" 0
verifie "nouveau : une seule ligne FIN « termine », 5 champs, tabulations" fin_unique a1 0 termine
# La suite attendue : celle de l'original, plus get nodes et verifier avant la
# collecte, plus verifier avant chaque injection.
cut -f2- "$D_ORIG/appels.log" | awk -v v="$VERIF" '
    /collecte\.sh. demarrer/ { print "kubectl get nodes --no-headers"; print v }
    /panne\.sh. injecter/    { print v }
    { print }' | sans_instant | traduire_original > "$D/attendu.txt"
appels | sans_enveloppe | sans_instant > "$D/obtenu.txt"
if diff -u "$D/attendu.txt" "$D/obtenu.txt" > "$D/suite.diff"; then
    ok "suite des appels = original + get nodes + verifier (départ) + verifier (avant l'injection) — $(wc -l < "$D/obtenu.txt") appels"
else
    echec "suite des appels différente de l'attendu :"; sed 's/^/         /' "$D/suite.diff"
fi
verifie "lecture bornée sur le master : consommateur.sh verifier" appel_avec "consommateur\\.sh' verifier" "JOURNAL_OFF=1 timeout -k 10 120 bash"
verifie "lecture bornée sur le master : panne.sh etat"           appel_avec "panne\\.sh' etat" "JOURNAL_OFF=1 timeout -k 10 120 bash"
verifie "lecture bornée sur le master : panne.sh temoin (complet, 300 s)" appel_avec "panne\\.sh' temoin\$" "JOURNAL_OFF=1 timeout -k 10 300 bash"
verifie "lecture bornée sur le master : kubectl get nodes"       appel_avec "kubectl get nodes" "timeout -k 10 120 kubectl get nodes"
verifie "lecture bornée sur le master : find | tar (les deux)"   appel_avec "find \\." "timeout -k 10 300 find . -maxdepth 1"
verifie "    … et le tar"                                       appel_avec "find \\." "| timeout -k 10 300 tar -c"
for g in "panne\\.sh' injecter" "panne\\.sh' retirer" "loadgen\\.sh' scale" "loadgen\\.sh' reset" \
         "collecte\\.sh' demarrer" "collecte\\.sh' arreter" "donnees\\.sh' purger"; do
    verifie "geste jamais borné sur le master : ${g//\\/}" appel_sans_timeout "$g"
done
verifie "le retour au premier palier fait partie de la suite comparée (scale 10 après le retrait)" \
    egal "$(appels | grep -oE "panne.sh' retirer|loadgen.sh' scale 10" | tail -2 | paste -sd, -)" "panne.sh' retirer,loadgen.sh' scale 10"
verifie "options ssh sur CHAQUE appel : BatchMode, ConnectTimeout 15, ServerAlive 15 × 4" \
    egal "$(enveloppes | cut -f1 | sort -u)" "BatchMode=yes ConnectTimeout=15 ServerAliveInterval=15 ServerAliveCountMax=4"
verifie "CHAQUE appel passe par « timeout --foreground -k 30 <plafond> ssh » ici" \
    egal "$(enveloppes | cut -f2 | grep -cvE '^timeout --foreground -k 30 [1-9][0-9]* ssh ')" 0
verifie "plafonds par défaut : injecter 1200, retirer 2400, scale 600, lecture 120" \
    egal "$(enveloppes | awk -F'\t' '$4 ~ /panne.sh. (injecter|retirer)|loadgen.sh. scale 10|panne.sh. etat/ {split($2, a, " "); sub(/.*apps\//, "", $4); split($4, b, " "); print b[1], b[2], a[5]}' | sort -u | paste -sd, -)" \
         "loadgen.sh' scale 600,panne.sh' etat 120,panne.sh' injecter 1200,panne.sh' retirer 2400"
verifie "le déroulé porte machines_pretes"  dans_yaml a1 "action: machines_pretes, machines: 3"
verifie "le déroulé porte reglage_verifie"  dans_yaml a1 "action: reglage_verifie, resultat: ok"
verifie "nom anglais au master : panne.sh verifier consumer-slowdown" appel_avec "panne\\.sh' verifier" "verifier consumer-slowdown"
verifie "nom anglais au master : panne.sh injecter consumer-slowdown" appel_avec "panne\\.sh' injecter" "injecter consumer-slowdown --duree 2"
verifie "compte rendu : « cause: consumer-slowdown » (en-tête et déroulé)" dans_yaml a1 "^  cause: consumer-slowdown$"
verifie "    … aucun ancien nom dans le compte rendu" bash -c "! grep -qwE 'lenteur|blocage|hote|reseau' '$D/campagnes/a1/campagne.yaml'"
normaliser() {
    grep -vE 'action: (machines_pretes|reglage_verifie)' "$1" \
        | sed -E 's/[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z/<instant>/g; s/[0-9]{4}-[0-9]{2}-[0-9]{2}/<date>/g; s/[0-9]{2}:[0-9]{2}/<hh:mm>/g'
}
if diff <(normaliser "$D_ORIG/campagnes/a1/campagne.yaml" | traduire_original) <(normaliser "$D/campagnes/a1/campagne.yaml") > "$D/yaml.diff"; then
    ok "compte rendu identique à celui de l'original (instants, nouvelles actions et nom anglais de la cause mis à part)"
else
    echec "compte rendu différent :"; sed 's/^/         /' "$D/yaml.diff"
fi

# ============================================================== (b) machine NotReady
titre "(b) une machine NotReady"
remise_a_zero; export FAUX_NOEUDS='master Ready control-plane 9d v1.30\nworkers3 NotReady <none> 9d v1.30\nworkers4 Ready,SchedulingDisabled <none> 9d v1.30'
preparer b; lancer b1 --profil "25:3"; attendre_fin 30
verifie "code 1 (lu : $CODE)" egal "$CODE" 1
verifie "ligne FIN depart_refuse" fin_unique b1 1 depart_refuse
verifie "collecte.sh demarrer jamais appelé" egal "$(nb_appels "collecte\\.sh' demarrer")" 0
verifie "la machine est nommée : workers3 (NotReady)" dans_sortie "workers3 (NotReady)"
verifie "la machine est nommée : workers4 (Ready,SchedulingDisabled)" dans_sortie "workers4 (Ready,SchedulingDisabled)"

# ============================================================== (c) verifier au départ
titre "(c) consommateur.sh verifier au départ"
remise_a_zero; export FAUX_VERIFIER="1 0"
preparer c1; lancer c1 --profil "25:3"; attendre_fin 30
verifie "1, reposer, 0 → départ : code 0 (lu : $CODE), FIN termine" fin_unique c1 0 termine
verifie "1, reposer, 0 → reposer appelé une fois" egal "$(nb_appels "consommateur\\.sh' reposer")" 1
verifie "1, reposer, 0 → verifier, reposer, verifier, puis collecte.sh demarrer" \
    egal "$(appels | grep -E "consommateur|collecte\\.sh' demarrer" | sed -E "s/.*apps\\/([a-z.]+)' ([a-z]+).*/\\1 \\2/" | paste -sd, -)" \
         "consommateur.sh etat,consommateur.sh verifier,consommateur.sh reposer,consommateur.sh verifier,collecte.sh demarrer,consommateur.sh etat"
verifie "1, reposer, 0 → noté « reglage_verifie, resultat: repose »" dans_yaml c1 "action: reglage_verifie, resultat: repose"
for cas in "1 1:1" "3:0" "2:0"; do
    suite="${cas%%:*}"; reposer_attendu="${cas#*:}"
    remise_a_zero; export FAUX_VERIFIER="$suite"
    preparer "c-${suite// /-}"; lancer c2 --profil "25:3"; attendre_fin 30
    verifie "verifier « $suite » → refus : code 1 (lu : $CODE), FIN depart_refuse" fin_unique c2 1 depart_refuse
    verifie "verifier « $suite » → collecte jamais démarrée" egal "$(nb_appels "collecte\\.sh' demarrer")" 0
    verifie "verifier « $suite » → sortie de verifier affichée" dans_sortie "faux, code ${suite##* }"
    verifie "verifier « $suite » → reposer appelé $reposer_attendu fois" egal "$(nb_appels "consommateur\\.sh' reposer")" "$reposer_attendu"
done

# ============================================================== (d) verifier avant l'injection
titre "(d) verifier non nul juste avant l'injection (cause donnée par son ancien nom, « lenteur »)"
remise_a_zero; export FAUX_VERIFIER="0 1"
preparer d; lancer d1 --profil "10:2,25:4" --panne lenteur --a 3 --duree 1; attendre_fin 40
verifie "l'alias est dit : « lenteur → consumer-slowdown »" dans_sortie "lenteur → consumer-slowdown"
verifie "code 3 (lu : $CODE), ligne FIN reglage_absent" fin_unique d1 3 reglage_absent
verifie "panne.sh injecter jamais appelé" egal "$(nb_appels "panne\\.sh' injecter")" 0
verifie "verifier appelé juste après le témoin d'avant" \
    egal "$(appels | grep -A1 "panne.sh' temoin\$" | sed -n 2p | sans_enveloppe)" "$VERIF"
verifie "reposer jamais appelé" egal "$(nb_appels "consommateur\\.sh' reposer")" 0
verifie "ensuite : retour au premier palier (scale 10), fenetre et arrêt de la collecte" \
    egal "$(appels | awk '/consommateur.sh. verifier/ {n++} n == 2' \
            | grep -oE "loadgen.sh' scale 10|collecte.sh' (fenetre|arreter)" | paste -sd, -)" \
         "loadgen.sh' scale 10,collecte.sh' fenetre,collecte.sh' arreter"
verifie "compte rendu : « cause: consumer-slowdown, resultat: REFUSEE_REGLAGE »" dans_yaml d1 "action: injection, cause: consumer-slowdown, resultat: REFUSEE_REGLAGE"
verifie "compte rendu : l'en-tête porte le nom anglais"  dans_yaml d1 "^  cause: consumer-slowdown$"
verifie "le master reçoit le nom anglais (verifier)"     appel_avec "panne\\.sh' verifier" "verifier consumer-slowdown"
verifie "compte rendu : interrompue: oui"                dans_yaml d1 "^interrompue: oui"
verifie "compte rendu : injections_non_confirmees: 1"    dans_yaml d1 "injections_non_confirmees: 1"

# ============================================================== (e) un appel qui pend
titre "(e) un appel qui pend"
remise_a_zero; export FAUX_PEND="panne\\.sh' etat" CAMPAGNE_PLAFOND_LECTURE=3
preparer e-lecture; lancer e1 --profil "25:3"; attendre_fin 40
attente=$(duree "$(instant_appel "panne\\.sh' etat")" "$T_FIN")
verifie "lecture qui pend (panne.sh etat, plafond 3 s) → le pilote reprend la main en ${attente} s (3 ≤ … < 7)" entre "$attente" 3 7
verifie "lecture qui pend → chemin existant, départ refusé : code 1 (lu : $CODE), FIN depart_refuse" fin_unique e1 1 depart_refuse
verifie "lecture qui pend → message « n'a pas répondu en 3 s »" dans_sortie "« panne.sh etat » n'a pas répondu en 3 s"
verifie "lecture → la commande porte « timeout -k 10 3 » côté master" appel_avec "panne\\.sh' etat" "JOURNAL_OFF=1 timeout -k 10 3 bash"

remise_a_zero; export FAUX_PEND="loadgen\\.sh' scale" CAMPAGNE_PLAFOND_SCALE=3
preparer e-geste; lancer e2 --profil "25:3"; attendre_fin 40
attente=$(duree "$(instant_appel "loadgen\\.sh' scale")" "$(instant_apres "loadgen.sh' scale")")
verifie "geste qui pend (loadgen.sh scale, plafond 3 s) → appel suivant ${attente} s plus tard (3 ≤ … < 7)" entre "$attente" 3 7
verifie "geste qui pend → chemin existant : palier NON_CONFIRME" dans_yaml e2 "action: charge, voyageurs: 25, resultat: NON_CONFIRME"
verifie "geste qui pend → la campagne continue : code 0 (lu : $CODE), FIN termine" fin_unique e2 0 termine
verifie "geste → message « n'a pas répondu en 3 s »" dans_sortie "« loadgen.sh scale » n'a pas répondu en 3 s"
verifie "geste → commande envoyée telle quelle, AUCUN timeout côté master" \
    egal "$(appels | grep "loadgen.sh' scale")" "JOURNAL_OFF=1 bash '/home/ubuntu/autodeploy/apps/loadgen.sh' scale 25"

# ============================================================== (f) TERM, HUP
for sig in TERM HUP; do
    titre "(f) $sig envoyé au pilote pendant l'injection"
    remise_a_zero; VITESSE=20
    preparer "f-$sig"; lancer f1 --profil "25:6" --panne consumer-slowdown --a 1 --duree 3
    if attendre_appel "panne\\.sh' injecter" 30; then
        "$VRAI_SLEEP" 0.5; kill -"$sig" "$PID"
    else echec "$sig : l'injection n'a jamais été appelée"; fi
    attendre_fin 40
    verifie "$sig → code 130 (lu : $CODE), une seule ligne FIN interrompu_$sig" fin_unique f1 130 "interrompu_$sig"
    verifie "$sig → panne.sh retirer appelé une fois" egal "$(nb_appels "panne\\.sh' retirer")" 1
    verifie "$sig → compte rendu : interrompue: oui" dans_yaml f1 "^interrompue: oui"
    verifie "$sig → compte rendu : retrait, motif: interruption" dans_yaml f1 "action: retrait, motif: interruption"
    [ "$sig" = HUP ] && verifie "HUP → le nettoyage s'écrit dans le journal du pilote" dans_journal "campagne « f1 » INTERROMPUE"
done

# ============================================================== (g) kill -INT pendant une longue attente
titre "(g) kill -INT au pid du pilote SEUL pendant une longue attente"
remise_a_zero; VITESSE=2      # 2 min jusqu'au contrôle = 60 s réelles d'attente
preparer g-original "$ORIGINAL"; lancer g0 --profil "25:30"
if attendre_appel "loadgen\\.sh' scale" 30; then "$VRAI_SLEEP" 1; kill -INT "$PID"; fi
"$VRAI_SLEEP" 5
verifie "(contraste) l'original n'a pas traité le kill -INT au bout de 5 s (sleep au premier plan)" kill -0 "$PID"
kill -9 -- "-$PID" 2>/dev/null; wait "$PID" 2>/dev/null
preparer g; lancer g1 --profil "25:30"; t_kill=0
if attendre_appel "loadgen\\.sh' scale" 30; then
    "$VRAI_SLEEP" 1; t_kill=$("$VRAI_DATE" +%s.%N); kill -INT "$PID"
fi
attendre_fin 30
reaction=$(duree "$t_kill" "$T_FIN")
verifie "kill -INT traité en ${reaction} s (< 5 s ; il restait ~58 s de sommeil)" plus_petit "$reaction" 5
verifie "code 130 (lu : $CODE), une seule ligne FIN interrompu_INT" fin_unique g1 130 interrompu_INT
verifie "compte rendu écrit" yaml_existe g1
verifie "le sommeil en arrière-plan est tué (plus aucun processus du groupe)" groupe_vide "$PID"

# ============================================================== (h) tee du journal tué
titre "(h) tee du journal tué pendant l'injection, puis le pilote écrit"
remise_a_zero; VITESSE=20
preparer h; lancer h1 --profil "25:6" --panne consumer-slowdown --a 1 --duree 3
TEE=""
if attendre_appel "panne\\.sh' injecter" 30; then
    "$VRAI_SLEEP" 0.3; TEE=$(pgrep -P "$PID" -x tee)
    [ -z "$TEE" ] || kill -9 "$TEE"
fi
verifie "tee du journal trouvé sous le pilote et tué" test -n "$TEE"
attendre_fin 40
verifie "pas de mort silencieuse : code 130 (lu : $CODE), FIN interrompu_PIPE" fin_unique h1 130 interrompu_PIPE
verifie "panne.sh retirer appelé une fois" egal "$(nb_appels "panne\\.sh' retirer")" 1
verifie "compte rendu écrit (interrompue: oui)" dans_yaml h1 "^interrompue: oui"
verifie "la suite du nettoyage est dans le journal du pilote" dans_journal "campagne « h1 » INTERROMPUE"

# ============================================================== (i) master injoignable
titre "(i) master injoignable au tout début"
remise_a_zero; export FAUX_INJOIGNABLE=1
preparer i; lancer i1 --profil "25:3"; attendre_fin 20
verifie "code 1 (lu : $CODE), ligne FIN depart_refuse" fin_unique i1 1 depart_refuse
verifie "un seul appel tenté (ssh true)" egal "$(appels)" "true"
verifie "message « Master injoignable »" dans_sortie "Master injoignable"

# ============================================================== (j) deux signaux
titre "(j) deux signaux à la suite"
remise_a_zero; VITESSE=20; export FAUX_LENT_RETIRER=2
preparer j; lancer j1 --profil "25:6" --panne consumer-slowdown --a 1 --duree 3
if attendre_appel "panne\\.sh' injecter" 30; then
    "$VRAI_SLEEP" 0.3; kill -TERM "$PID"
    if attendre_appel "panne\\.sh' retirer" 10; then
        "$VRAI_SLEEP" 0.2; kill -INT "$PID"; "$VRAI_SLEEP" 0.2; kill -TERM "$PID"
    fi
fi
attendre_fin 40
verifie "code 130 (lu : $CODE), une seule ligne FIN interrompu_TERM" fin_unique j1 130 interrompu_TERM
verifie "nettoyage fait une seule fois : panne.sh retirer ×1" egal "$(nb_appels "panne\\.sh' retirer")" 1
verifie "nettoyage fait une seule fois : « Interrompu. » ×1 (dans le journal, où va le nettoyage)" \
    egal "$(cat "$D"/journaux/campagne-*.log | grep -c 'ATTENTION: Interrompu.')" 1
verifie "nettoyage fait une seule fois : action interrompu ×1" egal "$(grep -c 'action: interrompu' "$D/campagnes/j1/campagne.yaml")" 1
verifie "clôture complète malgré les signaux suivants (collecte arrêtée)" dans_yaml j1 "action: collecte_arretee"

# ============================================================== (k) parcours en défaut à la minute 2
titre "(k) parcours en défaut au contrôle de la minute 2 (chemin existant, nouveau motif)"
remise_a_zero; export FAUX_BILAN="0 1"
preparer k; lancer k1 --profil "25:6" --panne consumer-slowdown --a 1 --duree 3; attendre_fin 40
verifie "code 130 (lu : $CODE), une seule ligne FIN parcours_en_defaut" fin_unique k1 130 parcours_en_defaut
verifie "l'injection en cours est retirée une fois" egal "$(nb_appels "panne\\.sh' retirer")" 1
verifie "compte rendu : controle_parcours EN_DEFAUT, interrompue: oui" dans_yaml k1 "action: controle_parcours, resultat: EN_DEFAUT"

# ============================================================== (l) injection qui pend
titre "(l) panne.sh injecter qui pend : plafond atteint, l'injection reste à retirer"
remise_a_zero; export FAUX_PEND="panne\\.sh' injecter" CAMPAGNE_PLAFOND_INJECTER=3
preparer l; lancer l1 --profil "25:6" --panne consumer-slowdown --a 1 --duree 3; attendre_fin 40
verifie "message « panne.sh injecter » n'a pas répondu en 3 s" dans_sortie "« panne.sh injecter » n'a pas répondu en 3 s"
verifie "chemin existant : injection NON_CONFIRME" dans_yaml l1 "action: injection, cause: consumer-slowdown, resultat: NON_CONFIRME"
verifie "elle a pu être posée : retirée à l'heure prévue (retrait ok)" dans_yaml l1 "action: retrait, cause: consumer-slowdown, resultat: ok"
verifie "panne.sh retirer appelé une fois" egal "$(nb_appels "panne\\.sh' retirer")" 1
verifie "la campagne va au bout : code 0 (lu : $CODE), FIN termine" fin_unique l1 0 termine

# ============================================================== (m) signal non rattrapé
titre "(m) USR1 (non rattrapé) pendant l'injection : le trap EXIT retire, motif erreur"
remise_a_zero; VITESSE=20
preparer m; lancer m1 --profil "25:6" --panne consumer-slowdown --a 1 --duree 3
if attendre_appel "panne\\.sh' injecter" 30; then "$VRAI_SLEEP" 0.5; kill -USR1 "$PID"; fi
attendre_fin 40
verifie "le pilote meurt du signal (code 138, lu : $CODE)" egal "$CODE" 138
verifie "une seule ligne FIN, motif erreur (pas « termine »)" fin_ligne m1 0 erreur
verifie "panne.sh retirer appelé une fois, par le trap EXIT" egal "$(nb_appels "panne\\.sh' retirer")" 1

# ============================================================== (n) Ctrl-C au groupe entier
titre "(n) Ctrl-C dans tmux (INT à tout le groupe, tee du journal compris)"
remise_a_zero; VITESSE=20
preparer n-original "$ORIGINAL"; lancer n0 --profil "25:6" --panne lenteur --a 1 --duree 3
if attendre_appel "panne\\.sh' injecter" 30; then "$VRAI_SLEEP" 0.5; kill -INT -- "-$PID"; fi
attendre_fin 40
echo "         (contraste) l'original : code $CODE, panne.sh retirer ×$(nb_appels "panne\\.sh' retirer"), compte rendu $(yaml_existe n0 && echo écrit || echo absent)"
preparer n; lancer n1 --profil "25:6" --panne consumer-slowdown --a 1 --duree 3
if attendre_appel "panne\\.sh' injecter" 30; then "$VRAI_SLEEP" 0.5; kill -INT -- "-$PID"; fi
attendre_fin 40
verifie "code 130 (lu : $CODE), une seule ligne FIN interrompu_INT" fin_unique n1 130 interrompu_INT
verifie "panne.sh retirer appelé une fois" egal "$(nb_appels "panne\\.sh' retirer")" 1
verifie "le nettoyage est dans le journal (INTERROMPUE), malgré le tee tué" dans_journal "campagne « n1 » INTERROMPUE"
verifie "    … et le retrait aussi" dans_journal "[panne] OK  retirée"

titre "(n) second Ctrl-C pendant le retrait du nettoyage"
remise_a_zero; VITESSE=20; export FAUX_LENT_RETIRER=2
preparer n2; lancer n2 --profil "25:6" --panne consumer-slowdown --a 1 --duree 3
if attendre_appel "panne\\.sh' injecter" 30; then
    "$VRAI_SLEEP" 0.5; kill -INT -- "-$PID"
    attendre_appel "panne\\.sh' retirer" 10 && { "$VRAI_SLEEP" 0.3; kill -INT -- "-$PID"; }
fi
attendre_fin 40
verifie "le retrait va au bout malgré le second Ctrl-C (hors du groupe du terminal)" test -f "$D/faux/retrait.fini"
verifie "    … il tourne dans une autre session que le pilote" \
    bash -c "[ \"\$(grep \"panne.sh' retirer\" '$D/appels.log.env' | cut -f3)\" != \"\$(grep \"panne.sh' etat\" '$D/appels.log.env' | cut -f3)\" ]"
verifie "code 130 (lu : $CODE), FIN interrompu_INT, retrait noté « motif: interruption »" fin_unique n2 130 interrompu_INT
verifie "    … dans le compte rendu" dans_yaml n2 "action: retrait, motif: interruption"

titre "(n) retrait du nettoyage en échec : noté ECHEC, que fautifs.py signale"
remise_a_zero; VITESSE=20; export FAUX_RETIRER_ECHEC=1
preparer n3; lancer n3 --profil "25:6" --panne consumer-slowdown --a 1 --duree 3
if attendre_appel "panne\\.sh' injecter" 30; then "$VRAI_SLEEP" 0.5; kill -TERM "$PID"; fi
attendre_fin 40
verifie "compte rendu : « action: retrait, resultat: ECHEC, motif: interruption »" dans_yaml n3 "action: retrait, resultat: ECHEC, motif: interruption"
verifie "message « Retrait non confirmé »" dans_journal "Retrait non confirmé"

# ============================================================== (o) lancé sans set -m
titre "(o) lancé en arrière-plan par un script sans « set -m » : INT ignoré, c'est dit"
remise_a_zero; export FAUX_INJOIGNABLE=1 SANS_SET_M=1
preparer o; lancer o1 --profil "25:3"; attendre_fin 20
verifie "avertissement « SIGINT ignoré dès le lancement »" dans_sortie "SIGINT ignoré dès le lancement"
remise_a_zero; export FAUX_INJOIGNABLE=1
preparer o2; lancer o2 --profil "25:3"; attendre_fin 20
verifie "pas d'avertissement quand INT est rattrapable" bash -c "! grep -q 'SIGINT ignoré' '$D/sortie.txt'"

# ============================================================== (p) plafonds
titre "(p) plafonds : valeur refusée nommée, plafond de « load-surge » (donnée par son ancien nom, « charge »)"
remise_a_zero; export CAMPAGNE_PLAFOND_RETIRER=00
preparer p; lancer p1 --profil "25:3"; attendre_fin 20
verifie "« 00 » refusé (timeout 0 n'aurait aucun plafond) : FIN depart_refuse" fin_unique p1 1 depart_refuse
verifie "la variable fautive est nommée" dans_sortie "CAMPAGNE_PLAFOND_RETIRER : un nombre de secondes, pas « 00 »"
verifie "aucun appel au master" egal "$(appels)" ""
remise_a_zero
preparer p2; lancer p2 --profil "25:4" --panne charge --a 1 --duree 2 --intensite 400; attendre_fin 30
verifie "charge (alias de load-surge) --intensite 400 : injecter plafonné à 4 × (30 + 400) = 1720" \
    egal "$(enveloppes | grep "panne.sh' injecter" | cut -f2 | awk '{print $5}')" 1720
verifie "charge (alias de load-surge) --intensite 400 : retirer garde 2400 (plus grand)" \
    egal "$(enveloppes | grep "panne.sh' retirer" | cut -f2 | awk '{print $5}')" 2400
verifie "charge → le master reçoit « injecter load-surge »" appel_avec "panne\\.sh' injecter" "injecter load-surge --duree 2 --intensite 400"
verifie "charge → compte rendu « cause: load-surge »" dans_yaml p2 "action: injection, cause: load-surge, resultat: confirme"

# ============================================================== (q) noms des causes
titre "(q) noms des causes : chaque ancien nom est traduit dès la lecture, un nom inconnu est refusé"
for paire in charge:load-surge lenteur:consumer-slowdown blocage:replica-freeze hote:noisy-neighbor \
             base:database-slowdown reseau:network-delay; do
    ancien="${paire%%:*}"; anglais="${paire#*:}"
    extra=(); [ "$anglais" != network-delay ] || extra=(--cible workers2:workers1 --intensite 50)
    remise_a_zero; export FAUX_INJOIGNABLE=1   # le plan est écrit, puis le départ est refusé
    preparer "q-$ancien"; lancer "q-$ancien" --profil "25:6" --panne "$ancien" --a 1 --duree 3 "${extra[@]}"; attendre_fin 20
    verifie "$ancien : « $ancien → $anglais » est dit" dans_sortie "$ancien → $anglais"
    verifie "$ancien : le plan porte « cause : $anglais »" dans_sortie "cause : $anglais"
    remise_a_zero; export FAUX_INJOIGNABLE=1
    preparer "q-$anglais"; lancer "q-$anglais" --profil "25:6" --panne "$anglais" --a 1 --duree 3 "${extra[@]}"; attendre_fin 20
    verifie "$anglais : accepté tel quel, sans ligne d'alias" bash -c "grep -qF 'cause : $anglais' '$D/sortie.txt' && ! grep -qF ' → $anglais' '$D/sortie.txt'"
done
remise_a_zero
preparer q-inconnu; lancer q-inconnu --profil "25:6" --panne lenteurr --a 1 --duree 3; attendre_fin 20
verifie "nom inconnu « lenteurr » : départ refusé, FIN depart_refuse" fin_unique q-inconnu 1 depart_refuse
verifie "    … la liste des noms anglais est donnée" dans_sortie "--panne accepte load-surge, consumer-slowdown, replica-freeze, noisy-neighbor, database-slowdown ou network-delay — pas « lenteurr »"
verifie "    … aucun appel au master" egal "$(appels)" ""

# ============================================================== (z) pourquoi un geste n'est pas borné sur le master
titre "(z) le minuteur nohup de panne.sh vit dans le groupe du script : un timeout côté master le tuerait"
cat > "$BAC/minuteur.sh" <<EOF
nohup bash -c "$VRAI_SLEEP 30; touch '$BAC/minuteur.fait'" >/dev/null 2>&1 < /dev/null &
echo "\$!" > "$BAC/minuteur.pid"
echo "\$(ps -o pgid= -p \$\$ | tr -d ' ') \$(ps -o pgid= -p \$! | tr -d ' ')" > "$BAC/minuteur.groupes"
$VRAI_SLEEP 5
EOF
timeout -k 1 1 bash "$BAC/minuteur.sh"
"$VRAI_SLEEP" 0.3
read -r g_script g_min < "$BAC/minuteur.groupes"
verifie "même groupe ($g_script = $g_min), comme « nohup … & » dans panne.sh injecter" [ "$g_script" = "$g_min" ]
verifie "le minuteur est tué avec le groupe quand timeout (sans --foreground) expire" \
    bash -c "! kill -0 \$(cat '$BAC/minuteur.pid') 2>/dev/null"

# ------------------------------------------------------------------ bilan
echo
echo "── bilan : $REUSSIS OK, $RATES ÉCHEC"
if [ "$RATES" -eq 0 ] && [ -z "${GARDER:-}" ]; then rm -rf "$BAC"; else echo "   dossier gardé : $BAC"; fi
[ "$RATES" -eq 0 ]
