from pathlib import Path
import json
import re
from tools.universal_parser import extract_symbols


IGNORE = {".git",".venv","__pycache__","node_modules","dist","build"}

TEXT = {".py",".md",".txt",".json",".yaml",".yml",".toml",".cfg",".ini",".java",".js",".jsx"}


def build_tree(repo):
    repo = Path(repo)
    tree = []

    for p in repo.rglob("*"):
        if any(i in p.parts for i in IGNORE):
            continue
        tree.append(str(p.relative_to(repo)))

    return sorted(tree)


def extract_imports_regex(text):
    """Cheap universal-ish import detection."""
    imports = []

    imports += re.findall(r'import\s+([\w\.]+)', text)
    imports += re.findall(r'from\s+([\w\.]+)\s+import', text)

    # java-style imports
    imports += re.findall(r'import\s+([\w\.]+\.\*)', text)

    return sorted(set(imports))


def build_repo_brain(repo_root, call_llm):
    """
    Walk repo, build repo_tree.json + repo_files.json
    Uses Universal Parser for structure.
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
            content = f.read_text(encoding="utf-8", errors="ignore")

            # ✅ UNIVERSAL SYMBOL EXTRACTION
            symbols = extract_symbols(content, str(f))

            func_names = [x["name"] for x in symbols["functions"]]
            class_names = [x["name"] for x in symbols["classes"]]

            imports = extract_imports_regex(content)

            preview = content[:4000]

            prompt = f"""
FILE: {f.name}

Functions: {func_names}
Classes: {class_names}
Imports: {imports}

CODE PREVIEW:
{preview}

Explain what this file does in ONE short sentence.
Plain English only.
""".strip()

            try:
                summary = call_llm(prompt).strip()
                if not summary or summary.startswith("```") or len(summary) > 300:
                    raise ValueError()
            except Exception:
                summary = (
                    f"Provides functions {', '.join(func_names[:5])} "
                    f"and classes {', '.join(class_names[:5])}."
                )

            brain[str(f.relative_to(repo))] = {
                "summary": summary,
                "functions": symbols["functions"],
                "classes": symbols["classes"],
                "imports": imports,
            }

            print("Indexed:", f)

        except Exception as e:
            print("SKIP:", f, e)

    # save files

    with open(repo / "repo_tree.json", "w") as t:
        json.dump(build_tree(repo_root), t, indent=2)

    with open(repo / "repo_files.json", "w") as fjson:
        json.dump(brain, fjson, indent=2)

    print("Repo brain created.")