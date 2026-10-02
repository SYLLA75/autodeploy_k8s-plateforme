#!/bin/bash
# ==============================================================================
#  test_demarrer.sh — essai à blanc de « collecte.sh demarrer »
# ==============================================================================
#
#  Aucun cluster n'est touché : un FAUX kubectl est placé en tête du PATH, et
#  le test refuse de tourner si « command -v kubectl » ne le désigne pas. Un
#  faux sleep, lui aussi dans le PATH, rend l'attente de 2 minutes instantanée
#  sans changer la valeur du script.
#
#  Le script est copié dans un dossier de travail SANS journal.sh : rien n'est
#  écrit ailleurs que dans ce dossier, effacé à la fin.
#
#  Usage :  bash tests/collecte/test_demarrer.sh
#  Rend 0 seulement si tous les cas passent.
# ==============================================================================
set -uo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPS="$(cd "$ICI/../../apps" && pwd)"
NOUVEAU="$APPS/collecte.sh"
ORIGINE="$APPS/collecte.sh.origine"

TRAVAIL="$(mktemp -d "${TMPDIR:-/tmp}/test_collecte.XXXXXX")"
trap 'rm -rf "$TRAVAIL"' EXIT

# Deux dossiers, un par version, chacun avec un fichier du même nom : ainsi
# « $0 » est identique dans les deux sorties quand on les compare.
mkdir -p "$TRAVAIL/bin" "$TRAVAIL/nouveau" "$TRAVAIL/origine"
cp "$NOUVEAU" "$TRAVAIL/nouveau/collecte.sh"
cp "$ORIGINE" "$TRAVAIL/origine/collecte.sh"
export JOURNAL_OFF=1

# ------------------------------------------------------------ faux kubectl
# L'état de chaque déploiement vit dans $FAUX_ETAT :
#   <dep>.rep    nombre d'exemplaires (fichier absent = déploiement introuvable)
#   <dep>.note   nombre mémorisé par « arreter »
#   <dep>.n      nombre de fois qu'on a demandé readyReplicas
# Variables :
#   FAUX_PRET_AU   la passerelle est prête au N-ième relevé (0 = jamais)
#   FAUX_SCALE_KO  nom du déploiement dont « scale » échoue
cat > "$TRAVAIL/bin/kubectl" <<'FAUX'
#!/bin/bash
E="$FAUX_ETAT"
echo "kubectl $*" >> "$E/appels"
[ "${1:-}" = "version" ] && exit 0

verbe="$1"; shift
type="$1"; shift
dep=""; ns=""; jp=""; rep=""
case "$type" in deploy) dep="$1"; shift ;; esac
while [ $# -gt 0 ]; do
    case "$1" in
        -n) ns="$2"; shift 2 ;;
        -o) jp="$2"; shift 2 ;;
        --replicas=*) rep="${1#--replicas=}"; shift ;;
        autodeploy/collecte-repliques=*) note="${1#*=}"; shift ;;
        *) shift ;;
    esac
done

case "$verbe:$type" in
    get:pods)
        printf 'ts-a-1 1/1 Running 0 1d\nts-b-1 0/1 Running 0 1d\n' ;;
    get:daemonset)
        printf 'otel-opentelemetry-collector-agent 3 3 3 3 3 <none> 1d\n'
        printf 'node-exporter 3 3 3 3 3 <none> 1d\n' ;;
    get:deploy)
        [ -f "$E/$dep.rep" ] || { echo "Error: not found" >&2; exit 1; }
        case "$jp" in
            "") echo "$dep 0/0 0 0 1d" ;;
            *spec.replicas*) cat "$E/$dep.rep" ;;
            *annotations*) [ -f "$E/$dep.note" ] && cat "$E/$dep.note" ;;
            *readyReplicas*)
                n=$(( $(cat "$E/$dep.n" 2>/dev/null || echo 0) + 1 ))
                echo "$n" > "$E/$dep.n"
                r=$(cat "$E/$dep.rep")
                if [ "$r" != "0" ] && [ "${FAUX_PRET_AU:-1}" != "0" ] \
                   && [ "$n" -ge "${FAUX_PRET_AU:-1}" ]; then
                    echo "$r"
                fi ;;
        esac ;;
    scale:deploy)
        [ -f "$E/$dep.rep" ] || exit 1
        [ "$dep" = "${FAUX_SCALE_KO:-}" ] && { echo "Error: refusé" >&2; exit 1; }
        echo "$rep" > "$E/$dep.rep" ;;
    annotate:deploy)
        [ -f "$E/$dep.rep" ] || exit 1
        echo "$note" > "$E/$dep.note" ;;
esac
exit 0
FAUX

