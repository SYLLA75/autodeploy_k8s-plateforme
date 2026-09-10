#!/usr/bin/env python3
"""
Découper une plage rapatriée en une suite de fenêtres.

    python3 decoupage.py donnees/2026-09-09_1505-1514
    python3 decoupage.py donnees/2026-09-09_1505-1514 --largeur 30 --pas 30
    python3 decoupage.py donnees/2026-09-09_1505-1514 --largeur 60 --pas 20

POURQUOI DÉCOUPER. Un seul compte sur toute la plage ne montre rien : une file
qui déraille une minute sur dix se noie dans la moyenne. En comptant fenêtre par
fenêtre on voit QUAND ça dérape, ce qui est le but même du travail.

LARGEUR ET PAS.

    largeur   la durée que couvre une fenêtre
    pas       de combien on avance d'une fenêtre à la suivante

    pas = largeur    fenêtres bout à bout, aucun recouvrement
    pas < largeur    fenêtres qui se chevauchent — c'est ça, « glissant »

Une note peut alors appartenir à plusieurs fenêtres. C'est normal et voulu.

TROIS RÈGLES, décidées après mesure sur données réelles (voir OBSERVABILITE.md) :

  1. Une note est rangée d'après son DÉBUT, jamais sa fin. Aujourd'hui ça ne
     change rien (un retrait dure 5 ms). Sous panne, un consommateur ralenti
     produirait des retraits longs, et compter la fin décalerait la sortie dans
     une fenêtre ultérieure — masquant exactement l'anomalie recherchée.

  2. On ne garde que les fenêtres entièrement couvertes par les données. Les
     bords d'une plage téléchargée sont amputés : les fichiers sont rangés par
     minute d'export, pas par instant de l'événement. Une fenêtre qui ne dure que
     40 s au lieu de 60 donne des comptes plus petits sans que le trafic ait
     bougé — on la lirait comme une chute de trafic.

     Ce tri suffit. Il a d'abord été doublé d'une marge « une fenêtre de chaque
     côté par sécurité » ; la colonne « couvre » a montré que cette marge jetait
     deux fenêtres pleines (59 s sur 60) pour rien. Elle est donc à zéro par
     défaut. --bords N la rétablit si un jeu de données se révélait plus sale.

  3. Un message retiré compte une fois, pas deux — deux notes sont émises pour
     le même retrait. Voir lecture.messages_retires.

CE QUE CE MODULE NE FAIT PAS. Il ne construit ni ronds ni flèches. Il découpe, et
s'arrête là. La largeur et le pas ne sont PAS arrêtés scientifiquement : les
valeurs par défaut sont des repères de travail, à trancher par l'expérience.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lecture import (Note, Releve, lire_notes, lire_releves,  # noqa: E402
                     messages_deposes, messages_retires)

MILLIARD = 1_000_000_000


# ----------------------------------------------------------------- la fenêtre
@dataclass(slots=True)
class Fenetre:
    """Une tranche de temps, et tout ce qui s'y est passé."""
    indice: int                  # position sur la grille absolue
    debut_ns: int
    fin_ns: int                  # exclu
    notes: list[Note] = field(default_factory=list)
    releves: list[Releve] = field(default_factory=list)

    @property
    def duree_s(self) -> float:
        return (self.fin_ns - self.debut_ns) / 1e9

    @property
    def couverture_s(self) -> float:
        """
        Combien de secondes cette fenêtre contient VRAIMENT de données.

        Sert à contrôler les bords : une fenêtre amputée donne des comptes plus
        petits sans que le trafic ait bougé. Si ce nombre est nettement inférieur
        à la largeur, la fenêtre ment. Sur une plage à faible trafic il peut être
        un peu court sans que ce soit grave — c'est un indice, pas un verdict.
        """
        instants = [n.debut_ns for n in self.notes]
        instants += [r.instant_ns for r in self.releves if r.instant_ns]
        return (max(instants) - min(instants)) / 1e9 if instants else 0.0

    @property
    def horodatage(self) -> str:
        return datetime.fromtimestamp(self.debut_ns / 1e9,
                                      timezone.utc).strftime("%H:%M:%S")

    # -- raccourcis de lecture ---------------------------------------------
    @property
    def depots(self) -> list[Note]:
        return messages_deposes(self.notes)

    @property
    def retraits(self) -> list[Note]:
        return messages_retires(self.notes)

    def ecart(self, file: str | None = None) -> int:
        """
        Messages entrés moins messages sortis, pendant cette fenêtre.

        C'est un bilan de flux, pas un appariement : un message déposé ici et
        retiré trois fenêtres plus loin compte +1 ici et −1 là-bas. Les deux
        sont exacts — la file a bien grossi, puis bien maigri. Un écart négatif
        est donc parfaitement légitime.
        """
        d = [n for n in self.depots if file is None or n.nom_file == file]
        r = [n for n in self.retraits if file is None or n.nom_file == file]
        return len(d) - len(r)

    @property
    def files(self) -> list[str]:
        return sorted({n.nom_file for n in self.depots + self.retraits if n.nom_file})


