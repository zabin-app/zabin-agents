# Document Schemas

Content boundary definitions for project documentation. This is the single source of truth referenced by the `doc_maintainer` agent and the `doc_validate` skill.

---

## Managed Set and Content Ownership

The managed set contains four document types, all subsystem variants of the first three, and both root instruction files:

- `docs/ARCHITECTURE.md`, `docs/CODE_STANDARDS.md`, `docs/DEVELOPMENT.md`, `docs/REVIEW_FOCUS.md`;
- `docs/<SUBSYSTEM>_ARCHITECTURE.md`, `docs/<SUBSYSTEM>_CODE_STANDARDS.md`, `docs/<SUBSYSTEM>_DEVELOPMENT.md`;
- root `AGENTS.md` and root `CLAUDE.md`.

| Content type | Canonical owner |
|---|---|
| System overview, modules, dependencies, flows, minimal key types | `ARCHITECTURE.md` |
| Idioms, naming, error handling, tests, coding anti-patterns | `CODE_STANDARDS.md` |
| Prerequisites, environment, build/run/test commands, CI, troubleshooting | `DEVELOPMENT.md` |
| Project-specific review priorities, hot spots, severity calibration | `REVIEW_FOCUS.md` |
| Repository-specific agent guardrails and documentation routing | root `AGENTS.md` |
| Compatibility import only | root `CLAUDE.md` |

A fact appears in its owner once. Every other managed file links to the owner rather than restating it. In particular, commands live only in `DEVELOPMENT.md` and repository guardrails live only in root `AGENTS.md`.

---

## Size Budgets & Compaction

Core docs are **maps, not the territory**. They have hard size budgets, because an unbounded doc is one nobody reads and the `doc_maintainer` keeps appending to. Budgets are measured in lines (`wc -l`).

| Doc | Target | Hard cap | Over cap → |
|-----|--------|----------|------------|
| `ARCHITECTURE.md` / `CODE_STANDARDS.md` / `DEVELOPMENT.md` (flat, or a hub-and-spoke spoke) | ≤ 350 | **500** | compact, or split to hub-and-spoke |
| Hub-and-spoke index doc | ≤ 120 | 150 | move detail into spokes |
| `REVIEW_FOCUS.md` | ≤ 150 | 200 | prune stale hot spots; generic advice goes nowhere (reviewers already know it) |
| `AGENTS.md` | ≤ 80 | 100 | move commands/content into the owning core doc and link |
| `CLAUDE.md` | one nonblank line | one nonblank line | replace with `@AGENTS.md` |

- **Target** = healthy size. **Hard cap** = a doc over this value is a defect (validator Error). Splitting to hub-and-spoke is the expected remedy once a doc legitimately needs more than 500 lines of content — never let one doc absorb it all.
- Updates should be **net-neutral**: adding a fact means removing what it supersedes. A doc that only ever grows is a process failure.

## Altitude & Duplication Rules (apply to all core docs)

**Altitude.** Core docs describe the *shape* of the system, not its implementation. A statement is **too low-altitude** (belongs in code/comments or a spec, not a core doc) when it:
- names a specific private function, struct field, DB column, or constant as the subject of an explanation;
- walks through an algorithm step by step, or describes control flow / idempotency / recovery semantics;
- enumerates files, widgets, or screens one by one (a "tour" of the code);
- would become wrong if someone renamed a private symbol or reordered internal steps.

Rule of thumb: one module gets a few sentences (responsibility + dependencies + key public types), not a multi-page deep-dive.

**Present tense / no changelog.** Core docs describe the *current* state only. Prohibited: "Phase N", "previously", "was changed to", "collapsed/refactored", migration narratives, deprecation play-by-plays, and dates. That history belongs in git.

**No duplication.** Each fact lives in exactly one managed file; other files cross-reference it. `AGENTS.md` links to the core docs, `DEVELOPMENT.md` owns commands, and `AGENTS.md` owns repository-specific guardrails. `CLAUDE.md` imports `AGENTS.md` and contains nothing else.

