# Journal des décisions

Ce qui a changé, pourquoi, et où le retrouver. Une entrée par décision, datée.
Le détail de chaque changement est dans le message de commit correspondant
(`git log --grep=<mot>`). Ce journal dit *ce qu'il faut savoir* pour ne pas
refaire une erreur déjà faite.

---

## 2026-09-18 — Les lignes de base sont mesurées : un tableau plat nomme la cause sur chaque fenêtre de test

`graphe_en/ligne_de_base.py` (PROCEDURE.md, étape 13) sur les cinq campagnes,
saine-08, charge-03, blocage-02, lenteur-01, hote-01. Vérité tirée des
déroulés, fenêtres à cheval sur une transition et fenêtres de vidange (tas >
10 après le retrait, plus une de garde) écartées. Coupure par le temps, la
troisième injection de chaque campagne servant de test : 575 fenêtres, 406
gardées, 256 pour l'apprentissage, 150 pour le test, 19 par cause.

| ligne de base | sur les 150 fenêtres de test |
|---|---|
| seuil, `backlog_slope` > 20 | alarme sur 56 des 57 fenêtres de charge, blocage, lenteur ; jamais sur hote ; aucune fausse alerte ; jamais une cause |
| file seule, 6 nombres | 129 bien nommées (arbre) ; hote jamais, la file ne bouge pas |
| tableau plat, 16 nombres, aucune flèche | 150 bien nommées, arbre de décision et forêt aléatoire pareil |
| règles à la main, limites prises sur saine-08 | 150 bien nommées |

Les quatre questions de l'arbre : `rate_imbalance` > 0,21 (la file se
remplit), `hote_cpu_busy_max` > 0,51 (hote), `process_time_p50_max` > 894 ms
(lenteur, à mi-chemin entre 706 et 1 081), `publish_rate` > 4,10 msg/s
(charge, sinon blocage).

**Conséquence.** Sur quatre causes injectées une à la fois, un modèle qui lit
les flèches ne peut pas nommer la cause mieux qu'un tableau qui les ignore,
au plus aussi bien — la leçon de Fang et al. (2025), reproduite ici. Le
graphe reste la représentation (les 16 nombres en viennent) et la
contribution (la file comme nœud) ; l'argument pour un modèle sur graphe doit
se faire là où le tableau est aveugle : nommer la réplique ou l'hôte en
faute, le même motif sous des pods renommés, une panne qui se propage (la
base ralentit les répliques qui remplissent la file), plusieurs files, deux
pannes à la fois. À concevoir dans les prochaines campagnes. Rappel : `hote`
n'atteint pas la file (la demande CPU garantit sa part à la réplique, son
temps est de l'attente réseau) — anomalie d'hôte sans faute de coordination,
témoin négatif, pas le cas à plusieurs sauts qu'un modèle sur graphe
exigerait. Une cause d'hôte qui atteindrait la file passerait par le réseau
de l'hôte de la réplique, ou par l'hôte de la base.

## 2026-09-13 — Les quatre campagnes sont faites : le jeu de données existe

Après saine-08 et charge-03 (entrée précédente) :

| campagne | plage UTC | tas au retrait (×3) | fondu avant la suivante |
|---|---|---|---|
| blocage-02 | 06:15 → 08:25 | 744 / 711 / 745 | oui (minutes 46, 86, 133) |
| lenteur-01 | 08:31 → 10:41 | 824 / 877 / 883 | oui (4 et 7 avant les injections 2 et 3) |
| hote-01 | 10:48 → 12:58 | 0 – 9 | rien à fondre |

Chaque cause laisse la trace attendue et seulement elle : blocage →
`consumers` 3 → 2 et une réplique à cpu 0 sans temps de traitement ;
lenteur → 706 → 1 081 ms par message sur les trois répliques (5 × 75,
exact) ; hote → `cpu_busy` 0,04 → 0,83 et `cpu_pressure` 0,01 → 0,66 sur un
seul hôte, et la file ne bouge pas (réplique +0,5 %). Entrée stable à
3,4–3,7 msg/s dans les trois. Le service des commandes n'a plus gelé :
~7 300 commandes par campagne, sous le seuil.

**blocage-01** a été abandonnée par le pilote à la minute 2 : le service des
commandes, à court de mémoire à la fin de charge-03, répondait 500 à toute
recherche — la purge ne le redémarre pas, par choix. Le pilote relit
maintenant le bilan des parcours **avant** de partir, avec le remède
(`donnees.sh redemarrer`, puis deux minutes).

**État du jeu de données** : 1 référence (55 fenêtres) + 4 campagnes (130
fenêtres chacune) = 575 fenêtres, dont 180 sous injection (60 par cause
pour charge, blocage, lenteur, et 60 « hôte saturé, file saine »).
`scaler.json` calé sur saine-08. Les dossiers `campagnes/*` sont la
provenance ; les runs sont à reconstruire depuis le magasin d'objets avec
la plage de chaque `campagne.yaml`.

**Ce qui reste** : l'étiquetage par fenêtre depuis les déroulés (avec une
période de garde autour des transitions), le découpage par injection
(jamais au hasard), le modèle et ses deux comparaisons imposées, puis
l'étude à 50 % et 95 % d'occupation avec sa propre référence chacune.

## 2026-09-13 — saine-08 et charge-03 : la référence refaite, la première campagne propre

**saine-08** (10/25/20 voyageurs, 60 min, service des commandes à 2 cœurs,
dates sur l'année) : identique à saine-07 en tout point mesuré — entrée
1,4 / 3,4 / 2,7 msg/s, tas 0 à 5, 3 consommateurs, 706 ms par message
(846 à 10 voyageurs). `scaler.json` recalculé dessus.

**charge-03** (`campagnes/charge-03/lecture.txt`) : les trois injections
sont exactement le calcul.

```
   injection   entrée    tas au retrait   fondu à 0 à la minute
   1 (min 5)   4,8–5,1     692            40
   2 (min 50)  4,8–5,0     792            88
   3 (min 95)  4,8–5,2     764           128
```

Sortie plafonnée à 4,25/s, répliques à 706 ms, 3 consommateurs, hôtes
calmes. Le service des commandes est monté jusqu'à 532 m de CPU — au-dessus
de son ancienne limite : la correction était nécessaire.

**Réserve, à écrire** : fenêtres 05:41–05:45 (minutes 126–130, après la
dernière fonte) — `ts-order-service` à court de tas Java
(`java -Xmx200m`, `OutOfMemoryError: Java heap space` dans ses journaux,
~8 500 commandes en table) : recherche et réservation gelées 3 min, entrée
de la file à 0, puis reprise seule. Les injections ne sont pas touchées ;
ces fenêtres sont à écarter, ou à étiqueter « anomalie non injectée ».

**Décision : le tas Java n'est pas relevé pour ces campagnes** (la commande
existe depuis pour les suivantes : `donnees.sh dimensionner --tas 1g`,
testée puis retirée, à poser avant une nouvelle référence). `memory_used` est un attribut
du graphe ; un tas plus grand changerait le niveau de ce nœud dans toutes
les fenêtres, et la référence serait à refaire une seconde fois. Les
trois campagnes restantes tournent à 25 voyageurs d'un bout à l'autre :
~7 300 commandes en 135 min, sous les ~8 500 où le tas a manqué (charge-03
en a produit 9 000 avec ses trois paliers à 35). Si le gel réapparaît, il
se rapporte. Limite connue de la plateforme : **une campagne ne doit pas
dépasser ~8 000 commandes** avec le tas de 200 Mo du service des commandes.

## 2026-09-13 — charge-01 et charge-02 : l'application s'étouffe au bout d'une heure, deux couches

Deux campagnes de 135 min (25 voyageurs, 35 pendant les injections à 5, 50
et 95 min). Dans les deux, les injections 1 et 2 sont exactement le calcul
(entrée 3,5 → 4,9/s, tas ~700–800, fondu en 19 min, file à 0–10 avant la
suivante). Dans les deux, la troisième ne produit rien : l'entrée de la
file s'effondre à 0,6–2/s **avant** elle, dès la 75ᵉ–80ᵉ minute
(`campagnes/charge-01/lecture.txt`, `charge-02/lecture.txt`).

**Mesuré, pas deviné** (Locust `/stats/requests`, `kubectl top`) : la
réservation passe de 0,3 s à 5, 28 puis 60 s (p95) ; les voyageurs y
restent coincés et ne commandent plus de repas — ce sont les repas qui
déposent dans la file. Derrière, `ts-order-service` à 500 m de CPU, sa
limite.

**Première couche** (charge-01) : 6 400 commandes empilées sur 30 dates
(~240 par date, un seul train sur la liaison) ; le service recharge et
journalise la pile à chaque recherche. Correction : dates étalées sur
365 jours (`LG_JOURS_ETALEMENT`, passé au conteneur Locust).

