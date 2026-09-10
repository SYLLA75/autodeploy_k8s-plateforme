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
grep '^APPS=' ~/autodeploy_k8s/.env
```

**`.env.secrets`** — les identifiants du magasin d'objets. Ce fichier est ignoré
par git, il ne doit **jamais** être committé.

```bash
cat ~/autodeploy_k8s/.env.secrets
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
scp ~/autodeploy_k8s/.env.secrets master:/home/ubuntu/autodeploy/.env.secrets
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

Après chaque `git pull` sur le nœud de contrôle, rafraîchis-la :

```bash
./deploy.sh --push-scripts
```

Ça ne déploie rien, ne redémarre rien, ne touche pas aux applications. Ça recopie
les fichiers de `apps/` sur le master, et c'est tout — quelques secondes.

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

## Étape 7 — Le générateur de trafic

**Où** : sur le master · **Durée** : 2 minutes

```bash
bash ~/autodeploy/apps/loadgen.sh install
bash ~/autodeploy/apps/loadgen.sh isolate workers6
```

Sans trafic, l'application ne fait rien : les services ne s'appellent pas et les
files restent vides.

**Vérification** : la page de pilotage doit répondre, et le taux d'échec être à
zéro. Voir l'étape 9 pour l'accès.

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
| `apps/loadgen.sh` | le trafic · `install` `scale <n>` `isolate` |
| `apps/metrics-keep.txt` | la liste des compteurs sauvegardés, un par ligne |
| `destroy.sh` | tout libérer |


---

## Entre deux expériences — arrêter la collecte sans casser la grappe

Recréer une grappe coûte 45 à 60 minutes. Laisser la collecte tourner en continu
remplit le magasin de données que personne ne regardera — environ 107 Mo par
heure une fois compressées. On garde donc la grappe debout, et on n'enregistre
que pendant les fenêtres qui comptent.

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
