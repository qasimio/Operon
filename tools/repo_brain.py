from pathlib import Path
import json
import re
import ast


IGNORE = {".git",".venv","__pycache__","node_modules","dist","build"}

TEXT = {".py",".md",".txt",".json",".yaml",".yml",".toml",".cfg",".ini"}


def build_tree(repo):

    repo = Path(repo)

    tree = []

    for p in repo.rglob("*"):

        if any(i in p.parts for i in IGNORE):
            continue

        tree.append(str(p.relative_to(repo)))

    return sorted(tree)


def extract_python_info(text):

    funcs = re.findall(r'def\s+(\w+)\(', text)
    classes = re.findall(r'class\s+(\w+)', text)
    imports = re.findall(r'import\s+([\w\.]+)', text)

    return funcs, classes, imports

def build_repo_brain(repo_root, call_llm):
    """
    Walk the repo, build repo_tree.json and repo_files.json.
    Uses AST for structure and a small LLM prompt to produce short summaries.
    """

    repo = Path(repo_root)

    files = []

    for p in repo.rglob("*"):
        if any(i in p.parts for i in IGNORE):
            continue
        if not p.is_file():
            continue
        if p.suffix not in TEXT:
            continue
        files.append(p)

    brain = {}

    for f in files:
        try:
            content = f.read_text(errors="ignore")
        except Exception as e:
            print("SKIP (read error):", f, e)
            continue

        # AST structure extraction (functions/classes with line ranges)
        structure = extract_python_structure_ast(content)

        # deterministic regex fallback to collect simple names and imports
        funcs, classes, imports = extract_python_info(content)

        # Keep prompt small and structured: use only names (not big dicts)
        func_names = [fn["name"] for fn in structure.get("functions", [])]
        class_names = [c["name"] for c in structure.get("classes", [])]

        preview = content[:4000]   # limit tokens, small models panic otherwise

        prompt = f"""
FILE: {f.name}

Functions: {func_names}
Classes: {class_names}
Imports: {imports}

CODE PREVIEW (first 4000 chars):
{preview}

Explain what this file does in ONE short sentence.
Plain English only. No markdown, no lists, no code blocks.
""".strip()

        # Ask the LLM, but be defensive — if it fails, fall back to a deterministic short summary
        try:
            summary = call_llm(prompt).strip()
            # simple guard: if the model output looks like markdown or is empty, fallback
            if not summary or summary.startswith("```") or len(summary) > 300:
                raise ValueError("LLM returned unsuitable summary")
        except Exception:
            # deterministic fallback short summary
            summary = (
                f"Provides functions {', '.join(func_names[:5])} "
                f"and classes {', '.join(class_names[:5])}."
            )

        brain[str(f.relative_to(repo))] = {
            "summary": summary,
            "functions": structure.get("functions", []),
            "classes": structure.get("classes", []),
            "imports": imports
        }

        print("Indexed:", f)

    # save everything
    with open(repo / "repo_tree.json", "w") as t:
        json.dump(build_tree(repo_root), t, indent=2)

    with open(repo / "repo_files.json", "w") as fjson:
        json.dump(brain, fjson, indent=2)

    print("Repo brain created.")

def extract_python_structure_ast(code: str):

    results = {
        "functions": [],
        "classes": []
    }

    try:
        tree = ast.parse(code)
    except Exception:
        return results

    class Visitor(ast.NodeVisitor):

        def visit_FunctionDef(self, node):
            results["functions"].append({
                "name": node.name,
                "start": node.lineno,
                "end": getattr(node, "end_lineno", node.lineno),
            })
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node):
            results["functions"].append({
                "name": node.name,
                "start": node.lineno,
                "end": getattr(node, "end_lineno", node.lineno),
            })
            self.generic_visit(node)

        def visit_ClassDef(self, node):

            results["classes"].append({
                "name": node.name,
                "start": node.lineno,
                "end": getattr(node, "end_lineno", node.lineno),
            })

            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    results["functions"].append({
                        "name": f"{node.name}.{child.name}",
                        "start": child.lineno,
                        "end": getattr(child, "end_lineno", child.lineno),
                    })

            self.generic_visit(node)

    Visitor().visit(tree)

    return results