Goal: make a copy of an image at exactly twice its width and height, using one of the workflow templates of the ComfyUI instance your tools are connected to.

That instance has no models, and you must not download or install anything. Use `template_search` to find templates for this goal, and choose one that this instance can actually run. Get it with `template_get`, and run it with `workflow_run` as the template is: convert it to the API format `workflow_run` takes, and keep its input image, nodes and settings. Wait until the run has finished, then list what it saved.

Write `results/T5.json` as one JSON object with exactly these keys:

- `template`: the name of the template you ran, as `template_search` gave it
- `runnable`: what `template_get` reported about whether this instance can run it, as a JSON boolean
- `job_id`: the job id `workflow_run` returned
- `outputs`: the filenames of the files the run saved to ComfyUI's output directory (type `output`), not temporary previews (type `temp`), as a JSON array of strings
