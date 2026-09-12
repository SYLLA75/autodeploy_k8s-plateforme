# Procédure — de zéro à une plateforme qui mesure

> Toutes les commandes, dans l'ordre, depuis la création des machines.
> Chaque étape indique **où** la lancer, **combien de temps** elle prend, et
> **ce que tu dois voir** si elle a réussi.
>
> Sur la grappe actuelle, les étapes 1 à 7 sont déjà faites.

---

## Avant de commencer — une seule fois

Deux fichiers doivent exister sur ton PC, dans `~/autodeploy_k8s` :

**`.env`** — la configuration. Elle existe déjà. Vérifie seulement qu'elle vise
la bonne application :

```bash
grep '^APPS=' ~/autodeploy_k8s-plateforme/.env
```

**`.env.secrets`** — les identifiants du magasin d'objets. Ce fichier est ignoré
par git, il ne doit **jamais** être committé.

```bash
cat ~/autodeploy_k8s-plateforme/.env.secrets
```

Tu dois y voir `OBS_S3_ENDPOINT`, `OBS_S3_BUCKET`, `OBS_S3_ACCESS_KEY`,
`OBS_S3_SECRET_KEY`.

---

## Étape 1 — Créer les machines, Kubernetes et l'application

**Où** : sur ton PC · **Durée** : 45 à 60 minutes

```bash
cd ~/autodeploy_k8s
./deploy.sh --app train-ticket
```

Cette seule commande réserve les machines sur SLICES-RI, installe Kubernetes,
prépare le stockage, **réserve le nœud de mesure**, puis déploie les 56 pods de
train-ticket.

Le nœud de mesure est celui nommé par `OBS_DEDICATED_NODE` dans `.env`. Il est
marqué **avant** le déploiement de l'application, qui ne s'y installe donc
jamais. Sans cette précaution, l'isolement ultérieur laisse des volumes
applicatifs coincés dessus : un volume `local-path` est attaché à sa machine et
ne peut plus être déplacé.

`PROFILE_TT_WORKERS` vaut 7 pour cette raison : six machines pour l'application,
une pour la mesure.

**Ce que tu dois voir à la fin** : un récapitulatif avec l'adresse du master et
les URLs de l'application.

**Vérification** :

```bash
ssh master 'kubectl get nodes'
ssh master 'kubectl get pods -n train-ticket --no-headers | wc -l'
```

Sept machines, et 56 pods.

> Si ça échoue, relance la même commande : le script est rejouable, il réutilise
> ce qui existe déjà.

---

## Étape 2 — Envoyer les identifiants du magasin sur le master

**Où** : sur ton PC · **Durée** : une seconde

```bash
scp ~/autodeploy_k8s-plateforme/.env.secrets master:/home/ubuntu/autodeploy/.env.secrets
ssh master 'chmod 600 /home/ubuntu/autodeploy/.env.secrets'
```

`deploy.sh` copie les scripts mais pas ce fichier — il ne doit pas traîner dans
un dossier suivi par git.

---

## Deux copies des scripts, et comment les garder d'accord

Les scripts de `apps/` vivent à deux endroits :

| où | quoi |
|---|---|
| ton nœud de contrôle, dans le dépôt | la version de référence, celle que `git pull` met à jour |
| le master, dans `~/autodeploy/apps/` | la copie qui s'exécute, faite au moment du déploiement |

**Un `git pull` ne touche pas la copie du master.** Elle date du dernier
déploiement, et rien ne le signale : les scripts s'exécutent sans se plaindre,
dans leur ancienne version.

Le geste à retenir, en une seule commande, depuis la racine du dépôt sur le nœud
de contrôle :

```bash
git pull && ./deploy.sh --push-scripts
```

Ça ne déploie rien, ne redémarre rien, ne touche pas aux applications. Ça recopie
les fichiers de `apps/` sur le master, et c'est tout — quelques secondes. Sans
danger même pendant une campagne de mesure en cours.

**Quand est-ce nécessaire ?** Uniquement si le `git pull` a modifié quelque chose
dans `apps/`. Le reste du dépôt s'exécute sur le nœud de contrôle et n'a pas de
copie ailleurs :

| ce qui a changé | ce qu'il faut faire |
|---|---|
| `apps/*.sh` | `git pull && ./deploy.sh --push-scripts` |
| `apps/loadgen/locustfile.py` | `--push-scripts`, **puis réinstaller le générateur** |
| `graphe_en/`, `deploy.sh`, `lib/`, la documentation | `git pull` suffit |

Dans le doute, lance la commande complète : recopier des fichiers identiques ne
coûte rien.

### Les parcours de trafic ont un piège de plus

`locustfile.py` ne vit pas dans l'image du générateur : il est envoyé dans une
ressource de configuration **au moment de l'installation**. Le copier sur le
master ne suffit donc pas — le générateur qui tourne garde l'ancienne version,
sans rien signaler.

```bash
ssh master 'bash ~/autodeploy/apps/loadgen.sh uninstall && bash ~/autodeploy/apps/loadgen.sh install'
```

Deux minutes. C'est le seul moyen de recharger les parcours.

---

## Étape 3 — Poser la chaîne de mesure

**Où** : sur le master · **Durée** : 5 à 10 minutes

```bash
ssh master
set -a; . ~/autodeploy/.env.secrets; set +a
export OBS_DEDICATED_NODE=workers6
bash ~/autodeploy/apps/observability.sh install
```

Installe le relevé des machines, celui de Kubernetes, les deux collecteurs, la
visionneuse de traces, et ouvre le port de mesure du courtier.

