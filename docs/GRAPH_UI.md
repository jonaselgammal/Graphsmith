# Graph UI

Graphsmith includes a local web UI for visually inspecting plans, viewing
candidates, applying refinements, and tracking plan versions.

## Launch

```bash
graphsmith ui
```

Options:
```bash
graphsmith ui --provider anthropic --model claude-haiku-4-5-20251001 --candidates 3
graphsmith ui --port 8080
```

Opens `http://localhost:8741` in your browser.

## Panels

### Goal / Controls
- Text input for the goal
- Plan button to run the planner
- Refine button to modify the current plan

### Graph View (main canvas)
- Visual node/edge graph with topological layout
- Input node (blue), skill nodes (white), output node (green)
- Click any skill node to inspect its details
- Edges labeled with port names

### Plan Summary (left panel, Plan tab)
- Flow chain (normalize → extract → format)
- Step list with skill tags
- Output mappings
- Decomposition (content transforms, presentation)

### Candidates (left panel, Candidates tab)
- All N candidates with scores
- Selected candidate highlighted
- Steps and penalties shown per candidate
- Failed candidates show status and error

### Refine (left panel, Refine tab)
- Text input for refinement request
- Apply button runs delta extraction + replan
- Shows parsed delta (e.g., `add_output(normalized)`)
- Shows structural diff (added/removed steps and outputs)

### Versions (left panel, Versions tab)
- List of all plan versions in the session
- Click a version to view its graph
- Diff between last two versions shown

## API Endpoints

The UI communicates with a local JSON API:

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/plan` | Plan a goal (`{"goal": "..."}`) |
| POST | `/api/refine` | Refine current plan (`{"request": "..."}`) |
| GET | `/api/versions` | List plan versions |
| GET | `/api/version/:id` | Get a specific version |
| GET | `/api/diff` | Diff between last two versions |

## Limitations

- Local only (no auth, no persistence)
- Session state resets on restart
- No execution/trace display yet (planned)
- Graph layout is simple top-down (no advanced positioning)
