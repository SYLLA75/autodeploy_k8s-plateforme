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

## 2026-09-25 — Cibles tournantes : `--cible` en liste, essai à blanc réussi

Code (commit 58c9691) : `campagne.sh --cible x,y,z` donne une cible par injection, dans
l'ordre des `--a` (chaque cible suit sa minute au tri) ; une seule cible vaut pour
toutes ; refusée pour charge et lenteur ; chaîne entière limitée aux caractères d'un nom
Kubernetes. `panne.sh verifier <cause> --cible …` contrôle chaque cible avant le départ :
réplique en marche (blocage) ; nœud qui porte une réplique, démon Chaos Mesh, place libre
(hote). Le déroulé note la cible après le résultat, `ligne_de_base.py` lit les lignes
comme avant (vérifié sur les essais et sur blocage-02). Relecture par quatre relecteurs
indépendants : deux défauts réels corrigés avant le commit (liste collée avec des retours
à la ligne réduite à son premier nom ; hôte sans réplique accepté comme cible).

Ordre retenu pour la seconde série : blocage bmgvs (workers2) → r5pwb (workers0) →
tvmfl (workers5) ; hôte workers5 → workers2 → workers0. Au même rang d'injection, les deux
causes ne frappent jamais la même machine. Les huit machines ont 4 cœurs : l'intensité
par défaut de l'hôte vaut 2 partout. La demande du voisin reste plafonnée par la place
libre de chaque machine (1 400 à 1 700m, comme les 1 600m de hote-01) ; le stress, lui,
occupe les 4 cœurs à 100 % partout.

Avant l'essai, le pilote a refusé de partir : « chercher un train » à 43 % d'échecs,
15 057 commandes après 15 h de Locust à 10 voyageurs depuis la fin de saine-09. Remède
`donnees.sh purger --redemarrer`, recherche revenue à 0,9/s sans échec.

Essai sur vms0, collecte éteinte (`--sans-collecte`, rien dans S3), 12 min par cause,
injections de 2 min aux minutes 3, 6 et 9 : six injections confirmées, chacune sur sa
cible (pannes.tsv et déroulé concordent), réplique gelée à 0m de CPU, hôte visé à 4000m,
rien de résiduel. Dossiers d'essai rangés hors du dépôt.

## 2026-09-25 — Seconde série : blocage-03, hote-02, charge-04, lenteur-02

Enchaînées sur vms0 (tmux `serie`, script hors dépôt), 11:10 → 20:13 UTC, chacune
25 voyageurs pendant 135 min, injections de 20 min aux minutes 5, 50 et 95, mêmes
intensités qu'en septembre (charge 35, lenteur +75 ms, hôte 2 cœurs). Cibles tournantes :
bmgvs → r5pwb → tvmfl ; workers5 → workers2 → workers0. 12 injections sur 12 confirmées
sur leur cible, 13 veilles « parcours ok » par campagne, aucun redémarrage de conteneur,
retard de base reposé, S3 complet (aucune minute sans traces ni mesures).

| campagne | plage | file 1 min après retrait | septembre |
|---|---|---|---|
| blocage-03 | 11:13–13:23 | 794 / 791 / 798 | 768 / 695 / 698 |
| hote-02 | 13:29–15:39 | 0 / 0 / 7 | 0 à 9 |
| charge-04 | 15:45–17:56 | 704 / 731 / 721 | 696 / 754 / 490 |
| lenteur-02 | 18:01–20:11 | 814 / 813 / 896 | 847 / 853 / 883 |

Graphes sur vms0 avec la mise à l'échelle de saine-09 appliquée (`scaler: apply`),
130 ou 131 fenêtres, 0 avertissement, 29,5 à 29,8 % de valeurs absentes (saine-09 :
29,7 %). Marques relevées dans le graphe, 5 fenêtres avant contre fenêtres pendant :
- blocage : la réplique visée seule perd son temps de traitement, son CPU tombe à 0 et
  son arête `queries` disparaît ; `consumers` 3 → 2 ; retrait 3,5 → 2,83 msg/s.
- lenteur : les trois répliques 706 → 1 081 ms par message, leurs arêtes `queries`
  141 → 216 ms (+75 exactement) ; les douze autres appelants de la base restent à 0,45 ms.
- charge : dépôt 3,5 → 4,9 msg/s, répliques inchangées.
- hote : l'hôte visé seul à `cpu_busy` 0,83 et `cpu_pressure` 0,64 à 0,72.

