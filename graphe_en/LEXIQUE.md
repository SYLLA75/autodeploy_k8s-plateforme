# Lexique du graphe — ce que veut dire chaque nombre

Ce fichier dit, pour chaque attribut d'une fenêtre, d'où vient le nombre,
dans quelle unité il est, ce qu'il vaut quand tout va bien, et quelle panne
le fait bouger. Les valeurs « saines » sont celles de la référence saine-07
(25 voyageurs) ; les valeurs « en panne » viennent des essais courts du 12
septembre 2026 (`campagnes/essai-*/lecture.txt`).

## D'où viennent les nombres

Dans le magasin d'objets, il n'y a aucun « par minute ». Il y a deux sortes
de données brutes :

| brut | ce que c'est | exemple |
|---|---|---|
| une **trace** (un *span*) | un événement unitaire : « ce service a traité cette requête, de tel instant à tel instant, avec ou sans erreur » | un span de 706 ms sur `ts-delivery-service` |
| un **échantillon de métrique** | une valeur relevée toutes les 15 s : un compteur qui monte, ou un niveau | `rabbitmq_queue_messages_ready = 548` |

Tout ce qu'on lit dans le graphe est **calculé à partir de ça**, fenêtre par
fenêtre, par les modules de `graphe_en/` :

```
fetch.py       rapatrie les fichiers de la plage
otlp.py        les lit : traces → spans, métriques → échantillons
windows.py     coupe la plage en fenêtres de 60 s (config.yaml : windows.width_s)
nodes.py       liste ce qui existe dans la fenêtre : pods, files, hôtes
features.py    calcule les nombres de chaque nœud
edges.py       calcule les flèches : qui appelle qui, qui dépose, qui retire
snapshot.py    écrit la fenêtre en JSON (window_0042.json)
export_pyg.py  met les JSON en tenseurs (graph.pt) — même contenu, autre forme
```

`features.py` n'a que cinq façons de résumer une minute :

| opérateur | ce qu'il fait | sert à |
|---|---|---|
| **last** | la dernière valeur de la fenêtre | `backlog`, `consumers`, `memory_used` |
| **extreme** | le minimum ou le maximum de la fenêtre | `memory_available_min` |
| **increase** | de combien un compteur a monté pendant la fenêtre | base des débits |
| **rate** | increase ÷ 60 → « par seconde » | `publish_rate`, `cpu_rate`, `call_rate` |
| **quantile** | percentile des durées des spans de la fenêtre | `process_time_p50`, `latency_p95` |

Plus la **pente** : la différence avec les fenêtres précédentes
(`backlog_slope`, `memory_slope`, sur `graph.slope_horizon` fenêtres).

**Les percentiles (p50, p95, p99).** On classe les durées de la minute de la
plus courte à la plus longue. p50 = la médiane : la moitié ont pris moins.
p95 = 95 % ont pris moins. p99 = 99 %. Le p50 dit le cas courant, le p99 le
pire cas fréquent.

**Unités.** Les temps sont en **millisecondes**, les débits en **par
seconde**, les pentes en **par minute**, les parts (cpu, pression, erreurs)
**entre 0 et 1**, la mémoire en **octets**.

## La file (nœud `queue`, ici `food_delivery`)

| attribut | en mots | calcul | sain | en panne |
|---|---|---|---|---|
| `backlog` | le tas : messages qui attendent | last de `messages_ready` | 0 à 4 | 500–800 |
| `backlog_slope` | de combien le tas change par minute | pente | 0 | +40 (monte), −40 (fond) |
| `publish_rate` | messages déposés par seconde | rate | 3,5 | 4,9 (charge à 35 voyageurs) |
| `consume_rate` | messages retirés par seconde | rate | 3,5 | 4,25 au plus (3 répliques × 706 ms) ; 2,8 (lenteur) |
| `rate_imbalance` | dépôts − retraits | différence | 0 | +0,7 |
| `consumers` | répliques abonnées à la file | last | 3 | 2 (blocage, après ~2 min) |

## Une instance (nœud `instance`, un pod — 58 par fenêtre)

Les valeurs saines sont celles d'une réplique de `ts-delivery-service`.

