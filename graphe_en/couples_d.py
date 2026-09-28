"""
Les couples (X, Y) de la phase D, par la règle écrite avant D (journal, 28 sept., D.1).

    ./.venv/bin/python couples_d.py --placement <fichier> --libres <fichier> [options]

X porte le réseau ralenti, Y le leurre bruyant. Aucun tirage, aucun témoin lu :
seulement le placement au départ de D, le CPU libre des machines et les fenêtres
NORMALES d'APPRENTISSAGE des deux séries (jamais le test, jamais C ni D).

  X  une machine de travail qui porte une réplique du consommateur ET au moins
     deux autres services actifs, et qui ne porte ni le leader de la base, ni
     rabbitmq, ni le producteur ts-food-service, ni ts-order-service, ni la
     passerelle ; une suiveuse de la base l'exclut si SUIVEUSE_EXCLUT (réglé par
     la mesure de D.2) ; jamais workers6 ni le master.
  Y  une autre machine de travail, jamais workers6 ni le master, sans pod de la
     base (leader ou suiveuse), ni rabbitmq, ni le producteur, ni ts-order-service,
     ni la passerelle, ni réplique, où le voisin leurre réclamerait au moins
     1 400 m par la règle de la cause hote (min(2 cœurs, libre − 100 m, arrondi
     à 100 m)) : la plus petite demande des voisins de la seconde série (D.2).
  actif  un service placé sur X, SOURCE d'une flèche calls ou queries vers un
     service placé (au moins un de ses pods) hors de X, dans plus de la moitié
     des fenêtres normales d'apprentissage des deux séries.
  ordre  X trié par nom, Y trié par nom, couples (X, Y) avec X ≠ Y dans l'ordre
     lexicographique ; l'injection k prend le couple (k − 1) mod n.

Options :
  --placement <f>   « pod machine phase … » par ligne (la sortie de lire_placement
                    de campagne.sh, ou le bloc placement de campagne.yaml) ; seuls
                    les pods Running, pas en arrêt, comptent
  --libres <f>      « machine millicœurs_libres » par ligne (panne.sh libres)
  --injections <n>  écrit aussi la cible de chaque injection (« X:Y »)
  --campaigns <d>   le dossier des dossiers de campagne (défaut ../campagnes)
  --runs <d>        où sont les runs (défaut runs)
  --help            ce texte

Code de sortie 0 ; 1 si aucun couple ou une lecture refusée ; 2 sur un mauvais argument.
"""
from __future__ import annotations

import sys
from pathlib import Path

import fautifs as fautifs_module
import juge
import temoin_noeud as tn

HERE = Path(__file__).resolve().parent
CONSO = "instance:ts-delivery-service"
EXCLUS = {"instance:rabbitmq": "rabbitmq", "instance:ts-food-service": "le producteur",
          "instance:ts-order-service": "ts-order-service", "instance:ts-gateway-service": "la passerelle"}
LEADER, BASE = "tsdb-mysql-0", "tsdb-mysql-"
JAMAIS = {"workers6", "master"}
LEURRE_MIN_M = 1400   # la plus petite demande du voisin dans la seconde série (workers2)


def demande_voisin(libre: int) -> int:
    """Ce que le voisin réclame par la règle de panne.sh : 2 cœurs, sinon libre − 100 m arrondi à 100 m."""
    return 2000 if 2000 <= libre - 100 else (libre - 100) // 100 * 100
# Mesure de D.2 (journal, 28 sept.) : une suiveuse retardée change-t-elle le temps de validation ?
SUIVEUSE_EXCLUT = False   # 0,54 → 0,60 ms, leader inchangé : ne change pas
APPELS = ("calls", "queries")


def lire_placement(chemin: Path) -> dict[str, str]:
    """{pod : machine} des pods EN MARCHE, depuis « pod machine phase … » : un pod en
    attente (machine « <none> ») ou en arrêt (« en_arret=… ») n'est placé nulle part."""
    out = {}
    for ligne in chemin.read_text().splitlines():
        mots = ligne.split()
        if (len(mots) >= 3 and not ligne.lstrip().startswith("#") and not mots[0].endswith(":")
                and mots[2] == "Running" and not any(m.startswith("en_arret=") for m in mots)):
            out[mots[0]] = mots[1]
    return out


def lire_libres(chemin: Path) -> dict[str, int]:
    out = {}
    for ligne in chemin.read_text().splitlines():
        mots = ligne.split()
        if len(mots) == 2 and mots[1].lstrip("-").isdigit():
            out[mots[0]] = int(mots[1])
    return out


def paires_par_fenetre(campagnes: Path, runs: Path) -> list[set[tuple[str, str]]]:
    """Pour chaque fenêtre normale d'apprentissage des deux séries : ses paires (source, cible) calls/queries."""
    fen = juge.lire(fautifs_module.SERIES, campagnes, runs)
    out = []
    for f in fen:
        if f["jeu"] != "apprentissage" or f["etiquette"] != "normale":
            continue
        d, paires = f["donnees"], set()
        for rel, bloc in d["edges"].items():
            if rel not in APPELS:
                continue
            sn = d["nodes"][bloc["source_kind"]]["names"]
            tg = d["nodes"][bloc["target_kind"]]["names"]
            for s, t in zip(bloc["source"], bloc["target"]):
                paires.add((tn.identite(bloc["source_kind"], sn[s]), tn.identite(bloc["target_kind"], tg[t])))
        out.append(paires)
    return out


