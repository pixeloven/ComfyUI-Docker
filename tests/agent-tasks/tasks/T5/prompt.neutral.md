Goal: make a copy of an image at exactly twice its width and height, using one of the workflow templates of the ComfyUI instance your tools are connected to.

That instance has no models, and you must not download or install anything. Use your MCP server's tools to find a template for this goal, and choose one that this instance can actually run. Get the template, and run it as it is: if it needs converting to the format your tools run, keep its input image, nodes and settings. Wait until the run has finished, then list what it saved.

Write `results/T5.json` as one JSON object with exactly these keys:

- `template`: the name of the template you ran, as your tools gave it
- `runnable`: whether this instance can run that template, as your tools reported it or as you determined it, as a JSON boolean
- `job_id`: the job id (ComfyUI's prompt id) of the run
- `outputs`: the filenames of the files the run saved to ComfyUI's output directory (type `output`), not temporary previews (type `temp`), as a JSON array of strings
