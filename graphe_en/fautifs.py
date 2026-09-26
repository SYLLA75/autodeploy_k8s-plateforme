"""
Le fautif de chaque injection : la réponse juste, écrite avant tout calcul.

    ./.venv/bin/python fautifs.py [options] [campagne ...]

Phase B.1. Les témoins (tableau équitable, score par nœud, règle qui suit les
flèches) puis le GNN désignent un fautif ; on les juge contre ce fichier. Les
règles sont fixées le 26 sept. 2026, avant d'avoir calculé le moindre témoin et
avant toute donnée de la base lente (phase C) ou des jumeaux (phase D) : une
règle choisie après avoir vu les réponses pourrait l'être pour arranger.

LES RÈGLES, UNE PAR CAUSE (noms de cause de apps/panne.sh)

  blocage   la réplique gelée (nœud instance), nommée par le registre des
            pannes de la campagne ; pas les deux autres, qui vont bien
  hote      la machine où le voisin brûle le CPU (nœud host), nommée par le
            registre ; pas le voisin, qui n'est pas dans le graphe, ni les pods
            de la machine, qui en sont victimes. Vrai aussi quand la panne se
            propage en amont (hote-02, 3e injection) : le fautif reste la machine
  lenteur   les trois répliques du consommateur (nœuds instance), ensemble :
            ce sont elles qui mettent plus longtemps par message (le retard est
            posé sur ce qu'elles envoient à la base, pas sur la base)
  charge    AUCUN fautif (décidé avec l'utilisateur le 26 sept.) : rien n'est
            cassé, il y a plus de voyageurs. Jugée sur la cause seulement ;
            forcer un composant serait artificiel
  base      phase C, la base lente : le pod de la base (graphe_fige.json,
            « bases » : tsdb-mysql-0), le fautif muet. Pas les services qui
            l'appellent, qui en sont victimes
  reseau    phase D, les jumeaux : la machine dont le réseau est dégradé
            (nœud host), nommée par le registre. Jamais la machine leurre dont
            on charge le CPU

COMMENT ON JUGE UNE DÉSIGNATION (même règle pour tous, GNN compris)

  Un témoin classe les nœuds, toutes sortes confondues, du plus suspect au
  moins suspect. Il a juste au rang k (top-1, top-3) si au moins un fautif
  est parmi ses k premiers. Seules les fenêtres entièrement dans une
  injection confirmée portent un fautif ; les fenêtres normales n'en ont pas
  (y désigner quelqu'un est une fausse alerte) ; la charge compte pour la
  cause, jamais pour le fautif.

CE QUE FAIT LE SCRIPT

Pour chaque campagne nommée (sans nom : les dix des deux séries, SERIES) : lit le déroulé et le registre des pannes de
campagne.yaml, applique la règle de la cause, puis vérifie chaque fautif dans
le graphe figé de la campagne (le run nommé en tête de lecture.txt, contrôlé
par gel.py) : il doit exister comme nœud de la bonne sorte dans chaque fenêtre
entièrement dans l'injection. Écrit <campagnes>/fautifs.txt et affiche le même
texte.

Options :
  --campaigns <dossier>  le dossier des dossiers de campagne (défaut ../campagnes)
  --runs <dossier>       où sont les runs nommés par lecture.txt (défaut runs)
  --consumer <prefixe>   les répliques du consommateur (défaut ts-delivery-service-)
  --help                 ce texte

Code de sortie 0 si chaque injection a son fautif (ou n'en a pas, par règle)
et qu'il est vu dans le graphe figé ; 1 sinon ; 2 sur un mauvais argument.
Bibliothèque standard seulement.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import gel

HERE = Path(__file__).resolve().parent
TS = "%Y-%m-%dT%H:%M:%SZ"

# Les campagnes de l'étude : première série puis seconde série.
SERIES = ["saine-08", "charge-03", "blocage-02", "lenteur-01", "hote-01",
          "saine-09", "blocage-03", "hote-02", "charge-04", "lenteur-02"]

# La sorte de nœud du fautif, par cause ; None : pas de fautif.
SORTE = {"blocage": "instance", "hote": "host", "lenteur": "instance",
         "charge": None, "base": "instance", "reseau": "host"}


def _instant(texte: str) -> datetime:
    return datetime.strptime(texte, TS).replace(tzinfo=timezone.utc)


def injections(campagne: Path) -> list[dict]:
    """Les injections du déroulé, chacune avec sa ligne du registre des pannes."""
    texte = campagne.read_text()
    deroule = re.compile(r"instant: (\S+), action: (injection|retrait), cause: (\w+), "
                         r"resultat: (\w+)")
    paires, ouverte = [], None
    for m in deroule.finditer(texte):
        if m.group(2) == "injection":
            ouverte = {"debut": _instant(m.group(1)), "cause": m.group(3),
                       "confirmee": m.group(4) == "confirme"}
        elif ouverte:
            paires.append({**ouverte, "fin": _instant(m.group(1))})
            ouverte = None
    registre = texte.split("pannes_mesurees: |", 1)[1] if "pannes_mesurees: |" in texte else ""
    lignes = [l.strip().split("\t") for l in registre.splitlines()
              if re.match(r"\s+\d{4}-\d\d-\d\dT", l)]
    for p in paires:
        # La ligne du registre écrite par panne.sh au moment de CETTE injection
        # (le registre porte aussi tout l'historique du cluster).
        proches = [l for l in lignes if len(l) >= 8 and l[2] == "injection" and l[3] == p["cause"]
                   and abs((_instant(l[0]) - p["debut"]).total_seconds()) < 120]
        p["registre"] = proches[0] if len(proches) == 1 else None
        p["registre_ambigu"] = len(proches) > 1
    return paires


def fautifs(p: dict, fige: dict, consommateur: str, noms_instances: set[str]) -> tuple[list[str], str]:
    """(noms des fautifs, d'où vient la réponse), selon la règle de la cause."""
    cause = p["cause"]
    if cause not in SORTE:
        raise ValueError(f"cause inconnue : {cause}")
    if SORTE[cause] is None:
        return [], "aucun fautif par règle (jugée sur la cause)"
    if cause == "base":
        return sorted(set(fige["bases"].values())), "graphe_fige.json, bases"
    if cause == "lenteur":
        return sorted(n for n in noms_instances if n.startswith(consommateur)), \
            f"toutes les instances {consommateur}*"
    reg = p["registre"]
    if reg is None:
        raise ValueError("registre des pannes : " + ("plusieurs lignes" if p["registre_ambigu"]
                                                       else "aucune ligne") + " pour cette injection")
    cible = reg[5].split("@")[0]
    return [cible], f"registre : {reg[5]}"


def fenetres(run: Path) -> list[dict]:
    graphe = run / "graph"
    return [json.loads(p.read_text()) for p in sorted(graphe.glob("window_*.json"))]


def run_de(lecture: Path) -> str | None:
    m = re.search(r"construit par run\.py — (runs/\S+)", lecture.read_text())
    return m.group(1) if m else None


def rapport(campagnes: Path, noms: list[str], runs: Path, consommateur: str) -> int:
    fige, ecarts_ref, _ = gel.reference()
    tag = gel._empreintes_du_tag(fige)
    problemes = 0
    print("# Fautif de chaque injection — écrit par graphe_en/fautifs.py, ne pas éditer à la main.")
    print("# Règles fixées le 26 sept. 2026, avant tout calcul des témoins (voir fautifs.py).")
    print("# vu : fenêtres entièrement dans l'injection où chaque fautif est un nœud du graphe figé.")
    if ecarts_ref:
        print(f"# ATTENTION : {ecarts_ref[0]}")
        problemes += 1
    for nom in noms:
        dossier = campagnes / nom
        run_nom = run_de(dossier / "lecture.txt")
        run = (runs / run_nom.split("/", 1)[1]) if run_nom else None
        print(f"\n{nom}   graphe figé : {run_nom or '?'}")
        if run is None or not run.is_dir():
            print(f"  ÉCART  run introuvable : {run}")
            problemes += 1
            continue
        ecarts, _ = gel.run(run, fige, tag)
        if ecarts:
            print(f"  ÉCART  graphe non conforme au gel : {ecarts[0]}")
            problemes += 1
            continue
        fen = fenetres(run)
        liste = injections(dossier / "campagne.yaml")
        if not liste:
            print("  aucune injection : référence normale, aucun fautif")
        for k, p in enumerate(liste, 1):
            dedans = [f for f in fen if f["window"]["start_ns"] / 1e9 >= p["debut"].timestamp()
                      and f["window"]["end_ns"] / 1e9 <= p["fin"].timestamp()]
            instances = {n for f in dedans for n in f["nodes"]["instance"]["names"]}
            tete = (f"  {k}  {p['debut']:%H:%M:%S} → {p['fin']:%H:%M:%S}  {p['cause']:<8} "
                    f"{'' if p['confirmee'] else '(NON CONFIRMÉE) '}")
            try:
                noms_f, source = fautifs(p, fige, consommateur, instances)
            except ValueError as e:
                print(f"{tete}ÉCART  {e}")
                problemes += 1
                continue
            if not p["confirmee"]:
                print(f"{tete}écartée, pas de fautif")
                continue
            if not noms_f:
                print(f"{tete}—  {source}")
                continue
            sorte = SORTE[p["cause"]]
            vus = [sum(1 for f in dedans if n in f["nodes"][sorte]["names"]) for n in noms_f]
            print(f"{tete}{sorte} : {', '.join(noms_f)}")
            print(f"       {source} ; vu {'/'.join(map(str, vus))} sur {len(dedans)} fenêtres")
            if not dedans or any(v != len(dedans) for v in vus):
                print("       ÉCART  un fautif manque au graphe pendant l'injection")
                problemes += 1
    print(f"\n{'TOUS LES FAUTIFS SONT ÉTABLIS' if not problemes else f'{problemes} PROBLÈME(S)'}")
    return 0 if not problemes else 1


def main(argv: list[str]) -> int:
    campagnes, runs, consommateur = HERE.parent / "campagnes", HERE / "runs", "ts-delivery-service-"
    noms: list[str] = []
    args = argv[1:]
    try:
        while args:
            a = args.pop(0)
            if a == "--help":
                print(__doc__.strip())
                return 0
            elif a == "--campaigns":
                campagnes = Path(args.pop(0))
            elif a == "--runs":
                runs = Path(args.pop(0))
            elif a == "--consumer":
                consommateur = args.pop(0)
            elif a.startswith("-"):
                print(f"option inconnue : {a}", file=sys.stderr)
                return 2
            else:
                noms.append(a)
    except IndexError:
        print("option sans valeur", file=sys.stderr)
        return 2
    campagnes, runs = campagnes.resolve(), runs.resolve()
    noms = noms or SERIES
    manquants = [n for n in noms if not (campagnes / n / "campagne.yaml").is_file()
                 or not (campagnes / n / "lecture.txt").is_file()]
    if manquants:
        print(f"campagne.yaml ou lecture.txt manque pour : {', '.join(manquants)}", file=sys.stderr)
        return 1
    import contextlib
    import io
    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie):
        code = rapport(campagnes, noms, runs, consommateur)
    texte = sortie.getvalue()
    print(texte, end="")
    if code == 0:
        cible = campagnes / "fautifs.txt"
        cible.write_text(texte)
        print(f"-> {cible}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