**Vérification** :

```bash
kubectl get pods -n observability
```

Dix-sept pods, tous en `Running`.

> `OBS_DEDICATED_NODE` doit valoir le **même nœud** que celui réservé par
> `deploy.sh` à l'étape 1 — celui nommé dans `.env`. Il place directement les
> composants et leurs disques sur ce nœud. Sans lui, il faudrait tout déplacer
> ensuite, et les disques seraient perdus au passage : un volume `local-path`
> ne suit pas son pod.

---

## Étape 4 — Vérifier la réservation du nœud de mesure

**Où** : sur le master · **Durée** : quelques secondes

Le nœud nommé dans `OBS_DEDICATED_NODE` a été réservé automatiquement par
`deploy.sh`, **avant** le déploiement de l'application. Il reste à le vérifier.

```bash
kubectl get node "$OBS_DEDICATED_NODE" -o jsonpath='{.spec.taints}'; echo
kubectl get pods -n train-ticket -o wide --no-headers | awk '{print $7}' | sort | uniq -c
```

Une marque `dedicated=observability:NoSchedule`, et aucun pod de l'application
sur ce nœud.

**Pourquoi cette réservation précède le déploiement.** Un volume `local-path`
est attaché à la machine qui l'a créé. Si l'application s'installe d'abord sur
ce nœud, ses volumes y restent et les pods qui les utilisent ne peuvent plus
bouger : ils restent `Pending` indéfiniment. Marquer le nœud avant supprime le
problème par construction.

> **Repli.** Si tu as déployé l'application sans réservation préalable :
>
> ```bash
> bash ~/autodeploy/apps/observability.sh isolate <nœud>
> ```
>
> Il évacue les pods qui peuvent l'être, et **nomme** ceux qui ne le peuvent pas
> — ceux dont le volume est sur ce nœud. Ces derniers restent en place avec une
> tolérance : les déplacer demanderait de supprimer leur volume.

---

## Étape 5 — Faire parler les 46 services

**Où** : sur le master · **Durée** : 15 à 20 minutes

```bash
bash ~/autodeploy/apps/instrument.sh install --all
```

Attache un observateur à chaque service Java. **Le code de train-ticket n'est
pas modifié** : un conteneur d'amorçage dépose l'observateur à côté, et Java le
charge au démarrage.

**Vérification** :

```bash
bash ~/autodeploy/apps/instrument.sh status
```

Quarante-six déploiements listés.

---

## Étape 6 — Trois copies du consommateur

**Où** : sur le master · **Durée** : une minute

```bash
kubectl scale deploy ts-delivery-service -n train-ticket --replicas=3
```

**Pourquoi** : une des quatre causes à départager est « une copie est bloquée,
les autres vont bien ». Avec une seule copie, il n'y a pas de « les autres ».

**Vérification** :

```bash
R=$(kubectl get pods -n train-ticket --no-headers | grep -i rabbit | head -1 | cut -d' ' -f1)
kubectl exec -n train-ticket $R -- rabbitmqctl list_queues name consumers
```

`food_delivery` doit afficher **3** consommateurs.

---

## Étape 6 bis — L'injecteur de pannes

**Où** : sur le master · **Durée** : 5 minutes

```bash
bash ~/autodeploy/apps/chaos.sh install
bash ~/autodeploy/apps/chaos.sh isolate workers6
```

**À installer AVANT la campagne de référence, même si tu n'injectes rien tout de
suite.** Le démon tourne sur chaque nœud, y compris ceux qu'on mesure. Son coût
est faible mais réel, et il doit être présent des deux côtés — référence saine et
campagnes de panne. Sinon la différence entre les deux contient son coût à lui,
mêlé à celui de la panne, et le modèle apprendrait « Chaos Mesh présent = panne ».

**Vérification** :

```bash
bash ~/autodeploy/apps/chaos.sh status
```

```
     3       types d'injection disponibles
     1       contrôleur(s) en marche
     8/8     démons — un par nœud

  [chaos] OK  prêt à injecter
```

Les trois lignes comptent. Des pods « Running » ne suffisent pas : sans les
définitions d'injection rien n'est possible, et **un nœud sans démon ne peut pas
être touché** — ce qui ne se verrait qu'au moment de l'injection ratée.

### Pourquoi un outil plutôt que des commandes

Les quatre causes s'injectent toutes à la main. Deux le font mal :

| cause | à la main | avec Chaos Mesh |
|---|---|---|
| ralentir un service | baisser la limite CPU déclenche un redémarrage roulant — **nouveaux nœuds dans le graphe** | le retard est posé dans le pod existant, sans redémarrage |
| saturer un hôte | une charge qu'il faut lancer, puis penser à arrêter | la durée est portée par l'objet injecté : il s'arrête seul |

Et une raison qui n'est pas technique : « injecté avec Chaos Mesh 2.x » se
vérifie, « injecté par un script maison » se croit sur parole.

Bloquer une réplique tient en un `SIGSTOP` (les pods de train-ticket n'ont
pas de sonde de vivacité), mais il doit partir **de la machine** : Java est le
processus 1 de son conteneur, et le noyau lui fait ignorer les signaux venus
de l'intérieur du conteneur. C'est le démon Chaos Mesh du nœud, qui voit les
processus de la machine, qui l'envoie. Les quatre injections sont faites par
`apps/panne.sh` (étape 11) ; `chaos.sh` installe seulement l'outil.

### À figer

