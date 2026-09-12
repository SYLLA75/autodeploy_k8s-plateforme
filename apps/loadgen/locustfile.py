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

Deux parcours déposent dans « food_delivery », par le même service et le même
message :
  - « commander un repas » — un seul appel, direct, à ts-food-service. C'est
    LUI qui fixe le débit de la file : un appel par voyageur et par rythme,
    donc un débit proportionnel au nombre de voyageurs.
  - « réserver un billet » — la chaîne complète (chercher, contacts, réserver),
    où un voyageur sur deux commande un repas au passage. C'est elle qui
    produit les relations d'appel entre services.
Et « déclencher un courriel » alimente « email ».

POURQUOI LE DÉBIT DE LA FILE NE PEUT PAS VENIR DE LA RÉSERVATION SEULE

Mesuré sur une référence d'une heure : à 10, 30 puis 55 voyageurs, la file
recevait 0,5 puis 0,5 puis 0,25 message par seconde. Le débit ne suit pas les
voyageurs, il BAISSE. Une réservation passe par la recherche de train, l'appel
lourd de l'application ; dès 10 voyageurs elle ralentit, et à 55 chaque
voyageur réserve moins qu'à 10. Avec ce seul parcours, « plus de charge en
amont » ne peut pas exister, et la référence oscille du simple au quadruple.
D'où le parcours direct, et des poids qui gardent la recherche à un niveau que
l'application tient encore à 50 voyageurs.

QUATRE PARCOURS, ET C'EST VOLONTAIRE

Chaque parcours supplémentaire ajoute de la variance à la charge de référence.
Or la grandeur cherchée est un écart de quelques pour cent entre le débit
déposé et le débit retiré : plus la référence bouge, moins cet écart se voit.
Les parcours de consultation qui n'appellent qu'un seul service et ne touchent
aucune file ont été retirés — du volume sans arête ni message.

  commander un repas     poids 6   alimente food_delivery, débit ∝ voyageurs
  réserver un billet     poids 2   chaîne d'appels + un repas sur deux
  chercher un train      poids 1   signal de charge en amont
  déclencher un courriel poids 1   alimente email