**Deuxième couche** (charge-02, dates étalées, 16 commandes par date) : le
CPU croît quand même, avec le **total** — 97 m à 1 900 commandes, 212 m à
4 700, 444 m à 5 900, 500 m à 7 000. Le service fait un travail
proportionnel à toutes les commandes du train, pas de la date.
Correction : `donnees.sh dimensionner`, limite CPU 500 m → 2 000 m, une
fois. Testé avec 7 600 commandes en table, 25 voyageurs, 6 min : 308 m,
réservation médiane 430 ms, repas à 3,3/s — personne de coincé.

**Résidu accepté, à écrire** : même sans saturation, la réservation passe
de 110 ms (table vide) à ~430 ms (8 000 commandes) — le `request_time`
des trois services de la chaîne dérive lentement pendant toute campagne,
de la même façon dans toutes, et n'atteint pas la file. C'est
l'application ; on ne la corrige pas.

**Pourquoi la référence est refaite** (saine-08) : la limite CPU est un
attribut du graphe (`cpu_quota` du service des commandes). Une référence
doit partager toutes les conditions des campagnes qu'on lui compare.
saine-07 reste dans le dépôt ; le `scaler.json` est recalculé sur saine-08.

**Deux pièges au passage** : `kubectl set resources` sans `-c` touche aussi
le conteneur d'initialisation de l'agent, qui n'a pas de demande —
Kubernetes lui donne alors une demande égale à la limite et le pod ne
trouve plus de nœud (« Insufficient cpu ») ; corrigé. Et une campagne qui
traverse minuit (charge-02, 23:46 → 01:56) : `fetch.py` parcourt
maintenant les deux jours, `run.py` borne la plage sur le lendemain quand
la fin n'est pas après le début.

## 2026-09-12 — essai-hote-02 : la quatrième cause se voit sur l'hôte, pas sur la file

Voisin à 100 % des 4 cœurs de `workers0` de la minute 3 à 8, plage 21:01 →
21:08 (`campagnes/essai-hote-02/lecture.txt`) :

```
   fenêtre   workers0 cpu_busy  cpu_pressure   réplique r5pwb p50   backlog
   21:01          0,24             0,08              706 ms             0
   21:02          0,84             0,62              711 ms             4
   21:05          0,84             0,63              709 ms             0
   21:07          0,05             0,01              706 ms             0
```

L'hôte est saturé, et seulement lui. La réplique qui y vit ralentit de
0,5 % ; la file ne bouge pas. Explication : sa demande CPU (100 m) lui
garantit sa part quand tout le monde veut du processeur, et 4 m lui
suffisent — son temps est fait d'attente réseau, pas de calcul. **Résultat
retenu tel quel** (règle : une cause sans trace se rapporte, ne se retire
pas) : un voisin bruyant sur l'hôte d'une réplique n'est pas une panne de
coordination sur cette plateforme. Pour le modèle, c'est une anomalie
d'hôte *sans* symptôme sur la file — utile pour apprendre à ne pas
attribuer un tas à un hôte chargé. Si un jour il faut qu'un hôte pèse sur
la file, viser l'hôte de la base (les trois répliques y passent cinq fois
par message) serait la voie ; c'est une autre cause, à décider, pas à
glisser.

**Décision pour les grandes campagnes** (`PROCEDURE.md`, étape 11, point
3) : profil `25:135`, injections à 5, 50 et 95 min, 20 min chacune, 25 min
de retour — le temps que le tas du gel (0,7/s, sans réglage possible)
fonde à 0,6/s. `charge` à 35 voyageurs et `lenteur` à +75 ms pour que les
trois causes fassent monter le tas au même rythme (~0,7/s) : le modèle ne
peut alors pas les distinguer à la taille du symptôme. `hote` à sa
valeur par défaut. Ordre : charge, blocage, lenteur, hote.

## 2026-09-12 — essai-lenteur : troisième cause validée, et un trou comblé

+300 ms par échange de la minute 3 à la minute 8, plage 20:31 → 20:38
(`campagnes/essai-lenteur/lecture.txt`) :

