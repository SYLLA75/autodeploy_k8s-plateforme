# Extraire les chiffres du graphe — explications

> Document de travail, écrit en mots simples.
> Il explique **ce qu'on installe, pourquoi, et dans quel ordre**.
> Il est mis à jour au fur et à mesure. La dernière section est un journal.

---

## 1. Ce qu'on veut obtenir

On veut, pour chaque tranche de temps, **une carte du système avec des chiffres dessus**.

Sur la carte, trois sortes de ronds et quatre sortes de flèches :

```
   ( copie de service ) ──── appelle ────▶ ( copie de service )
            │                                        │
         dépose                                   retire
            │                                        │
            ▼                                        │
   [ file de messages ] ─────────────────────────────┘
            
   ( copie de service ) ─ ─ tourne sur ─ ─▶ [ machine ]
```

Chaque rond porte des chiffres. Chaque flèche aussi (sauf « tourne sur », qui ne
porte rien : elle dit seulement qui partage quelle machine).

**Ce document ne parle que d'une chose : faire exister ces chiffres.**
Pas de modèle, pas d'apprentissage. Juste : les chiffres existent-ils, et
peut-on les lire ?

---

## 2. D'où viennent les chiffres

Il y a exactement **deux sources**, et elles ne se remplacent pas.

**Les notes des programmes.** Chaque fois qu'un programme fait quelque chose, il
peut écrire une note : « à 10h00m03s, j'ai déposé un message dans la file
*livraisons*, ça m'a pris 4 millisecondes ». Ces notes s'appellent des *traces*.

> ⚠️ Un programme n'écrit pas ces notes tout seul. Il faut lui **attacher un
> mouchard**. Sans ça, il est muet.

**Les compteurs.** La machine, Kubernetes et le courtier de messages tiennent des
compteurs : mémoire restante, processeur utilisé, nombre de lettres en attente.
Ce sont les *métriques*.

> ⚠️ Ces compteurs ne se lisent pas tout seuls non plus. Il faut un programme qui
> passe les relever régulièrement.

**Règle simple à retenir :**

| Ce qu'on veut savoir | Source |
|---|---|
| Qui a fait quoi, et vers qui | les notes des programmes |
| Comment va chaque composant | les compteurs |

---

## 3. Ce qu'on a découvert sur la grappe

Ces constats ne viennent pas de la documentation. Ils ont été **vérifiés
directement sur le cluster**, et ce sont eux qui justifient les choix qui suivent.

### 3.1 Presque rien n'était en place

Ce qui existait venait entièrement du paquet `otel-demo`. C'était un accident :
si on retire cette application, il ne reste rien. C'est pourquoi on installe
maintenant une pile **à nous**, qui ne dépend d'aucune application.

| Vérifié | Constat |
|---|---|
| Mouchard des machines | **absent** |
| Mouchard de Kubernetes | **absent** |
| Cadence de relevé | **1 fois par minute** — beaucoup trop lent |
| Conservation | 7 jours, sans disque, effacé à la destruction |
| Notes de train-ticket | **aucune** — 0 pod sur 56 est équipé |

### 3.2 Le courtier de messages donne moins que prévu

On a interrogé RabbitMQ directement. Résultat :

**Bonne nouvelle** — le greffon de mesure est **déjà actif**. Il n'y a que le
port à ouvrir. Et il donne bien, **par file** :

- le nombre de lettres en attente
- le nombre de lettres délivrées non acquittées
- le nombre de consommateurs connectés

**Mauvaise nouvelle** — les compteurs de **flux** (combien de lettres déposées,
combien retirées) existent, mais **pour tout le courtier**, pas par file :

```
rabbitmq_queue_messages_ready{queue="food_delivery"}    ← par file ✅
rabbitmq_queue_messages_published_total                 ← sans file ❌
rabbitmq_channel_messages_delivered_total               ← sans file ❌
```

**Conséquence, et elle est importante :**

> Le débit déposé, le débit retiré, et donc **l'écart entre les deux — le chiffre
> central de la thèse — n'ont aucune source côté courtier.**
> Ils ne peuvent venir que des notes des programmes.

C'est pour ça qu'équiper train-ticket n'est plus une option : c'est la condition
d'existence du chiffre principal.

### 3.3 Train-ticket a déjà la tuyauterie, mais pas le bon mouchard

Train-ticket propose une option `--with-tracing`. Elle installe **SkyWalking**,
qui est un autre outil, avec son propre vocabulaire.

Ça ne convient pas, pour deux raisons :

1. SkyWalking ne note pas l'identité Kubernetes de la copie. Or **distinguer deux
   copies d'un même programme**, c'est le cas central du travail.
2. Tout le vocabulaire des documents est celui d'OpenTelemetry. Deux vocabulaires
   = plus rien de comparable.

**Mais** — et c'est une très bonne nouvelle — le mécanisme d'attachement du
mouchard est déjà écrit dans les manifestes de train-ticket. Il ne reste qu'à
échanger le mouchard. Et les pods portent déjà la variable `NODE_IP`, qui est
exactement ce dont on a besoin pour leur dire où envoyer les notes.

---

## 4. Les briques, et pourquoi chacune

### Brique 1 — Une pile à nous, qui ne dépend de rien

Trois morceaux :

**Le collecteur sur chaque machine.** Son rôle unique et irremplaçable :
**poser l'identité**. Une note brute dit « j'ai traité un message en 18 ms ».
Elle ne dit pas *qui*. Le collecteur ajoute le nom du service, l'identifiant
unique de la copie, et le nom de la machine.

> Sans lui, on a des chiffres mais on ne sait pas à quel rond les attacher.
> Et la flèche « tourne sur » n'a aucune source.

**La passerelle, en un seul exemplaire.** C'est elle qui écrit l'archive des
notes sur disque. Un seul écrivain = un seul fichier. Si chaque machine écrivait
la sienne, il faudrait recoller six morceaux.

**Le magasin de traces.** Pour pouvoir regarder à l'œil pendant les essais.
Avec un disque, pas en mémoire — l'ancien perdait tout au-delà de 25 000 notes.

### Brique 2 — Le mouchard des machines

Absent aujourd'hui. Il produit les 5 chiffres du rond « machine ».

Le plus important d'entre eux : le **temps passé à attendre**. Ce n'est pas la
même chose que le taux d'utilisation. Une machine peut tourner à 90 % sans que
personne n'en souffre. Ce qui caractérise la saturation, c'est le temps qu'un
programme passe à attendre son tour.

### Brique 3 — Le mouchard de Kubernetes

Absent aussi. Il sert à deux choses, dont une non évidente :

1. compter les redémarrages ;
2. **faire le pont entre deux mondes.** Les compteurs des conteneurs sont
   étiquetés « namespace + nom du pod ». L'identité qu'on a choisie est « nom de
   service + identifiant unique ». Ce mouchard est le seul à porter les deux à
   la fois.

> Sans ce pont, aucun chiffre de ressource ne peut être rattaché à un rond.

### Brique 4 — Ouvrir le port de mesure du courtier

Le greffon est déjà actif, le port répond, mais il n'est déclaré nulle part :
personne ne peut l'atteindre.

**On ne touche qu'au Service, pas au programme.** Déclarer un port dans le
programme est purement décoratif — il écoute déjà — et modifier le programme
provoquerait un redémarrage, donc un **nouvel identifiant de copie**, donc une
rupture dans le suivi du rond d'une minute à l'autre. On évite.

On lit le point d'accès « par objet », le seul qui distingue les files. Le point
d'accès par défaut mélange tout le courtier.

### Brique 5 — Équiper train-ticket *(à venir)*

Attacher le mouchard OpenTelemetry aux services, sur le mécanisme déjà présent.

→ débloque **toutes les flèches**, et les débits des files qui n'ont pas d'autre
source.

⚠️ Java 1.8.0_111 (2016) : à essayer sur **un seul service** avant les 46.

### Brique 6 — Les réglages qui faussent en silence

Ce sont des détails d'apparence. Chacun casse quelque chose sans prévenir.

| Réglage | Ce qui casse sans lui |
|---|---|
| Cadence de relevé rapide | Une seule mesure par tranche de temps : ni min, ni max, ni pente calculables |
| `OTEL_SEMCONV_STABILITY_OPT_IN=messaging` | Les deux files fusionnent en un seul rond, **sans message d'erreur** |
| Versions figées | Deux lancements n'installent pas la même chose |

*(le troisième point sera traité quand la pile sera stabilisée)*

