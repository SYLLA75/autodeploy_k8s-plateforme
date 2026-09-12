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

Bloquer une réplique n'en a pas besoin : un `SIGSTOP` suffit, les pods de
train-ticket n'ayant pas de sonde de vivacité. Les quatre injections sont
faites par `apps/panne.sh` (étape 11) ; `chaos.sh` installe seulement l'outil.

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

**Vérification**, après deux minutes de trafic :

```bash
bash ~/autodeploy/apps/loadgen.sh bilan
```

Chaque parcours doit avoir des appels et presque aucun échec. Un parcours à zéro
appel est aussi grave qu'un parcours qui échoue — voir « Avant chaque campagne ».

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
   parcours                             appels   échecs     taux
   --------------------------------------------------------------
   01 connexion                            300        0     0.0%
   10 chercher un train                    900       12     1.3%
   20 commander un repas                   180        2     1.1%

   Tous les parcours passent. La campagne peut être lancée.
```

**Deux choses sont fatales, et aucune ne se voit ailleurs :**

| | ce que ça produit |
|---|---|
| un parcours qui **échoue** | des taux d'erreur qui n'ont aucun rapport avec une panne injectée |
| un parcours **jamais exécuté** | une file vide, un graphe sans flèche — et pas un seul compteur d'erreur qui bouge |

Une campagne d'une heure a été perdue faute de ce contrôle : le jeton de
connexion avait expiré, tous les parcours s'arrêtaient à leur première ligne.
L'application tournait, les pods étaient `Running`, la collecte écrivait dans le
magasin. Rien ne le montrait — sauf ce tableau.

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
   1. démarre la collecte           collecte.sh demarrer
   2. pour chaque palier            loadgen.sh scale <n>
        vérifie la charge réelle
        attend la minute prévue
   3. s'il y a une panne            panne.sh injecter … / retirer
        à la minute dite, pour la durée dite
   4. calcule la fenêtre            collecte.sh fenetre
   5. arrête la collecte            collecte.sh arreter
   6. écrit le compte rendu         campagnes/saine-01/campagne.yaml
```

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
| `charge` | plus de voyageurs : on dépose plus vite qu'on ne retire | `loadgen.sh scale` | `publish_rate` ↑, `consume_rate` plafonne, `backlog` ↑ ; tout le reste sain |
| `lenteur` | les 3 répliques attendent 1 s de plus à chaque échange avec leur base | Chaos Mesh, retard réseau entre ces pods et `tsdb-mysql` | `process_time_p50` ↑ sur les 3 répliques, cpu normal, hôtes normaux, `backlog` ↑ |
| `hote` | un pod voisin, hors du graphe, occupe tous les cœurs de l'hôte d'UNE réplique | Chaos Mesh, stress CPU sur ce voisin | `cpu_pressure` ↑ sur cet hôte seul ; la réplique qui y vit ralentit, les 2 autres vont bien ; les autres services de cet hôte aussi |
| `blocage` | une seule réplique est gelée, sans être tuée | `SIGSTOP` sur son processus Java | `consume_rate` 0 et cpu ≈ 0 sur elle, mémoire inchangée ; les 2 autres absorbent ; hôte normal ; après ~2 min le courtier ne compte plus que 2 consommateurs |

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
| `--intensite <n>` | voyageurs (`charge`) · ms de retard (`lenteur`) · cœurs réclamés par le voisin (`hote`) | 4 × la charge · 1000 · la moitié de l'hôte |
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
sienne à l'échéance, la levée du gel est programmée dans le conteneur gelé, le
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

1. **Étalonner** : trouver la charge où les trois répliques saturent. À 0,3
   message par seconde et 6 ms par message, il faudra peut-être beaucoup de
   voyageurs — c'est justement ce qu'on mesure.

   ```bash
   ./campagne.sh etalonnage --profil "10:10,20:10,40:10,80:10,160:10"
   ```

   Puis l'étape 12 sur cette campagne (`export.scaler: apply` — la référence
   reste la campagne saine), et une ligne par fenêtre pour la file :

   ```bash
   cd graphe_en && ./.venv/bin/python queues.py runs/<horodatage>
   ```

   ```
   window  start_utc                 backlog  …  publish_rate  consume_rate  rate_imbalance  consumers
       12  2026-09-12T10:12:00Z            0         0.610         0.610           0.000          3
       31  2026-09-12T10:31:00Z           12         2.400         1.100           1.300          3
   ```

   Le palier où `backlog` se met à grossir — ou `consume_rate` cesse de suivre
   `publish_rate` — est celui où le consommateur sature. Les instants de chaque
   palier sont dans `paliers_mesures` du compte rendu. Si aucun palier ne
   sature, c'est un résultat aussi : la cause `charge` demandera plus que 160
   voyageurs, ou le générateur lui-même plafonne avant.

2. **Un essai court par cause**, figures à l'appui, avant de dépenser des
   heures : on vérifie que la trace attendue est visible.

   ```bash
   ./campagne.sh essai-blocage --profil "25:12" --panne blocage --a 3 --duree 5
   ```

3. **Les campagnes** : 5 min sain, 20 min panne, 5 min retour, trois fois,
   dans l'ordre `charge`, `blocage`, `lenteur`, `hote` — du plus simple au plus
   délicat.

   ```bash
   ./campagne.sh charge-01 --profil "25:90" --panne charge --a 5,35,65 --duree 20
   ```

L'intensité est un réglage d'expérience, pas une constante : celle qui produit
la trace attendue est à lire dans les figures de l'essai, puis à figer dans le
nom et le compte rendu de la campagne.

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
| `apps/loadgen.sh` | le trafic · `install` `scale <n>` `bilan` `isolate` |
| `apps/collecte.sh` | l'enregistrement · `demarrer` `arreter` `fenetre` `etat` |
| `apps/chaos.sh` | l'injecteur de pannes · `install` `status` `isolate` |
| `apps/panne.sh` | les quatre pannes · `verifier` `injecter` `retirer` `etat` `temoin` |
| `campagne.sh` | une campagne entière depuis le nœud de contrôle — charge, panne, collecte, compte rendu |
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
