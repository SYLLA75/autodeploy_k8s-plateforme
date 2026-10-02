"""
Un faux train-ticket, sur 127.0.0.1, pour faire tourner le vrai Locust.

Il rend juste assez pour que les quatre parcours avancent (jeton, trajet,
contact), et note chaque requête reçue dans un journal (une ligne JSON).

Chaque voyageur reçoit un témoin « voyageur=<n> » au premier appel : le
journal sait donc qui a envoyé quoi, voyageur par voyageur.

Trois façons de répondre :
  normal      (défaut) un serveur HTTP ; FAUX_SUSPENDRE liste les chemins qui
              ne répondent JAMAIS, à partir d'un instant donné :
              « /api/v1/foodservice/orders@0,/api/v1/users/login@4 » ;
              FAUX_CORPS_FIGE, même forme : les en-têtes et le début du corps
              partent, puis plus rien ; FAUX_403=1 : toute requête sans jeton
              (hors code et connexion) est refusée par un 403
  --muet      accepte la connexion, lit la requête, ne répond rien
  --plein     écoute sans jamais accepter : la file d'attente du noyau se
              remplit, et les connexions suivantes ne s'établissent plus

Usage : python3 faux_serveur.py <fichier_port> <journal> [--muet|--plein]
"""
import itertools
import json
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

T0 = time.monotonic()
VERROU = threading.Lock()
NUMEROS = itertools.count(1)


def _noter(journal, **ligne):
    ligne["t"] = round(time.monotonic() - T0, 3)
    with VERROU, open(journal, "a", encoding="utf-8") as f:
        f.write(json.dumps(ligne) + "\n")


def _suspendus(variable="FAUX_SUSPENDRE"):
    """Les chemins figés, avec l'instant (en s) à partir duquel ils le sont."""
    regles = {}
    for morceau in filter(None, os.getenv(variable, "").split(",")):
        chemin, _, apres = morceau.partition("@")
        regles[chemin] = float(apres or 0)
    return regles


REPONSES = {
    ("GET", "/api/v1/verifycode/generate"): {"status": 1},
    ("POST", "/api/v1/users/login"): {"status": 1, "data": {"token": "jeton", "userId": "uid-1"}},
    ("POST", "/api/v1/foodservice/orders"): {"status": 1},
    ("POST", "/api/v1/travelservice/trips/left"): {
        "status": 1, "data": [{"tripId": {"type": "G", "number": "1234"}}]},
    ("GET", "/api/v1/contactservice/contacts/account/uid-1"): {"status": 1, "data": [{"id": "c1"}]},
    ("POST", "/api/v1/preserveservice/preserve"): {"status": 1},
    ("GET", "/api/v1/notifyservice/test_send_mq"): {"status": 1},
}


def serveur_normal(fichier_port, journal):
    regles = _suspendus()
    corps_figes = _suspendus("FAUX_CORPS_FIGE")
    refus = os.getenv("FAUX_403") == "1"
    libres = ("/api/v1/verifycode/generate", "/api/v1/users/login")

    class Gestion(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass

        def _traiter(self):
            longueur = int(self.headers.get("Content-Length") or 0)
            corps = self.rfile.read(longueur) if longueur else b""
            try:
                cles = sorted(json.loads(corps)) if corps else []
            except ValueError:
                cles = ["?"]
            temoin = self.headers.get("Cookie") or ""
            voyageur = temoin.partition("voyageur=")[2].split(";")[0] or None
            nouveau = None
            if voyageur is None:
                nouveau = voyageur = str(next(NUMEROS))
            age = time.monotonic() - T0
            fige = self.path in regles and age >= regles[self.path]
            corps_fige = self.path in corps_figes and age >= corps_figes[self.path]
            auth = self.headers.get("Authorization")
            _noter(journal, methode=self.command, chemin=self.path, cles=cles,
                   voyageur=voyageur, auth=auth, fige=fige or corps_fige)
            if fige:
                # Ne JAMAIS répondre : on garde la connexion ouverte.
                while True:
                    time.sleep(3600)
            charge = REPONSES.get((self.command, self.path), {"status": 0})
            code = 200 if (self.command, self.path) in REPONSES else 404
            if refus and not auth and self.path not in libres:
                charge, code = {"status": 0, "msg": "refusé"}, 403
            donnees = json.dumps(charge).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(donnees)))
            if nouveau:
                self.send_header("Set-Cookie", f"voyageur={nouveau}; Path=/")
            self.end_headers()
            if corps_fige:
                # Les en-têtes et cinq octets partent, le reste JAMAIS.
                self.wfile.write(donnees[:5])
                self.wfile.flush()
                while True:
                    time.sleep(3600)
            self.wfile.write(donnees)

        do_GET = do_POST = _traiter

    ThreadingHTTPServer.daemon_threads = True
    # File d'attente du noyau à 64, pas les 5 par défaut de socketserver : au
    # départ, les 10 voyageurs de (a) se connectent dans la même seconde ; une
    # demande de connexion refusée faute de place n'est renvoyée qu'après 1 s,
    # soit exactement le délai de connexion des essais (1 s) — d'où un
    # « ConnectTimeout » au hasard, environ 1 course sur 12. Le faux serveur ne
    # doit jamais être le goulet ; « --plein » garde sa propre file pleine.
    ThreadingHTTPServer.request_queue_size = 64
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Gestion)
    _publier(fichier_port, srv.server_address[1])
    srv.serve_forever()


def serveur_muet(fichier_port, journal):
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", 0))
    s.listen(64)
    _publier(fichier_port, s.getsockname()[1])
    gardees = []
    while True:
        c, _ = s.accept()
        gardees.append(c)   # jamais fermée, jamais de réponse
        _noter(journal, evenement="connexion acceptee")


def serveur_plein(fichier_port, journal):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(0)
    _publier(fichier_port, s.getsockname()[1])
    _noter(journal, evenement="ecoute sans accepter")
    while True:
        time.sleep(3600)


def _publier(fichier_port, port):
    with open(fichier_port + ".tmp", "w") as f:
        f.write(str(port))
    os.replace(fichier_port + ".tmp", fichier_port)


if __name__ == "__main__":
    fichier_port, journal = sys.argv[1], sys.argv[2]
    mode = sys.argv[3] if len(sys.argv) > 3 else ""
    {"--muet": serveur_muet, "--plein": serveur_plein}.get(mode, serveur_normal)(fichier_port, journal)