---

## Instruction Precedence

Repository documentation never overrides live system, developer, user, or role instructions supplied by the host. Within the repository instruction layer:

1. a path-scoped `AGENTS.md` applies to its subtree and takes precedence over an ancestor `AGENTS.md` for that scope;
2. root `AGENTS.md` is the canonical repository-wide instruction source and routes topic detail to the managed docs;
3. the owning managed doc is canonical for architecture, coding standards, development commands, or review focus, but cannot override an applicable `AGENTS.md` guardrail;
4. root `CLAUDE.md` has no independent authority; it imports root `AGENTS.md` verbatim through the host's supported import directive.

Conflicting copies are defects, not precedence mechanisms. Resolve them by retaining the statement in its canonical owner and replacing other copies with links.

---

## Document Type: AGENTS.md

### Purpose
The canonical repository instruction entry point. It orients an agent, declares repository-specific guardrails, and routes topic detail to the managed docs. It is a lean index, not a copy of those docs.

### Required Content
- One-paragraph project description.
- Links to all four managed doc types that exist for the selected structure.
- A pointer to `DEVELOPMENT.md` for commands, without copying the commands.
- Repo-specific agent guardrails that live nowhere else.

### Prohibited Content
- Commands, command fences, or environment setup copied from `DEVELOPMENT.md`.
- Architecture inventories, coding standards, or review guidance copied from a core doc.
- Generic platform, model, provider, or transport instructions supplied by a higher authority.
- A second copy of a guardrail already present in a path-scoped `AGENTS.md` for the same scope.

### Detection Heuristics (for validation)
- Length > 100 lines → almost certainly duplicating doc content.
- Headed sections that mirror core-doc sections (e.g. "Module Structure", "Naming Conventions", "Build Commands") with their own prose rather than a link → duplication.
- Shell fences or recognized build/run/test commands → command duplication; move them to `DEVELOPMENT.md`.
- Guardrail prose repeated in another managed file → duplication; keep it only in `AGENTS.md`.

---

## Document Type: CLAUDE.md

### Purpose

A compatibility wrapper for hosts that discover `CLAUDE.md`. It delegates entirely to canonical root `AGENTS.md`.

### Required Content

The sole nonblank line is exactly:

```text
@AGENTS.md
```

### Prohibited Content

Everything else: frontmatter, headings, prose, commands, guardrails, links tables, additional imports, and client-specific alternatives.

### Detection Heuristics (for validation)

- Strip blank lines and line endings. The remaining line array must equal `["@AGENTS.md"]`.
- A missing root `AGENTS.md` makes the wrapper target unresolved.
- Any content shared with `AGENTS.md` or a core doc is duplication in addition to a wrapper-shape violation.

---

## Document Type: ARCHITECTURE.md

### Purpose
System design documentation. Describes WHAT the system is and HOW its parts relate.

### Required Sections
- **Overview / TL;DR** — Brief system description
- **Module / Component Structure** — Inventory of modules, crates, packages with responsibilities
- **Layer Dependencies** — Which modules depend on which, dependency rules, compile-time enforcement
- **Data Flow** — How data moves through the system (request paths, event flows, pipelines)
- **Key Types / Interfaces** — Central types, traits, interfaces (minimal signatures only — full code goes in CODE_STANDARDS)

### Optional Sections
- Architecture diagrams (ASCII art, text descriptions)
- Design decision records
- Future architecture / planned changes
- Component interaction tables
- Subsystem deep-dives

### Prohibited Content
- **Code samples** beyond minimal type/trait signatures (move to CODE_STANDARDS.md)
- **Build, run, or test commands** (move to DEVELOPMENT.md)
- **Coding style rules**, naming conventions, anti-patterns (move to CODE_STANDARDS.md)
- **Configuration details** or environment setup (move to DEVELOPMENT.md or CONFIGURATION.md)
- **Troubleshooting steps** (move to DEVELOPMENT.md)
- **Inline implementation details** — describe the design, not the code

