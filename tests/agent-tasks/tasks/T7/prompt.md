The ComfyUI instance your tools are connected to has one model installed: a Stable Diffusion 1.5 checkpoint. It runs on a CPU, so keep images small and steps few, as below.

1. Start from one of that instance's workflow templates for text to image, and adapt it to that checkpoint. Make it generate the prompt `a red apple on a wooden table` at 256×256 pixels, with 4 sampling steps and seed 1, and save the image with the filename prefix `t7_`. Run it, and wait until it has finished.
2. Then change two things in that same workflow: the seed to 2, and the width to 384 (keep the height at 256). Keep everything else as it was. Run it again, and wait until it has finished.

Report the filenames of both saved images.