# --------------------------------------------------------------- chargement
def charger(dossier: Path, avec_compteurs: bool = True
            ) -> tuple[list[Note], list[Releve]]:
    """
    Lit tous les fichiers d'un dossier rapatrié.

    ATTENTION À LA MÉMOIRE. Tout est gardé d'un bloc, parce que le découpage a
    besoin de revoir les mêmes données plusieurs fois quand les fenêtres se
    chevauchent. Dix minutes tiennent largement ; une journée entière ne
    tiendrait pas. Au-delà d'une heure, découper la plage en morceaux.
    """
    notes: list[Note] = []
    releves: list[Releve] = []
    fichiers = sorted(f for f in dossier.iterdir()
                      if f.is_file() and f.name != "origine.json")
    if not fichiers:
        sys.exit(f"aucun fichier de mesure dans {dossier}")

    for f in fichiers:
        tete = f.read_bytes()[:120]
        if b"resourceSpans" in tete:
            notes += lire_notes(f)
        elif b"resourceMetrics" in tete and avec_compteurs:
            releves += lire_releves(f)
    return [n for n in notes if n.debut_ns], releves


# ---------------------------------------------------------------- découpage
def _indices(instant_ns: int, largeur_ns: int, pas_ns: int) -> range:
    """
    Les fenêtres qui contiennent cet instant.

    La grille est ancrée sur l'origine des temps absolue, pas sur le début des
    données. Deux plages différentes découpées avec les mêmes réglages tombent
    donc sur exactement les mêmes frontières — c'est ce qui rend deux campagnes
    comparables entre elles.
    """
    dernier = instant_ns // pas_ns
    premier = (instant_ns - largeur_ns) // pas_ns + 1
    return range(premier, dernier + 1)


