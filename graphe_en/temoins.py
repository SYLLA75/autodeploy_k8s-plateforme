"""
Les mesures de tous les témoins, côte à côte.

    ./.venv/bin/python temoins.py [options]

Phase B.6. Les trois témoins, chacun dans ses réglages, et le plancher « a
priori », sur les deux séries, jugés par juge.py avec les règles de fautifs.py.
Rien n'est réglé ici : chaque témoin est appris par son propre fichier
(temoin_tableau.py, temoin_noeud.py, temoin_fleches.py), exactement comme
dans son rapport à lui.

1. LE TABLEAU DE BORD : les mesures du test, une ligne par témoin. Un témoin
   qui tire au hasard est appris avec les graines 0 à 4 : médiane, et entre
   crochets le minimum et le maximum s'ils diffèrent.

2. LES FAUSSES ALERTES AU FIL DU TEMPS, sur les fenêtres normales du test :
   campagne par campagne dans l'ordre des dates, avant et après la dernière
   injection (une campagne sans injection : son dernier tiers). Le flux
   commandes → base grossit avec l'âge de la purge : une dérive se verrait en
   fin de campagne. Graines : la médiane par case.

3. LA RÉPÉTITION « PANNE JAMAIS VUE » : chaque cause connue retirée à son tour
   de l'apprentissage (toutes ses injections passent au test, la bonne cause y
   est « inconnue », fautifs.py). Pour chaque témoin : la détection,
   « inconnue », le fautif top-1 et top-3 sur les fenêtres de la cause retirée.
   C'est l'épreuve de la base lente (phase C), répétée sur des pannes connues :
   qui désigne un fautif qu'il n'a jamais vu fauter ? La règle qui suit les
   flèches porte les noms des quatre causes (l'ingénieur les connaît) : sa
   colonne « inconnue » est sans objet, et sa désignation ne dit rien de
   l'inconnu, chaque branche ayant été écrite pour sa cause : ses lignes ne se
   comparent pas à celles du GNN ; seule la base lente l'éprouve. Sans exemples, le score par nœud et
   la règle ne changent pas quand une cause est retirée : leur ligne mesure la
   même méthode sur les trois injections de la cause au lieu d'une.

Options :
  --campaigns <dossier>  le dossier des dossiers de campagne (défaut ../campagnes)
  --runs <dossier>       où sont les runs (défaut runs)
  --validation           la coupure répétée dans l'apprentissage (juge.validation),
                         le vrai test jamais lu : pour régler ; écrit
                         <campagnes>/temoins-validation.txt
  --graines <n>          nombre de graines, à partir de 0 (défaut 5)
  --no-install           n'installe jamais scikit-learn
  --help                 ce texte

Écrit <campagnes>/temoins.txt et affiche le même texte. Code de sortie 0, 1 si
une campagne est refusée ou une bibliothèque manque, 2 sur un mauvais argument.
"""
from __future__ import annotations

import contextlib
import io
import statistics
import sys
from pathlib import Path

import bootstrap
import fautifs as fautifs_module
import gel
import juge
import temoin_fleches as tf
import temoin_noeud as tn
import temoin_tableau as tt

HERE = Path(__file__).resolve().parent
REPETEES = ("blocage", "charge", "hote", "lenteur")


def temoins(fige: dict) -> list[tuple[str, object, bool]]:
    """(nom, fabrique(fen, graine), tire au hasard)."""
    return [
        ("tableau équitable", lambda fen, g: tt.Tableau(fen, graine=g), True),
        ("score par nœud, sans exemples", lambda fen, g: tn.Noeud(fen, "sans exemples", fige), False),
        ("score par nœud, avec exemples", lambda fen, g: tn.Noeud(fen, "avec exemples", fige, graine=g), True),
        ("règle littérale, sans exemples", lambda fen, g: tf.Fleches(fen, "sans exemples", fige, "littérale"), False),
        ("règle littérale, avec exemples", lambda fen, g: tf.Fleches(fen, "avec exemples", fige, "littérale"), False),
        ("règle cause commune, sans exemples",
         lambda fen, g: tf.Fleches(fen, "sans exemples", fige, "cause commune"), False),
        ("règle cause commune, avec exemples",
         lambda fen, g: tf.Fleches(fen, "avec exemples", fige, "cause commune"), False),
    ]


def repondre(t, fen: list[dict]) -> dict:
    test = [f for f in fen if f["jeu"] == "test" and f["etiquette"] not in juge.ECARTEES]
    return {f["id"]: {k: v for k, v in t.repondre(f["donnees"]).items() if not k.startswith("_")} for f in test}