### Brique 7 — Sortir les données avant de rendre la grappe *(à venir)*

Les disques vivent sur les machines réservées. Quand la réservation se termine,
tout part. Il faut un script d'export appelé **avant** la destruction.

---

## 5. Les choix, et pourquoi ceux-là

**Pourquoi Prometheus et pas les relevés d'OpenTelemetry ?**
Parce que les noms de compteurs écrits dans les documents (`container_...`,
`node_...`) sont les noms de Prometheus. Les relevés d'OpenTelemetry donnent les
mêmes chiffres sous d'autres noms. Prendre Prometheus évite de devoir réécrire
tous les tableaux d'attributs.

**Pourquoi Jaeger écrit en manifeste brut et pas en paquet Helm ?**
Parce que la forme des réglages du paquet change souvent. Quarante lignes qu'on
maîtrise sont plus stables qu'un paquet dont le schéma bouge.

**Pourquoi un collecteur sur chaque machine ET une passerelle ?**
Le collecteur de machine pose l'identité — il doit être près des programmes.
La passerelle écrit l'archive — elle doit être unique. Deux rôles, deux endroits.

**Pourquoi les programmes envoient à `http://$(NODE_IP):4318` ?**
Parce que c'est portable. Le programme parle à sa propre machine, sans avoir à
connaître le moindre nom de service. Et train-ticket possède **déjà** cette
variable dans tous ses pods.

**Pourquoi aucun nom en dur ?**
Le courtier est cherché par motif, les files sont lues et non devinées, tous les
réglages sont des variables. Le code doit marcher sur une autre grappe que la
nôtre.

**Pourquoi pas de fenêtre d'une minute écrite dans le code ?**
La largeur de la tranche de temps, le pas de glissement et l'horizon sont des
**choix d'expérience**, pas des constantes de programme. Ils seront tranchés plus
tard, sur données. Le code se contente de relever assez souvent pour que
n'importe quel choix reste possible.

---

## 6. Comment s'en servir

```bash
# depuis le master
bash ~/autodeploy/apps/observability.sh install    # pose la pile
bash ~/autodeploy/apps/observability.sh verify     # inventaire d'extraction
bash ~/autodeploy/apps/observability.sh urls       # adresses web
bash ~/autodeploy/apps/observability.sh uninstall  # retire tout
```

`verify` est le plus utile : il répond, grandeur par grandeur, à la question
*« existe-t-elle vraiment, maintenant, sur cette grappe ? »*. C'est la fiche de
relevé du protocole de vérification, exécutée par le code au lieu d'être remplie
à la main.

---

## 7. Où on en est

| Brique | État |
|---|---|
| 1 — Pile autonome | **installée et vérifiée** |
| 2 — Mouchard des machines | **installé et vérifié** |
| 3 — Mouchard de Kubernetes | **installé et vérifié** |
| 4 — Port du courtier | **ouvert et vérifié** |
| 5 — Équiper train-ticket | **46 sur 46** — tous parlent |
| 8 — Générateur de trafic | **posé et vérifié** — 0 % d'échec |
| 6 — Réglages | cadence faite ; conventions avec la brique 5 |
| 7 — Export | à faire |

### Résultat de l'inventaire d'extraction

Sortie réelle de `observability.sh verify`, exécutée sur la grappe :

```
--- Noeud MACHINE (5 composantes) ---
attente processeur (pression noyau)        PRESENT  (7 series)
attente memoire (pression noyau)           PRESENT  (14 series)
attente entrees-sorties (pression noyau)   PRESENT  (14 series)
memoire disponible                         PRESENT  (7 series)
occupation processeur                      PRESENT  (224 series)

--- Noeud INSTANCE, etat des ressources ---
etranglement processeur (numerateur)       PRESENT  (108 series)
etranglement processeur (denominateur)     PRESENT  (108 series)
usage processeur                           PRESENT  (384 series)
memoire occupee                            PRESENT  (385 series)
limite memoire declaree                    PRESENT  (764 series)
redemarrages                               PRESENT  (246 series)

--- Noeud INSTANCE, signal de transport ---
paquets perdus en reception                PRESENT  (686 series)
paquets perdus en emission                 PRESENT  (686 series)
erreurs de reception                       PRESENT  (688 series)
octets recus                               PRESENT  (688 series)

--- Pont entre les traces et les metriques ---
identifiant de pod + machine               PRESENT  (110 series)

--- Noeud FILE (famille file classique) ---
niveau d'accumulation par file             PRESENT  (2 series)
nombre de consommateurs par file           PRESENT  (2 series)
messages delivres non acquittes            PRESENT  (2 series)

--- Traces ---
services applicatifs qui emettent          ABSENT   (aucun service equipe)
```

**Lecture.** Tout ce qui vient des compteurs existe désormais. Tout ce qui vient
des notes des programmes est encore absent, parce qu'aucun programme n'est
équipé.

Ce qui est extractible **maintenant** :

- les 5 chiffres de chaque machine ✅
- les chiffres de ressource et de réseau de chaque copie ✅
- le niveau, les non-acquittés et le nombre de consommateurs de chaque file ✅
- le pont entre les copies et les machines ✅

Ce qui reste hors d'atteinte tant que la brique 5 n'est pas faite :

- les durées de traitement, les débits, les taux d'échec ❌
- **les quatre sortes de flèches** ❌
- **les débits déposé et retiré des files, et leur écart** ❌

Autrement dit : **la moitié « compteurs » est finie, la moitié « notes » n'a pas
commencé.** Et c'est la seconde qui porte le chiffre central du travail.

---

## 8. Journal

**Suppression d'otel-demo.** Retiré à la demande, pour éviter les collisions et
libérer les machines. Le cluster passe de 127 à 92 pods. Conséquence assumée :
plus aucun collecteur, plus aucun Prometheus, plus aucun Jaeger — c'est
exactement ce que la brique 1 remplace, mais en autonome cette fois.

**Vérification V1 exécutée.** Point d'accès du courtier : `/metrics/per-object`
sur le port 15692, préfixe `rabbitmq_`, étiquettes `{vhost, queue}`.
Deux files existent : `food_delivery` et `email`, un consommateur chacune.
Résultat marquant : les compteurs de flux ne portent pas d'étiquette de file.

**Constat sur l'instrumentation.** Jaeger ne connaissait que 21 services, tous
appartenant à otel-demo. Aucun des 56 pods de train-ticket n'est équipé, aucun
conteneur d'amorçage, aucune variable de mouchard.

**Version de Java.** 1.8.0_111. À surveiller au moment d'attacher le mouchard.

**Essai d'instrumentation — réussi.** Le mouchard a été attaché à la paire
`ts-food-service` (dépose) et `ts-delivery-service` (retire), les deux bouts de
la file `food_delivery`. L'agent version 2.31.1 se charge sans problème sur Java
1.8.0_111 : le risque principal est levé.

Ce que les notes portent réellement, relevé sur la grappe :

```
messaging.system            = rabbitmq
messaging.destination.name  = food_delivery      ← le VRAI nom, pas « <default> »
messaging.operation.type    = send        (le producteur)
messaging.operation.type    = process     (le consommateur)
k8s.pod.uid                 = 0e655f37-…         ← l'identité de la copie
k8s.node.name               = workers2 / workers3 ← la machine
k8s.namespace.name          = train-ticket
```

Traduction : l'identité d'une copie, l'identité d'une file, l'identité d'une
machine, et de quoi séparer les dépôts des retraits — **tout ce qu'il faut pour
tracer les quatre sortes de flèches est là.**

À noter au passage : les valeurs sont `send` et `process`, pas `publish` et
`deliver`. Ce sont les nouveaux noms. Un traitement qui filtrerait sur les
anciennes valeurs ne trouverait rien.

**Le registre d'images de GitHub est bloqué sur SLICES-RI.** La première tentative
a échoué : `403 Forbidden`. Le script propose donc deux voies, et prend par défaut
celle qui télécharge l'agent depuis le dépôt public de bibliothèques Java —
joignable, lui, comme GitHub. C'est une leçon de portabilité : ne jamais supposer
qu'un registre est accessible.

**Une erreur de ma part, et sa correction.** Le port de mesure du courtier avait
été ajouté avec une fusion simple. Or ce type de fusion **remplace** une liste au
lieu de la compléter : le port applicatif a disparu, et le courtier est devenu
injoignable — tous les producteurs et consommateurs en échec, sans que le lien
avec l'opération soit visible. Réparé, et le script procède désormais par ajout
explicite en fin de liste, en nommant au passage les ports qui ne l'étaient pas
(Kubernetes l'exige dès qu'il y en a plusieurs).

