"""Local UI backend — serves the web UI and provides a JSON API."""
from __future__ import annotations

import json
import tempfile
import traceback
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from graphsmith.graph_export import graph_to_json
from graphsmith.planner.deltas import build_refined_goal, compute_diff, extract_deltas, format_diff
from graphsmith.planner.ir_backend import IRPlannerBackend
from graphsmith.planner.models import GlueGraph


class UIState:
    """Shared state for the UI session."""

    def __init__(
        self,
        backend: IRPlannerBackend,
        registry: Any,
    ) -> None:
        self.backend = backend
        self.registry = registry
        self.last_goal = ""
        self.plan_versions: list[dict[str, Any]] = []
        self.last_candidates: list[dict[str, Any]] = []
        self.last_decomposition: dict[str, Any] = {}

    def plan(self, goal: str) -> dict[str, Any]:
        from graphsmith.planner.candidates import retrieve_candidates
        from graphsmith.planner.models import PlanRequest

        self.last_goal = goal
        cands = retrieve_candidates(goal, self.registry)
        request = PlanRequest(goal=goal, candidates=cands)
        result = self.backend.compose(request)

        # Capture candidates
        self.last_candidates = []
        for c in self.backend.last_candidates:
            entry: dict[str, Any] = {
                "index": c.index, "status": c.status,
                "error": c.error or "",
            }
            if c.ir:
                entry["steps"] = [s.name for s in c.ir.steps]
                entry["skills"] = [s.skill_id for s in c.ir.steps]
                entry["outputs"] = list(c.ir.final_outputs.keys())
            if c.score:
                entry["score"] = c.score.total
                entry["penalties"] = [r for r, _ in c.score.penalties]
                entry["rewards"] = [r for r, _ in c.score.rewards]
            if c.glue:
                entry["selected"] = True
            self.last_candidates.append(entry)

        # Mark the selected candidate
        compiled = [e for e in self.last_candidates if e.get("score")]
        if compiled:
            best = max(compiled, key=lambda x: x.get("score", 0))
            for e in self.last_candidates:
                e["selected"] = e["index"] == best["index"]

        # Capture decomposition
        d = self.backend.last_decomposition
        self.last_decomposition = {}
        if d:
            self.last_decomposition = {
                "content_transforms": d.content_transforms,
                "presentation": d.presentation,
                "final_output_names": d.final_output_names,
                "reasoning": d.reasoning or "",
            }

        if result.status != "success" or result.graph is None:
            return {"status": "failure", "error": "Planning failed"}

        graph_data = _glue_to_dict(result.graph)
        version = {
            "label": f"v{len(self.plan_versions)+1}: {goal[:40]}",
            "goal": goal,
            "graph": graph_data,
        }
        self.plan_versions.append(version)

        return {
            "status": "success",
            "graph": graph_data,
            "candidates": self.last_candidates,
            "decomposition": self.last_decomposition,
            "version": len(self.plan_versions),
        }

    def refine(self, request_text: str) -> dict[str, Any]:
        if not self.last_goal or not self.plan_versions:
            return {"status": "failure", "error": "No plan to refine"}

        prev_graph = self.plan_versions[-1]["graph"]
        refinement = extract_deltas(request_text)
        deltas_info = [{"kind": d.kind, "target": d.target} for d in refinement.deltas]

        refined_goal = build_refined_goal(self.last_goal, refinement)
        result = self.plan(refined_goal)

        if result["status"] == "success" and self.plan_versions:
            curr_graph = self.plan_versions[-1]["graph"]
            diff = _compute_dict_diff(prev_graph, curr_graph)
            result["delta"] = deltas_info
            result["diff"] = diff
            result["refined_goal"] = refined_goal
            result["previous_graph"] = prev_graph

        return result

    def get_versions(self) -> list[dict[str, Any]]:
        return [
            {"index": i+1, "label": v["label"], "goal": v["goal"]}
            for i, v in enumerate(self.plan_versions)
        ]

    def get_version(self, index: int) -> dict[str, Any] | None:
        if 0 < index <= len(self.plan_versions):
            return self.plan_versions[index - 1]
        return None

    def get_diff(self) -> dict[str, Any]:
        if len(self.plan_versions) < 2:
            return {"error": "Need at least 2 versions"}
        prev = self.plan_versions[-2]["graph"]
        curr = self.plan_versions[-1]["graph"]
        return _compute_dict_diff(prev, curr)


def _glue_to_dict(glue: GlueGraph) -> dict[str, Any]:
    """Convert GlueGraph to a JSON-serializable dict for the UI."""
    return {
        "goal": glue.goal,
        "inputs": [{"name": i.name, "type": i.type} for i in glue.inputs],
        "outputs": [{"name": o.name, "type": o.type} for o in glue.outputs],
        "effects": glue.effects,
        "graph": {
            "nodes": [
                {"id": n.id, "op": n.op, "config": dict(n.config)}
                for n in glue.graph.nodes
            ],
            "edges": [
                {"from_": e.from_, "to": e.to}
                for e in glue.graph.edges
            ],
            "outputs": dict(glue.graph.outputs),
        },
    }


def _compute_dict_diff(before: dict, after: dict) -> dict[str, Any]:
    """Compute a simple structural diff between two graph dicts."""
    before_nodes = {n["id"] for n in before.get("graph", {}).get("nodes", [])}
    after_nodes = {n["id"] for n in after.get("graph", {}).get("nodes", [])}
    before_outs = set(before.get("graph", {}).get("outputs", {}).keys())
    after_outs = set(after.get("graph", {}).get("outputs", {}).keys())

    return {
        "added_steps": sorted(after_nodes - before_nodes),
        "removed_steps": sorted(before_nodes - after_nodes),
        "added_outputs": sorted(after_outs - before_outs),
        "removed_outputs": sorted(before_outs - after_outs),
    }


def create_handler(state: UIState, ui_dir: Path):
    """Create an HTTP request handler with access to UIState."""

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(ui_dir), **kwargs)

        def log_message(self, fmt: str, *args: Any) -> None:
            pass

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/"):
                self._handle_api_get(parsed.path, parse_qs(parsed.query))
            else:
                super().do_GET()

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/"):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length)) if length else {}
                self._handle_api_post(parsed.path, body)
            else:
                self.send_error(404)

        def _handle_api_get(self, path: str, params: dict) -> None:
            try:
                if path == "/api/versions":
                    self._json_response(state.get_versions())
                elif path == "/api/diff":
                    self._json_response(state.get_diff())
                elif path.startswith("/api/version/"):
                    idx = int(path.split("/")[-1])
                    v = state.get_version(idx)
                    self._json_response(v or {"error": "not found"})
                else:
                    self._json_response({"error": "unknown endpoint"}, 404)
            except Exception as exc:
                self._json_response({"error": str(exc)}, 500)

        def _handle_api_post(self, path: str, body: dict) -> None:
            try:
                if path == "/api/plan":
                    goal = body.get("goal", "")
                    if not goal:
                        self._json_response({"error": "goal required"}, 400)
                        return
                    result = state.plan(goal)
                    self._json_response(result)
                elif path == "/api/refine":
                    request_text = body.get("request", "")
                    if not request_text:
                        self._json_response({"error": "request required"}, 400)
                        return
                    result = state.refine(request_text)
                    self._json_response(result)
                else:
                    self._json_response({"error": "unknown endpoint"}, 404)
            except Exception as exc:
                self._json_response({"error": str(exc), "trace": traceback.format_exc()}, 500)

        def _json_response(self, data: Any, status: int = 200) -> None:
            body = json.dumps(data, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler
