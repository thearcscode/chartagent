"""PROTOTYPE — the fail-loud gate for a Flint version bump.

    python check_bump.py build/vocab-0.2.1.json build/vocab-0.5.1.json

Exit 0 = the new bundle only widens. Exit 1 = something the facade currently
admits is GONE, so regenerating would silently change what the planner may emit.
That is the failure mode ticket #17 names: every upstream break from 0.2.1 to
0.5.1 was a removal, and a quiet regeneration would have absorbed it.
"""
import json
import sys


def surface(vocab):
    """Flatten to comparable atoms: chart types, property keys+types, enum options."""
    charts, props, options = set(), {}, {}
    for backend, chart_map in vocab["backends"].items():
        for chart, spec in chart_map.items():
            charts.add(f"{backend}|{chart}")
            for p in spec["properties"]:
                pid = f"{backend}|{chart}|{p['key']}"
                props[pid] = p["type"]
                if p["options"]:
                    options[pid] = set(p["options"])
    return charts, props, options


def main():
    old = json.load(open(sys.argv[1]))
    new = json.load(open(sys.argv[2]))
    oc, op, oo = surface(old)
    nc, np_, no = surface(new)

    breaks = []
    for c in sorted(oc - nc):
        breaks.append(f"CHART REMOVED       {c}")
    for p in sorted(set(op) - set(np_)):
        if p.rsplit("|", 1)[0].replace("|", "|") in (oc - nc):
            continue  # already reported as a whole-chart removal
        breaks.append(f"PROPERTY REMOVED    {p}")
    for p in sorted(set(op) & set(np_)):
        if op[p] != np_[p]:
            breaks.append(f"PROPERTY RETYPED    {p}: {op[p]} -> {np_[p]}")
    for p in sorted(set(oo) & set(no)):
        gone = oo[p] - no[p]
        if gone:
            vals = ", ".join(sorted(str(g) for g in gone))
            breaks.append(f"OPTION REMOVED      {p}: lost {vals}")

    added = sorted(set(np_) - set(op))
    print(f"{sys.argv[1]} -> {sys.argv[2]}")
    print(f"  properties: {len(op)} -> {len(np_)}   added: {len(added)}   breaking: {len(breaks)}")
    if new.get("missing_exports"):
        breaks.append(f"BACKEND MISSING     {', '.join(new['missing_exports'])}")
    for b in breaks:
        print("  " + b)
    if breaks:
        print("\nFAIL — regenerate deliberately: each line above changes what the planner may emit.")
        return 1
    print("\nOK — widening only.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