La leçon vaut d'être gardée : **une opération qui a l'air d'ajouter peut
retrancher.** Sur une grappe d'expérience, cela se traduirait par une campagne
entière de données vides.

**Démonstration d'accumulation, réussie.** On a arrêté le service qui vide la
file `food_delivery`, envoyé 15 commandes, puis remis le service en marche :

```
AVANT     food_delivery   0 message    1 consommateur
PENDANT   food_delivery  15 messages   0 consommateur   ← le tas grossit
          email           0 message    1 consommateur   ← l'autre file ne bouge pas
APRES     food_delivery   0 message    1 consommateur   ← rattrapé
```

Deux choses à retenir. D'abord, chaque file est mesurée séparément : c'est ce qui
permet d'avoir un rond par file. Ensuite, et c'est le cœur du sujet, le service
qui dépose a répondu **200 (succès) à chacune des 15 commandes** pendant que
personne ne traitait rien. Aucune erreur, aucune alerte, et pourtant le système
allait déjà mal. C'est exactement la panne visée par le travail, reproduite en
deux minutes et réversible.

**Les deux files sont maintenant couvertes.** Cinq services parlent :
`ts-food-service` et `ts-delivery-service` pour `food_delivery` ;
`ts-preserve-service`, `ts-preserve-other-service` et `ts-notification-service`
pour `email`. Sur 46 services, seuls ces cinq touchent une file — les 41 autres
se parlent directement.

**Place disponible avant d'équiper les 41 autres.** 26,6 Go libres sur la grappe,
machines entre 62 % et 74 %. Le besoin estimé est d'environ 4,1 Go (une centaine
de mégaoctets par observateur). La marge est confortable.

**Les 46 services parlent.** Tous les pods tournent, aucune anomalie, mémoire
entre 59 % et 75 %. Jaeger connaît 42 services contre zéro le matin même.

**Le fil de la trace traverse la file.** En reconstruisant les liens depuis les
notes, on trouve `ts-food-service → ts-delivery-service`. Or ces deux services ne
s'appellent jamais directement : ils ne communiquent que par la file. La note du
consommateur est donc rattachée à celle du producteur, dans une même histoire.

C'est un résultat pour la section 2 du travail, qui envisage deux façons de relier
producteur et consommateur et affirme que l'argument tient dans les deux cas. On
sait désormais dans laquelle on se trouve, par constat et non par hypothèse.

**Ce que contient réellement une note, vérifié sur trafic réel.** Sur un service
où l'appel aboutit, on relève : `http.request.method`, `http.response.status_code`,
`http.route`, `url.path`, `server.address`, le lien parent-enfant, la durée, et
les attributs de messagerie. Tous les noms employés dans la carte sont donc
constatés, aucun n'est repris d'une documentation.

**Un bonus non prévu : les appels à la base de données.** L'agent capture aussi
`DeliveryRepository.save`, `SELECT ts.delivery`, `INSERT ts.delivery`,
`Transaction.commit`. Ce n'est pas dans les documents de travail, et c'est offert.
Cela pourrait servir : quand un service ralentit, savoir si le retard vient de lui
ou de sa base change le diagnostic.

**Le manque qui reste, et il est net : personne ne fait travailler l'application.**
Un premier essai de trafic n'a produit qu'une seule flèche, non pas à cause de la
collecte mais parce que les appels de test étaient trop simples ou n'aboutissaient
pas. Réserver un billet enchaîne une dizaine de services ; demander la liste des
gares n'en enchaîne aucun.

Train-ticket ne fournit aucun générateur de charge dans son dépôt. Sans lui, le
graphe restera presque vide quelle que soit la qualité de la collecte. C'est
désormais le premier manque, devant la sauvegarde.

**Accès aux interfaces : un piège à connaître.** Les VMs de SLICES-RI n'ont pas
d'adresse publique, il faut donc un tunnel. Mais la forme habituelle du tunnel,
celle qui vise `localhost` du côté distant, **échoue ici sans message d'erreur**.

Constaté sur la grappe : le port répond sur l'adresse réelle du nœud, pas sur
l'interface locale.

```
jaeger via 127.0.0.1      →  échec
jaeger via 10.10.221.123  →  200
```

La cible du tunnel doit donc être l'adresse du nœud :

```
ssh -N -L 16686:<IP du master>:30686 -L 9090:<IP du master>:<port> master
```

Le script affiche désormais la bonne commande tout seul. Cela vaut aussi pour les
autres interfaces exposées par le dépôt : les exemples du README qui visent
`localhost` sont à revoir.

## Le générateur de trafic

Déployé dans son propre espace `loadgen`, **non instrumenté** : c'est le monde
extérieur, pas un service du système étudié. Il est donc exclu d'office de toutes
les mesures, qui filtrent sur l'espace `train-ticket`.

**Trois erreurs dans le dépôt officiel des parcours.** `train-ticket-auto-query`
vise une autre version de l'application. Chaque écart rendait les parcours
inopérants **sans lever la moindre erreur** :

| Ce que le dépôt officiel envoie | Ce que cette version attend |
|---|---|
| `startingPlace` | `startPlace` |
| `"Shang Hai"`, `"Su Zhou"` | `shanghai`, `suzhou` |
| la date des données d'exemple (2013-05-04) | aujourd'hui ou plus tard |

Le plus vicieux : avec les mauvais champs, l'application répondait
`{"status":1,"msg":"Success","data":[]}`. Un succès, une liste vide, aucune
erreur. **Cela mérite une ligne de plus dans le protocole de vérification :
constater qu'un appel de test produit un résultat NON VIDE, et pas seulement un
code 200.**

**Résultat après correction**, sur 10 voyageurs à un parcours toutes les 5 s :

```
parcours                        nb   échecs   médiane
10 chercher un train           147        0     190 ms
20 mes contacts                 46        0      13 ms
30 réserver un billet           46        0     500 ms
40 mes commandes                33        0      10 ms
50 les trajets                  15        0      22 ms
                        2,6 requêtes/s, 0 % d'échec
```

**Le graphe se remplit.** 22 flèches distinctes entre 17 services, là où il n'y
en avait qu'une. La chaîne de réservation est complète :

```
ts-gateway ─▶ ts-preserve ─▶ ts-travel ─▶ ts-seat ─▶ ts-order
                  ├─▶ ts-security   ├─▶ ts-config
                  ├─▶ ts-contacts   └─▶ ts-basic ─▶ ts-station / ts-route / ts-price
                  └─▶ ts-user
```

Et la traversée de file `ts-food-service → ts-delivery-service`, 80 fois, avec
122 notes portant `food_delivery`.

**Découverte gênante : la file `email` est morte dans cette version.** L'appel qui
la remplit est mis en commentaire par les auteurs, aux deux endroits où il devrait
avoir lieu :

```java
// TODO: change to async message serivce
// sendEmail(notifyInfo, headers);
```

La file existe, elle est déclarée, un consommateur y est connecté — et personne
n'y dépose jamais rien. Un point d'entrée de test, `test_send_mq`, permet de
l'alimenter, et il a été ajouté aux parcours. Sans cela, l'une des deux files
serait éternellement vide, ce qui empêcherait de montrer qu'elles sont mesurées
séparément.

À signaler dans le dispositif expérimental : le trafic de la file `email` est
**provoqué par un point d'entrée de test**, pas produit par un parcours
utilisateur naturel. Et le message envoyé est la chaîne littérale `test`, que le
consommateur rejette faute de pouvoir la lire. Le dépôt et le retrait ont bien
lieu — ce qui suffit pour mesurer les débits — mais le traitement échoue. Cela
doit être déclaré, car un taux d'échec de cent pour cent sur une file n'est pas
un régime nominal.

## Ce que produit la chaîne complète

Vérifié sur la grappe, archive à l'appui :

```
/archive/spans.jsonl        98 Mo, en croissance

notes portant une destination :
   food_delivery    480
   email            234
```

L'archive contient les identités de copie posées par le collecteur
(`ts-user-service-5cf6895d5-z6wns`), les attributs de messagerie, les liens
parent-enfant et les durées. C'est le jeu de données, et il se constitue tout
seul tant que le générateur tourne.

## Isolement de la chaîne de mesure