# Faux sleep : ne dort pas, compte seulement les appels.
cat > "$TRAVAIL/bin/sleep" <<'FAUX'
#!/bin/bash
echo "$*" >> "$FAUX_ETAT/sommes"
exit 0
FAUX
chmod +x "$TRAVAIL/bin/kubectl" "$TRAVAIL/bin/sleep"
export PATH="$TRAVAIL/bin:$PATH"

# Garde-fou : si un autre kubectl passait devant, on s'arrête tout de suite.
if [ "$(command -v kubectl)" != "$TRAVAIL/bin/kubectl" ]; then
    echo "ÉCHEC : kubectl appelé = $(command -v kubectl), pas le faux. Arrêt." >&2
    exit 1
fi
if [ "$(command -v sleep)" != "$TRAVAIL/bin/sleep" ]; then
    echo "ÉCHEC : sleep appelé = $(command -v sleep), pas le faux. Arrêt." >&2
    exit 1
fi
echo "  kubectl utilisé : $(command -v kubectl)  (faux)"
echo

GW="otel-gateway-opentelemetry-collector"
LG="locust"
ECHECS=0
ok()    { echo "  OK     $*"; }
echec() { echo "  ÉCHEC  $*"; ECHECS=$((ECHECS + 1)); }

# Prépare un état neuf : passerelle à <g> exemplaires (ou « absente »),
# générateur à <l> exemplaires (ou « absent »), note mémorisée pour la passerelle.
preparer() {
    local g="$1" l="$2" note="${3:-}"
    FAUX_ETAT="$TRAVAIL/etat"; export FAUX_ETAT
    rm -rf "$FAUX_ETAT"; mkdir -p "$FAUX_ETAT"
    [ "$g" = "absente" ] || echo "$g" > "$FAUX_ETAT/$GW.rep"
    [ "$l" = "absent" ]  || echo "$l" > "$FAUX_ETAT/$LG.rep"
    [ -n "$note" ] && echo "$note" > "$FAUX_ETAT/$GW.note"
    : > "$FAUX_ETAT/appels"; : > "$FAUX_ETAT/sommes"
}

# Lance la nouvelle version ; garde la sortie et le code de retour.
lancer() {
    SORTIE=$(cd "$TRAVAIL/nouveau" && bash ./collecte.sh "$@" 2>&1); RC=$?
}

# Vérifie : code attendu (0 ou « non0 ») et présence (1) / absence (0) de
# « Enregistrement repris ».
verifier() {
    local nom="$1" rc_att="$2" repris_att="$3" repris=0 bon=1
    grep -q "Enregistrement repris" <<<"$SORTIE" && repris=1
    case "$rc_att" in
        0)    [ "$RC" -eq 0 ] || bon=0 ;;
        non0) [ "$RC" -ne 0 ] || bon=0 ;;
    esac
    [ "$repris" = "$repris_att" ] || bon=0
    if [ "$bon" = "1" ]; then
        ok "$nom  (code $RC, « Enregistrement repris » : $([ $repris = 1 ] && echo présent || echo absent))"
    else
        echec "$nom  (code $RC, attendu $rc_att ; « Enregistrement repris » : $repris, attendu $repris_att)"
        sed 's/^/           | /' <<<"$SORTIE"
    fi
}

# (a) passerelle arrêtée, prête au 2e relevé, 3 exemplaires mémorisés
preparer 0 0 3
FAUX_PRET_AU=2 lancer demarrer
verifier "(a) prête au 2e essai" 0 1
grep -q -- "scale deploy $GW -n observability --replicas=3" "$FAUX_ETAT/appels" \
    && ok "(a) nombre mémorisé rétabli (3)" \
    || echec "(a) nombre mémorisé non rétabli"

# (b) passerelle jamais prête : 30 relevés, 30 « sleep 4 », puis erreur
preparer 0 0
FAUX_PRET_AU=0 lancer demarrer
verifier "(b) jamais prête" non0 0
grep -q "NON démarrée" <<<"$SORTIE" && ok "(b) message « collecte NON démarrée »" \
                                    || echec "(b) message d'erreur manquant"
n_sleep=$(grep -c '^4$' "$FAUX_ETAT/sommes")
[ "$n_sleep" = "30" ] && ok "(b) délai inchangé : 30 × sleep 4" \
                      || echec "(b) délai modifié : $n_sleep sleep 4 au lieu de 30"

# (b2) passerelle déjà en marche mais jamais prête : même erreur
preparer 2 0
FAUX_PRET_AU=0 lancer demarrer
verifier "(b2) déjà en marche, jamais prête" non0 0
grep -q "NON démarrée" <<<"$SORTIE" && ok "(b2) message « collecte NON démarrée »" \
                                    || echec "(b2) message d'erreur manquant"
