"""
Le graphe figé : ce qui ne change plus depuis la phase A.8, et sa vérification.

    ./.venv/bin/python gel.py                  le code d'ici est-il le graphe figé ?
    ./.venv/bin/python gel.py runs/<a> ...     ces graphes ont-ils été construits avec lui ?

Le graphe figé est décrit dans graphe_fige.json : les colonnes de chaque sorte
de nœud, dans l'ordre ; les relations, leur sens et leurs colonnes ; les
colonnes passées au log avant la mise à l'échelle, nœuds et relations ; les
réglages qui changent les nombres ; l'adresse de la base et son pod ; la façon
d'écrire les tenseurs ; la mise à l'échelle calée sur saine-09, par son
empreinte ; les fichiers qui calculent le graphe. Figé le 26 sept. 2026,
étiquette git graphe-fige.

Pourquoi : les témoins (phase B), puis le GNN (phase E), lisent tous le même
graphe. Figé avant toute donnée de la base lente (phase C) : un graphe
retouché après l'avoir vue serait taillé pour la réponse.

La référence est lue DANS L'ÉTIQUETTE (git show graphe-fige:…), pas sur le
disque : modifier graphe_fige.json ne desserre aucun contrôle, c'est un écart.
Sans l'étiquette, ou sans git, rien n'est prouvé : c'est un écart aussi. Sur
une copie qui ne l'a pas : git fetch --tags.

Sans argument, contrôle du code :
  1  l'étiquette, et aucune différence avec elle dans graphe_fige.json, gel.py
     et les fichiers listés, modifications non committées comprises ;
  2  les colonnes et relations de features.py, edges.py, export_pyg.py ;
  3  scaler.json, s'il est là (vms0) : même empreinte, mêmes colonnes, mêmes
     colonnes en log.
Avec des dossiers de run, chacun est contrôlé en plus : le code qui l'a
construit (empreintes du manifest.json contre l'étiquette), ses réglages, sa
façon d'écrire les tenseurs et sa mise à l'échelle, les colonnes de chaque
fenêtre, et les arêtes queries (au moins une, toutes vers la base figée, aucun
appel à une adresse inconnue). Un run construit avant le gel est refusé.

Un écart n'est jamais corrigé ici. S'il faut vraiment changer le graphe : le
dire, le noter dans notes/JOURNAL.md, modifier graphe_fige.json, poser une
nouvelle étiquette, reconstruire toutes les campagnes.

Code de sortie 0 si tout est conforme, 1 sinon, 2 sur un mauvais argument.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RACINE = HERE.parent
TAG = "graphe-fige"
REFERENCE = "graphe_en/graphe_fige.json"


def _git(*args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", "-C", str(RACINE), *args], capture_output=True)
    except OSError:
        return None


def reference() -> tuple[dict, list[str], str]:
    """graphe_fige.json tel que l'étiquette le porte ; le disque à défaut, avec un écart."""
    montre = _git("show", f"refs/tags/{TAG}:{REFERENCE}")
    if montre is not None and montre.returncode == 0:
        return json.loads(montre.stdout), [], f"référence lue dans l'étiquette {TAG}"
    pourquoi = "git absent" if montre is None else f"étiquette {TAG} absente ou illisible"
    return (json.loads((HERE / "graphe_fige.json").read_text()),
            [f"{pourquoi} : le gel ne peut pas être prouvé ici (git fetch --tags)"], "")


def dans_le_tag(fige: dict) -> tuple[list[str], str]:
    # gel.py aussi : la moitié des contrôles n'est écrite que dans ce code.
    fichiers = [REFERENCE, "graphe_en/gel.py"] + [f"graphe_en/{f}" for f in fige["fichiers"]]
    diff = _git("diff", "--name-only", f"refs/tags/{TAG}", "--", *fichiers)
    if diff is None or diff.returncode != 0:
        return ["comparaison avec l'étiquette impossible"], ""
    changes = diff.stdout.decode().split()
    if changes:
        return [f"{f} diffère de l'étiquette {TAG}" for f in changes], ""
    return [], f"{len(fichiers)} fichiers identiques à l'étiquette"


