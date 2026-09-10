#!/usr/bin/env python3
"""
Assembler le graphe et l'écrire — un fichier par fenêtre.

    python3 graphe.py donnees/2026-09-09_1505-1514 --espace train-ticket
    python3 graphe.py donnees/... --espace train-ticket --sortie graphes/essai1

Sixième brique. Elle appelle les cinq précédentes et range le résultat dans un
format neutre, lisible sans aucune bibliothèque particulière.

POURQUOI UN FORMAT NEUTRE ET NON DIRECTEMENT PyTorch Geometric

    PyG tire PyTorch, soit deux à trois gigaoctets, et ses versions cassent
    entre elles. Un jeu de données doit survivre au changement de bibliothèque :
    dans cinq ans, un relecteur ouvrira un JSON, il n'installera pas ta version
    de PyG. La conversion vers PyG est donc une brique séparée et facultative,
    qui lit ces fichiers.

CE QU'ON ÉCRIT

    graphes/<campagne>/
        manifeste.json          les réglages, la provenance, les dimensions
        fenetre_0001.json       un cliché
        fenetre_0002.json
        ...

Chaque fichier de fenêtre porte, pour chaque sorte de rond, la liste des
identifiants et une matrice de nombres ; pour chaque sorte de flèche, les deux
listes d'indices et une matrice de nombres. Les indices renvoient à la position
dans la liste de ronds du type concerné — c'est la forme qu'attendent aussi bien
PyG que DGL, et elle se relit à la main.

LES VALEURS MANQUANTES sont écrites `null`, jamais zéro. Un zéro et une absence
ne veulent pas dire la même chose : un débit nul est une information, un débit
inconnu n'en est pas une. Le manifeste rappelle qu'il faudra les traiter avant
tout apprentissage.

LE MANIFESTE DÉCRIT LE JEU DE DONNÉES lui-même : réglages employés, provenance
des fichiers bruts, dimensions, et les écarts assumés par rapport au papier. Un
jeu de données sans ce carnet n'est pas réutilisable.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from decoupage import charger, decouper                       # noqa: E402
from fleches import NOMS_APPELER, NOMS_DEBIT, fleches_de       # noqa: E402
from ronds import ronds_de                                     # noqa: E402
from valeurs import (NOMS_COPIE, NOMS_FILE, NOMS_MACHINE,      # noqa: E402
                     QUANTILES, calculer)

RACINE = Path(__file__).resolve().parent
GENRES_RONDS = ("copie", "file", "machine")
GENRES_FLECHES = {
    "appeler":     ("copie", "copie", NOMS_APPELER),
    "deposer":     ("copie", "file", NOMS_DEBIT),
    "retirer":     ("file", "copie", NOMS_DEBIT),
    "tourner_sur": ("copie", "machine", []),
}
NOMS_PAR_GENRE = {"copie": NOMS_COPIE, "file": NOMS_FILE, "machine": NOMS_MACHINE}


def _propre(v):
    """JSON n'accepte ni NaN ni infini. On les rend indistincts d'une absence."""
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def batir(fenetre, vecteurs, fl, rapport_fleches) -> dict:
    """Un cliché, prêt à écrire."""
    ronds = {g: [] for g in GENRES_RONDS}
    for cle, vec in vecteurs.items():
        ronds[vec.rond.genre].append((cle, vec))
    for g in ronds:
        ronds[g].sort(key=lambda x: x[1].rond.nom)

    position = {g: {cle: i for i, (cle, _) in enumerate(ronds[g])} for g in ronds}

    bloc_ronds = {}
    for g, lot in ronds.items():
        bloc_ronds[g] = {
            "cles":     [cle for cle, _ in lot],
            "noms":     [v.rond.nom for _, v in lot],
            "machines": [v.rond.machine for _, v in lot],
            "colonnes": NOMS_PAR_GENRE[g],
            "X":        [[_propre(x) for x in v.valeurs] for _, v in lot],
        }

    bloc_fleches = {}
    for genre, (gd, gv, noms) in GENRES_FLECHES.items():
        lot = [x for x in fl if x.genre == genre]
        de, vers, X = [], [], []
        for x in lot:
            i, j = position[gd].get(x.de), position[gv].get(x.vers)
            if i is None or j is None:
                continue                      # extrémité hors du graphe retenu
            de.append(i)
            vers.append(j)
            X.append([_propre(v) for v in x.valeurs])
        bloc_fleches[genre] = {"de_type": gd, "vers_type": gv,
                               "de": de, "vers": vers,
                               "colonnes": noms, "X": X}

    return {
        "fenetre": {
            "indice": fenetre.indice,
            "debut_ns": fenetre.debut_ns, "fin_ns": fenetre.fin_ns,
            "horodatage_utc": fenetre.horodatage,
            "duree_s": fenetre.duree_s,
            "couverture_s": round(fenetre.couverture_s, 2),
            "notes": len(fenetre.notes), "releves": len(fenetre.releves),
        },
        "ronds": bloc_ronds,
        "fleches": bloc_fleches,
        "resolution_appels": rapport_fleches["resolution"],
    }


def manifeste(source: Path, sortie: Path, args, rapport, n: int, suite) -> dict:
    origine = source / "origine.json"
    prov = json.loads(origine.read_text()) if origine.exists() else None
    return {
        "genere_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": str(source),
        "provenance_brute": {
            "magasin": prov.get("magasin") if prov else None,
            "bucket": prov.get("bucket") if prov else None,
            "fichiers": len(prov["fichiers"]) if prov else None,
        },
        "reglages": {
            "largeur_s": args.largeur,
            "pas_s": args.pas if args.pas is not None else args.largeur,
            "espace": args.espace,
            "horizon_pente_H": args.horizon,
            "echantillonnage_eta": args.echantillon,
            "quantiles": list(QUANTILES),
            "assignation": "une note appartient à la fenêtre de son DÉBUT",
            "bords": "fenêtres non entièrement couvertes par les données : écartées",
        },
        "dimensions": {
            "ronds": {g: len(NOMS_PAR_GENRE[g]) for g in GENRES_RONDS},
            "fleches": {g: len(v[2]) for g, v in GENRES_FLECHES.items()},
        },
        "decoupage": {k: v for k, v in rapport.items() if k != "ecartees"},
        "fenetres_ecrites": n,
        "ecartees_du_decoupage": [
            {"horodatage": f.horodatage, "couverture_s": round(f.couverture_s, 2),
             "notes": len(f.notes), "raison": raison}
            for f, raison in rapport.get("ecartees", [])
        ],
        "ecarts_au_papier": [
            "Composante 3 du vecteur de file (débit publié) : le compteur "
            "rabbitmq_queue_messages_published_total n'existe pas sur RabbitMQ 3.8. "
            "Elle est calculée à partir des notes de dépôt, symétriquement à la "
            "composante 4 que le papier reconstruit déjà à partir des notes de retrait.",
            "L'opérateur inc somme les hausses entre relevés consécutifs au lieu de "
            "faire dernière moins première : un compteur remis à zéro par un "
            "redémarrage produirait sinon un débit négatif.",
            "Un message retiré produit deux notes identiques ; elles sont "
            "dédoublonnées, sans quoi le débit consommé serait doublé.",
            "SIGNALÉ, NON CORRIGÉ : la composante 4 du vecteur d'instance et la "
            "composante 1 de la relation de consommation sont la même quantité. "
            "Elle figure donc deux fois dans la représentation.",
        ],
        "a_faire_avant_apprentissage": [
            "Traiter les valeurs manquantes (écrites null, jamais 0).",
            "Mettre à l'échelle : les ordres de grandeur vont de 1e-2 à 1e8. "
            "Caler la mise à l'échelle sur la campagne saine SEULEMENT.",
            "Aucun encodage one-hot n'est requis : le graphe est hétérogène et "
            "aucune composante n'est catégorielle.",
        ],
    }


def ecrire(source: Path, sortie: Path, args) -> int:
    notes, releves = charger(source)
    print(f"chargé : {len(notes)} notes · {len(releves)} relevés")
    pas = args.pas if args.pas is not None else args.largeur
    fenetres, rapport = decouper(notes, releves, args.largeur, pas)
    print(f"fenêtres retenues : {rapport['gardees']}")
    if not fenetres:
        print("rien à écrire.")
        return 1

    vecteurs = calculer(fenetres, args.espace, args.largeur, args.horizon,
                        args.echantillon)
    sortie.mkdir(parents=True, exist_ok=True)

    suite = []
    for i, (f, vecs) in enumerate(zip(fenetres, vecteurs), 1):
        ronds = {cle: v.rond for cle, v in vecs.items()}
        fl, rap_fl = fleches_de(f, ronds, args.largeur, args.echantillon)
        cliche = batir(f, vecs, fl, rap_fl)
        (sortie / f"fenetre_{i:04d}.json").write_text(
            json.dumps(cliche, ensure_ascii=False, indent=1), encoding="utf-8")
        suite.append(cliche)

    (sortie / "manifeste.json").write_text(
        json.dumps(manifeste(source, sortie, args, rapport, len(suite), suite),
                   ensure_ascii=False, indent=2), encoding="utf-8")

    # ------------------------------------------------------------ résumé
    def t(x):
        print(f"\n{x}\n" + "─" * len(x))

    t(f"ÉCRIT DANS {sortie}")
    octets = sum(p.stat().st_size for p in sortie.glob("*.json"))
    print(f"  {len(suite)} fenêtres + 1 manifeste · {octets/1024:.0f} Ko")

    t("CE QUE CONTIENT CHAQUE CLICHÉ")
    print(f"  {'fenêtre':>8} │" + "".join(f"{g:>9}" for g in GENRES_RONDS)
          + " │" + "".join(f"{g:>12}" for g in GENRES_FLECHES) + " │  résol.")
    print("  " + "─" * 8 + "┼" + "─" * 27 + "┼" + "─" * 49 + "┼" + "─" * 8)
    for c in suite:
        r = c["resolution_appels"]
        fin_ligne = f" │ {100*r:5.1f} %" if r is not None else " │       —"
        print(f"  {c['fenetre']['horodatage_utc']:>8} │"
              + "".join(f"{len(c['ronds'][g]['cles']):9d}" for g in GENRES_RONDS)
              + " │"
              + "".join(f"{len(c['fleches'][g]['de']):12d}" for g in GENRES_FLECHES)
              + fin_ligne)

    t("FORME DES MATRICES, dernier cliché")
    c = suite[-1]
    for g in GENRES_RONDS:
        b = c["ronds"][g]
        print(f"  X_{g:<9} {len(b['X']):3d} × {len(b['colonnes']):2d}")
    for g, b in c["fleches"].items():
        print(f"  E_{g:<9} {len(b['de']):3d} flèches × {len(b['colonnes']):2d} nombres"
              f"   ({b['de_type']} → {b['vers_type']})")

    manquants = 0
    total = 0
    for c in suite:
        for g in GENRES_RONDS:
            for ligne in c["ronds"][g]["X"]:
                total += len(ligne)
                manquants += sum(1 for v in ligne if v is None)
    t("VALEURS MANQUANTES")
    print(f"  {manquants} sur {total} nombres de ronds ({100*manquants/total:.1f} %)")
    print("  Écrites `null`, jamais 0 : un débit nul est une information, un débit")
    print("  inconnu n'en est pas une. À traiter avant tout apprentissage.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dossier")
    p.add_argument("--sortie", default=None,
                   help="où écrire (défaut : graphes/<nom du dossier source>)")
    p.add_argument("--largeur", type=float, default=60)
    p.add_argument("--pas", type=float, default=None)
    p.add_argument("--espace", default=None)
    p.add_argument("--horizon", type=int, default=3)
    p.add_argument("--echantillon", type=float, default=1.0)
    args = p.parse_args()

    source = Path(args.dossier)
    if not source.is_dir():
        sys.exit(f"dossier introuvable : {source}")
    sortie = Path(args.sortie) if args.sortie else RACINE / "graphes" / source.name
    return ecrire(source, sortie, args)


if __name__ == "__main__":
    raise SystemExit(main())