### Detection Heuristics (for validation)
- File length over the hard cap (500 lines) → Error: compact or split to hub-and-spoke
- Code fences with language tags (` ```rust `, ` ```typescript `, etc.) beyond 5 lines → likely violation
- Lines containing `cargo`, `npm run`, `docker`, `make`, `flutter run`, `go build` → build command leak
- Sections titled "Naming Conventions", "Anti-patterns", "Code Style", "Idioms" → style content leak
- **Altitude leak (prose):** sentences whose subject is a specific private function, struct field, DB column, or constant (backtick-quoted `snake_case` symbols described over multiple sentences); step-by-step algorithm / control-flow / idempotency / recovery descriptions; per-file or per-widget "tours" → implementation detail, move to code/comments or a spec doc
- **Changelog leak:** "Phase N", "previously", "was changed/collapsed/refactored", deprecation protocols, dates → historical narrative, belongs in git
- **Deep nesting:** heavy use of `####`/`#####` headings under a single module → that module has become a deep-dive; collapse to a summary or move to a spoke
- **Duplicate sections:** two headings with the same/near-same title → dedupe

---

## Document Type: CODE_STANDARDS.md

### Purpose
Coding conventions, quality expectations, and pattern guidance. Describes HOW to write code in this project.

### Required Sections
- **Language Idioms** — Language-specific best practices (ownership in Rust, hooks in React, etc.)
- **Error Handling Patterns** — How errors should be created, propagated, and handled (with code examples)
- **Naming Conventions** — Casing rules, prefixes, module naming
- **Anti-patterns to Avoid** — Common mistakes with BAD/GOOD code examples
- **Testing Patterns** — Test naming, structure, what to test, test examples

### Optional Sections
- Security coding practices
- Performance guidelines
- Logging standards
- Documentation standards (doc comments, module headers)
- Quality metrics / severity levels
- File size limits and when to split
- Code review red flags

### Prohibited Content
- **System architecture descriptions** — module inventory, layer diagrams, data flow (move to ARCHITECTURE.md)
- **Build, run, or test commands** (move to DEVELOPMENT.md)
- **Module dependency diagrams** or layer boundary descriptions (move to ARCHITECTURE.md)
- **Configuration reference** (move to CONFIGURATION.md)
- **Deployment procedures** (move to DEVELOPMENT.md)

### Detection Heuristics (for validation)
- Sections titled "Architecture", "Module Structure", "Layer Dependencies", "Data Flow", "System Design" → architecture leak
- Lines containing `cargo build`, `npm install`, `docker compose`, `make build` → build command leak
- Dependency diagrams (ASCII box-and-arrow art describing module relationships) → architecture leak

---

## Document Type: DEVELOPMENT.md

### Purpose
Build, run, test, and deploy instructions. Describes HOW to work with the codebase as a developer.

### Required Sections
- **Prerequisites / Dependencies** — Required tools, versions, installation
- **Build Commands** — Debug, release, platform-specific builds
- **Run Commands** — How to start the application (modes, flags)
- **Test Commands** — Unit, integration, e2e test execution
- **Environment Setup** — Environment variables, config files, secrets

### Optional Sections
- Docker / devnet setup
- CI/CD configuration
- Troubleshooting / common issues
- Workflow locations (where plans, tasks, reviews go)
- Dependency management
- Editor / tooling recommendations
- File extension reference
- Runtime and dev dependencies list
- Quality gates checklist (pre-commit checks)

### Prohibited Content
- **Architecture descriptions** — module structure, layer dependencies, data flow (move to ARCHITECTURE.md)
- **Coding style rules** — naming conventions, anti-patterns, idioms (move to CODE_STANDARDS.md)
- **Design pattern explanations** (move to CODE_STANDARDS.md)
- **Feature specifications** or design decisions (move to ARCHITECTURE.md or separate spec docs)
- **Code examples** beyond command-line snippets (move to CODE_STANDARDS.md)

