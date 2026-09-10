"""
Lecture des fichiers bruts produits par la chaîne de mesure.

C'est la première brique du constructeur, et la seule qui connaisse le format
OTLP. Tout ce qui vient après manipule des enregistrements plats, sans jamais
savoir d'où ils sortent.

Deux sources, deux formes :

  TRACES     ce que les programmes racontent    →  des notes (spans)
  COMPTEURS  ce que la grappe mesure            →  des relevés

Les deux arrivent en JSON compressé, rangés par date :

    otel-data/year=2026/month=09/day=09/hour=16/minute=19/traces_*.json.gz
    otel-data/year=2026/month=09/day=09/hour=16/minute=19/metrics_*.json.gz

Le format OTLP imbrique fortement : une ressource contient des portées, qui
contiennent des notes. On aplatit tout, en recopiant sur chaque note l'identité
de la ressource qui l'a émise — c'est cette identité qui rattachera plus tard
la note à un rond du graphe.
"""
from __future__ import annotations

import gzip
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


# ---------------------------------------------------------------- valeurs OTLP
def _valeur(v: dict) -> Any:
    """
    OTLP enveloppe chaque valeur dans un objet qui dit son type :
        {"stringValue": "ts-food-service"}   {"intValue": "42"}
    On ne garde que le contenu.
    """
    if not isinstance(v, dict) or not v:
        return None
    cle, brut = next(iter(v.items()))
    if cle == "intValue":
        return int(brut)
    if cle == "doubleValue":
        return float(brut)
    if cle == "boolValue":
        return bool(brut)
    return brut


def _attributs(liste: list[dict] | None) -> dict[str, Any]:
    """Transforme la liste [{key, value}] d'OTLP en dictionnaire simple."""
    return {a["key"]: _valeur(a.get("value", {})) for a in (liste or [])}


# --------------------------------------------------------------------- modèles
@dataclass(slots=True)
class Note:
    """
    Une action faite par un programme : ce qu'OTLP appelle un span.

    Les quatre premiers champs disent QUI a agi. Ils viennent de la ressource,
    pas de la note elle-même : une note brute dit « j'ai traité un message en
    18 ms » sans dire qui. C'est le collecteur qui a ajouté l'identité, et c'est
    elle qui permet de rattacher la note à un rond du graphe.
    """
    service: str | None          # nom du service            → 1re part de l'identité
    pod_uid: str | None          # identifiant de la copie   → 2e part de l'identité
    machine: str | None          # nom de la machine         → flèche « tourne sur »
    namespace: str | None

    trace_id: str
    note_id: str
    parent_id: str | None        # relie une note à celle qui l'a déclenchée
    nom: str
    genre: int                   # 1 interne · 2 SERVEUR (reçoit) · 3 CLIENT (émet)
                                 # 4 PRODUCTEUR (dépose) · 5 CONSOMMATEUR (retire)
                                 # Vérifié sur données réelles : les notes de genre 2
                                 # sont bien « POST /api/... », celles de genre 3 des
                                 # « SELECT ... ». Un commentaire antérieur inversait 2 et 3.
    debut_ns: int
    fin_ns: int
    attributs: dict[str, Any] = field(default_factory=dict)

    @property
    def duree_ns(self) -> int:
        return self.fin_ns - self.debut_ns

    @property
    def duree_ms(self) -> float:
        return self.duree_ns / 1_000_000

    # -- raccourcis de messagerie ------------------------------------------
    # Ces trois attributs décident si la note est un dépôt ou un retrait, et
    # dans quelle file. Ce sont eux qui construisent les flèches « déposer » et
    # « retirer », et qui donnent son identité au rond « file ».
    @property
    def systeme_file(self) -> str | None:
        return self.attributs.get("messaging.system")

    @property
    def nom_file(self) -> str | None:
        return self.attributs.get("messaging.destination.name")

    @property
    def operation_file(self) -> str | None:
        """« send » quand on dépose, « process » quand on retire."""
        return self.attributs.get("messaging.operation.type")

    @property
    def cle_message(self) -> tuple | None:
        """
        Ce qui identifie UN message, et non une note.

        ATTENTION — piège vérifié sur données réelles. Un même message retiré
        produit DEUX notes, pas une : mêmes attributs, même genre, même parent,
        même numéro de livraison, seul l'identifiant de note diffère. C'était
        systématique, sur 92 consommations sur 92.

        Compter les notes double donc le débit retiré — c'est-à-dire la moitié
        de l'écart entre ce qui entre et ce qui sort, la grandeur centrale du
        travail. Mesuré sur cinq minutes réelles :

            en comptant les notes     : écart = -52 et -39   (absurde)
            en comptant les messages  : écart =   1 et   0   (crédible)

        Un écart négatif voudrait dire qu'une file se vide sans que personne
        n'y dépose.
        """
        if not self.nom_file:
            return None
        return (self.trace_id,
                self.attributs.get("messaging.rabbitmq.message.delivery_tag"),
                self.attributs.get("messaging.message.id"))


@dataclass(slots=True)
class Releve:
    """
    Un nombre, mesuré à un instant, pour une chose.

    Les étiquettes disent DE QUOI on parle : quel pod, quelle machine, quelle
    file. Ce sont elles qui rattachent le relevé à un rond.
    """
    nom: str
    valeur: float
    instant_ns: int
    etiquettes: dict[str, Any] = field(default_factory=dict)

    # -- raccourcis de rattachement ----------------------------------------
    @property
    def pod(self) -> str | None:
        return self.etiquettes.get("pod")

    @property
    def namespace(self) -> str | None:
        return self.etiquettes.get("namespace")

    @property
    def machine(self) -> str | None:
        # Les compteurs de machine et ceux de conteneur ne nomment pas la
        # machine de la même façon : constaté sur les données réelles.
        return (self.etiquettes.get("node")
                or self.etiquettes.get("kubernetes_io_hostname")
                or self.etiquettes.get("instance"))

    @property
    def file(self) -> str | None:
        return self.etiquettes.get("queue")


