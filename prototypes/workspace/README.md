# Workspace layout prototype

Throwaway UI prototype for comparing three Agent Hub workspace structures. It is intentionally isolated on the `prototype/workspace-layout` branch and is not production application code.

Run from the repository root:

```sh
make prototype-workspace
```

Then open <http://localhost:4173>. Use the floating switcher or the left/right arrow keys to compare:

- `?variant=A` — Conversation Spine
- `?variant=B` — Artifact Studio
- `?variant=C` — Adaptive Workbench

The question is whether the default product should remain chat-centred, become artifact-centred, or support an explicit artifact-focus transition between the two.