**Le problème.** Le nœud « machine » du graphe porte l'état de la machine
entière, tous pods confondus. C'est voulu : la troisième cause candidate est un
voisin qui sature la machine, et ce voisin n'est pas forcément modélisé. Ne
compter que l'application reviendrait à être aveugle au cas même qu'on cherche.

Mais cela crée un défaut de méthode : **la chaîne de mesure devient elle-même le
voisin bruyant.** Ce n'est pas théorique. La visionneuse de traces a atteint deux
gigaoctets, s'est fait tuer, et a fait passer son nœud en pression mémoire — ce
qui a marqué le nœud et empêché son propre replacement. Pire : une injection de
saturation mémoire aurait tué le magasin de métriques au moment précis où l'on
en avait besoin.

Mesuré avant correction :

```
train-ticket     56 pods   1014 m CPU   23 434 Mi
kube-system      35 pods    348 m CPU    2 287 Mi
observabilité    17 pods    148 m CPU    2 016 Mi   dont jaeger 850, prometheus 490
```

**Le correctif.** Un nœud est réservé à la mesure (`workers1`) : marqué, puis
interdit aux pods applicatifs. Les composants lourds y sont épinglés, et les
sept pods applicatifs qui s'y trouvaient ont été relancés ailleurs.

```
workers1            jaeger · prometheus · kube-state-metrics · passerelle · locust
workers0/2/3/4/5    train-ticket seul
master              relevé de machine seul
```

Deux exceptions, par nature : le relevé de machine et le collecteur de spans
restent sur **tous** les nœuds. Le premier mesure chaque machine ; le second
reçoit les spans à l'adresse du nœud local. Une tolérance a dû être ajoutée au
collecteur, sans quoi le nœud réservé n'aurait plus rien collecté.

**Un coût à connaître.** Le stockage local cloue un volume à un nœud. Isoler
après coup oblige donc à recréer les volumes situés ailleurs, et leur contenu
est perdu. L'historique des métriques et l'index des traces y sont passés ;
l'archive, elle, était déjà sur le bon nœud et n'a pas bougé. **À faire avant une
campagne, jamais pendant.**

Rejouable par `observability.sh isolate <nœud>` et `loadgen.sh isolate <nœud>`.

## Sortie vers un magasin d'objets

Le seul vrai risque restant était que tout vive sur les disques des machines
réservées. C'est réglé : la passerelle écrit désormais **en continu** vers un
magasin d'objets externe, et non au moment de la destruction — un arrêt imprévu
n'emporte donc que les dernières secondes.

Trois destinations en parallèle, et c'est volontaire :

| Destination | Rôle | Survit à la grappe |
|---|---|---|
| disque local | lecture immédiate, sans réseau | non |
| Jaeger | consultation à l'œil | non |
| magasin d'objets | le jeu de données publiable | **oui** |

Si le réseau vers le magasin tombe, rien n'est perdu localement.

**Rangement** : `otel-data/year=…/month=…/day=…/hour=…/minute=…/traces_*.json`,
au format OTLP/JSON. Le partitionnement par date permet de ne relire qu'une
tranche de temps sans lister tout le bucket.

**Un réglage qui n'est pas cosmétique.** Le regroupement par défaut envoie toutes
les 200 millisecondes, ce qui convient à une base de données mais pas à un
magasin d'objets. Mesuré : **1505 objets en deux minutes et demie**, soit environ
600 par minute. Sur une campagne de plusieurs heures, ce sont des centaines de
milliers de petits fichiers, longs à lister et pénibles à relire.

Après passage du regroupement à 30 secondes :

```
avant   1505 objets en 2,5 min   ~600 objets/minute
après      6 objets en 3 min        2 objets/minute
```

Trois cents fois moins de fichiers, pour le même volume. Le seul coût est que la
visionneuse affiche les traces avec jusqu'à trente secondes de retard.

**Volumétrie mesurée** : environ **380 Mo par heure** à la charge de référence
(10 voyageurs, 2 requêtes par seconde). Une campagne de trois heures produit donc
de l'ordre de 1,1 Go. À rapporter dans le dispositif expérimental.

**Les identifiants ne sont nulle part dans le code.** Ils vivent dans
`.env.secrets`, ignoré par git, et transitent par un Secret Kubernetes. À noter :
`.env` est suivi dans un dépôt public — il ne contient aujourd'hui que des
chemins, mais c'est exactement le fichier où l'on finit par mettre un mot de
passe. À retirer du suivi par `git rm --cached .env`.

## Saturation du disque — le risque et son traitement

Les trois volumes vivent sur **un seul nœud**, celui réservé à la mesure. La
question de la saturation se pose donc, et la réponse initiale était mauvaise.

**Ce qui n'allait pas.** Le stockage local **n'applique pas** la taille annoncée
d'un volume : un `PersistentVolumeClaim` de 20 Gio n'est qu'un répertoire sur le
disque du nœud, et rien n'empêche d'y écrire davantage. Or la rotation de
l'archive autorisait `128 Mo × 200 fichiers`, soit 25 Go, et la base de métriques
n'avait qu'un plafond de durée, pas de taille. À trois, ces composants pouvaient
dépasser les 32 Go disponibles — et un disque plein évince **tous** les pods du
nœud.

**Ce qui a été fait.** L'archive antérieure a d'abord été mise à l'abri dans le
magasin d'objets (1,19 Gio, sous `otel-data/backfill/`), puis les plafonds ont
été posés :

| Composant | Avant | Après |
|---|---|---|
| archive locale | 25 Go possibles | **768 Mo** (6 fichiers) |
| base de métriques | durée seulement | **8 Go** + 15 jours |
| visionneuse | sans limite | 6 h de rétention |

Depuis que l'export fonctionne, l'archive locale n'est plus un magasin mais un
**tampon** : elle sert à relire les dernières minutes sans réseau, pas à
conserver la campagne.

État constaté après correction :

```
jaeger-badger            582 Mo
otel-traces-archive      675 Mo     (était 1,3 Go, la rotation a élagué)
prom-prometheus-server   9,6 Mo
disque : 15 Go / 47 Go utilisés, 32 Go libres
```

Pire cas désormais possible : environ 11 Go sur 32 disponibles.

### Trois pièges rencontrés en chemin, tous du même genre

Ils méritent d'être notés parce qu'ils touchent la validité des mesures, et
qu'aucun ne se signalait par une erreur.

**Une clé YAML répétée écrase la précédente.** Le bloc de placement ajoutait un
second `server:` dans le fichier de valeurs. Tous les réglages du premier étaient
perdus, **cadence de mesure comprise** : elle était revenue à une minute alors que
le fichier annonçait dix secondes. Helm rapportait « upgraded », les pods
tournaient, et seules les données étaient trois fois moins fines qu'annoncé.

**Une ressource créée à la main ne peut plus être reprise par Helm.** Kubernetes
retient qui a écrit chaque champ et refuse qu'un autre outil l'écrase. Le script
s'arrêtant à la première erreur, un composant sans rapport avec le conflit n'a
jamais reçu sa correction.

**Un symptôme ne dit pas sa cause.** En voyant un réglage non appliqué, la
première conclusion — « mauvaise clé de configuration » — était fausse : la clé
était bonne, mais le script n'atteignait jamais cette ligne. Une solution juste a
été remplacée par une fausse.

D'où la règle appliquée depuis : **vérifier la configuration effective dans le
cluster, jamais le message de succès.**

## Les compteurs aussi partent vers le magasin

Une première version n'exportait que les traces. Les compteurs ne vivaient que
dans la base locale, qui disparaît avec la réservation — soit la moitié du
graphe perdue : les cinq grandeurs de chaque machine, celles des conteneurs, et
l'état des files.

Ils suivent désormais le même chemin, et arrivent au même endroit, dans le même
format. Le constructeur n'a donc qu'une seule façon de lire et un seul découpage
temporel à gérer.

**Deux obstacles rencontrés.** Prometheus 3 envoie par défaut l'ancienne version
du protocole, que le receveur refuse — « unsupported proto version, rejecting ».
Il faut demander la nouvelle explicitement. Et l'ancien nom du receveur est
déprécié. Les deux échouaient **en silence** : les pods tournaient, Helm
rapportait un succès, et rien n'arrivait dans le magasin.

**Ce qui est exporté, et seulement cela.** La grappe produit 109 126 séries. La
liste retenue — les 21 noms de la section 11 — en représente **4 698, soit
4,3 %**. Elle vit dans `apps/metrics-keep.txt`, un nom par ligne, commentée par
partie du graphe. Pour ajouter un compteur, on écrit une ligne. Le script
fabrique l'expression attendue par Prometheus ; personne n'a à en écrire une.