def code(fige: dict) -> list[str]:
    sys.path.insert(0, str(HERE))
    import edges
    import export_pyg
    import features

    ecarts = []
    if features.COLUMNS != fige["noeuds"]:
        ecarts.append(f"colonnes des nœuds : {features.COLUMNS}")
    relations = {r: {"de": s, "vers": t, "colonnes": list(c)}
                 for r, (s, t, c) in edges.RELATIONS.items()}
    if relations != fige["relations"]:
        ecarts.append(f"relations : {relations}")
    if export_pyg.LOG_COLUMNS != fige["log_avant_echelle"]["noeuds"]:
        ecarts.append(f"colonnes des nœuds en log : {export_pyg.LOG_COLUMNS}")
    if export_pyg.LOG_EDGE_COLUMNS != fige["log_avant_echelle"]["relations"]:
        ecarts.append(f"colonnes des relations en log : {export_pyg.LOG_EDGE_COLUMNS}")
    return ecarts


def _attendu_en_log(fige: dict) -> list[tuple[str, list[str], list[str], str]]:
    """(nom, colonnes, colonnes en log, où les chercher dans scaler.json)."""
    log = fige["log_avant_echelle"]
    out = [(k, c, log["noeuds"].get(k, []), "noeud") for k, c in fige["noeuds"].items()]
    out += [(r, spec["colonnes"], log["relations"].get(r, []), "relation")
            for r, spec in fige["relations"].items() if spec["colonnes"]]
    return out


def echelle(fige: dict) -> tuple[list[str], str]:
    chemin = HERE / "scaler.json"
    if not chemin.exists():
        return [], "scaler.json absent ici (normal hors de vms0) : non contrôlé"
    ecarts = []
    empreinte = hashlib.sha256(chemin.read_bytes()).hexdigest()
    if empreinte != fige["echelle"]["sha256"]:
        ecarts.append(f"scaler.json a changé : empreinte {empreinte[:12]}…, "
                      f"figée {fige['echelle']['sha256'][:12]}…")
    stats = json.loads(chemin.read_text()).get("scaler", {})
    for nom, colonnes, en_log, sorte in _attendu_en_log(fige):
        bloc = stats.get(nom, []) if sorte == "noeud" else stats.get("relations", {}).get(nom, [])
        if [s.get("column") for s in bloc] != colonnes:
            ecarts.append(f"scaler.json, {nom} : calé sur {[s.get('column') for s in bloc]}")
        elif [s["column"] for s in bloc if s.get("log")] != [c for c in colonnes if c in en_log]:
            ecarts.append(f"scaler.json, {nom} : colonnes en log différentes")
    return ecarts, "" if ecarts else f"scaler.json = celui de {fige['echelle']['campagne']}"


def _empreintes_du_tag(fige: dict) -> dict[str, str | None]:
    out = {}
    for f in fige["fichiers"]:
        montre = _git("show", f"refs/tags/{TAG}:graphe_en/{f}")
        out[f] = (hashlib.sha256(montre.stdout).hexdigest()
                  if montre is not None and montre.returncode == 0 else None)
    return out


