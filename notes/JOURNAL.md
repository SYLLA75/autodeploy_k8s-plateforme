# Journal des décisions

Ce qui a changé, pourquoi, et où le retrouver. Une entrée par décision, datée.
Le détail de chaque changement est dans le message de commit correspondant
(`git log --grep=<mot>`). Ce journal dit *ce qu'il faut savoir* pour ne pas
refaire une erreur déjà faite.

---

## 2026-09-12 — essai-charge : deuxième cause validée, et une règle d'intensité

50 voyageurs (2 × la base) de la minute 3 à la minute 8, plage 20:02 → 20:10
(`campagnes/essai-charge/lecture.txt`) :

```
   fenêtre   backlog  slope  publish  consume  imbalance
   20:02         1      -     3,65     3,65      0,00     avant
   20:04       308    153     7,47     4,25      3,22     injection à 20:03:29
   20:07       800    171     7,13     4,23      2,90
   20:08       813     93     4,05     4,20     -0,15     retrait à 20:08:26
   20:09       784     -8     3,72     4,25     -0,53
```

L'entrée double, la sortie plafonne à 4,25/s (trois répliques à 706 ms),
le tas monte de 170 par minute ; répliques, hôtes, temps par message :
inchangés. C'est la ligne « charge » du tableau des causes.

**Ce que l'essai apprend en plus** : le tas ne fond qu'à ~0,5–0,75/s sous
la charge de base. Vingt minutes à 50 voyageurs feraient 3 300 messages,
plus d'une heure de fonte : dans une campagne à trois injections, la
deuxième partirait sur le tas de la première, et les fenêtres « saines »
entre deux ne le seraient pas. **Règle retenue pour les grandes
campagnes** : l'intensité est choisie pour que le tas construit pendant
l'injection soit fondu avant l'injection suivante, calculée sur les débits
mesurés dans l'essai. Les valeurs sont fixées après les essais lenteur et
hôte (entrée suivante).

**Nettoyé au passage** : deux boucles `while true; do panne.sh temoin;
sleep 20; done`, restées orphelines sur le master après la fermeture de
leurs sessions SSH, avaient écrit 780 fichiers dans `journaux/` ; tuées.
Une simple lecture (`etat`, `temoin`, `bilan`, `fenetre`) n'écrit plus de
journal. Et le pilote attend maintenant une file vide avant de partir, et
relève le bilan des parcours toutes les dix minutes sans arrêter.

## 2026-09-12 — essai-blocage-02 : la première cause validée sur la plateforme

25 voyageurs, réplique gelée de la minute 3 à la minute 8, lu au témoin
toutes les 20 s :

```
   pendant   2 consommateurs (le courtier a lâché la gelée), 2 non acquittés,
             tas + ~50 par minute (129 → 182 en 63 s ; prévu + 40)
   minute 8  3 consommateurs, pic à 188
   après     fonte à ~45 par minute, 0 au bout de cinq minutes, puis 0–3
```

L'entrée n'a pas bougé (3,5/s) ; la sortie est passée de 4,2 à 2,8/s. La
trace est nette, datée, réversible.

**Le graphe la porte** (run sur la plage 19:12 → 19:19, `scaler: apply`,
gardé dans `campagnes/essai-blocage-02/lecture.txt`) :

```
   fenêtre   backlog  slope  publish  consume  imbalance  consumers
   19:12         0      -     3,55     3,55      0,00        3      avant
   19:13        25     25     3,35     2,80      0,55        3      gel à 19:12:59
   19:15        95     35     3,43     2,83      0,60        2      le courtier lâche la gelée
   19:17       192     48     3,75     2,93      0,82        2
   19:18       156      9     3,48     4,22     -0,73        3      levée à 19:17:56
```

Et sur les répliques : la gelée (`…-bmgvs`) n'a plus de `process_time` et
`cpu_rate` 0,000 de 19:13 à 19:17, mémoire inchangée ; les deux autres
gardent 706 ms. Exactement la ligne « blocage » du tableau des causes.

**Corrigé au passage** : le pilote d'alors lisait le début de la plage dans
la date du pod de collecte (resté de la campagne d'avant : « 19:00 »). Il
la calcule maintenant depuis ses propres instants (`collecte_demarree` +
marge). Et le dossier d'une campagne recevait *tout* `journaux/` du master,
600 fichiers dont 500 d'avant elle : il ne reçoit plus que les registres
(.tsv) et les journaux écrits depuis le départ du pilote.

## 2026-09-12 — Le gel d'une réplique doit partir de la machine

**Mesuré** (essai-blocage, première tentative) : `kill -STOP` envoyé depuis
l'intérieur du conteneur à Java, processus 1 → état `S`, rien ne se passe.
Le noyau fait ignorer au processus 1 d'un conteneur les signaux envoyés
depuis son propre conteneur, STOP compris. Sur simulateur, ça passait.

**Décision** : le signal part de la machine, par le démon Chaos Mesh du nœud
(processus de la machine en vue) : le processus Java est retrouvé par
l'identifiant du conteneur dans son cgroup, gelé, et la levée est programmée
dans le démon. `verifier blocage` exige un démon sur le nœud de chaque
réplique. L'essai est à refaire.

## 2026-09-12 — Référence saine-07 : la plateforme réglée se comporte comme calculé

Campagne complète (10 / 25 / 20 voyageurs), `scaler.json` écrit dessus.
Mesuré (`queues.py`, `instances.py`) :

| palier | dépôts/s | tas | temps par message (p50) |
|---|---|---|---|
| 10 voyageurs | 1,2 – 1,5 | 0 | 846 ms |
| 25 voyageurs | 3,3 – 3,75 | 0 – 4, redescend toujours | 706 ms |
| 20 voyageurs | 2,6 – 3,1 | 0 – 3 | 706 ms |

Le débit suit les voyageurs (0,12/s par voyageur, comme prévu), l'écart
dépôt/retrait reste sous ±0,1, 3 consommateurs sans interruption, aucun
point chaud sur les hôtes (pression CPU max 0,026 — les commandes réparties
sur trente dates ne chargent plus le service des commandes).

Le temps par message vaut 5 échanges × 140 ms à 25 voyageurs — le facteur 5
estimé est exact — et 6 échanges à 10 voyageurs : une connexion restée
inactive plus d'une demi-seconde est vérifiée avant réutilisation (Hikari,
`aliveBypassWindow`), un aller-retour de plus. Le temps par message *baisse*
donc quand la charge monte ; c'est une propriété de l'application, à
connaître avant d'interpréter une figure. Occupation à 25 voyageurs :
3,5 × 0,706 ÷ 3 = 82 %.

