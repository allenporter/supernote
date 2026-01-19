---
name: project_development
description: Use standardized scripts to manage the project environment, testing, and linting.
---

# Project Development Skill

This skill teaches you how to interact with the Supernote-Lite codebase using standardized scripts, following the "Scripts to Rule Them All" pattern.

## Core Scripts

| Script | When to use |
| :--- | :--- |
| `script/bootstrap` | After cloning or when dependencies change. |
| `script/test` | Before submitting changes or to verify functionality. |
| `script/lint` | Before committing to ensure code style and quality. |
| `script/server` | When you need a running server for integration testing or manual verification. |

## Usage Patterns

### Standard Development Flow
1. **Initialize**: `./script/bootstrap`
2. **Implement**: Make your changes to the code.
3. **Lint**: `./script/lint` to check for style issues.
4. **Test**: `./script/test` to run the test suite.
5. **Verify**: `./script/server` to run an ephemeral server for manual checks.

### Notes
- All scripts are located in the `script/` directory at the project root.
- Scripts are designed to be run from the project root.
- The scripts will automatically use `uv` if it is installed, otherwise they will fall back to standard Python tools.
