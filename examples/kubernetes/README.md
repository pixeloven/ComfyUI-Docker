# ComfyUI on Kubernetes

A minimal, generic example: one Deployment, one PersistentVolumeClaim per data
volume, and a ClusterIP Service. It uses the `core:cpu` image so it runs on any
cluster. There is no ingress, no namespace, and no storage class. Those depend on
your cluster, so you add them.

| File | What it is |
|------|------------|
| `deployment.yaml` | ComfyUI, running as UID/GID `1000`, with a readiness probe on `/system_stats` |
| `pvc.yaml` | Seven `ReadWriteOnce` claims, one per volume root under `/app` |
| `service.yaml` | `comfyui:8188` inside the cluster |

## Deploy

```bash
kubectl apply -f examples/kubernetes/
kubectl rollout status deployment/comfyui
kubectl port-forward service/comfyui 8188:8188
```

Then open **http://localhost:8188**.

## How the Container Starts Here

The pod sets `runAsUser`, so the container starts **as non-root**, and the
entrypoint takes its non-root path. It skips `PUID`/`PGID`, `useradd`, `chown` and
`gosu`, and runs ComfyUI directly as UID 1000. Setting `PUID` or `PGID` here does
nothing.

That path never `chown`s anything, so **`fsGroup` is what makes the volumes
writable**. The kubelet makes each PVC group-owned by GID 1000 and group-writable
before the container starts. Without `fsGroup`, a freshly provisioned volume is
usually owned by root, and ComfyUI fails to write models, output or its database.
`fsGroupChangePolicy: OnRootMismatch` limits that to the volume root, so a large
model store isn't relabelled on every start.

Any UID works. If you change `runAsUser`, change `runAsGroup` and `fsGroup` with
it. The root filesystem has to stay writable (`readOnlyRootFilesystem: false`),
because the entrypoint adds an `/etc/passwd` entry for a UID the image doesn't
know, and the Manager installs custom-node dependencies into the venv.

The [Runtime Contract](../../docs/user-guides/runtime-contract.md) describes both
startup paths, every environment variable, and the volume paths.

## Adapting It

- **Pin the image.** `cpu-latest` moves with every merge to `main`. Use a release
  tag and a digest:
  `ghcr.io/pixeloven/comfyui/core:cpu-X.Y.Z@sha256:<digest>`. Each release lists
  its digests in `IMAGE-DIGESTS.txt` (see [`VERSIONING.md`](../../VERSIONING.md)).
- **NVIDIA GPU.** Use a `cuda` image (`core:cuda-*` or `complete:cuda-*`), add
  `nvidia.com/gpu: 1` to `resources.limits`, and raise the memory limit to suit
  your models.
- **Storage.** Set `storageClassName` and the sizes for your cluster. Models need
  the most room by far.
- **Port.** To move it, change `COMFY_PORT`, `containerPort`, and the Service
  `port` together.
- **Extra model paths.** Mount an `extra_model_paths.yaml` (for example from a
  ConfigMap) at `/app/extra_model_paths.yaml`, and ComfyUI loads it.
- **Exposure.** Add whatever your cluster uses (an Ingress, a Gateway route, or a
  LoadBalancer) in front of the `comfyui` Service.

## Validation

`make validate` checks these manifests against the Kubernetes schemas with
[kubeconform](https://github.com/yannh/kubeconform), run through Docker, and CI runs
the same check.
