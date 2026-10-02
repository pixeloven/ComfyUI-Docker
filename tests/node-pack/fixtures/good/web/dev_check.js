// The node-pack template test's frontend extension. run.sh edits MARKER and
// checks that ComfyUI serves the edit with no restart.
import { app } from "../../scripts/app.js";

const MARKER = "served-v1";

app.registerExtension({ name: "dev_check.fixture", marker: MARKER });
