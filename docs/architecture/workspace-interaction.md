# Three-panel workspace interaction model

## Design question

How should Agent Hub adapt the useful parts of the Codex and VS Code workspace pattern while making durable, project-owned engineering Artifacts more prominent than they are in a coding chat client?

A throwaway UI prototype was used to compare the alternatives. Its validated direction is preserved on branch `prototype/workspace-layout` at commit `b3e8c60`; it is a design source, not production application code.

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

### D. Project-scoped workbench

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ Agent Hub  [selected Project ▾]                              Project status │
├────────┬──────────────────┬────────────────────────┬────────────────────────┤
│ view   │ current view     │ Thread chat            │ Artifact host          │
│ rail   │ Chats list       │                        │ trusted host chrome    │
│        │ Artifacts list   │                        │ ┌────────────────────┐ │
│ Chat   │ Sources list     │                        │ │ sandboxed MCP App  │ │
│ Art.   │ Plugins/config   │                        │ │ iframe             │ │
│ Source │ or plugin view   │                        │ └────────────────────┘ │
└────────┴──────────────────┴────────────────────────┴────────────────────────┘
```

Project selection sits above the workspace. The activity rail changes the project-scoped navigation view rather than mixing every collection into one tree. A Plugin may contribute a rail view when it provides a substantial workspace surface, but Plugins do not receive an icon automatically.

## Decision

Adopt alternative D: a project-scoped, chat-centred workbench with an explicit Artifact focus mode.

The product borrows the stable navigation/chat/inspector structure from Codex and VS Code, but differs in two important respects: Project selection is above the workspace, and the right workspace is Project-persistent and can expand into the primary surface because Artifacts are first-class project work products rather than transient tool output.

## Desktop behavior

### Top: Project selection

- Selects the active Project before the user navigates Chats, Artifacts, Sources, or Plugins.
- Changing Project changes the scope of every workspace view.
- An Artifact from one Project is never carried visually into another.

### Left: Project-scoped activity rail and navigator

- Provides separate core views for Chats, Artifacts, Sources, and Plugin management.
- The adjacent navigator shows only the collection or controls for the selected rail view.
- Exposes enabled Plugins and the curated Plugin Catalog through the shared Plugin management view.
- Allows a Plugin to contribute an optional rail view when it provides a substantial, frequently used workspace surface; installation alone does not add an icon.
- Collapses without losing the selected Project, Thread, Artifact, or view.
- Does not pretend that the Virtual Filesystem is the user's computer filesystem.

### Centre: Thread chat

- Remains the default primary surface.
- Shows streamed messages, Agent Run state, tool calls, approvals, errors, and the composer.
- Clearly distinguishes user and assistant messages by alignment, surface treatment, and an accessible sender label. Assistant text renders safe Markdown, including emphasis, lists, links, and fenced code blocks; untrusted HTML is never rendered.
- Selecting or creating a Thread changes this surface but does not automatically close the current Project Artifact.
- Links and tool results can select an Artifact or Source in the right workspace without navigating away from the Thread. Project and Thread-local Scratch file links open safe previews in that workspace without changing their lifecycle.

### Right: Artifact workspace

- Displays the Artifact or Source selected through its corresponding project-scoped rail view; neither is mixed into the message transcript.
- Renders the selected portable Artifact using its MCP App when available, with a generic document/JSON fallback.
- Shows Artifact identity, provenance, validation state, Plugin identity, and trusted controls in host chrome outside the untrusted MCP App iframe.
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

- A newly created Thread has a deterministic provisional title. On its first user message, Agent Hub replaces that title with a normalized, truncated excerpt of that message; this avoids a model call solely to name a conversation. A user rename is authoritative and prevents later automatic replacement.
- Hovering or focusing a Thread exposes a compact overflow menu with Rename and Delete actions. Deletion requires confirmation, removes the Thread from the Project's visible conversation list, and selects the next available Thread (or the empty-chat state) without changing the active Project or open Project Artifact. The Run/checkpoint retention work follows the backend's durable-deletion design rather than being hidden in the menu.
- Artifact creation selects the saved Artifact only after Agent Hub has validated and persisted it.
- An MCP App edit remains pending until the Plugin result passes the Artifact Host Adapter and the updated current document is saved.
- When another Thread changes the open Artifact, the host marks it stale with a compact notice. The user or agent can reload it; live merging is not implied.
- The Artifact catalog is discoverable on demand. Its full contents are not injected into every Thread prompt.
- A Source can open beside chat through the same workspace, but it is never mislabeled as an Artifact.
- A Scratch preview is explicitly Thread-local. It can be opened from that Thread's chat but is never listed in the Project Artifact catalog, promoted to a Project File, or made visible to other Threads merely by previewing it.

## Narrow-screen behavior

Below the usable three-column width, show one primary surface at a time:

- Project navigator becomes a drawer, opened from an explicit title-bar control. It includes the Chats, Artifacts, Sources, and Plugins controls as well as the selected view's navigator controls, including Thread creation and selection.
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
- Artifact focus and the detailed mobile treatment of rich Artifact and Plugin App surfaces.
- Multiple Artifacts visible simultaneously.
- Detachable windows or browser tabs.
- Real-time co-editing and live cross-Thread refresh.
- User-synchronized layout preferences across devices.
