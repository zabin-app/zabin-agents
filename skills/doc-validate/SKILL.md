---
name: doc_validate
description: Validates project documentation for structural compliance and content boundary violations. Audits ARCHITECTURE.md, CODE_STANDARDS.md, DEVELOPMENT.md, and REVIEW_FOCUS.md against document schemas. Triggers on "doc-validate", "validate docs", "audit docs", "check docs".
---

# Doc Validate

Audit project documentation for structural compliance and content boundary violations. This is a **read-only** skill — it reports findings but does not fix them.

## When to Use

- After implementation waves complete (spot check)
- Periodically as a documentation health check
- Before major releases
- When documentation drift is suspected
- After manual doc edits

## Before Starting (Mandatory)

1. Read `~/.agents/skills/doc-validate/schemas.md` for content boundary rules
2. Identify the project's `docs/` directory

## Workflow

### Step 1: Discover

Find all documentation files using your file-listing/glob tool:

```
docs/*.md
docs/**/*.md
```

### Step 2: Classify

**Determine pattern:**
- If `docs/` contains files like `<SUBSYSTEM>_ARCHITECTURE.md` → **hub-and-spoke**
- If only `ARCHITECTURE.md`, `CODE_STANDARDS.md`, `DEVELOPMENT.md` directly → **flat**

**Classify each file:**
- **Managed** (core docs): ARCHITECTURE.md, CODE_STANDARDS.md, DEVELOPMENT.md, REVIEW_FOCUS.md + subsystem variants, and the repo-root agent instructions file (e.g. `AGENTS.md`/`CLAUDE.md`, whichever exists)
- **Unmanaged**: TESTING.md, CONFIGURATION.md, KEYBINDINGS.md, IDEAS.md, etc.

Only validate managed docs. Report unmanaged docs as inventory only.

### Step 3: Validate Structure

For each managed doc, check against the schema in `schemas.md`:

**Required sections present?**
- ARCHITECTURE: Overview, Module Structure, Layer Dependencies, Data Flow, Key Types
- CODE_STANDARDS: Language Idioms, Error Handling, Naming Conventions, Anti-patterns, Testing Patterns
- DEVELOPMENT: Prerequisites, Build Commands, Run Commands, Test Commands, Environment Setup
- REVIEW_FOCUS: Review Priorities, Known Hot Spots, Severity Calibration

Section names may vary (e.g., "Build" vs "Build Commands") — match on intent, not exact titles.

**Prohibited sections present?**
- Check for section headers that indicate content from the wrong doc type

### Step 4: Validate Content Boundaries

Scan each managed doc for content that belongs elsewhere.

**ARCHITECTURE.md violations:**
- Code fences with language tags (` ```rust `, ` ```typescript `, ` ```python `, ` ```go `, ` ```dart `, ` ```java `) containing more than 5 lines → code sample belongs in CODE_STANDARDS
- Lines containing build/run commands: `cargo build`, `cargo test`, `npm run`, `npm install`, `docker compose`, `docker build`, `make`, `flutter run`, `go build`, `gradle` → belongs in DEVELOPMENT
- Sections with titles matching: "Naming", "Conventions", "Anti-pattern", "Idiom", "Code Style", "Coding Standard" → belongs in CODE_STANDARDS

**CODE_STANDARDS.md violations:**
- Sections with titles matching: "Architecture", "Module Structure", "Layer Dependencies", "Data Flow", "System Design", "Component Overview" → belongs in ARCHITECTURE
- Lines containing build/run commands (same list as above) → belongs in DEVELOPMENT
- ASCII box-and-arrow diagrams describing module relationships → belongs in ARCHITECTURE

**DEVELOPMENT.md violations:**
- Sections with titles matching: "Naming", "Conventions", "Anti-pattern", "Idiom", "Code Style", "Coding Standard" → belongs in CODE_STANDARDS
- Sections with titles matching: "Architecture", "Module Structure", "Layer Dependencies", "Data Flow" → belongs in ARCHITECTURE
- Code fences with language tags (not `bash`/`shell`/`sh`/`console`/`toml`/`yaml`/`json`/`env`) containing function/struct/class definitions → code samples belong in CODE_STANDARDS

**REVIEW_FOCUS.md violations:**
- Sections with titles matching: "Naming", "Conventions", "Anti-pattern", "Code Style" → belongs in CODE_STANDARDS
- Sections with titles matching: "Architecture", "Module Structure", "Data Flow" → belongs in ARCHITECTURE
- Lines containing build/run commands (same list as above) → belongs in DEVELOPMENT
- Bullets naming no project-specific module, path, type, or flow (generic review advice) → Warning: prune, reviewers already know it

### Step 4.5: Validate Size, Altitude & Duplication

Run `wc -l` on every managed doc and apply the budgets from `schemas.md` (*Size Budgets & Compaction*):

