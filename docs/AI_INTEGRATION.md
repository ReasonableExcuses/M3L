# Connecting an LLM to M3L v0.3

M3L is provider-neutral. Keep provider-specific inference in an orchestrator and use the local service for deterministic validation, export, patching, and (when Blender is installed) rendering.

## Recommended control loop

1. Fetch `GET /v1/schema` and `GET /v1/capabilities` to discover version and available backends.
2. Give the LLM a design brief, explicit acceptance criteria and the relevant schema. Request only M3L source.
3. Call `POST /v1/validate`; pass structured diagnostics to the model for minimal repairs, with a bounded retry count.
4. Call `POST /v1/judge` to check deterministic readiness and mesh topology.
5. Call `POST /v1/compile` with `format: "glb"`, persist the decoded artifact, and store the scene IR and hash.
6. When Blender is installed, call `POST /v1/render` and decode `png_base64`. Send the image and original brief to a **separate** vision/task judge.
7. Convert the review into named defects and narrowly scoped `/v1/patch` edits or request an updated source. Recompile and rerender with a fixed iteration budget.
8. Optionally call `/v1/export/step` when the downstream application needs editable B-rep solids instead of display meshes.
9. Accept only when required hard constraints and task-specific visual criteria pass. Persist all revisions and reasons.

For an edited candidate, compare its compiled meaning to the accepted source before promotion:

```bash
python -m m3l.cli diff accepted.m3l candidate.m3l --out candidate.diff.json
```

The equivalent `POST /v1/diff` request accepts `before_source` and `after_source`. It returns stable asset revisions and named semantic paths; large geometry payloads are represented by hashes to keep reports compact. A source formatting change alone does not alter the asset revision.

`POST /v1/patch` can include `expected_revision` from the source scene's `provenance.asset_revision`. If the source is stale, the API returns `409 stale_revision`. A successful patch returns `base_revision`, `candidate_revision`, and a semantic diff; callers can inspect the candidate and decide whether to promote it.

## HTTP examples

```bash
curl -s http://127.0.0.1:8765/health
curl -s http://127.0.0.1:8765/v1/capabilities
curl -s http://127.0.0.1:8765/v1/schema

curl -s http://127.0.0.1:8765/v1/validate \
  -H 'Content-Type: application/json' \
  -d '{"source":"scene \"tiny\" { box b { size = [1, 1, 1] } }"}'
```

Render request:

```bash
curl -s http://127.0.0.1:8765/v1/render \
  -H 'Content-Type: application/json' \
  -d '{"source":"scene \"tiny\" { box b { size = [1, 1, 1] } }", "resolution":512}'
```

`/v1/render` returns a `503` `BLENDER_UNAVAILABLE` response if it cannot locate Blender. The CLI supports `M3L_BLENDER` or `--blender /path/to/blender` as well. A service response with a valid scene is not the same as an aesthetically accepted render.

## Provider-neutral Python skeleton

The model call is intentionally left to the host application. This example covers deterministic compile repair; add renderer/vision review as the next stage rather than treating successful compilation as final acceptance.

```python
import base64
import json
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:8765"


def get(path: str) -> dict:
    with urllib.request.urlopen(API + path, timeout=10) as response:
        return json.load(response)


def post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        API + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)


def build_scene(goal: str, model_call, max_repairs: int = 4):
    schema = get("/v1/schema")
    capabilities = get("/v1/capabilities")
    prompt = (
        "Create a 3D scene in M3L v0.3. Return only source. "
        "Use named parts and explicit requirements.\n"
        f"Goal: {goal}\nSchema: {json.dumps(schema)}\n"
        f"Capabilities: {json.dumps(capabilities)}"
    )
    source = model_call(prompt)
    history = []

    for round_index in range(max_repairs + 1):
        result = post("/v1/validate", {"source": source})
        history.append({"round": round_index, "valid": result["valid"],
                        "diagnostics": result["diagnostics"]})
        if result["valid"]:
            judged = post("/v1/judge", {"source": source})
            if not judged.get("ready_for_visual_review", False):
                source = model_call(
                    "Repair this M3L v0.3 source without weakening requirements.\n"
                    f"Source:\n{source}\nJudge findings:\n{json.dumps(judged)}"
                )
                continue
            compiled = post("/v1/compile", {"source": source, "format": "glb"})
            artifact = base64.b64decode(compiled["glb_base64"], validate=True)
            Path("scene.glb").write_bytes(artifact)
            return {"source": source, "scene": compiled.get("scene"),
                    "glb_path": "scene.glb", "history": history,
                    "requires_visual_review": True}
        source = model_call(
            "Make the smallest safe repair. Preserve task requirements. Return the full source.\n"
            f"Goal: {goal}\nSource:\n{source}\n"
            f"Diagnostics:\n{json.dumps(result['diagnostics'], indent=2)}"
        )
    return {"accepted": False, "source": source, "history": history}
```

In production, add provider timeouts, cancellation, retry policy, token/cost budgets, output extraction rules, artifact persistence, render-process isolation, and a separate visual judge. A vision review should return structured findings and confidence, not just an ungrounded score.

## Security

The API has no authentication and is intended for loopback use. An external LLM cannot call a local port directly; a local orchestrator must bridge it. Before exposing M3L remotely, add authentication, rate limits, request-size limits, render timeouts, process isolation, geometry budgets and artifact access controls. Do not pass LLM-generated scripts to the Blender runtime; use the fixed bundled renderer script.