| attribut | en mots | calcul | sain | en panne |
|---|---|---|---|---|
| `process_time_p50/p95/p99` | temps pour traiter un message pris dans la file | quantile des spans « consommateur » | 706 / 707 / 846 ms | 2 206 ms (lenteur +300), 1 081 (lenteur +75), absent (gelée) |
| `request_time_p50/p95/p99` | temps pour répondre à une requête HTTP (services web) | quantile des spans « serveur » | 29 / 35 / 38 ms (`ts-travel-service`) | monte quand l'application s'étouffe |
| `error_ratio` | part des requêtes en erreur | erreurs ÷ requêtes | 0 | > 0 si des 500 apparaissent |
| `cpu_rate` | part d'un cœur utilisée (1 = un cœur entier) | rate de `cpu_usage_seconds` | 0,003 | 0,000 (gelée) |
| `cpu_throttle_ratio` | part du temps où Kubernetes a bridé le conteneur | rate | 0 | > 0 s'il tape sa limite |
| `memory_used` | mémoire occupée | last | 427 M | inchangée (gelée), monte si fuite |
| `memory_slope` | variation de mémoire par minute | pente | 0 | > 0 si fuite |
| `memory_limit`, `cpu_quota` | plafonds fixés par Kubernetes | last | 2 G, 0,5 cœur | constants |
| `restarts` | redémarrages du conteneur | last | 0 | > 0 si crash |
| `rx_bytes` | octets reçus par seconde | rate | ~1 100 | suit le trafic |
| `rx/tx_packets_dropped`, `rx_errors` | paquets perdus ou en erreur | rate | 0 | > 0 en panne réseau |

Une réplique gelée (blocage) n'a **plus** de `process_time` : elle ne traite
rien, donc aucun span. L'absence est portée par un masque, pas par un zéro
(`export.missing: mask`).

## Un hôte (nœud `host`, une machine — 8 par fenêtre)

| attribut | en mots | calcul | sain | en panne (hote) |
|---|---|---|---|---|
| `cpu_busy` | part du temps où les cœurs travaillent | rate | 0,04 | 0,83 |
| `cpu_pressure` | part du temps où un programme attend un cœur libre (PSI) | rate | 0,01 | 0,63 |
| `memory_pressure` | idem pour la mémoire | rate | 0 | 0 |
| `io_pressure` | idem pour le disque | rate | 0 | 0 |
| `memory_available_min` | mémoire libre au pire moment de la minute | extreme (min) | 2,8 G | baisse si un voisin mange la mémoire |

`cpu_pressure` n'est pas « part du processeur utilisée » (ça, c'est
`cpu_busy`) : c'est une part de *temps d'attente*. À 0,63, les programmes
attendent un cœur 63 % du temps.

## Les relations (les flèches)

| relation | attributs | en mots | exemple sain |
|---|---|---|---|
| `calls` (instance → instance) | `call_rate`, `latency_p50/p95/p99`, `error_ratio` | appels/s, durée de l'appel vu de l'appelant, part en erreur | travel → seat : 6,5/s, 5 / 6 / 10 ms, 0 |
| `publishes` (instance → file) | `rate` | messages déposés/s par ce service | food → food_delivery : 3,5/s |
| `consumes` (file → instance) | `rate` | messages retirés/s par cette réplique | 1,2/s chacune (3 × 1,2 ≈ 3,5) |
| `executes_on` (instance → hôte) | aucun | le lien, seulement | — |

## Quelle panne fait bouger quoi

| panne | ce qui bouge | ce qui ne bouge pas |
|---|---|---|
| charge | `publish_rate` ↑, `backlog` ↑, `call_rate` en amont ↑ | `process_time`, `consumers`, hôtes |
| lenteur | `process_time_*` des 3 répliques ↑, `latency_*` réplique → base ↑, `consume_rate` ↓, `backlog` ↑ | `publish_rate`, cpu, hôtes |
| blocage | `consumers` 3 → 2, une réplique à `cpu_rate` 0 sans `process_time`, `backlog` ↑ | `publish_rate`, les 2 autres répliques |
| hote | `cpu_busy`, `cpu_pressure` d'un hôte ↑ | **tout le reste, file comprise** (mesuré : la demande CPU du pod le protège) |

Ce qui ne bouge pas compte autant que ce qui bouge : c'est ce qui permet
d'exclure les autres causes.

## Brut, tableau, tenseur : trois formes du même nombre

| où | forme | un `cpu_rate` négatif y veut dire |
|---|---|---|
| `window_*.json`, `lecture.txt` | valeurs **brutes** | une erreur (compteur remis à zéro) — ne devrait pas arriver |
| `graph.pt` | valeurs **mises à l'échelle** : (valeur − moyenne saine) ÷ écart-type sain, avec `scaler.json` calculé sur la référence | « un peu en dessous de la moyenne saine » — normal |

Le modèle voit la forme mise à l'échelle : il apprend l'écart à la normale,
en unités d'écart-type. Un `publish_rate` à +3, c'est « très au-dessus de ce
qu'on voit sain » — c'est une charge.

## Pourquoi 60 secondes, et pourquoi ne pas y toucher

Plus court, une fenêtre a trop peu de messages (à 3,5/s, 10 s = 35 messages :
un percentile n'y veut rien dire). Plus long, une panne de 20 min ne ferait
que 4 fenêtres et son début serait noyé. À 60 s, une injection = 20
fenêtres, et son début se voit dès la première. Une référence à 60 s et une
panne à 30 s ne seraient plus comparables : débits, pentes et percentiles
n'auraient pas la même signification.
