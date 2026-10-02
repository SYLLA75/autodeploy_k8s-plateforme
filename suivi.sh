#!/bin/bash
# ==============================================================================
#  suivi.sh — l'état de la collecte en un écran, sans rien toucher
# ==============================================================================
#
#  CE QUE FAIT CE SCRIPT
#
#  Il affiche, en un écran (au plus 40 lignes, 110 colonnes), où en est la
#  collecte, à partir des SEULS fichiers de vms0 :
#    1. l'heure UTC ; l'âge de la dernière ligne de garde.tsv (au-delà de 3 min :
#       « GARDIEN MUET depuis N min », en gros) ; le mode du gardien, AGIR ou PROPOSE ;
#    2. la campagne en cours : pilote vivant ou non, nom, depuis quand, dernière
#       ligne de son journal et son âge ;
#    3. la panne déclarée (cause, depuis, durée) ou « aucune » ;
#    4. la dernière minute : état, causes, notes ; puis les valeurs clés
#       (voyageurs, req/s, échecs, dépôt, retrait, tas, consommateurs, CPU et
#       nombre des commandes, 140 ms, leader, nœuds prêts, âge S3, place sur vms0) ;
#    5. les 30 dernières minutes en une ligne : O=OK, M=MALADE, D=DOUTEUX, ·=trou
#       (minute absente de garde.tsv) ;
#    6. les alertes OUVERTES (une ligne DEBUT sans FIN dans alertes.txt), puis
#       les 5 dernières lignes d'alertes.txt ;
#    7. le drapeau de pause (présent ? pourquoi ?) et les 3 dernières actions ;
#    8. les 5 dernières lignes FIN de journaux/fins.tsv ; depuis minuit UTC, le
#       nombre de campagnes finies et de minutes MALADE.
#  Avec --journal, il suit le journal du pilote en cours (comme tail -F) et
#  passe tout seul au journal suivant quand une nouvelle campagne démarre.
#
#  POURQUOI
#
#  Pendant les 7 jours de collecte, on veut pouvoir regarder à tout moment, sans
#  risque de rien casser : ce script n'écrit rien, ne lance ni ssh ni kubectl, ne
#  charge pas le cluster. Il lit garde.tsv, dernier.json, alertes.txt,
#  actions.tsv, pause (dossier du gardien), journaux/fins.tsv et
#  journaux/campagne-*.log (le dépôt : le dossier de ce script), et /proc pour
#  savoir si le pilote vit. Un fichier absent, vide ou coupé en cours
#  d'écriture donne « (pas encore de données) », jamais une erreur. Il ne
#  décide rien sur un nom de panne ou de cause : il recopie ce que le gardien a
#  écrit. Le travail est fait par suivi.py, à côté.
#
#  C'est le volet du haut de la session tmux « collecte » (collecte-tmux.sh),
#  qu'on regarde en lecture seule :  tmux attach -r -t =collecte  (Ctrl-b puis d
#  pour partir).
#
#  Usage (sur vms0, dans le dépôt) :
#      ./suivi.sh                    un écran, puis s'arrête (= --une-fois)
#      ./suivi.sh --boucle 30        efface et redessine toutes les 30 s (Ctrl-C pour sortir) ;
#                                    dans une fenêtre trop basse sautent, dans l'ordre : les
#                                    5 dernières lignes d'alertes.txt (le volet du milieu les
#                                    montre), la liste des fins (le bilan du jour reste), puis
#                                    deux des trois actions
#      ./suivi.sh --journal          suit le journal du pilote en cours (Ctrl-C pour sortir)
#      options : --dossier <d>       le dossier du gardien
#
#  Variables reconnues :
#      GARDE_DOSSIER     (défaut: ~/journaux-hors-campagne/garde) le dossier du gardien
#      GARDE_PROC        (défaut: /proc) où chercher le pilote (essais)
#      SUIVI_MAINTENANT  (essais seulement) l'heure du suivi, AAAA-MM-JJTHH:MM:SSZ
#      SUIVI_ATTENTE     (défaut: 2) secondes entre deux lectures du journal (--journal)
#      NO_COLOR          pas de couleur
# ==============================================================================
set -uo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

say()  { echo "  [suivi] $*"; }
ok()   { echo "  [suivi] OK  $*"; }
warn() { echo "  [suivi] ATTENTION: $*" >&2; }
fail() { echo "  [suivi] ERREUR: $*" >&2; exit 1; }

case "${1:-}" in
    -h|--help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0 ;;
esac

command -v python3 >/dev/null 2>&1 || fail "python3 introuvable"
[ -f "$ICI/suivi.py" ] || fail "suivi.py manque à côté de suivi.sh ($ICI)"

# Rien n'est écrit à côté des fichiers lus (garde.py est chargé, pas compilé sur disque).
export PYTHONDONTWRITEBYTECODE=1
exec python3 "$ICI/suivi.py" "$@"