### Detection Heuristics (for validation)
- Sections titled "Naming Conventions", "Anti-patterns", "Idioms", "Code Style", "Coding Standards" → style leak
- Sections titled "Architecture", "Module Structure", "Layer Dependencies", "Data Flow" → architecture leak
- Code fences with language tags (not shell/bash) containing function definitions, structs, classes → code sample leak
- Pattern explanation blocks with BAD/GOOD examples → style content leak

---

## Document Type: CONFIGURATION.md (optional, repository-defined)

### Purpose
An optional fifth core doc, DEVELOPMENT-adjacent: the flag/env-var/config-file reference for a
project's runnable binaries or deployables — precedence chains, config-file schemas, and
security-relevant defaults. Not part of `doc_maintainer`'s mandatory core-four, but recognized
when a repository's own `DOC_POLICY.md` (or equivalent recorded policy) designates it as a
managed doc with its own budget entry.

### Required Sections
- One quick-reference table (flags/env vars) per runnable binary or deployable the repository
  ships.

### Optional Sections
- Config-file schemas, precedence/resolution-order chains, credential/trust models, worked
  deployment recipes, security notes specific to configuration surfaces.

### Prohibited Content
Same as `DEVELOPMENT.md`: architecture descriptions, coding style rules, design pattern
explanations, and non-command code examples beyond config-file snippets.

### Size and structure
Follows the size-discipline ladder in "Size Budgets & Compaction" above using whatever budget the
repository's own `DOC_POLICY.md` records for it (defaulting to the flat/spoke tier when unset).
When it hits its cap at correct altitude, the expected remedy is the same hub-and-spoke escalation
as a core doc: `docs/CONFIGURATION.md` becomes a lean index (quick-reference tables + pointers)
and the detail moves to sibling documents split along a real seam the repository already has —
per binary, per deployable, or per client/server boundary (for example
`CLIENT-CONFIGURATION.md`/`SERVER-CONFIGURATION.md`, or a per-service name). Each satellite is a
managed doc in its own right once declared in `write_files` and recorded in the repository's
`DOC_POLICY.md`; an unlinked satellite is a broken-spoke-link defect exactly as for the core four.

### Detection Heuristics (for validation)
- Same content-boundary and duplication heuristics as `DEVELOPMENT.md`.
- File length over the repository's recorded cap for this doc (or the flat/spoke default if
  unrecorded) → Error: compact or escalate to hub-and-spoke, same as a core doc.
- A satellite doc not linked from `docs/CONFIGURATION.md`'s index → Error: broken spoke link.

---

## Document Type: REVIEW_FOCUS.md

### Purpose
Project-specific review guidance consumed by the review agents (`review-diff` dimensions, `security_reviewer`). Tells reviewers WHERE to look hardest and HOW to calibrate severity **in this project**. It captures curated judgment (hot spots, incident history, trust boundaries) — not anything derivable from the other core docs.

### Required Sections
- **Review Priorities** — Ranked project-specific concerns reviewers should weight first
- **Known Hot Spots** — Modules/paths with a history of regressions or subtle invariants (with WHY each is fragile)
- **Severity Calibration** — What counts as Critical vs Major vs Minor in this project

### Optional Sections
- Security focus (trust boundaries, sensitive data paths — pointers, not a threat model)
- Past incident patterns (the pattern, not the changelog)
- Out of scope (things reviewers should NOT flag here, with rationale)

### Prohibited Content
- **Coding conventions, anti-patterns, style rules** (move to CODE_STANDARDS.md)
- **Architecture descriptions**, module inventories, layer diagrams (move to ARCHITECTURE.md — reference modules by name and link)
- **Build/run/test commands** (move to DEVELOPMENT.md)
- **Generic review advice** that applies to any project ("check for null derefs") — reviewers already know it; only project-specific signal earns a line
- **Historical narrative** — an incident earns a bullet only as a recurring pattern to watch for, not a play-by-play

