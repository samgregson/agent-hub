# Workspace layout prototype

Throwaway UI prototype for comparing three Agent Hub workspace structures. It is intentionally isolated on the `prototype/workspace-layout` branch and is not production application code.

Run from the repository root:

```sh
make prototype-workspace
```

Then open <http://localhost:4174>. Use the floating switcher or the left/right arrow keys to compare:

The server binds to `127.0.0.1`, so it is reachable only from the same computer and is not shared over the local network.

- `?variant=A` — Conversation Spine
- `?variant=B` — Artifact Studio
- `?variant=C` — Adaptive Workbench
- `?variant=D` — Hub + Plugin Pane, combining A's chat with B's navigation and an iframe-hosted Plugin App

The question is whether the default product should remain chat-centred, become artifact-centred, or support an explicit artifact-focus transition between the two.
