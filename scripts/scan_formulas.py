"""
Check every saved calculation against the formula engine.

Usage (from the app directory, venv active):
  python scripts/scan_formulas.py

Reports formulas that no longer parse, and formulas whose results may change
because text comparisons now ignore case (STARTSWITH / ENDSWITH / = / <> on text).
CONTAINS already ignored case, so it is unaffected.
"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils.config import get_base_dir                      # noqa: E402
from utils.formula import parse, FormulaError, to_sql        # noqa: E402


def walk(node, found):
    k = node[0]
    if k == "call":
        if node[1] in ("STARTSWITH", "ENDSWITH"):
            found.add(node[1])
        for a in node[2]:
            walk(a, found)
    elif k == "bin":
        if node[1] in ("=", "<>") and ("lit" in (node[2][0], node[3][0])) and \
           any(n[0] == "lit" and isinstance(n[1], str) for n in (node[2], node[3])):
            found.add("text " + node[1])
        walk(node[2], found); walk(node[3], found)
    elif k in ("not", "neg"):
        walk(node[1], found)
    elif k == "if":
        for c, v in node[1]:
            walk(c, found); walk(v, found)
        walk(node[2], found)


def main():
    base = get_base_dir() / "data"
    sources = [("(global)", base.parent / "config.json")]
    sources += [(p.name, p / "config.json") for p in sorted((base / "users").glob("*")) if (p / "config.json").exists()]
    shared = base / "shared" / "calculations.json"
    total = problems = 0
    for owner, path in sources:
        if not path.exists():
            continue
        calcs = json.load(open(path)).get("global_calculations", {})
        for name, defn in calcs.items():
            if defn.get("type") != "formula":
                continue
            total += 1
            f = defn.get("formula", "")
            try:
                node = parse(f)
            except FormulaError as e:
                problems += 1
                print(f"[DOES NOT PARSE]  {owner} / {name}: {f}\n                  -> {e}")
                continue
            found = set()
            walk(node, found)
            if found:
                print(f"[CASE CHANGE]     {owner} / {name}: {f}\n                  -> now ignores case in: {', '.join(sorted(found))}"
                      f" (use the _CS version or EXACT() to keep exact case)")
            if to_sql(f, lambda n: "x") is None:
                print(f"[DISPLAY ONLY]    {owner} / {name}: {f}  (can't be used as a filter)")
    if shared.exists():
        for name, defn in json.load(open(shared)).items():
            total += 1
            try:
                parse(defn.get("formula", ""))
            except FormulaError as e:
                problems += 1
                print(f"[DOES NOT PARSE]  shared / {name}: {defn.get('formula')}\n                  -> {e}")
    print(f"\nChecked {total} formula calculation(s); {problems} need fixing.")


if __name__ == "__main__":
    main()
