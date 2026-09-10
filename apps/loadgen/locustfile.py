"""
Générateur de trafic pour train-ticket.

Il simule des voyageurs qui se connectent, cherchent un train, réservent, et
commandent un repas. Les adresses viennent du dépôt officiel
FudanSELab/train-ticket-auto-query, mais les NOMS DE CHAMPS et les DONNÉES ont
dû être corrigés : ce dépôt vise une autre version de l'application. Voir le
bloc d'avertissement plus bas — chaque écart rendait les parcours inopérants
sans lever la moindre erreur.

DEUX EXIGENCES DE L'EXPÉRIENCE, ET COMMENT ELLES SONT TENUES

1. Un débit RÉGULIER. Sans lui, la file monte et descend toute seule et l'on ne
   sait jamais si une variation vient d'une panne ou du hasard. C'est le rôle de
   « constant_pacing » : chaque voyageur virtuel démarre un parcours à intervalle
   fixe, au lieu d'attendre une durée tirée au hasard.

2. Un débit PILOTABLE. La première cause candidate d'un retard qui croît est une
   hausse de charge parfaitement légitime. Pour la reproduire, il faut pouvoir
   augmenter le nombre de voyageurs à un instant choisi, et noter cet instant.
   Locust le permet depuis sa page web ou par une simple requête, sans redémarrer.

CE QUI TRAVERSE LES FILES DE MESSAGES

Le parcours « réserver » est le plus important des quatre, car il alimente les
DEUX files à lui seul :
  - ts-preserve-service dépose dans la file « email » ;
  - et quand le voyageur commande un repas, ts-food-service dépose dans la file
    « food_delivery ».

TROIS PARCOURS SEULEMENT, ET C'EST VOLONTAIRE

Chaque parcours supplémentaire ajoute de la variance à la charge de référence.
Or la grandeur cherchée est un écart de quelques pour cent entre le débit
déposé et le débit retiré : plus la référence bouge, moins cet écart se voit.

Les parcours de consultation qui n'appellent qu'un seul service et ne touchent
aucune file ont donc été retirés — ils produisaient du volume sans produire ni
arête ni message.

  réserver un billet     poids 5   chaîne d'appels + alimente food_delivery
  chercher un train      poids 3   signal de charge en amont
  déclencher un courriel poids 2   alimente email
"""
import os
import random
from datetime import datetime, timedelta

from locust import HttpUser, task, constant_pacing, events

# Le rythme : un parcours toutes N secondes et par voyageur. C'est ce qui donne
# un débit stable, et donc une référence sur laquelle une dérive se mesure.
PACING = float(os.getenv("TT_PACING_SECONDS", "5"))

# Comptes de démonstration livrés avec train-ticket.
USERNAME = os.getenv("TT_USERNAME", "fdse_microservice")
PASSWORD = os.getenv("TT_PASSWORD", "111111")

# ATTENTION — ces valeurs ont été CONSTATÉES sur la grappe, pas reprises du
# dépôt officiel « train-ticket-auto-query », qui vise une autre version de
# l'application. Trois écarts ont été trouvés, et chacun rendait les parcours
# silencieusement inopérants :
#   • les champs s'appellent « startPlace » / « endPlace », et non
#     « startingPlace » / « endPlace » ;
#   • les gares s'écrivent en minuscules et sans espace : « shanghai », et non
#     « Shang Hai » ;
#   • la date doit être aujourd'hui ou plus tard — le service rejette toute date
#     passée, y compris celle des données d'exemple (2013-05-04).
# Sans ces trois corrections, l'application répondait « succès » avec une liste
# vide, et aucun parcours n'allait plus loin.
PLACE_PAIRS = [
    ("shanghai", "suzhou"),
]


def _date_du_jour() -> str:
    """Aujourd'hui : le service refuse toute date antérieure."""
    return datetime.now().strftime("%Y-%m-%d")


@events.quitting.add_listener
def _bilan(environment, **_):
    print("\n[loadgen] parcours terminés — voir Locust pour le détail\n")


