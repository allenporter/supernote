# Code Review & Engineering Style Guide

This document establishes the project's engineering, architectural, coding, and testing principles. It serves as the definitive reference guide for code design, pull request reviews, and API refactoring.

---

## Core Engineering Principles

### 1. Strict Abstraction Boundaries (Zero Leaky Abstractions)
High-level component interfaces must never expose low-level wire formats, transport tokens, or protocol artifacts to upper layers.

* **Domain-Driven Signatures**: Methods should speak in domain models and standard exception semantics (`None` on success, typed exceptions on failure).
* **No Wire Token Leaks**: Callers and test suites should never be forced to inspect protocol literals (such as `"Received"`, `"true"`, or raw status strings) to determine success or failure.
* **Narrow Exception Scoping**: Catch only specific, expected exceptions (e.g. `(json.JSONDecodeError, ValueError, TypeError, KeyError)`). Never use bare `except Exception:` when handling payload parsing or decoding.

---

### 2. Orthogonality & State Isolation
Independent operations must not share state or queue mechanisms that create side effects or race conditions.

* **Decoupled Control vs Data Streams**: Control operations (health checks, transport heartbeats, background monitoring) must be completely decoupled from primary application data streams.
* **Isolated Queues**: Maintain separate, dedicated queues per event category so background monitoring never pollutes, delays, or races with application event loops.
* **Explicit Dependency Injection**: Classes and setup functions must accept dependencies explicitly via parameters rather than reaching into global containers (`app["config"]`) or global mutable state.

---

### 3. Defensive API Ergonomics (One Canonical Entry Point)
APIs should be minimal, intuitive, predictable, and impossible to misuse.

* **Canonical Operations**: Provide a single, canonical way to perform every operation. Avoid cluttering public interfaces with redundant wrapper methods.
* **Deterministic Return Types**: Avoid ambiguous union return types (e.g. `str | DomainModel`). Every method should return a clear, deterministic type.
* **Idiomatic Streaming**: Expose event streams via standard Python async generators (`async for msg in client.messages():`).

---

### 4. Linear Control Flow & Guard-Clause Flatness
Code should read straight down from top to bottom with minimal cognitive load and zero unnecessary nesting.

* **Flat Guard Clauses**: Handle error conditions and invalid states immediately using guard clauses and early returns. Keep the primary execution path unindented at the root level.
* **Error Emission Helpers**: Extract repetitive multiline error formatting or emission blocks into concise helper functions to keep event handlers flat and readable.
* **Clean Hygiene**: Place all imports at the top of the file (no inline/function-level imports). Do not use numbered step comments (`# 1.`, `# 2.`). Use explicit package `__all__` exports.
* **Relative Documentation Links Only**: Markdown documentation and skill definitions must use relative repository links (`[link](docs/foo.md)`) instead of absolute `file://` filesystem URIs.

---

### 5. High-Signal, Specification-Driven Testing
Test suites should mirror production modules 1:1 and validate complete behavioral contracts with zero setup noise.

* **1:1 Module Parity**: Every implementation file must have a corresponding test file matching its exact module name.
  * `supernote/models/socket.py` $\rightarrow$ `tests/models/test_socket.py`
  * `supernote/server/socket_auth.py` $\rightarrow$ `tests/server/test_socket_auth.py`
  * `supernote/server/socket.py` $\rightarrow$ `tests/server/test_socket.py`
* **Full-Structure Assertions**: Assert on complete dictionary structures (`assert data_dict == {...}`) rather than checking individual keys piecemeal.
* **Fixture Pre-Wiring**: Test functions should receive ready-to-use client and service instances via reusable fixtures rather than imperatively constructing host URLs and objects inside every test.
* **High-Signal Focus**: Focus test coverage on serialization roundtrips, cryptographic/JWT signature verification, error paths, and multi-client isolation rather than testing framework constants.
