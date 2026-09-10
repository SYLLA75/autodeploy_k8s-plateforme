#!/usr/bin/env python3
"""
Dessiner une fenêtre du graphe.

    python3 dessiner.py graphes/2026-09-09_1505-1514
    python3 dessiner.py graphes/2026-09-09_1505-1514 --fenetre 1
    python3 dessiner.py graphes/2026-09-09_1505-1514 --file food_delivery

Brique facultative. Elle ne produit aucune donnée : elle relit les fichiers
écrits par graphe.py et en fait une image.

TROIS BANDES, de bas en haut :

    machines      les machines du cluster
    copies        les copies de service
    files         les files d'attente

C'est la disposition qui rend la structure lisible : on voit d'un coup quelle
copie tourne sur quelle machine, et quelles copies touchent quelle file.

LA DISPOSITION EST FIXE, calculée à partir des noms, sans aucun tirage au sort.
Deux exécutions donnent donc exactement la même image, et deux fenêtres
successives sont superposables — sans quoi on croirait voir bouger le système
alors que seul le dessin aurait changé.

--file restreint au voisinage d'une file : la file, les copies qui y déposent ou
y retirent, et leurs machines. C'est la vue utile pour une figure d'article, le
graphe entier étant trop dense pour être lu.

OÙ METTRE DU TEXTE, OÙ METTRE DU VISUEL

    files       2 ronds        du texte : débits, écart, niveau
    machines    5 à 7 ronds    du texte court : trois nombres
    copies      41 à 56 ronds  aucun texte, un remplissage

Écrire un nombre sous chacune des 41 copies rendrait la figure illisible. Leur
valeur passe donc par le noircissement du rond. --valeur-copie et
--valeur-machine choisissent laquelle des composantes est représentée ; tous les
noms de colonnes sont acceptés.

NIVEAUX DE GRIS ET NON COULEURS. La figure reste lisible imprimée en noir et
blanc, et le seul accent coloré est réservé à la file — c'est elle qu'on regarde.

L'ÉCHELLE DE GRIS EST CALCULÉE SUR TOUTE LA CAMPAGNE, pas sur la fenêtre
dessinée. Sans cela deux fenêtres auraient chacune leur propre échelle et une
copie inchangée changerait de teinte d'une image à l'autre — on croirait voir
une évolution qui n'existe pas. C'est le même raisonnement que pour la
disposition fixe.

UN ROND À CONTOUR POINTILLÉ n'a pas la valeur à zéro : il ne l'a pas du tout.
Un débit inconnu et un débit nul ne se ressemblent pas.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                                  # noqa: E402
from matplotlib.lines import Line2D                              # noqa: E402
from matplotlib.patches import FancyArrowPatch                    # noqa: E402

# Gris sobres, un seul accent pour la file — c'est elle qu'on regarde.
GRIS_TRAIT = "#9a9a9a"
GRIS_PALE = "#d8d8d8"
NOIR = "#1a1a1a"
ACCENT = "#c2410c"
Y = {"machine": 0.0, "copie": 1.0, "file": 2.25}


def _positions(cliche: dict, retenus: dict[str, set[int]]) -> dict:
    """
    Une position par rond, calculée et non tirée au sort.

    Les copies sont rangées par machine puis par nom : les traits « tourne sur »
    se regroupent au lieu de se croiser, et l'appartenance saute aux yeux.

    Une file se place au-dessus des copies qu'elle touche, et non à un rang
    arbitraire : sans cela ses deux flèches traversent toute la figure et on ne
    lit plus rien.
    """
    pos = {}
    for genre in ("machine", "copie"):
        b = cliche["ronds"][genre]
        idx = sorted(retenus[genre])
        if genre == "copie":
            idx.sort(key=lambda i: (b["machines"][i] or "", b["noms"][i]))
        n = len(idx)
        for rang, i in enumerate(idx):
            pos[(genre, i)] = (0.5 if n == 1 else rang / (n - 1), Y[genre])

    voisins: dict[int, list[float]] = {}
    for genre, cote_file, cote_copie in (("deposer", "vers", "de"),
                                         ("retirer", "de", "vers")):
        b = cliche["fleches"][genre]
        for k in range(len(b["de"])):
            i_f, i_c = b[cote_file][k], b[cote_copie][k]
            if ("copie", i_c) in pos:
                voisins.setdefault(i_f, []).append(pos[("copie", i_c)][0])

    idx = sorted(retenus["file"])
    libres = [i for i in idx if i not in voisins]
    for rang, i in enumerate(idx):
        if i in voisins:
            x = sum(voisins[i]) / len(voisins[i])
        else:
            r = libres.index(i)
            x = 0.5 if len(libres) == 1 else r / (len(libres) - 1)
        pos[("file", i)] = (min(0.97, max(0.03, x)), Y["file"])
    return pos


def bornes_campagne(cliches: list[dict], colonnes: dict[str, str]) -> dict:
    """
    Le plus petit et le plus grand de chaque valeur représentée, sur TOUTE la
    campagne. Deux fenêtres partagent ainsi la même échelle de gris et
    deviennent comparables à l'oeil.
    """
    bornes = {}
    for genre, nom in colonnes.items():
        noms = cliches[0]["ronds"][genre]["colonnes"]
        if nom not in noms:
            bornes[genre] = None
            continue
        j = noms.index(nom)
        vues = [ligne[j] for c in cliches for ligne in c["ronds"][genre]["X"]
                if ligne[j] is not None]
        bornes[genre] = (min(vues), max(vues)) if vues else None
    return bornes


def _gris(valeur, borne):
    """Du blanc au gris foncé. Rend None si la valeur est absente."""
    if valeur is None or borne is None:
        return None
    bas, haut = borne
    if haut <= bas:
        return 0.12
    return 0.06 + 0.62 * (valeur - bas) / (haut - bas)


def _lisible(x: float | None, unite: str = "") -> str:
    if x is None:
        return "?"
    if unite == "o":
        for u, seuil in (("G", 1e9), ("M", 1e6), ("k", 1e3)):
            if abs(x) >= seuil:
                return f"{x/seuil:.1f}{u}"
        return f"{x:.0f}"
    if unite == "%":
        return f"{100*x:.1f}%"
    if abs(x) >= 100 or (x and abs(x) < 0.01):
        return f"{x:.2g}"
    return f"{x:.3g}"


def _fleche(ax, a, b, couleur, epaisseur, courbure=0.0, style="-", alpha=1.0,
            tete=True):
    ax.add_patch(FancyArrowPatch(
        a, b, connectionstyle=f"arc3,rad={courbure}",
        arrowstyle="-|>" if tete else "-",
        mutation_scale=11 if tete else 1,
        linewidth=epaisseur, linestyle=style, color=couleur, alpha=alpha,
        shrinkA=9, shrinkB=11, zorder=1))


def _voisinage(cliche: dict, nom_file: str) -> dict[str, set[int]]:
    """La file, les copies qui la touchent, et leurs machines."""
    bf = cliche["ronds"]["file"]
    if nom_file not in bf["noms"]:
        sys.exit(f"file « {nom_file} » absente de cette fenêtre. "
                 f"Présentes : {', '.join(bf['noms']) or 'aucune'}")
    i_file = bf["noms"].index(nom_file)
    copies = set()
    for genre, sens in (("deposer", "de"), ("retirer", "vers")):
        b = cliche["fleches"][genre]
        autre = "vers" if sens == "de" else "de"
        for k in range(len(b["de"])):
            if b[autre][k] == i_file:
                copies.add(b[sens][k])
    bc = cliche["ronds"]["copie"]
    machines = set()
    bm = cliche["ronds"]["machine"]
    for i in copies:
        m = bc["machines"][i]
        if m in bm["noms"]:
            machines.add(bm["noms"].index(m))
    return {"file": {i_file}, "copie": copies, "machine": machines}


def dessiner(cliche: dict, sortie: Path, nom_file: str | None,
             valeurs: dict[str, str], bornes: dict, titre_sup: str = "") -> Path:
    if nom_file:
        retenus = _voisinage(cliche, nom_file)
    else:
        retenus = {g: set(range(len(cliche["ronds"][g]["cles"])))
                   for g in ("machine", "copie", "file")}

    pos = _positions(cliche, retenus)
    n_copies = len(retenus["copie"])
    large = max(9.0, min(26.0, 0.42 * n_copies + 5))
    fig, ax = plt.subplots(figsize=(large, 6.4))

    def dedans(genre, i):
        return (genre, i) in pos

    # ---- flèches, du plus discret au plus visible
    b = cliche["fleches"]["tourner_sur"]
    for k in range(len(b["de"])):
        i, j = b["de"][k], b["vers"][k]
        if dedans("copie", i) and dedans("machine", j):
            _fleche(ax, pos[("copie", i)], pos[("machine", j)], GRIS_PALE, 0.7,
                    style=(0, (1, 2)), tete=False)

    b = cliche["fleches"]["appeler"]
    debits = [x[0] or 0 for x in b["X"]] or [1]
    dmax = max(debits) or 1
    for k in range(len(b["de"])):
        i, j = b["de"][k], b["vers"][k]
        if dedans("copie", i) and dedans("copie", j):
            _fleche(ax, pos[("copie", i)], pos[("copie", j)], GRIS_TRAIT,
                    0.6 + 1.8 * (debits[k] / dmax), courbure=0.16, alpha=0.75)

    for genre, gd, gv in (("deposer", "copie", "file"), ("retirer", "file", "copie")):
        b = cliche["fleches"][genre]
        for k in range(len(b["de"])):
            i, j = b["de"][k], b["vers"][k]
            if dedans(gd, i) and dedans(gv, j):
                _fleche(ax, pos[(gd, i)], pos[(gv, j)], ACCENT, 1.9)

    # ---- ronds
    col = {g: cliche["ronds"][g]["colonnes"] for g in ("copie", "file", "machine")}
    idx = {g: (col[g].index(valeurs[g]) if valeurs[g] in col[g] else None)
           for g in ("copie", "machine")}

    for (genre, i), (x, y) in pos.items():
        b = cliche["ronds"][genre]
        nom = b["noms"][i]
        ligne = b["X"][i]

        if genre == "machine":
            v = ligne[idx["machine"]] if idx["machine"] is not None else None
            g = _gris(v, bornes.get("machine"))
            ax.scatter([x], [y], s=420, marker="s",
                       facecolor="white" if g is None else str(1 - g),
                       edgecolor=NOIR, linewidth=1.1,
                       linestyle="--" if g is None else "-", zorder=3)
            def prendre(nomcol):
                return ligne[col["machine"].index(nomcol)] if nomcol in col["machine"] else None
            detail = (f"cpu {_lisible(prendre('occupation_cpu'), '%')}"
                      f"   mem {_lisible(prendre('memoire_dispo_min'), 'o')}"
                      f"\nattente cpu {_lisible(prendre('attente_cpu'))}")
            ax.text(x, y - 0.17, f"{nom}\n{detail}", ha="center", va="top",
                    fontsize=7.8, color=NOIR, linespacing=1.5)

        elif genre == "file":
            niveau = ligne[0]
            ax.scatter([x], [y], s=min(620 + 90 * (niveau or 0), 2600),
                       facecolor="white", edgecolor=ACCENT, linewidth=2.0,
                       linestyle="-" if niveau is not None else "--", zorder=3)
            detail = ""
            if ligne[2] is not None and ligne[3] is not None:
                detail = (f"\nentre {ligne[2]:.2f}/s   sort {ligne[3]:.2f}/s"
                          f"\necart {ligne[4]:+.2f}/s")
            detail += f"\nen attente {_lisible(niveau)}"
            if ligne[5] is not None:
                detail += f"   {ligne[5]:.0f} consommateur(s)"
            ax.text(x, y + 0.22, nom + detail, ha="center", va="bottom",
                    fontsize=9, color=ACCENT, linespacing=1.5)

        else:
            v = ligne[idx["copie"]] if idx["copie"] is not None else None
            g = _gris(v, bornes.get("copie"))
            ax.scatter([x], [y], s=165,
                       facecolor="white" if g is None else str(1 - g),
                       edgecolor=NOIR, linewidth=0.9,
                       linestyle="--" if g is None else "-", zorder=3)
            court = nom.rsplit("-", 2)[0] if nom.count("-") >= 3 else nom
            court = court.replace("ts-", "").replace("-service", "")
            ax.text(x, y - 0.09, court, ha="right", va="top", fontsize=7.2,
                    rotation=42, rotation_mode="anchor", color=NOIR)

    # échelle de gris, en bas à gauche
    bc = bornes.get("copie")
    if bc:
        x0, larg, yb = 0.02, 0.13, -0.86
        for k in range(24):
            ax.add_patch(plt.Rectangle((x0 + k * larg / 24, yb),
                                       larg / 24, 0.075,
                                       facecolor=str(1 - (0.06 + 0.62 * k / 23)),
                                       edgecolor="none", zorder=2))
        ax.add_patch(plt.Rectangle((x0, yb), larg, 0.075, fill=False,
                                   edgecolor=GRIS_TRAIT, linewidth=0.6, zorder=3))
        ax.text(x0, yb - 0.03, _lisible(bc[0]), fontsize=7, ha="left", va="top",
                color=GRIS_TRAIT)
        ax.text(x0 + larg, yb - 0.03, _lisible(bc[1]), fontsize=7, ha="right",
                va="top", color=GRIS_TRAIT)
        ax.text(x0, yb + 0.10, f"remplissage des copies : {valeurs['copie']}",
                fontsize=7.5, ha="left", va="bottom", color=NOIR)

    f = cliche["fenetre"]
    titre = f"{f['horodatage_utc']} UTC   ·   fenêtre de {f['duree_s']:.0f} s"
    if nom_file:
        titre += f"   ·   voisinage de la file {nom_file}"
    if titre_sup:
        titre += f"   ·   {titre_sup}"
    ax.set_title(titre, fontsize=11, color=NOIR, pad=16, loc="left")

    ax.legend(handles=[
        Line2D([], [], color=ACCENT, lw=1.9, label="déposer / retirer"),
        Line2D([], [], color=GRIS_TRAIT, lw=1.4, label="appeler (épaisseur = débit)"),
        Line2D([], [], color=GRIS_PALE, lw=1.0, ls=(0, (1, 2)), label="tourne sur"),
        Line2D([], [], color=NOIR, lw=0, marker="o", markerfacecolor="white",
               markeredgecolor=NOIR, markeredgewidth=0.9, ls="--",
               label="contour pointillé : valeur absente"),
    ], loc="lower right", frameon=False, fontsize=8.5, ncol=4,
        bbox_to_anchor=(1.0, -0.16))

    ax.set_xlim(-0.06, 1.06)
    ax.set_ylim(-1.10, 3.05)
    ax.axis("off")
    ax.text(-0.055, Y["machine"], "machines", fontsize=8, color=GRIS_TRAIT,
            va="center", ha="right", rotation=90)
    ax.text(-0.055, Y["copie"], "copies", fontsize=8, color=GRIS_TRAIT,
            va="center", ha="right", rotation=90)
    ax.text(-0.055, Y["file"], "files", fontsize=8, color=ACCENT,
            va="center", ha="right", rotation=90)

    fig.tight_layout()
    fig.savefig(sortie, dpi=170, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return sortie


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dossier", help="dossier écrit par graphe.py")
    p.add_argument("--fenetre", type=int, default=None,
                   help="numéro de fenêtre (défaut : la première qui a du trafic de file)")
    p.add_argument("--file", default=None,
                   help="ne dessiner que le voisinage de cette file")
    p.add_argument("--sortie", default=None)
    p.add_argument("--valeur-copie", default="debit_cpu",
                   help="composante représentée par le remplissage des copies")
    p.add_argument("--valeur-machine", default="occupation_cpu",
                   help="composante représentée par le remplissage des machines")
    args = p.parse_args()

    d = Path(args.dossier)
    fichiers = sorted(d.glob("fenetre_*.json"))
    if not fichiers:
        sys.exit(f"aucun cliché dans {d}")

    if args.fenetre:
        choix = d / f"fenetre_{args.fenetre:04d}.json"
        if not choix.exists():
            sys.exit(f"{choix.name} n'existe pas (1 à {len(fichiers)})")
    else:
        choix = next((f for f in fichiers
                      if json.loads(f.read_text())["fleches"]["deposer"]["de"]),
                     fichiers[0])

    cliche = json.loads(choix.read_text())
    valeurs = {"copie": args.valeur_copie, "machine": args.valeur_machine}
    for genre, nom in valeurs.items():
        dispo = cliche["ronds"][genre]["colonnes"]
        if nom not in dispo:
            sys.exit(f"« {nom} » n'est pas une composante de {genre}.\n"
                     f"  disponibles : {', '.join(dispo)}")
    tous = [json.loads(f.read_text()) for f in fichiers]
    bornes = bornes_campagne(tous, valeurs)

    suffixe = f"_{args.file}" if args.file else ""
    sortie = Path(args.sortie) if args.sortie else d / f"{choix.stem}{suffixe}.png"
    chemin = dessiner(cliche, sortie, args.file, valeurs, bornes)

    f = cliche["fenetre"]
    print(f"cliché  : {choix.name}   ({f['horodatage_utc']} UTC)")
    print(f"ronds   : " + " · ".join(
        f"{len(cliche['ronds'][g]['cles'])} {g}" for g in ("copie", "file", "machine")))
    print(f"flèches : " + " · ".join(
        f"{len(b['de'])} {g}" for g, b in cliche["fleches"].items()))
    for genre in ("copie", "machine"):
        b = bornes.get(genre)
        etendue = f"{b[0]:.4g} → {b[1]:.4g}" if b else "aucune valeur"
        print(f"gris {genre:<8}: {valeurs[genre]}   ({etendue}, sur toute la campagne)")
    print(f"image   : {chemin}  ({chemin.stat().st_size/1024:.0f} Ko)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
