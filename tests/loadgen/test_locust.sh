#!/bin/bash
# ==============================================================================
# tests/loadgen/test_locust.sh — le délai d'abandon des voyageurs, essayé
# avec le VRAI Locust contre un faux train-ticket sur 127.0.0.1.
#
#   (a) nominal : le nouveau et l'original envoient les mêmes requêtes, dans
#       les mêmes proportions (par requête, et par parcours : khi-deux), sans échec ;
#   (b) un chemin figé (repas, puis repas + connexion) : échec compté sous le
#       bon nom, aucun voyageur bloqué plus que le délai, les parcours suivent ;
#   (c) l'original dans le même cas reste bloqué, sans aucun échec affiché ;
#   (d) connexion refusée, serveur muet, file d'attente pleine : le délai
#       tient, l'erreur est comptée ;
#   (e) sans variable d'environnement, requests reçoit bien (10, 60) ; un
#       délai explicite garde la priorité ;
#   (f) en-têtes reçus puis corps figé (repas, puis connexion de on_start) :
#       l'incident est compté en exception, aucun voyageur ne meurt ;
#   (g) connexion figée et 403 sans jeton : au plus 4 requêtes
#       d'authentification par parcours, les parcours s'enchaînent.
#
#   Délais réduits pour aller vite : 1 s de connexion, 2 s de réponse.
#   Aucun accès réseau hors de 127.0.0.1. Borné à 9 minutes au total.
#
#   Usage : bash tests/loadgen/test_locust.sh
#   Variables : VENV_LOCUST (environnement où est installé locust 2.32.4),
#               ORIGINAL (locustfile de référence), GARDER=1 (garde les traces)
#   Code de retour : 0 seulement si tous les cas passent.
# ==============================================================================
set -uo pipefail

# Le test entier est borné : un cas qui pend est un ÉCHEC, pas une attente.
if [ -z "${_TEST_BORNE:-}" ]; then
    exec env _TEST_BORNE=1 timeout -k 10 540 bash "$0" "$@"
fi

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHANTIER="$(cd "$ICI/../.." && pwd)"
NOUVEAU="$CHANTIER/apps/loadgen/locustfile.py"
ORIGINAL="${ORIGINAL:-$HOME/autodeploy_k8s-phases/apps/loadgen/locustfile.py}"
VENV="${VENV_LOCUST:-/tmp/claude-1000/-home-chsylla-zero/1ee970ae-08c1-4fb2-8769-2d32a5acc308/scratchpad/venv-locust}"
LOCUST="$VENV/bin/locust"
PY="$VENV/bin/python"

# Rien n'est écrit à côté des fichiers lus (pas de __pycache__ dans le dépôt).
export PYTHONDONTWRITEBYTECODE=1

W="$(mktemp -d)"
PIDS=()
nettoyer() {
    for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null; done
    if [ -n "${GARDER:-}" ]; then echo "traces gardées dans $W"; else rm -rf "$W"; fi
}
trap nettoyer EXIT

RESULTATS=()
resultat() {   # resultat <cas> <code>
    if [ "$2" -eq 0 ]; then RESULTATS+=("OK      $1"); echo "  => OK"
    else RESULTATS+=("ÉCHEC   $1"); echo "  => ÉCHEC"; fi
}

# ------------------------------------------------------------------------------
# lancer_serveur <dossier> [--muet|--plein] — pose PORT ; FAUX_SUSPENDRE hérité
lancer_serveur() {
    local d="$1"; shift
    mkdir -p "$d"
    python3 "$ICI/faux_serveur.py" "$d/port" "$d/journal" "$@" 2>"$d/serveur.err" &
    PIDS+=($!)
    for _ in $(seq 50); do [ -f "$d/port" ] && break; sleep 0.1; done
    PORT="$(cat "$d/port" 2>/dev/null)"
    [ -n "$PORT" ] || { echo "  faux serveur muet au démarrage :"; cat "$d/serveur.err"; return 1; }
}