def notes(fen: list[dict], fige: dict, graines: int) -> dict[str, list[tuple[dict, dict]]]:
    """{témoin : [(chiffres, réponses) par graine]}, plus « a priori »."""
    out = {}
    for nom, fabrique, hasard in temoins(fige):
        out[nom] = []
        for g in range(graines if hasard else 1):
            rep = repondre(fabrique(fen, g), fen)
            out[nom].append((juge.noter(fen, rep)[1], rep))
    rep = juge.factices(fen)["a priori"]
    out["a priori (ne lit rien)"] = [(juge.noter(fen, rep)[1], rep)]
    return out


def _case(valeurs: list[int], total: int) -> str:
    m = statistics.median(valeurs)
    texte = f"{m:g}/{total}"
    if min(valeurs) != max(valeurs):
        texte += f" [{min(valeurs)}–{max(valeurs)}]"
    return texte


def tableau_de_bord(n: dict) -> list[str]:
    """Une ligne par témoin ; les causes apprises, puis chaque cause jamais vue à part."""
    premier = next(iter(n.values()))[0][0]
    jamais = sorted(k.split(" : ", 1)[1] for k in premier if k.startswith("detection jamais vue : "))
    apprises = lambda cle: f"{cle}, causes apprises" if jamais else cle
    injection = lambda k, part: f"{k} ({part})" if jamais else k
    colonnes = [("détection", apprises("detection")), ("fausses alertes", "fausses alertes non vues"),
                ("f.a. saine-09", "fausses alertes vues (saine-09)"), ("cause", apprises("cause")),
                ("top-1", "top-1 causes apprises"), ("top-3", "top-3 causes apprises"),
                ("top-1 blocage", "top-1 blocage"), ("top-1 hôte", "top-1 hote"),
                ("top-1 lenteur", "top-1 lenteur"), ("top-1 nouveau", "top-1 fautif nouveau")]
    injections = [("injections cause", injection("cause", "causes apprises")),
                  ("injections top-1", injection("top-1", "causes apprises"))]
    for c in jamais:
        colonnes += [(f"{c} (jamais vue) : détection", f"detection jamais vue : {c}"),
                     ("« inconnue »", f"cause jamais vue : {c}"),
                     ("top-1", f"top-1 jamais vue : {c}"), ("top-3", f"top-3 jamais vue : {c}")]
        injections += [(f"{c} : injections top-1", injection("top-1", f"jamais vue : {c}"))]
    out = []
    for nom, liste in n.items():
        out.append(f"{nom}  ({len(liste)} graine{'s' if len(liste) > 1 else ''})")
        cases = []
        for titre, cle in colonnes:
            v = [c[cle][0] for c, _ in liste if cle in c]
            if v:
                cases.append(f"{titre} {_case(v, liste[0][0][cle][1])}")
        for titre, cle in injections:
            v = [c["injections"][cle][0] for c, _ in liste if cle in c["injections"]]
            if v:
                cases.append(f"{titre} {_case(v, liste[0][0]['injections'][cle][1])}")
        for i in range(0, len(cases), 4):
            out.append("    " + " ; ".join(cases[i:i + 4]))
    return out


def fil_du_temps(fen: list[dict], n: dict) -> list[str]:
    normales = [f for f in fen if f["jeu"] == "test" and f["etiquette"] == "normale"]
    ordre = sorted({f["campagne"] for f in normales}, key=lambda c: min(f["debut"] for f in fen if f["campagne"] == c))
    derniere = {}
    for c in ordre:
        # la première fenêtre de la DERNIÈRE injection du test (une cause jamais vue
        # met toutes ses injections au test)
        pannes = [f for f in fen if f["campagne"] == c and f["etiquette"] == "panne" and f["jeu"] == "test"]
        k = max((f["injection"] for f in pannes), default=None)
        derniere[c] = min((f["debut"] for f in pannes if f["injection"] == k), default=None)
    cles = []
    for c in ordre:
        if derniere[c] is None:
            cles.append((c, "fin", [f for f in normales if f["campagne"] == c]))
        else:
            cles.append((c, "avant", [f for f in normales if f["campagne"] == c and f["debut"] < derniere[c]]))
            cles.append((c, "après", [f for f in normales if f["campagne"] == c and f["debut"] >= derniere[c]]))
    noms = list(n)
    largeur = max(len(x) for x in noms)
    out = [f"{'campagne':<12}{'':<7}{'fen.':>5}  " + "  ".join(f"{i + 1:>7}" for i in range(len(noms)))]
    for i, nom in enumerate(noms):
        out.insert(i, f"  {i + 1} = {nom:<{largeur}}")
    for c, quand, groupe in cles:
        if not groupe:
            continue
        cases = []
        for nom in noms:
            v = [sum(1 for f in groupe if rep[f["id"]]["alarme"]) for _, rep in n[nom]]
            cases.append(f"{statistics.median(v):>7g}")
        date = min(f["debut"] for f in groupe)
        out.append(f"{c:<12}{quand:<7}{len(groupe):>5}  " + "  ".join(cases) + f"   ({date:%d/%m %H:%M} UTC)")
    return out