L'installation affiche la version du chart. Reporte-la dans `.env` —
`CHAOS_VERSION=…` — sans quoi une réinstallation dans six mois prendra une autre
version, et l'expérience ne sera plus rejouable.

---

## Étape 7 — Le générateur de trafic

**Où** : sur le master · **Durée** : 2 minutes

```bash
bash ~/autodeploy/apps/loadgen.sh install
bash ~/autodeploy/apps/loadgen.sh isolate workers6
```

Sans trafic, l'application ne fait rien : les services ne s'appellent pas et les
files restent vides.

Quatre parcours, avec des poids choisis pour que le débit de la file suive le
nombre de voyageurs :

| parcours | poids | rôle |
|---|---|---|
| 40 commander un repas | 6 | un appel direct à `ts-food-service` → un message dans `food_delivery`. **C'est lui qui fixe le débit de la file** |
| 30 réserver un billet | 2 | la chaîne complète (chercher, contacts, réserver) → les relations d'appel du graphe |
| 10 chercher un train | 1 | l'appel lourd de l'application, gardé bas |
| 60 déclencher un courriel | 1 | un message dans `email` |

Avec un rythme de 5 s : **0,12 message/s par voyageur**, soit 3/s à 25
voyageurs, 6/s à 50. Les voyageurs partent à des dates réparties sur le mois
qui vient (`TT_JOURS_ETALEMENT`, défaut 30) : réservés tous le même jour, les
commandes s'accumulent sur un seul train et une seule date, et c'est ce que
le service des commandes ne supporte pas (voir « Avant chaque campagne »).

Pourquoi la réservation seule ne suffisait pas : mesuré sur une heure, à 10,
30 puis 55 voyageurs, la file recevait 0,5 puis 0,5 puis 0,25 message/s. Le
débit ne suivait pas les voyageurs, il baissait — la recherche de train
ralentit dès 10 voyageurs, et chaque voyageur réserve moins. « Plus de charge
en amont » n'aurait jamais pu exister.

**Vérification**, après deux minutes de trafic :

```bash
bash ~/autodeploy/apps/loadgen.sh bilan
```

Chaque parcours doit avoir des appels et presque aucun échec. Un parcours à zéro
appel est aussi grave qu'un parcours qui échoue — voir « Avant chaque campagne ».

---

## Étape 7 bis — Dimensionner le consommateur

**Où** : sur le master · **Durée** : 3 minutes (une minute de redémarrage roulant)

```bash
bash ~/autodeploy/apps/consommateur.sh dimensionner --retard 140
```

**Pourquoi** : une faute de coordination n'apparaît que si le consommateur est
taillé pour sa charge, avec peu de marge — comme dans tout système réel. Or
`ts-delivery-service` ne fait presque rien par message :

```
   ce qui arrive dans la file      3,4 messages/s   (25 voyageurs, mesuré)
   ce que 3 répliques absorbent   ~500 messages/s   (6 ms par message)
   marge                             × 150
```

Avec cette marge, une réplique gelée ou un hôte saturé ne changent rien à la
file : les deux autres absorbent tout, le tas reste à zéro, et le symptôme
central de l'étude n'existe pas. Deux réglages, **posés une fois, avant la
référence saine, et jamais changés ensuite** :

| réglage | ce que c'est | effet |
|---|---|---|
| temps de service `--retard 140` | chaque échange entre une réplique et sa base est retardé de 140 ms (Chaos Mesh, sans durée). Traiter un message coûte ~5 échanges : **≈ 0,7 s par message** | 3 répliques absorbent ~4,3 messages/s ; à 25 voyageurs (3,4/s), la file est occupée à **80 %** |
| `--prefetch 1` (défaut) | le courtier ne confie qu'un message à la fois à chaque réplique, au lieu de 250 d'avance | le tas visible bouge dès le premier message en retard ; une réplique gelée n'en emporte pas 250 |

Comment la valeur est choisie : capacité = répliques ÷ (5 × retard) ; on vise
80 % à la charge de base, donc `retard = 0,8 × 3 ÷ (5 × 3,4) ≈ 0,14 s`. Le
débit de base se lit dans `bilan` (colonne maintenant/s de « commander un
repas », plus la moitié de « réserver un billet »). Le facteur 5 (échanges
par message) est une estimation : la première référence le vérifie —
`process_time_p50` ≈ 0,7 s sur les répliques dans les figures. Si le
générateur ou la charge de base changent, la valeur est à recalculer — et la
référence à refaire.

**Chaos Mesh sert ici de réglage, pas de panne.** C'est un outil qui sait
retarder le trafic réseau ; on lui fait poser un retard *permanent* (sans
durée), présent pendant la référence **et** pendant toutes les pannes — le
modèle le voit comme la normale. La cause `lenteur` (étape 11) est le même
curseur poussé plus loin le temps d'une injection, puis remis à sa valeur.

Pourquoi un retard réseau et pas un sommeil dans la base : un déclencheur SQL
qui dort à chaque insertion a été essayé d'abord. La base n'exécute qu'un
sommeil à la fois, quel que soit le nombre de répliques (mesuré : 1 sommeil
actif en permanence, 1,3 message/s pour 3 répliques à 0,7 s, 570 messages en
attente en cinq minutes). La capacité ne dépendait plus du nombre de
répliques, et une réplique gelée n'aurait rien changé. Le retard réseau
s'applique dans chaque pod, indépendamment des autres.

Ce que ça donne pour les quatre causes, à 25 voyageurs de base :

