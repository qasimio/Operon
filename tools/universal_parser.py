# tools/universal_parser.py — Operon v5
"""
Full AST-based symbol extraction + syntax checking.

Supports:
  Python  — uses ast stdlib (zero dependencies)
  JS/TS   — regex fallback with heuristic accuracy
  Java    — regex fallback
  Other   — best-effort regex

extract_symbols() returns:
  {
    "functions":  [{name, start, end, args, docstring, decorators, is_async}],
    "classes":    [{name, start, end, bases, methods, docstring}],
    "variables":  [{name, start, value_repr}],
    "imports":    [{name, start, source}],
    "assignments":[{target, start, value_repr}],
    "decorators": [{name, start, target}],
    "annotations":[{name, annotation, start}],
    "comments":   [{text, start}],  # only populated when include_comments=True
  }
"""
from __future__ import annotations

import ast
import re
import tokenize
import io
from pathlib import Path
from typing import Any, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Syntax check
# ─────────────────────────────────────────────────────────────────────────────

def check_syntax(code: str, file_path: str) -> bool:
    """Returns True if code appears syntactically valid."""
    if not code or not code.strip():
        return True
    ext = str(file_path).rsplit(".", 1)[-1].lower()
    if ext == "py":
        try:
            compile(code, file_path, "exec")
            return True
        except SyntaxError:
            return False
    try:
        opens  = code.count("{") + code.count("(") + code.count("[")
        closes = code.count("}") + code.count(")") + code.count("]")
        return abs(opens - closes) < 20
    except Exception:
        return True


# ─────────────────────────────────────────────────────────────────────────────
# Python extraction — uses ast
# ─────────────────────────────────────────────────────────────────────────────

def _ast_extract_python(source: str) -> Dict[str, List[Any]]:
    result: Dict[str, List[Any]] = {
        "functions": [], "classes": [], "variables": [],
        "imports": [], "assignments": [], "decorators": [],
        "annotations": [], "comments": [],
    }
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return result

    lines = source.splitlines()

    def _get_end_line(node) -> int:
        try:
            return node.end_lineno
        except AttributeError:
            return node.lineno

    def _docstring(node) -> Optional[str]:
        if (node.body and isinstance(node.body[0], ast.Expr)
                and isinstance(getattr(node.body[0], "value", None), ast.Constant)
                and isinstance(node.body[0].value.value, str)):
            return node.body[0].value.value.strip()[:200]
        return None

    def _args_list(args_node) -> List[str]:
        result_args = []
        for a in args_node.args:
            s = a.arg
            if a.annotation:
                s += f": {ast.unparse(a.annotation)}"
            result_args.append(s)
        if args_node.vararg:
            s = "*" + args_node.vararg.arg
            result_args.append(s)
        for a in args_node.kwonlyargs:
            result_args.append(a.arg)
        if args_node.kwarg:
            s = "**" + args_node.kwarg.arg
            result_args.append(s)
        return result_args

    def _decorator_names(node) -> List[str]:
        names = []
        for d in getattr(node, "decorator_list", []):
            try:
                names.append(ast.unparse(d))
            except Exception:
                names.append("?")
        return names

    def _value_repr(node) -> str:
        try:
            return ast.unparse(node)[:80]
        except Exception:
            return "?"

    # Walk top-level and one level deep (class bodies)
    for node in ast.walk(tree):
        # Functions
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            entry = {
                "name":       node.name,
                "start":      node.lineno,
                "end":        _get_end_line(node),
                "args":       _args_list(node.args),
                "docstring":  _docstring(node),
                "decorators": _decorator_names(node),
                "is_async":   isinstance(node, ast.AsyncFunctionDef),
            }
            result["functions"].append(entry)
            # Decorators as separate entries
            for d in node.decorator_list:
                result["decorators"].append({
                    "name":   ast.unparse(d) if hasattr(ast, "unparse") else "?",
                    "start":  d.lineno,
                    "target": node.name,
                })

        # Classes
        elif isinstance(node, ast.ClassDef):
            bases = []
            for b in node.bases:
                try:
                    bases.append(ast.unparse(b))
                except Exception:
                    bases.append("?")
            methods = [
                n.name for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            result["classes"].append({
                "name":      node.name,
                "start":     node.lineno,
                "end":       _get_end_line(node),
                "bases":     bases,
                "methods":   methods,
                "docstring": _docstring(node),
                "decorators": _decorator_names(node),
            })

        # Imports
        elif isinstance(node, ast.Import):
            for alias in node.names:
                result["imports"].append({
                    "name":   alias.asname or alias.name,
                    "source": alias.name,
                    "start":  node.lineno,
                    "kind":   "import",
                })
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                result["imports"].append({
                    "name":   alias.asname or alias.name,
                    "source": f"{mod}:{alias.name}",
                    "start":  node.lineno,
                    "kind":   "from_import",
                    "module": mod,
                })

        # Assignments & annotations
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    result["assignments"].append({
                        "target":     t.id,
                        "start":      node.lineno,
                        "value_repr": _value_repr(node.value),
                    })
                    # Expose as "variable" too for convenience
                    result["variables"].append({
                        "name":        t.id,
                        "start":       node.lineno,
                        "value_repr":  _value_repr(node.value),
                    })
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                ann_str = ""
                try:
                    ann_str = ast.unparse(node.annotation)
                except Exception:
                    pass
                result["annotations"].append({
                    "name":       node.target.id,
                    "annotation": ann_str,
                    "start":      node.lineno,
                    "value_repr": _value_repr(node.value) if node.value else None,
                })
                result["variables"].append({
                    "name":       node.target.id,
                    "start":      node.lineno,
                    "annotation": ann_str,
                    "value_repr": _value_repr(node.value) if node.value else None,
                })

    return result


def _extract_comments_python(source: str) -> List[Dict]:
    comments = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for tok in tokens:
            if tok.type == tokenize.COMMENT:
                comments.append({
                    "text":  tok.string.lstrip("#").strip(),
                    "start": tok.start[0],
                })
    except Exception:
        pass
    return comments


# ─────────────────────────────────────────────────────────────────────────────
# JS/TS extraction — regex
# ─────────────────────────────────────────────────────────────────────────────

def _regex_extract_js(source: str) -> Dict[str, List[Any]]:
    result: Dict[str, List[Any]] = {
        "functions": [], "classes": [], "variables": [],
        "imports": [], "assignments": [], "decorators": [],
        "annotations": [], "comments": [],
    }
    lines = source.splitlines()

    def lineno_at(pos: int) -> int:
        return source[:pos].count("\n") + 1

    # functions: function foo(…), const foo = (…) =>, async function
    for m in re.finditer(
        r"(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(|"
        r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)\s*=>|\w+\s*=>)",
        source
    ):
        name = m.group(1) or m.group(2)
        if name:
            ln = lineno_at(m.start())
            result["functions"].append({"name": name, "start": ln, "end": ln, "args": [], "docstring": None, "decorators": [], "is_async": False})

    # classes
    for m in re.finditer(r"class\s+(\w+)", source):
        ln = lineno_at(m.start())
        result["classes"].append({"name": m.group(1), "start": ln, "end": ln, "bases": [], "methods": [], "docstring": None, "decorators": []})

    # imports
    for m in re.finditer(r"import\s+.*?\s+from\s+['\"]([^'\"]+)['\"]", source):
        ln = lineno_at(m.start())
        result["imports"].append({"name": m.group(0).split("from")[0].strip(), "source": m.group(1), "start": ln, "kind": "es_import"})

    # const/let/var assignments
    for m in re.finditer(r"(?:const|let|var)\s+(\w+)\s*=", source):
        ln = lineno_at(m.start())
        result["variables"].append({"name": m.group(1), "start": ln, "value_repr": ""})

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Java extraction — regex
# ─────────────────────────────────────────────────────────────────────────────

