---
status: accepted
---

# Keep Input Selection source neutral

Input Selection owns bounded filtering, ordering, limiting, and ordered value identity independently of Dataset, Transform, Batch, and MCP storage. Each source owner exposes retained values through its package-root Interface; the Module starting a Run captures the exact selected values and source provenance. This keeps selection rules consistent across sources without making Transforms import Batch Execution, which already depends on Transforms.

Cross-source execution belongs in an owning application Module when that delivery slice begins. `main.py` wires its dependencies but does not resolve source values or decide cardinality. The architecture gate rejects cross-Module implementation imports and directed import cycles, including a future Transform → Batch Execution edge. Selection and invocation cardinality remain separate as decided in [ADR 0008](0008-separate-input-selection-from-invocation-cardinality.md).
