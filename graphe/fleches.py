#!/usr/bin/env python3
"""
Les flèches du graphe : qui parle à qui, dans chaque fenêtre.

    python3 fleches.py donnees/2026-09-09_1505-1514 --espace train-ticket

Cinquième brique. Quatre sortes de flèches, avec les nombres qu'elles portent :

    appeler       copie  →  copie      5 nombres
    déposer       copie  →  file       1 nombre
    retirer       file   →  copie      1 nombre
    tourner sur   copie  →  machine    0 nombre — purement structurelle

COMMENT ON RETROUVE UN APPEL

Quand un service en appelle un autre, deux notes sont écrites, pas une :

    chez l'appelant   une note CLIENT   (genre 3)
    chez l'appelé     une note SERVEUR  (genre 2), dont le parent est la note CLIENT

On part donc des notes SERVEUR, on remonte au parent, et on regarde dans quelle
copie ce parent a été écrit. Si c'est une autre copie, on tient une flèche.

DEUX PIÈGES, tous deux mesurés et rapportés :

  1. Le parent peut être introuvable — sa note est tombée dans une autre fenêtre,
     ou dans un fichier qu'on n'a pas rapatrié. La proportion de parents
     retrouvés est le TAUX DE RÉSOLUTION du papier. Il est affiché : une flèche
     manquante fausse le graphe en silence, un taux affiché ne le peut pas.

  2. Le parent peut être dans LA MÊME copie. C'est un appel interne, pas une
     relation entre deux ronds. On l'écarte, et on le compte à part.

LA FLÈCHE « TOURNER SUR » NE PORTE RIEN. Elle n'est pas pour autant inutile :
c'est elle qui rend visible que deux services partagent une machine, ce qui peut
expliquer une panne sans qu'aucune mesure ne soit portée par la flèche elle-même.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from decoupage import Fenetre, charger, decouper          # noqa: E402
from lecture import Note                                  # noqa: E402
from ronds import Rond, ronds_de                          # noqa: E402
from valeurs import QUANTILES, quant, rap                  # noqa: E402

NOMS_APPELER = ["debit_appels", "duree_q50", "duree_q95", "duree_q99", "taux_erreur"]
NOMS_DEBIT = ["debit"]


@dataclass(slots=True)
class Fleche:
    genre: str                   # appeler | deposer | retirer | tourner_sur
    de: str                      # clé du rond de départ
    vers: str                    # clé du rond d'arrivée
    noms: list[str] = field(default_factory=list)
    valeurs: list[float | None] = field(default_factory=list)


def _erreur(n: Note) -> bool:
    """Une note est en erreur si son code de réponse est 400 ou plus."""
    code = n.attributs.get("http.response.status_code")
    if code is None:
        return bool(n.attributs.get("error.type"))
    try:
        return int(code) >= 400
    except (TypeError, ValueError):
        return False


def fleches_de(fenetre: Fenetre, ronds: dict[str, Rond], W: float,
               eta: float = 1.0) -> tuple[list[Fleche], dict]:
    """Construit les quatre sortes de flèches pour une fenêtre."""
    fleches: list[Fleche] = []
    dedans = set(ronds)

    # ---------------------------------------------------------- appeler
    par_id = {n.note_id: n for n in fenetre.notes if n.note_id}
    serveur = [n for n in fenetre.notes if n.genre == 2 and n.parent_id]
    groupes: dict[tuple[str, str], list[Note]] = defaultdict(list)
    resolus = orphelins = internes = hors_graphe = 0

    for n in serveur:
        parent = par_id.get(n.parent_id)
        if parent is None:
            orphelins += 1
            continue
        resolus += 1
        if parent.pod_uid == n.pod_uid:
            internes += 1
            continue
        if parent.pod_uid not in dedans or n.pod_uid not in dedans:
            hors_graphe += 1
            continue
        groupes[(parent.pod_uid, n.pod_uid)].append(n)

    for (de, vers), lot in groupes.items():
        durees = [x.duree_ns / 1e6 for x in lot]
        fleches.append(Fleche("appeler", de, vers, NOMS_APPELER, [
            rap(len(lot) / eta, W),
            *[quant(durees, q) for q in QUANTILES],
            rap(sum(1 for x in lot if _erreur(x)), len(lot)),
        ]))

    # ------------------------------------------------- déposer et retirer
    for genre, lot, sens in (("deposer", fenetre.depots, "vers_file"),
                             ("retirer", fenetre.retraits, "depuis_file")):
        compte: Counter = Counter()
        for n in lot:
            if not (n.pod_uid and n.nom_file):
                continue
            cle_file = f"file:{n.nom_file}"
            if n.pod_uid not in dedans or cle_file not in dedans:
                continue
            compte[(n.pod_uid, cle_file)] += 1
        for (pod, cle_file), k in compte.items():
            de, vers = (pod, cle_file) if sens == "vers_file" else (cle_file, pod)
            fleches.append(Fleche(genre, de, vers, NOMS_DEBIT,
                                  [rap(k / eta, W)]))

    # ------------------------------------------------------- tourner sur
    for cle, r in ronds.items():
        if r.genre != "copie" or not r.machine:
            continue
        cible = f"machine:{r.machine}"
        if cible in dedans:
            fleches.append(Fleche("tourner_sur", cle, cible, [], []))

    total_parents = resolus + orphelins
    rapport = {
        "notes_serveur_avec_parent": total_parents,
        "parents_retrouves": resolus,
        "parents_introuvables": orphelins,
        "resolution": resolus / total_parents if total_parents else None,
        "appels_internes": internes,
        "hors_graphe": hors_graphe,
    }
    return fleches, rapport


# ------------------------------------------------------------------ affichage
def _n(v: float | None) -> str:
    if v is None:
        return "    —"
    if v == 0:
        return "    0"
    return f"{v:>5.3g}" if abs(v) < 1e5 else f"{v:>5.1e}"


def montrer(fenetres, suite, tous_ronds, W: float) -> None:
    def t(x):
        print(f"\n{x}\n" + "─" * len(x))

    t("LES FLÈCHES, FENÊTRE PAR FENÊTRE")
    print(f"  {'fenêtre':>8} │ {'appeler':>8} {'déposer':>8} {'retirer':>8} "
          f"{'tourne sur':>11} │ {'total':>6} │ {'parents retrouvés':>18}")
    print("  " + "─" * 8 + "┼" + "─" * 39 + "┼" + "─" * 8 + "┼" + "─" * 19)
    for f, (fl, rap_) in zip(fenetres, suite):
        c = Counter(x.genre for x in fl)
        r = rap_["resolution"]
        taux = f"{100*r:5.1f} %" if r is not None else "    —"
        print(f"  {f.horodatage:>8} │ {c['appeler']:8d} {c['deposer']:8d} "
              f"{c['retirer']:8d} {c['tourner_sur']:11d} │ {len(fl):6d} │"
              f"       {taux}")

    ex = next((i for i, (fl, _) in enumerate(suite)
               if any(x.genre == "deposer" for x in fl)), len(suite) - 1)
    f, (fl, rap_) = fenetres[ex], suite[ex]
    ronds = tous_ronds[ex]
    lisible = lambda cle: ronds[cle].nom if cle in ronds else cle[:12]

    t(f"CE QUI A ÉTÉ ÉCARTÉ, fenêtre {f.horodatage}")
    print(f"  notes SERVEUR ayant un parent : {rap_['notes_serveur_avec_parent']}")
    print(f"    parent retrouvé             : {rap_['parents_retrouves']}")
    print(f"    parent introuvable          : {rap_['parents_introuvables']}"
          f"   (sa note est hors de la fenêtre)")
    print(f"    appel interne à une copie   : {rap_['appels_internes']}"
          f"   (pas une relation entre deux ronds)")
    print(f"    hors du graphe étudié       : {rap_['hors_graphe']}"
          f"   (écarté par --espace)")

    t(f"LES FLÈCHES DE MESSAGERIE, fenêtre {f.horodatage}")
    msg = [x for x in fl if x.genre in ("deposer", "retirer")]
    if not msg:
        print("  aucune sur cette fenêtre.")
    for x in sorted(msg, key=lambda x: (x.genre, x.de)):
        print(f"  {x.genre:<9} {lisible(x.de)[:34]:<34} → {lisible(x.vers)[:24]:<24} "
              f"débit {_n(x.valeurs[0])} msg/s")

    t(f"LES CINQ APPELS LES PLUS CHARGÉS, fenêtre {f.horodatage}")
    app = sorted((x for x in fl if x.genre == "appeler"),
                 key=lambda x: -(x.valeurs[0] or 0))[:5]
    print(f"  {'appelant → appelé':<52}{'débit/s':>9}{'q50 ms':>9}"
          f"{'q95 ms':>9}{'q99 ms':>9}{'err':>7}")
    for x in app:
        lien = f"{lisible(x.de)[:24]} → {lisible(x.vers)[:24]}"
        print(f"  {lien:<52}" + "".join(_n(v).rjust(9) for v in x.valeurs[:4])
              + _n(x.valeurs[4]).rjust(7))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dossier")
    p.add_argument("--largeur", type=float, default=60)
    p.add_argument("--pas", type=float, default=None)
    p.add_argument("--espace", default=None)
    p.add_argument("--echantillon", type=float, default=1.0)
    args = p.parse_args()

    dossier = Path(args.dossier)
    if not dossier.is_dir():
        sys.exit(f"dossier introuvable : {dossier}")

    notes, releves = charger(dossier)
    print(f"chargé : {len(notes)} notes · {len(releves)} relevés")
    pas = args.pas if args.pas is not None else args.largeur
    fenetres, rapport = decouper(notes, releves, args.largeur, pas)
    print(f"fenêtres retenues : {rapport['gardees']}")
    if not fenetres:
        return 1

    tous_ronds = [ronds_de(f, args.espace) for f in fenetres]
    suite = [fleches_de(f, r, args.largeur, args.echantillon)
             for f, r in zip(fenetres, tous_ronds)]
    montrer(fenetres, suite, tous_ronds, args.largeur)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