def _regex_extract_java(source: str) -> Dict[str, List[Any]]:
    result: Dict[str, List[Any]] = {
        "functions": [], "classes": [], "variables": [],
        "imports": [], "assignments": [], "decorators": [],
        "annotations": [], "comments": [],
    }

    def lineno_at(pos: int) -> int:
        return source[:pos].count("\n") + 1

    # methods
    for m in re.finditer(
        r"(?:public|private|protected|static|\s)+[\w<>\[\]]+\s+(\w+)\s*\([^)]*\)\s*(?:throws\s+\w+\s*)?\{",
        source
    ):
        ln = lineno_at(m.start())
        result["functions"].append({"name": m.group(1), "start": ln, "end": ln, "args": [], "docstring": None, "decorators": [], "is_async": False})

    # classes
    for m in re.finditer(r"(?:public\s+)?class\s+(\w+)", source):
        ln = lineno_at(m.start())
        result["classes"].append({"name": m.group(1), "start": ln, "end": ln, "bases": [], "methods": [], "docstring": None, "decorators": []})

    # imports
    for m in re.finditer(r"import\s+([\w\.]+)\s*;", source):
        ln = lineno_at(m.start())
        result["imports"].append({"name": m.group(1).split(".")[-1], "source": m.group(1), "start": ln, "kind": "import"})

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def extract_symbols(content: str, file_path: str, include_comments: bool = False) -> Dict[str, List[Any]]:
    """
    Extract all symbols from source code.

    Returns dict with keys:
      functions, classes, variables, imports, assignments, decorators,
      annotations, comments
    """
    ext = Path(file_path).suffix.lower()

    if ext == ".py":
        result = _ast_extract_python(content)
        if include_comments:
            result["comments"] = _extract_comments_python(content)
        return result

    if ext in (".js", ".jsx", ".ts", ".tsx", ".mjs"):
        return _regex_extract_js(content)

    if ext == ".java":
        return _regex_extract_java(content)

    # Generic regex for anything else
    result: Dict[str, List[Any]] = {
        "functions": [], "classes": [], "variables": [],
        "imports": [], "assignments": [], "decorators": [],
        "annotations": [], "comments": [],
    }
    for m in re.finditer(r"^(?:def|async def)\s+(\w+)\s*\(", content, re.MULTILINE):
        ln = content[:m.start()].count("\n") + 1
        result["functions"].append({"name": m.group(1), "start": ln, "end": ln, "args": [], "docstring": None, "decorators": [], "is_async": False})
    for m in re.finditer(r"^class\s+(\w+)", content, re.MULTILINE):
        ln = content[:m.start()].count("\n") + 1
        result["classes"].append({"name": m.group(1), "start": ln, "end": ln, "bases": [], "methods": [], "docstring": None, "decorators": []})
    return result


def get_block_source(content: str, start_line: int, end_line: int) -> str:
    """Extract lines [start_line..end_line] (1-based, inclusive)."""
    lines = content.splitlines(keepends=True)
    s = max(0, start_line - 1)
    e = min(len(lines), end_line)
    return "".join(lines[s:e])