Une première version enfermait cette liste dans une expression régulière
compressée — illisible et pénible à modifier pour une liste destinée à évoluer.

⚠️ **Le filtre ne vaut que pour l'avenir.** Un compteur ajouté demain n'existera
pas dans les données déjà exportées.

## Compression

Mesuré avant compression : environ **un kilo-octet par relevé**. Le nombre utile
fait neuf caractères ; les étiquettes qui l'entourent en font mille, et elles
sont répétées à l'identique toutes les dix secondes.

```
                    avant        après       facteur
compteurs        1,55 Go/h     78 Mo/h        ~20×
traces           0,38 Go/h     29 Mo/h        ~13×
────────────────────────────────────────────────────
total            1,93 Go/h    107 Mo/h
campagne 3 h        6 Go       320 Mo
campagne 1 jour    45 Go       2,6 Go
```

**La compression ne touche qu'à l'encodage.** Vérifié en relisant un fichier
réel : 57 096 octets compressés redonnent 1 003 356 octets de JSON OTLP valide,
portant les identités attendues (`k8s.pod.uid`, `k8s.node.name`). Aucune série,
aucune cadence, aucune étiquette n'est perdue — **le graphe reconstruit est le
même**.

C'est le seul levier de volume qui ne coûte rien scientifiquement. Les autres —
retirer un nom, ralentir la cadence, échantillonner les traces — modifient tous
ce que le graphe voit.

**Un piège de lecture rencontré en chemin.** Les mêmes notes étaient introuvables
par l'interface de consultation alors qu'elles étaient bien dans l'archive. La
leçon vaut pour la suite : **la vérité est dans l'archive**, la visionneuse n'est
qu'un confort. Toute vérification sérieuse doit porter sur les fichiers, pas sur
ce que montre une interface.

**Pile installée.** Briques 1 à 4 posées et vérifiées. 17 pods dans le namespace
`observability`, trois disques (métriques, archive des traces, index des traces).
La cadence de relevé passe de 1 minute à 10 secondes.

**Vérification V3 exécutée — bonne nouvelle.** Les compteurs de pression du noyau
répondent sur les 7 machines. La solution de repli prévue dans le protocole
(« taux d'usage élevé + corrélation entre voisins », explicitement décrite comme
un discriminant plus faible) **n'aura pas à être employée**.

**Deux corrections faites après le premier essai.** Le nom du service de
Prometheus dépend de la version du paquet : il est maintenant découvert au lieu
d'être supposé. Et l'exportateur du collecteur a été renommé en amont — l'ancien
nom est réécrit automatiquement pour l'instant, mais le script écrit désormais
le nom actuel.

**Un piège de comptage, corrigé.** La première version de l'inventaire annonçait
« 9 services qui émettent des traces », ce qui était faux : elle comptait des
guillemets dans la réponse au lieu de lire le nombre. Jaeger n'en connaît qu'un,
lui-même. L'inventaire dit maintenant `ABSENT`. C'est une leçon à garder : un
indicateur qui ne peut jamais dire « absent » ne vérifie rien.

---

## Décision — à quelle fenêtre appartient une note ?

Une note a un début et une fin. Quand elle traverse une frontière de fenêtre, il
faut choisir : on la compte dans la fenêtre de son début, ou dans celle de sa fin ?

**Mesuré** sur la plage 2026-09-09 15:05→15:14 (30 639 notes) :

| grille | notes à cheval | dépôts à cheval | retraits à cheval |
|--------|---------------|-----------------|-------------------|
| 10 s   | 6.63 %        | 0 / 87          | 0 / 88            |
| 30 s   | 2.40 %        | 0 / 87          | 0 / 88            |
| 60 s   | 1.18 %        | 0 / 87          | 0 / 88            |

Un dépôt dure 0.1 ms, un retrait 4.6 ms : trop court pour traverser quoi que ce
soit. Les deux conventions donnent le même écart, à l'unité près.

**Décision : on assigne par le DÉBUT.**

Pas pour aujourd'hui — ça ne change rien — mais pour le jour de l'injection de
panne. Un consommateur ralenti produira des retraits longs. Le message quitte la
file au moment où il est *livré*, c'est-à-dire au début de la note ; compter par
la fin le décalerait dans une fenêtre ultérieure et masquerait exactement
l'anomalie recherchée.

**Conséquence : la première et la dernière fenêtre d'une plage sont tronquées.**

Attention, la raison est mécanique et non logique. Ce n'est PAS une histoire de
messages dont le dépôt manquerait : mesuré sur cette plage, 87 retraits sur 88
ont leur dépôt dans la fenêtre, et un écart négatif est parfaitement légitime
(une file peut se vider d'un message déposé avant — le niveau descend, c'est vrai).

La vraie raison : **la fenêtre du bord est plus courte que les autres.**

| fenêtre  | dép | ret | écart | durée réellement couverte |
|----------|-----|-----|-------|---------------------------|
| 15:04:00 |  9  | 10  |  −1   | **40.6 s** (19 s manquantes) |
| 15:05:00 | 17  | 17  |  +0   | 59.9 s |
| 15:06:00 | 17  | 17  |  +0   | 59.0 s |
| 15:07:00 | 11  | 11  |  +0   | 59.8 s |
| 15:08:00 | 18  | 18  |  +0   | 59.9 s |
| 15:09:00 | 15  | 15  |  +0   | 59.9 s |

Neuf dépôts en 40 s comparés à dix-sept en 60 s se lisent comme un doublement du
trafic. Il n'y en a pas : on a simplement mesuré moins longtemps. Les fichiers
sont rangés par minute d'export, pas par instant de l'événement, donc les bords
d'une plage téléchargée ont toujours une couverture partielle.

**Le décalage dépôt/retrait entre deux fenêtres n'est pas un défaut à corriger.**
Chaque fenêtre mesure un flux, pas un appariement : « combien sont entrés,
combien sont sortis pendant ces 60 s ». Un message déposé en fenêtre N et retiré
en fenêtre N+5 donne +1 en N et −1 en N+5 — les deux sont exacts. Sous panne,
c'est précisément ce décalage qui constitue le symptôme recherché.

*Variante écartée :* diviser par la durée réellement couverte au lieu de jeter.
Cela corrigerait les comptes de notes, mais pas la couverture partielle des
compteurs sur la même fenêtre. Jeter deux fenêtres coûte moins cher qu'un
redressement partiel.

**Contrôle de bon fonctionnement.** Sur cette plage, l'écart vaut +0 sur toutes
les fenêtres complètes de 60 s : autant de messages entrent que de messages
sortent. Première vérification bout en bout de la chaîne de mesure.

---

## Le découpage — `graphe/decoupage.py`

Deuxième brique du constructeur. Prend un dossier rapatrié, rend une suite de
fenêtres, chacune avec ses notes et ses relevés.

```bash
./.venv/bin/python decoupage.py donnees/2026-09-09_1505-1514
./.venv/bin/python decoupage.py donnees/2026-09-09_1505-1514 --largeur 60 --pas 30
```

`--largeur` = ce que couvre une fenêtre. `--pas` = de combien on avance.
Quand le pas est plus petit que la largeur, les fenêtres se chevauchent : c'est
le mode glissant, et une note appartient alors à plusieurs fenêtres. Voulu.

**Grille ancrée sur l'origine absolue des temps**, pas sur le début des données.
Deux campagnes découpées avec les mêmes réglages tombent donc sur exactement les
mêmes frontières — condition pour qu'elles soient comparables.

**Largeur et pas ne sont PAS arrêtés.** 60 s est un repère de travail. Le module
le rappelle à chaque exécution.

**Il annonce toujours ce qu'il écarte.** Une troncature silencieuse se lirait
comme une couverture complète.

### Les bords : une marge d'abord posée, puis retirée sur preuve

Première version : écarter les fenêtres mal couvertes, PUIS une fenêtre de plus
de chaque côté « par sécurité ». Choix prudent, mais arbitraire.

Une colonne « couvre » a été ajoutée — combien de secondes chaque fenêtre
contient réellement. Résultat sur la plage 15:05→15:14, marge désactivée :

```
  15:05:00  59.9 s      15:08:00  59.9 s      15:11:00  59.0 s
  15:06:00  59.0 s      15:09:00  59.9 s      15:12:00  59.8 s
  15:07:00  59.8 s      15:10:00  59.5 s      15:13:00  59.0 s
```