def couples(placement: dict[str, str], libres: dict[str, int],
            fenetres: list[set[tuple[str, str]]]) -> tuple[list[tuple[str, str]], list[str]]:
    """(couples dans l'ordre, lignes d'explication)."""
    ident = {p: tn.identite("instance", p) for p in placement}
    ou: dict[str, set[str]] = {}
    for p, m in placement.items():
        ou.setdefault(ident[p], set()).add(m)
    machines = sorted({m for m in placement.values() if m not in JAMAIS})
    lignes = [f"{len(fenetres)} fenêtres normales d'apprentissage des deux séries ; "
              f"suiveuse {'exclut' if SUIVEUSE_EXCLUT else 'n exclut pas'} X (mesure de D.2)"]

    def porte(m: str) -> dict[str, list[str]]:
        """Ce qui, sur la machine m, compte pour la règle."""
        r: dict[str, list[str]] = {"leader": [], "suiveuse": [], "exclus": [], "replique": []}
        for p, mm in placement.items():
            if mm != m:
                continue
            if p == LEADER:
                r["leader"].append(p)
            elif p.startswith(BASE):
                r["suiveuse"].append(p)
            elif ident[p] in EXCLUS:
                r["exclus"].append(EXCLUS[ident[p]])
            elif ident[p] == CONSO:
                r["replique"].append(p)
        return r

    xs, ys = [], []
    for m in machines:
        r = porte(m)
        # X
        raisons = []
        if not r["replique"]:
            raisons.append("aucune réplique")
        if r["leader"]:
            raisons.append("le leader de la base")
        if r["exclus"]:
            raisons.append(", ".join(sorted(set(r["exclus"]))))
        if r["suiveuse"] and SUIVEUSE_EXCLUT:
            raisons.append("une suiveuse de la base")
        services = sorted({ident[p] for p, mm in placement.items() if mm == m} - {CONSO})
        actifs = []
        for s in services:
            n = sum(1 for w in fenetres
                    if any(src == s and any(h != m for h in ou.get(t, ())) for src, t in w))
            if 2 * n > len(fenetres):
                actifs.append(f"{s.split(':', 1)[1]} ({n}/{len(fenetres)})")
        if len(actifs) < 2:
            raisons.append(f"{len(actifs)} service(s) actif(s) seulement")
        if raisons:
            lignes.append(f"  {m} : pas X ({' ; '.join(raisons)})")
        else:
            xs.append(m)
            lignes.append(f"  {m} : X possible — actifs : {', '.join(actifs)}")
        # Y
        raisons = []
        if r["leader"] or r["suiveuse"]:
            raisons.append("un pod de la base")
        if r["exclus"]:
            raisons.append(", ".join(sorted(set(r["exclus"]))))
        if r["replique"]:
            raisons.append("une réplique")
        libre = libres.get(m)
        if libre is None or demande_voisin(libre) < LEURRE_MIN_M:
            raisons.append(f"CPU libre {libre if libre is not None else '?'} m : le voisin réclamerait moins de {LEURRE_MIN_M} m")
        if raisons:
            lignes.append(f"  {m} : pas Y ({' ; '.join(raisons)})")
        else:
            ys.append(m)
            lignes.append(f"  {m} : Y possible — {libre} m libres, le voisin réclamerait {demande_voisin(libre)} m")
    out = [(x, y) for x in sorted(xs) for y in sorted(ys) if x != y]
    return out, lignes


def main(argv: list[str]) -> int:
    campagnes, runs, placement, libres, n_inj = HERE.parent / "campagnes", HERE / "runs", None, None, 0
    args = argv[1:]
    try:
        while args:
            a = args.pop(0)
            if a == "--help":
                print(__doc__.strip())
                return 0
            elif a == "--placement":
                placement = Path(args.pop(0))
            elif a == "--libres":
                libres = Path(args.pop(0))
            elif a == "--injections":
                n_inj = int(args.pop(0))
            elif a == "--campaigns":
                campagnes = Path(args.pop(0))
            elif a == "--runs":
                runs = Path(args.pop(0))
            else:
                print(f"option inconnue : {a}", file=sys.stderr)
                return 2
    except (IndexError, ValueError):
        print("option sans valeur ou valeur illisible", file=sys.stderr)
        return 2
    if placement is None or libres is None:
        print("--placement et --libres sont exigés", file=sys.stderr)
        return 2
    try:
        fenetres = paires_par_fenetre(campagnes.resolve(), runs.resolve())
    except juge.Refus as e:
        print(f"REFUS  {e}")
        return 1
    liste, lignes = couples(lire_placement(placement), lire_libres(libres), fenetres)
    print("\n".join(lignes))
    print("couples : " + (", ".join(f"{x}:{y}" for x, y in liste) if liste else "AUCUN"))
    if liste and n_inj:
        print("cibles : " + ",".join(f"{liste[k % len(liste)][0]}:{liste[k % len(liste)][1]}" for k in range(n_inj)))
    return 0 if liste else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