class Voyageur(HttpUser):
    """Un voyageur virtuel. Locust en lance autant que tu le demandes."""

    wait_time = constant_pacing(PACING)

    # ---------------------------------------------------------------- session
    def on_start(self):
        self._connexion()

    def _connexion(self):
        """Connexion. Sans jeton, la plupart des parcours sont refusés."""
        self.token = None
        self.uid = None
        # Le premier appel pose les témoins de session attendus par la suite.
        self.client.get("/api/v1/verifycode/generate", name="00 code de vérification")
        r = self.client.post(
            "/api/v1/users/login",
            json={"username": USERNAME, "password": PASSWORD, "verificationCode": "1234"},
            name="01 connexion",
        )
        try:
            data = r.json().get("data") or {}
            self.token = data.get("token")
            self.uid = data.get("userId")
            if self.token:
                self.client.headers.update({"Authorization": f"Bearer {self.token}"})
        except Exception:
            pass

    # ------------------------------------------------------------------ jeton
    # Le jeton de connexion EXPIRE. Sans renouvellement, tous les appels
    # authentifiés basculent en 403 au bout d'un moment, et le générateur cesse
    # de produire du trafic utile : il produit des refus.
    #
    # C'est un piège grave pour ce travail, parce que le taux d'échec est une
    # grandeur portée par le nœud d'instance. Un jeton expiré ferait grimper ce
    # taux sans qu'aucune anomalie n'ait été injectée, et l'on attribuerait à
    # l'application un défaut qui vient du générateur.
    def _verifier(self, r):
        """Renouvelle la session si le serveur a refusé pour cause de jeton."""
        if r is not None and r.status_code in (401, 403):
            self._connexion()
            return False
        return True

    # ------------------------------------------------------------- parcours 1
    @task(3)
    def chercher_un_train(self):
        """Le parcours le plus courant : consulter les trains disponibles."""
        depart, arrivee = random.choice(PLACE_PAIRS)
        r = self.client.post(
            "/api/v1/travelservice/trips/left",
            json={
                "departureTime": _date_du_jour(),
                "startPlace": depart,
                "endPlace": arrivee,
            },
            name="10 chercher un train",
        )
        self._verifier(r)

    # ------------------------------------------------------------- parcours 2
    @task(5)
    def reserver(self):
        """
        LE parcours qui compte : il alimente les deux files.

        Il enchaîne quatre appels — chercher, lire ses contacts, éventuellement
        choisir un repas, puis réserver. C'est cette chaîne qui produit les
        relations d'appel entre services dans le graphe.
        """
        if not self.uid:
            return
        depart, arrivee = random.choice(PLACE_PAIRS)
        date = _date_du_jour()

        r = self.client.post(
            "/api/v1/travelservice/trips/left",
            json={"departureTime": date, "startPlace": depart, "endPlace": arrivee},
            name="10 chercher un train",
        )
        if not self._verifier(r):
            return
        trip_ids = []
        try:
            for t in (r.json().get("data") or []):
                tid = (t.get("tripId") or {})
                num = f"{tid.get('type','')}{tid.get('number','')}"
                if num:
                    trip_ids.append(num)
        except Exception:
            pass
        if not trip_ids:
            return

        rc = self.client.get(
            f"/api/v1/contactservice/contacts/account/{self.uid}",
            name="20 mes contacts",
        )
        if not self._verifier(rc):
            return
        contact_id = ""
        try:
            contacts = rc.json().get("data") or []
            if contacts:
                contact_id = random.choice(contacts).get("id", "")
        except Exception:
            pass
        if not contact_id:
            return

        charge = {
            "accountId": self.uid,
            "contactsId": contact_id,
            "tripId": random.choice(trip_ids),
            "seatType": random.choice([2, 3]),   # entier, pas chaîne
            "date": date,
            "from": depart,
            "to": arrivee,
            "assurance": 0,
            "foodType": 0,
        }

        # Un voyageur sur deux commande un repas : c'est ce choix qui remplit la
        # file « food_delivery ». L'autre moitié ne remplit que « email ».
        if random.random() < 0.5:
            charge.update(
                {
                    "foodType": 1,
                    "foodName": "Bone Soup",
                    "foodPrice": 2.5,
                    "stationName": depart,
                    "storeName": "Roman Holiday",
                }
            )

        self.client.post(
            "/api/v1/preserveservice/preserve",
            json=charge,
            name="30 réserver un billet",
        )

    # ------------------------------------------------------------- parcours 3
    @task(2)
    def declencher_un_courriel(self):
        """
        Alimente la SECONDE file, « email ».

        Pourquoi un point d'entrée de test plutôt que le parcours naturel : dans
        cette version de train-ticket, l'envoi du courriel de confirmation est
        DÉSACTIVÉ. Le code existe, mais l'appel est mis en commentaire par les
        auteurs, dans ts-preserve-service comme dans ts-preserve-other-service :

            // TODO: change to async message serivce
            // sendEmail(notifyInfo, headers);

        Sans ce parcours, la file « email » resterait donc éternellement vide,
        avec un consommateur connecté qui n'a jamais rien à faire. Or les deux
        files sont nécessaires pour montrer qu'elles sont mesurées séparément.
        """
        self._verifier(self.client.get(
            "/api/v1/notifyservice/test_send_mq",
            name="60 déclencher un courriel",
        ))
