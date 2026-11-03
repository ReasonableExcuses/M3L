"""Small, dependency-free parser for the M3L v0.3 scene language."""
from __future__ import annotations

import ast
import json
import math
import re
from typing import Any


class M3LParseError(Exception):
    def __init__(self, message: str, line: int = 1):
        super().__init__(message)
        self.message = message
        self.line = line


def _json_value(value: Any) -> Any:
    """Normalize Python literal containers to the JSON-shaped M3L value model."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite numbers are not allowed")
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    raise ValueError(f"{type(value).__name__} is not a supported JSON value")


def _strip_comment(line: str) -> str:
    """Remove # comments without eating #rrggbb strings."""
    quote = None
    escaped = False
    for i, ch in enumerate(line):
        if escaped:
            escaped = False
            continue
        if ch == "\\" and quote:
            escaped = True
            continue
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in ('"', "'"):
            quote = ch
        elif ch == "#":
            return line[:i]
    return line


_SAFE_MATH_CONSTANTS: dict[str, float] = {
    "pi": math.pi, "PI": math.pi, "e": math.e,
}
_SAFE_MATH_FUNCS: dict[str, Any] = {
    "min": min, "max": max, "abs": abs, "round": round,
    "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
}


def _eval_ast_node(node: ast.AST, env: dict[str, Any], line_no: int) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        if node.id in _SAFE_MATH_CONSTANTS:
            return _SAFE_MATH_CONSTANTS[node.id]
        raise M3LParseError(f"Undefined parameter or symbol {node.id!r} in expression.", line_no)
    if isinstance(node, ast.BinOp):
        left = _eval_ast_node(node.left, env, line_no)
        right = _eval_ast_node(node.right, env, line_no)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise M3LParseError("Division by zero in expression.", line_no)
            return left / right
        if isinstance(node.op, ast.Mod):
            return left % right
        if isinstance(node.op, ast.Pow):
            if abs(float(right)) > 100:
                raise M3LParseError("Exponent too large in expression (limit is 100).", line_no)
            return left ** right
        raise M3LParseError(f"Unsupported binary operator in expression.", line_no)
    if isinstance(node, ast.UnaryOp):
        operand = _eval_ast_node(node.operand, env, line_no)
        if isinstance(node.op, ast.UAdd):
            return +operand
        if isinstance(node.op, ast.USub):
            return -operand
        raise M3LParseError("Unsupported unary operator in expression.", line_no)
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval_ast_node(elt, env, line_no) for elt in node.elts]
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in _SAFE_MATH_FUNCS:
            func = _SAFE_MATH_FUNCS[node.func.id]
            args = [_eval_ast_node(arg, env, line_no) for arg in node.args]
            return func(*args)
        raise M3LParseError("Only safe mathematical functions (min, max, abs, round, sqrt, sin, cos, tan) are allowed.", line_no)
    raise M3LParseError(f"Unsupported expression syntax.", line_no)


def _parse_value(raw: str, line_no: int, env: dict[str, Any] | None = None) -> Any:
    raw = raw.strip().rstrip(";").strip()
    if not raw:
        raise M3LParseError("Expected a value after '='.", line_no)
    # Arrays, dicts and quoted strings use Python's literal parser (the syntax is the same here).
    if raw.startswith("{") or raw.startswith("[") or raw.startswith("(") or raw.startswith("\"") or raw.startswith("'"):
        try:
            value = ast.literal_eval(raw)
            return _json_value(value)
        except (SyntaxError, ValueError):
            # Attempt to parse json-like syntax with unquoted keys (e.g. {time: 0.0, value: 1.0})
            try:
                normalized = re.sub(r'([{\[,]\s*)([A-Za-z_][A-Za-z0-9_-]*)\s*[:=]\s*', r'\1"\2": ', raw)
                value = json.loads(normalized)
                return _json_value(value)
            except Exception:
                pass
            if env:
                try:
                    parsed_expr = ast.parse(raw, mode="eval")
                    val = _eval_ast_node(parsed_expr.body, env, line_no)
                    return _json_value(val)
                except M3LParseError:
                    pass
                except Exception:
                    pass
            if raw.startswith("[") and raw.endswith("]"):
                inner = raw[1:-1].strip()
                if inner:
                    parts = [p.strip() for p in inner.split(",") if p.strip()]
                    if all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.:-]*", p) for p in parts):
                        if env:
                            return [env.get(p, p) for p in parts]
                        return parts
            raise M3LParseError(f"Invalid value {raw!r}.", line_no)
    lower = raw.lower()
    if lower in ("true", "false"):
        return lower == "true"
    if lower in ("null", "none"):
        return None
    try:
        if re.fullmatch(r"[+-]?\d+", raw):
            return int(raw)
        value = float(raw)
        if math.isfinite(value):
            return value
    except ValueError:
        pass
    # Bare identifiers are useful for enum values and material references.
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.:-]*", raw):
        # If the bare identifier is a declared parameter, resolve it; otherwise keep as identifier string
        if env and raw in env:
            return env[raw]
        return raw
    # Try safe expression evaluation if an environment of parameters is available
    if env is not None:
        try:
            parsed_expr = ast.parse(raw, mode="eval")
            val = _eval_ast_node(parsed_expr.body, env, line_no)
            return _json_value(val)
        except M3LParseError:
            raise
        except Exception as exc:
            raise M3LParseError(f"Cannot evaluate expression {raw!r}: {exc}", line_no) from exc
    raise M3LParseError(f"Can't parse value {raw!r}. Use a number, quoted string, array, boolean, or identifier.", line_no)


