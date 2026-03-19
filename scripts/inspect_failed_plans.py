#!/usr/bin/env python3
"""Inspect saved failing plan artifacts and extract structural patterns.

Usage:
    python scripts/inspect_failed_plans.py /tmp/gs_failed_plans_goals/
    python scripts/inspect_failed_plans.py /tmp/gs_failed_plans_*/
"""
import json
import sys
from pathlib import Path


def analyze_plan(path: Path) -> dict:
    data = json.loads(path.read_text())
    goal = data.get("goal", "?")
    status = data.get("status", "?")
    error = data.get("error", "")
    plan = data.get("plan")

    print(f"\n{'='*70}")
    print(f"GOAL: {goal}")
    print(f"STATUS: {status}")
    if error:
        print(f"ERROR: {error[:200]}")

    if not plan:
        print("  NO PLAN GENERATED")
        return {"goal": goal, "issues": ["no_plan"]}

    graph = plan.get("graph", {})
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    outputs = graph.get("outputs", {})
    effects = plan.get("effects", [])

    node_ids = {n.get("id") for n in nodes}
    issues = []

    # Check edges
    for e in edges:
        src = e.get("from_") or e.get("from", "")
        dst = e.get("to", "")
        src_scope = src.split(".")[0] if "." in src else src
        dst_scope = dst.split(".")[0] if "." in dst else dst

        if "." not in src:
            issues.append(f"BARE source: '{src}' → {dst}")
        elif src_scope not in ("input",) and src_scope not in node_ids:
            issues.append(f"INVALID source scope '{src_scope}': {src} → {dst}")

        if "." not in dst:
            issues.append(f"BARE destination: {src} → '{dst}'")
        elif dst_scope not in node_ids:
            issues.append(f"INVALID dest scope '{dst_scope}': {src} → {dst}")

    # Check graph_outputs
    for name, addr in outputs.items():
        if "." not in addr:
            issues.append(f"BARE graph_output: {name} → '{addr}'")
        else:
            scope = addr.split(".")[0]
            if scope not in node_ids:
                issues.append(f"graph_output refs unknown node: {name} → '{addr}'")

    # Check effects
    allowed = {"pure", "llm_inference", "network_read", "network_write",
               "filesystem_read", "filesystem_write", "memory_read", "memory_write"}
    for eff in effects:
        if eff not in allowed:
            issues.append(f"INVENTED effect: '{eff}'")

    # Check multi-source conflicts
    dest_sources: dict[str, str] = {}
    for e in edges:
        src = e.get("from_") or e.get("from", "")
        dst = e.get("to", "")
        if dst in dest_sources and dest_sources[dst] != src:
            issues.append(f"MULTI-SOURCE: '{dst}' ← {dest_sources[dst]} AND {src}")
        dest_sources[dst] = src

    print(f"  Nodes: {[(n.get('id'), n.get('op')) for n in nodes]}")
    print(f"  Effects: {effects}")
    print(f"  Outputs: {outputs}")
    if issues:
        print(f"  ISSUES ({len(issues)}):")
        for iss in issues:
            print(f"    - {iss}")
    else:
        print("  No structural issues")

    return {"goal": goal, "issues": issues}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/inspect_failed_plans.py <dir> [...]")
        sys.exit(1)

    all_issues: list[dict] = []
    for arg in sys.argv[1:]:
        p = Path(arg)
        if p.is_dir():
            for f in sorted(p.glob("*.json")):
                all_issues.append(analyze_plan(f))
        elif p.is_file():
            all_issues.append(analyze_plan(p))

    # Aggregate
    print(f"\n{'='*70}")
    print("AGGREGATED PATTERNS")
    print(f"{'='*70}")
    patterns: dict[str, int] = {}
    for r in all_issues:
        for iss in r.get("issues", []):
            tag = iss.split(":")[0].strip()
            patterns[tag] = patterns.get(tag, 0) + 1
    if patterns:
        for tag, count in sorted(patterns.items(), key=lambda x: -x[1]):
            print(f"  {count}x  {tag}")
    else:
        print("  No issues found")