- **Size:** flat/spoke core doc > 500 lines → **Error** (compact or split); > 350 → **Warning**. Hub-and-spoke index > 150 → Error. `REVIEW_FOCUS.md` > 200 → Error, > 150 → Warning. Root agent-instructions file > 100 → Error, > 80 → Warning.
- **Altitude leak (prose):** scan for backtick-quoted private symbols described over multiple sentences, step-by-step algorithm/control-flow/idempotency descriptions, and per-file/per-widget "tours" → **Warning** with the line range.
- **Changelog leak:** grep for `Phase ` + a digit, `previously`, `was changed`, `collapsed`, `refactored to`, `deprecat` → **Warning** (historical narrative belongs in git).
- **Deep nesting:** count `####`/`#####` headings under each module; a module with many → **Warning** (deep-dive; collapse or move to a spoke).
- **Duplicate sections:** list heading titles; same/near-same title twice → **Error**.
- **Cross-doc / root-doc duplication:** prose in the root agent-instructions file (or one core doc) that restates another core doc instead of linking → **Warning**.

When several of these fire on one doc, recommend a `docs-sync` rebuild rather than piecemeal fixes.

### Step 5: Validate Cross-References (Hub-and-Spoke Only)

For hub-and-spoke projects:
- Each index doc link resolves to an existing file
- Every subsystem-specific doc is linked from its index
- Subsystem naming is consistent (same prefix across all three doc types)

### Step 6: Report

Output the structured audit report.

## Output Format

```markdown
## Documentation Audit Report

**Project:** <project name>
**Pattern:** Flat / Hub-and-Spoke
**Managed Docs:** <count>
**Unmanaged Docs:** <count>
**Overall Status:** PASS / VIOLATIONS FOUND

### Document Inventory

| File | Type | Managed | Status |
|------|------|---------|--------|
| `docs/ARCHITECTURE.md` | Architecture | Yes | PASS/FAIL |
| `docs/CODE_STANDARDS.md` | Code Standards | Yes | PASS/FAIL |
| `docs/DEVELOPMENT.md` | Development | Yes | PASS/FAIL |
| `docs/REVIEW_FOCUS.md` | Review Focus | Yes | PASS/FAIL |
| `docs/TESTING.md` | Testing | No | (not audited) |

### Structural Issues

| File | Issue | Severity |
|------|-------|----------|
| `docs/<file>` | Missing required section: <section> | Warning |
| `docs/<file>` | Contains prohibited section: <section> | Error |

### Content Boundary Violations

| File | Line(s) | Content Found | Belongs In | Severity |
|------|---------|--------------|------------|----------|
| `docs/ARCHITECTURE.md` | 45-60 | Rust code sample (15 lines) | CODE_STANDARDS.md | Error |
| `docs/ARCHITECTURE.md` | 112 | `cargo build --release` | DEVELOPMENT.md | Warning |
| `docs/CODE_STANDARDS.md` | 23-40 | "Module Structure" section | ARCHITECTURE.md | Error |

### Size & Altitude Issues

| File | Lines | Cap | Issue | Severity |
|------|-------|-----|-------|----------|
| `docs/ARCHITECTURE.md` | 1457 | 500 | Over hard cap — split to hub-and-spoke | Error |
| `docs/ARCHITECTURE.md` | 546 | — | Duplicate `## Project Context` section | Error |
| `docs/ARCHITECTURE.md` | 162-448 | — | Module deep-dive / altitude leak (function & field-level prose) | Warning |
| `docs/ARCHITECTURE.md` | — | — | "Phase N" changelog narrative throughout | Warning |
| root agent-instructions file | 240 | 100 | Over cap — duplicates core-doc content instead of linking | Error |

### Cross-Reference Issues (Hub-and-Spoke)

| Index File | Link | Issue |
|-----------|------|-------|
| `docs/ARCHITECTURE.md` | `BACKEND_ARCHITECTURE.md` | File not found |

### Summary

- **Structural issues:** <count>
- **Content boundary violations:** <count>
- **Size & altitude issues:** <count>
- **Cross-reference issues:** <count>

### Recommendations

1. <Specific actionable recommendation>
2. <Specific actionable recommendation>

To fix isolated violations, dispatch the `doc_maintainer` agent:
"Dispatch doc_maintainer to fix documentation violations found by doc_validate"

When a doc is over its hard cap or has several altitude/duplication issues, a piecemeal fix won't help — run a full rebuild instead:
"Load and run the docs-sync skill to reconstruct the docs compactly from the current codebase"
```

## Severity Definitions

| Severity | Meaning |
|----------|---------|
| **Error** | Clear content boundary violation — content is in the wrong document |
| **Warning** | Borderline content — may be acceptable in context but worth reviewing |
| **Info** | Structural suggestion — missing optional section or improvement opportunity |

## Boundaries

- **DO** read all managed documentation files thoroughly
- **DO** check every content boundary rule from schemas.md
- **DO** report specific line numbers for violations
- **DO** provide actionable recommendations
- **DO NOT** edit any files (read-only audit)
- **DO NOT** validate unmanaged docs (TESTING, CONFIGURATION, etc.)
- **DO NOT** validate source code files