| cause | occupation attendue *(pas encore mesuré)* |
|---|---|
| charge 25 → 50 voyageurs | 80 % → 160 % : le tas grossit |
| blocage d'une réplique | 80 % → 120 % : le tas grossit |
| lenteur (+300 ms par échange ≈ +1,5 s par message) | 80 % → 250 % : le tas grossit vite |
| hote | faible : le temps par message est de l'attente, pas du CPU — à mesurer |

**Vérification** — trois regards, du plus direct au plus complet :

```bash
bash ~/autodeploy/apps/consommateur.sh etat
```

```
  consommateur : ts-delivery-service (3/3 répliques prêtes)
  temps de service : 140 ms de retard par échange avec la base, ≈ 700 ms par message   (appliqué)
  prefetch : 1
```

Le retard est-il *réellement* appliqué ? Ouvrir une connexion depuis une
réplique vers la base doit prendre au moins 140 ms (mesuré sans retard :
2 ms) :

```bash
P=$(kubectl get pods -n train-ticket -l app=ts-delivery-service -o custom-columns=:metadata.name --no-headers | head -1)
kubectl exec -n train-ticket "$P" -c ts-delivery-service -- bash -c "time (exec 3<>/dev/tcp/tsdb-mysql-leader/3306)" 2>&1 | grep real
```

Puis, après deux minutes à 25 voyageurs (`loadgen.sh scale 25`) :

```bash
bash ~/autodeploy/apps/panne.sh temoin
```

`food_delivery` doit rester à **0 en attente** (1 ou 2, jamais plus), avec
**2 ou 3 non acquittés** — les répliques travaillent et suivent. Si le tas
grossit, le retard est trop grand ; s'il faut plus de 50 voyageurs pour le
faire grossir (cause `charge`), il est trop petit.

Le pilote recopie l'état du consommateur dans chaque compte rendu
(`reglage_consommateur`) : deux campagnes ne se comparent que si elles l'ont
identique. Après la référence, `instances.py runs/<horodatage> delivery`
donne le temps par message réellement mesuré (`process_time_p50`).

---

## Étape 8 — Vérifier que tout est mesurable

**Où** : sur le master · **Durée** : 2 minutes

```bash
bash ~/autodeploy/apps/observability.sh verify
```

Parcourt chaque grandeur dont le graphe a besoin et répond `PRESENT` ou
`ABSENT`.

**Ce que tu dois voir** : tout en `PRESENT`, y compris la dernière ligne sur les
services qui émettent des notes.

---

## Étape 9 — Accéder aux interfaces

**Où** : sur ton PC · **Durée** : immédiat

Les machines de SLICES-RI n'ont pas d'adresse publique. Il faut un tunnel.

⚠️ La cible du tunnel est **l'adresse du nœud**, pas `localhost` — la forme
habituelle échoue ici sans message d'erreur.

Récupère les bonnes adresses :

```bash
ssh master 'bash ~/autodeploy/apps/observability.sh urls'
ssh master 'bash ~/autodeploy/apps/loadgen.sh urls'
```

Puis, en laissant tourner dans un terminal :

```bash
ssh -N -L 16686:<IP_MASTER>:30686 -L 9090:<IP_MASTER>:<PORT_PROM> -L 8089:<IP_MASTER>:30089 master
```

| Interface | Adresse | À quoi ça sert |
|---|---|---|
| Traces | http://localhost:16686 | voir le chemin d'une commande |
| Compteurs | http://localhost:9090 | interroger les mesures |
| Générateur | http://localhost:8089 | changer le nombre de voyageurs |

---

## Étape 10 — Vérifier que les données sortent

**Où** : sur le master · **Durée** : une minute

```bash
Y=$(date -u +%Y); M=$(date -u +%m); J=$(date -u +%d)
kubectl run s3ck --rm -i --restart=Never --quiet --image=minio/mc:latest -n observability \
  --env=MC_HOST_s="https://<CLE>:<SECRET>@s3.slices-be.eu" \
  --command -- mc ls --recursive "s/<BUCKET>/otel-data/year=$Y/month=$M/day=$J/" | tail -5
```

Tu dois voir des fichiers `traces_*.json.gz` et `metrics_*.json.gz` datés
d'aujourd'hui.

---

## Avant chaque campagne — deux minutes qui en sauvent soixante

```bash
ssh master 'bash ~/autodeploy/apps/loadgen.sh bilan'
```

```
   parcours                         appels   échecs   taux   maintenant    échecs     p50
                                     total    total                 /s        /s      ms
   ------------------------------------------------------------------------------------
   01 connexion                        300        0   0.0%        0.10      0.00     120
   10 chercher un train                900       12   1.3%        1.50      0.00     310
   30 réserver un billet               180        2   1.1%        0.80      0.00     650
   40 commander un repas              1800        0   0.0%        3.00      0.00      40

   Tous les parcours passent. La campagne peut être lancée.
```

Deux lectures par parcours. Les **totaux** comptent depuis le dernier « reset »
— le pilote en fait un au départ de chaque campagne, donc ils décrivent la
campagne en cours, pas la nuit d'avant. **Maintenant**, ce sont les dix
dernières secondes : c'est là-dessus que le verdict se prend dès qu'un
parcours tourne. Pendant une campagne, c'est la colonne à regarder ; `p50`
qui grimpe d'un palier à l'autre, c'est l'application qui approche de son
plafond.

**Deux choses sont fatales, et aucune ne se voit ailleurs :**

