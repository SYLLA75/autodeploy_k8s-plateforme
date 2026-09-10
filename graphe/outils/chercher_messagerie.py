import os, sys, gzip, collections, boto3
from botocore.config import Config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lecture import lire_notes

s3 = boto3.client("s3", endpoint_url=os.environ["OBS_S3_ENDPOINT"],
    aws_access_key_id=os.environ["OBS_S3_ACCESS_KEY"],
    aws_secret_access_key=os.environ["OBS_S3_SECRET_KEY"],
    config=Config(signature_version="s3v4", s3={"addressing_style":"path"}),
    region_name="us-east-1")
b = os.environ["OBS_S3_BUCKET"]
objs = []
for p in s3.get_paginator("list_objects_v2").paginate(Bucket=b, Prefix="otel-data/"):
    objs += p.get("Contents", [])
tr = sorted([o for o in objs if "/traces_" in o["Key"] ],
            key=lambda o: o["LastModified"])
print("fichiers de traces :", len(tr))
print("periode :", tr[0]["LastModified"].strftime("%H:%M"), "→", tr[-1]["LastModified"].strftime("%H:%M"))

os.makedirs("/home/chsylla/autodeploy_k8s/graphe/donnees", exist_ok=True)
noms = collections.Counter(); avec = 0; total = 0
meilleur = (0, None)
for o in tr:
    raw = s3.get_object(Bucket=b, Key=o["Key"])["Body"].read()
    txt = (gzip.decompress(raw) if raw[:2]==b"\x1f\x8b" else raw).decode()
    p = "/home/chsylla/autodeploy_k8s/graphe/donnees/tmp.json"
    open(p,"w").write(txt)
    notes = lire_notes(p)
    total += len(notes)
    for n in notes: noms[n.nom] += 1
    msg = [n for n in notes if n.systeme_file]
    if msg:
        avec += 1
        if len(msg) > meilleur[0]:
            meilleur = (len(msg), o["Key"])
            open("/home/chsylla/autodeploy_k8s/graphe/donnees/messagerie.json","w").write(txt)
print("notes lues au total :", total)
print("fichiers avec messagerie :", avec)
print("meilleur :", meilleur[0], "notes ·", (meilleur[1] or "").split("otel-data/")[-1])
print("\n-- noms de notes les plus frequents --")
for n, c in noms.most_common(12): print("   %-52s %d" % (n[:52], c))
os.remove(p)
