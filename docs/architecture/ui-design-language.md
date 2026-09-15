# UI design language and shared primitives

## Purpose

Agent Hub is a workbench, not a collection of unrelated screens. The visual
language should make persistent Project context, conversational authorship,
trusted host controls, and untrusted Plugin surfaces easy to distinguish while
keeping the application calm enough for technical work.

This is an implementation contract, not a finished visual-design specification.
It establishes reusable foundations without introducing an application-wide
component library before the product has enough repeated needs to justify one.

## Foundations

Global CSS owns named tokens for colour, typography, spacing, radii, borders,
focus treatment, and semantic states such as selected, pending, destructive,
and error. Module CSS consumes those tokens rather than defining competing
values for the same role.

The initial visual hierarchy is:

1. Project context and navigation are quiet but continuously visible.
2. Conversation authorship is immediately scannable: user and assistant
   messages are distinct, with a readable sender label for assistive technology.
3. Agent activity, approvals, and errors are explicit states, not incidental
   prose in the transcript.
4. Trusted Agent Hub controls sit outside sandboxed Plugin UI and use distinct
   host chrome.

## Reusable primitives

`apps/web/src/shared/ui/` owns only generic presentation primitives with no
Project, Thread, Artifact, Plugin, or agent vocabulary. It currently provides
the following foundations; the set grows only when a behaviour is genuinely
repeated:

- `Menu`: accessible trigger, focus management, and dismiss behaviour for
  compact overflow actions;
- `Markdown`: safe rendering policy for model and user-visible rich text.

`Button`, `IconButton`, `Panel`, and `EmptyState` are candidates, not implied
requirements. They should be extracted only after the corresponding local
patterns have stabilised in more than one product module.

Modules compose these primitives into product behaviour. For example, the
Workspace Module owns Thread selection and deletion, while a generic Menu owns
only menu mechanics. assistant-ui remains the conversation/runtime primitive;
Agent Hub supplies the message presentation components required by its visual
language rather than reimplementing assistant-ui state or streaming.

## Interaction requirements

- Every hover-only affordance has a keyboard-focus and accessible-name path.
- Destructive actions require confirmation and use a destructive visual state.
- User-entered and model-produced text is rendered as safe Markdown without
  arbitrary HTML execution.
- Icons supplement, rather than replace, text labels or accessible names.
- Module CSS may define local layout, but uses global tokens for shared visual
  roles.
- Do not create a catch-all component collection. A new shared primitive needs
  at least two stable consumers or a documented cross-application accessibility
  concern.

## Initial implementation order

1. Introduce global tokens and use them in the workspace and agent-message
   surfaces.
2. Add safe Markdown presentation and clear user/assistant messages through
   assistant-ui's rendering hooks.
3. Add the accessible generic overflow Menu and use it for Thread actions.
4. Extract further primitives only after repeat use appears in Artifacts,
   Sources, or Plugin management.
