#!/usr/bin/env python3
"""
Rapatrier une plage de temps depuis le magasin d'objets, et dire ce qu'elle
contient.

    python3 rapatrier.py                                  aujourd'hui, tout
    python3 rapatrier.py --date 2026-09-09                un jour précis
    python3 rapatrier.py --date 2026-09-09 --de 15:00 --a 15:05
    python3 rapatrier.py --de 15:00 --a 15:05 --resume    sans télécharger

Le magasin range les fichiers par date :

    otel-data/year=2026/month=09/day=09/hour=15/minute=01/traces_*.json.gz

On s'en sert pour ne demander que la tranche voulue, au lieu de tout parcourir.

CE QUE CET OUTIL NE FAIT PAS. Il ne découpe rien en fenêtres. Il rapatrie une
plage et s'arrête là. La largeur de la fenêtre est un choix d'expérience qui
n'est pas encore arrêté : le figer ici l'imposerait à tout ce qui suit.

Les identifiants viennent de .env.secrets, jamais du code :

    set -a; . ../.env.secrets; set +a
    ./.venv/bin/python rapatrier.py
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
from collections import Counter
from datetime import date as Date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lecture import lire_notes, lire_releves, est_cumulatif  # noqa: E402

RACINE = Path(__file__).resolve().parent
DONNEES = RACINE / "donnees"
PREFIXE = "otel-data/"

# year=2026/month=09/day=09/hour=15/minute=01/
_CLE = re.compile(r"year=(\d{4})/month=(\d{2})/day=(\d{2})/hour=(\d{2})/minute=(\d{2})/")


def _client():
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        sys.exit("boto3 absent.  ./.venv/bin/pip install boto3")
    manquant = [v for v in ("OBS_S3_ENDPOINT", "OBS_S3_BUCKET",
                            "OBS_S3_ACCESS_KEY", "OBS_S3_SECRET_KEY")
                if not os.environ.get(v)]
    if manquant:
        sys.exit("Identifiants absents : " + ", ".join(manquant) +
                 "\n  set -a; . ../.env.secrets; set +a")
    return boto3.client(
        "s3",
        endpoint_url=os.environ["OBS_S3_ENDPOINT"],
        aws_access_key_id=os.environ["OBS_S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["OBS_S3_SECRET_KEY"],
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        region_name=os.environ.get("OBS_S3_REGION", "us-east-1"),
    ), os.environ["OBS_S3_BUCKET"]


def _minutes(cle: str) -> int | None:
    """Position de la clé dans la journée, en minutes. None si illisible."""
    m = _CLE.search(cle)
    return int(m.group(4)) * 60 + int(m.group(5)) if m else None


def _hhmm(t: str) -> int:
    h, mn = t.split(":")
    return int(h) * 60 + int(mn)


def _lisible(n: int) -> str:
    for u in ("o", "Ko", "Mo", "Go"):
        if n < 1024 or u == "Go":
            return f"{n:.0f} {u}" if u == "o" else f"{n:.1f} {u}"
        n /= 1024
    return ""


# ------------------------------------------------------------------ recherche
def chercher(s3, bucket: str, jour: Date, de: int, a: int) -> list[dict]:
    """Liste les objets de la plage. On ne parcourt que le préfixe du jour."""
    prefixe = f"{PREFIXE}year={jour.year:04d}/month={jour.month:02d}/day={jour.day:02d}/"
    trouves = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefixe):
        for o in page.get("Contents", []):
            pos = _minutes(o["Key"])
            if pos is None or not (de <= pos <= a):
                continue
            nom = o["Key"].rsplit("/", 1)[-1]
            if nom.startswith("traces_"):
                sorte = "traces"
            elif nom.startswith("metrics_"):
                sorte = "compteurs"
            else:
                continue
            trouves.append({"cle": o["Key"], "taille": o["Size"],
                            "sorte": sorte, "position": pos})
    return sorted(trouves, key=lambda x: (x["position"], x["cle"]))


# ------------------------------------------------------------- téléchargement
def rapatrier(s3, bucket: str, objets: list[dict], dossier: Path) -> list[Path]:
    """Télécharge, décompresse, et garde le nom d'origine dans le nom local."""
    dossier.mkdir(parents=True, exist_ok=True)
    chemins = []
    for i, o in enumerate(objets, 1):
        m = _CLE.search(o["cle"])
        nom = o["cle"].rsplit("/", 1)[-1].removesuffix(".gz")
        local = dossier / f"{m.group(4)}-{m.group(5)}_{nom}"
        if not local.exists():
            brut = s3.get_object(Bucket=bucket, Key=o["cle"])["Body"].read()
            if brut[:2] == b"\x1f\x8b":
                brut = gzip.decompress(brut)
            local.write_bytes(brut)
        chemins.append(local)
        if i % 25 == 0 or i == len(objets):
            print(f"    {i}/{len(objets)}", end="\r", flush=True)
    print(" " * 30, end="\r")
    return chemins