def decouper(notes: list[Note], releves: list[Releve],
             largeur_s: float, pas_s: float, bords: int = 0
             ) -> tuple[list[Fenetre], dict]:
    """
    Range chaque note et chaque relevé dans les fenêtres qui les contiennent.

    Rend les fenêtres retenues, et un compte rendu de ce qui a été écarté — pour
    qu'aucune donnée ne disparaisse en silence.
    """
    if pas_s <= 0 or largeur_s <= 0:
        sys.exit("largeur et pas doivent être positifs")
    if pas_s > largeur_s:
        sys.exit(f"pas ({pas_s} s) plus grand que la largeur ({largeur_s} s) : "
                 "il resterait des trous entre les fenêtres.")

    largeur_ns = int(largeur_s * MILLIARD)
    pas_ns = int(pas_s * MILLIARD)

    instants = [n.debut_ns for n in notes] + [r.instant_ns for r in releves if r.instant_ns]
    if not instants:
        return [], {"raison": "aucun instant exploitable"}
    d0, d1 = min(instants), max(instants)

    boites: dict[int, Fenetre] = {}

    def boite(k: int) -> Fenetre:
        f = boites.get(k)
        if f is None:
            f = boites[k] = Fenetre(indice=k, debut_ns=k * pas_ns,
                                    fin_ns=k * pas_ns + largeur_ns)
        return f

    for n in notes:
        for k in _indices(n.debut_ns, largeur_ns, pas_ns):
            boite(k).notes.append(n)
    for r in releves:
        if not r.instant_ns:
            continue
        for k in _indices(r.instant_ns, largeur_ns, pas_ns):
            boite(k).releves.append(r)

    toutes = [boites[k] for k in sorted(boites)]

    # règle 2 — d'abord la couverture, ensuite la marge de sécurité
    pleines = [f for f in toutes if f.debut_ns >= d0 and f.fin_ns <= d1]
    incompletes = len(toutes) - len(pleines)

    if bords > 0 and len(pleines) > 2 * bords:
        gardees = pleines[bords:-bords]
    elif bords > 0:
        gardees = []
    else:
        gardees = pleines

    # On garde les écartées pour les MONTRER. Sans ça, il faudrait croire sur
    # parole qu'elles ne contenaient rien d'intéressant — or c'est précisément
    # ce qu'il faut pouvoir vérifier : une anomalie jetée en silence ne se
    # rattrape jamais.
    sur_le_bord = set(id(f) for f in pleines)
    ecartees = [(f, "hors couverture des données") for f in toutes
                if id(f) not in sur_le_bord]
    gardees_ids = set(id(f) for f in gardees)
    ecartees += [(f, "marge --bords") for f in pleines if id(f) not in gardees_ids]
    ecartees.sort(key=lambda x: x[0].indice)

    rapport = {
        "fenetres_construites": len(toutes),
        "ecartees_incompletes": incompletes,
        "ecartees_marge": len(pleines) - len(gardees),
        "gardees": len(gardees),
        "ecartees": ecartees,
        "donnees_de": d0, "donnees_a": d1,
        "largeur_s": largeur_s, "pas_s": pas_s, "bords": bords,
    }
    return gardees, rapport


# ------------------------------------------------------------------ affichage
def _u(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1e9, timezone.utc).strftime("%H:%M:%S")


