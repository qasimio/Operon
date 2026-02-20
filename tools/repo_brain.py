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
            structure = extract_python_structure_ast(content)
        except:
            continue

        preview = content[:3500]

        prompt = f"""
Summarize this file in ONE SHORT paragraph.
Be technical and concise.

FILE: {f.name}

CONTENT:
{preview}
"""

        summary = call_llm(prompt).strip()

        funcs, classes, imports = extract_python_info(content)

        brain[str(f.relative_to(repo))] = {
            "summary": summary,
            "functions": structure["functions"],
            "classes": structure["classes"],
            "imports": imports
        }

        print("Indexed:", f)

    # save everything
    with open(repo/"repo_tree.json","w") as t:
        json.dump(build_tree(repo_root), t, indent=2)

    with open(repo/"repo_files.json","w") as f:
        json.dump(brain, f, indent=2)

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