Neuf fenêtres, toutes à 59 s sur 60. Aucune amputée. **La marge jetait deux
fenêtres pleines pour rien** : le tri de couverture suffit à lui seul.

`--bords` passe donc à 0 par défaut, et reste disponible si un jeu de données se
révélait plus sale. Le drapeau « ! » signale toute fenêtre couvrant moins de 90 %
de sa largeur, ce qui rend le contrôle visible à chaque exécution plutôt que
supposé une fois pour toutes.

### Pourquoi un pas plus petit que la largeur

Avec des fenêtres bout à bout, un incident à cheval sur une frontière est coupé
en deux : chaque fenêtre n'en voit que la moitié, et l'amplitude peut passer sous
le seuil de détection. Avec un pas inférieur à la largeur, tout incident plus
court que la largeur tombe entier dans au moins une fenêtre.

Coût : chaque note comptée largeur/pas fois, et deux fenêtres voisines partagent
une partie de leurs données — elles ne sont plus des échantillons indépendants,
ce dont l'analyse statistique devra tenir compte.

Les deux modes sont disponibles ; le choix appartient à l'expérience.

### Ce que le découpage a révélé sur la plage 15:05→15:14

Contrairement à ce qui était écrit plus haut, cette plage n'est PAS complète de
bout en bout :

| fenêtre | notes | relevés | dépôts | retraits |
|---------|-------|---------|--------|----------|
| 15:06   | 5018  | **0**   | 17     | 17       |
| 15:07   | 5373  | **0**   | 11     | 11       |
| 15:08   | 5156  | 20811   | 18     | 18       |
| 15:09   | 3663  | 27086   | 15     | 15       |
| 15:10   | 802   | 27960   | **0**  | **0**    |
| 15:11   | 778   | 26986   | **0**  | **0**    |

Les compteurs ne démarrent qu'à 15:08 ; le trafic de messagerie s'arrête à
15:09:37 et le nombre de notes s'effondre de 5000 à 800 (générateur arrêté).

**Seules deux fenêtres portent les deux signaux : 15:08 et 15:09.** Suffisant
pour écrire et déboguer les briques suivantes, insuffisant pour une mesure. La
campagne réelle est à refaire sur la grappe réinstallée, avec l'étape 6
(trois consommateurs) appliquée.

### Et si la fenêtre jetée contenait l'anomalie ?

Le tri compare chaque fenêtre aux **deux extrémités des données**, jamais au
contenu. Conséquences :

- Une fenêtre du milieu n'est jamais écartée, même vide. Un effondrement du
  trafic reste visible (constaté : fenêtres 15:10→15:13, trafic tombé de 5000 à
  800 notes et messagerie à zéro — gardées et affichées).
- Seules les fenêtres des deux bouts peuvent l'être. Une anomalie n'est donc
  perdue que si elle tombe exactement au bord de la plage rapatriée.

Le module **affiche le contenu des fenêtres écartées** (notes, dépôts, retraits,
couverture) au lieu de se contenter de les compter. Sans ça il faudrait croire
sur parole qu'elles ne contenaient rien — or une anomalie jetée en silence ne se
rattrape jamais. Il signale « ← REGARDE » toute fenêtre écartée qui portait du
trafic de messagerie.

**Règle d'expérience.** L'injection de panne se place au milieu de la campagne,
et la plage rapatriée déborde d'au moins une fenêtre de chaque côté. Injection à
15:30 pendant 5 min → rapatrier 15:20→15:45. Les bords écartés tombent alors dans
du trafic normal. Le moment de l'injection étant choisi par l'expérimentateur, ce
risque est entièrement contrôlable.

### Choisir la largeur et le pas — la règle

Ce qu'on mesure dans une fenêtre est proportionnel à la part de cette fenêtre
occupée par la panne. Une fenêtre à moitié dans la panne montre une amplitude
deux fois trop faible, et peut passer sous le seuil d'alerte.

Calculé (`graphe/outils/choisir_pas.py`) sur le pire placement possible de la
panne, fenêtre de 60 s :

| durée panne | pas 60 s | pas 30 s | pas 20 s | pas 10 s | plafond |
|-------------|----------|----------|----------|----------|---------|
|   5 s       |  4.2 % ! |  8.3 %   |  8.3 %   |  8.3 %   |  8.3 %  |
|  10 s       |  8.3 % ! | 16.7 %   | 16.7 %   | 16.7 %   | 16.7 %  |
|  30 s       | 25.0 % ! | 50.0 %   | 50.0 %   | 50.0 %   | 50.0 %  |
|  60 s       | 50.0 % ! | 75.0 % ! | 83.3 % ! | 91.7 % ! | 100 %   |
|  90 s       | 75.0 % ! | 100 %    | 100 %    | 100 %    | 100 %   |
| 120 s       | 100 %    | 100 %    | 100 %    | 100 %    | 100 %   |
| 300 s       | 100 %    | 100 %    | 100 %    | 100 %    | 100 %   |

**Règle générale :** `pas ≤ | durée de la panne − largeur de la fenêtre |`.

**Règle pratique, celle à retenir :**

> largeur ≤ durée de la panne ÷ 2, puis pas = largeur.

Dès que la panne dure au moins deux fois la fenêtre, des fenêtres entières
tombent à l'intérieur de la panne : le signal est à pleine force et le
recouvrement n'apporte rien. La durée d'injection étant choisie par
l'expérimentateur, on peut toujours se placer dans ce cas.

**Deux pièges symétriques :**

- Panne aussi longue que la fenêtre — pire cas absolu, aucun pas ne garantit de
  la voir entière (91.7 % au mieux avec pas = 10 s). Ne jamais choisir une
  largeur égale à la durée de panne visée.
- Panne beaucoup plus courte que la fenêtre — elle est diluée (8 % pour 5 s dans
  60 s) quel que soit le pas. Le remède est alors de réduire la LARGEUR, pas le
  pas.

**Décision pour les campagnes à venir :** injection longue (≥ 5 min), fenêtres de
60 s, pas de 60 s. Fenêtres bout à bout, donc échantillons indépendants — ce qui
simplifie aussi l'analyse statistique. Le mode glissant reste disponible pour
l'étude de transitoires courts.

---

## Les ronds — `graphe/ronds.py`

Troisième brique. Dresse, pour chaque fenêtre, la liste de ce qui existe, avec un
nom stable. Ne calcule aucune valeur, ne trace aucune flèche.

```bash
./.venv/bin/python ronds.py donnees/2026-09-09_1505-1514 --espace train-ticket
```

### Le pont entre les deux sources

Les traces et les compteurs ne désignent pas un pod de la même façon :

```
  traces     k8s.pod.uid = fc2f0f27-b624-433c-98ea-fff47c39355d
  compteurs  pod         = ts-seat-service-6fbf7f6fbb-zllcn
```

`kube_pod_info` porte les deux, plus la machine. C'est la seule pièce qui les
relie — d'où sa présence dans la liste des métriques exportées.

**Vérifié** (`graphe/outils/pont.py`) sur la plage 15:05→15:14 :

```
  pods vus dans les traces                                41
  retrouvés dans kube_pod_info                            41 / 41
  machine selon les traces vs selon les compteurs   41 d'accord · 0 en désaccord
```

Les deux sources sont donc utilisables ensemble sans ambiguïté.

### Redémarrages : rien à décider

- Conteneur redémarré sur place → **même** identifiant, même rond, et
  `kube_pod_container_status_restarts_total` s'incrémente.
- Pod recréé → **nouvel** identifiant, nouveau rond. C'est correct : c'est bien
  une autre copie, possiblement sur une autre machine.

Les deux cas se distinguent dans les données ; aucune convention arbitraire n'est
nécessaire.

### Ce que le module a montré

| fenêtre | copies | files | machines |
|---------|--------|-------|----------|
| 15:05   | 41     | 2     | 5        |
| 15:07   | 41     | 2     | 5        |
| 15:08   | **56** | 2     | **7**    |
| 15:13   | 56     | 2     | 7        |

Le saut à 15:08 est l'arrivée des compteurs, pas une instabilité : +15 pods non
instrumentés (mysql, nacos, rabbitmq) que seuls les compteurs voient, +2 machines
(master et le nœud de mesure) qui ne portent aucun service instrumenté.

**Conséquence pour l'analyse :** deux fenêtres ne sont comparables que si elles
disposent des mêmes sources. Une campagne où traces et compteurs tournent dès le
début ne présente pas ce défaut. Le module signale les ronds intermittents plutôt
que de les masquer.

