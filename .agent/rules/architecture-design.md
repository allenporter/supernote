---
trigger: always_on
description: Universal software design heuristics for abstraction boundaries, role cohesion, and interface design.
---

# Software Design Heuristics

Before adding a method, parameter, or dependency to an interface or base class, apply these checks:

1. **Preserve Role Cohesion (No Downward Leakage of Caller Concerns)**:
   - Ask: *"Is this part of this abstraction's intrinsic responsibility, or is it a caller's storage, scheduling, or transport concern?"*
   - An implementation should not need to import or understand its caller's persistence schema, query builder, or orchestration mechanics.

2. **Expose Intrinsic Facts, Not Caller Mechanisms**:
   - When a driver or caller needs to coordinate across implementations, prefer exposing simple, declarative properties on the interface (identity, capabilities, version, status) so the caller can run its own logic generically—rather than adding procedural hooks that force each implementation to build pieces of the caller's work.

3. **Fix Root Model Gaps & Generalize Existing Platform Mechanisms**:
   - If the existing base abstraction or state model cannot express a new requirement, pause and ask what single concept is missing from the core model. Extend the base invariant once rather than writing bespoke overrides in every implementation.
   - Before adding a parallel ad-hoc execution path (a fire-and-forget `asyncio.create_task` runner, a cloned dry-run pipeline, or a duplicate blob/upload helper), check whether an existing platform mechanism (`ProcessorService`, the real compile pipeline, `BlobStorage`, `FileService`) should be generalized or parameterized instead. When a user questions whether two paths should share code, audit the duplication skeptically rather than reflexively defending just-written code.

4. **Prefer Idiomatic Library Primitives Over Custom Ceremony**:
   - Before writing custom serializers, validators, or wrapper subclasses, check what the underlying library (`mashumaro`, `sqlalchemy`, `aiohttp`, stdlib) already supports natively (e.g., `field_options(serialize=str)` rather than custom serializer/deserializer pairs and wrapper VOs).
   - During code or adversarial reviews, fix genuine security boundaries and state-invariant bugs; reject fixes that add speculative defensive bloat for contrived inputs.

5. **Never Bypass Architectural Conformance Tests or Legacy Allowlists**:
   - When a schema or architecture conformance test fails (e.g., `test_init.py` multi-user primary-key and scoping invariants), treat it as a hard design error in the new code—never add new tables or modules to legacy exemption allowlists (`TABLES_WITHOUT_USER_ID_IN_PK_ALLOWLIST`, `TABLES_WITHOUT_USER_ID_ALLOWLIST`, `UNSCOPED_UNIQUE_CONSTRAINT_ALLOWLIST`) to make the test pass.
   - If a new table genuinely appears to conflict with an invariant, stop and ask the user rather than modifying the allowlist.

6. **Ground Analysis in Verified Facts & Take a Clear Stance**:
   - In research and architectural reviews, explicitly separate verified code facts from unverified documentation or inference, and re-verify tool/CLI availability (e.g. `which gh && gh auth status`) before reporting an environment block.
   - When evaluating design options, define any referenced option inline, commit to one clear recommendation anchored to the concrete use case, and avoid hedging with alternatives that conflict with project principles.

7. **Treat Empirical AI/Quality Claims as Hypotheses & Run Fair Evals**:
   - For empirical questions (LLM synthesis quality, prompt design, chunking, ordering, retrieval/ranking), never dismiss a user's alternative or assert an untested intuition as fact—label it explicitly as an unverified hypothesis until measured.
   - Always include the user's proposed alternative as an explicit head-to-head arm in the same experiment alongside the current baseline; never run a single arm and declare victory.
   - Build evals that stress real production constraints (scale, noise ratio, candidate/context limits, undated or messy inputs). If a toy dataset trivially hits 100% on the first pass, treat the dataset as too easy rather than proof that the design is optimal.
   - Pair aggregate eval metrics with 1–2 concrete input/output examples so the reader can judge actual output quality directly.
   - Be transparent about eval limits: note single-run LLM variance and synthetic-dataset bias honestly, and keep raw run artifacts/logs inspectable so every reported metric is verifiable.
