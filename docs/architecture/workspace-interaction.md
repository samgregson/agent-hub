# Three-panel workspace interaction model

## Design question

How should Agent Hub adapt the useful parts of the Codex and VS Code workspace pattern while making durable, project-owned engineering Artifacts more prominent than they are in a coding chat client?

No production UI or throwaway application code was created. The alternatives below are structural wireframes.

## Alternatives considered

### A. Chat-centred inspector

```text
┌──────────────────┬──────────────────────────────┬──────────────────────────┐
│ Projects         │ Thread chat                  │ Artifact workspace       │
│ ├─ Project A     │                              │ [Artifacts] [Sources]    │
│ │  ├─ Thread 1   │ messages                     │                          │
│ │  ├─ Thread 2   │ tool calls                   │ selected Artifact        │
│ │  └─ Plugins    │ approvals                    │ or MCP App               │
│ └─ Project B     │ composer                     │                          │
└──────────────────┴──────────────────────────────┴──────────────────────────┘
```

This is closest to Codex: chat remains the stable centre and work products open in an inspector. It is immediately understandable, but a narrow right panel can undersell a complex calculation or diagram.

### B. Artifact-first engineering bench

```text
┌──────────────────┬────────────────────────────────────────┬────────────────┐
│ Project explorer │ Artifact / MCP App                     │ Chat           │
│                  │                                        │                │
│ files            │ primary engineering work surface       │ compact thread │
│ artifacts        │                                        │                │
│ threads          │                                        │                │
└──────────────────┴────────────────────────────────────────┴────────────────┘
```

This gives calculations and diagrams maximum space but makes the product feel like a document editor with chat attached. It conflicts with the requirement that the agent conversation remain central.

### C. Chat-centred workspace with Artifact focus mode

```text
Default
┌──────────────────┬──────────────────────────────┬──────────────────────────┐
│ Project navigator│ Thread chat                  │ Artifact workspace       │
└──────────────────┴──────────────────────────────┴──────────────────────────┘

Artifact focus
┌─────────┬───────────────────┬──────────────────────────────────────────────┐
│ Nav rail│ compact chat      │ expanded Artifact / MCP App                 │
└─────────┴───────────────────┴──────────────────────────────────────────────┘
```

This keeps chat central by default but lets a calculation, diagram, or report become the main surface temporarily without opening a separate page. It adds one explicit layout state but fits both conversational and engineering work.

## Decision

Adopt alternative C: a chat-centred three-panel workspace with an explicit Artifact focus mode.

The product borrows the stable navigation/chat/inspector structure from Codex and VS Code, but differs in one important respect: the right workspace is Project-persistent and can expand into the primary surface because Artifacts are first-class project work products rather than transient tool output.

## Desktop behavior

### Left: Project navigator

- Shows Projects and, within the selected Project, its Threads.
- Exposes enabled Plugins and access to the curated Plugin Catalog as Project configuration.
- Collapses to a narrow rail without losing the selected Project or Thread.
- Does not pretend that the Virtual Filesystem is the user's computer filesystem.

### Centre: Thread chat

- Remains the default primary surface.
- Shows streamed messages, Agent Run state, tool calls, approvals, errors, and the composer.
- Selecting or creating a Thread changes this surface but does not automatically close the current Project Artifact.
- Links and tool results can select an Artifact or Source in the right workspace without navigating away from the Thread.

### Right: Artifact workspace

- Has top-level `Artifacts` and `Sources` views; these are not mixed into the message transcript.
- Renders the selected portable Artifact using its MCP App when available, with a generic document/JSON fallback.
- Shows provenance and current-version status in host chrome outside the untrusted MCP App iframe.
- Supports collapsed, split, and focus states.
- Keeps the selected Artifact open when switching Threads inside the same Project because the Artifact belongs to the Project.
- Clears or restores an appropriate selection when switching Projects; an Artifact from one Project is never carried visually into another.

## Layout state

The shell has three explicit states:

1. `chat`: right workspace closed; chat uses the available centre space.
2. `split`: chat and right workspace are both visible and independently usable.
3. `artifact-focus`: navigation reduces to a rail, chat becomes a compact contextual column, and the Artifact gets most of the width.

Opening an Artifact from chat moves `chat` to `split`. The user—not the Plugin—chooses whether to enter `artifact-focus`. Closing focus returns to the prior split sizes.

Panel sizes and collapse state are presentation preferences. They may be kept locally per browser initially and do not belong in Project domain data. The selected Project Artifact is workspace state and should survive Thread switches within that Project.

## Thread and Artifact interaction

- Artifact creation selects the saved Artifact only after Agent Hub has validated and persisted it.
- An MCP App edit remains pending until the Plugin result passes the Artifact Host Adapter and the new document version is saved.
- When another Thread changes the open Artifact, the host marks it stale with a compact notice. The user or agent can reload it; live merging is not implied.
- The Artifact catalog is discoverable on demand. Its full contents are not injected into every Thread prompt.
- A Source can open beside chat through the same workspace, but it is never mislabeled as an Artifact.

## Narrow-screen behavior

Below the usable three-column width, show one primary surface at a time:

- Project navigator becomes a drawer.
- Chat and Artifact workspace become peer routes/tabs with explicit back navigation.
- Opening an Artifact moves to the Artifact surface while preserving Thread scroll and draft state.
- Approvals that block an Agent Run remain reachable from both surfaces.
- No essential operation depends on drag resizing, hover, or a permanently visible side panel.

## Accessibility and interaction constraints

- Resizers are keyboard operable and expose separator semantics.
- Collapse/focus actions have visible controls and keyboard shortcuts.
- Focus returns predictably when a panel closes.
- Host chrome clearly distinguishes trusted Agent Hub controls from sandboxed Plugin UI.
- Layout changes do not discard unsent chat drafts or unsaved Plugin UI state without warning.

## Deferred questions

- Exact visual styling, dimensions, icons, animation, and breakpoint values.
- Multiple Artifacts visible simultaneously.
- Detachable windows or browser tabs.
- Real-time co-editing and live cross-Thread refresh.
- User-synchronized layout preferences across devices.
