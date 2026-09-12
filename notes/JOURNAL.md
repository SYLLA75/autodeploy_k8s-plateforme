# Journal des décisions

Ce qui a changé, pourquoi, et où le retrouver. Une entrée par décision, datée.
Le détail de chaque changement est dans le message de commit correspondant
(`git log --grep=<mot>`). Ce journal dit *ce qu'il faut savoir* pour ne pas
refaire une erreur déjà faite.

---

## 2026-09-12 — L'application s'étouffe sur ses propres données (`apps/donnees.sh`)

**Symptôme** : après l'étalonnage, « chercher un train » répond `500` à 100 %,
`p50` = 30 000 ms, même à 1 voyageur, même après redémarrage de
`ts-travel-service`, puis de `ts-seat-service`.

**Diagnostic, de haut en bas** (connexions ouvertes lues dans `/proc/net/tcp`
de chaque pod, requêtes vues côté MySQL, journaux) :

1. `ts-travel-service` : ses 10 connexions à la base dorment (`Sleep 232 s`),
   tenues par des requêtes qui attendent `ts-seat-service` (4 connexions sans
   réponse). Spring garde la connexion pendant toute la requête
   (`open-in-view`) : au-delà de 10 recherches en attente, les suivantes
   attendent 30 s et rendent `500`.
2. `ts-seat-service` : aucune erreur ; il attend `ts-order-service`
   (4 connexions sans réponse).
3. `ts-order-service` : 41 connexions à la base pour une réserve de 10,
   dormant depuis 20 min à 2 h ; journal : *« Thread starvation or clock leap
   detected (55 s) »* — la JVM (tas de 200 Mo) se fige.
4. La base : 9 643 commandes, dont **5 229 sur le train D1345 le 12 et 4 408
   le 13** — toutes les réservations visaient le même train à la même date
   (« demain »). Pour compter les places vendues, le service des sièges fait
   charger toutes ces commandes en mémoire à chaque recherche.

**Conséquence** : le comportement de train-ticket dépend du volume de ses
tables ; deux campagnes ne se comparent que si elles partent des mêmes
données. C'est aussi ce qui faisait baisser le débit au fil de l'heure dans
saine-03.

**Décisions** :
- `apps/donnees.sh purger` vide `orders`, `orders_other`, `food_order`,
  `delivery` (le déclencheur reste) et redémarre `ts-order-service`. Le pilote
  l'appelle au départ de chaque campagne, avant la collecte ; le compte rendu
  note l'état des tables (`donnees_au_depart`).
- Le générateur étale les dates de départ sur trente jours
  (`TT_JOURS_ETALEMENT`) : trente fois moins de commandes par train et par
  date.
- Remède documenté si la signature revient : redémarrer commandes, sièges,
  recherche, dans cet ordre.
- `apps/mysql.sh`, sourcé par `consommateur.sh` et `donnees.sh`.

## 2026-09-12 — Le débit de la file ne suit pas les voyageurs : nouveau parcours