def parse(source: str) -> dict[str, Any]:
    """Parse M3L into a normalized mutable AST.

    Grammar is line-oriented by design: one declaration or property per line.
    This makes both LLM output and line/field patches straightforward.
    """
    if not isinstance(source, str) or not source.strip():
        raise M3LParseError("Source is empty.", 1)

    lines = source.splitlines()
    scene: dict[str, Any] | None = None
    stack: list[tuple[str, dict[str, Any], int]] = []
    saw_scene = False

    def current_context() -> tuple[str, dict[str, Any], int] | None:
        return stack[-1] if stack else None

    accumulator = ""
    accum_start_line = 0

    for line_no, raw_line in enumerate(lines, start=1):
        line = _strip_comment(raw_line).strip()
        if not line:
            continue

        if accumulator:
            accumulator += " " + line
            if (accumulator.count("[") <= accumulator.count("]") and
                accumulator.count("(") <= accumulator.count(")") and
                accumulator.count("{") <= accumulator.count("}")):
                line = accumulator
                accumulator = ""
                line_no = accum_start_line
            else:
                continue
        elif "=" in line and not line.endswith("{"):
            if (line.count("[") > line.count("]") or
                line.count("(") > line.count(")") or
                line.count("{") > line.count("}")):
                accumulator = line
                accum_start_line = line_no
                continue

        if not saw_scene:
            m = re.fullmatch(r'scene\s+(?:"([^"]+)"|([A-Za-z_][A-Za-z0-9_-]*))\s*\{', line)
            if not m:
                raise M3LParseError('The file must begin with: scene "name" {', line_no)
            name = m.group(1) or m.group(2)
            scene = {
                "name": name, "units": "m", "materials": {}, "objects": [], "arrays": [], "features": [], "variants": [],
                "groups": [], "prototypes": [], "instances": [], "params": {}, "joints": [], "animations": [],
                "camera": None, "lights": [], "constraints": [], "source_lines": len(lines)
            }
            stack.append(("scene", scene, line_no))
            saw_scene = True
            continue

        if line == "}":
            if not stack:
                raise M3LParseError("Unexpected closing brace.", line_no)
            stack.pop()
            continue

        if not stack:
            raise M3LParseError("Content found after the scene's closing brace.", line_no)

        kind, owner, owner_line = current_context()  # type: ignore[misc]

        # Scene-level or group-level parameter declaration: param <name> = <val>;
        m_param = re.fullmatch(r'param\s+([A-Za-z_][A-Za-z0-9_-]*)\s*=\s*(.*?)\s*;?', line)
        if m_param:
            pname, raw_val = m_param.group(1), m_param.group(2)
            val = _parse_value(raw_val, line_no, env=scene["params"])  # type: ignore[index]
            scene["params"][pname] = val  # type: ignore[index]
            scene.setdefault("_param_lines", {})[pname] = line_no  # type: ignore[union-attr]
            continue

        # Nested block declarations.
        m = re.fullmatch(r'(material|feature|variant|box|sphere|cylinder|extrude|revolve|sweep|loft|cone|torus|boolean|subdivision|group|prototype|instance|camera|light|constraint|array|joint|animation)\s*(?:([A-Za-z_][A-Za-z0-9_-]*))?\s*\{', line)
        if m:
            block_type, block_name = m.group(1), m.group(2)
            if kind not in ("scene", "group", "prototype"):
                raise M3LParseError("Blocks cannot be nested inside object blocks in M3L.", line_no)
            if kind == "group" and block_type in ("group", "prototype", "instance", "material", "feature", "variant", "camera", "light", "constraint", "joint", "animation"):
                raise M3LParseError(f"A {block_type} block cannot be declared inside a group.", line_no)
            if kind == "prototype" and block_type in ("group", "prototype", "instance", "material", "feature", "variant", "camera", "light", "constraint", "array", "joint", "animation"):
                raise M3LParseError(f"A {block_type} block cannot be declared inside a prototype.", line_no)
            if block_type in ("material", "feature", "variant", "box", "sphere", "cylinder", "extrude", "revolve", "sweep", "loft", "cone", "torus", "boolean", "subdivision", "group", "prototype", "instance", "light", "constraint", "array", "joint", "animation") and not block_name:
                raise M3LParseError(f"A {block_type} block needs a name.", line_no)
            if block_type == "camera" and block_name:
                raise M3LParseError("Camera is a singleton and does not take a name.", line_no)
            block = {"name": block_name, "props": {}, "line": line_no}
            if kind == "group" and isinstance(owner, dict):
                block["group"] = owner.get("name")
            if block_type == "material":
                if block_name in scene["materials"]:  # type: ignore[index]
                    raise M3LParseError(f"Duplicate material name {block_name!r}.", line_no)
                scene["materials"][block_name] = block["props"]  # type: ignore[index]
                scene.setdefault("_material_lines", {})[block_name] = line_no  # type: ignore[union-attr]
                stack.append(("material", block["props"], line_no))
            elif block_type == "feature":
                scene["features"].append(block)  # type: ignore[index]
                stack.append(("feature", block["props"], line_no))
            elif block_type == "variant":
                scene["variants"].append(block)  # type: ignore[index]
                stack.append(("variant", block["props"], line_no))
            elif block_type == "group":
                scene["groups"].append(block)  # type: ignore[index]
                stack.append(("group", block, line_no))
            elif block_type == "prototype":
                scene["prototypes"].append(block)  # type: ignore[index]
                stack.append(("prototype", block, line_no))
            elif block_type == "instance":
                scene["instances"].append(block)  # type: ignore[index]
                stack.append(("instance", block["props"], line_no))
            elif block_type in ("box", "sphere", "cylinder", "extrude", "revolve", "sweep", "loft", "cone", "torus", "boolean", "subdivision"):
                obj_decl = {"type": block_type, "name": block_name, "props": block["props"], "line": line_no}
                if kind == "group" and isinstance(owner, dict):
                    obj_decl["group"] = owner.get("name")
                elif kind == "prototype" and isinstance(owner, dict):
                    obj_decl["prototype"] = owner.get("name")
                scene["objects"].append(obj_decl)  # type: ignore[index]
                stack.append(("object", block["props"], line_no))
            elif block_type == "camera":
                if scene["camera"] is not None:  # type: ignore[index]
                    raise M3LParseError("Only one camera block is supported.", line_no)
                scene["camera"] = block["props"]  # type: ignore[index]
                scene["_camera_line"] = line_no  # type: ignore[index]
                stack.append(("camera", block["props"], line_no))
            elif block_type == "light":
                scene["lights"].append(block)  # type: ignore[index]
                stack.append(("light", block["props"], line_no))
            elif block_type == "constraint":
                scene["constraints"].append(block)  # type: ignore[index]
                stack.append(("constraint", block["props"], line_no))
            elif block_type == "array":
                scene["arrays"].append(block)  # type: ignore[index]
                stack.append(("array", block["props"], line_no))
            elif block_type == "joint":
                scene["joints"].append(block)  # type: ignore[index]
                stack.append(("joint", block["props"], line_no))
            elif block_type == "animation":
                scene["animations"].append(block)  # type: ignore[index]
                stack.append(("animation", block["props"], line_no))
            continue

        if line in ("};", "}; # end"):
            if not stack:
                raise M3LParseError("Unexpected closing brace.", line_no)
            stack.pop()
            continue

        # Property or scene-level setting. `;` is accepted as an optional line terminator.
        pm = re.fullmatch(r'([A-Za-z_][A-Za-z0-9_-]*)\s*=\s*(.*?)\s*;?', line)
        if pm:
            key, raw_value = pm.group(1), pm.group(2)
            value = _parse_value(raw_value, line_no, env=scene["params"])  # type: ignore[index]
            if kind == "scene":
                if key == "units":
                    scene["units"] = value  # type: ignore[index]
                else:
                    raise M3LParseError(f"Unknown scene-level setting {key!r}. Supported: units.", line_no)
            else:
                target_dict = owner["props"] if (kind in ("group", "prototype") and isinstance(owner, dict) and "props" in owner) else owner
                if key in target_dict:
                    raise M3LParseError(f"Property {key!r} is defined more than once in this block.", line_no)
                target_dict[key] = value
                target_dict.setdefault("__lines__", {})[key] = line_no
            continue

        raise M3LParseError(f"Unrecognized syntax: {line}", line_no)

    if not saw_scene or scene is None:
        raise M3LParseError('Missing scene declaration: scene "name" {', 1)
    if stack:
        kind, _, open_line = stack[-1]
        raise M3LParseError(f"Unclosed {kind} block opened on line {open_line}.", len(lines) or 1)
    # Remove parser-only metadata from the values, retaining line metadata separately.
    scene["_property_lines"] = {}
    scene["_object_lines"] = {o["name"]: o["line"] for o in scene["objects"]}
    scene["_light_lines"] = {l["name"]: l["line"] for l in scene["lights"]}
    scene["_constraint_lines"] = {c["name"]: c["line"] for c in scene["constraints"]}
    scene["_array_lines"] = {a["name"]: a["line"] for a in scene["arrays"]}
    scene["_group_lines"] = {g["name"]: g["line"] for g in scene.get("groups", [])}
    scene["_prototype_lines"] = {p["name"]: p["line"] for p in scene.get("prototypes", [])}
    scene["_instance_lines"] = {i["name"]: i["line"] for i in scene.get("instances", [])}
    return scene