def montrer(fenetres: list[Fenetre], rapport: dict) -> None:
    def t(x):
        print(f"\n{x}\n" + "─" * len(x))

    t("RÉGLAGES")
    print(f"  largeur d'une fenêtre : {rapport['largeur_s']:g} s")
    print(f"  pas entre deux        : {rapport['pas_s']:g} s"
          + ("   (bout à bout, aucun recouvrement)"
             if rapport['pas_s'] == rapport['largeur_s']
             else f"   (glissant : chaque instant vu "
                  f"{rapport['largeur_s'] / rapport['pas_s']:.0f} fois)"))
    print(f"  données réelles       : {_u(rapport['donnees_de'])} → {_u(rapport['donnees_a'])}")
    print("\n  ATTENTION : largeur et pas sont des repères de travail, pas un")
    print("  choix arrêté. Ils devront être justifiés par l'expérience.")

    t("CE QUI A ÉTÉ ÉCARTÉ")
    print(f"  fenêtres construites          : {rapport['fenetres_construites']}")
    print(f"  écartées, pas assez couvertes : {rapport['ecartees_incompletes']}")
    print(f"  écartées, marge de sécurité   : {rapport['ecartees_marge']}")
    print(f"  GARDÉES                       : {rapport['gardees']}")
    print("\n  Seules les fenêtres des DEUX BOUTS peuvent être écartées : le tri")
    print("  compare chaque fenêtre aux extrémités des données. Une fenêtre du")
    print("  milieu est toujours gardée, même vide — un effondrement du trafic se")
    print("  voit, il ne disparaît pas.")

    ecartees = rapport.get("ecartees") or []
    if ecartees:
        print("\n  CE QU'ELLES CONTENAIENT — pour contrôle, ne pas les comparer aux autres :")
        print(f"    {'début':>8} │ {'couvre':>7} │ {'notes':>6} │ {'dép':>4} {'ret':>4} │ raison")
        for f, raison in ecartees:
            d, r = len(f.depots), len(f.retraits)
            alerte = "   ← REGARDE" if (d or r) and f.couverture_s < 0.5 * rapport["largeur_s"] else ""
            print(f"    {f.horodatage:>8} │ {f.couverture_s:5.1f} s │ {len(f.notes):6d} │"
                  f" {d:4d} {r:4d} │ {raison}{alerte}")
        print("\n    Si l'une de ces lignes montre du trafic, élargis la plage rapatriée")
        print("    d'une fenêtre de chaque côté et recommence : l'événement sera alors")
        print("    dans une fenêtre pleine, donc exploitable.")

    if not fenetres:
        print("\n  Aucune fenêtre exploitable. La plage est trop courte pour cette")
        print("  largeur, ou les bords ont tout mangé. Élargis la plage rapatriée,")
        print("  ou réduis --largeur.")
        return

    t("LES FENÊTRES")
    largeur = rapport["largeur_s"]
    print(f"  {'début':>8} │ {'couvre':>7} │ {'notes':>6} {'relevés':>8} │"
          f" {'copies':>6} {'mach':>4} │ {'dép':>4} {'ret':>4} {'écart':>6} │ files")
    print("  " + "─" * 8 + "┼" + "─" * 9 + "┼" + "─" * 16 + "┼" + "─" * 13
          + "┼" + "─" * 19 + "┼" + "─" * 20)
    for f in fenetres:
        copies = len({n.pod_uid for n in f.notes if n.pod_uid})
        mach = len({n.machine for n in f.notes if n.machine})
        d, r = len(f.depots), len(f.retraits)
        c = f.couverture_s
        drapeau = " !" if c < 0.9 * largeur else "  "
        print(f"  {f.horodatage:>8} │ {c:5.1f} s{drapeau}│ {len(f.notes):6d} {len(f.releves):8d} │"
              f" {copies:6d} {mach:4d} │ {d:4d} {r:4d} {d - r:+6d} │"
              f" {', '.join(f.files) if f.files else '—'}")
    print(f"\n  « ! » = la fenêtre couvre moins de 90 % de sa largeur : elle est amputée,")
    print(f"  ses comptes sont plus petits que la réalité. Ne pas la comparer aux autres.")

    t("PAR FILE")
    files = sorted({q for f in fenetres for q in f.files})
    if not files:
        print("  aucune messagerie sur cette plage.")
    else:
        for q in files:
            ecarts = [f.ecart(q) for f in fenetres]
            deps = sum(len([n for n in f.depots if n.nom_file == q]) for f in fenetres)
            rets = sum(len([n for n in f.retraits if n.nom_file == q]) for f in fenetres)
            print(f"\n  file « {q} »")
            print(f"    dépôts {deps} · retraits {rets} · écart total {deps - rets:+d}")
            print(f"    écart par fenêtre : min {min(ecarts):+d} · max {max(ecarts):+d}")
            suspectes = [f.horodatage for f in fenetres if abs(f.ecart(q)) > 0]
            if suspectes:
                print(f"    fenêtres à écart non nul : {', '.join(suspectes)}")
            else:
                print("    écart nul sur toutes les fenêtres — la file suit le rythme.")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dossier", help="dossier rapatrié par rapatrier.py")
    p.add_argument("--largeur", type=float, default=60,
                   help="durée d'une fenêtre, en secondes (défaut 60)")
    p.add_argument("--pas", type=float, default=None,
                   help="avance entre deux fenêtres, en secondes (défaut : = largeur)")
    p.add_argument("--bords", type=int, default=0,
                   help="fenêtres écartées de chaque côté EN PLUS du tri de "
                        "couverture (défaut 0 : le tri de couverture suffit, "
                        "vérifié par la colonne « couvre »)")
    p.add_argument("--sans-compteurs", action="store_true",
                   help="ignorer les fichiers de compteurs (plus rapide, moins de mémoire)")
    args = p.parse_args()

    dossier = Path(args.dossier)
    if not dossier.is_dir():
        sys.exit(f"dossier introuvable : {dossier}")
    pas = args.pas if args.pas is not None else args.largeur

    print(f"dossier : {dossier}")
    notes, releves = charger(dossier, avec_compteurs=not args.sans_compteurs)
    print(f"chargé  : {len(notes)} notes · {len(releves)} relevés")

    fenetres, rapport = decouper(notes, releves, args.largeur, pas, args.bords)
    montrer(fenetres, rapport)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