# lancer_locust <dossier> <fichier> <port> <voyageurs> <durée_s> [VAR=val…]
lancer_locust() {
    local d="$1" fichier="$2" port="$3" n="$4" duree="$5"; shift 5
    local rc=0
    ( cd "$d" && env "$@" timeout -k 5 $((duree + 30)) "$LOCUST" -f "$fichier" \
        --headless -u "$n" -r "$n" -t "${duree}s" --host "http://127.0.0.1:$port" \
        --csv "$d/r" --only-summary --loglevel WARNING --exit-code-on-error 0 \
        --stop-timeout 0 >"$d/locust.log" 2>&1 ) || rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "  Locust s'est terminé avec le code $rc (124 : bloqué au-delà de la borne)"
        tail -20 "$d/locust.log" | sed 's/^/    | /'
    fi
    return "$rc"
}

# copie <dossier> <locustfile> — le fichier est copié : Locust n'écrit rien à côté de l'original
copie() { mkdir -p "$1"; cp "$2" "$1/locustfile.py"; }

DELAIS=(TT_DELAI_CONNEXION=1 TT_DELAI_REPONSE=2)

# ------------------------------------------------------------------------------
echo "Locust : $("$LOCUST" --version 2>&1 | head -1)"
"$LOCUST" --version 2>&1 | grep -q "locust 2.32.4" \
    || { echo "ÉCHEC : locust 2.32.4 introuvable dans $VENV"; exit 1; }
[ -f "$ORIGINAL" ] || { echo "ÉCHEC : original introuvable : $ORIGINAL"; exit 1; }
# compile() plutôt que py_compile : rien n'est écrit à côté du fichier.
python3 -c 'import sys; compile(open(sys.argv[1], encoding="utf-8").read(), sys.argv[1], "exec")' \
    "$NOUVEAU" 2>&1 && echo "compilation : ok" \
    || { echo "ÉCHEC : $NOUVEAU ne compile pas"; exit 1; }

# ------------------------------------------------------------------------------
echo
# 24 s et non plus 8 : environ 3 000 parcours par course au lieu de 1 100.
# L'écart de part de « 40 commander un repas » entre deux courses avait un écart
# type d'environ 2,4 points sur 8 s (8 essais), plus sur une machine chargée :
# le seuil de 6 points sautait par hasard (2 fois sur 9, 6,3 points vu). Sur 24 s,
# cet écart type tombe vers 1,4 point. Le tirage est en plus jugé PAR PARCOURS
# (khi-deux, seuil 0,001 : voir verifier.py), un test calibré par les comptes.
echo "(a) nominal : 10 voyageurs, rythme 0,02 s, 24 s, nouveau puis original"
rc=0
for v in nouveau original; do
    f="$NOUVEAU"; [ "$v" = original ] && f="$ORIGINAL"
    copie "$W/a_$v" "$f"
    lancer_serveur "$W/a_$v" || rc=1
    lancer_locust "$W/a_$v" "$W/a_$v/locustfile.py" "$PORT" 10 24 \
        TT_PACING_SECONDS=0.02 "${DELAIS[@]}" || rc=1
done
"$PY" "$ICI/verifier.py" nominal "$W/a_nouveau" "$W/a_original" || rc=1
resultat "(a) nominal : mêmes requêtes, mêmes proportions, aucun échec" "$rc"

# ------------------------------------------------------------------------------
echo
# 30 s et non plus 12 : le contrôle « les autres parcours avancent encore à la
# fin » regarde le dernier tiers de la course. Sur 12 s, ce tiers (4 s) ne
# contient qu'environ 2 parcours par voyageur ; s'ils tirent tous « commander un
# repas » (poids 6 sur 10, le chemin figé exprès), rien n'est servi et le cas
# échouait par hasard : 0,6^(3 voyageurs × 2) ≈ 1 fois sur 21, ce qu'on voyait.
# Sur 30 s, le tiers dure 10 s, environ 5 parcours par voyageur : 0,6^15 ≈ 1 fois
# sur 2 000. Les contrôles restent les mêmes, sur la même part de la course.
echo "(b1) nouveau, la commande de repas ne répond jamais : 3 voyageurs, 30 s"
rc=0
copie "$W/b1" "$NOUVEAU"
FAUX_SUSPENDRE="/api/v1/foodservice/orders@0" lancer_serveur "$W/b1" || rc=1
lancer_locust "$W/b1" "$W/b1/locustfile.py" "$PORT" 3 30 \
    TT_PACING_SECONDS=0.5 "${DELAIS[@]}" || rc=1
