#!/bin/bash
# ==============================================================================
#  tests/garde/test_garde.sh — le gardien (garde.py) et sa sonde (garde_sonde.py)
#  face à un faux master
# ==============================================================================
#
#  Aucun vrai ssh, aucun cluster, aucun S3 : en tête du PATH,
#    - un FAUX ssh note ses options et la commande reçue, puis exécute la sonde
#      ICI ; le seul geste admis, « bash <dépôt>/apps/panne.sh retirer », est
#      noté à part (gestes.log) et simulé (FAUX_RETIRER : ok, echec, pend) ;
#      toute autre commande est refusée et notée INTERDIT ;
#    - un FAUX kubectl (faux_kubectl.py) rejoue les sorties RÉELLES du master
#      (donnees/modele.json, relevées le 1/10 au soir), modifiées par le cas ;
#    - un FAUX boto3 (faux_s3/) remplace S3, avec un config.yaml factice.
#  Chaque cas a son propre faux master (dépôt, journaux, HOME) et son propre
#  dossier de garde, dans un dossier temporaire. Une horloge factice
#  (GARDE_MAINTENANT) fait passer les minutes sans attendre.
#  Le pilote est cherché dans GARDE_PROC, un dossier qui imite /proc avec les
#  SEULS processus créés par le test (liens vers /proc/<pid>) : un vrai
#  campagne.sh sur la machine ne fausse plus rien. Pour le prouver, un faux
#  « bash campagne.sh essai-z » tourne à côté pendant tout l'essai, puis il est
#  arrêté par son pid. Les signaux ne visent que des processus créés ici.
#
#  Cas : (a) saine en campagne ; (b) hors campagne, Locust à 0 ; (c) chaque
#  seuil seul (et les codes confirmés sur 2 ou 3 minutes) ; (d) pendant une
#  panne, un changement de palier ; (e) ssh qui pend, Prometheus en erreur pour
#  une requête ; (f) trou de 3 minutes ; (g) contamination ; (h) alertes (pas de
#  FIN pour une cause non mesurée) ; (i) les propositions, sans --agir aucun
#  geste ; (j) verrou (la seconde garde n'écrit rien) ; (k) secret S3 ; (l) la
#  sonde seule ; (m) memoire.json cassé (les alertes ouvertes reçoivent une FIN,
#  aussi celles que la mémoire ignore ; le mode est gardé ; memoire.json
#  illisible ou absent au départ) ; (p) le pilote sous
#  timeout / bash -x ;
#  (q) les gestes du niveau 1 avec --agir (retrait en arrière-plan, seconde
#  tentative, décision humaine, objet de base, kill -TERM d'un faux pilote, pid
#  réutilisé avant la minute ou pendant la sonde, pilote têtu, objet resté dans
#  la fenêtre du pilote, effondrement coupé par un trou, gestes du master
#  inconnus, retrait du pilote en cours, incident clos sans --agir, plafond
#  global, mode boucle) et le drapeau de pause ; (z) l'autre pilote.
#
#  Usage :  bash tests/garde/test_garde.sh        (GARDER=1 garde le dossier)
#  Code 0 seulement si tout passe. Borné à 15 minutes.
#
#  Le compte des connexions ssh (g) se fait par minute de sonde, dans le seul
#  cas (g) : le journal du faux ssh est commun, et les cas longs partis en
#  arrière-plan (e1, e2 : une vraie boucle d'une minute) y écrivent quand ils
#  veulent. C'est la cause probable du « 11 au lieu de 10 » vu une fois : la
#  seconde minute de la boucle e2 tombait pendant le cas (g).
# ==============================================================================
set -uo pipefail

if [ -z "${_TEST_BORNE:-}" ]; then
    exec env _TEST_BORNE=1 timeout -k 10 900 bash "$0" "$@"
fi

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHANTIER="$(cd "$ICI/../.." && pwd)"
GARDE="$CHANTIER/garde.py"
SONDE="$CHANTIER/apps/garde_sonde.py"
PYTHON="$(command -v python3)"
export PYTHONDONTWRITEBYTECODE=1   # rien n'est écrit à côté des fichiers lus
BAC="$(mktemp -d "${TMPDIR:-/tmp}/test_garde.XXXXXX")"
FAUX="$BAC/bin"; mkdir -p "$FAUX"
SECRET="SECRET-FAUX-7f3a9c-NE-JAMAIS-AFFICHER"
ACCES="AKIAFAUXACCES0042"
nettoyer() {
    # Seulement les tâches de CE shell encore en marche (jobs -pr) : un processus
    # déjà récolté n'y est plus, son pid ne peut pas viser un autre processus.
    pilote_off 2>/dev/null
    local p; for p in $(jobs -pr); do kill "$p" 2>/dev/null; done
    if [ -n "${GARDER:-}" ]; then echo "dossier gardé : $BAC"; else rm -rf "$BAC"; fi
}
trap nettoyer EXIT

REUSSIS=0; RATES=0
ok()    { echo "  OK     $*"; REUSSIS=$((REUSSIS + 1)); }
echec() { echo "  ÉCHEC  $*"; RATES=$((RATES + 1)); }
titre() { echo; echo "── $*"; }

# ------------------------------------------------------------------ les faux
cat > "$FAUX/kubectl" <<EOF
#!/bin/bash
exec "$PYTHON" "$ICI/faux_kubectl.py" "\$@"
EOF
cat > "$FAUX/ssh" <<'EOF'
#!/bin/bash
# Faux ssh : note ses options et la commande, puis exécute LOCALEMENT la sonde
# (faux kubectl du PATH, HOME factice du master). Toute autre commande est refusée.
opts=""
while [ $# -gt 0 ]; do case "$1" in -o) opts="$opts -o $2"; shift 2 ;; -*) opts="$opts $1"; shift ;; *) break ;; esac; done
hote="$1"; shift; cmd="$*"
# Le seul geste admis : « bash <dépôt>/apps/panne.sh retirer », noté À PART.
if [[ "$cmd" =~ ^bash\ ([^\ ]+)/apps/panne\.sh\ retirer$ ]]; then
    racine="${BASH_REMATCH[1]}"
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$(date -u +%H:%M:%S)" "$hote" "${opts# }" "$cmd" \
        "${FAUX_CAS:-}" "${GARDE_MAINTENANT:-}" >> "$FAUX_LOG_GESTES"
    case "${FAUX_RETIRER:-ok}" in
        pend)  exec sleep 100000 ;;
        echec) echo "  [panne] ERREUR: faux retrait en échec" >&2; exit 1 ;;
        *)     # Le faux retrait fait ce que ferait panne.sh : plus d'état, plus d'objet.
               rm -f "$racine/journaux/panne.etat"
               python3 -c 'import json,sys; f=sys.argv[1]; d=json.load(open(f)); d.pop("chaos",None); json.dump(d,open(f,"w"))' "$FAUX_SCENARIO"
               echo "  [panne] OK  nettoyé"; exit 0 ;;
    esac
fi
printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$(date -u +%H:%M:%S)" "$hote" "${opts# }" "$cmd" \
    "${FAUX_CAS:-}" "${GARDE_MAINTENANT:-}" >> "$FAUX_LOG_SSH"
[ -z "${FAUX_SSH_PEND:-}" ] || exec sleep 100000
if [ -n "${FAUX_SSH_PEND_PREMIER:-}" ] && [ ! -f "$FAUX_SSH_PEND_PREMIER" ]; then
    touch "$FAUX_SSH_PEND_PREMIER"; exec sleep 100000
fi
[ -z "${FAUX_SSH_REPONSE:-}" ] || { echo "$FAUX_SSH_REPONSE"; exit 0; }
[ -z "${FAUX_SSH_LENT:-}" ] || sleep "$FAUX_SSH_LENT"   # une sonde lente (secondes)
if [[ "$cmd" =~ ^python3\ [^\ ]+/apps/garde_sonde\.py(\ --commandes)?$ ]]; then
    exec env HOME="$FAUX_HOME_MASTER" bash -c "$cmd"
fi
printf 'INTERDIT\t%s\n' "$cmd" >> "$FAUX_LOG_SSH"
echo "faux ssh : commande refusée : $cmd" >&2
exit 99
EOF
cat > "$BAC/consommateur.sh" <<'EOF'
#!/bin/bash
# Faux consommateur.sh : « verifier » rend FAUX_VERIFIER (0, 1, 3, usage, injoignable, pend).
[ "${1:-}" = verifier ] || { echo "Usage: $0 {dimensionner|etat|verifier|reposer|retirer}" >&2; exit 2; }
case "${FAUX_VERIFIER:-0}" in
    0) echo "  retard par réplique (attendu : 140ms) :"
       echo "  [consommateur] OK  chaque réplique en marche de ts-delivery-service porte le retard"; exit 0 ;;
    1) echo "      ts-delivery-service-79c46f4f45-r5pwb   sur workers3   rien   <- MANQUE"
       echo "  [consommateur] ATTENTION: des répliques en marche n'ont pas le bon retard" >&2; exit 1 ;;
    3) echo "  [consommateur] rien à reposer pendant la panne"; exit 3 ;;
    usage) echo "Usage: /home/ubuntu/autodeploy/apps/consommateur.sh {dimensionner --retard <ms> [--prefetch <n>]|etat|retirer}" >&2; exit 2 ;;
    injoignable) echo "  retard par réplique : l'API Kubernetes ne répond pas, rien n'est lu"
       echo "  [consommateur] ATTENTION: relancer quand l'API répond" >&2; exit 1 ;;
    pend) exec sleep 100000 ;;
esac
EOF
cat > "$BAC/donnees.sh" <<'EOF'
#!/bin/bash
# Faux donnees.sh : « etat --brut » rend FAUX_COMMANDES commandes (ou « illisible »).
[ "${1:-} ${2:-}" = "etat --brut" ] || { echo "Usage" >&2; exit 2; }
n="${FAUX_COMMANDES:-1200}"
if [ "$n" = illisible ]; then
    echo "orders=? orders_other=0 food_order=? delivery=0 total=?"
    echo "  [donnees] ATTENTION: table(s) illisible(s)" >&2; exit 1
fi
echo "orders=$n orders_other=12 food_order=$((n * 3 / 4)) delivery=$((n / 2)) total=$((n + 12 + n * 3 / 4 + n / 2))"
EOF
cat > "$BAC/campagne.sh" <<'EOF'
#!/bin/bash
# Faux pilote : un processus « bash …/campagne.sh <nom> … » qui dort. Sur TERM, il
# écrit « TERM <pid> » dans FAUX_PILOTE_TERM (s'il est donné), puis s'arrête ;
# avec FAUX_PILOTE_TETU=1, il note le signal et continue (un pilote qui ne finit pas).
sleep 100000 & enfant=$!
recu() {
    [ -z "${FAUX_PILOTE_TERM:-}" ] || echo "TERM $$" >> "$FAUX_PILOTE_TERM"
    [ -n "${FAUX_PILOTE_TETU:-}" ] && return 0
    kill "$enfant" 2>/dev/null; exit 0
}
trap recu TERM
while kill -0 "$enfant" 2>/dev/null; do wait "$enfant"; done
EOF
chmod +x "$FAUX/kubectl" "$FAUX/ssh"
export PATH="$FAUX:$PATH"

titre "les faux sont en tête du PATH"
# Sinon on s'arrête TOUT DE SUITE : continuer appellerait le vrai ssh ou le vrai kubectl.
[ "$(command -v ssh)" = "$FAUX/ssh" ] && ok "ssh → $(command -v ssh)" \
    || { echo "  ÉCHEC  ssh n'est pas le faux : $(command -v ssh) — arrêt"; exit 2; }
[ "$(command -v kubectl)" = "$FAUX/kubectl" ] && ok "kubectl → $(command -v kubectl)" \
    || { echo "  ÉCHEC  kubectl n'est pas le faux : $(command -v kubectl) — arrêt"; exit 2; }

# ------------------------------------------------------------------ l'autre pilote
titre "(z) un autre pilote, « bash campagne.sh essai-z », tourne à côté pendant tout l'essai"
bash "$BAC/campagne.sh" essai-z --profil 25:30 > /dev/null 2>&1 & ZPID=$!
for _ in $(seq 20); do grep -q campagne.sh "/proc/$ZPID/cmdline" 2>/dev/null && break; sleep 0.1; done

# Environnement commun à toutes les gardes de l'essai.
export GARDE_SSH=master GARDE_PYTHON_S3="$PYTHON" PYTHONPATH="$ICI/faux_s3"
export FAUX_LOG_SSH="$BAC/ssh.log" FAUX_LOG_KUBECTL="$BAC/kubectl.log" FAUX_LOG_GESTES="$BAC/gestes.log"
export FAUX_T0="$(date -u -d 2026-10-01T11:00:00Z +%s)"   # les totaux de Locust partent de 11:00
: > "$FAUX_LOG_SSH"; : > "$FAUX_LOG_GESTES"
# Le faux /proc : la garde n'y voit que les processus du test (proc_voir).
export GARDE_PROC="$BAC/proc"; mkdir -p "$GARDE_PROC"

# ------------------------------------------------------------------ les outils
descendants() {   # <pid>… — les pid donnés et tous leurs descendants (par pid parent)
    local p e
    for p in "$@"; do
        echo "$p"
        for e in $(pgrep -P "$p"); do descendants "$e"; done
    done
}
proc_voir() {   # <pid>… — rend ces processus (et leurs descendants) visibles de la garde
    local p; for p in $(descendants "$@"); do ln -sfn "/proc/$p" "$GARDE_PROC/$p"; done
}
PILOTE=""
pilote_on() {   # <nom> — un faux pilote vivant (TERM noté dans $D/term.recu), et son journal frais
    FAUX_PILOTE_TERM="$D/term.recu" bash "$DEPOT/campagne.sh" "$1" --profil 25:30 & PILOTE=$!
    for _ in $(seq 20); do grep -q campagne.sh "/proc/$PILOTE/cmdline" 2>/dev/null && break; sleep 0.1; done
    proc_voir "$PILOTE"
    touch "$DEPOT/journaux/campagne-20261001-140000.log"
}
# Arrêt par KILL du pilote du test et de ses descendants (pid connus) : pas de TERM,
# qui serait compté comme reçu de la garde. Seulement s'il est encore une tâche en
# marche de ce shell : un pilote déjà sorti (après TERM) n'est plus visé.
pilote_off() {
    [ -n "$PILOTE" ] || return 0
    if jobs -pr | grep -qx "$PILOTE"; then
        kill -KILL $(descendants "$PILOTE") 2>/dev/null
    fi
    wait "$PILOTE" 2>/dev/null
    PILOTE=""
}

