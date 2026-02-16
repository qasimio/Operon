from pathlib import Path
import json
import re

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
            "functions": funcs,
            "classes": classes,
            "imports": imports
        }

        print("Indexed:", f)

    # save everything
    with open(repo/"repo_tree.json","w") as t:
        json.dump(build_tree(repo_root), t, indent=2)

    with open(repo/"repo_files.json","w") as f:
        json.dump(brain, f, indent=2)

    print("Repo brain created.")
