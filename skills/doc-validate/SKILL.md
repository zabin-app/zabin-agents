---
name: doc_validate
description: Read-only audit of all managed project docs, subsystem variants, canonical AGENTS.md, and the CLAUDE.md import wrapper for structure, precedence, duplication, size, boundaries, and links. Triggers on "doc-validate", "validate docs", "audit docs", "check docs".
---

# Doc Validate

Audit the complete managed documentation set. Report evidence and actionable findings; never edit a file.

## Before starting

1. Resolve and read this skill's bundled [schemas.md](schemas.md) completely through the host's skill/resource mechanism. Do not assume an installation or home-directory path.
2. Resolve the repository root with the host's git/filesystem capability.
3. Require read/search, line-count, and link-inspection capabilities. If any required read cannot be completed, report the audit incomplete and fail toward caution.

The validator policy is the source of truth for ownership and budgets. Live system, developer, user, and role instructions remain higher authority than repository documentation.

## 1. Discover and inventory

List:

- root `AGENTS.md` and root `CLAUDE.md` explicitly, including absence;
- `docs/ARCHITECTURE.md`, `docs/CODE_STANDARDS.md`, `docs/DEVELOPMENT.md`, and `docs/REVIEW_FOCUS.md`, including absence;
- every `docs/<SUBSYSTEM>_ARCHITECTURE.md`, `docs/<SUBSYSTEM>_CODE_STANDARDS.md`, and `docs/<SUBSYSTEM>_DEVELOPMENT.md`;
- other `docs/**/*.md` files as unmanaged inventory only.

Do not treat “whichever root file exists” as sufficient. `AGENTS.md` is canonical and `CLAUDE.md` is the compatibility wrapper; both receive an explicit result.

Classify the repository as hub-and-spoke when any managed subsystem variant exists; otherwise classify it as flat. Under hub-and-spoke, the three base architecture/standards/development files are indexes. `REVIEW_FOCUS.md` remains a single curated project doc unless the policy is explicitly extended.

Missing-file severity:

- missing root `AGENTS.md`: Error;
- missing root `CLAUDE.md`: Error;
- missing any of the four base managed docs: Error;
- a missing subsystem counterpart or unlinked managed spoke: Error.

## 2. Validate the root instruction model

### Canonical `AGENTS.md`

Verify that it:

- gives a short project orientation;
- links to all four base managed docs and, when relevant, the hub indexes;
- points to `DEVELOPMENT.md` rather than repeating commands;
- contains only repository-specific guardrails not duplicated elsewhere;
- contains no core-doc section clone, command block, provider/model selection, transport-qualified tool name, or higher-authority instruction copy.

### Import-only `CLAUDE.md`

Normalize line endings, discard blank lines, and require the remaining line array to equal exactly:

```text
@AGENTS.md
```

Any heading, frontmatter, prose, command, guardrail, extra import, or alternate instruction is an Error. Verify that the imported root `AGENTS.md` exists.

### Precedence and conflict

Check for contradictory normative statements across `AGENTS.md` and the managed docs. Apply this repository-layer order:

1. the nearest path-scoped `AGENTS.md` for files in its subtree;
2. root `AGENTS.md` for repository-wide guardrails;
3. the owning core doc for architecture, standards, development, or review-focus detail;
4. `CLAUDE.md` contributes no independent instruction.

A lower-precedence contradiction is an Error. A repeated but non-conflicting rule is still a duplication Error: precedence does not justify copies.

## 3. Validate structure and content boundaries

Match headings by intent rather than exact spelling.

| Document | Required intent |
|---|---|
| Architecture | overview, module/component structure, layer dependencies, data flow, key types/interfaces |
| Code standards | language idioms, error handling, naming, anti-patterns, testing patterns |
| Development | prerequisites, build, run, tests, environment setup |
| Review focus | review priorities, known hot spots, severity calibration |

Apply every prohibited-content and detection rule in `schemas.md` to each base doc and each managed spoke. Important boundary checks include:

- architecture: no commands, coding-style sections, configuration setup, long code samples, or implementation walkthroughs;
- code standards: no system inventory, dependency/data-flow diagrams, commands, configuration, or deployment procedure;
- development: no architecture, style rules, feature design, or non-command implementation examples;
- review focus: no generic review advice, architecture summary, coding rules, commands, or historical play-by-play.

