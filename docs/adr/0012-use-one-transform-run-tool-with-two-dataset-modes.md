---
status: accepted
---

# Use one Transform run tool with two Dataset modes

A user or agent runs a Transform Definition on a Dataset through one tool with an explicit execution mode: invoke once with the Dataset's ordered Records, or invoke independently for each Record. The first mode lets Python filter, sort, aggregate, or otherwise work across Records and produces one Transform Run output; the second retains independent per-Record outcomes, failures, and provenance in a Batch Result Set. The tool's review plan shows the captured Dataset version and Records, mode, invocation count, and output shape before a durable start. An agent start still requires approval.

This replaces ADR 0008's rejection of a Dataset-wide versus per-Record choice as the primary Transform action. There is no separate “selected collection” mode for a Dataset Transform: a Dataset-wide invocation receives its captured Records and the Transform may select among them in Python. Input Selection remains useful for Bindings and values derived from retained operation outputs; those sources should enter the same run interface when supported, without silently applying preview defaults. The host keeps the current bounded execution, immutable snapshots, and explicit output-save rules. Existing direct, selected, and Batch execution paths are implementation seams to consolidate behind this interface, rather than separate concepts the user or agent must discover.