# cas <nom> : un faux master neuf (dépôt déployé, journaux, HOME), un dépôt vms0
# neuf, un dossier de garde neuf ; plateforme saine, palier 25 depuis 11:00.
cas() {
    pilote_off
    unset FAUX_VERIFIER FAUX_COMMANDES FAUX_SSH_PEND FAUX_SSH_PEND_PREMIER FAUX_SSH_REPONSE \
          FAUX_S3_ERREUR AVEC_S3 GARDE_VMS0_LIBRE_MIN_GO JOURNAL_FIGE GARDE_PLAFOND_SSH \
          AGIR FAUX_RETIRER GARDE_PLAFOND_GESTE FAUX_SSH_LENT
    rm -rf "${GARDE_PROC:?}"/*
    export FAUX_CAS="$1"
    D="$BAC/cas/$1"; DOSSIER="$D/garde"; TSV="$DOSSIER/garde.tsv"
    MASTER="$D/master/autodeploy"; DEPOT="$D/depot"
    mkdir -p "$MASTER/apps" "$MASTER/journaux" "$D/master/home" "$DEPOT/journaux" "$DEPOT/graphe_en"
    cp "$SONDE" "$MASTER/apps/garde_sonde.py"
    cp "$BAC/consommateur.sh" "$BAC/donnees.sh" "$MASTER/apps/"
    cp "$BAC/campagne.sh" "$DEPOT/campagne.sh"
    printf '# instant_demande\tinstant_effectif\tvoyageurs_observes\tvoyageurs_demandes\tspawn_rate\tcible\torigine\n' > "$MASTER/journaux/paliers.tsv"
    palier 25 "11:00"
    printf '# instant_demande\tinstant_effectif\taction\tcause\tintensite\tcible\toutil\tresultat\n2026-09-30T17:10:37Z\t2026-09-30T17:10:38Z\tretrait\tbase\t75\ttsdb-mysql-0@workers4 -> 55 clients\tchaos-mesh\tok\n' > "$MASTER/journaux/pannes.tsv"
    printf '# instant\taction\tlignes_avant\tresultat\n2026-10-01T10:00:00Z\tpurger\t5000\tok\n' > "$MASTER/journaux/donnees.tsv"
    cat > "$DEPOT/graphe_en/config.yaml" <<EOF
source:
  endpoint: http://faux-magasin:9000
  bucket: faux-seau
  prefix: otel-data
  access_key: $ACCES
  secret_key: $SECRET
EOF
    export GARDE_DISTANT="$MASTER" GARDE_DEPOT="$DEPOT" GARDE_S3_CONFIG="$DEPOT/graphe_en/config.yaml"
    export FAUX_HOME_MASTER="$D/master/home" FAUX_SCENARIO="$D/scenario.json" FAUX_S3_OBJETS="$D/s3.json"
    export FAUX_S3_LOG="$D/s3.log"
    echo '{}' > "$FAUX_SCENARIO"
    s3_objets 30 "12:00"
}
scenario() { echo "$1" > "$FAUX_SCENARIO"; }
iso() { echo "2026-10-01T$1:00Z"; }           # « 12:05 » → instant UTC
ep()  { date -u -d "2026-10-01T$1:00Z" +%s; }
palier() {   # <voyageurs> <HH:MM> [origine]
    printf '%s\t%s\t%s\t%s\t1\ttrain-ticket\t%s\n' "$(iso "$2")" "$(iso "$2")" "$1" "$1" "${3:-demande}" \
        >> "$MASTER/journaux/paliers.tsv"
}
s3_objets() {   # <âge en s> <HH:MM> — le dernier objet S3, âgé de tant à HH:MM:30
    local t; t=$(date -u -d "@$(( $(ep "$2") + 30 - $1 ))" +%Y-%m-%dT%H:%M:%SZ)
    printf '[{"Key": "otel-data/year=2026/month=10/day=01/hour=%s/minute=%s/traces_1.json.gz", "LastModified": "%s"}]\n' \
        "${t:11:2}" "${t:14:2}" "$t" > "$FAUX_S3_OBJETS"
}
panne_etat() {   # <cause> <début HH:MM> <durée> — panne.etat comme panne.sh l'écrit
    printf "CAUSE='%s'\nOUTIL='chaos-mesh'\nCIBLE='x'\nINTENSITE='300'\nDEBUT='%s'\nDUREE='%s'\nMINUTEUR=''\n" \
        "$1" "$(iso "$2")" "$3" > "$MASTER/journaux/panne.etat"
}
# garde_minute <HH:MM> — une minute de garde à l'horloge factice HH:MM:30
garde_minute() {
    local h="$1"; shift
    if [ -n "$PILOTE" ] && [ -z "${JOURNAL_FIGE:-}" ]; then
        touch -d "@$(ep "$h")" "$DEPOT/journaux/campagne-20261001-140000.log"
    fi
    GARDE_MAINTENANT="2026-10-01T$h:30Z" "$PYTHON" "$GARDE" --une-fois --dossier "$DOSSIER" \
        $([ -n "${AVEC_S3:-}" ] || echo --sans-s3) $([ -z "${AGIR:-}" ] || echo --agir) "$@" >> "$D/sortie.txt" 2>&1
}
val() { "$PYTHON" "$ICI/lire.py" "$TSV" "$1" "$2"; }
# attendu <description> <HH:MM> <état> <causes triées, séparées par des virgules>
attendu() {
    local e c; e=$(val "$2" etat); c=$(val "$2" causes)
    if [ "$e" = "$3" ] && [ "$c" = "$4" ]; then ok "$1 — $2 : $e ${c:-(aucune cause)}"
    else echec "$1 — $2 : attendu $3 « $4 », obtenu $e « $c »"; tail -5 "$D/sortie.txt" | sed 's/^/        | /'; fi
}
egal() {   # <description> <obtenu> <attendu>
    if [ "$2" = "$3" ]; then ok "$1 : $2"; else echec "$1 : attendu « $3 », obtenu « $2 »"; fi
}
contient() {   # <description> <texte> <motif grep -E>
    if printf '%s' "$2" | grep -qE -- "$3"; then ok "$1"; else echec "$1 (« $3 » absent de « $2 »)"; fi
}
compte() { grep -cE -- "$2" <<< "$1"; }   # <texte> <motif> — lignes qui correspondent
gestes_du_cas() { awk -F'\t' -v c="$FAUX_CAS" '$5 == c' "$FAUX_LOG_GESTES" | wc -l; }
alertes() { cat "$DOSSIER/alertes.txt" 2>/dev/null; }
actions() { cut -f2,5 "$DOSSIER/actions.tsv" 2>/dev/null | tail -n +2 | tr '\t' ' ' | tr '\n' ';'; }
attendre_gestes() {   # <n> — le faux ssh a reçu n gestes dans ce cas (le sous-processus démarre ; au plus 10 s)
    local _; for _ in $(seq 50); do [ "$(gestes_du_cas)" -ge "$1" ] && return 0; sleep 0.2; done; return 1
}
attendre_resultats() {   # <n> — n résultats de retrait écrits dans gestes/ (au plus 40 s)
    local _; for _ in $(seq 200); do
        [ "$(ls "$DOSSIER/gestes/"*.json 2>/dev/null | wc -l)" -ge "$1" ] && return 0; sleep 0.2
    done; return 1
}

"$PYTHON" - "$GARDE" "$ZPID" "$GARDE_PROC" <<'EOF' && ok "(z) essai-z est vu dans le vrai /proc, pas dans GARDE_PROC" || echec "(z) essai-z"
import importlib.util, sys
spec = importlib.util.spec_from_file_location("garde_lu", sys.argv[1])
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
z = int(sys.argv[2])
assert z in [p["pid"] for p in g.trouver_pilotes("/proc")], "essai-z absent du vrai /proc"
assert z not in [p["pid"] for p in g.trouver_pilotes(sys.argv[3])], "essai-z vu dans GARDE_PROC"
assert g.PROC == sys.argv[3]
EOF

# ==============================================================================
# Les cas longs (une vraie attente) partent en arrière-plan, et sont jugés à la fin.
# ==============================================================================
cas e1_ssh_pend
export FAUX_SSH_PEND=1
( debut=$(date +%s); garde_minute 12:00; echo $(( $(date +%s) - debut )) > "$D/duree" ) &
E1=$!; E1D="$D"
unset FAUX_SSH_PEND

cas e2_boucle
( export GARDE_PLAFOND_SSH=5 FAUX_SSH_PEND_PREMIER="$D/premier.fait"
  debut=$(date +%s)
  "$PYTHON" "$GARDE" --dossier "$DOSSIER" --sans-s3 --tours 2 > "$D/sortie.txt" 2>&1
  echo "$? $(( $(date +%s) - debut ))" > "$D/fin" ) &
E2=$!; E2D="$D"

cas l2_sonde_pend
scenario '{"pend": true}'
( debut=$(date +%s)
  HOME="$D/master/home" "$PYTHON" "$MASTER/apps/garde_sonde.py" --commandes > "$D/sonde.json" 2> "$D/sonde.err"
  echo $(( $(date +%s) - debut )) > "$D/duree" ) &
L2=$!; L2D="$D"

# ==============================================================================
titre "(a) plateforme saine en campagne : 25 voyageurs, 7,5 req/s, dépôt 3,3, file vide, 3 consommateurs, 140 ms"
cas a
pilote_on essai-a
scenario '{"prom": {"cpu_commandes": 0.40}}'
AVEC_S3=1
GARDE_MAINTENANT="2026-10-01T12:00:30Z" "$PYTHON" "$GARDE" --une-fois --dossier "$DOSSIER" >> "$D/sortie.txt" 2>&1
attendu "(a) saine" 12:00 OK ""
egal "(a) notes" "$(val 12:00 notes)" ""
egal "(a) voyageurs demandés/réels, req/s" "$(val 12:00 voyageurs_demandes)/$(val 12:00 voyageurs_reels)/$(val 12:00 req_s)" "25/25/7.50"
egal "(a) dépôt, retrait, tas, consommateurs" "$(val 12:00 depot)/$(val 12:00 retrait)/$(val 12:00 tas)/$(val 12:00 consommateurs)" "3.30/3.30/0/3"
egal "(a) 140 ms, leader, nœuds" "$(val 12:00 reglage_140ms)/$(val 12:00 leader)/$(val 12:00 noeuds_prets)" "ok/tsdb-mysql-0/8/8"
egal "(a) commandes lues, âge S3, jours de Prometheus" "$(val 12:00 commandes)/$(val 12:00 s3_age_s)/$(val 12:00 prometheus_jours)" "1200/30/5.8"
contient "(a) pilote vivant noté" "$(val 12:00 pilote)" "^essai-a\\($PILOTE\\)$"
egal "(a) aucune proposition" "$(val 12:00 action_niveau1_proposee)/$(val 12:00 pause_proposee)" "/0"
"$PYTHON" -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["etat"]=="OK" and d["mesure"]["prom"]["depot"]["valeur"]==3.3' \
    "$DOSSIER/dernier.json" && ok "(a) dernier.json lisible et complet" || echec "(a) dernier.json"
egal "(a) en-tête de garde.tsv" "$("$PYTHON" "$ICI/lire.py" "$TSV" --entete)" \
    "$("$PYTHON" -c 'import ast,sys; t=ast.parse(open(sys.argv[1]).read()); print(",".join(next(ast.literal_eval(n.value) for n in t.body if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "COLONNES")))' "$GARDE")"
contient "(a) S3 lu sous le préfixe du jour, à partir de l'heure précédente" "$(cat "$D/s3.log")" '"prefix": "otel-data/year=2026/month=10/day=01/", "start_after": "otel-data/year=2026/month=10/day=01/hour=11/"'
[ "$(grep -vc '^#' "$D/garde/alertes.txt" 2>/dev/null)" = 0 ] || [ ! -s "$D/garde/alertes.txt" ] \
    && ok "(a) alertes.txt sans alerte" || echec "(a) alertes.txt : $(cat "$D/garde/alertes.txt")"
unset AVEC_S3
pilote_off

# ==============================================================================
titre "(b) hors campagne : Locust à 0 réplique (« no endpoints »), palier 0, pas de pilote"
cas b
palier 0 "11:30"
scenario '{"locust": "absent", "prom": {"depot": 0, "retrait": 0, "cpu_commandes": 0.0016, "reseau_commandes": 120}, "passerelle": "0/0"}'
garde_minute 12:00
attendu "(b) Locust absent hors campagne = normal" 12:00 OK ""
egal "(b) voyageurs réels" "$(val 12:00 voyageurs_reels)" "0"

cas b4_palier_0_pilote; pilote_on essai-b4
palier 0 "11:30"
scenario '{"locust": "absent", "prom": {"depot": 0, "retrait": 0, "cpu_commandes": 0.0016, "reseau_commandes": 120}}'
garde_minute 12:00; garde_minute 12:01
attendu "(b4) pilote vivant, palier 0, Locust à 0 réplique : demande = réalité" 12:01 OK ""
pilote_off

cas b2_verifier_ancien
export FAUX_VERIFIER=usage
garde_minute 12:00
attendu "(b2) verifier ancien (Usage, code 2), retard lu par la garde : présent" 12:00 DOUTEUX "VERIFIER_UNAVAILABLE"
egal "(b2) réglage lu dans podnetworkchaos" "$(val 12:00 reglage_140ms)" "ok"

cas b3_verifier_ancien_manque
export FAUX_VERIFIER=usage
scenario '{"sans_140": ["ts-delivery-service-79c46f4f45-r5pwb"]}'
garde_minute 12:00
attendu "(b3) verifier ancien et une réplique sans 140 ms" 12:00 MALADE "BASE_DELAY_MISSING,VERIFIER_UNAVAILABLE"
egal "(b3) réglage" "$(val 12:00 reglage_140ms)" "manque:1/3"

# ==============================================================================
titre "(c) chaque seuil franchi seul, hors panne, en campagne"
# un_seuil <nom> <code attendu> <état> <scénario JSON> [variable=valeur…]
un_seuil() {
    local nom="$1" code="$2" etat="$3" sc="$4"; shift 4
    cas "c_$nom"; pilote_on "essai-$nom"
    scenario "$sc"
    local v; for v in "$@"; do export "$v"; done
    garde_minute 12:00
    attendu "(c) $nom" 12:00 "$etat" "$code"
    pilote_off
}
un_seuil req_s_bas       LOCUST_RATE_LOW    MALADE '{"locust": {"req_s": 5.5}}'
un_seuil echecs          LOCUST_ERRORS      MALADE '{"locust": {"echecs_pct": {"40 commander un repas": 10}}}'
un_seuil recherche_30s   SEARCH_SLOW        MALADE '{"locust": {"recherche_ms": 31000}}'
un_seuil gel_depot       PUBLISH_FROZEN     MALADE '{"prom": {"depot": 0.5, "retrait": 0.5}}'
un_seuil tas             QUEUE_BACKLOG      MALADE '{"prom": {"tas_pret": 15}}'
un_seuil consommateurs   CONSUMERS          MALADE '{"prom": {"consommateurs": 2}}'
un_seuil sans_140ms      BASE_DELAY_MISSING MALADE '{}' FAUX_VERIFIER=1
un_seuil cpu_commandes   ORDER_CPU_HIGH     MALADE '{"prom": {"cpu_commandes": 1.3}}'
egal "(c) CPU > 1,2 → pause proposée" "$(val 12:00 pause_proposee)/$(val 12:00 pause_motif)" "1/ORDER_CPU_HIGH"
un_seuil gel_cpu         ORDER_FROZEN       MALADE '{"prom": {"cpu_commandes": 0.001}}'
un_seuil gel_reseau      ORDER_FROZEN       MALADE '{"prom": {"reseau_commandes": 80}}'
un_seuil pod_pas_pret    KEY_POD_NOT_READY  MALADE '{"pods": {"ts-seat-service": {"pret": false}}}'
un_seuil sans_leader     LEADER_LOST        MALADE '{"leader": null}'
un_seuil noeud           NODE_NOT_READY     MALADE '{"noeuds": {"workers4": {"statut": "NotReady"}}}'
un_seuil disque_noeud    NODE_DISK_FULL     MALADE '{"prom": {"disque_utilise_pct": [[{"node": "workers6"}, 85.0], [{"node": "workers0"}, 30.0]]}}'
un_seuil disque_vms0     VMS0_DISK_LOW      MALADE '{}' GARDE_VMS0_LIBRE_MIN_GO=1000000
un_seuil memoire_noeud   NODE_MEMORY_LOW    MALADE '{"prom": {"memoire_noeuds": [[{"node": "workers0"}, 314572800], [{"node": "workers1"}, 2147483648]]}}'
un_seuil memoire_mysql   MYSQL_MEMORY_HIGH  MALADE '{"prom": {"memoire_pods": [[{"namespace": "train-ticket", "pod": "tsdb-mysql-0"}, 1.0e9], [{"namespace": "observability", "pod": "jaeger-x"}, 1.0e9]]}}'
un_seuil passerelle      GATEWAY_DOWN       MALADE '{"passerelle": "1/0"}'
un_seuil jaeger_memoire  JAEGER_MEMORY      DOUTEUX '{"prom": {"memoire_pods": [[{"namespace": "observability", "pod": "jaeger-x"}, 2.0e9]]}}'
un_seuil prometheus_court PROMETHEUS_SHORT_HISTORY DOUTEUX '{"prom": {"historique_prometheus": 86400}}'
un_seuil prometheus_plein "" OK '{"prom": {"taille_prometheus": 8.0e9}}'
un_seuil prometheus_illisible "" OK '{"prom": {"historique_prometheus": "vide"}}'
egal "(c) historique de Prometheus illisible : seulement noté" "$(val 12:00 notes)" "PROMETHEUS_HISTORY_UNREAD"
un_seuil verifier_injoignable "MEASURE_FAILED:verifier" MALADE '{}' FAUX_VERIFIER=injoignable
un_seuil verifier_ancien VERIFIER_UNAVAILABLE DOUTEUX '{}' FAUX_VERIFIER=usage

# confirme <nom> <code> <état> <minutes> <scénario> [variable=valeur…] : le code
# n'est retenu qu'à la n-ième minute de suite ; avant, il est seulement noté.
confirme() {
    local nom="$1" code="$2" etat="$3" n="$4" sc="$5"; shift 5
    cas "c_$nom"; pilote_on "essai-$nom"
    scenario "$sc"
    local v i; for v in "$@"; do export "$v"; done
    for i in $(seq 0 $((n - 1))); do garde_minute "12:0$i"; done
    attendu "(c) $nom : minute $((n - 1))/$n, pas encore" "12:0$((n - 2))" OK ""
    contient "(c) $nom : noté en attendant" "$(val "12:0$((n - 2))" notes)" "$code"
    attendu "(c) $nom : $n minutes de suite" "12:0$((n - 1))" "$etat" "$code"
    pilote_off
}
confirme voyageurs     LOCUST_USERS  MALADE 2 '{"locust": {"voyageurs": 20}}'
confirme locust_absent LOCUST_USERS  MALADE 2 '{"locust": "absent"}'
confirme depot_bas     PUBLISH_LOW   MALADE 3 '{"prom": {"depot": 2.9, "retrait": 2.9}}'
confirme residu        CHAOS_RESIDUE MALADE 2 '{"restes": ["train-ticket/panne-base"]}'

for n in 6000 7000 8000; do
    case $n in 6000) e=OK; c=""; no=ORDERS_WARN; p=0 ;; 7000) e=OK; c=""; no=ORDERS_HIGH; p=1 ;;
               8000) e=MALADE; c=ORDERS_MAX; no=""; p=1 ;; esac
    un_seuil "commandes_$n" "$c" "$e" '{"prom": {"cpu_commandes": 0.40}}' FAUX_COMMANDES=$n
    egal "(c) $n commandes : notes, pause proposée" "$(val 12:00 notes)/$(val 12:00 pause_proposee)" "$no/$p"
done
contient "(c) 6000 commandes : alerte écrite, niveau NOTE" "$(cat "$BAC/cas/c_commandes_6000/garde/alertes.txt")" "DEBUT  NOTE     ORDERS_WARN"

cas c_pilote_muet; pilote_on essai-muet
JOURNAL_FIGE=1; touch -d "@$(( $(ep 12:00) - 20 * 60 ))" "$DEPOT/journaux/campagne-20261001-140000.log"
garde_minute 12:00; unset JOURNAL_FIGE
attendu "(c) pilote_muet (journal de 20 min)" 12:00 MALADE PILOT_SILENT
pilote_off

cas c_s3_ancien; pilote_on essai-s3
s3_objets 330 12:00; AVEC_S3=1
GARDE_MAINTENANT="2026-10-01T12:00:30Z" "$PYTHON" "$GARDE" --une-fois --dossier "$DOSSIER" >> "$D/sortie.txt" 2>&1
attendu "(c) S3 sans objet neuf depuis 330 s, collecte en route" 12:00 MALADE S3_STALE
unset AVEC_S3; pilote_off

cas c_s3_depart   # hors campagne : la collecte se met en route à 12:01
scenario '{"passerelle": "0/0"}'; s3_objets 4000 12:00; AVEC_S3=1
garde_minute 12:00
scenario '{}'
for m in 01 02 03; do garde_minute "12:$m"; done
attendu "(c) collecte en route depuis 0 min, S3 vu avant : pas jugé" 12:01 OK ""
attendu "(c) collecte en route depuis 1 min : pas jugé" 12:02 OK ""
attendu "(c) S3 revérifié 2 min après la mise en route, toujours ancien" 12:03 MALADE S3_STALE
egal "(c) S3 lu à 12:00 et revérifié à 12:03 (pas à 12:01 ni 12:02)" "$(wc -l < "$D/s3.log")" "2"
unset AVEC_S3

cas c_s3_minuit
s3_objets 60 00:02
GARDE_MAINTENANT="2026-10-01T00:02:30Z" "$PYTHON" "$GARDE" --une-fois --dossier "$DOSSIER" >> "$D/sortie.txt" 2>&1
contient "(c) juste après minuit : la veille est lue aussi" "$(cat "$D/s3.log")" 'day=30/", "start_after": "otel-data/year=2026/month=09/day=30/hour=22/"'
egal "(c) juste après minuit : âge S3" "$("$PYTHON" "$ICI/lire.py" "$TSV" 00:02 s3_age_s)" "60"

cas c_s3_erreur; pilote_on essai-s3e
export FAUX_S3_ERREUR=1
GARDE_MAINTENANT="2026-10-01T12:00:30Z" "$PYTHON" "$GARDE" --une-fois --dossier "$DOSSIER" >> "$D/sortie.txt" 2>&1
attendu "(c) S3 en erreur" 12:00 MALADE "MEASURE_FAILED:s3"
contient "(c) S3 en erreur : le secret est tu" "$(cat "$DOSSIER/alertes.txt")" "accès refusé pour la clé \*\*\*"
unset FAUX_S3_ERREUR; pilote_off

cas c_s3_yaml; pilote_on essai-yaml   # une ligne fautive de config.yaml qui porte le secret
printf 'source:\n  endpoint: http://faux-magasin:9000\n  secret_key: "%s\n  bucket: b\n' "$SECRET" > "$DEPOT/graphe_en/config.yaml"
AVEC_S3=1; garde_minute 12:00; unset AVEC_S3
attendu "(c) config.yaml mal formé" 12:00 MALADE "MEASURE_FAILED:s3"
contient "(c) config.yaml mal formé : seul le type de l'erreur" "$(cat "$DOSSIER/alertes.txt")" "ScannerError \(configuration illisible ; message tu\)"
pilote_off

# Les seuils qui comparent à la minute précédente (ou à la référence) : deux minutes.
deux_minutes() {   # <nom> <code> <état> <scénario de la 2e minute> [variable=valeur…]
    local nom="$1" code="$2" etat="$3" sc="$4"; shift 4
    cas "c_$nom"; pilote_on "essai-$nom"
    garde_minute 12:00
    scenario "$sc"
    local v; for v in "$@"; do export "$v"; done
    garde_minute 12:01
    attendu "(c) $nom : minute de référence" 12:00 OK ""
    attendu "(c) $nom" 12:01 "$etat" "$code"
    pilote_off
}
deux_minutes redemarrage   POD_RESTART     MALADE  '{"pods": {"ts-order-service": {"redemarrages": 1}}}'
deux_minutes redem_prom    POD_RESTART     MALADE  '{"prom": {"redemarrages": [[{"namespace": "loadgen", "pod": "locust-6f7b-q8x"}, 1], [{"namespace": "train-ticket", "pod": "ts-auth-service-d57b979b6-6rhnt"}, 63]]}}'
deux_minutes jaeger_oom    JAEGER_RESTART  DOUTEUX '{"prom": {"redemarrages": [[{"namespace": "observability", "pod": "jaeger-7d9f8c-abcde"}, 28], [{"namespace": "train-ticket", "pod": "ts-auth-service-d57b979b6-6rhnt"}, 63]]}}'
deux_minutes leader        LEADER_CHANGED  MALADE  '{"leader": "tsdb-mysql-1"}'
deux_minutes adresse_ip    NODE_IP_CHANGED MALADE  '{"noeuds": {"workers2": {"ip": "10.10.222.200"}}}'
deux_minutes reservation   BOOKING_STUCK   MALADE  '{"locust": {"bloque": ["30 réserver un billet"]}}'

cas c_recherche_moyenne; pilote_on essai-rm
scenario '{"locust": {"recherche_ms": 16000}}'
garde_minute 12:00; garde_minute 12:01
attendu "(c) médiane 16 s sans minute précédente : sous 30 s" 12:00 OK ""
attendu "(c) moyenne sur la minute 16 s ≥ 15 s" 12:01 MALADE SEARCH_SLOW
scenario '{"locust": {"recherche_ms": 14000}}'
garde_minute 12:02; garde_minute 12:03
attendu "(c) moyenne sur la minute 14 s" 12:03 MALADE RECOVERING
pilote_off

cas c_debit_10s; pilote_on essai-10s
garde_minute 12:00
scenario '{"locust": {"req_s_10s": 5.5}}'; garde_minute 12:01
attendu "(c) 5,5 req/s sur 10 s, 7,5 sur la minute : jugé sur la minute" 12:01 OK ""
contient "(c) colonne req_s : le débit sur la minute" "$(val 12:01 req_s)" "^7\.[3-7]"
pilote_off

cas c_redem_vide; pilote_on essai-rv
garde_minute 12:00
scenario '{"prom": {"redemarrages": "vide"}}'; garde_minute 12:01
scenario '{}'; garde_minute 12:02
attendu "(c) séries de redémarrages vides une minute" 12:01 OK ""
attendu "(c) … puis revenues : pas de faux redémarrage" 12:02 OK ""
egal "(c) … ni OBS_RESTART noté" "$(val 12:02 notes)" ""
pilote_off

cas c_retrait_lent; pilote_on essai-retrait
scenario '{"prom": {"depot": 3.3, "retrait": 3.1}}'
for m in 00 01 02 03 04 05 06 07 08 09; do garde_minute "12:$m"; done
attendu "(c) retrait < dépôt depuis 9 min : pas encore" 12:08 OK ""
attendu "(c) retrait < dépôt depuis 10 min" 12:09 MALADE DRAIN_LAG
pilote_off

# ==============================================================================
titre "(d) pendant une panne déclarée : baisses de débit et tas notés, pas MALADE ; un redémarrage reste MALADE"
cas d
pilote_on essai-d
garde_minute 12:00
panne_etat "cause-opaque-Zx9" 12:01 20
scenario '{"locust": {"req_s": 4.0, "echecs_pct": {"40 commander un repas": 12}}, "prom": {"depot": 2.0, "retrait": 1.2, "tas_pret": 40}}'
garde_minute 12:01
attendu "(d) baisses et tas pendant la panne" 12:01 OK ""
egal "(d) en_panne, cause opaque" "$(val 12:01 en_panne)/$(val 12:01 panne_declaree)" "1/cause-opaque-Zx9"
egal "(d) les baisses sont notées" "$(val 12:01 notes)" "LOCUST_ERRORS,LOCUST_RATE_LOW,PUBLISH_LOW,QUEUE_BACKLOG"
scenario '{"locust": {"req_s": 4.0}, "prom": {"depot": 2.0, "retrait": 1.2, "tas_pret": 40}, "pods": {"ts-travel-service": {"redemarrages": 2}}}'
garde_minute 12:02
attendu "(d) un redémarrage pendant la panne" 12:02 MALADE POD_RESTART
egal "(d) … et les baisses restent notées" "$(val 12:02 notes)" "LOCUST_RATE_LOW,PUBLISH_LOW,QUEUE_BACKLOG"
rm -f "$MASTER/journaux/panne.etat"
printf '%s\t%s\tretrait\tcause-opaque-Zx9\t300\tx\tchaos-mesh\tok\n' "$(iso 12:02)" "$(iso 12:02)" >> "$MASTER/journaux/pannes.tsv"
scenario '{"prom": {"tas_pret": 30}}'
garde_minute 12:03
attendu "(d) après la panne, le tas reste noté (contamination du redémarrage)" 12:03 MALADE RECOVERING
contient "(d) tas noté après le retrait" "$(val 12:03 notes)" "QUEUE_BACKLOG"
egal "(d) en_panne après le retrait" "$(val 12:03 en_panne)" "0"
pilote_off

cas d2_tas_10min_apres
printf '%s\t%s\tretrait\tcause-opaque\t1\tx\ty\tok\n' "$(iso 11:50)" "$(iso 11:50)" >> "$MASTER/journaux/pannes.tsv"
scenario '{"prom": {"tas_pret": 30}}'
garde_minute 12:00
attendu "(d2) tas 10 min après un retrait (pannes.tsv) : noté" 12:00 OK ""
egal "(d2) note" "$(val 12:00 notes)" "QUEUE_BACKLOG"
cas d3_tas_26min_apres
printf '%s\t%s\tretrait\tcause-opaque\t1\tx\ty\tok\n' "$(iso 11:34)" "$(iso 11:34)" >> "$MASTER/journaux/pannes.tsv"
scenario '{"prom": {"tas_pret": 30}}'
garde_minute 12:00
attendu "(d3) tas 26 min après un retrait : MALADE" 12:00 MALADE QUEUE_BACKLOG

cas d5_descente; pilote_on essai-desc
scenario '{"locust": {"etat": "spawning", "voyageurs": 18, "req_s": 5.0}, "prom": {"depot": 2.5, "retrait": 2.5}}'
garde_minute 12:00
attendu "(d5) Locust retire des voyageurs (palier pas encore écrit) : débit noté" 12:00 OK ""
egal "(d5) notes" "$(val 12:00 notes)" "LOCUST_RAMPING,LOCUST_RATE_LOW,PALIER_SETTLING,PUBLISH_LOW"
pilote_off

cas d4_palier_recent; pilote_on essai-palier
palier 40 "11:59"
scenario '{"locust": {"voyageurs": 40, "req_s": 8.0}, "prom": {"depot": 3.4, "retrait": 3.4}}'
garde_minute 12:00
attendu "(d4) palier changé il y a 1 min : débit noté" 12:00 OK ""
egal "(d4) notes" "$(val 12:00 notes)" "LOCUST_RATE_LOW,PALIER_SETTLING,PUBLISH_LOW"
pilote_off

# ==============================================================================
titre "(e) mesures impossibles"
cas e3_prom_une_requete
scenario '{"prom": {"cpu_commandes": "erreur"}}'
garde_minute 12:00
attendu "(e) Prometheus en erreur pour une seule requête" 12:00 MALADE "MEASURE_FAILED:prom_cpu_commandes"
egal "(e) les autres mesures sont là" "$(val 12:00 depot)/$(val 12:00 cpu_commandes)/$(val 12:00 voyageurs_reels)" "3.30//25"
cas e4_prom_vide
scenario '{"prom": {"depot": "vide"}}'
garde_minute 12:00
attendu "(e) réponse vide de Prometheus" 12:00 MALADE "MEASURE_FAILED:prom_depot"
cas e5_sonde_illisible
export FAUX_SSH_REPONSE="bash: python3: command not found"
garde_minute 12:00
attendu "(e) sonde illisible" 12:00 MALADE "MEASURE_FAILED:sonde"
unset FAUX_SSH_REPONSE
cas e6_commandes_illisibles
export FAUX_COMMANDES=illisible
garde_minute 12:00
attendu "(e) commandes illisibles" 12:00 MALADE "MEASURE_FAILED:commandes"

# ==============================================================================
titre "(f) trou de 3 minutes : garde arrêtée à 12:00, relancée à 12:04"
cas f
garde_minute 12:00
garde_minute 12:04
egal "(f) lignes MEASURE_GAP" "$("$PYTHON" "$ICI/lire.py" "$TSV" --compte causes=MEASURE_GAP)" "3"
egal "(f) 12:01, 12:02, 12:03" "$(val 12:01 etat)/$(val 12:02 causes)/$(val 12:03 causes)" "MALADE/MEASURE_GAP/MEASURE_GAP"
egal "(f) lignes en tout" "$("$PYTHON" "$ICI/lire.py" "$TSV" --lignes)" "5"
attendu "(f) la minute de reprise est contaminée" 12:04 MALADE RECOVERING
GARDE_MAINTENANT="2026-10-01T12:04:50Z" "$PYTHON" "$GARDE" --une-fois --dossier "$DOSSIER" --sans-s3 >> "$D/sortie.txt" 2>&1
egal "(f) une minute déjà écrite n'est pas réécrite" "$("$PYTHON" "$ICI/lire.py" "$TSV" --lignes)" "5"

# ==============================================================================
titre "(g) contamination, puis (h) alertes"
cas g
garde_minute 12:00
scenario '{"prom": {"consommateurs": 2}}'; garde_minute 12:01
scenario '{}';                             garde_minute 12:02
scenario '{"prom": {"tas_pret": 3}}';      garde_minute 12:03
scenario '{}'
for m in 04 05 06 07 08 09; do garde_minute "12:$m"; done
attendu "(g) saine" 12:00 OK ""
attendu "(g) la panne" 12:01 MALADE CONSUMERS
attendu "(g) 1re minute en régime" 12:02 MALADE RECOVERING
attendu "(g) 3 messages prêts : pas en régime, la série repart" 12:03 MALADE RECOVERING
attendu "(g) 1re/5" 12:04 MALADE RECOVERING
attendu "(g) 4e/5" 12:07 MALADE RECOVERING
attendu "(g) 5e minute de suite en régime" 12:08 OK ""
attendu "(g) ensuite" 12:09 OK ""
# Compté par minute de sonde (colonne 6 : l'horloge de la garde), dans ce seul cas
# (colonne 5) : les cas en arrière-plan écrivent aussi dans ce journal.
sondes_g=$(awk -F'\t' '$5 == "g" && $4 ~ /garde_sonde\.py/ {print $6}' "$FAUX_LOG_SSH" | sort | uniq -c)
egal "(g) une seule connexion ssh par minute de sonde" \
    "$(awk '{print $1}' <<< "$sondes_g" | sort -u | tr '\n' ' ')/$(wc -l <<< "$sondes_g")" "1 /10"
egal "(g) aucune autre connexion dans ce cas" "$(awk -F'\t' '$5 == "g"' "$FAUX_LOG_SSH" | wc -l)" "10"
A="$(cat "$DOSSIER/alertes.txt")"
egal "(h) DEBUT CONSUMERS, une fois" "$(grep -c 'DEBUT  MALADE   CONSUMERS' <<< "$A")" "1"
egal "(h) FIN CONSUMERS, une fois" "$(grep -c 'FIN    MALADE   CONSUMERS' <<< "$A")" "1"
egal "(h) DEBUT RECOVERING, une fois" "$(grep -c 'DEBUT  MALADE   RECOVERING' <<< "$A")" "1"
egal "(h) FIN RECOVERING, une fois" "$(grep -c 'FIN    MALADE   RECOVERING' <<< "$A")" "1"
contient "(h) DEBUT à 12:01 avec son niveau et sa mesure" "$A" "^2026-10-01T12:01Z  DEBUT  MALADE   CONSUMERS  .* — 2 consommateurs au lieu de 3"
contient "(h) FIN à 12:02" "$A" "^2026-10-01T12:02Z  FIN    MALADE   CONSUMERS  \(apparu à 2026-10-01T12:01Z, 1 min\)"
egal "(h) à 12:02, la FIN avant le DEBUT" "$(grep '^2026-10-01T12:02Z' <<< "$A" | awk '{print $2}' | tr '\n' ' ')" "FIN DEBUT "
contient "(h) FIN de la contamination à 12:08" "$A" "^2026-10-01T12:08Z  FIN    MALADE   RECOVERING"
contient "(h) une légende en tête" "$(head -1 <<< "$A")" "^# alertes.txt de la garde"
egal "(h) lignes d'alerte en tout (hors légende)" "$(grep -vc '^#' <<< "$A")" "4"

cas h2_non_mesure
scenario '{"prom": {"consommateurs": 2}}'; garde_minute 12:00
export FAUX_SSH_REPONSE="bash: python3: command not found"; garde_minute 12:01; unset FAUX_SSH_REPONSE
garde_minute 12:02
scenario '{"prom": {"consommateurs": "erreur"}}'; garde_minute 12:03
scenario '{}'; garde_minute 12:04
A="$(cat "$DOSSIER/alertes.txt")"
egal "(h2) cause ouverte, sonde muette, requête en erreur : un seul DEBUT" "$(grep -c 'DEBUT  MALADE   CONSUMERS' <<< "$A")" "1"
egal "(h2) … et une seule FIN, quand on la voit vraiment finie" "$(grep 'FIN    MALADE   CONSUMERS' <<< "$A" | cut -c1-17)" "2026-10-01T12:04Z"
contient "(h2) la FIN dit la vraie durée" "$A" "FIN    MALADE   CONSUMERS  \(apparu à 2026-10-01T12:00Z, 4 min\)"

# ==============================================================================
titre "(i) les propositions : écrites ; sans --agir, aucun geste"
cas i1_panne_restee; pilote_on essai-i1
panne_etat "cause-opaque" 11:28 20
scenario '{"chaos": [{"kind": "NetworkChaos", "name": "panne-quelconque", "creation": "2026-10-01T11:28:05Z", "duration": "20m"}]}'
garde_minute 11:49
attendu "(i) objet à durée + 1 min : rien" 11:49 OK ""
garde_minute 11:51
attendu "(i) objet resté plus que durée + 2 min" 11:51 MALADE FAULT_OVERDUE
egal "(i) proposition" "$(val 11:51 action_niveau1_proposee)" "retirer:FAULT_OVERDUE:NetworkChaos/panne-quelconque"
pilote_off

cas i1b_deux_objets; pilote_on essai-i1b
panne_etat "cause-opaque" 11:50 20
scenario '{"chaos": [{"kind": "NetworkChaos", "name": "panne-a", "creation": "2026-10-01T11:50:05Z", "duration": "20m"}, {"kind": "NetworkChaos", "name": "reste-b", "creation": "2026-10-01T11:20:00Z", "duration": "20m"}]}'
garde_minute 12:00
attendu "(i) deux objets, le second dépassé" 12:00 MALADE FAULT_OVERDUE
egal "(i) la proposition nomme l'objet en retard" "$(val 12:00 action_niveau1_proposee)" "retirer:FAULT_OVERDUE:NetworkChaos/reste-b"
pilote_off

cas i2_orphelin
panne_etat "cause-opaque" 11:55 20
garde_minute 12:00
attendu "(i) panne.etat sans pilote vivant" 12:00 MALADE FAULT_ORPHANED
egal "(i) proposition" "$(val 12:00 action_niveau1_proposee)" "retirer:FAULT_ORPHANED"
contient "(i) la proposition est dans alertes.txt, et dit : sans --agir, aucun geste" "$(cat "$DOSSIER/alertes.txt")" "PROPOSITION niveau 1 : retirer:FAULT_ORPHANED — \[PROPOSE : sans --agir, aucun geste\]$"

cas i3_objet_sans_etat
scenario '{"chaos": [{"kind": "StressChaos", "name": "reste", "namespace": "voisin", "creation": "2026-10-01T11:58:00Z", "duration": "20m"}]}'
garde_minute 12:00
attendu "(i) objet Chaos Mesh sans panne.etat" 12:00 MALADE CHAOS_UNDECLARED
egal "(i) proposition" "$(val 12:00 en_panne)/$(val 12:00 action_niveau1_proposee)" "1/retirer:CHAOS_UNDECLARED:StressChaos/reste"

cas i4_effondrement; pilote_on essai-i4
scenario '{"locust": {"req_s": 2.0}}'
for m in 00 01 02 03 04 05 06 07 08 09 10; do garde_minute "12:$m"; done
egal "(i) effondrement depuis 9 min : rien" "$(val 12:09 action_niveau1_proposee)" ""
egal "(i) effondrement depuis 10 min" "$(val 12:10 action_niveau1_proposee)" "term:LOCUST_COLLAPSE"
pilote_off

cas i5_gel; pilote_on essai-i5
scenario '{"prom": {"cpu_commandes": 0.001}}'
for m in 00 01 02 03 04 05 06 07 08 09 10; do garde_minute "12:$m"; done
egal "(i) ts-order-service gelé depuis 10 min" "$(val 12:10 action_niveau1_proposee)" "term:ORDER_FROZEN"
pilote_off

cas i6_7000
export FAUX_COMMANDES=7000
garde_minute 12:00
egal "(i) 7000 commandes → pause proposée" "$(val 12:00 pause_proposee)/$(val 12:00 pause_motif)" "1/ORDERS_HIGH"
contient "(i) pause dans alertes.txt" "$(cat "$DOSSIER/alertes.txt")" "PROPOSITION pause : oui — ORDERS_HIGH \(voir la ligne ACTION pause\)"
egal "(i) drapeau posé sans --agir : motifs et dernière valeur" \
    "$(grep -E '^(POSE_PAR|MOTIFS|VALEURS)=' "$DOSSIER/pause" | tr '\n' ' ')" "POSE_PAR=garde MOTIFS=ORDERS_HIGH VALEURS=commandes=7000 "
unset FAUX_COMMANDES
egal "(i) une minute sur dix seulement : 12:05 sans --commandes" \
    "$(garde_minute 12:05; tail -1 "$FAUX_LOG_SSH" | cut -f4 | grep -c -- --commandes)" "0"
egal "(i) minutes sans mesure (12:01-12:04) : ORDERS_HIGH reste ouvert" "$(grep -c 'FIN    NOTE     ORDERS_HIGH' "$DOSSIER/alertes.txt")" "0"
garde_minute 12:10
egal "(i) 12:10 avec --commandes" "$(tail -1 "$FAUX_LOG_SSH" | cut -f4 | grep -c -- --commandes)" "1"
contient "(i) 12:10 : 1200 commandes lues, fin de la pause" "$(cat "$DOSSIER/alertes.txt")" "12:10Z  PROPOSITION pause : plus de pause proposée"
egal "(i) 12:10 : drapeau encore là (1 minute sans la condition)" "$([ -f "$DOSSIER/pause" ] && echo present)" "present"
garde_minute 12:11
egal "(i) 12:11 : 2 minutes sans la condition, drapeau effacé" "$([ -f "$DOSSIER/pause" ] && echo present || echo efface)" "efface"

cas i7_purges   # seule une purge réussie fait oublier la lecture des commandes
export FAUX_COMMANDES=7000; garde_minute 12:00; unset FAUX_COMMANDES
printf '%s\tdimensionner\t1->2\tok\n' "$(iso 12:02)" >> "$MASTER/journaux/donnees.tsv"
printf '%s\tpurger\t7000\tECHEC\n' "$(iso 12:02)" >> "$MASTER/journaux/donnees.tsv"
garde_minute 12:03
egal "(i) après « dimensionner » et une purge en échec : lecture gardée" "$(val 12:03 commandes)/$(val 12:03 pause_proposee)" "7000/1"
printf '%s\tpurger\t7000\tok\n' "$(iso 12:04)" >> "$MASTER/journaux/donnees.tsv"
printf '%s\tdimensionner\ttas:image\tok\n' "$(iso 12:04)" >> "$MASTER/journaux/donnees.tsv"
garde_minute 12:05
egal "(i) après une purge réussie (suivie d'un dimensionner) : lecture oubliée" "$(val 12:05 commandes)/$(val 12:05 pause_proposee)" "/0"

# ==============================================================================
titre "(q) les gestes du niveau 1 (K1.6b) et le drapeau de pause"
EFFONDRE='{"locust": {"req_s": 2.0}}'   # 2 req/s < min(5 ; 0,2 × 25) : effondré

cas q1_sans_agir; pilote_on essai-q1
panne_etat "cause-opaque" 11:28 20
scenario '{"locust": {"req_s": 2.0}, "chaos": [{"kind": "NetworkChaos", "name": "panne-q1", "creation": "2026-10-01T11:28:05Z", "duration": "20m"}]}'
for m in 00 01 02 03 04 05 06 07 08 09 10 11; do garde_minute "12:$m"; done
egal "(q1) sans --agir : propositions écrites" "$(val 12:00 action_niveau1_proposee)/$(val 12:10 action_niveau1_proposee)" \
    "retirer:FAULT_OVERDUE:NetworkChaos/panne-q1/term:LOCUST_COLLAPSE"
egal "(q1) sans --agir : aucun retrait (faux ssh)" "$(gestes_du_cas)" "0"
egal "(q1) sans --agir : aucun TERM reçu, pilote vivant" "$([ -s "$D/term.recu" ] && echo recu || echo rien)/$(kill -0 "$PILOTE" 2>/dev/null && echo vivant)" "rien/vivant"
egal "(q1) colonne action_niveau1_faite vide partout" "$("$PYTHON" "$ICI/lire.py" "$TSV" --compte action_niveau1_faite=)" "12"
A="$(alertes)"
contient "(q1) la proposition dit le mode" "$A" "PROPOSITION niveau 1 : term:LOCUST_COLLAPSE — \\[PROPOSE : sans --agir, aucun geste\\]"
egal "(q1) aucune ligne ACTION, aucun actions.tsv" "$(compte "$A" 'Z  ACTION ')/$([ -e "$DOSSIER/actions.tsv" ] && echo existe || echo absent)" "0/absent"
pilote_off

cas q2_retrait; pilote_on essai-q2; AGIR=1
export GARDE_PLAFOND_GESTE=8 FAUX_RETIRER=pend
panne_etat "cause-opaque" 11:28 20
scenario '{"chaos": [{"kind": "NetworkChaos", "name": "panne-q2", "creation": "2026-10-01T11:28:05Z", "duration": "20m"}]}'
garde_minute 11:49; garde_minute 11:50
egal "(q2) FAULT_OVERDUE 1 minute : pas encore de geste" "$(val 11:50 causes)/$(gestes_du_cas)" "FAULT_OVERDUE/0"
garde_minute 11:51; attendre_gestes 1
egal "(q2) 2 minutes de suite : un retrait lancé, en arrière-plan" "$(val 11:51 action_niveau1_faite)/$(gestes_du_cas)" "retirer:en_cours/1"
t0=$(date +%s.%N); garde_minute 11:52; t1=$(date +%s.%N)
egal "(q2) le retrait pend : la minute suivante est mesurée quand même" "$(val 11:52 action_niveau1_faite)/$(val 11:52 causes)/$(gestes_du_cas)" "retirer:en_cours/FAULT_OVERDUE/1"
"$PYTHON" -c 'import sys; d=float(sys.argv[2])-float(sys.argv[1]); print(f"        (minute 11:52 rendue en {d:.1f} s, retrait toujours pendu)"); assert d < 8' "$t0" "$t1" \
    && ok "(q2) la minute n'attend pas le retrait" || echec "(q2) la minute a attendu le retrait"
attendre_resultats 1 || echec "(q2) le retrait pendu n'a pas été coupé au plafond local"
garde_minute 11:53
egal "(q2) plafond local atteint : ECHEC" "$(val 11:53 action_niveau1_faite)" "retirer:ECHEC"
export FAUX_RETIRER=echec
for m in 11:54 11:55 11:56 11:57 11:58 11:59 12:00 12:01 12:02; do garde_minute "$m"; done
egal "(q2) moins de 10 min après l'échec : rien" "$(gestes_du_cas)/$(val 12:02 action_niveau1_faite)" "1/"
garde_minute 12:03; attendre_gestes 2
egal "(q2) 10 min après l'échec : la seconde tentative" "$(gestes_du_cas)/$(val 12:03 action_niveau1_faite)" "2/retirer:en_cours"
attendre_resultats 2 || echec "(q2) la seconde tentative n'a rien rendu"
for m in 12:04 12:05 12:06 12:07 12:15; do garde_minute "$m"; done
egal "(q2) seconde en échec, puis plus rien" "$(val 12:04 action_niveau1_faite)/$(gestes_du_cas)" "retirer:ECHEC/2"
A="$(alertes)"
egal "(q2) alertes : 2 DEBUT, 2 FIN ECHEC, 1 décision humaine" \
    "$(compte "$A" 'ACTION DEBUT  retirer  motif=FAULT_OVERDUE cible=NetworkChaos/panne-q2')/$(compte "$A" 'ACTION FIN    retirer  ECHEC')/$(compte "$A" 'Z  NIVEAU 3 — DÉCISION HUMAINE NÉCESSAIRE')" "2/2/1"
contient "(q2) la décision humaine, à 12:04" "$A" "^2026-10-01T12:04Z  NIVEAU 3 — DÉCISION HUMAINE NÉCESSAIRE : la panne est encore là après 2 retraits"
contient "(q2) mode AGIR, code pas encore confirmé : la proposition dit quand viendrait le geste" "$A" \
    "^2026-10-01T11:50Z  PROPOSITION niveau 1 : retirer:FAULT_OVERDUE:NetworkChaos/panne-q2 — \\[AGIR\\] \\(geste dans 1 min si confirmé\\)$"
contient "(q2) le 1er ECHEC dit l'heure de la seconde tentative" "$A" "^2026-10-01T11:53Z  ACTION FIN    retirer  ECHEC .*; seconde tentative au plus tôt à 2026-10-01T12:03Z si la panne est encore là$"
contient "(q2) le 2e ECHEC dit qu'il n'y en aura plus" "$A" "^2026-10-01T12:04Z  ACTION FIN    retirer  ECHEC .*; plus de tentative pour cet incident$"
contient "(q2) la sortie du retrait en chemin relatif" "$A" "ACTION DEBUT  retirer  .*sortie : gestes/retirer-20261001T115130Z-1\\.log\\)$"
contient "(q2) le mode est dit au départ" "$(head -2 <<< "$A")" "INFO   la garde passe en mode AGIR"
egal "(q2) actions.tsv" "$(actions | sed 's/aucune réponse en [0-9]* s/X/; s/code 1 : [^;]*/code 1/')" \
    "retirer lance;retirer ECHEC:X;retirer lance;retirer ECHEC:code 1;retirer decision_humaine;"
egal "(q2) actions.tsv : en-tête, cible, durée" "$(head -1 "$DOSSIER/actions.tsv" | tr '\t' ' ')|$(sed -n 3p "$DOSSIER/actions.tsv" | cut -f4)|$(sed -n 3p "$DOSSIER/actions.tsv" | cut -f6 | cut -d. -f1)" \
    "instant geste motif cible resultat duree_s|NetworkChaos/panne-q2|8"
sondes=$(awk -F'\t' -v c="$FAUX_CAS" '$5 == c && $4 ~ /garde_sonde\.py/ {print $6}' "$FAUX_LOG_SSH" | sort | uniq -c)
egal "(q2) sonde : une connexion par minute ; les 2 gestes comptés à part" \
    "$(awk '{print $1}' <<< "$sondes" | sort -u)/$(wc -l <<< "$sondes")/$(gestes_du_cas)" "1/20/2"
egal "(q2) TERM jamais envoyé au pilote" "$([ -s "$D/term.recu" ] && echo recu || echo rien)" "rien"
pilote_off

cas q3_orphelin; AGIR=1          # panne.etat sans pilote, dans sa durée, puis au-delà
panne_etat "cause-opaque" 11:55 20
for m in 00 01 02 03 04 05; do garde_minute "12:$m"; done
egal "(q3) FAULT_ORPHANED dans sa durée : proposé, aucun retrait" "$(val 12:05 causes)/$(val 12:05 action_niveau1_proposee)/$(gestes_du_cas)" \
    "FAULT_ORPHANED/retirer:FAULT_ORPHANED/0"
garde_minute 12:16; garde_minute 12:17
egal "(q3) au-delà de DEBUT + DUREE + 2 min : FAULT_OVERDUE (panne.etat)" "$(val 12:16 causes)|$(val 12:17 causes)|$(val 12:17 action_niveau1_proposee)" \
    "FAULT_ORPHANED|FAULT_ORPHANED,FAULT_OVERDUE|retirer:FAULT_OVERDUE:panne.etat"
garde_minute 12:18; attendre_gestes 1
egal "(q3) confirmé 2 min : retrait lancé" "$(val 12:18 action_niveau1_faite)/$(gestes_du_cas)" "retirer:en_cours/1"
attendre_resultats 1 || echec "(q3) le retrait n'a rien rendu"
garde_minute 12:19
egal "(q3) retrait réussi, panne partie" "$(val 12:19 action_niveau1_faite)/$(val 12:19 en_panne)/$(val 12:19 causes)" "retirer:ok/0/RECOVERING"
contient "(q3) incident clos dans alertes.txt" "$(alertes)" "12:19Z  INFO   panne restée : plus rien à retirer"
A="$(alertes)"
contient "(q3) mode AGIR : FAULT_ORPHANED dit pourquoi aucun geste ne suit" "$A" \
    "12:00Z  PROPOSITION niveau 1 : retirer:FAULT_ORPHANED — \\[AGIR\\] \\(pas de geste : dans sa durée déclarée, le minuteur de panne.sh retire la panne"
contient "(q3) la cible panne.etat est dite avec sa cause" "$A" "12:18Z  ACTION DEBUT  retirer  motif=FAULT_OVERDUE cible=panne déclarée « cause-opaque » \\(panne.etat\\) tentative 1/2"
egal "(q3) actions.tsv" "$(actions)" "retirer lance;retirer ok;"

cas q4_objet_base; AGIR=1        # un objet qui porte le nom du réglage de base, hors train-ticket
scenario '{"chaos": [{"kind": "NetworkChaos", "name": "consommateur-temps-de-service", "namespace": "voisin", "creation": "2026-10-01T11:00:00Z"}]}'
for m in 00 01 02 03 04 05 06; do garde_minute "12:$m"; done
egal "(q4) objet de base : proposé, jamais retiré" "$(val 12:06 action_niveau1_proposee)/$(gestes_du_cas)" \
    "retirer:CHAOS_UNDECLARED:NetworkChaos/consommateur-temps-de-service/0"
egal "(q4) le refus est dit une fois, la cible une fois" "$(compte "$(alertes)" 'ACTION REFUS  retirer  l.objet de base \(140 ms\) : jamais retiré par la garde \(motif=CHAOS_UNDECLARED cible=NetworkChaos/consommateur-temps-de-service\)$')" "1"

cas q5_non_declare; AGIR=1       # objet sans panne.etat ni pilote : 5 minutes de suite
scenario '{"chaos": [{"kind": "StressChaos", "name": "reste-q5", "namespace": "voisin", "creation": "2026-10-01T11:58:00Z", "duration": "60m"}]}'
for m in 00 01 02 03 04; do garde_minute "12:$m"; done; attendre_gestes 1
egal "(q5) CHAOS_UNDECLARED : rien à 4 min, retrait à 5 min" "$(val 12:03 action_niveau1_faite)/$(val 12:04 action_niveau1_faite)/$(gestes_du_cas)" "/retirer:en_cours/1"
attendre_resultats 1; garde_minute 12:05
egal "(q5) retrait réussi" "$(val 12:05 action_niveau1_faite)/$(val 12:05 en_panne)" "retirer:ok/0"
cas q5b_non_declare_pilote; AGIR=1; pilote_on essai-q5b
scenario '{"chaos": [{"kind": "StressChaos", "name": "reste-q5b", "namespace": "voisin", "creation": "2026-10-01T11:58:00Z", "duration": "60m"}]}'
for m in 00 01 02 03 04 05 06; do garde_minute "12:$m"; done
egal "(q5b) CHAOS_UNDECLARED avec un pilote vivant : alerte seulement" "$(val 12:06 causes)/$(gestes_du_cas)" "CHAOS_UNDECLARED/0"
contient "(q5b) la proposition dit pourquoi aucun geste ne suit" "$(alertes)" \
    "PROPOSITION niveau 1 : retirer:CHAOS_UNDECLARED:StressChaos/reste-q5b — \\[AGIR\\] \\(pas de geste : un pilote vit"
pilote_off

cas q6_term; AGIR=1; pilote_on essai-q6
scenario "$EFFONDRE"
for m in 00 01 02 03 04 05 06 07 08 09; do garde_minute "12:$m"; done
egal "(q6) effondré depuis 9 min : rien" "$(val 12:09 action_niveau1_faite)/$([ -e "$D/term.recu" ] && echo recu || echo rien)" "/rien"
garde_minute 12:10
for _ in $(seq 50); do kill -0 "$PILOTE" 2>/dev/null || break; sleep 0.1; done
egal "(q6) 10 min : SIGTERM reçu une fois par le faux pilote, qui s'arrête" \
    "$(val 12:10 action_niveau1_faite)/$(cat "$D/term.recu" 2>/dev/null)/$(kill -0 "$PILOTE" 2>/dev/null && echo vivant || echo arrete)" "term:envoye/TERM $PILOTE/arrete"
garde_minute 12:11
A="$(alertes)"
contient "(q6) ACTION DEBUT term dans alertes.txt" "$A" "12:10Z  ACTION DEBUT  term     SIGTERM envoyé à campagne.sh essai-q6 \\(pid $PILOTE\\) — motif term:LOCUST_COLLAPSE"
contient "(q6) puis l'arrêt du pilote" "$A" "12:11Z  ACTION FIN    term     campagne.sh essai-q6 \\(pid $PILOTE\\) s'est arrêté, 1 min après TERM"
egal "(q6) actions.tsv" "$(actions)" "term envoye;term pilote_arrete;"
pilote_off

cas q7_tetu; AGIR=1
FAUX_PILOTE_TETU=1 pilote_on essai-q7
scenario "$EFFONDRE"
for m in 00 01 02 03 04 05 06 07 08 09 10 11 12; do garde_minute "12:$m"; done
garde_minute 12:54
egal "(q7) TERM envoyé une seule fois, pilote têtu toujours vivant, 44 min après : pas encore d'alerte" \
    "$(wc -l < "$D/term.recu")/$(kill -0 "$PILOTE" 2>/dev/null && echo vivant)/$(compte "$(alertes)" 'Z  NIVEAU 3')" "1/vivant/0"
garde_minute 12:55; garde_minute 12:56
egal "(q7) 45 min après TERM : décision humaine, une fois ; aucun autre signal (pas de kill -9)" \
    "$(compte "$(alertes)" '12:55Z  NIVEAU 3 — DÉCISION HUMAINE NÉCESSAIRE : campagne.sh essai-q7')/$(compte "$(alertes)" 'Z  NIVEAU 3')/$(wc -l < "$D/term.recu")/$(kill -0 "$PILOTE" 2>/dev/null && echo vivant)" \
    "1/1/1/vivant"
egal "(q7) actions.tsv" "$(actions)" "term envoye;term toujours_vivant:decision_humaine;"
pilote_off

cas q8_pid_reutilise; AGIR=1; pilote_on essai-q8
scenario "$EFFONDRE"
for m in 00 01 02 03 04 05 06 07 08 09; do garde_minute "12:$m"; done
# Le pid du pilote est « réutilisé » : même ligne de commande, autre date de démarrage.
rm -f "${GARDE_PROC:?}/${PILOTE:?}"; mkdir "$GARDE_PROC/$PILOTE"
cp "/proc/$PILOTE/cmdline" "$GARDE_PROC/$PILOTE/cmdline"
awk '{ $22 = $22 + 1; print }' "/proc/$PILOTE/stat" > "$GARDE_PROC/$PILOTE/stat"
garde_minute 12:10
egal "(q8) pid réutilisé : aucun signal, la série repart" \
    "$(val 12:10 action_niveau1_faite)/$(val 12:10 action_niveau1_proposee)/$([ -e "$D/term.recu" ] && echo recu || echo rien)" "//rien"
pilote_off

# signaler_pilote relit le pid JUSTE AVANT le signal : seuls des processus du test.
cas q8b_relecture
"$PYTHON" - "$GARDE" "$BAC/campagne.sh" "$D" <<'EOF' && ok "(q8b) relu juste avant : autre date de démarrage, autre nom, autre processus → aucun signal ; le bon → TERM" || echec "(q8b) relecture avant le signal"
import importlib.util, os, subprocess, sys, time
garde, faux_pilote, d = sys.argv[1:4]
proc = os.path.join(d, "proc"); os.makedirs(proc)
os.environ["GARDE_PROC"] = proc
spec = importlib.util.spec_from_file_location("garde_lu", garde)
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
recu = os.path.join(d, "term.recu")
p = subprocess.Popen(["bash", faux_pilote, "essai-u"], env=dict(os.environ, FAUX_PILOTE_TERM=recu))
s = subprocess.Popen(["sleep", "300"])
try:
    for _ in range(50):
        if b"campagne.sh" in open(f"/proc/{p.pid}/cmdline", "rb").read():
            break
        time.sleep(0.1)
    time.sleep(0.2)   # le temps que le faux pilote pose son trap
    for x in (p.pid, s.pid):
        os.symlink(f"/proc/{x}", os.path.join(proc, str(x)))
    debut = g.lire_processus(p.pid)["debut"]
    oui, r = g.signaler_pilote(p.pid, "essai-u", debut + 1); print("        ", r); assert not oui and "réutilisé" in r
    oui, r = g.signaler_pilote(p.pid, "essai-autre", debut); print("        ", r); assert not oui
    oui, r = g.signaler_pilote(s.pid, "essai-u", g.lire_processus(s.pid)["debut"]); print("        ", r); assert not oui
    time.sleep(0.5)
    assert not os.path.exists(recu) and p.poll() is None and s.poll() is None, "un signal est parti"
    oui, r = g.signaler_pilote(p.pid, "essai-u", debut); print("        ", r); assert oui
    p.wait(timeout=5)
    assert open(recu).read() == f"TERM {p.pid}\n"
finally:
    for x in (p, s):
        if x.poll() is None:
            x.kill(); x.wait()
EOF

cas q9_pause                     # sans --agir : le drapeau est du niveau 0
scenario '{"prom": {"cpu_commandes": 1.3}}'
garde_minute 12:00; garde_minute 12:01
egal "(q9) drapeau posé, contenu" "$(tr '\n' ' ' < "$DOSSIER/pause")" \
    "POSE_PAR=garde DEPUIS=2026-10-01T12:00:30Z INSTANT=2026-10-01T12:01:30Z MOTIFS=ORDER_CPU_HIGH VALEURS=cpu_commandes=1.300 "
scenario '{}'; garde_minute 12:02
export FAUX_SSH_REPONSE="bash: python3: command not found"; garde_minute 12:03; unset FAUX_SSH_REPONSE
garde_minute 12:04
egal "(q9) 1 minute sans la condition, puis une minute non mesurée, puis 1 : drapeau gardé" "$([ -f "$DOSSIER/pause" ] && echo present)" "present"
garde_minute 12:05
egal "(q9) 2 minutes mesurées de suite sans la condition : effacé" "$([ -f "$DOSSIER/pause" ] && echo present || echo efface)" "efface"
A="$(alertes)"
egal "(q9) alertes : posé à 12:00, effacé à 12:05" "$(grep -oE '^[^ ]+  ACTION (DEBUT|FIN) +pause' <<< "$A" | cut -c12-16,18- | tr -s ' ' | tr '\n' ';')" \
    "12:00 ACTION DEBUT pause;12:05 ACTION FIN pause;"
egal "(q9) actions.tsv" "$(actions)" "pause posee;pause effacee;"
cas q9b_pause_main               # un drapeau posé à la main n'est jamais touché
mkdir -p "$DOSSIER"; echo "pause manuelle" > "$DOSSIER/pause"
scenario '{"prom": {"cpu_commandes": 1.3}}'; garde_minute 12:00
scenario '{}'; garde_minute 12:01; garde_minute 12:02; garde_minute 12:03
egal "(q9b) drapeau manuel intact" "$(cat "$DOSSIER/pause")" "pause manuelle"

cas q10_seuil; pilote_on essai-q10   # N = palier d'AVANT la panne (paliers.tsv), pas la panne de charge
palier 10 "11:00"
panne_etat "cause-opaque" 12:00 20
palier 20 "12:01" panne
scenario '{"locust": {"voyageurs": 20, "req_s": 3.0}}'
garde_minute 12:05
seuil() { "$PYTHON" -c 'import json,sys; d=json.load(open(sys.argv[1])); e=d["effondrement"]; m=json.load(open(sys.argv[2])); print(e["n"], e["source"], e["seuil_req_s"], m.get("effondrement_depuis"))' "$DOSSIER/dernier.json" "$DOSSIER/memoire.json"; }
egal "(q10) pendant la panne : N = 10 (palier d'avant), seuil 2 req/s ; 3 req/s n'est pas un effondrement" "$(seuil)" "10 palier d'avant la panne 2.0 None"
scenario '{"locust": {"voyageurs": 20, "req_s": 1.5}}'; garde_minute 12:06
egal "(q10) 1,5 req/s < 2 : effondrement compté" "$(seuil)" "10 palier d'avant la panne 2.0 2026-10-01T12:06Z"
pilote_off
cas q10b_seuil_sans_panne; pilote_on essai-q10b
palier 20 "11:30"
scenario '{"locust": {"voyageurs": 20, "req_s": 3.0}}'; garde_minute 12:05
egal "(q10b) hors panne : N = palier courant (20), seuil 4 req/s" "$(seuil)" "20 palier courant 4.0 2026-10-01T12:05Z"
pilote_off
cas q10c_ligne_mal_formee; pilote_on essai-q10c   # une ligne illisible juste avant la panne
palier 10 "11:00"
printf '%s\t%s\t?\t?\t1\ttrain-ticket\tdemande\n' "$(iso 11:59)" "$(iso 11:59)" >> "$MASTER/journaux/paliers.tsv"
panne_etat "cause-opaque" 12:00 20
palier 20 "12:01" panne
scenario '{"locust": {"voyageurs": 20, "req_s": 3.0}}'; garde_minute 12:05
egal "(q10c) palier illisible juste avant la panne : on prend le précédent lisible (10)" "$(seuil)" "10 palier d'avant la panne 2.0 None"
pilote_off

# Relecture juste avant le signal, de bout en bout : le pilote est vu au début de la
# minute ; pendant la sonde (lente), son pid est « réutilisé » (autre date de démarrage).
cas q8c_relu_avant_signal; AGIR=1; pilote_on essai-q8c
scenario "$EFFONDRE"
for m in 00 01 02 03 04 05 06 07 08 09; do garde_minute "12:$m"; done
( for _ in $(seq 200); do   # dès que la sonde de 12:10 est partie (le pilote est déjà lu)
      awk -F'\t' -v c="$FAUX_CAS" '$5 == c && $6 ~ /T12:10:30Z$/' "$FAUX_LOG_SSH" | grep -q . && break; sleep 0.05
  done
  rm -f "${GARDE_PROC:?}/${PILOTE:?}"; mkdir "$GARDE_PROC/$PILOTE"
  cp "/proc/$PILOTE/cmdline" "$GARDE_PROC/$PILOTE/cmdline"
  awk '{ $22 = $22 + 1; print }' "/proc/$PILOTE/stat" > "$GARDE_PROC/$PILOTE/stat"
  touch "$D/change.fait" ) & CHANGE=$!
FAUX_SSH_LENT=4 garde_minute 12:10; wait "$CHANGE"
egal "(q8c) pid changé pendant la minute : proposé, relu, aucun signal" \
    "$([ -e "$D/change.fait" ] && echo change)/$(val 12:10 action_niveau1_proposee)/$(val 12:10 action_niveau1_faite)/$([ -e "$D/term.recu" ] && echo recu || echo rien)" \
    "change/term:LOCUST_COLLAPSE//rien"
contient "(q8c) le refus dit la relecture" "$(alertes)" "12:10Z  ACTION REFUS  term     pid $PILOTE réutilisé"
pilote_off

# Le mode boucle : le retrait suivi par son objet Popen (poll, puis récolté).
cas q11_popen
panne_etat "cause-opaque" 11:30 20
"$PYTHON" - "$GARDE" "$DOSSIER" "$MASTER/journaux/panne.etat" <<'EOF' && ok "(q11) mode boucle : retrait suivi par son Popen, récolté, résultat ok" || echec "(q11) mode boucle : Popen"
import importlib.util, os, sys, time
spec = importlib.util.spec_from_file_location("garde_lu", sys.argv[1])
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
garde = g.Garde(sys.argv[2], True, agir=True)
incident = garde.mem["incident_retrait"] = {"debut": "2026-10-01T12:00Z", "tentatives": [], "refus": [], "humain": False}
assert garde.lancer_retrait("2026-10-01T12:00Z", "FAULT_OVERDUE", "panne.etat", incident) == "retirer:en_cours"
p = garde.geste_proc
assert p is not None
for _ in range(150):
    r = garde.suivre_retrait("2026-10-01T12:01Z")
    if r != "retirer:en_cours":
        break
    time.sleep(0.1)
print("        ", r, "; code du sous-processus :", p.returncode)
assert r == "retirer:ok", r
assert p.returncode == 0, "sous-processus non récolté"
assert garde.geste_proc is None and garde.mem["geste"] is None
assert not os.path.exists(sys.argv[3]), "panne.etat encore là"
EOF

# Un objet RESTÉ (injection d'avant) en retard pendant la fenêtre de la panne neuve
# du pilote : « panne.sh retirer » lèverait la panne neuve. Aucun geste.
cas q12_fenetre; AGIR=1; pilote_on essai-q12
panne_etat "cause-opaque" 11:50 20       # la panne neuve : fenêtre jusqu'à 11:50 + 20 + 2 = 12:12
scenario '{"chaos": [{"kind": "StressChaos", "name": "reste-q12", "namespace": "voisin", "creation": "2026-10-01T11:00:00Z", "duration": "20m"}]}'
for m in 00 01 02 03; do garde_minute "12:$m"; done
egal "(q12) objet resté en retard, pilote dans sa fenêtre : proposé, aucun retrait" \
    "$(val 12:03 causes)/$(val 12:03 action_niveau1_proposee)/$(gestes_du_cas)" "FAULT_OVERDUE/retirer:FAULT_OVERDUE:StressChaos/reste-q12/0"
egal "(q12) une ligne ACTION REFUS, une fois" \
    "$(compte "$(alertes)" 'ACTION REFUS  retirer  le pilote est dans sa fenêtre déclarée \(jusqu.à 2026-10-01T12:12Z\) : c.est à lui de retirer')" "1"
garde_minute 12:13; garde_minute 12:14; attendre_gestes 1
egal "(q12) fenêtre passée, panne.etat lui-même en retard : retrait, pilote vivant (l'exception voulue)" \
    "$(val 12:14 action_niveau1_faite)/$(gestes_du_cas)" "retirer:en_cours/1"
attendre_resultats 1 || echec "(q12) le retrait n'a rien rendu"
garde_minute 12:15
egal "(q12) retrait réussi" "$(val 12:15 action_niveau1_faite)" "retirer:ok"
pilote_off

# L'effondrement se compte en minutes MESURÉES de suite.
cas q13_effondrement_trou; AGIR=1; pilote_on essai-q13
scenario "$EFFONDRE"
for m in 00 01 02 03 04 05; do garde_minute "12:$m"; done
export FAUX_SSH_REPONSE="bash: python3: command not found"; garde_minute 12:06; unset FAUX_SSH_REPONSE
for m in 07 08 09 10; do garde_minute "12:$m"; done
egal "(q13) effondré, 12:06 non mesurée, effondré : rien à 12:10" \
    "$(val 12:10 action_niveau1_proposee)/$(val 12:10 action_niveau1_faite)/$([ -e "$D/term.recu" ] && echo recu || echo rien)" "//rien"
garde_minute 12:30      # garde arrêtée de 12:11 à 12:29
egal "(q13) garde arrêtée 19 min, puis 1 minute effondrée : rien" \
    "$(val 12:30 action_niveau1_proposee)/$([ -e "$D/term.recu" ] && echo recu || echo rien)" "/rien"
for m in 31 32 33 34 35 36 37 38 39 40; do garde_minute "12:$m"; done
for _ in $(seq 50); do [ -s "$D/term.recu" ] && break; sleep 0.1; done
egal "(q13) 11 minutes mesurées de suite (12:30-12:40) : TERM à 12:40, pas avant" \
    "$(val 12:39 action_niveau1_faite)/$(val 12:40 action_niveau1_faite)/$(cat "$D/term.recu" 2>/dev/null)" "/term:envoye/TERM $PILOTE"
pilote_off

# La sonde n'a pas pu dire ce qui agit sur le master : on attend (et on le dit).
reponse_sonde() {   # <gestes_en_cours en JSON | absent> — la dernière photo, gestes changés
    "$PYTHON" -c 'import json,sys
m = json.load(open(sys.argv[1]))["mesure"]
if sys.argv[2] == "absent":
    m.pop("gestes_en_cours", None)
else:
    m["gestes_en_cours"] = json.loads(sys.argv[2])
print(json.dumps(m))' "$DOSSIER/dernier.json" "$1"
}
cas q14_gestes_inconnus; AGIR=1
panne_etat "cause-opaque" 11:30 20       # sans pilote, en retard depuis 11:52
garde_minute 12:00
export FAUX_SSH_REPONSE="$(reponse_sonde '{"erreur": "PermissionError: /proc"}')"
garde_minute 12:01; garde_minute 12:02
export FAUX_SSH_REPONSE="$(reponse_sonde absent)"   # une sonde ancienne
garde_minute 12:03; unset FAUX_SSH_REPONSE
egal "(q14) gestes du master inconnus (erreur, puis absents) : proposé, aucun retrait" \
    "$(val 12:02 action_niveau1_proposee)/$(val 12:03 action_niveau1_proposee)/$(gestes_du_cas)" \
    "retirer:FAULT_OVERDUE:panne.etat/retirer:FAULT_OVERDUE:panne.etat/0"
egal "(q14) le refus est dit une fois" \
    "$(compte "$(alertes)" 'ACTION REFUS  retirer  la sonde n.a pas pu dire ce qui agit sur le master \(gestes_en_cours\) : on attend')" "1"
garde_minute 12:04; attendre_gestes 1
egal "(q14) gestes de nouveau connus : retrait" "$(val 12:04 action_niveau1_faite)/$(gestes_du_cas)" "retirer:en_cours/1"
attendre_resultats 1 || echec "(q14) le retrait n'a rien rendu"
garde_minute 12:05

# Le retrait du pilote dure (rollout) : panne.etat en retard pendant qu'un panne.sh
# agit = seulement noté ; ensuite, sans panne.sh, MALADE.
cas q15_retrait_du_pilote; AGIR=1; pilote_on essai-q15
panne_etat "cause-opaque" 11:30 20       # en retard à partir de 11:52
garde_minute 11:51
export FAUX_SSH_REPONSE="$(reponse_sonde '["panne.sh retirer"]')"
garde_minute 11:52; garde_minute 11:53; unset FAUX_SSH_REPONSE
egal "(q15) un panne.sh agit : FAULT_OVERDUE de panne.etat seulement noté, rien de proposé" \
    "$(val 11:52 etat)/$(val 11:53 etat)/$(val 11:53 notes | tr ',' '\n' | grep -c '^FAULT_OVERDUE$')/$(val 11:53 action_niveau1_proposee)/$(gestes_du_cas)" "OK/OK/1//0"
garde_minute 11:54
egal "(q15) plus de panne.sh : MALADE FAULT_OVERDUE" "$(val 11:54 causes)" "FAULT_OVERDUE"
pilote_off

# Un incident ouvert est clos aussi sans --agir : la panne suivante en ouvre un neuf.
cas q16_incident_mode; AGIR=1; export FAUX_RETIRER=echec
panne_etat "cause-opaque" 11:30 20       # sans pilote, en retard
garde_minute 12:00; garde_minute 12:01; attendre_gestes 1; attendre_resultats 1
garde_minute 12:02
egal "(q16) premier retrait en échec" "$(val 12:02 action_niveau1_faite)" "retirer:ECHEC"
unset AGIR; rm -f "$MASTER/journaux/panne.etat"     # retirée à la main ; garde sans --agir
garde_minute 12:03
contient "(q16) sans --agir, l'incident est clos quand même" "$(alertes)" \
    "12:03Z  INFO   panne restée : plus rien à retirer \(incident ouvert à 2026-10-01T12:01Z, 1 retrait"
AGIR=1; export FAUX_RETIRER=ok
panne_etat "cause-opaque" 11:40 20       # une nouvelle panne restée (en retard depuis 12:02)
garde_minute 12:04; garde_minute 12:05; attendre_gestes 2
egal "(q16) nouvel incident : retrait sans attendre, tentative 1/2" \
    "$(val 12:05 action_niveau1_faite)/$(gestes_du_cas)/$(compte "$(alertes)" '12:05Z  ACTION DEBUT  retirer  .* tentative 1/2')" "retirer:en_cours/2/1"
attendre_resultats 2 || echec "(q16) le second retrait n'a rien rendu"
garde_minute 12:06

# Plafond global : 4 retraits lancés en 6 h (mémoire préparée) → niveau 3, aucun geste.
cas q17_plafond_global; AGIR=1
mkdir -p "$DOSSIER"
echo '{"retraits_lances": ["2026-10-01T09:00:00Z", "2026-10-01T09:40:00Z", "2026-10-01T10:20:00Z", "2026-10-01T11:00:00Z"]}' > "$DOSSIER/memoire.json"
panne_etat "cause-opaque" 11:30 20
for m in 00 01 02 03; do garde_minute "12:$m"; done
egal "(q17) 4 retraits en 6 h : aucun geste, une alerte niveau 3" \
    "$(gestes_du_cas)/$(compte "$(alertes)" '12:01Z  NIVEAU 3 — DÉCISION HUMAINE NÉCESSAIRE : 4 retraits lancés en 6 h \(plafond 4\)')/$(compte "$(alertes)" 'Z  NIVEAU 3')" "0/1/1"

# ==============================================================================
titre "(j) deux gardes en même temps : la seconde refuse"
cas j
"$PYTHON" "$GARDE" --dossier "$DOSSIER" --sans-s3 > "$D/premiere.txt" 2>&1 & P1=$!
for _ in $(seq 150); do [ -f "$TSV" ] && [ "$("$PYTHON" "$ICI/lire.py" "$TSV" --lignes)" -ge 1 ] && break; sleep 0.2; done
"$PYTHON" "$GARDE" --une-fois --dossier "$DOSSIER" --sans-s3 > "$D/seconde.txt" 2>&1; code=$?
egal "(j) code de la seconde" "$code" "3"
contient "(j) message" "$(cat "$D/seconde.txt")" "une autre garde tourne déjà"
kill -TERM "$P1"; wait "$P1"; code=$?
egal "(j) la première s'arrête proprement sur TERM" "$code" "0"
contient "(j) message d'arrêt" "$(cat "$D/premiere.txt")" "garde : arrêtée"

cas j2_entete
mkdir -p "$DOSSIER"; printf 'ancien\tformat\n2026-10-01T11:59Z\tOK\n' > "$TSV"
"$PYTHON" -c 'import fcntl,sys,time; f=open(sys.argv[1],"a+"); fcntl.flock(f, fcntl.LOCK_EX); open(sys.argv[2],"w").close(); time.sleep(60)' \
    "$DOSSIER/garde.verrou" "$D/tenu" & P2=$!
for _ in $(seq 50); do [ -f "$D/tenu" ] && break; sleep 0.1; done
"$PYTHON" "$GARDE" --une-fois --dossier "$DOSSIER" --sans-s3 > "$D/seconde.txt" 2>&1; code=$?
kill "$P2" 2>/dev/null; wait "$P2" 2>/dev/null
egal "(j2) verrou tenu, colonnes différentes : code" "$code" "3"
egal "(j2) garde.tsv intact" "$(cat "$TSV")" "$(printf 'ancien\tformat\n2026-10-01T11:59Z\tOK')"
egal "(j2) rien d'autre d'écrit" "$(cd "$DOSSIER" && ls | tr '\n' ' ')" "garde.tsv garde.verrou "

# ==============================================================================
titre "(m) memoire.json cassé : 3 minutes en erreur, puis mis de côté ; alertes ouvertes fermées, mode gardé"
cas m
garde_minute 12:00
echo '{"commandes_essai": "pas-une-minute"}' > "$DOSSIER/memoire.json"
for m in 01 02 03 04; do garde_minute "12:$m"; done
egal "(m) 12:01-12:03 en erreur de la garde" "$(val 12:01 causes)/$(val 12:02 causes)/$(val 12:03 causes)" \
    "MEASURE_FAILED:garde/MEASURE_FAILED:garde/MEASURE_FAILED:garde"
egal "(m) memoire.json mis de côté une fois" "$(ls "$DOSSIER" | grep -c '^memoire.json.*\.casse$')" "1"
contient "(m) dit dans alertes.txt" "$(cat "$DOSSIER/alertes.txt")" "memoire.json mis de côté"
attendu "(m) 12:04 mesurée de nouveau (contaminée)" 12:04 MALADE RECOVERING

# Les alertes ouvertes d'alertes.txt, comme suivi.py les lit (DEBUT sans FIN après).
ouvertes() { awk '$2 == "DEBUT" { o[$4] = 1 } $2 == "FIN" { delete o[$4] } END { for (c in o) print c }' \
    "$DOSSIER/alertes.txt" | sort | tr '\n' ' '; }
mode_memoire() { "$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("mode"))' "$DOSSIER/memoire.json"; }
casser_memoire() {   # <clé> <valeur JSON> — memoire.json gardé, une clé remplacée
    "$PYTHON" -c 'import json,sys; m=json.load(open(sys.argv[1])); m[sys.argv[2]]=json.loads(sys.argv[3]); json.dump(m, open(sys.argv[1], "w"))' \
        "$DOSSIER/memoire.json" "$1" "$2"
}

cas m2_alertes_fermees; AGIR=1   # mémoire lisible : ses alertes ouvertes reçoivent une FIN
scenario '{"prom": {"consommateurs": 2}}'
garde_minute 12:00
egal "(m2) mode AGIR écrit dans memoire.json au départ" "$(mode_memoire)" "agir"
casser_memoire commandes_essai '"pas-une-minute"'
for m in 01 02 03; do garde_minute "12:$m"; done
A="$(alertes)"
egal "(m2) mémoire remise à neuf à 12:03 : plus aucune alerte ouverte" "$(ouvertes)" ""
contient "(m2) FIN de CONSUMERS (ouverte depuis 12:00, non mesurée ensuite)" "$A" \
    "^2026-10-01T12:03Z  FIN    MALADE   CONSUMERS  \(apparu à 2026-10-01T12:00Z, 3 min ; fermée sans mesure : mémoire remise à neuf\)$"
contient "(m2) FIN de MEASURE_FAILED:garde" "$A" "^2026-10-01T12:03Z  FIN    MALADE   MEASURE_FAILED:garde  \(apparu à 2026-10-01T12:01Z, 2 min ; fermée sans mesure"
egal "(m2) les FIN avant la ligne « mis de côté », pas de ligne « oubliées » (la mémoire les connaissait)" \
    "$(grep '^2026-10-01T12:03Z' <<< "$A" | awk '{print $2}' | tr '\n' ' ')/$(compte "$A" 'oubliées')" "FIN FIN INFO /0"
egal "(m2) le mode est gardé dans la mémoire neuve" "$(mode_memoire)" "agir"
garde_minute 12:04
egal "(m2) 12:04 : le mode n'est pas redit (une seule ligne « passe en mode »)" "$(compte "$(alertes)" 'passe en mode')" "1"
attendu "(m2) 12:04 mesurée de nouveau" 12:04 MALADE CONSUMERS
egal "(m2) 12:04 : CONSUMERS repart d'un DEBUT" "$(ouvertes)" "CONSUMERS "

cas m3_alertes_illisibles   # la clé « alertes » illisible : relues dans alertes.txt
scenario '{"prom": {"consommateurs": 2}}'
garde_minute 12:00
egal "(m3) mode PROPOSE écrit dans memoire.json au départ (sans --agir)" "$(mode_memoire)" "propose"
casser_memoire alertes '"pas un dictionnaire"'
for m in 01 02 03; do garde_minute "12:$m"; done
A="$(alertes)"
egal "(m3) 12:01-12:03 en erreur, puis memoire.json mis de côté" \
    "$(val 12:03 causes)/$(ls "$DOSSIER" | grep -c '^memoire.json.*\.casse$')" "MEASURE_FAILED:garde/1"
contient "(m3) une ligne INFO : alertes ouvertes oubliées" "$A" \
    "^2026-10-01T12:03Z  INFO   alertes ouvertes oubliées \(mémoire remise à neuf, relues dans alertes.txt\) : CONSUMERS$"
contient "(m3) puis la FIN de CONSUMERS" "$A" "^2026-10-01T12:03Z  FIN    MALADE   CONSUMERS  \(apparu à 2026-10-01T12:00Z, 3 min ; fermée sans mesure"
egal "(m3) plus aucune alerte ouverte" "$(ouvertes)" ""
egal "(m3) le mode est gardé dans la mémoire neuve" "$(mode_memoire)" "propose"
scenario '{}'; garde_minute 12:04
attendu "(m3) 12:04 mesurée de nouveau (contaminée)" 12:04 MALADE RECOVERING

cas m4_memoire_illisible_au_depart   # memoire.json pas du JSON : mémoire neuve dès le départ
scenario '{"prom": {"consommateurs": 2}}'
garde_minute 12:00
echo '{"alertes": {"CONSUMERS": ' > "$DOSSIER/memoire.json"
scenario '{}'; garde_minute 12:01
A="$(alertes)"
contient "(m4) une ligne INFO au départ" "$A" \
    "^2026-10-01T12:01Z  INFO   alertes ouvertes oubliées \(memoire.json absent ou illisible au départ, relues dans alertes.txt\) : CONSUMERS$"
egal "(m4) une seule FIN de CONSUMERS (la garde ne la connaît plus)" "$(compte "$A" 'FIN    MALADE   CONSUMERS  \(apparu à 2026-10-01T12:00Z, 1 min ; fermée sans mesure')" "1"
egal "(m4) plus aucune alerte ouverte" "$(ouvertes)" ""
egal "(m4) memoire.json réécrit, avec le mode" "$(mode_memoire)" "propose"
# L'étiquette de 12:01 n'est pas fixée ici (mémoire neuve non contaminée, au
# contraire de memoire_cassee) : seulement « mesurée, sans erreur de la garde ».
egal "(m4) 12:01 mesurée, sans erreur de la garde" "$(val 12:01 causes | grep -c 'MEASURE_')" "0"
garde_minute 12:02
egal "(m4) au départ suivant (mémoire lisible), rien de plus" "$(compte "$(alertes)" '^2026.*(oubliées|fermée sans mesure)')" "2"

cas m5_memoire_absente_au_depart   # memoire.json effacé : mémoire neuve dès le départ
scenario '{"prom": {"consommateurs": 2}}'
garde_minute 12:00
rm "$DOSSIER/memoire.json"
scenario '{}'; garde_minute 12:01
A="$(alertes)"
contient "(m5) une ligne INFO au départ" "$A" \
    "^2026-10-01T12:01Z  INFO   alertes ouvertes oubliées \(memoire.json absent ou illisible au départ, relues dans alertes.txt\) : CONSUMERS$"
egal "(m5) une seule FIN de CONSUMERS" "$(compte "$A" 'FIN    MALADE   CONSUMERS  \(apparu à 2026-10-01T12:00Z, 1 min ; fermée sans mesure')" "1"
egal "(m5) plus aucune alerte ouverte" "$(ouvertes)" ""
egal "(m5) memoire.json réécrit, avec le mode" "$(mode_memoire)" "propose"

cas m6_debut_absent_de_la_memoire   # un DEBUT écrit, puis arrêt brutal avant sauver_memoire
scenario '{"prom": {"consommateurs": 2}}'
garde_minute 12:00
casser_memoire alertes '{}'                       # la mémoire lisible ne connaît pas CONSUMERS
casser_memoire commandes_essai '"pas-une-minute"'
for m in 01 02 03; do garde_minute "12:$m"; done
A="$(alertes)"
contient "(m6) INFO : seul CONSUMERS est oublié (MEASURE_FAILED:garde est dans la mémoire)" "$A" \
    "^2026-10-01T12:03Z  INFO   alertes ouvertes oubliées \(mémoire remise à neuf, relues dans alertes.txt\) : CONSUMERS$"
contient "(m6) FIN de CONSUMERS" "$A" "^2026-10-01T12:03Z  FIN    MALADE   CONSUMERS  \(apparu à 2026-10-01T12:00Z, 3 min ; fermée sans mesure"
contient "(m6) FIN de MEASURE_FAILED:garde" "$A" "^2026-10-01T12:03Z  FIN    MALADE   MEASURE_FAILED:garde  \(apparu à 2026-10-01T12:01Z, 2 min ; fermée sans mesure"
egal "(m6) plus aucune alerte ouverte" "$(ouvertes)" ""

# ==============================================================================
titre "(p) le pilote lancé sous timeout et bash -x ; ni un tail, ni un bash -c"
cas p
tail -f "$DEPOT/campagne.sh" > /dev/null 2>&1 & T1=$!
bash -c "sleep 300; echo $DEPOT/campagne.sh" > /dev/null 2>&1 & T2=$!
sleep 0.3
proc_voir "$T1" "$T2"
garde_minute 12:00
egal "(p) ni tail ni bash -c ne sont un pilote" "$(val 12:00 pilote)" ""
timeout 300 bash -x "$DEPOT/campagne.sh" essai-t --profil 25:30 2>/dev/null & PILOTE=$!
for _ in $(seq 20); do pgrep -P "$PILOTE" > /dev/null && break; sleep 0.1; done
proc_voir "$PILOTE"
touch "$DEPOT/journaux/campagne-20261001-140000.log"
garde_minute 12:01
egal "(p) « timeout 300 bash -x campagne.sh essai-t » : la racine, avec son nom" "$(val 12:01 pilote)" "essai-t($PILOTE)"
"$PYTHON" -c 'import json,sys; p=json.load(open(sys.argv[1]))["local"]["pilote"]; print(p["pid_signal"])' "$DOSSIER/dernier.json" > "$D/pid_signal"
egal "(p) TERM irait au bash qui lit campagne.sh, pas à timeout" "$(cat "$D/pid_signal")" "$(pgrep -P "$PILOTE" -x bash | head -1)"
pilote_off; kill $(descendants "$T1" "$T2") 2>/dev/null

# ==============================================================================
titre "(l) la sonde seule"
cas l1_tout_echoue
scenario '{"tout_erreur": true}'
find "$D/master/autodeploy" -printf '%p %s %T@\n' | sort > "$D/avant"
HOME="$D/master/home" "$PYTHON" "$MASTER/apps/garde_sonde.py" --commandes > "$D/sonde.json" 2> "$D/sonde.err"
"$PYTHON" - "$D/sonde.json" <<'EOF' && ok "(l) tout échoue : un JSON valide, une erreur par mesure kubectl" || echec "(l) tout échoue : JSON"
import json, sys
d = json.load(open(sys.argv[1]))
assert all("erreur" in v for v in d["prom"].values()), d["prom"]
for k in ("locust", "noeuds", "pods", "chaos", "podnetworkchaos", "passerelle", "leader"):
    assert "erreur" in d[k], k
assert d["verifier"]["code"] == 0 and d["commandes"]["tables"]["orders"] == 1200
EOF
egal "(l) seule écriture : ~/garde.battement" "$(cd "$D/master/home" && find . -type f)" "./garde.battement"
find "$D/master/autodeploy" -printf '%p %s %T@\n' | sort > "$D/apres"
cmp -s "$D/avant" "$D/apres" && ok "(l) le dépôt du master n'a pas bougé" || echec "(l) le dépôt du master a changé"
cas l3_debogage
HOME="$D/master/home" "$PYTHON" "$MASTER/apps/garde_sonde.py" | "$PYTHON" -m json.tool > "$D/joli.json" \
    && ok "(l) « garde_sonde.py | python3 -m json.tool » marche" || echec "(l) json.tool"
"$PYTHON" -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["chaos"]["base"]["latence"]=="140ms" and d["chaos"]["objets"]==[]; assert d["locust"]["voyageurs"]==25 and d["prom"]["depot"]["valeur"]==3.3; assert "commandes" not in d' "$D/joli.json" \
    && ok "(l) l'objet de base n'est pas une panne ; sans --commandes, pas de lecture des commandes" || echec "(l) contenu de la sonde"
# Une erreur imprévue en lisant les fichiers du master : chaque partie que garde.py
# lit porte le message (au lieu de « absent de la sonde »).
HOME="$D/master/home" "$PYTHON" - "$MASTER/apps/garde_sonde.py" > "$D/fichiers.json" 2>/dev/null <<'EOF'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("sonde", sys.argv[1])
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
def casse(racine):
    raise RuntimeError("registre imprévu")
m.fichiers = casse
sys.argv = [sys.argv[1]]
m.main()
EOF
"$PYTHON" -c 'import json,sys; d=json.load(open(sys.argv[1])); assert all("registre imprévu" in d[k]["erreur"] for k in ("panne_etat", "palier", "pannes", "purges")), d' "$D/fichiers.json" \
    && ok "(l) fichiers illisibles : l'erreur est dans panne_etat, palier, pannes, purges" || echec "(l) fichiers : $(head -c 300 "$D/fichiers.json")"

"$PYTHON" - "$GARDE" "$SONDE" <<'EOF' && ok "(e) la sonde rend (échéance + 1,5 s) au moins 10 s avant le plafond ssh" || echec "(e) plafonds"
import importlib.util, sys
def charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
g, s = charger("garde_lu", sys.argv[1]), charger("sonde_lue", sys.argv[2])
marge = g.PLAFOND_SSH - (s.ECHEANCE_S + 1.5)
print(f"        plafond ssh {g.PLAFOND_SSH:.0f} s, sonde ≤ {s.ECHEANCE_S + 1.5} s : {marge:.1f} s pour ssh et python")
assert marge >= 10
EOF

# ==============================================================================
titre "les cas longs, partis en arrière-plan"
wait "$E1"
egal "(e) ssh qui pend : ligne écrite" "$("$PYTHON" "$ICI/lire.py" "$E1D/garde/garde.tsv" 12:00 causes)" "MEASURE_FAILED:ssh"
d=$(cat "$E1D/duree"); [ "$d" -le 55 ] && ok "(e) ssh qui pend : rendu en $d s (≤ 55)" || echec "(e) ssh qui pend : $d s"
wait "$E2"
read -r code d < "$E2D/fin"
egal "(e) boucle : code de sortie" "$code" "0"
"$PYTHON" - "$E2D/garde/garde.tsv" <<'EOF' && ok "(e) boucle : 1re minute MEASURE_FAILED:ssh, la boucle continue, 2e minute mesurée" || echec "(e) boucle : $(cat "$E2D/garde/garde.tsv")"
import sys
l = [x.rstrip("\n").split("\t") for x in open(sys.argv[1])][1:]
assert len(l) == 2, l
assert l[0][2] == "MEASURE_FAILED:ssh", l[0]
assert "MEASURE_FAILED" not in l[1][2] and l[1][9] != "", l[1]
EOF
echo "        (boucle : $d s pour 2 minutes)"
wait "$L2"
d=$(cat "$L2D/duree"); [ "$d" -le 45 ] && ok "(l) chaque kubectl pend : sonde rendue en $d s (≤ 45)" || echec "(l) sonde : $d s"
"$PYTHON" -c 'import json,sys; d=json.load(open(sys.argv[1])); assert all("erreur" in v for v in d["prom"].values()); assert "erreur" in d["locust"]' \
    "$L2D/sonde.json" && ok "(l) sonde qui pend : JSON valide, chaque mesure en erreur" || echec "(l) sonde qui pend : $(head -c 300 "$L2D/sonde.json")"

# ==============================================================================
titre "(i) le faux ssh n'a reçu que la sonde, et les gestes à part ; (k) le secret S3"
egal "(i) commandes ssh refusées (INTERDIT)" "$(grep -c '^INTERDIT' "$FAUX_LOG_SSH")" "0"
egal "(i) commandes ssh autres que la sonde" \
    "$(cut -f4 "$FAUX_LOG_SSH" | grep -cvE '^python3 [^ ]+/apps/garde_sonde\.py( --commandes)?$')" "0"
egal "(i) options ssh" "$(cut -f3 "$FAUX_LOG_SSH" | sort -u)" \
    "-o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=4"
egal "(q) gestes : seulement « bash <dépôt du master>/apps/panne.sh retirer »" \
    "$(cut -f4 "$FAUX_LOG_GESTES" | grep -cvE '^bash [^ ]+/apps/panne\.sh retirer$')" "0"
egal "(q) gestes : mêmes options ssh que la sonde, même hôte" "$(cut -f2,3 "$FAUX_LOG_GESTES" | sort -u | tr '\t' ' ')" \
    "master -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=15 -o ServerAliveCountMax=4"
egal "(q) gestes : seulement dans les cas avec --agir qui en demandaient" "$(cut -f5 "$FAUX_LOG_GESTES" | LC_ALL=C sort | uniq -c | awk '{print $2 "=" $1}' | tr '\n' ' ')" \
    "q11_popen=1 q12_fenetre=1 q14_gestes_inconnus=1 q16_incident_mode=2 q2_retrait=2 q3_orphelin=1 q5_non_declare=1 "
egal "(i) kubectl : seulement des lectures (get)" "$(cut -d' ' -f1 "$BAC/kubectl.log" | sort -u)" "get"
egal "(i) hôte" "$(cut -f2 "$FAUX_LOG_SSH" | sort -u)" "master"
fuites=$(grep -rlF -e "$SECRET" -e "$ACCES" "$BAC" | grep -v '/graphe_en/config.yaml$')
egal "(k) fichiers où le secret ou la clé d'accès apparaît (hors config.yaml)" "${fuites:-aucun}" "aucun"

"$PYTHON" - "$GARDE" <<'EOF' && ok "en-tête de garde.py : chaque code et chaque colonne y sont décrits" || echec "en-tête de garde.py incomplet"
import importlib.util, re, sys
spec = importlib.util.spec_from_file_location("garde_lu", sys.argv[1])
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)          # rien ne s'exécute hors des constantes : main() n'est pas appelé
entete = open(sys.argv[1], encoding="utf-8").read().split("\nimport ")[0]
manque = [c for c in g.CODES if not re.search(rf"\b{c}\b", entete)]
manque += [c for c in g.COLONNES if not re.search(rf"#\s+{c}\s", entete)]
assert not manque, manque
print(f"        {len(g.CODES)} codes, {len(g.COLONNES)} colonnes")
EOF

kill "$ZPID" 2>/dev/null; wait "$ZPID" 2>/dev/null
egal "(z) essai-z arrêté par son pid" "$(kill -0 "$ZPID" 2>/dev/null && echo vivant || echo arrete)" "arrete"

# ==============================================================================
echo
echo "================ bilan ================"
echo "  $REUSSIS vérifications réussies, $RATES en échec"
[ "$RATES" -eq 0 ] && { echo "  => tous les cas passent"; exit 0; }
echo "  => AU MOINS UN CAS EN ÉCHEC"; exit 1
