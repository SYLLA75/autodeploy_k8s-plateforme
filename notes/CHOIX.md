# Choix d'implémentation

Décisions non évidentes, notées pour que quelqu'un qui reprend le travail
n'ait pas à les redécouvrir par l'échec.

Quelques décisions non évidentes, documentées pour la reproductibilité :

**Pourquoi deux versions de Helm sur le master ?**
Le chart `opentelemetry-demo` (≥ 0.41) réclame **Helm 4**. Or les charts
embarqués de Train Ticket (`nacos`, `rabbitmq`) sont encore au format
`apiVersion: v1`, que Helm 4 ne sait plus lire. Le script installe donc `helm`
(v4, pour otel-demo) **et** `helm3` (pour train-ticket). Les scripts amont de
train-ticket appelant `helm` en dur, un lien symbolique `helm → helm3` est placé
en tête de `PATH` le temps de leur exécution.

**Pourquoi une `StorageClass` par défaut ?**
Kubespray n'en installe aucune. Train Ticket en a impérativement besoin (les
charts MySQL et Nacos réclament des PVC) ; sans elle, les volumes restent en
`Pending` et le déploiement se bloque sur `kubectl rollout status`. Le script
active donc l'addon `local_path_provisioner` de Kubespray, avec un filet de
sécurité qui installe `local-path-provisioner` à la main si aucune classe par
défaut n'est détectée (cas d'un cluster préexistant).

**Pourquoi une attente active plutôt qu'un `sleep` ?**
La version initiale attendait 20 secondes après la création des VMs. C'est la
cause la plus fréquente d'échec de Kubespray : selon la charge du site, `sshd`
peut mettre plusieurs minutes à répondre. Le script attend désormais que chaque
VM réponde réellement, avec un délai maximal.

**Pourquoi les scripts d'application tournent-ils sur le master ?**
Pour rester rejouables sans le poste local, pour éviter d'exposer l'API
Kubernetes sur Internet, et pour que `helm`/`kubectl` n'aient à être installés
qu'à un seul endroit.

**Ré-entrance.** `deploy.sh` peut être relancé après un échec : il réutilise les
VMs existantes (sur confirmation), le clone Kubespray, et ne réinstalle pas une
application déjà présente (sauf `--force-reinstall`).

**Pour une expérience scientifique reproductible**, fige les trois versions :
`KUBESPRAY_REF`, `OTEL_CHART_VERSION` et `TT_REF`.

---