### Detection Heuristics (for validation)
- File length over the hard cap (200 lines) → Error: prune stale/generic content
- Sections titled "Naming", "Anti-patterns", "Code Style" → style leak
- Sections titled "Architecture", "Module Structure", "Data Flow" → architecture leak
- Lines containing build/run commands (`cargo`, `npm run`, `docker`, `make`) → command leak
- Bullets with no project-specific noun (no module, path, type, or flow named) → generic-advice leak

---

## Normative Validation Fixtures

Validator implementations and manual audits use these minimal fixtures to prove root precedence, wrapper shape, duplication, size, and content-boundary behavior. A fixture may omit unrelated required sections only when the asserted check is isolated; a full audit reports those omissions separately.

| Fixture | Relevant files/content | Expected finding |
|---|---|---|
| Canonical root pair | `AGENTS.md` links to core docs; `CLAUDE.md` is `@AGENTS.md` | Root checks pass |
| Missing canonical root | `CLAUDE.md` imports `@AGENTS.md`; no `AGENTS.md` | Error: missing canonical root and unresolved import |
| Wrapper prose | `CLAUDE.md` contains `@AGENTS.md` plus a heading or command | Error: wrapper-shape violation; duplication when content has another owner |
| Command in root instructions | `AGENTS.md` repeats a command present in `DEVELOPMENT.md` | Error: cross-file command duplication; keep it only in development docs |
| Guardrail outside canonical root | Same repository guardrail in `AGENTS.md` and a core doc | Error: cross-file guardrail duplication; keep it only in `AGENTS.md` |
| Precedence conflict | `AGENTS.md` forbids an operation while a managed doc directs it | Error: contradictory lower-precedence instruction |
| Boundary leak | `ARCHITECTURE.md` contains a build command | Error or Warning according to the architecture rule, with owning doc identified |
| Root over cap | `AGENTS.md` has more than 100 lines | Error; compact to links and unique guardrails |
| Review-focus over cap | `REVIEW_FOCUS.md` has more than 200 lines | Error; prune generic or stale material |
| Broken spoke link | Hub index links to a missing subsystem doc | Error: unresolved managed-doc link |

Portability fixtures also scan the documentation-policy sources themselves. They fail if an orchestration example contains a concrete provider/model name, a transport-qualified tool name, or a client-specific spawn/load command instead of registered semantic host capabilities.

---

## Flat vs Hub-and-Spoke

### When to Use Flat
- Single system or application
- One primary language/framework
- One build target
- Small to medium project

Result: Three files directly in `docs/`:
```
docs/
  ARCHITECTURE.md
  CODE_STANDARDS.md
  DEVELOPMENT.md
```

### When to Use Hub-and-Spoke
- Multi-system project (e.g., backend + frontend + mobile)
- Different tech stacks per subsystem
- Independent build targets per subsystem
- Large project where a single doc per type would exceed ~500 lines

Result: Index docs + subsystem-specific docs:
```
docs/
  ARCHITECTURE.md          ← index with shared overview + links
  CODE_STANDARDS.md        ← index with shared rules + links
  DEVELOPMENT.md           ← index with shared setup + links
  BACKEND_ARCHITECTURE.md
  BACKEND_CODE_STANDARDS.md
  BACKEND_DEVELOPMENT.md
  FRONTEND_ARCHITECTURE.md
  FRONTEND_CODE_STANDARDS.md
  FRONTEND_DEVELOPMENT.md
```

### Detection Criteria (for scaffolding)
- Multiple manifest files (e.g., `Cargo.toml` + `package.json`, or workspace with distinct subsystems)
- Multiple directories with their own build configs
- Existing subsystem-specific docs
- Project README mentions distinct systems/components with different tech stacks