| | ce que ça produit |
|---|---|
| un parcours qui **échoue** | des taux d'erreur qui n'ont aucun rapport avec une panne injectée |
| un parcours **jamais exécuté** | une file vide, un graphe sans flèche — et pas un seul compteur d'erreur qui bouge |

Une campagne d'une heure a été perdue faute de ce contrôle : le jeton de
connexion avait expiré, tous les parcours s'arrêtaient à leur première ligne.
L'application tournait, les pods étaient `Running`, la collecte écrivait dans le
magasin. Rien ne le montrait — sauf ce tableau.

**Les données de l'application** comptent autant que le trafic. Chaque
réservation ajoute une commande, et pour compter les places vendues le
service des sièges fait charger en mémoire *toutes* les commandes du train à
cette date. Mesuré : à 5 000 commandes sur le même train le même jour,
`ts-order-service` (tas Java de 200 Mo) se fige, le service des sièges
l'attend, la recherche attend le service des sièges en gardant ses 10
connexions à la base — et toute recherche répond `500` après 30 s, même à 1
voyageur, même après redémarrage des services du dessus. Dans `bilan`, la
signature est un `p50` de **30 000** sur « chercher un train ».

Le pilote remet donc les tables de commandes à zéro au départ de chaque
campagne (`donnees.sh purger`, avant la collecte, sans rien redémarrer), et
le compte rendu note l'état des tables (`donnees_au_depart`). À la main :

```bash
ssh master 'bash ~/autodeploy/apps/donnees.sh etat'
ssh master 'bash ~/autodeploy/apps/donnees.sh purger'
```

Si la recherche est à 30 000 (service des commandes déjà étouffé) : purger
**et** redémarrer la chaîne — commandes, sièges, recherche, dans cet ordre.
Jamais le service des commandes seul : ceux qui l'appellent gardent des
connexions vers le pod disparu et la recherche échoue pendant ~2 minutes.

```bash
ssh master 'bash ~/autodeploy/apps/donnees.sh purger --redemarrer'
```

Après un redémarrage, attendre deux minutes et refaire `bilan` avant de
lancer quoi que ce soit. Le pilote, lui, contrôle les parcours **à la minute
2** de chaque campagne et s'arrête si l'un échoue ou ne tourne pas — mieux
vaut perdre deux minutes que soixante.

Et une vérification de deux secondes : les instants du compte rendu viennent
de deux horloges, celle du nœud de contrôle et celle du master. Les deux
doivent être tenues par NTP, sinon les étiquettes ne s'alignent pas sur les
mesures.

```bash
timedatectl show -p NTPSynchronized; ssh master timedatectl show -p NTPSynchronized
```

Les deux doivent répondre `NTPSynchronized=yes`.

---

## Étape 11 — Lancer une campagne de mesure

Une campagne n'est pas une suite de commandes tapées à la main : c'est un
**profil de charge appliqué à des instants exacts**, enregistré au fur et à
mesure. Un seul script s'en charge, **depuis le nœud de contrôle**.

```bash
tmux new -s campagne
./campagne.sh saine-01 --profil "10:15,25:15,10:15,40:15"
```

Le profil se lit « voyageurs:minutes ». Ci-dessus : une heure, quatre paliers.

Le pilote prend en charge **tout le cycle**, y compris les deux bouts de la
collecte :

```
   0. remet les données à zéro      donnees.sh purger     (--sans-purge pour s'en passer)
   1. démarre la collecte           collecte.sh demarrer
   2. pour chaque palier            loadgen.sh scale <n>
        vérifie la charge réelle
        attend la minute prévue
      à la minute 2                 loadgen.sh bilan      (s'arrête si un parcours échoue)
   3. s'il y a une panne            panne.sh injecter … / retirer
        à la minute dite, pour la durée dite
   4. ramène la charge              loadgen.sh scale <premier palier>
   5. calcule la fenêtre            collecte.sh fenetre
   6. arrête la collecte            collecte.sh arreter
   7. écrit le compte rendu         campagnes/saine-01/campagne.yaml
```

Le point 4 compte : sans lui, un étalonnage qui finit à 320 voyageurs
laisserait l'application saturée jusqu'à la campagne suivante.

Tu n'as donc **rien à démarrer ni à arrêter toi-même**. Si la collecte tourne
déjà, le pilote la reprend sans dommage. Si elle est déjà pilotée par ailleurs,
`--sans-collecte` lui dit de ne pas y toucher.

**Sous `tmux`** : la campagne dure des heures, une session SSH qui tombe
emporterait le pilote avec elle.

### Pourquoi un pilote plutôt que des commandes à la main

| | à la main | avec le pilote |
|---|---|---|
| présence | il faut être là à chaque palier | tu lances et tu pars |
| instants | « à peu près quinze minutes » | exacts |
| oubli | un palier sans trace, ou l'inverse | impossible : même geste |

Le deuxième point décide de la qualité des étiquettes. La frontière entre deux
niveaux de charge sert à étiqueter les fenêtres de mesure ; floue de deux
minutes, les fenêtres autour deviennent ambiguës.

### Ce que « confirmé » veut dire

Que Locust réponde « Swarming started » prouve seulement que la requête a été
acceptée. Le pilote **relit le nombre de voyageurs réellement actifs** jusqu'à ce
qu'il corresponde. Un palier qui n'aboutit pas est enregistré comme tel, avec la
valeur observée — la campagne continue, mais elle ne ment pas.

Le compte rendu note **deux instants par palier** : celui de la demande, et
celui où la charge visée est atteinte. Entre les deux la charge monte
progressivement ; ces fenêtres-là sont à écarter au moment d'étiqueter.