**Constaté : la 3e injection d'hôte (workers0) remonte en amont.** Le dépôt dans la file
tombe de 3,6 à 0,94 msg/s, ce que ni workers5 ni workers2 ne font, ni workers0 en
septembre (hote-01, dépôt 3,4 à 3,9 pendant les trois injections). Cause :
`donnees.sh purger --redemarrer`, lancé le 25 sept. vers 10:30 pour débloquer
l'application avant l'essai à blanc, a recréé ts-order-service, ts-seat-service et
ts-travel-service, et l'ordonnanceur les a replacés : ts-order-service workers1 →
workers0, ts-seat-service workers3 → workers2, ts-travel-service workers4 → workers1.
Sur workers0 saturé, ts-order-service passe de 3 à 640 ms par requête, la réservation
(ts-preserve-service) de 0,2 à 84 s, donc moins de repas commandés et moins de messages
déposés. L'étiquette reste juste (l'hôte workers0 est fautif), mais cette injection, qui
est l'injection de test, se propage par le producteur alors que les deux premières
restent sur l'hôte. Le placement des pods n'est pas figé par la plateforme ; il fait
partie des conditions à noter dans chaque compte rendu.

## 2026-09-26 — Phase A.6 : lignes de base, septembre refait et seconde série à l'aveugle