Avec un rythme de 5 s : 0,12 message/s par voyageur pour food_delivery,
soit 3 messages/s à 25 voyageurs et 6 à 50. Les poids se règlent par
TT_POIDS_REPAS, TT_POIDS_RESERVER, TT_POIDS_CHERCHER, TT_POIDS_COURRIEL.
"""
import os
import random
import time
import uuid
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

# Durée après laquelle un voyageur se reconnecte, sans attendre l'expiration.
# Le jeton de train-ticket vit une heure ; vingt minutes laissent une marge large
# et le coût est négligeable — une connexion par voyageur toutes les 20 minutes.
SESSION_TTL = float(os.getenv("TT_SESSION_TTL_SECONDS", "1200"))


# Les dates de départ : de JOURS_AVANCE à JOURS_AVANCE + JOURS_ETALEMENT - 1
# jours après aujourd'hui, tirées au hasard. Une seule liaison, un seul train :
# tout ce qui est réservé s'empile sur « ce train, cette date », et le service
# des commandes recharge et journalise la pile entière à chaque recherche.
# Mesuré : à ~150 commandes par date (30 jours d'étalement, 1 h de campagne),
# il sature son CPU et les parcours s'allongent jusqu'à 88 s ; à 365 jours,
# une campagne de 2 h 15 laisse ~25 commandes par date.
JOURS_AVANCE = int(os.getenv("TT_JOURS_AVANCE", "1"))
JOURS_ETALEMENT = int(os.getenv("TT_JOURS_ETALEMENT", "365"))

# Les poids des parcours — voir l'en-tête pour ce qu'ils fixent.
POIDS_REPAS = int(os.getenv("TT_POIDS_REPAS", "6"))
POIDS_RESERVER = int(os.getenv("TT_POIDS_RESERVER", "2"))
POIDS_CHERCHER = int(os.getenv("TT_POIDS_CHERCHER", "1"))
POIDS_COURRIEL = int(os.getenv("TT_POIDS_COURRIEL", "1"))

# Le repas commandé, identique pour tous : la référence n'a pas à varier là.
REPAS = {"foodType": 2, "foodName": "Bone Soup", "price": 2.5,
         "storeName": "Roman Holiday"}


def _date_de_depart() -> str:
    """
    La date cherchée : un jour au hasard dans l'année qui vient, jamais
    aujourd'hui.

    Jamais aujourd'hui : le service refuse les dates passées, mais il écarte
    aussi les trains dont l'heure de départ est déjà dépassée. Chercher
    « aujourd'hui » rend donc une liste vide dès la fin de journée — mesuré :
    0 trajet le 10 au soir, 1 à 3 le lendemain, pour les mêmes gares. Le
    parcours de réservation s'arrêtait alors sans erreur et sans trace.

    Étalé sur un mois : pour compter les places vendues, le service des sièges
    charge en mémoire TOUTES les commandes du train à cette date. Avec une seule
    date, elles s'y accumulent toutes — mesuré : 5 000 commandes sur le même
    train le même jour, et le service des commandes s'est figé. Des voyageurs
    qui partent des jours différents répartissent les commandes sur trente
    dates.
    """
    jours = JOURS_AVANCE + random.randrange(max(1, JOURS_ETALEMENT))
    return (datetime.now() + timedelta(days=jours)).strftime("%Y-%m-%d")


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
        """
        Connexion. Sans jeton, la plupart des parcours sont refusés.

        L'EN-TÊTE EST EFFACÉ D'ABORD. Il vit sur la SESSION, pas sur la requête :
        sans cet effacement, la requête de reconnexion emporte elle-même le jeton
        périmé, le serveur la rejette, et plus aucune connexion ne peut aboutir.
        Constaté sur une campagne entière — « JWT expired at 02:27:17Z, current
        time 03:50:21Z » — pendant laquelle ts-auth-service a répondu 100 %
        d'erreurs et aucun parcours n'est allé au-delà de sa première ligne.
        """
        self.token = None
        self.uid = None
        self.client.headers.pop("Authorization", None)
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
                self.connecte_a = time.monotonic()
        except Exception:
            pass

    # ------------------------------------------------------------------ jeton
    # Le jeton de connexion EXPIRE, et c'est un piège grave pour ce travail : le
    # taux d'échec est une grandeur portée par le nœud d'instance. Un jeton périmé
    # le ferait grimper sans qu'aucune anomalie n'ait été injectée, et l'on
    # attribuerait à l'application un défaut qui vient du générateur.
    #
    # LE RENOUVELLEMENT EST PRÉVENTIF, PAS RÉACTIF. La version précédente
    # attendait un 401 ou un 403 pour se reconnecter. Or l'application ne répond
    # ni l'un ni l'autre : l'exception de jeton périmé remonte jusqu'à Tomcat, qui
    # rend un 500. Le garde-fou existait donc mais ne se déclenchait jamais.
    #
    # Réagir au 500 serait pire encore : pendant une injection de panne, les 500
    # sont attendus, et le générateur se reconnecterait sans cesse en plein
    # milieu de la mesure. On se reconnecte donc à l'heure, avant l'expiration,
    # sans rien déduire du code de réponse.
    def _session_fraiche(self):
        """Reconnexion préventive, avant que le jeton n'expire."""
        age = time.monotonic() - getattr(self, "connecte_a", 0.0)
        if self.token is None or age > SESSION_TTL:
            self._connexion()

    def _verifier(self, r):
        """Filet de sécurité : un refus explicite déclenche une reconnexion."""
        if r is not None and r.status_code in (401, 403):
            self._connexion()
            return False
        return True

    # ------------------------------------------------------------- parcours 1
    @task(POIDS_REPAS)
    def commander_un_repas(self):
        """
        Le parcours qui fixe le débit de « food_delivery ».

        Un seul appel : ts-food-service enregistre la commande et dépose le
        message de livraison dans la file — exactement ce que fait la
        réservation quand le voyageur prend un repas, sans la recherche de
        train devant. Le service exige seulement un numéro de commande inédit
        (un identifiant unique), il ne le vérifie pas auprès du service des
        commandes.
        """
        self._session_fraiche()
        depart, _ = random.choice(PLACE_PAIRS)
        charge = dict(REPAS, orderId=str(uuid.uuid4()), stationName=depart)
        self._verifier(self.client.post(
            "/api/v1/foodservice/orders",
            json=charge,
            name="40 commander un repas",
        ))

    # ------------------------------------------------------------- parcours 2
    @task(POIDS_CHERCHER)
    def chercher_un_train(self):
        """Le parcours le plus courant : consulter les trains disponibles."""
        self._session_fraiche()
        depart, arrivee = random.choice(PLACE_PAIRS)
        r = self.client.post(
            "/api/v1/travelservice/trips/left",
            json={
                "departureTime": _date_de_depart(),
                "startPlace": depart,
                "endPlace": arrivee,
            },
            name="10 chercher un train",
        )
        self._verifier(r)

    # ------------------------------------------------------------- parcours 3
    @task(POIDS_RESERVER)
    def reserver(self):
        """
        La chaîne complète : elle produit les relations d'appel du graphe, et
        alimente les deux files au passage.

        Il enchaîne quatre appels — chercher, lire ses contacts, éventuellement
        choisir un repas, puis réserver. C'est cette chaîne qui produit les
        relations d'appel entre services dans le graphe.
        """
        self._session_fraiche()
        if not self.uid:
            return
        depart, arrivee = random.choice(PLACE_PAIRS)
        date = _date_de_depart()

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

    # ------------------------------------------------------------- parcours 4
    @task(POIDS_COURRIEL)
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
        self._session_fraiche()
        self._verifier(self.client.get(
            "/api/v1/notifyservice/test_send_mq",
            name="60 déclencher un courriel",
        ))