Le dossier `campagnes/<nom>/` est à committer : c'est la provenance de tes
données. Il contient le compte rendu et les journaux du master, qui
disparaîtraient avec le cluster.

### Une campagne de panne

Le fil qu'on casse est toujours le même : `ts-food-service` dépose dans
`food_delivery`, les trois répliques de `ts-delivery-service` retirent. Quatre
causes font grossir le tas, chacune pour une raison différente :

| `--panne` | ce qui est fait | avec quoi | ce qu'on s'attend à voir *(pas encore mesuré)* |
|---|---|---|---|
| `charge` | deux fois plus de voyageurs : on dépose plus vite qu'on ne retire | `loadgen.sh scale` | `publish_rate` ↑, `consume_rate` plafonne à 3,75/s, `backlog` ↑ ; tout le reste sain |
| `lenteur` | les 3 répliques attendent 300 ms de plus à chaque échange avec leur base, en plus du réglage de base | Chaos Mesh, retard réseau entre ces pods et `tsdb-mysql` (remplace le réglage le temps de la panne, le repose après) | `process_time_p50` ↑ sur les 3 répliques, cpu normal, hôtes normaux, `backlog` ↑ |
| `hote` | un pod voisin, hors du graphe, occupe tous les cœurs de l'hôte d'UNE réplique | Chaos Mesh, stress CPU sur ce voisin | `cpu_pressure` ↑ sur cet hôte seul ; la réplique qui y vit ralentit, les 2 autres vont bien ; les autres services de cet hôte aussi |
| `blocage` | une seule réplique est gelée, sans être tuée | `SIGSTOP` sur son processus Java, envoyé depuis la machine par le démon Chaos Mesh | `consume_rate` 0 et cpu ≈ 0 sur elle, mémoire inchangée ; les 2 autres absorbent ; hôte normal ; après ~2 min le courtier ne compte plus que 2 consommateurs |

Une campagne de panne est un profil de charge ordinaire sur lequel une
injection est posée à une minute donnée :

```bash
tmux new -s campagne
./campagne.sh lenteur-01 --profil "25:30" --panne lenteur --a 5 --duree 20
```

```
   minute   0        5                        25       30
            |--------|========================|--------|
            25 voyageurs   panne « lenteur »   retour   fin
```

| option | rôle | défaut |
|---|---|---|
| `--panne <cause>` | `charge`, `lenteur`, `hote`, `blocage` | — |
| `--a <min[,min…]>` | minute(s) de début, depuis le premier palier ; `--a 5,35,65` répète | — |
| `--duree <min>` | durée de chaque injection | — |
| `--intensite <n>` | voyageurs (`charge`) · ms de retard en plus (`lenteur`) · cœurs réclamés par le voisin (`hote`) | 2 × la charge · 300 · la moitié de l'hôte |
| `--cible <x>` | nœud (`hote`) ou pod (`blocage`) | le moins chargé des hôtes portant une réplique · la première réplique |

Le pilote décide **quand** ; `apps/panne.sh`, sur le master, décide **comment**
et consigne **qui** a été touché. Le compte rendu reçoit en plus :

```
   panne:                  cause, intensité, cible, minutes de début, durée
   pannes_mesurees:        le registre de panne.sh — qui, quand, avec quoi
   # Témoins               file, consommateurs, charge des répliques et des
                           hôtes : juste avant, au milieu, une minute après
```

**Chaque injection expire d'elle-même** sur le master : Chaos Mesh lève la
sienne à l'échéance (et pour `lenteur`, un minuteur repose ensuite le réglage
de base), la levée du gel est programmée dans le démon Chaos Mesh du nœud, le
retour de charge par un minuteur. Un pilote qui meurt ne laisse pas la panne
derrière lui. Et `Ctrl-C` ne jette rien : l'injection est retirée, la collecte
close, le compte rendu écrit avec ce qui a eu lieu.

Avant toute campagne — saine comprise — le pilote refuse de partir si une
panne est encore en place. Pour voir et nettoyer à la main :

```bash
ssh master 'bash ~/autodeploy/apps/panne.sh etat'
ssh master 'bash ~/autodeploy/apps/panne.sh retirer'
```

### Dans quel ordre