**Mesuré** (saine-03, `queues.py` sur l'heure entière) :

| voyageurs | messages/s dans food_delivery |
|---|---|
| 10 | 0,40 – 0,60 |
| 30 | 0,37 – 0,60 |
| 10 | 0,22 – 0,53 |
| 55 | 0,13 – 0,35 |

Le débit **baisse** quand les voyageurs montent. Un message naît d'une
réservation, qui passe par la recherche de train — l'appel lourd. Dès 10
voyageurs la recherche ralentit ; à 55, chaque voyageur réserve moins qu'à 10.

**Conséquences** : la cause `charge` (« plus de voyageurs ») était impossible
par construction ; et un débit de 0,13 à 0,67 ne permet aucun dimensionnement
stable (30 % ou 120 % selon la minute).

**Décision** : un quatrième parcours dans le générateur, « commander un
repas » — un appel direct à `ts-food-service` (`POST /foodservice/orders`,
l'API existe, elle exige seulement un numéro de commande inédit), qui dépose
le même message dans `food_delivery` sans la recherche devant. Poids : repas
6, réserver 2, chercher 1, courriel 1. Le débit devient 0,12 message/s par
voyageur — 3/s à 25, 6/s à 50 — et la recherche reste à un niveau que
l'application tient à 50 voyageurs (moins de demande qu'avant à 25).

## 2026-09-12 — Le consommateur dimensionné pour sa charge (`apps/consommateur.sh`)

Deux réglages de plateforme, posés une fois avant la référence, jamais
changés ensuite, recopiés dans chaque compte rendu (`reglage_consommateur`) :

- **temps de service 0,8 s par message** : un déclencheur SQL sur la table
  `delivery` (`BEFORE INSERT … SLEEP(0.8)`). Capacité des 3 répliques :
  3,75 messages/s ; à 25 voyageurs (3/s), occupation 80 %. Formule :
  `temps = 0,8 × répliques ÷ débit_de_base`.
- **prefetch 1** (`SPRING_RABBITMQ_LISTENER_SIMPLE_PREFETCH=1`) : par défaut
  le courtier confie 250 messages d'avance à chaque réplique ; le tas visible
  (`messages_ready`) n'aurait bougé qu'après 750 messages en souffrance, et une
  réplique gelée en aurait emporté 250. Entraîne un redémarrage roulant, donc
  de nouveaux pods : d'où « avant la référence ».

Pourquoi un déclencheur SQL et pas un retard réseau Chaos Mesh : le retard
réseau est le mécanisme de la cause `lenteur` ; deux retards sur le même
chemin se seraient mélangés. Le temps de service est passé dans l'appel à la
base, là où un vrai service de livraison passerait le sien.

Attendu avec ce réglage (à mesurer par les essais courts) : charge 25 → 50 :
160 % ; blocage : 120 % ; lenteur +1 s réseau : ~380 % ; hote : faible, le
temps par message étant de l'attente et non du CPU.

La charge de base est 25 voyageurs ; la référence saine ne dépasse jamais 25
(au-delà, le tas grossirait dans la référence elle-même). La cause `charge`
vise 50 (`--intensite 50`, défaut 2 × la charge).

## 2026-09-12 — Le consommateur a mille fois trop de marge (mesuré, résolu ci-dessus)

**Mesuré** (étalonnage, profil 80/160/320) : la file reçoit 0,5 message/s à
25–55 voyageurs ; trois répliques de `ts-delivery-service` en absorbent ~500/s
(6 ms par message). Marge × 1000.

**Conséquence** : aucune cause ne fait grossir le tas — une réplique gelée ou
un hôte saturé, les deux autres absorbent tout ; seule une lenteur énorme
(≥ 10 s par message) se verrait sur la file. Le modèle ne verrait jamais le
symptôme central de la thèse.

**Décision** : donner au consommateur un coût par message réaliste, comme
*réglage de plateforme* posé avant la référence saine — pas comme panne. La
valeur se choisit par étalonnage pour que la charge de base occupe ~70 % de
la capacité. La référence saine (saine-03) est donc à refaire une fois ce
réglage posé. La cause `hote` restera la plus faible des quatre (une réplique
ralentie par le CPU quand son coût est surtout de l'attente) — à mesurer.

**Aussi mesuré** : l'application plafonne entre 55 et 80 voyageurs, et ce
n'est pas le CPU : `ts-travel-service` a 10 connexions à sa base (défaut
Spring) et en garde une pendant toute une recherche ; au-delà de 10 recherches
simultanées, les autres attendent 30 s et rendent `500`. Quand ça arrive, les
réservations s'arrêtent et la file **se vide**. La charge de base doit rester
nettement sous ce plafond (40 voyageurs), et la cause `charge` ne peut pas
dépasser ~60.

## 2026-09-12 — Les quatre injections existent (`apps/panne.sh`)

| cause | mécanisme | outil |
|---|---|---|
| charge | plus de voyageurs, retour programmé | `loadgen.sh scale` |
| lenteur | retard réseau entre les répliques et `tsdb-mysql` | Chaos Mesh NetworkChaos |
| hote | pod « voisin bruyant » hors du graphe, sur l'hôte d'une réplique, tous les cœurs | Chaos Mesh StressChaos |
| blocage | `SIGSTOP` sur le Java d'une réplique | `kubectl exec` |

Chaque injection expire d'elle-même. `panne.sh etat` rend 3 si quelque chose
est en place, et le pilote refuse alors de partir — saine comprise.
Correction de doc : `SIGSTOP` ne fait PAS redémarrer le pod, train-ticket n'a
pas de sonde de vivacité (vérifié dans ses manifestes).

Pilote (`campagne.sh`) : `--panne --a --duree --intensite --cible` ; instants
calculés depuis un point de départ unique ; témoins avant / pendant / après ;
`Ctrl-C` retire, clôt, écrit le compte rendu ; lu en entier avant d'exécuter
(un `git pull` pendant une campagne le tuait) ; compteurs Locust remis à zéro
au départ ; charge ramenée au premier palier à la fin.

`bilan` : deux lectures (totaux depuis le reset, et maintenant/s), le p50, et
le motif des échecs. Les totaux seuls ne disaient pas *quand*.

`queues.py` : une ligne par fenêtre pour une file — la lecture d'un étalonnage.

## 2026-09-11 — Référence saine-03 : signature confirmée

Campagne complète, `scaler.json` écrit. Sur toute l'heure : tas 0, écart 0,
3 consommateurs, 0,35–0,67 message/s selon le palier. Un service chaud par
déploiement (ici `station-food` à 0,4 cœur, avant `ts-order-service`) : un
hôte affiche une pression CPU 30–70 × les autres. Normal, pas une panne.
Les 3 répliques de `delivery` sont sur trois hôtes différents.

Reproductibilité vérifiée : création des VMs → campagne, en suivant
`INSTALL.md` puis `PROCEDURE.md`, sans intervention hors doc.

## 2026-09-10 — Deux campagnes perdues, deux causes

- saine-01 : jeton de connexion expiré (~1 h) → tous les parcours en `500`,
  pods `Running`, collecte active, rien ne le montrait. Correction :
  reconnexion proactive toutes les 20 min, en-tête vidé avant. Et `bilan`
  avant chaque campagne, obligatoire.
- saine-02 : VMs expirées en pleine campagne (`DURATION=10h`). Réglage : `3d`.
- Le soir, « aujourd'hui » ne rend aucun train : recherche pour le lendemain
  (`TT_JOURS_AVANCE=1`).

## 2026-09-10 — Chaos Mesh avant la référence

Installé **avant** la référence saine : son démon tourne sur chaque nœud, son
coût doit être des deux côtés. Une liste de tolérances remplace celle du
chart : `operator: Exists` pour que le démon monte aussi sur le master.
`CHAOS_VERSION` à figer dans `.env`.

## 2026-09-10 — Deux copies des scripts

`git pull` sur le nœud de contrôle ne met pas à jour le master :
`./deploy.sh --push-scripts` après chaque changement dans `apps/`. Le
locustfile vit dans un ConfigMap : `loadgen.sh uninstall && install` pour le
recharger.

## 2026-09-10 — Le dépôt rangé par machine

`deploy.sh`, `destroy.sh`, `lib/`, `campagne.sh`, `graphe_en/` tournent sur
le nœud de contrôle ; `apps/*.sh` sur le master. `graphe/` (ancienne version)
et `test.sh` supprimés. Les campagnes vivent dans `campagnes/<nom>/`
(compte rendu + journaux du master), à committer : c'est la provenance.

## 2026-09-09 — Corrections de la chaîne de graphe (`graphe_en/`)

- `process_rate` (nœud) valait 2 × `consume_rate` (arête) : il comptait les
  spans, pas les messages. Supprimé.
- Un message consommé = deux spans (livraison par le courtier, 0,09 ms ;
  traitement par l'application, 6 ms). Le p50 mélangeait les deux, 22 × trop
  petit. On garde le span de traitement (absence de `network.peer.address`).
- Les positions de pente étaient des indices figés : par nom maintenant.
- Un `scaler.json` d'une autre largeur de colonnes s'appliquait en silence :
  refusé.
- Deux définitions de « échec » : une seule, `otlp.failed()`.
- Plage à cheval sur minuit : refusée avec explication.

## 2026-09-09 — Le modèle (rapport de recherche externe)

R-GCN + MLP d'arêtes sur `calls`, entraînement en deux temps, classifieur
prototypique à peu d'exemples, rejet hors ensemble par distance aux
prototypes. Le point aveugle asynchrone de la littérature RCA est confirmé.
Rien ne change au graphe.

## Avant le dépôt — la construction de la plateforme (jusqu'au 9 septembre)

Résumé chronologique ; le détail, les mesures et les erreurs sont dans
`notes/OBSERVABILITE.md` (§3 découvertes, §4 briques, §8 journal, puis une
section par module du graphe), `notes/CHOIX.md` et `notes/RECOMMANDATIONS.md`.

1. **La grappe** (`deploy.sh`, Kubespray sur SLICES-RI). Deux Helm sur le
   master (v4 pour otel-demo, v3 pour les charts de train-ticket) ; une
   `StorageClass` par défaut, sans laquelle MySQL et Nacos restent en
   `Pending` ; une attente active des VMs à la place d'un `sleep` ; les
   scripts d'application copiés et exécutés sur le master. (CHOIX.md)
2. **L'application étudiée** : train-ticket (46 services, deux files RabbitMQ :
   `food_delivery` et `email`). otel-demo retiré : collisions et machines.
3. **La chaîne de mesure à nous** (`observability.sh`) : collecteur
   OpenTelemetry, Prometheus, Jaeger, relevés des machines et de Kubernetes,
   port de mesure du courtier. Découverte qui décide de tout le graphe : le
   courtier ne donne PAS de débit par file — les débits déposé / retiré
   viennent des traces, pas des compteurs. (OBSERVABILITE.md §3.2)
4. **Faire parler les 46 services** (`instrument.sh`) : agent Java 2.31.1
   attaché sans toucher au code, version figée ; téléchargé depuis Maven parce
   que le registre d'images de GitHub est bloqué sur SLICES-RI. Un message
   consommé donne deux notes (livraison par le courtier, traitement par
   l'application) — c'est la seconde qui compte. (§8)
5. **Le trafic** (`loadgen.sh`) : Locust dans la grappe, hors de l'espace
   applicatif, non instrumenté ; trois parcours d'abord, choisis pour toucher
   les files. La file `email` est morte dans cette version (l'envoi est
   commenté par les auteurs) : un point d'entrée de test l'alimente. Trois
   écarts constatés avec la documentation officielle (noms de champs, gares en
   minuscules, date passée refusée). (§« Le générateur »)
6. **Isoler la mesure** : un nœud réservé (`OBS_DEDICATED_NODE`), taché, où
   vivent collecteur, Prometheus, Jaeger et Locust — leur coût ne se mêle pas
   à celui des services mesurés.
7. **Sortir les données** : magasin d'objets MinIO (survit à la destruction
   des VMs), compression, traitement de la saturation du disque, compteurs
   exportés eux aussi, liste des compteurs gardés (`metrics-keep.txt`).
8. **Le graphe** (`graphe_en/`, ex-`graphe/`) : à quelle fenêtre appartient
   une note (décision mesurée), largeur et pas, marge aux bords retirée sur
   preuve, `null` jamais 0, aucun one-hot, format neutre puis PyTorch
   Geometric, manifeste qui décrit le jeu de données. Trois écarts au papier,
   tous mesurés. (sections « Le découpage », « Les valeurs », « Les flèches »)
9. **Six correctifs au déploiement (2026-09-10)** : MySQL inaccessible en
   IPv6, boucle arrêtée à la première base, `--apps-only` sans bastion,
   `isolate` qui expulsait l'inexpulsable, épinglage avant étiquetage, profil
   de dimensionnement périmé. (RECOMMANDATIONS.md, dernière section)
10. **Revue de la formalisation (2026-09-09)** : neuf défauts dans le papier,
    dont deux corrigés dans le code — voir l'entrée du 9 septembre ci-dessus.
    (RECOMMANDATIONS.md §1)

## Règles qui ne bougent plus

- `export.scaler: write` une seule fois, sur la référence saine ; `apply`
  partout ailleurs.
- `windows.width_s` / `step_s` ne changent pas entre deux campagnes.
- Identifiants du magasin dans `.env.secrets` et `graphe_en/config.yaml`,
  jamais dans git.
- `DURATION=3d` pour les VMs. Horloges NTP des deux côtés.
- Pas de code adapté à un incident : la règle dans le code, le récit dans le
  commit.
