#!/usr/bin/env python3
"""
Les ronds du graphe : qui existe, dans chaque fenêtre.

    python3 ronds.py donnees/2026-09-09_1505-1514
    python3 ronds.py donnees/2026-09-09_1505-1514 --espace train-ticket

Troisième brique. Elle ne calcule aucune valeur et ne trace aucune flèche : elle
dresse la liste de ce qui existe, et donne à chaque chose un nom stable, pour
qu'on la retrouve d'une fenêtre à l'autre.

TROIS SORTES DE RONDS

    copie      une copie d'un service qui tourne      un pod
    file       une file d'attente                     une queue RabbitMQ
    machine    une machine du cluster                 un node

DEUX SOURCES QUI NE PARLENT PAS LA MÊME LANGUE

Les traces désignent un pod par un identifiant :

    k8s.pod.uid = fc2f0f27-b624-433c-98ea-fff47c39355d

Les compteurs le désignent par son nom :

    pod = ts-seat-service-6fbf7f6fbb-zllcn

C'est kube_pod_info qui fait le pont : il porte les deux, plus la machine.
Vérifié sur la plage 15:05→15:14 — les 41 pods vus dans les traces sont tous
retrouvés, et la machine annoncée par les traces est la même que celle annoncée
par les compteurs, 41 fois sur 41, zéro désaccord.

REDÉMARRAGES. Deux cas à ne pas confondre :

    le conteneur redémarre sur place  →  MÊME identifiant, même rond, et le
                                         compteur kube_pod_container_status_
                                         restarts_total augmente
    le pod est recréé                 →  NOUVEL identifiant, nouveau rond

Le second est correct : c'est bien une autre copie, sur une autre machine
peut-être. Le premier ne casse rien, et reste visible par son compteur. Il n'y a
donc rien à décider : les deux situations se distinguent dans les données.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from decoupage import Fenetre, charger, decouper  # noqa: E402


@dataclass(slots=True)
class Rond:
    """Une chose du graphe, dans une fenêtre donnée."""
    genre: str                   # "copie" | "file" | "machine"
    cle: str                     # identifiant stable, sert de nom de rond
    nom: str                     # libellé lisible
    service: str | None = None
    espace: str | None = None    # namespace
    machine: str | None = None   # pour une copie : où elle tourne
    vu_traces: bool = False
    vu_compteurs: bool = False

    @property
    def source(self) -> str:
        if self.vu_traces and self.vu_compteurs:
            return "les deux"
        return "traces" if self.vu_traces else "compteurs"


# ------------------------------------------------------------------- le pont
def _annuaire(fenetre: Fenetre) -> dict[str, dict]:
    """
    L'annuaire des pods de la fenêtre, construit sur kube_pod_info.

    Rend, pour chaque identifiant de pod : son nom, son espace, sa machine.
    C'est la seule pièce qui relie le monde des traces à celui des compteurs.
    """
    par_uid: dict[str, dict] = {}
    for r in fenetre.releves:
        if r.nom != "kube_pod_info":
            continue
        e = r.etiquettes
        uid = e.get("uid")
        if uid:
            par_uid[uid] = {"pod": e.get("pod"), "espace": e.get("namespace"),
                            "machine": e.get("node")}
    return par_uid


def ronds_de(fenetre: Fenetre, espace: str | None = None) -> dict[str, Rond]:
    """
    Dresse la liste des ronds présents dans cette fenêtre.

    `espace` restreint à un namespace : sans ça on ramasse aussi les pods du
    système et ceux de la mesure elle-même, qui ne font pas partie du graphe
    étudié.
    """
    annuaire = _annuaire(fenetre)
    par_nom_pod = {v["pod"]: (uid, v) for uid, v in annuaire.items() if v["pod"]}
    ronds: dict[str, Rond] = {}

    def poser(genre: str, cle: str, **kw) -> Rond:
        r = ronds.get(cle)
        if r is None:
            r = ronds[cle] = Rond(genre=genre, cle=cle, nom=kw.pop("nom", cle))
        for k, v in kw.items():
            if v is not None and getattr(r, k, None) is None:
                setattr(r, k, v)
        return r

    def retenu(esp: str | None) -> bool:
        return espace is None or esp == espace

    # --- les copies, vues par les traces ---------------------------------
    for n in fenetre.notes:
        if not n.pod_uid or not retenu(n.namespace):
            continue
        fiche = annuaire.get(n.pod_uid, {})
        poser("copie", n.pod_uid,
              nom=fiche.get("pod") or n.service or n.pod_uid[:12],
              service=n.service, espace=n.namespace,
              machine=n.machine or fiche.get("machine")).vu_traces = True

    # --- les copies, vues par les compteurs ------------------------------
    for r in fenetre.releves:
        if not r.nom.startswith("container_"):
            continue
        nom_pod = r.etiquettes.get("pod")
        if not nom_pod or not retenu(r.etiquettes.get("namespace")):
            continue
        trouve = par_nom_pod.get(nom_pod)
        if not trouve:
            continue                      # pas dans l'annuaire : on ne devine pas
        uid, fiche = trouve
        poser("copie", uid, nom=nom_pod, espace=fiche["espace"],
              machine=fiche["machine"] or r.etiquettes.get("kubernetes_io_hostname"),
              ).vu_compteurs = True

    # --- les files -------------------------------------------------------
    for n in fenetre.depots + fenetre.retraits:
        if n.nom_file:
            poser("file", f"file:{n.nom_file}", nom=n.nom_file,
                  espace=n.namespace).vu_traces = True
    for r in fenetre.releves:
        if r.nom.startswith("rabbitmq_queue_") and r.file:
            poser("file", f"file:{r.file}", nom=r.file,
                  espace=r.etiquettes.get("namespace"),
                  machine=r.etiquettes.get("node")).vu_compteurs = True

    # --- les machines ----------------------------------------------------
    # Elles ne sont pas filtrées par espace : une machine porte des pods de
    # plusieurs espaces, et c'est justement ce partage qui peut expliquer une
    # panne — un voisin bruyant.
    for r in fenetre.releves:
        if r.nom.startswith("node_") and r.etiquettes.get("node"):
            poser("machine", f"machine:{r.etiquettes['node']}",
                  nom=r.etiquettes["node"]).vu_compteurs = True
    for c in [x for x in ronds.values() if x.genre == "copie" and x.machine]:
        poser("machine", f"machine:{c.machine}", nom=c.machine).vu_traces = True

    return ronds


# ------------------------------------------------------------------ affichage
def montrer(suite: list[tuple[Fenetre, dict[str, Rond]]], espace: str | None) -> None:
    def t(x):
        print(f"\n{x}\n" + "─" * len(x))

    t("LES RONDS, FENÊTRE PAR FENÊTRE")
    if espace:
        print(f"  (copies et files limitées à l'espace « {espace} » ; machines : toutes)\n")
    print(f"  {'fenêtre':>8} │ {'copies':>6} {'files':>5} {'machines':>8} │ {'total':>5}")
    print("  " + "─" * 8 + "┼" + "─" * 22 + "┼" + "─" * 7)
    for f, ronds in suite:
        c = Counter(r.genre for r in ronds.values())
        print(f"  {f.horodatage:>8} │ {c['copie']:6d} {c['file']:5d} {c['machine']:8d} │"
              f" {len(ronds):5d}")

    if not suite:
        return
    _, premiers = suite[0]

    t(f"DÉTAIL DE LA PREMIÈRE FENÊTRE ({suite[0][0].horodatage})")
    for genre, titre in (("machine", "MACHINES"), ("file", "FILES"), ("copie", "COPIES")):
        lot = sorted((r for r in premiers.values() if r.genre == genre),
                     key=lambda r: r.nom)
        print(f"\n  {titre} — {len(lot)}")
        for r in lot[:12]:
            ou = f"  sur {r.machine}" if r.machine and genre != "machine" else ""
            print(f"    {r.nom:<44} [{r.source}]{ou}")
        if len(lot) > 12:
            print(f"    … et {len(lot) - 12} autres")

    # --- stabilité : un rond disparaît-il d'une fenêtre à l'autre ? -------
    t("STABILITÉ DES RONDS")
    presence = defaultdict(list)
    for i, (_, ronds) in enumerate(suite):
        for cle in ronds:
            presence[cle].append(i)
    n = len(suite)
    partout = [c for c, v in presence.items() if len(v) == n]
    print(f"  ronds distincts sur toute la plage : {len(presence)}")
    print(f"  présents dans TOUTES les fenêtres  : {len(partout)}")
    intermittents = {c: v for c, v in presence.items() if len(v) < n}
    if intermittents:
        print(f"  intermittents                      : {len(intermittents)}")
        modele = {c: r for _, ronds in suite for c, r in ronds.items()}
        for c, v in sorted(intermittents.items(), key=lambda x: -len(x[1]))[:8]:
            r = modele[c]
            print(f"    {r.genre:<8} {r.nom:<40} vu {len(v)}/{n} fenêtres")
        print("\n  Un rond intermittent n'est pas forcément une anomalie : un service")
        print("  qui ne reçoit aucune requête pendant une minute n'émet aucune note.")
        print("  C'est la brique « valeurs » qui distinguera silencieux de disparu.")
    else:
        print("  aucun intermittent — tous les ronds sont là du début à la fin.")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("dossier")
    p.add_argument("--largeur", type=float, default=60)
    p.add_argument("--pas", type=float, default=None)
    p.add_argument("--espace", default=None,
                   help="ne garder que cet espace de noms (ex. train-ticket)")
    args = p.parse_args()

    dossier = Path(args.dossier)
    if not dossier.is_dir():
        sys.exit(f"dossier introuvable : {dossier}")

    notes, releves = charger(dossier)
    print(f"chargé : {len(notes)} notes · {len(releves)} relevés")
    fenetres, rapport = decouper(notes, releves, args.largeur,
                                 args.pas if args.pas is not None else args.largeur)
    print(f"fenêtres retenues : {rapport['gardees']}")

    suite = [(f, ronds_de(f, args.espace)) for f in fenetres]
    montrer(suite, args.espace)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