def repetition(noms_campagnes: list[str], campagnes: Path, runs: Path, fige: dict, graines: int,
               validation: bool) -> list[str]:
    out = []
    for cause in REPETEES:
        fen = juge.lire(noms_campagnes, campagnes, runs, jamais_vues=juge.JAMAIS_VUES | {cause})
        if validation:
            fen = juge.validation(fen)
        groupe = [f for f in fen if f["jeu"] == "test" and f["etiquette"] == "panne" and f["cause"] == cause]
        injections = len({(f["campagne"], f["injection"]) for f in groupe})
        out.append(f"\n{cause} retirée de l'apprentissage : {len(groupe)} fenêtres de test, {injections} injections")
        n = notes(fen, fige, graines)
        for nom, liste in n.items():
            cases = []
            for titre, cle in (("détection", f"detection jamais vue : {cause}"),
                               ("« inconnue »", f"cause jamais vue : {cause}"),
                               ("top-1", f"top-1 jamais vue : {cause}"),
                               ("top-3", f"top-3 jamais vue : {cause}")):
                v = [c[cle][0] for c, _ in liste if cle in c]
                if v:
                    cases.append(f"{titre} {_case(v, liste[0][0][cle][1])}")
            if nom.startswith("règle"):
                cases = [x for x in cases if not x.startswith("« inconnue »")] + ["« inconnue » sans objet"]
            out.append(f"  {nom:<36}" + " ; ".join(cases))
    return out


def rapport(noms: list[str], campagnes: Path, runs: Path, graines: int, validation: bool = False) -> int:
    try:
        fen = juge.lire(noms, campagnes, runs)
    except juge.Refus as e:
        print(f"REFUS  {e}")
        return 1
    if validation:
        fen = juge.validation(fen)
        print("# VALIDATION : coupure répétée dans l'apprentissage (juge.validation), vrai test jamais lu")
    fige, _, _ = gel.reference()
    print("# Les témoins côte à côte — écrit par graphe_en/temoins.py, ne pas éditer à la main.")
    print(f"# graines 0 à {graines - 1} pour ce qui tire au hasard ; règles : fautifs.py ; juge : juge.py")
    n = notes(fen, fige, graines)
    normales = [f for f in fen if f["jeu"] == "test" and f["etiquette"] == "normale"]
    print(f"\n== 1. tableau de bord ({'validation' if validation else 'test'} ; fausses alertes sur "
          f"{sum(1 for f in normales if not f['vue'])} minutes normales non vues, puis sur "
          f"{sum(1 for f in normales if f['vue'])} de saine-09)")
    print("\n".join(tableau_de_bord(n)))
    print("\n== 2. fausses alertes au fil du temps (fenêtres normales du test ; médiane sur les graines)")
    print("\n".join(fil_du_temps(fen, n)))
    print("\n== 3. répétition « panne jamais vue » (une cause connue retirée de l'apprentissage)")
    print("\n".join(repetition(noms, campagnes, runs, fige, graines, validation)))
    return 0


def main(argv: list[str]) -> int:
    campagnes, runs, installer, graines = HERE.parent / "campagnes", HERE / "runs", True, 5
    validation = False
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
            elif a == "--validation":
                validation = True
            elif a == "--graines":
                graines = int(args.pop(0))
                if graines < 1:
                    raise ValueError
            elif a == "--no-install":
                installer = False
            elif a.startswith("-"):
                print(f"option inconnue : {a}", file=sys.stderr)
                return 2
            else:
                noms.append(a)
    except (IndexError, ValueError):
        print("option sans valeur ou valeur illisible", file=sys.stderr)
        return 2
    req = bootstrap.REQUIREMENTS["baseline"]
    if not bootstrap.is_available(req.module):
        if installer and bootstrap.in_virtualenv():
            fait, detail = bootstrap.install(req)
            if not fait:
                print(f"impossible d'installer {req.package} : {detail}", file=sys.stderr)
                return 1
        else:
            print(f"{req.package} manque : {bootstrap.manual_command(req)}", file=sys.stderr)
            return 1
    campagnes, runs = campagnes.resolve(), runs.resolve()
    noms = noms or fautifs_module.SERIES
    sortie = io.StringIO()
    with contextlib.redirect_stdout(sortie):
        print(f"# campagnes lues : {', '.join(noms)}")
        code = rapport(noms, campagnes, runs, graines, validation)
    texte = sortie.getvalue()
    print(texte, end="")
    if code == 0:
        cible = campagnes / juge.sortie("temoins", noms, validation)
        cible.write_text(texte)
        print(f"-> {cible}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
