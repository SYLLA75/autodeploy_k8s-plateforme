"""
Fichier de parcours pour les cas (e) et (g) : le VRAI locustfile, avec un
espion sur l'envoi de requests qui note, pour chaque requête, le délai
réellement transmis, le voyageur (son greenlet) et le numéro de son parcours
(0 : on_start, puis 1, 2, …).

Le locustfile n'est pas modifié : il est importé tel quel, et Locust trouve
la classe Voyageur dans ce module. Le journal va dans JOURNAL_ENVOIS.
"""
import functools
import json
import os
import sys

import gevent
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_envoi = requests.Session.send
_PARCOURS = {}   # greenlet -> numéro du parcours en cours


def _espion(self, requete, **kw):
    g = id(gevent.getcurrent())
    with open(os.environ["JOURNAL_ENVOIS"], "a", encoding="utf-8") as f:
        f.write(json.dumps({"chemin": requete.path_url, "timeout": kw.get("timeout"),
                            "voyageur": g, "parcours": _PARCOURS.get(g, 0)}) + "\n")
    return _envoi(self, requete, **kw)


requests.Session.send = _espion

from locustfile import Voyageur  # noqa: E402


def _compter(tache):
    @functools.wraps(tache)
    def enveloppe(user):
        g = id(gevent.getcurrent())
        _PARCOURS[g] = _PARCOURS.get(g, 0) + 1
        return tache(user)
    return enveloppe


# La liste des tâches est construite à la création de la classe : on
# l'enveloppe en place, sans toucher au locustfile.
Voyageur.tasks = [_compter(t) for t in Voyageur.tasks]