**Septembre refait.** Les cinq campagnes du 13 septembre reconstruites sur vms0 avec le code
du graphe actuel (relation `queries`, hôte à 9 nombres ; sans mise à l'échelle, que les lignes
de base n'utilisent pas) : runs 20260926-020314 (saine-08), -020626 (charge-03), -021439
(blocage-02), -022230 (lenteur-01), -023015 (hote-01), 0 erreur, deux avertissements attendus
(compteurs réseau jamais relevés en septembre ; pas de mise à l'échelle). Les `lecture.txt`
régénérés ne diffèrent des originaux que par le numéro de run, et `ligne_de_base.py` redonne
exactement `campagnes/lignes_de_base.txt` : 150/150 inchangé. Les originaux sont gardés,
ce sont eux que cite le rapport.

**Seconde série, premier test à l'aveugle.** `ligne_de_base.py` tel que commité le 18 sept.,
aucune colonne ni aucun facteur changé, sur saine-09, blocage-03, hote-02, charge-04,
lenteur-02 : 636 fenêtres lues, 460 gardées, 162 de test (19 à 20 par cause, 85 normales).
Seuil : 57/57 pannes de file trouvées, 0 fausse alerte, hôte jamais. File seule : 142/162
(arbre), hôte jamais. Tableau plat : 162/162 (arbre et forêt). Règles à la main : 162/162.
L'arbre retrouve les mêmes quatre questions qu'en septembre (rate_imbalance > 0,20 ;
hote_cpu_busy_max > 0,32 ; process_time_p50_max > 894 ms ; publish_rate > 4,14). L'injection
de test d'hôte qui s'est propagée (workers0) est bien nommée : la file reste calme et l'hôte
chargé. À noter : la règle de lenteur coupe à 883 ms (1,25 × 706) et le normal à faible
trafic est à 846 ms ; la marge n'est que de 37 ms. Résultat : `campagnes/lignes_de_base_serie2.txt`.

Conclusion : sur les quatre causes, un tableau sans flèches nomme la cause à l'aveugle comme
en septembre. Le résultat du rapport tient ; l'intérêt des flèches et du modèle se jouera sur
la base lente (fautif muet) et les jumeaux.

## 2026-09-26 — Phase A.7 : les figures dessinent la relation `queries`

`render.py` (commit a87bb6a) : les arêtes `queries` sont tracées en tirets gris foncé,
courbées dans l'autre sens que `calls`, épaisseur selon le débit ; la vue de la file ajoute
les bases que ses instances interrogent, avec leur hôte (5 instances, 1 file, 4 hôtes pour
food_delivery), sans quoi la flèche réplique → base ne pourrait jamais y figurer ; chaque
hôte affiche aussi son réseau reçu et envoyé. Les instantanés construits avant la relation
se dessinent comme avant (pas de clé `queries`). README du graphe : cinq relations, hôte à
9 nombres. Vérifié sur vms0, sur une copie des fenêtres de lenteur-02 (18:02 et 18:13) :
les trois répliques et ts-food-service reliées à tsdb-mysql-0 dans la vue de la file, les
quinze arêtes convergent vers la base dans la vue complète. Images :
`~/verifications-phases/A7/` sur le poste.

## 2026-09-26 — Phase A.8 : le graphe est figé (étiquette `graphe-fige`)

À partir d'ici, plus aucune colonne, relation, réglage de fenêtre ni mise à l'échelle ne
change. Raison : les témoins (phase B) puis le GNN (phase E) doivent tous lire le même
graphe, et il est figé avant toute donnée de la base lente (phase C) ; un graphe retouché
après l'avoir vue serait taillé pour la réponse.

- `graphe_en/graphe_fige.json` : ce qui est figé (colonnes de chaque sorte de nœud, cinq
  relations et leurs colonnes, colonnes passées au log, réglages, adresse de la base et son
  pod, écriture des tenseurs, empreinte de la mise à l'échelle, fichiers qui calculent le
  graphe).
- `graphe_en/gel.py` : la vérification. Référence lue dans l'étiquette, pas sur le disque ;
  étiquette absente = écart. `gel.py runs/<a> …` contrôle en plus le code qui a construit
  chaque run (empreintes du manifest contre l'étiquette), ses réglages, sa mise à l'échelle,
  ses colonnes et ses arêtes `queries`.

Deux relectures indépendantes avant l'étiquette (chaque constat revérifié à part) ont
ajouté au gel :
- **Les flèches sont mises à l'échelle comme les nœuds**, sur saine-09 (log des débits et
  durées). Sans cela, la décision serait revenue au GNN, en phase E, donc après la base
  lente, qui ne se voit que par les flèches `queries`. Les statistiques des nœuds sont
  identiques à l'ancienne mise à l'échelle ; nouvelle empreinte 53b6728f…, l'ancienne
  gardée sur vms0 (`scaler-v2-saine-09-noeuds.json`).
- **Chaque run dit quel code l'a construit** (commit, sha256 de chaque module), avec quelle
  mise à l'échelle et quelle base visée ; chaque fenêtre compte ses appels à une base
  inconnue. Un graphe sans aucune arête `queries` est refusé.
- Corrigés au passage : l'écart 4 du manifest, périmé depuis 2a0ccc4 (le débit de
  traitement n'est plus en double) ; un refus de `run.py` affiche enfin sa raison ; le
  lexique (valeurs réseau saines de saine-09, pertes constantes par machine, 0,033 ou 0,05 ;
  la panne hôte fait monter `tcp_retrans_ratio` sur l'hôte visé et sur le master).

Les 10 graphes des deux séries ont été reconstruits sur vms0 avec le code figé (saine-09 en
`write`, les 9 autres en `apply`) : `gel.py` les dit tous CONFORMES ; le graphe de saine-08
d'avant le gel (runs/20260913-053054) est refusé (pas de `queries`, hôte à 5 nombres, code
inconnu). Les 10 `lecture.txt` ne changent que par le numéro du run : aucun nombre n'a
bougé. Seul avertissement, attendu : la première série n'a pas les compteurs réseau.

| campagne | run figé | | campagne | run figé |
|---|---|---|---|---|
| saine-09 | 20260926-033245 | | saine-08 | 20260926-041410 |
| blocage-03 | 20260926-034025 | | charge-03 | 20260926-041723 |
| hote-02 | 20260926-034850 | | blocage-02 | 20260926-042549 |
| charge-04 | 20260926-035654 | | lenteur-01 | 20260926-043347 |
| lenteur-02 | 20260926-040544 | | hote-01 | 20260926-044150 |

Pour la suite : les témoins de la phase B liront les fenêtres de ces runs (vérifiées par
`gel.py`), pas `lecture.txt` (arrondi, produit par des fichiers hors du gel).

## 2026-09-26 — Phase B.1 : le fautif de chaque injection, et comment on juge

Écrit avant tout calcul des témoins et avant toute donnée de la base lente :
`graphe_en/fautifs.py` (commits e338da4, 3c5aa84), qui produit `campagnes/fautifs.txt`.

Le fautif, par cause : blocage = la réplique gelée ; hôte = la machine (même quand la
panne remonte en amont, hote-02 injection 3) ; lenteur = les trois répliques ; **charge =
aucun fautif** (décidé avec l'utilisateur : rien n'est cassé, il y a plus de voyageurs ;
jugée sur la cause seulement) ; base lente (C) = le pod de la base ; jumeaux (D) = la
machine au réseau dégradé, jamais le leurre. Les 24 injections des deux séries ont leur
réponse, tirée du registre des pannes de chaque campagne ; les 18 qui ont un fautif le
retrouvent comme nœud du graphe figé dans chaque minute de l'injection.

Une relecture indépendante (2 relecteurs, chaque constat revérifié) a montré que les
règles de jugement étaient incomplètes ; complétées avant tout calcul :
- chaque témoin rend une alarme, une cause et un classement de tous les nœuds ; seuil
  d'alarme réglé sur les minutes normales d'apprentissage ; réglé sans puis avec exemples ;
- fausses alertes mesurées au fil du temps ; saine-09 à part (vue par la mise à l'échelle) ;
- top-k principal sans tenir compte de l'alarme, donné aussi « avec alarme » ;
- égalités départagées contre le témoin, jamais par l'ordre alphabétique des fichiers
  (il mettrait bmgvs et workers0 en tête, les fautifs fixes de la première série) ;
- mesures par minute et par injection ; une cause jamais vue est jugée sur toutes ses
  injections, la bonne cause y étant « panne inconnue ».
Et la lecture des campagnes à venir échoue bruyamment au lieu de se taire : campagne
interrompue, nom de cause inconnu, retrait raté, injection jamais retirée, compte
d'injections différent de l'en-tête, nombre de répliques de la lenteur.

## 2026-09-26 — Phase B.2 : le juge commun

`graphe_en/juge.py` (commits de B.2 jusqu'à 519c686) : tous les témoins, puis le GNN, passent
par lui. Il lit les 10 graphes figés (refusés s'ils ne sont pas conformes au gel), étiquette
chaque minute, coupe apprentissage et test, et note les réponses avec les règles de B.1.
`campagnes/etiquettes.txt` en garde la trace (identique sur le poste et sur vms0).

Étiquettes et coupure identiques à celles des lignes de base (`ligne_de_base.py`), minute
par minute, sur les 1 211 minutes : 408 normales, 458 de panne, 303 de vidange, 42 à cheval.
Test sans les écartées : 312 minutes, dont 153 de panne (8 injections, 6 avec un fautif) et
159 normales (39 de saine-09, marquées « vues » par la mise à l'échelle).

Une relecture indépendante (3 relecteurs, chaque constat revérifié) a trouvé de vrais
défauts, corrigés avant qu'un seul témoin soit calculé :
- le fautif n'était classé que parmi les nœuds notés par le témoin : un témoin qui ne
  notait RIEN obtenait 100 %. Il est maintenant classé parmi tous les nœuds de la fenêtre ;
- un NaN float32 (numpy, tenseur) sur le fautif le mettait premier ; classé dernier ;
- une alarme « False » (texte) ou 0,03 (probabilité) comptait comme alarme ; refusée,
  comme toute réponse mal formée ou un nœud nommé par son uid ;
- la bonne cause dépendait de la liste passée à la notation ; fixée une fois à la lecture.
Chaque correction a son essai dans le script (témoins factices de note connue, refus).

**Constat honnête, à écrire dans le rapport.** Un témoin « a priori », qui ne lit AUCUNE
donnée et classe les nœuds par le nombre de fois qu'ils ont été fautifs à l'apprentissage,
obtient déjà 100 % en top-1 sur la lenteur et 100 % en top-3 sur le blocage : les fautifs
sont toujours les trois mêmes répliques. Il fait 0 sur l'hôte. Sur les quatre causes
actuelles, les mesures qui départagent vraiment sont donc le top-1 du blocage et de l'hôte ;
et la base lente (C), dont le fautif n'a jamais été fautif, où ce plancher fait 0.

## 2026-09-26 — Phase B.3 : témoin 1, le tableau équitable

`graphe_en/temoin_tableau.py` (commits de B.3 jusqu'à 96d2622), résultat dans
`campagnes/temoin_tableau.txt` (identique sur le poste et sur vms0, 5 graines).

Ce qu'il voit : tous les nombres des nœuds (1128 par fenêtre, la base comprise, chaque pod
à une case fixe « service#rang »), plus des résumés sans identité : par sorte de nœud (max,
min, médiane, absents) et par relation (nombre de flèches, max et médiane de chaque
colonne). Il sait qu'un appel a ralenti quelque part, jamais qui appelle qui ni qui tourne
où. Deux forêts : la cause (rejet « inconnue » des deux côtés, seuils calés en mettant de
côté chaque injection ou campagne d'apprentissage) ; le fautif (une forêt pour tous les
nœuds, comme le GNN partage ses poids). Réglé avec exemples seulement : sans exemple, c'est
le score par nœud (témoin 2).

**Deux versions écartées, dites honnêtement.** (1) Rejet calé « hors sac » : trop sévère
(fenêtres voisines de la même injection dans les arbres), cause 33 % → recalé par injection
mise de côté. (2) Relecture indépendante : le fautif appris case par case ne pouvait désigner
que les 6 cases déjà fautives, plaçait la base dernière d'avance, et manquait le seul fautif
nouveau (tvmfl) ; les graines changeaient les chiffres ; il ne recevait aucun nombre des
flèches ; il ne pouvait pas dire « inconnue » d'une panne prise pour normale. Les quatre
points corrigés, chaque fois dans le sens qui RENFORCE le témoin (un adversaire faible
rendrait la victoire du GNN sans valeur).

Résultat (test, 5 graines, min–max) : détection 153/153 ; cause 149–153/153 (8/8
injections) ; fautif top-1 114–115/115, fautif nouveau 19/19 (6/6 injections) ; fausses
alertes 8–10/120 minutes normales non vues, 0/39 sur saine-09. Plancher « a priori » :
fautif top-1 57/115.

**Répétition d'une panne jamais vue** (une cause connue retirée de l'apprentissage, graine 0) :
- blocage retiré : détection 114/114, « inconnue » 114/114, fautif top-1 0/114 ;
- lenteur retirée : détection 114/114, « inconnue » 114/114, fautif top-1 0/114 ;
- hôte retiré : détection 3/117, fautif 0/117 (sans exemple, la panne CPU ressemble au normal).
Le tableau sait qu'une panne est NOUVELLE, pas OÙ elle est : son fautif n'a appris que les
motifs des causes vues. C'est le terrain de la première étape du GNN (l'écart au normal,
nœud par nœud) et du témoin 2.

## 2026-09-26 — Phase B.4 : témoin 2, le score par nœud

`graphe_en/temoin_noeud.py` (commit 4ca7001, puis 98ec3f9 et ea31952 après relectures ;
sortie de 4ca7001 gardée en 483e814), résultat dans `campagnes/temoin_noeud.txt` et `-validation.txt`.

Chaque nœud comparé à SON normal (appris sur les fenêtres normales d'apprentissage) :
écart robuste z par nombre, plus le nombre de valeurs absentes ; aucune flèche lue.
Deux réglages : **sans exemples** (score = plus grand |z| ; alarme au 95e centile du
normal mis de côté campagne par campagne ; cause « inconnue » dès qu'il sonne) et **avec
exemples** (détecteur forêt sur le profil d'écart, fautif par régression logistique
partagée, cause par prototypes avec rejet ; devant une panne « inconnue », le classement
retombe sur l'écart seul, comme le GNN désignera toujours par son étape 1).

**Quatre versions vues sur le test, dites** (`campagnes/versions-vues-sur-test/`) :
1. échelle par l'écart interquartile seul : seuil d'alarme 138 (pics rares de
   cpu_throttle_ratio, memory_slope) ; défaut vu sur le calage, mais la version avait
   aussi été notée sur le test (détection 48/153) ; corrigé ;
2. détecteur en régression logistique : seuil 0,043, 33/120 fausses alertes au test ;
   remplacé par une forêt APRÈS ce test ;
3. commit 4ca7001 (noté sur le test) : lenteur top-1 0/38 sans exemples ;
4. version finale, après deux relectures indépendantes. Leurs constats, vérifiés sur la
   **validation** (nouvelle, voir B.5), jamais sur le test :
   - le plancher d'échelle mesurait les différences de niveau entre nœuds : 0,28 en
     log pour le temps de traitement, 7 fois l'échelle propre des répliques, la lenteur
     n'y faisait que z = 1,5 ; maintenant, les écarts de chaque nœud à SA médiane ;
   - le détecteur apprenait sur des écarts au normal qui contient la fenêtre même : il
     apprend maintenant sur des écarts « croisés » (normal appris sans la campagne) ;
   - le fautif appris ne connaît que les pannes apprises : repli sur l'écart seul ;
   - distances aux prototypes mises à l'échelle.

**Résultat (test)** : sans exemples, détection 42/153, fausses alertes 5/120, fautif
top-1 100/115 (hôte 39/39, blocage 36/38, lenteur 25/38), 6/6 injections sans l'alarme.
Avec exemples (5 graines, médiane [min–max]) : détection 153/153, fausses alertes
28/120 [19–30], cause 130/153, fautif top-1 113/115.

**Ce qu'il apprend à la thèse.** Sans exemples, il désigne souvent la victime : la file,
dont le tas s'écarte bien plus que la réplique gelée ou lente. Ce résultat varie avec la
coupure : sur la validation, blocage top-1 1/38 et lenteur 0/38 (la file désignée),
contre 36/38 et 25/38 au test ; seul l'hôte est solide (39/39 partout). Avec exemples,
ses fausses alertes viennent de la dérive de fin de campagne : le CPU de
ts-order-service monte avec la table des commandes (relecture B.7 ; ce n'est pas un
reste de la panne d'hôte, selon la relecture ; à montrer sur ces fenêtres). Elles se
groupent juste après une injection de hote-01 : au test 13 sur 16 après la dernière, sur
la validation 11 sur 14 après la deuxième, en milieu de campagne. Il connaît chaque nœud
par son nom, ce que le GNN ne fait pas.

## 2026-09-26 — Phase B.5 : témoin 3, la règle qui suit les flèches

`graphe_en/temoin_fleches.py` (commits 98ec3f9, 483e814, ea31952), résultat dans
`campagnes/temoin_fleches.txt` et `-validation.txt`. Bibliothèque standard seulement.

La définition du 24 sept. : la file → ses répliques → leur machine, puis ce qu'elles
appellent → le dernier composant anormal. Écrite comme par un ingénieur qui connaît la
plateforme, le graphe figé et les quatre causes (sa structure reprend le tableau « quelle
panne fait bouger quoi » du LEXIQUE) ; limites d'alarme calées sur le normal seul.
**Deux versions, notées côte à côte** :
- **littérale** : la cible appelée est accusée si ses propres nombres sont anormaux ;
- **cause commune** : la cible est accusée si la plupart des AUTRES services qui
  l'appellent la voient aussi plus lente. Principe général (« lent pour tout le monde,
  ou pour moi seulement ? »), rien de propre à une base ; mais choisi par celui qui
  prépare la base lente, entre deux règles que la validation ne distingue pas (la cause
  commune ne se déclenche sur aucune panne connue ; au test, la littérale sans exemples
  accuse la base dans 25 fenêtres de lenteur) : d'où les deux versions.

**Versions vues sur le test, dites.** La première version a été notée sur le test
(détection 107/153, cause 52/153, lenteur top-1 0/38), puis changée : deux limites
d'alarme au lieu d'une ; charge par élimination ; et surtout le plancher fautif du
témoin 2, qui la rendait aveugle à la lenteur. Les chiffres de la règle sur les causes
connues sont donc « après une révision informée par le test ». La base lente ne l'est
pas, si la règle est figée avant C. Après deux relectures, vérifié sur la validation
seule : la saturation d'une machine = sa pression, pas son occupation (cpu_busy suit la
dérive de ts-order-service : fausses alertes 21 → 2 sur 102) ; réplique gelée = plus de
temps de traitement ; autres appelants comptés par service ; désignés à égalité.

**Outil nouveau : `juge.validation()`**, la coupure répétée une injection plus tôt, le
vrai test mis de côté (option `--validation` des scripts). **Depuis, tout choix de réglage
(témoins, puis GNN) se fait sur la validation, jamais sur le test.** Les pannes de la
base lente y sont toujours mises de côté (relecture B.7).

**Résultat (test)** : cause commune, sans exemples : détection 153/153, fausses alertes
10/120, cause 150/153, fautif top-1 115/115 ; avec exemples : cause 153/153, top-1
115/115. Littérale, sans exemples : cause 125/153, top-1 90/115, lenteur 13/38 (elle
accuse la base dans des fenêtres de lenteur : son épreuve compare au seuil de la file le
plus grand |z| des douze nombres de la base, que le bruit dépasse souvent) ; avec
exemples : 153/153, 115/115. Sur la validation, les deux versions font pareil : fausses
alertes 2/102 et top-1 114/115 pour les quatre, cause 150/153 sans exemples, 152/153 avec.

**Ce qu'elle sait de plus que le GNN** (à dire au rapport) : le normal de chaque nœud par
son nom, celui de chaque flèche par (relation, service source, service cible), les
consommateurs attendus de chaque file, les signatures des quatre causes écrites à la
main. C'est la référence experte sur les pannes connues ; ses presque 100 % y sont un
plafond par construction.

## 2026-09-26 — Phase B.6 : les témoins côte à côte

`graphe_en/temoins.py`, résultat dans `campagnes/temoins.txt` (test) et
`temoins-validation.txt`. Rien n'y est réglé : chaque témoin est appris par son fichier.

**Tableau de bord (test ; médiane sur 5 graines pour ce qui tire au hasard)**

| témoin | détection | fausses alertes /120 | cause | fautif top-1 /115 | nouveau /19 |
|---|---|---|---|---|---|
| tableau équitable | 153 | 9 [8–10] | 150 | 115 | 19 |
| score par nœud, sans exemples | 42 | 5 | 0 (par construction) | 100 | 17 |
| score par nœud, avec exemples | 153 | 28 [19–30] | 130 | 113 | 18 |
| règle littérale, sans / avec | 153 | 10 | 125 / 153 | 90 / 115 | 19 |
| règle cause commune, sans / avec | 153 | 10 | 150 / 153 | 115 | 19 |
| a priori (ne lit rien) | 0 | 0 | 0 | 57 | 0 |

**Fausses alertes au fil du temps.** Au test, aucune sur saine-08 ni saine-09 (fin de
campagne), aucune sur hote-02 (sur la validation : toujours aucune sur saine-08, mais le
score par nœud en fait 2 sur 26 sur saine-09 et 1 à 3 sur hote-02). Elles tombent après la dernière injection de charge-03 (4 à 6 sur 8
pour tous) et de hote-01 (le score par nœud avec exemples : 13 sur 16 ; les autres : 0 à
3). La relecture B.7 les attribue à la dérive de ts-order-service ; elles suivent de près
une injection : à montrer fenêtre par fenêtre avant de l'écrire au rapport.

**Répétition « panne jamais vue »** (une cause connue retirée de l'apprentissage ; toutes
ses injections au test) — le fautif top-1 :

| cause retirée | tableau | score par nœud (sans / avec) | règle (4 variantes) |
|---|---|---|---|
| blocage | 0/114 | 101/114 | 114/114 |
| hote | 0/117 | 117/117 | 117/117 |
| lenteur | 0/114 | 89/114 | 84 à 114/114 |

- Le tableau sait qu'une panne est nouvelle (« inconnue » 114/114 pour blocage et
  lenteur), jamais **où** elle est. Il ne voit presque pas un hôte jamais vu (3/117).
- Le score par nœud désigne un fautif qu'il n'a jamais vu fauter : c'est l'écart au normal
  nœud par nœud, l'idée de l'étape 1 du GNN. Mais sur la validation, il n'y arrive que
  pour l'hôte (78/78 ; blocage 1/76, lenteur 0/76 : il désigne la file, victime).
- La règle porte les noms des quatre causes et chaque branche a été écrite pour sa cause :
  sa colonne « inconnue » est sans objet, ses lignes ne se comparent pas au GNN. Seule la
  base lente l'éprouvera.
- La relecture B.7 nuance aussi B.3 : sur la validation, le tableau dit « inconnue » pour
  un blocage jamais vu dans 15/76 fenêtres seulement (il le prend pour une charge).

## 2026-09-26 — Phase B.7 : relecture finale des trois témoins, et gel

Deux relectures finales indépendantes (les trois témoins ensemble ; l'équité au niveau
de la thèse). Aucune fuite, aucun défaut de calcul dans le tableau. Corrigé (commit
ea31952) : les pannes de la base lente ne peuvent pas entrer dans la validation ; les
totaux par injection et le tableau de bord montrent une cause jamais vue à part ; les
résultats des deux séries ne sont jamais écrasés par une lecture qui ajoute C (fichiers
`<témoin>-<campagne>.txt`) ; chaque sortie dit les campagnes lues ; le tableau affiche son
budget de fausses alertes ; les versions vues sur le test sont dites dans chaque en-tête et
dans `campagnes/versions-vues-sur-test/LISEZMOI.md` (regards sur le test, version finale
comprise : tableau 3, score par nœud 4, règle 2). Chaque changement visait à renforcer le
témoin ; au test, c'est vrai pour le tableau (cause 144 → 150/153, top-1 94 → 115/115), la
règle (cause 52 → 150/153) et le score par nœud sans exemples (lenteur 0 → 25/38), mais le
score par nœud avec exemples y perd un peu (cause 136 → 130/153, top-1 114 → 113/115), et le
tableau fait 9/120 fausses alertes au lieu de 0 depuis son rejet des deux côtés.

**Budgets de fausses alertes** (fenêtres normales mises de côté, campagne par campagne) :
tableau et score par nœud sans exemples 13/249 = 5,2 % chacun (le même centile sur les
mêmes fenêtres ; les plus serrés) ; score par nœud avec exemples 25/249 = 10 % (deux
alarmes) ; règle 21/249 = 8,4 % (file et machines). Les fausses
alertes se comparent donc à budget égal, et par campagne (quelques fenêtres = du bruit).

**Ce que les témoins savent de plus que le GNN** : les noms (normal par nœud, cases du
tableau), le normal de chaque flèche par paire de services et les consommateurs attendus
(règle), les signatures des causes (règle), la cause commune écrite en sachant que C est
une base lente. Une victoire du GNN est donc prudente ; une défaite peut venir en partie
de là.

### Écrit AVANT la phase C : ce qui décidera (PROPOSÉ le 26 sept., à valider par l'utilisateur)

La logique du 24 sept. (un témoin sans flèches trouve la base lente → arrêter le
GNN ; seule la règle qui suit les flèches → H1 gagnée, le GNN seulement s'il bat la
règle ; personne → GNN justifié) n'était plus assez précise : la règle a deux
versions et deux réglages, le score par nœud deux réglages. La relecture finale
prévoit même que les deux réglages de la règle répondront à l'opposé. Table
proposée, à figer avant C :

**Mise en place.** Code à l'étiquette `temoins-figes`, inchangé. C lue par le juge
avec les causes jamais vues par défaut (base, reseau). Il faut au moins 2 injections
« base » confirmées, sinon C est refaite à l'identique.

**Mesure principale, par injection** (règle du 26 sept.) : F = tsdb-mysql-0 est
premier dans plus de la moitié des fenêtres de panne de l'injection, sans tenir
compte de l'alarme. A = la même avec l'alarme, donnée à côté. Méthodes au hasard :
médiane des graines 0 à 4, avec le minimum et le maximum.

**TROUVE** (pour une méthode) : F sur une majorité stricte des injections confirmées,
ET garde de spécificité G : sur aucune des 8 injections de test des causes connues,
tsdb-mysql-0 n'est premier dans plus de la moitié des fenêtres (une méthode qui
accuse la base partout ne « trouve » rien).

**Décisions, dans cet ordre**
1. Le tableau ou le score par nœud (l'un ou l'autre réglage) TROUVE → les nombres
   des nœuds suffisent : on arrête le GNN sur C.
2. Sinon, une version de la règle TROUVE → H1 soutenue. Le GNN n'est justifié que
   s'il TROUVE (au moins autant d'injections que la meilleure règle) ET gagne
   nettement sur au moins un axe sans perdre sur aucun :
   - (a) fausses alertes sur toutes les fenêtres normales du test, à budget égal
     (marge : au moins 3 fenêtres et 25 %, sur toutes les graines) ;
   - (b) alarme plus tôt dans au moins 2 injections sur 3 ;
   - (c) détection et désignation sur les fenêtres de C où la file ne se remplit
     pas (tas ≤ 10), là où la règle, partie de la file, ne va pas ;
   - (d) les jumeaux (phase D), table écrite avant D.
   « Inconnue » n'est pas un axe contre la règle (elle le dit par construction).
3. Personne ne trouve → le GNN est justifié s'il TROUVE. Si la plupart des fenêtres
   de C ont un tas ≤ 10 : dire « une règle partie de la file ne peut pas
   l'atteindre », pas « les flèches demandent un GNN ».

**Prédictions écrites avant C** (base ralentie d'environ 75 ms par échange, comme
la lenteur) :
- règle, cause commune, sans exemples : trouve (inconnue, tsdb-mysql-0), si la file
  se remplit et que la flèche des répliques vers la base dépasse s ;
- règle, cause commune, avec exemples : répond « lenteur, les répliques » (sa limite
  s = 5 laisse la flèche des répliques sous le seuil ; au-delà d'environ +140 ms
  elle trouverait aussi) ;
- règle littérale : réponse qui dépend du bruit. Sans exemples, la garde G l'écarte
  probablement déjà (au test, elle accuse une dépendance dans la plupart des fenêtres de
  lenteur-01 : vérifier que c'est tsdb-mysql-0) ; avec exemples (s = 5), elle n'accuse la
  base dans aucune panne connue et G ne l'écartera pas ;
- tableau : ne sait pas désigner le fautif d'une cause jamais vue (0 % dans la
  répétition), alors qu'il trouve un fautif nouveau d'une cause connue (19/19) ;
  nommera probablement la cause « lenteur » (ses nombres les plus utiles sont la
  latence des flèches queries, le tas et le temps de traitement) ;
- score par nœud : la base ne bouge presque pas elle-même (pas d'exportateur MySQL :
  c'est l'instrumentation qui la rend muette, à dire) ; il désignera une victime.

### Le calage de l'étape 1 du GNN, écrit avant (PROPOSÉ)
1. Fenêtres d'apprentissage du juge ; l'étape 1 n'apprend que sur les normales.
2. Chaque campagne mise de côté à son tour : l'étape 1 réapprise sans elle (mêmes
   réglages, même graine), score de ses fenêtres normales ; tous mis ensemble.
3. Score d'une fenêtre = le plus haut score de nœud, le même qui sert au classement ;
   l'erreur d'un nœud divisée par l'échelle robuste de sa sorte dans le pli. Comment
   l'erreur d'une flèche est rendue aux nœuds (la cible, la source, les deux) : fixé
   avant C.
4. Seuil = 95e centile ; plusieurs signaux d'alarme → leur union calée à 5 %, et
   aussi donnée au budget de la règle.
5. Modèle final sur toutes les normales d'apprentissage ; graines 0 à 4, chacune
   avec son calage.
6. Rejet de l'étape 2 : chaque injection mise de côté, 95e centile des distances des
   fenêtres bien classées (comme le tableau et le score par nœud).
7. Jamais les fenêtres de test, jamais les pannes de C, jamais `--validation` avec C
   (le juge la met « hors » de toute façon).
8. Tout choix du GNN (architecture, réglages) se fait sur la validation, ou sur la
   répétition « panne jamais vue » des causes connues ; jamais sur C.

### Les conditions de C, à fixer et noter avant (PROPOSÉ ; jamais réglées sur un témoin)
- Mécanisme : un retard réseau sur le pod leader tsdb-mysql-0 seul, vers tous ses
  clients, sans perte ni gigue ; vérifier qu'il ne double pas le retard permanent du
  chemin répliques → base. Écrire la prédiction sur les nombres de la base.
- Intensité : +75 ms (le même retard par échange que la lenteur). Écrire maintenant
  la règle de repli et le critère d'effondrement (par ex. erreurs Locust > 5 %).
  L'essai de calage n'est jamais noté ni pris dans le normal.
- Déroulé et charge identiques à la seconde série (3 × 20 min, mêmes écarts, 135 min,
  mêmes paliers Locust, même réglage du consommateur).
- Purge : `donnees.sh purger --redemarrer` juste avant, aucune entre les injections ;
  noter l'heure, le cpu de ts-order-service et la taille de la table des commandes à
  chaque injection (la dérive).
- Placement : pod → machine au début et à la fin (campagne.sh, à coder) ; accepté tel
  quel, jamais retiré au sort ; dire avant de noter si une réplique partage sa machine
  avec ts-order-service ou tsdb-mysql-0.
- Leader : vérifier que tsdb-mysql-0 est le leader avant et après.
- Noter sans viser : le tas, les débits de dépôt et de retrait. Que la file se
  remplisse n'est pas un but.
- Instrumentation inchangée : pas d'exportateur MySQL, gel.py CONFORME, cause nommée
  « base » dans panne.sh et campagne.yaml.
