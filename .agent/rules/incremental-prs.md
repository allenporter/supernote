---
trigger: always_on
description: Keep changes and pull requests small (~200 LoC target) and decompose multi-part features before coding.
---

# Incremental Changes & PR Sizing

1. **Decompose Multi-Part Issues Before Implementing**:
   - When an issue or feature spans multiple layers (schema, API, client, multiple domain services) or exceeds ~300 lines of production code, **stop and agree on an incremental PR breakdown first** rather than implementing everything in a single pass.
   - Sequence foundational layers first, followed by one domain vertical per PR, and implement **one slice at a time** unless explicitly asked to prototype end-to-end.

2. **Target ~200 LoC Per PR (Avoid ~1k LoC Diffs)**:
   - Aim for **~150–300 lines of production code** per PR (smaller is even better, e.g., 20–100 LoC when a change stands on its own). Anything approaching 1,000 LoC is too large to review effectively.
   - Every slice must build, migrate cleanly, and pass lint/type/unit checks independently with zero forward dependencies.