def run(dossier: Path, fige: dict, tag: dict) -> tuple[list[str], str]:
    graphe = dossier / "graph" if (dossier / "graph").is_dir() else dossier
    manifest = graphe / "manifest.json"
    fenetres = sorted(graphe.glob("window_*.json"))
    if not manifest.exists():
        return [f"pas de manifest.json dans {graphe}"], ""
    if not fenetres:
        return [f"aucune window_*.json dans {graphe}"], ""
    m = json.loads(manifest.read_text())
    ecarts = []

    # Le code qui a construit le run.
    empreintes = (m.get("code") or {}).get("files")
    if not empreintes:
        ecarts.append("construit avant le gel : le manifest ne dit pas quel code l'a construit")
    elif all(v is None for v in tag.values()):
        ecarts.append("étiquette illisible : le code qui a construit ce run n'est pas vérifiable")
    else:
        for f, voulu in tag.items():
            if voulu is None or empreintes.get(f) != voulu:
                ecarts.append(f"construit avec un {f} différent de l'étiquette")

    # Réglages et tenseurs.
    reglages = m.get("settings", {})
    for cle, voulu in {**fige["reglages"], "databases": fige["bases"]}.items():
        if reglages.get(cle) != voulu:
            ecarts.append(f"réglage {cle} = {reglages.get(cle)!r}, figé {voulu!r}")
    export = m.get("export") or {}
    for cle, voulu in fige["tenseurs"].items():
        if export.get(cle) != voulu:
            ecarts.append(f"tenseurs : {cle} = {export.get(cle)!r}, figé {voulu!r}")
    if export.get("scaler") not in ("write", "apply") or \
            export.get("scaler_sha256") != fige["echelle"]["sha256"]:
        ecarts.append(f"mise à l'échelle {export.get('scaler')!r}, empreinte "
                      f"{str(export.get('scaler_sha256'))[:12]}… : pas celle de "
                      f"{fige['echelle']['campagne']}")

    # Chaque fenêtre.
    # Toutes les fenêtres sont lues ; seuls les 8 premiers écarts sont gardés.
    bases = set(fige["bases"].values())
    vers_la_base = 0
    avant = len(ecarts)
    for chemin in fenetres:
        f = json.loads(chemin.read_text())
        for kind, colonnes in fige["noeuds"].items():
            vues = f["nodes"].get(kind, {}).get("columns")
            if vues != colonnes:
                ecarts.append(f"{chemin.name}, {kind} : {vues}")
        if set(f["edges"]) != set(fige["relations"]):
            ecarts.append(f"{chemin.name}, relations : {sorted(f['edges'])}")
        for rel, spec in fige["relations"].items():
            bloc = f["edges"].get(rel)
            if bloc is not None and bloc.get("columns") != spec["colonnes"]:
                ecarts.append(f"{chemin.name}, {rel} : {bloc.get('columns')}")
        if f.get("db_unmapped"):
            ecarts.append(f"{chemin.name} : {f['db_unmapped']} appels à une base inconnue")
        q = f["edges"].get("queries") or {"target": []}
        noms = f["nodes"]["instance"]["names"]
        cibles = [noms[t] for t in q["target"]]
        if set(cibles) - bases:
            ecarts.append(f"{chemin.name}, queries vers {sorted(set(cibles) - bases)}")
        vers_la_base += len(cibles)
    if len(ecarts) - avant > 8:
        reste = len(ecarts) - avant - 8
        ecarts = ecarts[:avant + 8] + [f"… et {reste} autre(s) écart(s) dans les fenêtres"]
    if not vers_la_base:
        ecarts.append("aucune arête queries dans tout le run : la base est invisible")
    return ecarts, "" if ecarts else f"{len(fenetres)} fenêtres conformes"


def main(argv: list[str]) -> int:
    if any(a in ("-h", "--help") for a in argv[1:]):
        print(__doc__.strip())
        return 0
    runs = [Path(a) for a in argv[1:]]
    manquants = [str(r) for r in runs if not r.is_dir()]
    if manquants:
        print(f"pas un dossier : {', '.join(manquants)}", file=sys.stderr)
        return 2
    fige, ecarts_ref, bilan_ref = reference()
    print(f"graphe figé le {fige['fige_le']}, étiquette {TAG}")
    controles = [("étiquette", (ecarts_ref, bilan_ref) if ecarts_ref else dans_le_tag(fige)),
                 ("code", (code(fige), "colonnes, relations et colonnes en log conformes")),
                 ("échelle", echelle(fige))]
    tag = _empreintes_du_tag(fige)
    controles += [(str(r), run(r, fige, tag)) for r in runs]
    total = 0
    for nom, (ecarts, bilan) in controles:
        if ecarts:
            total += len(ecarts)
            print(f"  ÉCART  {nom}")
            for e in ecarts:
                print(f"         {e}")
        else:
            print(f"  ok     {nom} : {bilan}")
    print("CONFORME" if not total else f"NON CONFORME : {total} écart(s)")
    return 0 if not total else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