"$PY" "$ICI/verifier.py" nouveau "$W/b1" 2 30 /api/v1/foodservice/orders || rc=1
resultat "(b1) repas figé : échec compté, voyageurs jamais bloqués" "$rc"

echo
echo "(b2) nouveau, repas figé, puis connexion figée dès 4 s (jeton renouvelé chaque seconde) : 14 s"
rc=0
copie "$W/b2" "$NOUVEAU"
FAUX_SUSPENDRE="/api/v1/foodservice/orders@0,/api/v1/users/login@4" lancer_serveur "$W/b2" || rc=1
lancer_locust "$W/b2" "$W/b2/locustfile.py" "$PORT" 3 14 \
    TT_PACING_SECONDS=0.5 TT_SESSION_TTL_SECONDS=1 "${DELAIS[@]}" || rc=1
"$PY" "$ICI/verifier.py" nouveau "$W/b2" 2 14 \
    /api/v1/foodservice/orders,/api/v1/users/login || rc=1
resultat "(b2) repas et connexion figés : reconnexions bornées, parcours continus" "$rc"

# ------------------------------------------------------------------------------
echo
echo "(c) ORIGINAL, la commande de repas ne répond jamais : 3 voyageurs, 10 s"
rc=0
copie "$W/c" "$ORIGINAL"
FAUX_SUSPENDRE="/api/v1/foodservice/orders@0" lancer_serveur "$W/c" || rc=1
lancer_locust "$W/c" "$W/c/locustfile.py" "$PORT" 3 10 TT_PACING_SECONDS=0.5 || rc=1
"$PY" "$ICI/verifier.py" original "$W/c" 10 || rc=1
resultat "(c) original : voyageurs figés, aucun échec visible (défaut montré)" "$rc"

# ------------------------------------------------------------------------------
echo
echo "(d1) nouveau, connexion refusée (port fermé) : 2 voyageurs, 6 s"
rc=0
copie "$W/d1" "$NOUVEAU"
PORT_FERME="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')"
lancer_locust "$W/d1" "$W/d1/locustfile.py" "$PORT_FERME" 2 6 \
    TT_PACING_SECONDS=0.5 "${DELAIS[@]}" || rc=1
"$PY" "$ICI/verifier.py" silence "$W/d1" 2 6 "Connection refused" || rc=1
resultat "(d1) connexion refusée : échec immédiat et compté" "$rc"

echo
echo "(d2) nouveau, serveur qui accepte et ne répond jamais aux en-têtes : 2 voyageurs, 12 s"
rc=0
copie "$W/d2" "$NOUVEAU"
lancer_serveur "$W/d2" --muet || rc=1
lancer_locust "$W/d2" "$W/d2/locustfile.py" "$PORT" 2 12 \
    TT_PACING_SECONDS=0.5 "${DELAIS[@]}" || rc=1
"$PY" "$ICI/verifier.py" silence "$W/d2" 2 12 "ReadTimeout" || rc=1
resultat "(d2) serveur muet : délai de réponse (2 s) respecté" "$rc"

echo
echo "(d3) nouveau, file d'attente du serveur pleine (connexion jamais établie) : 2 voyageurs, 10 s"
rc=0
copie "$W/d3" "$NOUVEAU"
lancer_serveur "$W/d3" --plein || rc=1
lancer_locust "$W/d3" "$W/d3/locustfile.py" "$PORT" 2 10 \
    TT_PACING_SECONDS=0.5 "${DELAIS[@]}" || rc=1