```
   fenêtre   backlog  slope  publish  consume  p50 réplique
   20:31         0      -     3,43     3,27      706 ms     avant
   20:32       127    127     3,53     1,35     2206 ms     injection à 20:31:55
   20:35       507    122     3,47     1,35     2206 ms
   20:36       417     19     3,43     5,22        3 ms     retrait à 20:36:55
   20:37       379    -64     3,65     4,23      706 ms
```

706 + 5 × 300 = 2 206 ms : le modèle « cinq échanges avec la base par
message » est exact. La sortie tombe à 1,35/s (3 ÷ 2,206), le tas monte de
127 par minute, CPU et hôtes ne bougent pas. Ligne « lenteur » du tableau.

**Le trou** : à 20:36, p50 de 3 ms et sortie à 5,2/s. Entre la suppression de
l'objet Chaos Mesh de la panne et la pose de celui du réglage, quelques
secondes sans aucun retard : les répliques ont avalé 150 messages à 3 ms.
Mesuré que deux retards sur les mêmes pods s'additionnent (140 + 1 → 143
ms) ; `panne.sh` pose donc la panne avant de retirer le réglage, et repose
le réglage avant de lever la panne. Le recouvrement dure quelques
secondes, un peu plus lent, jamais sans retard. Et un minuteur repose le
réglage de base à l'expiration si le pilote est mort entre-temps.

## 2026-09-12 — essai-hote (1) : refusé par le kubelet, refait

Le voisin bruyant demandait 2 cœurs (la moitié de l'hôte) ; l'hôte n'en a
que 3,4 allouables, dont 1,65 déjà demandés. `nodeName` contourne
l'ordonnanceur : c'est le kubelet qui a refusé le pod (`OutOfcpu`).
Injection non confirmée, essai sans mesure (`campagnes/essai-hote/`).
La demande ne fixe que le poids du voisin face aux autres pods ; le stress
occupe de toute façon tous les cœurs. Elle est maintenant plafonnée à ce
qui reste sur l'hôte moins 100 m (ici 1 600 m). Essai refait : `essai-hote-02`.

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

## 2026-09-24 — Phase A.1 : le pod leader de la base

Le leader est lu dans les mesures archivées sur S3, puis vérifié sur le cluster
(expérience `deployk8s_slices_final`, accès par le contrôleur `vms0`, jamais
directement depuis le poste).

Méthode : débit reçu (`container_network_receive_bytes_total`) des trois pods
`tsdb-mysql`, sur une minute au début et une vers la fin de chaque campagne. Le leader
reçoit toutes les écritures, il reçoit donc bien plus que les deux autres.

| campagne | minutes | tsdb-mysql-0 | tsdb-mysql-1 | tsdb-mysql-2 |
|---|---|---|---|---|
| saine-08 | 02:58, 03:25 | 50 / 37 ko/s | 6 / 5 | 7 / 6 |
| charge-03 | 04:14, 05:45 | 49 / 8 | 7 / 3 | 7 / 3 |
| blocage-02 | 06:52, 08:20 | 44 / 44 | 7 / 7 | 7 / 7 |
| lenteur-01 | 09:07, 10:35 | 47 / 51 | 7 / 7 | 7 / 7 |
| hote-01 | 11:24, 12:55 | 50 / 52 | 6 / 6 | 6 / 6 |

Résultat : `tsdb-mysql-0` est le leader dans les cinq campagnes, avec le même uid
(35b0f5fb…), jamais redémarré. Les appelants écrivent l'adresse `tsdb-mysql-leader`
(service Kubernetes) : cette adresse se relie donc au pod `tsdb-mysql-0`. La
correspondance se fait par le nom du pod, stable dans un StatefulSet, plutôt que par
l'uid, qui changerait si le pod était recréé.

Vérifié sur le cluster le 24 septembre : `tsdb-mysql-leader` pointe vers
`tsdb-mysql-0`, uid 35b0f5fb-f49f-4241-a901-7f58fd832737, démarré le 11 septembre à
21:02 UTC. C'est le même pod que pendant les cinq campagnes.

## 2026-09-24 — Phase A.2 : la relation queries (appelant → base)

Code : `graphe_en/edges.py` (relation `queries`, fonction `_queries`), `settings.py`
(`graph.databases`, vide par défaut), `run.py` (colonne et alerte), `config.example.yaml`.
Exécuté sur vms0, blocage-02, 06:23 à 06:28, configuration hors du dépôt
(`~/configs-hors-git/config-a2.yaml`, elle contient les identifiants).

Résultat, fenêtre 06:25 : 15 arêtes `queries`, toutes vers `tsdb-mysql-0`, aucune
adresse inconnue, résolution des appels inchangée (100 %).

- r5pwb et tvmfl : 2,8 appels/s, p50 141 ms (le retard réglé de 140 ms).
- bmgvs, gelée : aucune arête `queries`, comme pour consumes.
- les douze autres appelants : p50 de 0,2 à 0,8 ms.

Une base lente ferait donc monter d'un coup les quinze arêtes ; la cause 2 ne fait
monter que celles des répliques. Les figures ne dessinent pas encore la relation
(étape A.7).

## 2026-09-24 — Phase A.4 : quatre attributs réseau pour l'hôte

Code : `apps/metrics-keep.txt` (six compteurs node-exporter), `graphe_en/features.py`
(`net_rx_rate`, `net_tx_rate`, `net_drop_rate`, `tcp_retrans_ratio`, interface
physique seulement), `export_pyg.py` (échelle log), `LEXIQUE.md`. Le vecteur hôte
passe de 5 à 9 nombres. Les campagnes du 13 septembre n'ont pas ces compteurs :
absents, jamais 0. La mise à l'échelle calée sur saine-08 ne correspond plus
(`_check_scaler` refuse) : une nouvelle référence normale est nécessaire.

Déploiement : `git pull && ./deploy.sh --push-scripts` sur vms0, puis sur le master
`observability.sh tune`. PIÈGE vécu : `tune` lancé sans l'environnement de l'étape 3
a réinstallé Prometheus et la passerelle sans le nœud réservé ni l'envoi S3 (pods
Pending, puis passerelle en boucle, dix minutes, hors campagne). La seule forme
correcte, sur le master :

    set -a; . ~/autodeploy/.env.secrets; set +a
    export OBS_DEDICATED_NODE=workers6
    bash ~/autodeploy/apps/observability.sh tune

