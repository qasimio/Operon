# tools/diff_report.py
from pathlib import Path
import json
import datetime
def dump_diff_report_from_json(json_path, out_path=None):
    j = Path(json_path)
    if not j.exists():
        raise FileNotFoundError(f"No diff JSON at {json_path}")
    data = json.loads(j.read_text(encoding="utf-8") or "{}")
    if not out_path:
        out_path = j.parent / "last_session_diff.txt"
    out = Path(out_path)
    lines = []
    lines.append("OPERON DIFF REPORT")
    lines.append("="*70)
    for fname, patches in data.items():
        lines.append("")
        lines.append(f"FILE: {fname}")
        lines.append("-"*70)
        for p in patches:
            ts = datetime.datetime.fromtimestamp(p.get("ts", 0)).isoformat()
            lines.append(f"\nPATCH @ {ts}")
            lines.append("-"*30)
            diff = p.get("diff") or "(no diff recorded)"
            lines.append(diff)
            lines.append("\n")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
def dump_diff_report_from_repo(repo_root, out_path=None):
    path = Path(repo_root) / ".operon" / "last_session_diff.json"
    return dump_diff_report_from_json(path, out_path or (Path(repo_root)/".operon"/"last_session_diff.txt"))