Report missing required intent as Warning unless the file is only a hub index, where links and shared overview are the intended structure. Report a clear wrong-owner section as Error and an isolated command-like line according to the policy's stated severity.

## 4. Validate size, altitude, history, and duplication

Count physical lines for every managed file.

| File class | Warning | Error |
|---|---:|---:|
| Flat core doc or subsystem spoke | over 350 | over 500 |
| Hub index | over 120 | over 150 |
| `REVIEW_FOCUS.md` | over 150 | over 200 |
| `AGENTS.md` | over 80 | over 100 |
| `CLAUDE.md` | n/a | anything other than one nonblank import line |

Also check:

- private-symbol explanations, step-by-step control flow, idempotency/recovery walkthroughs, and per-file tours: Warning with line range;
- `Phase ` followed by a digit, `previously`, `was changed`, `collapsed`, `refactored to`, or deprecation narrative: Warning;
- excessive `####`/`#####` nesting under one module: Warning;
- duplicate or near-duplicate headings in one file: Error;
- substantively repeated prose, commands, or guardrails across managed files: Error with both locations;
- paraphrased duplication that links would replace: Error when it states the same normative rule, otherwise Warning when uncertain.

Compare normalized prose semantically as well as exact repeated lines. Ignore headings, table framing, import directives, and short unavoidable project names when identifying duplication.

## 5. Validate links and hub consistency

For every managed Markdown link or import:

- resolve the target relative to the containing file;
- report missing repository-relative targets;
- require every managed spoke to be linked from its matching base index;
- require consistent subsystem prefixes across architecture, standards, and development spokes;
- require all four base docs to be reachable from `AGENTS.md`;
- require `CLAUDE.md` to resolve only root `AGENTS.md`.

External links may be inventoried without network access unless the caller explicitly authorizes external verification.

## 6. Run normative fixture checks

Before reporting, apply the fixtures in `schemas.md` to the validator logic. At minimum demonstrate these decisions in the audit evidence:

1. canonical `AGENTS.md` plus one-line wrapper passes root shape;
2. missing `AGENTS.md` with an importing wrapper fails;
3. wrapper prose or a second import fails;
4. a command repeated in `AGENTS.md` and `DEVELOPMENT.md` fails duplication;
5. a guardrail repeated outside `AGENTS.md` fails duplication;
6. a managed doc contradicting an applicable `AGENTS.md` fails precedence;
7. over-cap root/review files fail size;
8. a boundary leak and a broken spoke link are attributed to their canonical owner.

These may be evaluated as in-memory or temporary-directory fixtures. Do not create fixture files in the repository. If the host cannot execute fixtures, report that verification gap instead of claiming the checks ran.

## 7. Report

Use this structure:

```markdown
## Documentation Audit Report

**Project:** <name>
**Pattern:** Flat / Hub-and-Spoke
**Managed Docs:** <present>/<expected>
**Unmanaged Docs:** <count>
**Overall Status:** PASS / VIOLATIONS FOUND / INCOMPLETE

### Document Inventory
| File | Type | Present | Status |

### Root Instruction and Precedence Issues
| File(s) | Line(s) | Issue | Severity |

### Structural Issues
| File | Issue | Severity |

### Content Boundary Violations
| File | Line(s) | Content | Canonical Owner | Severity |

### Size, Altitude, and Duplication Issues
| File(s) | Line(s) | Lines/Cap | Issue | Severity |

### Link and Hub Issues
| Source | Target | Issue | Severity |

### Fixture Evidence
| Fixture | Result | Evidence |

### Summary
- Errors: <count>
- Warnings: <count>
- Incomplete checks: <count>

### Recommendations
1. <specific owner-aware action>
```

`PASS` requires all managed files, a valid root pair, no Errors, and no incomplete required check. Warnings may coexist with PASS only when the report clearly lists them. Recommend `docs-sync` when files are over hard caps or multiple altitude/duplication failures show systemic drift; recommend a bounded `doc_maintainer` update for isolated findings.

## Boundaries

- Read every managed file completely and cite repository-relative paths and one-based lines.
- Audit both root files separately and together.
- Apply precedence, duplication, size, content-boundary, and link checks to the complete set.
- Inventory but do not validate unmanaged docs.
- Do not edit files, dispatch agents, choose a provider/model, or mutate repository state.