def carnet(dossier: Path, objets: list[dict], chemins: list[Path]) -> None:
    """
    Note d'où vient chaque fichier.

    Sans ce carnet, un fichier local n'est plus rattachable à son origine, et
    l'analyse cesse d'être refaisable. C'est le minimum pour qu'un jeu de
    données soit citable.
    """
    (dossier / "origine.json").write_text(json.dumps({
        "magasin": os.environ.get("OBS_S3_ENDPOINT"),
        "bucket": os.environ.get("OBS_S3_BUCKET"),
        "rapatrie_le": datetime.now().astimezone().isoformat(timespec="seconds"),
        "fichiers": [{"local": c.name, "cle": o["cle"], "octets": o["taille"]}
                     for o, c in zip(objets, chemins)],
    }, indent=2, ensure_ascii=False), encoding="utf-8")


# ------------------------------------------------------------------- résumé
def resumer(chemins: list[Path]) -> None:
    """
    Parcourt les fichiers un par un, sans tout garder en mémoire : une journée
    complète représente plusieurs gigaoctets une fois décompressée.
    """
    n_notes = n_msg = n_rel = 0
    services, copies, machines = set(), set(), set()
    avec_parent = 0
    depots, retraits = Counter(), Counter()
    noms_rel = Counter()
    etat_file: dict[tuple[str, str], tuple[int, float]] = {}
    debut = fin = None

    for c in chemins:
        tete = c.read_bytes()[:120]
        if b"resourceSpans" in tete:
            notes = lire_notes(c)
            n_notes += len(notes)
            for n in notes:
                if n.service:
                    services.add(n.service)
                if n.pod_uid:
                    copies.add(n.pod_uid)
                if n.machine:
                    machines.add(n.machine)
                if n.parent_id:
                    avec_parent += 1
                if n.debut_ns:
                    debut = n.debut_ns if debut is None else min(debut, n.debut_ns)
                    fin = n.fin_ns if fin is None else max(fin, n.fin_ns)
                if n.systeme_file and n.nom_file:
                    n_msg += 1
                    if n.operation_file == "send":
                        depots[n.nom_file] += 1
                    elif n.operation_file == "process":
                        retraits[n.nom_file] += 1
        elif b"resourceMetrics" in tete:
            for r in lire_releves(c):
                n_rel += 1
                noms_rel[r.nom] += 1
                if r.file and r.nom in ("rabbitmq_queue_messages_ready",
                                        "rabbitmq_queue_consumers"):
                    cle = (r.file, r.nom)
                    if cle not in etat_file or r.instant_ns > etat_file[cle][0]:
                        etat_file[cle] = (r.instant_ns, r.valeur)

    def t(x):
        print(f"\n{x}\n" + "─" * len(x))

    t("CE QUE LA PLAGE CONTIENT")
    print(f"  notes                 : {n_notes}")
    print(f"  relevés               : {n_rel}")
    if debut:
        print(f"  durée réelle couverte : {(fin - debut) / 60e9:.1f} minutes")

    if n_notes:
        t("LES RONDS DU GRAPHE")
        print(f"  copies de service : {len(copies):4d}   ({len(services)} services distincts)")
        print(f"  machines          : {len(machines):4d}   {', '.join(sorted(machines))}")
        files = sorted({f for f in list(depots) + list(retraits)})
        print(f"  files             : {len(files):4d}   {', '.join(files) if files else '—'}")

        t("LES FLÈCHES")
        print(f"  « appeler »  {avec_parent} notes ont un parent")
        for f in files:
            print(f"  « déposer »  file {f:<16} {depots[f]:4d} notes")
            print(f"  « retirer »  file {f:<16} {retraits[f]:4d} notes")
        if not files:
            print("  aucune note de messagerie sur cette plage.")

    if n_rel:
        t("LES COMPTEURS")
        print(f"  noms distincts : {len(noms_rel)}")
        familles = {"machine": "node_", "copie": "container_", "file": "rabbitmq_"}
        for lbl, p in familles.items():
            k = sum(v for n, v in noms_rel.items() if n.startswith(p))
            print(f"    {lbl:<9} {k:8d} relevés")
        pont = noms_rel.get("kube_pod_info", 0)
        print(f"    {'pont':<9} {pont:8d} relevés   (rattache une copie à sa machine)")

        if etat_file:
            t("ÉTAT DES FILES, dernier relevé de la plage")
            for f in sorted({k[0] for k in etat_file}):
                att = etat_file.get((f, "rabbitmq_queue_messages_ready"), (0, 0))[1]
                cons = etat_file.get((f, "rabbitmq_queue_consumers"), (0, 0))[1]
                print(f"    {f:<16} {att:6.0f} en attente · {cons:.0f} consommateur(s)")


