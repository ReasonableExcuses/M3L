# Getting started with M3L

This guide is for the contents of this ZIP. Commands below are intended to run from the extracted `m3l-ai3d` directory.

## 1. Requirements

- Python 3.10 or later.
- No third-party Python packages are required for the base parser, compiler, GLB exporter, tests or local API.
- Optional: CadQuery/OpenCascade for STEP export; VTK + Pillow for diagnostic previews; NumPy + Pillow for procedural texture maps; Blender for an independent production-render path. These are separate optional dependencies.

## 2. Install (recommended virtual environment)

### Windows PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

The editable install makes the `m3l` Python package and its CLI available in that environment. You can also run commands with `python -m m3l.cli ...` from the project directory without an install.

## 3. Validate, judge and compile a sample

```bash
python -m m3l.cli validate examples/robot.m3l
python -m m3l.cli judge examples/robot.m3l --require-camera
python -m m3l.cli compile examples/robot.m3l --out dist/robot.glb --json dist/robot.scene.json
python -m m3l.cli audit-glb dist/robot.glb --out dist/robot.quality.json
python -m m3l.cli build examples/robot.m3l --out dist/robot_bundle --require-camera
python -m m3l.cli verify-bundle dist/robot_bundle
python -m m3l.cli diff examples/robot.m3l examples/stool.m3l
```

The GLB is a portable glTF 2.0 binary asset. Open it in Blender, a glTF viewer, or another compatible 3D application. Existing example exports and STEP files are already present in `dist/` so you can inspect results without rebuilding them.

`m3l build` creates a review bundle with the authored `.m3l` source, compiled scene IR, GLB, structural quality audit, deterministic preflight report, and a `manifest.json` containing SHA-256 hashes and byte lengths for each payload file. The manifest also records the compiler and scene schema versions. Run `m3l verify-bundle` to check the payloads against the manifest after copying or receiving a bundle. The preflight report describes readiness for visual review; it does not judge appearance. Build output is written only after compilation and the GLB structural audit succeed.

`m3l diff` compiles two source files and reports named semantic changes and stable asset revisions. Use it to review a candidate repair before promoting it.

## 4. Run the tests

```bash
python -m unittest discover -s tests -v
```

The included M3L v0.5.0 source tree was verified with **60 tests passing** in this environment. The test suite's CAD round-trip tests use CadQuery/OpenCascade when available; install the optional extra if your environment does not have it:

```bash
python -m pip install -e ".[cad]"
```

Optional dependencies are declared in `pyproject.toml`:

```bash
python -m pip install -e ".[materials]"  # NumPy + Pillow
python -m pip install -e ".[preview]"    # VTK + Pillow
python -m pip install -e ".[cad]"        # CadQuery / OpenCascade
```

## 5. Open the Lamborghini exterior

The main deliverable is:

`dist/lamborghini_revuelto_outer.glb`

To view it in Blender: launch Blender, choose **File → Import → glTF 2.0 (.glb/.gltf)**, select the GLB, and frame the imported model. The included preview is:

`dist/lamborghini_revuelto_v06_color/contact_sheet.png`

The car audit JSON is:

`dist/lamborghini_revuelto_glb_audit.json`

The authored scene text is:

`examples/lamborghini_revuelto_outer.m3l`

**Compatibility limitation:** the included executable compiler is the v0.5.0 core and does not yet contain the v0.6 `loft` primitive used by the car source. The car GLB can be viewed and used as an asset, but the source cannot be rebuilt by the included CLI as-is. A car STEP assembly is not included because a CAD-export validation failure remains unresolved.

## 6. Useful documentation

- `docs/SYSTEM_DESIGN.md` — system architecture and design goals.
- `docs/ARCHITECTURE.md` — compiler / geometry / export architecture.
- `docs/AI_INTEGRATION.md` — connecting an LLM through the local API and source format.
- `docs/QUALITY_BLUEPRINT.md` — quality gates, benchmarks and the visual review roadmap.
- `dist/QUALITY_REPORT.md` and `dist/TEST_REPORT.md` — reports for the v0.5.0 technical study.

## 7. Optional local API

See `docs/ROADMAP_EXECUTION_PLAN.md` for the ordered implementation milestones derived from the AI asset-engine roadmap.

After installing the package, start the API with:

```bash
m3l-api
```

The API binds locally according to its configuration. Read `docs/AI_INTEGRATION.md` for supported endpoints and integration notes. Do not expose a local development service to an untrusted network without adding your own authentication and deployment controls.

## 8. Troubleshooting

- **`python` not found:** install Python 3.10+ and ensure it is on PATH; on Windows, `py -3` may work instead.
- **PowerShell blocks venv activation:** use the documented environment policy for your machine, or invoke `.venv\Scripts\python.exe` directly.
- **STEP export errors:** install `.[cad]`; remember that not all experimental geometry is guaranteed to round-trip through the CAD kernel. The car export is a known unresolved case.
- **A car source compile says `unknown geometry type: loft`:** expected with this archive's v0.5.0 compiler. Use the included GLB until the v0.6 compiler implementation is integrated.
- **A preview looks different between apps:** the GLB's appearance depends on viewer support for glTF PBR materials and extensions; the contact sheet is only a diagnostic render.
