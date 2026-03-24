"""Topological execution planner — computes deterministic node order."""
from __future__ import annotations

from collections import defaultdict

from graphsmith.exceptions import ExecutionError
from graphsmith.models import SkillPackage


def topological_order(pkg: SkillPackage) -> list[str]:
    """Return node IDs in a deterministic topological order.

    Uses Kahn's algorithm with ties broken by sorted node ID so the
    execution order is identical across runs.
    """
    node_ids = {node.id for node in pkg.graph.nodes}
    adj: dict[str, set[str]] = defaultdict(set)
    indegree: dict[str, int] = {nid: 0 for nid in node_ids}

    for edge in pkg.graph.edges:
        src_scope = edge.from_.split(".", 1)[0]
        dst_scope = edge.to.split(".", 1)[0]
        if src_scope == "input":
            continue
        if src_scope in node_ids and dst_scope in node_ids:
            if dst_scope not in adj[src_scope]:
                adj[src_scope].add(dst_scope)
                indegree[dst_scope] += 1

    # Also account for node.inputs address references
    for node in pkg.graph.nodes:
        for _port, address in node.inputs.items():
            src_scope = address.split(".", 1)[0]
            if src_scope in node_ids and src_scope != node.id:
                if node.id not in adj[src_scope]:
                    adj[src_scope].add(node.id)
                    indegree[node.id] += 1
        if node.when:
            raw = node.when[1:] if node.when.startswith("!") else node.when
            src_scope = raw.split(".", 1)[0]
            if src_scope in node_ids and src_scope != node.id:
                if node.id not in adj[src_scope]:
                    adj[src_scope].add(node.id)
                    indegree[node.id] += 1

    queue = sorted(nid for nid, deg in indegree.items() if deg == 0)
    order: list[str] = []

    while queue:
        current = queue.pop(0)
        order.append(current)
        for nxt in sorted(adj[current]):
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if len(order) != len(node_ids):
        raise ExecutionError("Cycle detected during execution planning")

    return order