# ------------------------------------------------------------------- ouverture
def _texte(chemin: str | Path) -> str:
    """Ouvre le fichier, compressé ou non."""
    chemin = Path(chemin)
    brut = chemin.read_bytes()
    if brut[:2] == b"\x1f\x8b":          # signature gzip
        brut = gzip.decompress(brut)
    return brut.decode("utf-8")


def _documents(texte: str) -> Iterator[dict]:
    """
    Un fichier peut contenir un seul document JSON, ou plusieurs à la suite,
    un par ligne. On accepte les deux.
    """
    texte = texte.strip()
    if not texte:
        return
    try:
        yield json.loads(texte)
        return
    except json.JSONDecodeError:
        pass
    for ligne in texte.splitlines():
        ligne = ligne.strip()
        if ligne:
            yield json.loads(ligne)


# ---------------------------------------------------------------- lecture
def lire_notes(chemin: str | Path) -> list[Note]:
    """Lit un fichier de traces et rend une liste plate de notes."""
    notes: list[Note] = []
    for doc in _documents(_texte(chemin)):
        for bloc in doc.get("resourceSpans", []):
            ident = _attributs(bloc.get("resource", {}).get("attributes"))
            service = ident.get("service.name")
            pod_uid = ident.get("k8s.pod.uid")
            machine = ident.get("k8s.node.name")
            espace = ident.get("k8s.namespace.name")
            for portee in bloc.get("scopeSpans", []):
                for s in portee.get("spans", []):
                    notes.append(Note(
                        service=service,
                        pod_uid=pod_uid,
                        machine=machine,
                        namespace=espace,
                        trace_id=s.get("traceId", ""),
                        note_id=s.get("spanId", ""),
                        parent_id=s.get("parentSpanId") or None,
                        nom=s.get("name", ""),
                        genre=int(s.get("kind", 0) or 0),
                        debut_ns=int(s.get("startTimeUnixNano", 0)),
                        fin_ns=int(s.get("endTimeUnixNano", 0)),
                        attributs=_attributs(s.get("attributes")),
                    ))
    return notes


def lire_releves(chemin: str | Path) -> list[Releve]:
    """Lit un fichier de compteurs et rend une liste plate de relevés."""
    releves: list[Releve] = []
    for doc in _documents(_texte(chemin)):
        for bloc in doc.get("resourceMetrics", []):
            for portee in bloc.get("scopeMetrics", []):
                for m in portee.get("metrics", []):
                    nom = m.get("name", "")
                    # ATTENTION : tout arrive en « gauge », y compris les
                    # compteurs cumulatifs en _total. C'est une conséquence de
                    # la conversion depuis Prometheus. La forme déclarée ne dit
                    # donc PAS si la valeur est un niveau ou un cumul — c'est au
                    # code de le savoir, par le nom.
                    for forme in ("gauge", "sum", "histogram", "summary"):
                        corps = m.get(forme)
                        if not corps:
                            continue
                        for dp in corps.get("dataPoints", []):
                            valeur = dp.get("asDouble")
                            if valeur is None and "asInt" in dp:
                                valeur = float(dp["asInt"])
                            if valeur is None:
                                continue
                            releves.append(Releve(
                                nom=nom,
                                valeur=float(valeur),
                                instant_ns=int(dp.get("timeUnixNano", 0)),
                                etiquettes=_attributs(dp.get("attributes")),
                            ))
    return releves


def est_cumulatif(nom: str) -> bool:
    """
    Un compteur cumulatif ne fait que monter ; un niveau monte et descend.

    La distinction est perdue à la conversion, on la retrouve par le nom.
    Elle est essentielle : sur un cumul on calcule un accroissement, sur un
    niveau on prend la dernière valeur.
    """
    return nom.endswith("_total") or nom.endswith("_seconds_total")


# ------------------------------------------------------ compter des messages
def messages_deposes(notes: list[Note]) -> list[Note]:
    """
    Les notes qui déposent un message dans une file, une par message.

    On ne dédoublonne PAS ici, et c'est volontaire. Un dépôt ne porte ni numéro
    de livraison ni identifiant de message : sa seule signature serait la trace,
    or une même trace peut très bien déposer deux messages différents. Les
    dédoublonner les confondrait.

    Vérifié sur données réelles : les dépôts ne sont pas dupliqués (87 dépôts
    pour 88 messages retirés — un écart de 1, pas un facteur 2).
    """
    return [n for n in notes
            if n.nom_file and n.operation_file == "send"]


def messages_retires(notes: list[Note]) -> list[Note]:
    """
    Les notes qui retirent un message d'une file, UNE PAR MESSAGE.

    Ici le dédoublonnage est indispensable : un même message retiré produit deux
    notes identiques. Voir Note.cle_message pour la démonstration. Sans ça le
    débit sortant est doublé et l'écart devient négatif sur une file saine.
    """
    vus, gardes = set(), []
    for n in notes:
        if not (n.nom_file and n.operation_file == "process"):
            continue
        c = n.cle_message
        if c in vus:
            continue
        vus.add(c)
        gardes.append(n)
    return gardes