def main() -> int:
    p = argparse.ArgumentParser(add_help=True, description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--date", help="jour visé, AAAA-MM-JJ (défaut : aujourd'hui)")
    p.add_argument("--de", default="00:00", help="heure de début, HH:MM")
    p.add_argument("--a", default="23:59", help="heure de fin, HH:MM")
    p.add_argument("--resume", action="store_true",
                   help="dire ce qu'il y a, sans rien télécharger")
    p.add_argument("--max", type=int, default=400,
                   help="garde-fou : nombre de fichiers au-delà duquel on refuse")
    args = p.parse_args()

    jour = Date.fromisoformat(args.date) if args.date else Date.today()
    de, a = _hhmm(args.de), _hhmm(args.a)

    s3, bucket = _client()
    print(f"magasin : {os.environ['OBS_S3_ENDPOINT']}/{bucket}")
    print(f"plage   : {jour.isoformat()}  de {args.de} à {args.a}")

    objets = chercher(s3, bucket, jour, de, a)
    if not objets:
        print("\naucun fichier sur cette plage.")
        return 0

    par_sorte = Counter(o["sorte"] for o in objets)
    octets = sum(o["taille"] for o in objets)
    print(f"\ntrouvé  : {len(objets)} fichiers  ({par_sorte['traces']} traces, "
          f"{par_sorte['compteurs']} compteurs)  ·  {_lisible(octets)} compressés")

    if args.resume:
        print("\n(--resume : rien n'est téléchargé)")
        return 0
    if len(objets) > args.max:
        print(f"\nRefusé : {len(objets)} fichiers dépassent la limite de {args.max}.")
        print("  Restreins la plage avec --de et --a, ou relève --max.")
        return 1

    dossier = DONNEES / f"{jour.isoformat()}_{args.de.replace(':', '')}-{args.a.replace(':', '')}"
    print(f"\nrapatriement vers {dossier.relative_to(RACINE)}/")
    chemins = rapatrier(s3, bucket, objets, dossier)
    carnet(dossier, objets, chemins)
    print(f"  {len(chemins)} fichiers · carnet d'origine écrit")

    resumer(chemins)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