"$PY" "$ICI/verifier.py" silence "$W/d3" 2 10 "ConnectTimeout" || rc=1
resultat "(d3) connexion jamais établie : délai de connexion (1 s) respecté" "$rc"

# ------------------------------------------------------------------------------
echo
echo "(e) nouveau, SANS TT_DELAI_* : délai réellement transmis à requests (2 voyageurs, 5 s)"
rc=0
copie "$W/e" "$NOUVEAU"
cp "$ICI/enveloppe_envoi.py" "$W/e/"
lancer_serveur "$W/e" || rc=1
lancer_locust "$W/e" "$W/e/enveloppe_envoi.py" "$PORT" 2 5 \
    -u TT_DELAI_CONNEXION -u TT_DELAI_REPONSE \
    TT_PACING_SECONDS=0.5 JOURNAL_ENVOIS="$W/e/envois" || rc=1
"$PY" "$ICI/verifier.py" delais "$W/e/envois" 10 60 || rc=1
( cd "$W/e" && timeout 30 "$PY" "$ICI/verifier.py" priorite "$W/e" "$PORT" ) || rc=1
resultat "(e) défaut (10, 60) transmis ; variable seule et délai explicite respectés" "$rc"

# ------------------------------------------------------------------------------
echo
echo "(f1) nouveau, repas : en-têtes reçus, puis corps figé : 3 voyageurs, 12 s"
rc=0
copie "$W/f1" "$NOUVEAU"
FAUX_CORPS_FIGE="/api/v1/foodservice/orders@0" lancer_serveur "$W/f1" || rc=1
lancer_locust "$W/f1" "$W/f1/locustfile.py" "$PORT" 3 12 \
    TT_PACING_SECONDS=0.5 "${DELAIS[@]}" || rc=1
"$PY" "$ICI/verifier.py" corps "$W/f1" 2 12 /api/v1/foodservice/orders || rc=1
resultat "(f1) corps de repas figé : compté en exception, voyageurs vivants" "$rc"

echo
echo "(f2) nouveau, connexion : en-têtes reçus, puis corps figé dès on_start : 3 voyageurs, 12 s"
rc=0
copie "$W/f2" "$NOUVEAU"
FAUX_CORPS_FIGE="/api/v1/users/login@0" lancer_serveur "$W/f2" || rc=1
lancer_locust "$W/f2" "$W/f2/locustfile.py" "$PORT" 3 12 \
    TT_PACING_SECONDS=0.5 "${DELAIS[@]}" || rc=1
"$PY" "$ICI/verifier.py" corps "$W/f2" 2 12 /api/v1/users/login || rc=1
resultat "(f2) corps de connexion figé dans on_start : voyageurs vivants" "$rc"

# ------------------------------------------------------------------------------
echo
echo "(g) nouveau, connexion figée et 403 sans jeton : 3 voyageurs, 16 s"
rc=0
copie "$W/g" "$NOUVEAU"
cp "$ICI/enveloppe_envoi.py" "$W/g/"
FAUX_SUSPENDRE="/api/v1/users/login@0" FAUX_403=1 lancer_serveur "$W/g" || rc=1
lancer_locust "$W/g" "$W/g/enveloppe_envoi.py" "$PORT" 3 16 \
    TT_PACING_SECONDS=0.5 JOURNAL_ENVOIS="$W/g/envois" "${DELAIS[@]}" || rc=1
"$PY" "$ICI/verifier.py" refus "$W/g" 2 16 || rc=1
resultat "(g) connexion figée + 403 : reconnexions bornées par parcours" "$rc"

# ------------------------------------------------------------------------------
echo
echo "================ bilan ================"
printf '  %s\n' "${RESULTATS[@]}"
for r in "${RESULTATS[@]}"; do
    case "$r" in ÉCHEC*) echo "  => AU MOINS UN CAS EN ÉCHEC"; exit 1 ;; esac
done
echo "  => tous les cas passent"
exit 0
