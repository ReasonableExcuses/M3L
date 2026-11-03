"""M3L: Model-first 3D Language — AI-oriented 3D scene compiler and geometry engine."""
from __future__ import annotations

__version__ = "0.7.0"

from .compiler import compile_source, apply_patches, semantic_diff, object_bounds, object_dimensions
from .glb import export_glb
from .exporters import export_obj, export_stl, export_usd
from .parser import parse, M3LParseError
from .judge import judge_result
from .quality import audit_glb, GLBFormatError
from .reverse import decompile_glb, compile_asset_projection, pack_glb, restore_package
from .blender_backend import render_source
from .geometry import HAS_M3L_CORE

__all__ = [
    "compile_source",
    "apply_patches",
    "semantic_diff",
    "object_bounds",
    "object_dimensions",
    "export_glb",
    "export_obj",
    "export_stl",
    "export_usd",
    "parse",
    "M3LParseError",
    "judge_result",
    "audit_glb",
    "GLBFormatError",
    "decompile_glb",
    "compile_asset_projection",
    "pack_glb",
    "restore_package",
    "render_source",
    "HAS_M3L_CORE",
    "__version__",
]
