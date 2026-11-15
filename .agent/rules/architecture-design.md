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

3. **Fix Root Model Gaps Rather Than Working Around Them in Subclasses**:
   - If the existing base abstraction or state model cannot express a new requirement, pause and ask what single concept is missing from the core model. Extend the base invariant once rather than writing bespoke overrides in every implementation.

4. **Prefer Idiomatic Library Primitives Over Custom Ceremony**:
   - Before writing custom serializers, validators, or wrapper subclasses, check what the underlying library (`mashumaro`, `sqlalchemy`, `aiohttp`, stdlib) already supports natively (e.g., `field_options(serialize=str)` rather than custom serializer/deserializer pairs and wrapper VOs).
   - During code or adversarial reviews, fix genuine security boundaries and state-invariant bugs; reject fixes that add speculative defensive bloat for contrived inputs.

5. **Never Bypass Architectural Conformance Tests or Legacy Allowlists**:
   - When a schema or architecture conformance test fails (e.g., `test_init.py` multi-user primary-key and scoping invariants), treat it as a hard design error in the new code—never add new tables or modules to legacy exemption allowlists (`TABLES_WITHOUT_USER_ID_IN_PK_ALLOWLIST`, `TABLES_WITHOUT_USER_ID_ALLOWLIST`, `UNSCOPED_UNIQUE_CONSTRAINT_ALLOWLIST`) to make the test pass.
   - If a new table genuinely appears to conflict with an invariant, stop and ask the user rather than modifying the allowlist.
