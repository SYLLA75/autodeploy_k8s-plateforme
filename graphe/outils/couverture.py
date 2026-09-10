"""Pour chaque minute de la journée : y a-t-il des traces AVEC messagerie, et des compteurs ?"""
import os, re, sys, gzip, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import boto3
from botocore.config import Config
from lecture import lire_notes

s3 = boto3.client("s3", endpoint_url=os.environ["OBS_S3_ENDPOINT"],
    aws_access_key_id=os.environ["OBS_S3_ACCESS_KEY"],
    aws_secret_access_key=os.environ["OBS_S3_SECRET_KEY"],
    config=Config(signature_version="s3v4", s3={"addressing_style":"path"}),
    region_name="us-east-1")
b = os.environ["OBS_S3_BUCKET"]
CLE = re.compile(r"hour=(\d{2})/minute=(\d{2})/")

objs = []
for p in s3.get_paginator("list_objects_v2").paginate(
        Bucket=b, Prefix="otel-data/year=2026/month=09/day=09/"):
    objs += p.get("Contents", [])

par_min = collections.defaultdict(lambda: {"tr": 0, "me": 0, "msg": 0})
tr_cles = collections.defaultdict(list)
for o in objs:
    m = CLE.search(o["Key"])
    if not m: continue
    mn = f"{m.group(1)}:{m.group(2)}"
    nom = o["Key"].rsplit("/",1)[-1]
    if nom.startswith("traces_"):
        par_min[mn]["tr"] += 1; tr_cles[mn].append(o["Key"])
    elif nom.startswith("metrics_"):
        par_min[mn]["me"] += 1

# un seul fichier de traces sondé par minute : suffit pour savoir si la messagerie coule
tmp = "/tmp/sonde.json"
for mn, cles in tr_cles.items():
    raw = s3.get_object(Bucket=b, Key=cles[0])["Body"].read()
    open(tmp,"w").write((gzip.decompress(raw) if raw[:2]==b"\x1f\x8b" else raw).decode())
    par_min[mn]["msg"] = sum(1 for n in lire_notes(tmp) if n.systeme_file and n.nom_file)
os.remove(tmp)

print("minute   traces  compteurs  messagerie")
print("-"*44)
deux = []
for mn in sorted(par_min):
    d = par_min[mn]
    ok = d["me"] > 0 and d["msg"] > 0
    if ok: deux.append(mn)
    print("%s %7d %10d %11d %s" % (mn, d["tr"], d["me"], d["msg"], "  ← LES DEUX" if ok else ""))
print()
print("minutes ayant À LA FOIS messagerie et compteurs :", len(deux))
if deux: print("  ", ", ".join(deux))