### Naming Convention
- Subsystem prefix: UPPERCASE, descriptive (e.g., `BIFROST`, `DASHBOARD`, `BACKEND`, `FRONTEND`, `API`)
- Format: `<SUBSYSTEM>_<DOCTYPE>.md`
- Index docs keep the base names: `ARCHITECTURE.md`, `CODE_STANDARDS.md`, `DEVELOPMENT.md`

### Hub-and-Spoke Index Template

```markdown
# <Project Name> - <Doc Type>

## Quick Links

| System | Documentation |
|--------|---------------|
| <Subsystem A> | [<SUBSYSTEM_A>_<DOCTYPE>.md](<SUBSYSTEM_A>_<DOCTYPE>.md) |
| <Subsystem B> | [<SUBSYSTEM_B>_<DOCTYPE>.md](<SUBSYSTEM_B>_<DOCTYPE>.md) |

## Shared <Doc Type Context>

<Brief shared content that applies across all subsystems>

## See Also

- [<Other doc type>](<OTHER_DOCTYPE>.md)
```

---

## Scaffolding Templates

### Root instruction pair

`AGENTS.md` is project-specific but keeps this ownership shape:

```markdown
# <Project Name>

<One short project orientation paragraph.>

## Documentation

| Topic | Canonical document |
|---|---|
| Architecture | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Code standards | [docs/CODE_STANDARDS.md](docs/CODE_STANDARDS.md) |
| Development commands and setup | [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) |
| Review focus | [docs/REVIEW_FOCUS.md](docs/REVIEW_FOCUS.md) |

## Repository Guardrails

- <Only guardrails unique to this repository; do not repeat commands or core-doc prose.>
```

`CLAUDE.md` is always:

```text
@AGENTS.md
```

### ARCHITECTURE.md (Flat)

```markdown
# <Project Name> - Architecture

## Overview

<1-3 sentence project description>

## Module Structure

| Module | Responsibility |
|--------|---------------|
| `<module>` | <description> |

## Layer Dependencies

<Describe which modules depend on which and why>

```
<module-a>
  └── <module-b>
      └── <module-c>
```

## Data Flow

<Describe primary data flow through the system>

## Key Types

| Type | Purpose |
|------|---------|
| `<TypeName>` | <description> |

## Future Considerations

<Planned architectural changes>
```

### CODE_STANDARDS.md (Flat)

```markdown
# <Project Name> - Code Standards

## Language Idioms

<Language-specific best practices for this project>

## Error Handling

<How errors should be created, propagated, and handled>

## Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| <element> | <rule> | `<example>` |

## Anti-patterns

### <Anti-pattern Name>

**BAD:**
```<lang>
// Don't do this
```

**GOOD:**
```<lang>
// Do this instead
```

## Testing Patterns

<Test naming, structure, and expectations>
```

### REVIEW_FOCUS.md

```markdown
# <Project Name> - Review Focus

## Review Priorities

1. <Project-specific concern reviewers weight first, and why>
2. <...>

## Known Hot Spots

| Area | Why fragile |
|------|-------------|
| `<module/path>` | <invariant or regression history> |

## Severity Calibration

- **Critical:** <what breaks users/data/security in THIS project>
- **Major:** <what blocks a release here>
- **Minor:** <everything else worth noting>

## Out of Scope

- <thing reviewers should not flag, and why>
```

### DEVELOPMENT.md (Flat)

```markdown
# <Project Name> - Development Guide

## Prerequisites

- <tool> <version>

## Build

```bash
# Debug
<debug build command>

# Release
<release build command>
```

## Run

```bash
<run command>
```

## Test

```bash
# All tests
<test command>

# Specific tests
<specific test command>
```

## Environment Setup

| Variable | Purpose | Default |
|----------|---------|---------|
| `<VAR>` | <purpose> | `<default>` |

## Troubleshooting

### <Common Issue>
<Solution>
```