Corrigé au passage : les fenêtres hors de la plage demandée entraient dans
l'analyse (le rapatriement prend un fichier de plus de chaque côté) ; cinq
fenêtres d'avant la campagne, sans compteurs du courtier, avaient été
comptées dans la normale. Écartées désormais (« outside requested range »).

## 2026-09-12 — Redémarrer le service des commandes seul casse la recherche deux minutes

**Mesuré** au départ de saine-04 : le pilote purgeait et redémarrait
`ts-order-service` ; dans la minute, « chercher un train » à 100 % de `500`
(30 s), puis retour à la normale de lui-même après ~2 minutes (57 ms). Les
services qui appellent les commandes gardent des connexions ouvertes vers le
pod disparu et y attendent. La campagne a été arrêtée et relancée : ses deux
premières minutes étaient fausses.

**Décisions** : la purge ne redémarre plus rien (`--redemarrer` redémarre la
chaîne complète — commandes, sièges, recherche — quand c'est nécessaire) ;
`bilan` rend un code de retour ; le pilote contrôle les parcours à la minute
2 et s'arrête proprement si l'un échoue ou ne tourne pas.

## 2026-09-12 — Le sommeil dans la base sérialise les répliques : retard réseau à la place

**Mesuré**, après la purge et à 25 voyageurs, avec le déclencheur SQL à
0,7 s : 570 messages en attente en cinq minutes ; 3,4 reçus/s, 1,3 traités/s
pour 3 répliques ; et côté base, **un seul** `User sleep` actif en
permanence (10 échantillons sur 10). MySQL n'exécute qu'un sommeil de
déclencheur à la fois : les trois répliques attendaient l'une après l'autre.
La capacité valait 1 ÷ S quel que soit le nombre de répliques — une réplique
gelée n'aurait rien changé, les causes `blocage` et `hote` étaient mortes.

**Décision** : le temps de service est un **retard réseau propre à chaque
réplique** (Chaos Mesh NetworkChaos sans durée, `consommateur.sh
dimensionner --retard 140`), entre les pods du consommateur et `tsdb-mysql`.
Traiter un message coûte ~5 échanges avec la base : ≈ 0,7 s. Le facteur 5
est une estimation, à vérifier sur la référence (`process_time_p50`) et sur
le témoin (tas à 0 à 25 voyageurs).

Piège trouvé à la première pose : les répliques parlent à la base par une
adresse de *service* (`tsdb-mysql-leader`), traduite en adresse de pod après
la sortie du pod ; un retard posé sur les seules adresses des pods de la base
ne voit jamais passer ce trafic (mesuré : connexion en 2 ms, Chaos Mesh
disant « appliqué »). Les adresses des services devant la base sont ajoutées
en `externalTargets` — pour le réglage comme pour la cause `lenteur`.

Conséquence sur la cause `lenteur` : un seul objet à la fois sur ce chemin.
La panne remplace le réglage par « base + panne » (défaut +300 ms) et
`retirer` repose le réglage. Le déclencheur SQL est retiré par
`dimensionner` s'il en reste un.

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

- **temps de service ≈ 0,7 s par message** : d'abord un déclencheur SQL
  (`SLEEP`) — abandonné le jour même, voir l'entrée suivante — puis un retard
  réseau de 140 ms par échange avec la base. Capacité des 3 répliques :
  ~4,3 messages/s ; à 25 voyageurs, **3,4 messages/s mesurés** (3,0 du
  parcours direct + 0,4 des réservations avec repas), occupation 80 %.
- **prefetch 1** (`SPRING_RABBITMQ_LISTENER_SIMPLE_PREFETCH=1`) : par défaut
  le courtier confie 250 messages d'avance à chaque réplique ; le tas visible
  (`messages_ready`) n'aurait bougé qu'après 750 messages en souffrance, et une
  réplique gelée en aurait emporté 250. Entraîne un redémarrage roulant, donc
  de nouveaux pods : d'où « avant la référence ».

Le déclencheur SQL avait été préféré au retard réseau pour ne pas mélanger
deux retards sur le même chemin (cause `lenteur`). La mesure a tranché
autrement (entrée suivante) ; `lenteur` remplace désormais le réglage le
temps de la panne.

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