**Les machines ne sont pas filtrées par espace de noms**, même quand `--espace`
est donné : une machine porte des pods de plusieurs espaces, et ce partage est
précisément ce qui peut expliquer une panne (un voisin bruyant).

---

## Les valeurs — `graphe/valeurs.py`

Quatrième brique. Calcule, pour chaque fenêtre et chaque rond, les nombres du
papier : 19 pour une copie de service, 6 pour une file, 5 pour une machine.

```bash
./.venv/bin/python valeurs.py donnees/2026-09-09_1505-1514 --espace train-ticket
```

Réglages : `--largeur` (W), `--horizon` (H, fenêtres regardées par la pente),
`--echantillon` (η). Aucun n'est en dur.

### Résultat sur la plage 15:05→15:14

| fenêtre | copies | files | machines |
|---------|--------|-------|----------|
| 15:05   | 41 · 15 % | 2 · 50 % | 5 · 0 % |
| 15:08   | 56 · 64 % | 2 · 83 % | 7 · 100 % |
| 15:13   | 56 · 64 % | 2 · 100 % | 7 · 100 % |

**Aucune des 30 composantes n'est restée vide** sur la plage. Le 64 % des copies
est structurel, non un défaut : les composantes 1–3 (durée de traitement des
messages) n'existent que pour un service consommateur — il n'y en a qu'un — et
les pods vus uniquement par les compteurs (mysql, nacos, rabbitmq) n'ont aucune
composante issue des traces.

Ordres de grandeur des machines : 2–4 % de processeur occupé, 2–6 Go de mémoire
libre, attente processeur ~10⁻². Plausibles.

### Trois écarts au papier, tous mesurés

**1. Une quantité comptée deux fois.** La composante 4 du vecteur d'instance
(« comptage des spans de traitement, taux, corrigé par η ») et la composante 1 de
la relation de consommation sont la même grandeur. Un modèle la verrait deux fois
et lui accorderait un poids double. À trancher dans le papier : l'une des deux
doit disparaître.

**2. `rabbitmq_queue_messages_published_total` n'existe pas.** Vérifié : absent
de RabbitMQ 3.8, donc absent des 21 métriques exportées. La composante 3 de la
file est calculée à partir des notes de dépôt, symétriquement à la composante 4
que le papier reconstruit déjà à partir des arêtes de consommation. Les deux
débits sont ainsi mesurés de la même façon, ce qui rend leur écart (composante 5)
homogène — un progrès sur la définition d'origine, qui mélangeait un compteur du
courtier et un comptage de spans.

**3. `inc` cassé par un redémarrage.** Le papier pose `inc = c(θ_k) − c(θ_k⁰)`.
Un compteur remis à zéro produit alors une valeur négative, donc un débit
négatif. L'implémentation somme les hausses entre relevés consécutifs. Sans
redémarrage, les deux formules coïncident.

### Encodage : aucun one-hot n'est nécessaire

- **Type de rond** : le graphe est hétérogène, chaque type a sa propre matrice
  (19, 6 et 5 colonnes). Le type est porté par la matrice, pas par une colonne.
  Idem pour les quatre types de relations.
- **Identités** : exclues volontairement (principe de séparation des clés). Les
  encoder apprendrait au modèle le nom du coupable au lieu de son comportement,
  et interdirait tout transfert vers une autre application ou un redéploiement.
- **Aucune composante n'est catégorielle** : durées, débits, rapports, niveaux,
  compteurs. Le one-hot n'a pas d'objet.

Ce qui est nécessaire à la place : **mise à l'échelle**. Les ordres de grandeur
vont de 10⁻² (taux d'erreur) à 10⁸ (octets de mémoire) ; sans standardisation les
grandes échelles écrasent les autres. Passer au logarithme les grandeurs à queue
lourde (les durées).

**Piège méthodologique :** la mise à l'échelle se cale sur la campagne saine
seulement, puis s'applique telle quelle à la campagne en panne. La caler sur les
deux ferait fuiter l'anomalie dans la normalisation.

---

## Les flèches — `graphe/fleches.py`

Cinquième brique. Quatre sortes de flèches et les nombres qu'elles portent.

```bash
./.venv/bin/python fleches.py donnees/2026-09-09_1505-1514 --espace train-ticket
```

| flèche | de → vers | nombres |
|--------|-----------|---------|
| appeler | copie → copie | 5 : débit, trois quantiles de durée, taux d'erreur |
| déposer | copie → file | 1 : débit |
| retirer | file → copie | 1 : débit |
| tourner sur | copie → machine | 0, purement structurelle |

### Comment un appel est reconstruit

Un appel entre services produit deux notes : une note CLIENT chez l'appelant
(genre 3) et une note SERVEUR chez l'appelé (genre 2), dont le parent est la note
CLIENT. On part des notes SERVEUR, on remonte au parent, on regarde dans quelle
copie il a été écrit.

Deux cas écartés, tous deux comptés et affichés :

- **parent introuvable** — sa note est hors de la fenêtre. La proportion de
  parents retrouvés est le taux de résolution du papier.
- **parent dans la même copie** — appel interne, pas une relation entre deux ronds.

### Résultat sur la plage 15:05→15:14

| fenêtre | appeler | déposer | retirer | tourne sur | parents retrouvés |
|---------|---------|---------|---------|------------|-------------------|
| 15:05 | 22 | 2 | 2 | 41 | 100.0 % |
| 15:06 | 22 | 2 | 2 | 41 | 99.7 % |
| 15:09 | 24 | 2 | 2 | 56 | 99.6 % |
| 15:13 | 4 | 0 | 0 | 56 | 100.0 % |

Sur la première fenêtre : 1075 notes SERVEUR avec parent, 1075 parents retrouvés,
0 appel interne, 0 hors graphe.

Les flèches de messagerie sont cohérentes de bout en bout :

```
  deposer   ts-food-service          → food_delivery            0.167 msg/s
  retirer   food_delivery            → ts-delivery-service      0.167 msg/s
  deposer   ts-notification-service  → email                    0.117 msg/s
  retirer   email                    → ts-notification-service  0.117 msg/s
```

Débits identiques dans les deux sens, donc écart nul — la file suit le rythme.

### À retenir pour la ligne de base

`ts-seat-service → ts-order-service` et `ts-travel-service → ts-seat-service`
mettent **2 s en médiane** alors que la plupart des appels sont à 2 ms. Ce n'est
pas une anomalie mais la lenteur normale de ces chemins dans train-ticket. À
connaître avant d'interpréter une mesure sous panne : le seuil de détection ne
peut pas être global.

---

## L'assemblage — `graphe/graphe.py`

Sixième brique. Appelle les cinq précédentes et écrit le résultat.

```bash
./.venv/bin/python graphe.py donnees/2026-09-09_1505-1514 --espace train-ticket
```

```
graphes/2026-09-09_1505-1514/
    manifeste.json          réglages, provenance, dimensions, écarts au papier
    fenetre_0001.json       un cliché
    ...
```

### Pourquoi un format neutre et non PyTorch Geometric directement

PyG tire PyTorch (2–3 Go) et ses versions cassent entre elles. Un jeu de données
doit survivre au changement de bibliothèque : dans cinq ans un relecteur ouvrira
un JSON, il n'installera pas cette version de PyG. La conversion vers PyG est une
brique séparée et facultative, qui lit ces fichiers.

### Forme d'un cliché

```json
"ronds": { "file": {
    "noms": ["email", "food_delivery"],
    "colonnes": ["niveau","niveau_pente","debit_publie","debit_consomme",
                 "ecart_debits","consommateurs"],
    "X": [[null, null, 0.1167, 0.1167, 0.0, null], ...] }},
"fleches": { "deposer": {
    "de_type": "copie", "vers_type": "file",
    "de": [19, 16], "vers": [0, 1],
    "colonnes": ["debit"], "X": [[0.1167], [0.1667]] }}
```

Les flèches portent des **positions** dans la liste de ronds du type concerné —
la forme qu'attendent PyG comme DGL, et qui se relit à la main.

### Résultat sur la plage 15:05→15:14

9 fenêtres + 1 manifeste, 214 Ko. Dernier cliché :

```
  X_copie        56 × 19        E_appeler       4 flèches × 5
  X_file          2 ×  6        E_deposer       0 flèches × 1
  X_machine       7 ×  5        E_retirer       0 flèches × 1
                                E_tourner_sur  56 flèches × 0
```

### Valeurs manquantes : `null`, jamais 0

47,4 % sur cette plage. La distinction compte : un débit nul est une information,
un débit inconnu n'en est pas une. Les écrire 0 fabriquerait des mesures fausses.

Décomposition : les fenêtres 15:05→15:07 n'ont aucun compteur (16 composantes sur
19 vides par copie) ; les fenêtres complètes sont à 36 %, et ces 36 % sont
structurels — un service qui ne consomme pas de messages n'a pas de durée de
traitement. Sur une campagne où les deux sources tournent dès le début, le taux
attendu est ~36 %.