1. **La référence saine**, avec le consommateur dimensionné (étape 7 bis) et
   une charge qui reste sous les 80 % — donc jamais plus de 25 voyageurs :

   ```bash
   ./campagne.sh saine-04 --profil "10:15,25:30,20:15"
   ```

   Puis l'étape 12 avec `export.scaler: write`, et la lecture de la file :

   ```bash
   cd graphe_en && ./.venv/bin/python queues.py runs/<horodatage>
   ```

   Attendu : `publish_rate` ≈ 3,4/s à 25 voyageurs, `backlog` 0 partout, 3
   consommateurs. Et le temps par message des répliques, qui ne se lit pas
   sur la figure (elle colore les instances par CPU) mais par :

   ```bash
   ./.venv/bin/python instances.py runs/<horodatage> delivery
   ```

   Attendu : `process_time_p50` ≈ 700 ms sur les trois répliques à 25
   voyageurs (mesuré sur saine-07 : 706 ms, soit 5 échanges ; et 846 ms à 10
   voyageurs — un échange de plus, la réserve de connexions vérifiant une
   connexion restée inactive plus d'une demi-seconde). Si le tas grossit
   déjà, le temps de service est trop grand.

2. **Un essai court par cause**, figures à l'appui, avant de dépenser des
   heures : on vérifie que la trace attendue est visible.

   ```bash
   ./campagne.sh essai-blocage --profil "25:12" --panne blocage --a 3 --duree 5
   ```

3. **Les campagnes** : 5 min sain, 20 min panne, 5 min retour, trois fois,
   dans l'ordre `charge`, `blocage`, `lenteur`, `hote` — du plus simple au plus
   délicat.

   ```bash
   ./campagne.sh charge-01 --profil "25:90" --panne charge --a 5,35,65 --duree 20 --intensite 50
   ```

4. **La sensibilité au réglage**, après les campagnes principales : les
   mêmes pannes à deux autres taux d'occupation, en ne changeant *que* le
   retard — ~90 ms pour 50 %, ~165 ms pour 95 % — chacune avec sa propre
   référence saine. Si les conclusions tiennent aux trois niveaux, elles ne
   tiennent pas à la valeur 80 %. C'est la réponse à « vous avez réglé la
   plateforme pour trouver de bons résultats ».

   ```bash
   ssh master 'bash ~/autodeploy/apps/consommateur.sh dimensionner --retard 90'
   ./campagne.sh saine-50pct --profil "10:15,25:30,20:15"
   ```

L'intensité est un réglage d'expérience, pas une constante : celle qui produit
la trace attendue est à lire dans les figures de l'essai, puis à figer dans le
nom et le compte rendu de la campagne. Ce qui ne se fait pas : régler les
seuils du modèle sur les campagnes qui servent à l'évaluer, ou retirer une
cause qui ne laisse pas de trace — celle-là se rapporte comme un résultat.

---

## Étape 12 — Construire le graphe et les figures

**Où** : sur le nœud de contrôle · **Durée** : quelques minutes

La première fois seulement, créer le fichier de réglages et l'environnement :

```bash
cd graphe_en
cp config.example.yaml config.yaml && chmod 600 config.yaml
python3 -m venv .venv
```

Laisse `access_key` et `secret_key` vides dans `config.yaml` : ils sont lus dans
`.env.secrets`, qui n'a pas à être recopié.

Ensuite, à chaque campagne, reporter la plage exploitable — **rien d'autre ne
change**. Le pilote l'affiche à la fin, et elle est écrite dans le compte
rendu, pour quand le terminal n'est plus là :

```bash
grep -A3 '^plage_exploitable' campagnes/<nom>/campagne.yaml
```

```
plage_exploitable:
  date: 2026-09-10
  from: "18:24:00"
  to:   "19:20:00"
```

À recopier dans `graphe_en/config.yaml` :

```yaml
range:
  date:       2026-09-10
  from:       "18:24:00"
  to:         "19:20:00"
```

(`collecte.sh fenetre` ne peut plus répondre une fois la collecte arrêtée : le
compte rendu est la seule source après coup.)

```bash
set -a; . ../.env.secrets; set +a
./.venv/bin/python run.py
```

Le premier lancement installe torch et le reste **dans le venv uniquement**. Sur
un interpréteur système le script refuse et affiche la commande à taper :
installer des paquets dans le Python de la machine casserait ses propres outils.

**Ce que tu obtiens** :

```
   runs/<horodatage>/
       run.log                 tout ce que le terminal a affiché
       raw/                    les archives rapatriées, et leur provenance
       graph/  manifest.json   réglages, provenance, dimensions
               window_*.json   un cliché par fenêtre
               graph.pt        les tenseurs PyTorch Geometric
       figures/                deux vues SVG par fenêtre
```

Pour refaire les figures sans retélécharger :

```bash
./.venv/bin/python run.py --render-only runs/<horodatage>
```

Puis **lire, et garder la lecture avec la campagne** — `runs/` ne se versionne
pas, mais ces deux tableaux sont ce qu'un rapport cite :

```bash
./.venv/bin/python lecture.py runs/<horodatage> <nom>
```

Écrit `campagnes/<nom>/lecture.txt` : le run d'origine, la plage, puis la file
(`queues.py`) et chaque réplique du consommateur (`instances.py … delivery`).
Le dossier `campagnes/<nom>/` se committe ensuite en entier — conditions et
lecture ensemble.

### Trois réglages à ne pas toucher entre deux campagnes

| | |
|---|---|
| `windows.width_s` et `step_s` | changer la largeur rendrait la référence et les pannes incomparables |
| `export.scaler` | `write` sur la campagne saine, `apply` sur toutes les autres |

Laisser `write` pendant une panne ferait apprendre au modèle que la panne **est**
la normale : elle définirait sa propre moyenne, et l'anomalie disparaîtrait
d'elle-même.

---

## Détruire

**Où** : sur ton PC

```bash
cd ~/autodeploy_k8s
./destroy.sh
```

Les données sont déjà dans le magasin d'objets, l'export est continu. Rien à
sauvegarder au préalable.

---

## Aide-mémoire — les commandes du quotidien

```bash
# état général
ssh master 'kubectl get pods -A --no-headers | awk "{print \$1}" | sort | uniq -c'

# inventaire de ce qui est mesurable
ssh master 'bash ~/autodeploy/apps/observability.sh verify'

# faire monter la charge, et noter l'instant
ssh master 'bash ~/autodeploy/apps/loadgen.sh scale 25'

# les parcours passent-ils, maintenant ?
ssh master 'bash ~/autodeploy/apps/loadgen.sh bilan'

# une panne est-elle en place ? la lever ; relever la file et les répliques
ssh master 'bash ~/autodeploy/apps/panne.sh etat'
ssh master 'bash ~/autodeploy/apps/panne.sh retirer'
ssh master 'bash ~/autodeploy/apps/panne.sh temoin'

# état des files
ssh master 'R=$(kubectl get pods -n train-ticket --no-headers | grep -i rabbit | head -1 | cut -d" " -f1); \
            kubectl exec -n train-ticket $R -- rabbitmqctl list_queues name messages consumers'

# après avoir modifié un réglage ou la liste des compteurs
ssh master 'set -a; . ~/autodeploy/.env.secrets; set +a; \
            export OBS_DEDICATED_NODE=workers6; \
            bash ~/autodeploy/apps/observability.sh tune'
```

---

## Ce que fait chaque script

| Script | Rôle |
|---|---|
| `deploy.sh` | machines, Kubernetes, application |
| `apps/observability.sh` | toute la chaîne de mesure · `install` `verify` `isolate` `tune` `urls` |
| `apps/instrument.sh` | attacher l'observateur aux services · `install --all` |
| `apps/loadgen.sh` | le trafic · `install` `scale <n>` `bilan` `reset` `isolate` |
| `apps/collecte.sh` | l'enregistrement · `demarrer` `arreter` `fenetre` `etat` |
| `apps/consommateur.sh` | tailler le consommateur pour sa charge · `dimensionner` `etat` `retirer` |
| `apps/donnees.sh` | remettre les tables de commandes à zéro · `etat` `purger [--redemarrer]` `redemarrer` |
| `apps/chaos.sh` | l'injecteur de pannes · `install` `status` `isolate` |
| `apps/panne.sh` | les quatre pannes · `verifier` `injecter` `retirer` `etat` `temoin` |
| `campagne.sh` | une campagne entière depuis le nœud de contrôle — charge, panne, collecte, compte rendu |
| `graphe_en/run.py` | le graphe d'une plage : rapatrie, découpe, exporte, dessine |
| `graphe_en/queues.py` · `instances.py` · `lecture.py` | lire la file, lire les répliques, garder les deux avec la campagne |
| `apps/metrics-keep.txt` | la liste des compteurs sauvegardés, un par ligne |
| `destroy.sh` | tout libérer |


---

## Entre deux expériences — arrêter la collecte sans casser la grappe

Recréer une grappe coûte 45 à 60 minutes. Laisser la collecte tourner en continu
remplit le magasin de données que personne ne regardera — environ 107 Mo par
heure une fois compressées. On garde donc la grappe debout, et on n'enregistre
que pendant les fenêtres qui comptent.

**Pendant une campagne, tu n'as pas à t'en occuper** : le pilote de l'étape 11
allume et éteint la collecte lui-même. Les commandes ci-dessous servent entre
deux campagnes, ou pour vérifier.

```bash
ssh master
bash ~/autodeploy/apps/collecte.sh etat        # où en est-on
bash ~/autodeploy/apps/collecte.sh arreter     # plus rien n'est enregistré
bash ~/autodeploy/apps/collecte.sh demarrer    # on réenregistre
bash ~/autodeploy/apps/collecte.sh fenetre     # quelle plage rapatrier
```

### Ce qui s'arrête et ce qui continue

| | pendant l'arrêt |
|---|---|
| passerelle vers le magasin | **arrêtée** — rien n'arrive dans MinIO |
| les 56 microservices | continuent |
| l'instrumentation Java | reste attachée |
| Prometheus et Jaeger | continuent, en local |
| relevés de machines et collecteurs locaux | continuent |

Les traces produites pendant l'arrêt sont perdues, et c'est le but.

**Pourquoi éteindre la passerelle plutôt que l'instrumentation.** Détacher
l'agent Java demanderait de redémarrer les 46 services : plusieurs minutes, et
un régime transitoire à chaque bascule. On mesurerait une montée en charge à
froid au lieu du régime établi. La passerelle s'éteint et se rallume en
quelques secondes sans toucher à l'application.

`--avec-charge` arrête aussi le générateur de trafic. À réserver aux pauses
longues : laisser la charge tourner garde l'application en régime établi, ce qui
rend la reprise immédiatement exploitable.

### `fenetre` — la commande qui évite l'erreur coûteuse

Elle rend la plage à recopier dans `graphe_en/config.yaml`, **en heure UTC**,
celle du magasin et non celle de ton poste.

```
  [collecte] Passerelle démarrée à  01:18:23 UTC
  [collecte] Charge démarrée à      01:30:03 UTC
  [collecte] Origine retenue        01:30:03 UTC  (démarrage du générateur de charge)
  [collecte] Il est 02:05:49 UTC — 35 minutes exploitables

    range:
      date:       2026-09-10
      from:       "01:32"
      to:         "02:03"
```

Elle retient **la plus tardive** des deux dates. Avant le démarrage de la
charge, l'application ne fait que bavarder — annuaire, sondes de vie — et le
graphe n'a aucune flèche. Rapatrier cette période donne un résultat d'apparence
valide mais vide, qui se présente comme une panne du constructeur :
`0 publishes, 0 consumes` alors que tout fonctionne.

Une marge de deux minutes est écartée de chaque côté : montée en charge au
début, latence d'écriture à la fin — le collecteur regroupe les mesures par lots
de 30 secondes.

Après une reprise, la commande signale que le magasin contient aussi des mesures
antérieures, séparées par un blanc, et s'arrête au bord de ce blanc. Une fenêtre
qui l'enjamberait mélangerait deux régimes séparés par un vide, et le découpeur
y verrait une chute de trafic qui n'a pas eu lieu.
