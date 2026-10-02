"""
Faux boto3 pour les essais de la garde : aucune connexion. Les objets du faux
magasin sont lus dans FAUX_S3_OBJETS (JSON : [{"Key": …, "LastModified": "…Z"}]).
FAUX_S3_ERREUR=1 : l'appel échoue avec un message qui CONTIENT le secret (la
garde doit le taire). FAUX_S3_PEND=1 : l'appel pend. Chaque appel est noté dans
FAUX_S3_LOG, sans aucune clé.
"""
import json
import os
import time
from datetime import datetime, timezone


class _Client:
    def __init__(self, secret):
        self._secret = secret

    def list_objects_v2(self, Bucket, Prefix, StartAfter="", ContinuationToken=None):
        if os.environ.get("FAUX_S3_LOG"):
            with open(os.environ["FAUX_S3_LOG"], "a", encoding="utf-8") as f:
                f.write(json.dumps({"bucket": Bucket, "prefix": Prefix, "start_after": StartAfter}) + "\n")
        if os.environ.get("FAUX_S3_PEND"):
            time.sleep(100000)
        if os.environ.get("FAUX_S3_ERREUR"):
            raise ConnectionError(f"accès refusé pour la clé {self._secret} sur {Bucket}")
        try:
            with open(os.environ["FAUX_S3_OBJETS"], encoding="utf-8") as f:
                objets = json.load(f)
        except (KeyError, OSError, ValueError):
            objets = []
        contenu = [{"Key": o["Key"], "Size": 10,
                    "LastModified": datetime.strptime(o["LastModified"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)}
                   for o in objets if o["Key"].startswith(Prefix) and o["Key"] > (StartAfter or "")]
        return {"Contents": contenu, "IsTruncated": False}


def client(service, endpoint_url=None, aws_access_key_id=None, aws_secret_access_key=None, **_):
    return _Client(aws_secret_access_key)