`tune` rallume aussi la passerelle, donc la collecte : la refermer ensuite avec
`collecte.sh arreter` si aucune expérience ne suit.

Vérifié : les six compteurs arrivent dans S3 dès 16:52 UTC pour les huit machines,
interface physique `enp6s18`. Graphe de 16:51 à 16:57 sur vms0, fenêtre 16:53 :
réception 13 à 134 ko/s (workers6, la mesure, en tête), envoi 17 à 113 ko/s,
2 paquets jetés par minute partout, aucune retransmission TCP. Collecte refermée.

## 2026-09-25 — Référence normale saine-09 (seconde série)

Pilote : `./campagne.sh saine-09 --profil "10:30,25:30,20:30,15:30"` sur vms0, tmux
`normale`, le 24 septembre de 17:34 à 19:34 UTC. Données remises à zéro au départ
(10 lignes), quatre paliers confirmés, douze veilles « parcours ok », file au plus à 3
au palier de 25 voyageurs puis revenue à 0. Aucun redémarrage de conteneur, mesure
restée sur workers6. Plage exploitable 17:37 à 19:32.

Graphe sur vms0 (`~/configs-hors-git/config-saine-09.yaml`, `databases` et
`scaler: write`), run `20260925-113438` : 1 547 116 spans, 115 fenêtres, 58/2/8 nœuds,
cinq relations dont 15 ou 16 arêtes `queries` par fenêtre, résolution 100 %,
0 avertissement. `scaler.json` recalé sur saine-09 (18 / 6 / 9 colonnes) ; l'ancien,
calé sur saine-08, est gardé en `scaler-v1-saine-08.json`.

Valeurs absentes 29,7 % contre 30,4 % pour saine-08, mêmes colonnes (temps de traitement
et de requête des pods qui n'en ont pas) : structurel. Colonnes réseau de l'hôte
remplies partout. Les trois répliques du consommateur interrogent la base en 143 ms,
les autres appelants en quelques millisecondes.

Observé grâce aux nouveaux compteurs : la réception de workers1 et l'envoi de workers4
montent au fil de la campagne (50 ko/s à 1,2 Mo/s). C'est ts-order-service qui reçoit
de plus en plus d'octets de tsdb-mysql-0 : la table des commandes grossit après la
remise à zéro et chaque lecture la renvoie. saine-08 montrait déjà la même montée
(15 à 896 ko/s). Comportement de l'application, identique dans toutes les campagnes
tant que chacune part de la même purge et dure autant ; les hôtes visés par les pannes
(workers0, 2, 5) ne sont pas concernés.
