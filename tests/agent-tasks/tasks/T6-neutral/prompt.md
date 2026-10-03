Answer these questions using what your MCP server can reach: its documentation, or anything else its tools give you. Look each answer up rather than answering from memory, and note where you found it.

- q1: In the ComfyUI workflow JSON schema, version 1.0, what is the exact name of the property of `state` that records the last group id? Spelling and letter case matter.
- q2: Which GET route of the ComfyUI server returns a map of custom node modules and the template workflows associated with them?
- q4: In docs.comfy.org's basic inpainting tutorial, which checkpoint file does the Load Checkpoint node load?

Write your answers to `results/T6-neutral.json` as one JSON object that maps each question id to an object with the `answer` and a `source`: where you found it, in your own words (a tool and what you passed it, a page, a path). Give each answer as the value alone, with no explanation or alternatives: a name as it is spelled, a route as just the path (no HTTP method), a file name as just the name. For example:

```json
{"q1": {"answer": "someName", "source": "..."}, "q2": {"answer": "/route", "source": "..."}, "q4": {"answer": "...", "source": "..."}}
```
