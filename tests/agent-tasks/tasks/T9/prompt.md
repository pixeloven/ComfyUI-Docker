The ComfyUI instance your tools are connected to has a saved workflow, `t9-portrait.json`, among its user's workflows: the ones its editor opens from the workflows sidebar. It renders a 512×768 portrait in 20 steps, which is too slow on this instance's CPU.

Change that saved workflow so that it renders at 256×384 (the same portrait shape) with 4 sampling steps, and saves its images with the filename prefix `t9_`. Keep everything else in it as it is. Save it back to the instance under the same name, in the format it is in now, so that the editor opens it with your changes.

Then run the changed workflow once, and wait until it has finished. Report the filename of the saved image.
