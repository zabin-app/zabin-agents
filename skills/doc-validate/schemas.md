# Document Schemas

Content boundary definitions for project documentation. This is the single source of truth referenced by the `doc_maintainer` agent and the `doc_validate` skill.

---

## Content Boundary Quick Reference

| Content Type | ARCHITECTURE | CODE_STANDARDS | DEVELOPMENT |
|---|---|---|---|
| System overview / TL;DR | YES | NO | NO |
| Module/component descriptions | YES | NO | NO |
| Layer dependencies | YES | NO | NO |
| Data flow diagrams | YES | NO | NO |
| Key type signatures (minimal) | YES | YES (full) | NO |
| Architecture diagrams (ASCII/text) | YES | NO | NO |
| Code samples / DO-DON'T patterns | NO | YES | NO |
| Naming conventions | NO | YES | NO |
| Anti-patterns with examples | NO | YES | NO |
| Error handling patterns | NO | YES | NO |
| Testing patterns / test examples | NO | YES | NO |
| Security coding practices | NO | YES | NO |
| Logging standards | NO | YES | NO |
| Performance guidelines | NO | YES | NO |
| Build commands (cargo, npm, make) | NO | NO | YES |
| Run commands / app startup | NO | NO | YES |
| Test commands (how to run tests) | NO | NO | YES |
| Docker / container setup | NO | NO | YES |
| Environment variables / .env setup | NO | NO | YES |
| Prerequisites / dependencies | NO | NO | YES |
| CI/CD configuration | NO | NO | YES |
| Troubleshooting / common issues | NO | NO | YES |
| Workflow locations (plans, tasks) | NO | NO | YES |
| Editor / tooling setup | NO | NO | YES |

---

## Size Budgets & Compaction

Core docs are **maps, not the territory**. They have hard size budgets, because an unbounded doc is one nobody reads and the `doc_maintainer` keeps appending to. Budgets are measured in lines (`wc -l`).

| Doc | Target | Hard cap | Over cap → |
|-----|--------|----------|------------|
| `ARCHITECTURE.md` / `CODE_STANDARDS.md` / `DEVELOPMENT.md` (flat, or a hub-and-spoke spoke) | ≤ 350 | **500** | compact, or split to hub-and-spoke |
| Hub-and-spoke index doc | ≤ 120 | 150 | move detail into spokes |
| `REVIEW_FOCUS.md` | ≤ 150 | 200 | prune stale hot spots; generic advice goes nowhere (reviewers already know it) |
| `CLAUDE.md` | ≤ 80 | 100 | move detail into the core docs and link |

- **Target** = healthy size. **Hard cap** = a doc at or above this is a defect (validator Error). Splitting to hub-and-spoke is the expected remedy once a doc legitimately needs >500 lines of content — never let one doc absorb it all.
- Updates should be **net-neutral**: adding a fact means removing what it supersedes. A doc that only ever grows is a process failure.

## Altitude & Duplication Rules (apply to all core docs)

**Altitude.** Core docs describe the *shape* of the system, not its implementation. A statement is **too low-altitude** (belongs in code/comments or a spec, not a core doc) when it:
- names a specific private function, struct field, DB column, or constant as the subject of an explanation;
- walks through an algorithm step by step, or describes control flow / idempotency / recovery semantics;
- enumerates files, widgets, or screens one by one (a "tour" of the code);
- would become wrong if someone renamed a private symbol or reordered internal steps.

Rule of thumb: one module gets a few sentences (responsibility + dependencies + key public types), not a multi-page deep-dive.

**Present tense / no changelog.** Core docs describe the *current* state only. Prohibited: "Phase N", "previously", "was changed to", "collapsed/refactored", migration narratives, deprecation play-by-plays, and dates. That history belongs in git.

**No duplication.** Each fact lives in exactly ONE doc; other docs cross-reference it (`See docs/X.md#section`). `CLAUDE.md` in particular must be a pointer/index — a link table into the core docs plus repo-specific agent guardrails — never a copy of their content.

---

## Document Type: CLAUDE.md

### Purpose
The agent entry point at the repo root. Orients an agent and routes it to the right doc. A lean **index**, never a content store.

### Required Content
- One-paragraph project description.
- A link table to the core docs (architecture / code standards / development).
- A few must-know commands, or a pointer to `DEVELOPMENT.md`.
- Repo-specific agent guardrails that live nowhere else.

### Prohibited Content
- Any prose copied from ARCHITECTURE/CODE_STANDARDS/DEVELOPMENT (link instead).
- Module inventories, coding standards, or build instructions duplicated from the core docs.

### Detection Heuristics (for validation)
- Length > 100 lines → almost certainly duplicating doc content.
- Headed sections that mirror core-doc sections (e.g. "Module Structure", "Naming Conventions", "Build Commands") with their own prose rather than a link → duplication.

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
