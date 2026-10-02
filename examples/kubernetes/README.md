# ComfyUI on Kubernetes

A minimal, generic example: one Deployment, one PersistentVolumeClaim per data
volume, and a ClusterIP Service, plus an opt-in MCP sidecar for agents in
`with-mcp/`. It uses the `core:cpu` image so it runs on any cluster. There is no ingress, no namespace, and no storage class. Those depend on
your cluster, so you add them.

| File | What it is |
|------|------------|
| `deployment.yaml` | ComfyUI, running as UID/GID `1000`, with a readiness probe on `/system_stats` |
| `pvc.yaml` | Seven `ReadWriteOnce` claims, one per volume root under `/app` |
| `service.yaml` | `comfyui:8188` inside the cluster |
| `with-mcp/` | **Opt-in.** The MCP sidecar: a patch that adds it to the Deployment, and a placeholder Secret for its token. `kubectl apply -f examples/kubernetes/` doesn't apply it |

## Deploy

```bash
kubectl apply -f examples/kubernetes/
kubectl rollout status deployment/comfyui
kubectl port-forward service/comfyui 8188:8188
```

Then open **http://localhost:8188**.

## Adding the MCP Sidecar (Opt-In)

The deploy above runs ComfyUI alone. To let agents drive it over MCP, add the
[`mcp` image](../../services/comfyrelay/README.md) as a second container in the
same pod: an MCP server for agents, one per ComfyUI. It reaches ComfyUI over the
pod's loopback (`COMFYUI_URL=http://127.0.0.1:8188`), so nothing extra is exposed
for it, and it serves agents on port 9000 at `/mcp`, behind a token. It installs
and restarts nothing. Skip this section if you don't use an MCP client.

1. **Create its token**, at least 32 characters, as the `comfyui-mcp` Secret:

   ```bash
   kubectl create secret generic comfyui-mcp \
     --from-literal=COMFYUI_MCP_HTTP_TOKEN="$(openssl rand -hex 32)"
   ```

   `with-mcp/mcp-secret.yaml` shows the same Secret as a manifest. Its value is a
   placeholder, deliberately too short: replace it before applying that file
   (and don't commit the real one), or the sidecar refuses to start.

2. **Add the container** to the Deployment, and wait for the pod to restart:

   ```bash
   kubectl patch deployment comfyui \
     --patch-file examples/kubernetes/with-mcp/mcp-sidecar.patch.yaml
   kubectl rollout status deployment/comfyui
   ```

   Re-applying `examples/kubernetes/` later keeps the sidecar. To remove it,
   delete the `mcp` container with `kubectl edit deployment comfyui`, or delete
   and re-apply the Deployment.

3. **Reach it from your machine.** The port-forward runs in the foreground, so
   leave it running and use another terminal for the client:

   ```bash
   kubectl port-forward deployment/comfyui 9000:9000
   ```

   Then, in another terminal, point the client at it with the token:

   ```bash
   claude mcp add --transport http comfyui http://127.0.0.1:9000/mcp \
     --header "Authorization: Bearer $(kubectl get secret comfyui-mcp -o jsonpath='{.data.COMFYUI_MCP_HTTP_TOKEN}' | base64 -d)"
   ```

The sidecar runs under the pod's UID with a read-only root filesystem, and its
memory limit is 256Mi, which fits the default large-request limit with up to
three clients that upload large files. Pin its image the same way as ComfyUI's
(the patch has the placeholder). See the
[runtime contract](../../docs/user-guides/runtime-contract.md#the-mcp-image) for
what it promises.

## How the Container Starts Here

The pod sets `runAsUser`, so the container starts **as non-root**, and the
entrypoint takes its non-root path. It skips `PUID`/`PGID`, `useradd`, `chown` and
`gosu`, and runs ComfyUI directly as UID 1000. Setting `PUID` or `PGID` here does
nothing.

That path never `chown`s anything, so **`fsGroup` is what makes the volumes
writable**. The kubelet makes each PVC group-owned by GID 1000 and group-writable
before the container starts. Without `fsGroup`, a freshly provisioned volume is
usually owned by root, and ComfyUI fails to write models, output or its database.

`fsGroupChangePolicy: OnRootMismatch` makes the kubelet check the volume root first.
If the root already has the right group and permissions, the kubelet leaves the
volume alone. If it doesn't, for example on the first mount or after `fsGroup`
changes, the kubelet changes **every file in the volume**, which can take a long time
on a large model store. The default policy (`Always`) does that on every mount.

Any UID works. If you change `runAsUser`, change `runAsGroup` and `fsGroup` with
it. The root filesystem has to stay writable (`readOnlyRootFilesystem: false`):
startup relies on it for a UID the image doesn't know, and the Manager installs
custom-node dependencies into the venv.

## What Is Lost on Restart

Only the seven volumes persist. Two things live in the container's writable layer
instead, and are lost on every container restart and every reschedule:

- the Python packages the Manager installs with pip for custom nodes. The nodes
  stay on `/app/custom_nodes`, but their dependencies don't.
- the caches under `/app/.cache`.

This is a known defect,
[#115](https://github.com/pixeloven/ComfyUI-Docker/issues/115).

The Deployment makes that storage explicit:

- **An `ephemeral-storage` request and limit** on the container. The writable layer
  counts against them, so the scheduler places the pod on a node with room for
  installed dependencies. A pod that outgrows the limit is evicted instead of
  filling the node's disk.
- **An `emptyDir` at `/app/.cache`**, with a `sizeLimit`. An `emptyDir` lasts as
  long as the pod does, so the cache survives a container restart (an OOM kill,
  for example), although not a reschedule. Everything under `/app/.cache` can be
  rebuilt, so starting it empty is safe. Drop the `emptyDir` if you'd rather keep
  the pod spec smaller. The cache then lives in the writable layer, under the
  container's limit.

The [Runtime Contract](../../docs/user-guides/runtime-contract.md) describes both
startup paths, every environment variable, and the volume paths.

## Adapting It

- **Pin the image.** `cpu-latest` moves with every merge to `main`. Use a release
  tag and a digest:
  `ghcr.io/pixeloven/comfyui/core:cpu-X.Y.Z@sha256:<digest>`. Each release lists
  its digests in `IMAGE-DIGESTS.txt` (see [`VERSIONING.md`](../../VERSIONING.md)).
- **NVIDIA GPU.** Use a `cuda` image (`core:cuda-*` or `complete:cuda-*`), add
  `nvidia.com/gpu: 1` to `resources.limits`, and raise the memory limit to suit
  your models. Be aware that the CUDA images set `NVIDIA_VISIBLE_DEVICES=all`. On a
  node where the NVIDIA runtime is the default, a pod that requests no GPU can
  still see every GPU on the node.
- **Storage.** Set `storageClassName` and the sizes for your cluster. Models need
  the most room by far.
- **Port.** To move it, change `COMFY_PORT`, `containerPort`, and the Service
  `port` together.
- **Extra model paths.** Mount an `extra_model_paths.yaml` (for example from a
  ConfigMap) at `/app/extra_model_paths.yaml`, and ComfyUI loads it.
- **Exposure.** Add whatever your cluster uses (an Ingress, a Gateway route, or a
  LoadBalancer) in front of the `comfyui` Service.

## Validation

`make validate` checks these manifests against the Kubernetes 1.36.4 schemas with
[kubeconform](https://github.com/yannh/kubeconform), run through Docker and pinned
by digest. The sidecar patch isn't a resource on its own, so it is validated as
the Deployment it makes, merged offline with `kubectl patch --local` (skipped
when `kubectl` isn't installed). CI runs the same checks.
