#!/usr/bin/env python3
"""
Regarder ce que contient un fichier de mesure.

    python3 voir.py donnees/messagerie.json

C'est un outil d'inspection, pas une étape du traitement. Il sert à répondre à
« qu'est-ce qu'il y a là-dedans ? » avant d'écrire le code qui s'en sert.

Il reconnaît tout seul les deux sortes de fichiers, compressés ou non.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lecture import lire_notes, lire_releves, est_cumulatif, _texte  # noqa: E402


def _titre(t: str) -> None:
    print(f"\n{t}\n" + "─" * len(t))


def voir_notes(chemin: str) -> None:
    notes = lire_notes(chemin)
    if not notes:
        return
    _titre("NOTES — ce que les programmes racontent")
    print(f"  nombre            : {len(notes)}")
    print(f"  services          : {len({n.service for n in notes if n.service})}")
    print(f"  copies de service : {len({n.pod_uid for n in notes if n.pod_uid})}")
    print(f"  machines          : {', '.join(sorted({n.machine for n in notes if n.machine}))}")
    print(f"  avec un parent    : {sum(1 for n in notes if n.parent_id)}"
          f"   (c'est ce qui donne les flèches « appeler »)")

    debut = min(n.debut_ns for n in notes)
    fin = max(n.fin_ns for n in notes)
    print(f"  période couverte  : {(fin - debut) / 1e9:.1f} secondes")

    msg = [n for n in notes if n.systeme_file]
    _titre("MESSAGERIE — ce qui construit les flèches de la file")
    if not msg:
        print("  aucune note de messagerie dans ce fichier.")
    else:
        print(f"  notes de messagerie : {len(msg)} sur {len(notes)}")
        print()
        c = Counter((n.nom_file, n.operation_file) for n in msg)
        for (f, op), k in sorted(c.items(), key=lambda x: (str(x[0][0]), str(x[0][1]))):
            role = {"send": "DÉPÔT  ", "process": "RETRAIT", "settle": "accusé "}.get(op, str(op))
            fichier = f if f else "(sans nom de file)"
            print(f"    {role}  file {fichier:<18} {k:3d} notes")
        print()
        print("  Rappel : « accusé » est la confirmation de traitement. Elle ne porte")
        print("  aucun nom de file, et ne doit compter ni comme dépôt ni comme retrait.")

    _titre("NOMS DE NOTES les plus fréquents")
    for nom, k in Counter(n.nom for n in notes).most_common(8):
        print(f"    {nom[:56]:<56} {k}")


def voir_releves(chemin: str) -> None:
    releves = lire_releves(chemin)
    if not releves:
        return
    _titre("RELEVÉS — ce que la grappe mesure")
    print(f"  nombre            : {len(releves)}")
    print(f"  noms distincts    : {len({r.nom for r in releves})}")
    print(f"  cumulatifs        : {sum(1 for r in releves if est_cumulatif(r.nom))}"
          f"   (on calcule un accroissement)")
    print(f"  niveaux           : {sum(1 for r in releves if not est_cumulatif(r.nom))}"
          f"   (on prend la dernière valeur)")

    _titre("PAR ROND DU GRAPHE")
    familles = {
        "machine": lambda r: r.nom.startswith("node_"),
        "copie de service": lambda r: r.nom.startswith("container_") or r.nom.startswith("kube_pod_container"),
        "file": lambda r: r.nom.startswith("rabbitmq_"),
        "pont copie ↔ machine": lambda r: r.nom == "kube_pod_info",
    }
    for titre, test in familles.items():
        sous = [r for r in releves if test(r)]
        print(f"\n  {titre} — {len(sous)} relevés")
        for nom, k in Counter(r.nom for r in sous).most_common(6):
            print(f"      {nom:<50} {k}")

    files = sorted({r.file for r in releves if r.file})
    if files:
        _titre("ÉTAT DES FILES, dernier relevé")
        for f in files:
            print(f"\n    file « {f} »")
            for nom in ("rabbitmq_queue_messages_ready",
                        "rabbitmq_queue_messages_unacked",
                        "rabbitmq_queue_consumers"):
                v = [r for r in releves if r.nom == nom and r.file == f]
                if v:
                    dernier = max(v, key=lambda r: r.instant_ns)
                    libelle = {"rabbitmq_queue_messages_ready": "messages qui attendent",
                               "rabbitmq_queue_messages_unacked": "donnés, pas confirmés",
                               "rabbitmq_queue_consumers": "consommateurs connectés"}[nom]
                    print(f"      {libelle:<26} {dernier.valeur:.0f}")


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    chemin = sys.argv[1]
    if not Path(chemin).exists():
        print(f"fichier introuvable : {chemin}")
        return 1

    tete = _texte(chemin)[:200]
    print(f"fichier : {chemin}")
    if "resourceSpans" in tete:
        voir_notes(chemin)
    elif "resourceMetrics" in tete:
        voir_releves(chemin)
    else:
        print("  format non reconnu (ni traces, ni compteurs)")
        return 1
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