### Le manifeste décrit le jeu de données lui-même

Provenance des fichiers bruts (magasin, bucket, nombre de fichiers), réglages
employés (W, pas, espace, H, η, quantiles, règle d'assignation, traitement des
bords), dimensions, fenêtres écartées au découpage avec leur contenu, les quatre
écarts assumés par rapport au papier, et la liste de ce qui reste à faire avant
apprentissage. Un jeu de données sans ce carnet n'est pas réutilisable.

---

## Le dessin — `graphe/dessiner.py`

Brique facultative. Relit les clichés écrits par `graphe.py` et en fait une image.
Ne produit aucune donnée.

```bash
./.venv/bin/python dessiner.py graphes/2026-09-09_1505-1514
./.venv/bin/python dessiner.py graphes/2026-09-09_1505-1514 --file food_delivery
./.venv/bin/python dessiner.py graphes/2026-09-09_1505-1514 --fenetre 5
```

Dépendances : `networkx`, `matplotlib` — installées dans `.venv`, et requises par
cette brique seule.

### Trois bandes

```
  files        les files d'attente
  copies       les copies de service, rangées par machine puis par nom
  machines     les machines du cluster
```

Ranger les copies par machine regroupe les traits « tourne sur » au lieu de les
croiser : l'appartenance devient lisible d'un coup d'œil.

**Une file se place au-dessus des copies qu'elle touche** (barycentre de ses
voisines), et non à un rang arbitraire. Première version : les files étaient aux
extrémités et leurs flèches traversaient toute la figure. Après correction,
`food_delivery` tombe entre `food` (qui dépose) et `delivery` (qui retire), et
`email` juste au-dessus de `notification`, qui dépose et retire lui-même.

### La disposition est déterministe

Aucun tirage au sort, aucune disposition par ressorts : les positions se
calculent à partir des noms. Deux exécutions donnent la même image, et deux
fenêtres successives sont superposables. Sans cela on croirait voir bouger le
système alors que seul le dessin aurait changé — défaut classique des figures
produites par `spring_layout`.

### Codage visuel

| élément | codage |
|---------|--------|
| flèche déposer / retirer | trait épais accentué |
| flèche appeler | gris, épaisseur proportionnelle au débit |
| flèche tourne sur | pointillé très pâle |
| rond de file | taille croissante avec le niveau d'accumulation |
| étiquette de file | débit entrant, débit sortant, écart, niveau |

`--file` restreint au voisinage d'une file : la file, les copies qui y déposent
ou y retirent, leurs machines. C'est la vue utile pour une figure d'article — le
graphe entier (41 copies, 22 appels) reste lisible mais est trop dense pour une
page.

---

## Le convertisseur — `graphe/vers_pyg.py`

Brique facultative. Traduit les clichés en objets PyTorch Geometric. Ne produit
aucune donnée nouvelle.

```bash
./.venv/bin/python vers_pyg.py graphes/saine    --ecrire-echelle echelle.json
./.venv/bin/python vers_pyg.py graphes/en_panne --echelle echelle.json
```

Dépendances : `torch` (version processeur, 1.2 Go installés) et
`torch_geometric` — requises par cette brique seule.

### Ce que ça donne

```
  data['copie'].x                          (41, 19)
  data['file'].x                           (2, 6)
  data['machine'].x                        (5, 5)
  data['copie','appeler','copie']          edge_index (2, 22)  edge_attr (22, 5)
  data['copie','deposer','file']           edge_index (2, 2)   edge_attr (2, 1)
  data['file','retirer','copie']           edge_index (2, 2)   edge_attr (2, 1)
  data['copie','tourner_sur','machine']    edge_index (2, 41)  edge_attr (41, 0)
```

Les identifiants et les noms de pods sont conservés (`data['copie'].cles`,
`.noms`) : un résultat du modèle reste rattachable à un pod réel.

### Trois choix de méthode, tous en réglage

**Valeurs manquantes** — `--manquant masque|moyenne|zero`, défaut `masque` :
remplace par 0 et ajoute un tenseur booléen `.present` disant où était le trou.
`zero` est le plus dangereux : un débit inconnu deviendrait un débit nul, soit
une panne inventée.

**Mise à l'échelle** — `--ecrire-echelle` calcule moyennes et écarts-types,
`--echelle` les applique. Les deux options sont séparées exprès : les statistiques
doivent être calculées sur la campagne SAINE seulement, puis appliquées telles
quelles à la campagne en panne. Les calculer sur les deux ferait entrer l'anomalie
dans la normalisation, qui la gommerait en partie — sans que rien ne le signale.
Vérifié après application : X_copie va de −1.28 à +8.31, moyenne +0.014.

**Logarithme** — appliqué à `log(1+x)` sur les colonnes à queue épaisse toujours
positives (durées, mémoire, octets, quota). La liste est **nommée dans le code**,
pas devinée, pour qu'un relecteur puisse la contester.

**Flèches inverses** — `--symetriser` ajoute les relations en sens contraire
(préfixe `inv_`). Non fait par défaut : c'est un choix de modèle, pas de format.

### Processeur ou carte graphique

`--appareil cpu|cuda|auto` choisit où les tenseurs sont construits. **Le fichier
écrit contient toujours des tenseurs de processeur**, délibérément : un `.pt`
contenant des tenseurs de carte ne se relit que sur une machine équipée, parfois
seulement avec la même version de CUDA — l'inverse de la portabilité recherchée.

```python
suite = torch.load('pyg.pt', weights_only=False)
suite = [d.to('cuda') for d in suite]        # l'appareil appartient à l'entraînement
```

`--garder-appareil` force l'écriture sur l'appareil choisi. Demander `cuda` sur
une installation processeur seul s'arrête immédiatement avec la commande
d'installation CUDA, plutôt que d'échouer plus loin.

Un fichier `environnement.json` est écrit à côté du `.pt` : versions de Python,
torch et torch_geometric, CUDA compilé, cartes présentes, appareil employé. Sans
ce relevé un résultat n'est pas refaisable. La conversion ne comporte aucun
tirage au sort : même résultat sur processeur et sur carte.

### Afficher des valeurs sur la figure sans la surcharger

Règle appliquée : **du texte là où les ronds sont peu nombreux, un codage visuel
là où ils sont nombreux.**

| bande | nombre de ronds | ce qui est affiché |
|-------|-----------------|--------------------|
| files | 2 | débit entrant, débit sortant, écart, niveau, consommateurs |
| machines | 5 à 7 | occupation processeur, mémoire libre, attente processeur |
| copies | 41 à 56 | aucun texte — le remplissage du rond porte la valeur |

Quarante-et-un nombres écrits sous les copies rendraient la figure illisible.

```bash
./.venv/bin/python dessiner.py graphes/... --valeur-copie duree_requete_q95
./.venv/bin/python dessiner.py graphes/... --valeur-machine attente_io
```

`--valeur-copie` et `--valeur-machine` acceptent n'importe quel nom de colonne
des vecteurs (19 et 5 respectivement). Un nom inconnu affiche la liste des noms
valides au lieu d'échouer.

**L'échelle de gris est calculée sur toute la campagne**, pas sur la fenêtre
dessinée. Sinon chaque image aurait sa propre échelle et une copie inchangée
changerait de teinte d'une fenêtre à l'autre : on lirait une évolution qui
n'existe pas. Même raisonnement que pour la disposition fixe. Les bornes
employées sont imprimées à l'exécution et sous la barre d'échelle.

**Contour pointillé = valeur absente**, et non valeur nulle. Cohérent avec le
reste de la chaîne, où `null` n'est jamais confondu avec 0.

**Niveaux de gris et non couleurs** : la figure reste lisible imprimée en noir et
blanc, et le seul accent coloré est réservé à la file.

Vérifié sur la fenêtre 15:08 : `workers0` ressort immédiatement en foncé, à
10,8 % de processeur contre 1,7 à 3,1 % pour les autres machines.
