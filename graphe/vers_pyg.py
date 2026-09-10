#!/usr/bin/env python3
"""
Traduire les clichés en objets PyTorch Geometric.

    python3 vers_pyg.py graphes/2026-09-09_1505-1514
    python3 vers_pyg.py graphes/saine     --ecrire-echelle echelle.json
    python3 vers_pyg.py graphes/en_panne  --echelle echelle.json

Brique facultative. Elle ne produit aucune donnée nouvelle : elle relit les
fichiers de graphe.py et les met dans la forme qu'attend la bibliothèque.

    ronds.copie.X        →  data['copie'].x                       tenseur
    fleches.deposer.de   →  data['copie','deposer','file'].edge_index
    fleches.deposer.X    →  data['copie','deposer','file'].edge_attr

TROIS CHOSES QUE LA CONVERSION DOIT TRANCHER, et qui sont des choix de méthode,
pas de la plomberie. Chacune est un réglage, aucune n'est imposée en silence.

1. LES VALEURS MANQUANTES. Le fichier écrit `null`. Un tenseur ne connaît pas
   l'absence. Trois conduites possibles :

       masque   remplace par 0 ET ajoute un tenseur booléen qui dit où était le
                trou. Le modèle peut alors apprendre à s'en méfier.  (défaut)
       moyenne  remplace par la moyenne de la colonne sur la campagne
       zero     remplace par 0, sans rien dire

   `zero` est le plus dangereux : un débit inconnu deviendrait un débit nul,
   c'est-à-dire une panne inventée.

2. LA MISE À L'ÉCHELLE. Les ordres de grandeur vont de 1e-2 à 1e8 ; sans
   correction la mémoire écrase tout le reste.

   PIÈGE MÉTHODOLOGIQUE. Il faut calculer moyennes et écarts-types sur la
   CAMPAGNE SAINE seulement, puis appliquer les mêmes nombres à la campagne en
   panne. Les calculer sur les deux ferait entrer l'anomalie dans la
   normalisation, qui la gommerait en partie — et les résultats seraient faux
   sans que rien ne le signale. D'où les deux options séparées
   --ecrire-echelle et --echelle.

3. LE LOGARITHME. Les durées, la mémoire et les octets s'étalent sur plusieurs
   ordres de grandeur avec une queue épaisse. On leur applique log(1+x) avant
   de standardiser. Les colonnes concernées sont nommées ci-dessous, pas
   devinées.

PROCESSEUR OU CARTE GRAPHIQUE. --appareil cpu|cuda|auto choisit où les tenseurs
sont construits. Mais LE FICHIER ÉCRIT CONTIENT TOUJOURS DES TENSEURS DE
PROCESSEUR, et c'est délibéré : un fichier contenant des tenseurs de carte
graphique ne se relit que sur une machine qui a une carte, et parfois seulement
avec la même version de CUDA. Ce serait exactement l'inverse de ce qu'on cherche.

L'appareil appartient à la boucle d'entraînement, pas au jeu de données. On
déplace au chargement :

    suite = torch.load('pyg.pt', weights_only=False)
    suite = [d.to('cuda') for d in suite]

--garder-appareil force l'écriture sur l'appareil choisi, en connaissance de
cause.

L'installation faite ici est la version processeur seul, qui ne peut pas voir de
carte graphique même s'il y en a une. Pour une machine équipée :

    pip uninstall torch
    pip install torch --index-url https://download.pytorch.org/whl/cu124

Le script écrit un fichier environnement.json à côté du .pt : versions, appareil,
présence de CUDA. Sans ce relevé, un résultat n'est pas refaisable.

SENS DES FLÈCHES. Les flèches sont écrites dans le sens des données : une copie
dépose VERS une file, une copie tourne SUR une machine. Pour qu'un rond reçoive
de l'information de ses voisins dans les deux sens, un modèle a souvent besoin
des flèches inverses : --symetriser les ajoute, sous des noms préfixés par
« inv_ ». Non fait par défaut, parce que c'est un choix de modèle.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent

GENRES_RONDS = ("copie", "file", "machine")
LIENS = {
    "appeler":     ("copie", "copie"),
    "deposer":     ("copie", "file"),
    "retirer":     ("file", "copie"),
    "tourner_sur": ("copie", "machine"),
}

# Colonnes à queue épaisse, toujours positives : on passe au log(1+x).
# Nommées et non devinées, pour qu'un relecteur puisse contester la liste.
COLONNES_LOG = {
    "copie": ["duree_traitement_q50", "duree_traitement_q95", "duree_traitement_q99",
              "duree_requete_q50", "duree_requete_q95", "duree_requete_q99",
              "memoire_finale", "memoire_limite", "quota_cpu", "octets_recus"],
    "file": ["niveau"],
    "machine": ["memoire_dispo_min"],
}


def _charger(dossier: Path) -> tuple[list[dict], dict]:
    fichiers = sorted(dossier.glob("fenetre_*.json"))
    if not fichiers:
        sys.exit(f"aucun cliché dans {dossier}")
    manif = dossier / "manifeste.json"
    return ([json.loads(f.read_text()) for f in fichiers],
            json.loads(manif.read_text()) if manif.exists() else {})


# -------------------------------------------------------------- mise à l'échelle
def calculer_echelle(cliches: list[dict]) -> dict:
    """Moyenne et écart-type par colonne, les absences ignorées."""
    echelle = {}
    for genre in GENRES_RONDS:
        colonnes = cliches[0]["ronds"][genre]["colonnes"]
        log = set(COLONNES_LOG.get(genre, []))
        stats = []
        for j, nom in enumerate(colonnes):
            vues = []
            for c in cliches:
                for ligne in c["ronds"][genre]["X"]:
                    v = ligne[j]
                    if v is None:
                        continue
                    if nom in log:
                        v = math.log1p(max(0.0, v))
                    vues.append(v)
            if vues:
                m = sum(vues) / len(vues)
                var = sum((x - m) ** 2 for x in vues) / len(vues)
                e = math.sqrt(var)
            else:
                m, e = 0.0, 1.0
            stats.append({"colonne": nom, "moyenne": m,
                          "ecart_type": e if e > 1e-12 else 1.0,
                          "log": nom in log, "observations": len(vues)})
        echelle[genre] = stats
    return echelle


def _appliquer(ligne: list, stats: list[dict] | None, colonnes: list[str],
               genre: str) -> tuple[list[float], list[bool]]:
    """Rend la ligne transformée et le masque des valeurs présentes."""
    log = set(COLONNES_LOG.get(genre, []))
    sortie, presents = [], []
    for j, v in enumerate(ligne):
        presents.append(v is not None)
        if v is None:
            sortie.append(None)
            continue
        x = float(v)
        if colonnes[j] in log:
            x = math.log1p(max(0.0, x))
        if stats:
            s = stats[j]
            x = (x - s["moyenne"]) / s["ecart_type"]
        sortie.append(x)
    return sortie, presents


def choisir_appareil(demande: str) -> str:
    """
    Rend l'appareil réellement utilisable, jamais celui demandé aveuglément.

    Demander « cuda » sur une installation processeur seul échouerait à la
    première opération, très loin d'ici. On le dit tout de suite.
    """
    import torch
    dispo = torch.cuda.is_available()
    if demande == "auto":
        return "cuda" if dispo else "cpu"
    if demande == "cuda" and not dispo:
        sys.exit("--appareil cuda demandé, mais aucune carte graphique n'est "
                 "utilisable.\n"
                 f"  torch installé : {torch.__version__}\n"
                 "  la version « +cpu » ne voit jamais de carte. Pour en avoir une :\n"
                 "    pip uninstall torch\n"
                 "    pip install torch --index-url "
                 "https://download.pytorch.org/whl/cu124")
    return demande


def releve_environnement(appareil: str) -> dict:
    """Ce qu'il faut noter pour qu'un résultat soit refaisable."""
    import platform
    import torch
    import torch_geometric
    return {
        "python": platform.python_version(),
        "systeme": f"{platform.system()} {platform.release()}",
        "torch": torch.__version__,
        "torch_geometric": torch_geometric.__version__,
        "cuda_compile_dans_torch": torch.version.cuda,
        "cuda_utilisable": torch.cuda.is_available(),
        "cartes": [torch.cuda.get_device_name(i)
                   for i in range(torch.cuda.device_count())],
        "appareil_employe": appareil,
        "graine": None,
        "remarque": "La conversion ne comporte aucun tirage au sort : "
                    "elle donne le même résultat sur processeur et sur carte.",
    }


def convertir(cliches: list[dict], echelle: dict | None, manquant: str,
              symetriser: bool, appareil: str = "cpu"):
    import torch
    from torch_geometric.data import HeteroData

    # moyennes de remplacement, calculées après transformation
    moyennes = {}
    if manquant == "moyenne":
        for genre in GENRES_RONDS:
            colonnes = cliches[0]["ronds"][genre]["colonnes"]
            stats = echelle.get(genre) if echelle else None
            acc = [[] for _ in colonnes]
            for c in cliches:
                for ligne in c["ronds"][genre]["X"]:
                    vals, _ = _appliquer(ligne, stats, colonnes, genre)
                    for j, v in enumerate(vals):
                        if v is not None:
                            acc[j].append(v)
            moyennes[genre] = [sum(a) / len(a) if a else 0.0 for a in acc]

    suite = []
    for c in cliches:
        data = HeteroData()
        for genre in GENRES_RONDS:
            b = c["ronds"][genre]
            colonnes = b["colonnes"]
            stats = echelle.get(genre) if echelle else None
            lignes, masques = [], []
            for ligne in b["X"]:
                vals, presents = _appliquer(ligne, stats, colonnes, genre)
                bouche = moyennes.get(genre) if manquant == "moyenne" else None
                vals = [(bouche[j] if bouche else 0.0) if v is None else v
                        for j, v in enumerate(vals)]
                lignes.append(vals)
                masques.append(presents)
            data[genre].x = torch.tensor(lignes, dtype=torch.float32).reshape(
                len(b["X"]), len(colonnes)).to(appareil)
            data[genre].num_nodes = len(b["cles"])
            data[genre].cles = b["cles"]
            data[genre].noms = b["noms"]
            data[genre].colonnes = colonnes
            if manquant == "masque":
                data[genre].present = torch.tensor(
                    masques, dtype=torch.bool).reshape(
                    len(b["X"]), len(colonnes)).to(appareil)

        for genre, (gd, gv) in LIENS.items():
            b = c["fleches"][genre]
            ei = torch.tensor([b["de"], b["vers"]],
                              dtype=torch.long).reshape(2, -1).to(appareil)
            ea = torch.tensor([[0.0 if v is None else float(v) for v in x]
                               for x in b["X"]],
                              dtype=torch.float32).reshape(
                len(b["X"]), len(b["colonnes"])).to(appareil)
            data[gd, genre, gv].edge_index = ei
            data[gd, genre, gv].edge_attr = ea
            if symetriser:
                data[gv, f"inv_{genre}", gd].edge_index = ei.flip(0)
                data[gv, f"inv_{genre}", gd].edge_attr = ea

        data.horodatage = c["fenetre"]["horodatage_utc"]
        data.debut_ns = c["fenetre"]["debut_ns"]
        suite.append(data)
    return suite


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dossier", help="dossier écrit par graphe.py")
    p.add_argument("--sortie", default=None, help="fichier .pt à écrire")
    p.add_argument("--manquant", choices=("masque", "moyenne", "zero"),
                   default="masque")
    p.add_argument("--ecrire-echelle", default=None,
                   help="calculer la mise à l'échelle sur CETTE campagne et l'écrire")
    p.add_argument("--echelle", default=None,
                   help="appliquer une mise à l'échelle calculée ailleurs")
    p.add_argument("--symetriser", action="store_true",
                   help="ajouter les flèches inverses (inv_...)")
    p.add_argument("--appareil", choices=("cpu", "cuda", "auto"), default="cpu",
                   help="où construire les tenseurs (défaut cpu)")
    p.add_argument("--garder-appareil", action="store_true",
                   help="écrire le fichier sur l'appareil choisi au lieu de le "
                        "ramener sur le processeur — rend le fichier non portable")
    args = p.parse_args()

    d = Path(args.dossier)
    if not d.is_dir():
        sys.exit(f"dossier introuvable : {d}")
    cliches, manif = _charger(d)
    print(f"clichés : {len(cliches)}   ({d})")

    if args.ecrire_echelle and args.echelle:
        sys.exit("--ecrire-echelle et --echelle ne vont pas ensemble : soit on "
                 "calcule, soit on applique.")

    echelle = None
    if args.ecrire_echelle:
        echelle = calculer_echelle(cliches)
        Path(args.ecrire_echelle).write_text(
            json.dumps({"source": str(d), "echelle": echelle},
                       ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"échelle calculée sur cette campagne → {args.ecrire_echelle}")
        print("  À N'UTILISER que si cette campagne est la campagne SAINE.")
    elif args.echelle:
        charge = json.loads(Path(args.echelle).read_text())
        echelle = charge["echelle"]
        print(f"échelle appliquée, calculée sur : {charge.get('source')}")
    else:
        print("AUCUNE mise à l'échelle. Les grandeurs vont de 1e-2 à 1e8 : un")
        print("  modèle entraîné tel quel ne verra que la mémoire. Utilise")
        print("  --ecrire-echelle sur la campagne saine, puis --echelle ici.")

    appareil = choisir_appareil(args.appareil)
    env = releve_environnement(appareil)
    print(f"appareil : {appareil}" +
          (f"   ({', '.join(env['cartes'])})" if env["cartes"] else "") +
          ("" if env["cuda_utilisable"] else
           "   (torch installé en version processeur seul)"))

    suite = convertir(cliches, echelle, args.manquant, args.symetriser, appareil)

    def t(x):
        print(f"\n{x}\n" + "─" * len(x))

    import torch
    t("PREMIER CLICHÉ")
    d0 = suite[0]
    print(f"  horodatage : {d0.horodatage} UTC")
    for genre in GENRES_RONDS:
        s = tuple(d0[genre].x.shape)
        m = ""
        if args.manquant == "masque":
            manque = int((~d0[genre].present).sum())
            m = f"   ({manque} valeurs absentes, marquées dans .present)"
        print(f"  data['{genre}'].x            {s}{m}")
    for genre, (gd, gv) in LIENS.items():
        e = d0[gd, genre, gv]
        print(f"  data['{gd}','{genre}','{gv}']"
              f"   edge_index {tuple(e.edge_index.shape)}"
              f"   edge_attr {tuple(e.edge_attr.shape)}")

    t("CONTRÔLE")
    x = d0["copie"].x
    print(f"  X_copie : min {float(x.min()):+.3g} · max {float(x.max()):+.3g} · "
          f"moyenne {float(x.mean()):+.3g}")
    if echelle is None and float(x.abs().max()) > 1e4:
        print("  Écart d'échelle énorme, comme attendu sans normalisation.")
    print(f"  aucun NaN : {not bool(torch.isnan(x).any())}")
    print(f"  aucun infini : {not bool(torch.isinf(x).any())}")

    sortie = Path(args.sortie) if args.sortie else d / "pyg.pt"
    if appareil != "cpu" and not args.garder_appareil:
        suite = [x.to("cpu") for x in suite]
        print("\n  Tenseurs ramenés sur le processeur avant écriture : un fichier")
        print("  contenant des tenseurs de carte ne se relit que sur une machine")
        print("  équipée. --garder-appareil pour passer outre.")

    torch.save(suite, sortie)
    (sortie.parent / "environnement.json").write_text(
        json.dumps(env, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nécrit : {sortie}  ({sortie.stat().st_size/1024:.0f} Ko)")
    print(f"        {sortie.parent / 'environnement.json'}")
    print(f"\n  relecture :  suite = torch.load('{sortie}', weights_only=False)")
    print("  sur carte :  suite = [d.to('cuda') for d in suite]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