grep -q "bash ./collecte.sh arreter" <<<"$SORTIE" && ok "(b2) le message dit comment l'éteindre" \
                                                  || echec "(b2) pas de marche à suivre dans le message"

# (c) passerelle introuvable
preparer absente 0
FAUX_PRET_AU=1 lancer demarrer
verifier "(c) passerelle introuvable" non0 0
grep -q "NON démarrée" <<<"$SORTIE" && ok "(c) message « collecte NON démarrée »" \
                                    || echec "(c) message d'erreur manquant"

# (c2) passerelle introuvable avec --avec-charge : erreur, et le générateur
#      n'est pas touché
preparer absente 0
FAUX_PRET_AU=1 lancer demarrer --avec-charge
verifier "(c2) passerelle introuvable, --avec-charge" non0 0
grep -q "scale deploy $LG" "$FAUX_ETAT/appels" \
    && echec "(c2) générateur relancé malgré l'erreur" \
    || ok "(c2) générateur non relancé"

# (d) scale de la passerelle qui échoue
preparer 0 0
FAUX_PRET_AU=1 FAUX_SCALE_KO="$GW" lancer demarrer
verifier "(d) scale qui échoue" non0 0
grep -q "NON démarrée" <<<"$SORTIE" && ok "(d) message « collecte NON démarrée »" \
                                    || echec "(d) message d'erreur manquant"
grep -q "readyReplicas" "$FAUX_ETAT/appels" \
    && echec "(d) attente lancée malgré l'échec du scale" \
    || ok "(d) pas d'attente inutile après l'échec"

# (e) passerelle déjà en marche
preparer 2 0
FAUX_PRET_AU=1 lancer demarrer
verifier "(e) déjà en marche" 0 1
grep -q "scale deploy" "$FAUX_ETAT/appels" \
    && echec "(e) scale appelé alors que la passerelle tournait" \
    || ok "(e) aucun scale"

# (g) générateur de charge absent avec --avec-charge : reste un avertissement
preparer 0 absent
FAUX_PRET_AU=1 lancer demarrer --avec-charge
verifier "(g) charge absente, --avec-charge" 0 1
grep -q "ATTENTION: générateur de charge ignoré" <<<"$SORTIE" \
    && ok "(g) avertissement « générateur de charge ignoré »" \
    || echec "(g) avertissement sur le générateur manquant"

# (h) scale du générateur qui échoue avec --avec-charge : reste un avertissement
preparer 0 0
FAUX_PRET_AU=1 FAUX_SCALE_KO="$LG" lancer demarrer --avec-charge
verifier "(h) scale de la charge qui échoue" 0 1
grep -q "ATTENTION: générateur de charge ignoré" <<<"$SORTIE" \
    && ok "(h) avertissement « générateur de charge ignoré »" \
    || echec "(h) avertissement sur le générateur manquant"

# (f) arreter et etat : même sortie, même code, mêmes appels que l'original
comparer() {
    local nom="$1" g="$2" l="$3"; shift 3
    local s_o s_n rc_o rc_n a_o a_n
    preparer "$g" "$l"
    s_o=$(cd "$TRAVAIL/origine" && bash ./collecte.sh "$@" 2>&1); rc_o=$?
    a_o=$(cat "$FAUX_ETAT/appels")
    preparer "$g" "$l"
    s_n=$(cd "$TRAVAIL/nouveau" && bash ./collecte.sh "$@" 2>&1); rc_n=$?
    a_n=$(cat "$FAUX_ETAT/appels")
    if [ "$s_o" = "$s_n" ] && [ "$rc_o" = "$rc_n" ] && [ "$a_o" = "$a_n" ]; then
        ok "(f) $nom identique à l'original (code $rc_n)"
    else
        echec "(f) $nom différent de l'original (codes $rc_o / $rc_n)"
        diff <(echo "$s_o"; echo "$a_o") <(echo "$s_n"; echo "$a_n") | sed 's/^/           | /'
    fi
}
export FAUX_PRET_AU=1
comparer "arreter (en marche)"             2 1 arreter
comparer "arreter --avec-charge"           2 1 arreter --avec-charge
comparer "arreter (déjà arrêtée)"          0 0 arreter
comparer "arreter (passerelle introuvable)" absente absent arreter --avec-charge
comparer "etat (en marche)"                2 1 etat
comparer "etat (arrêtée)"                  0 absent etat

echo
if [ "$ECHECS" -eq 0 ]; then
    echo "  Tous les cas passent."
    exit 0
fi
echo "  $ECHECS cas en échec."
exit 1
