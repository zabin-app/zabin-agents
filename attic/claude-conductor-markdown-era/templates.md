# Planning Document Templates

Reference templates for creating plans, bug reports, task indexes, and individual tasks.

---

## Feature Plan Template

**Location:** `workflow/plans/features/<feature-name>/PLAN.md`

```markdown
# Plan: <Feature Name>

## TL;DR

<20-100 words: what/how/why>

---

## Background

<Context on why this feature is needed, current limitations, user pain points>

---

## Affected Modules

- `src/<module>.rs` - <Brief description of changes>
- `src/<module>.rs` - **NEW** <For new files>

---

## Development Phases

### Phase 1: <Phase Title>

**Goal**: <1-2 sentence description>

**Duration**: <Estimate>

#### Steps

1. **<Step Title>**
   - <Bullet points with specific changes>
   - <Implementation details>

2. **<Step Title>**
   - <Details>

**Milestone**: <What users can do when phase complete>

---

### Phase 2: <Phase Title>

<Repeat structure>

---

## Edge Cases & Risks

### <Risk Category>
- **Risk:** <Description>
- **Mitigation:** <How to address>

---

## Configuration Additions

<If applicable, show config file additions>

```toml
[section]
option = "value"
```

---

## Keyboard Shortcuts Summary

| Key | Action |
|-----|--------|
| `x` | <Action> |

---

## Success Criteria

### Phase 1 Complete When:
- [ ] <Measurable outcome>
- [ ] <Testable condition>

### Phase 2 Complete When:
- [ ] <Measurable outcome>

---

## Future Enhancements

<Optional: ideas for future iterations>

---

## References

- [Link](url)
```

---

## Bug Report Plan Template

**Location:** `workflow/plans/bugs/<bug-name>/BUG.md`

```markdown
# Bugfix Plan: <Bug Title>

## TL;DR

<20-100 words: what bugs exist, root cause summary, fix approach>

## Bug Reports

### Bug 1: <Bug Title>
**Symptom:** <What the user sees>

**Expected:** <What should happen>

**Root Cause Analysis:**
1. <Specific code path causing issue>
2. <Why it fails>

**Affected Files:**
- `src/<file>.rs` - <description>

---

### Bug 2: <Bug Title>

<Repeat structure>

---

## Affected Modules

- `src/<module>.rs`: <Description of needed changes>

---

## Phases

### Phase 1: <Fix Category> (Bug X) - Critical

<Description of fix approach>

**Steps:**
1. <Specific code change>
2. <Implementation detail>

**Measurable Outcomes:**
- <How to verify fix works>
- <Test case>

---

## Edge Cases & Risks

### <Risk Category>
- **Risk:** <Description>
- **Mitigation:** <How to address>

---

## Further Considerations

1. **<Question>** <Options or tradeoffs>

---

## Task Dependency Graph

```
Phase 1
├── 01-task-slug
├── 02-task-slug
│   └── depends on: 01
└── 03-task-slug
    └── depends on: 02
```

---

## Success Criteria

### Phase 1 Complete When:
- [ ] <Bug X is fixed, verified by...>
- [ ] <No regression in...>

---

## Milestone Deliverable

<Summary of what's achieved when all bugs are fixed>
```

---

## Task Index Template

**Location:** `workflow/plans/<type>/<name>/<phase>/TASKS.md`

```markdown
# <Phase/Feature Name> - Task Index

## Overview

<1-2 sentence summary of this phase/feature>

**Total Tasks:** X
**Estimated Hours:** X-Y hours

## Task Dependency Graph

```
┌─────────────────────┐     ┌─────────────────────┐
│  01-task-slug       │     │  02-task-slug       │
└─────────┬───────────┘     └──────────┬──────────┘
          │                            │
          └──────────┬─────────────────┘
                     ▼
          ┌─────────────────────┐
          │  03-task-slug       │
          └─────────────────────┘
```

## Tasks

| # | Task | Status | Complexity | Depends On | Est. Hours | Modules |
|---|------|--------|------------|------------|------------|---------|
| 1 | [01-task-slug](tasks/01-task-slug.md) | Not Started | medium | - | 3-4h | `module.rs` |
| 2 | [02-task-slug](tasks/02-task-slug.md) | Not Started | low | - | 2-3h | `module.rs` |
| 3 | [03-task-slug](tasks/03-task-slug.md) | Not Started | high | 1, 2 | 4-5h | `module.rs` |

## File Overlap Analysis

<!-- The conductor uses this section to determine isolation strategy per wave -->

| Task | Files Modified (Write) | Files Read (Dependencies) |
|------|----------------------|--------------------------|
| 01-task-slug | `src/<file>.rs`, `src/<file>.rs` | `src/<config>.rs` |
| 02-task-slug | `src/<file>.rs` | `src/<config>.rs` |
| 03-task-slug | `src/<file>.rs`, `src/<file>.rs` | - |

### Overlap Matrix

<!-- Compare write-files between tasks that share the same wave (no dependency between them) -->
<!-- Read-only overlap is fine — only write overlap forces sequential execution -->

| Task Pair | Shared Write Files | Isolation Strategy |
|-----------|-------------------|-------------------|
| 01 + 02 | None | Parallel (worktree) |
| 01 + 03 | `src/<file>.rs` | Sequential (same branch) |
| 02 + 03 | None | Parallel (worktree) |

## Success Criteria

<Phase/feature> is complete when:

- [ ] <Measurable outcome>
- [ ] <Testable condition>
- [ ] All new code has unit tests
- [ ] No regressions in existing functionality

## Keyboard Shortcuts

<If applicable>

| Key | Action |
|-----|--------|
| `x` | <Action> |

## Notes

- <Important context>
- <Constraints or considerations>
```

---

## Individual Task Template

**Location:** `workflow/plans/<type>/<name>/<phase>/tasks/<##-task-slug>.md`

```markdown
## Task: <Task Title>

**Objective**: <1-2 sentences describing what this task accomplishes>

**Depends on**: <Task slugs or "None">

**Agent:** <doc_maintainer for core doc tasks, or omit for default implementor>

**Complexity:** <low | medium | high — drives the implementor model tier (haiku/sonnet/opus); see SKILL.md "Task Complexity Rating">

**Docs:** <resolved by the conductor — see SKILL.md "Doc routing". Flat project: the four `docs/*.md`. Split project: root `docs/ARCHITECTURE.md` (always) + each touched unit's docs. List only files that exist.>
- `docs/ARCHITECTURE.md`: cross-unit dependencies and layer rules
- `docs/<UNIT>_ARCHITECTURE.md` (or `<package>/docs/ARCHITECTURE.md`): the unit this task changes
- `docs/CODE_STANDARDS.md`, `docs/DEVELOPMENT.md`, `docs/REVIEW_FOCUS.md`

**Estimated Time**: <X-Y hours>

### Scope

**Files Modified (Write):**
- `src/<module>.rs`: <Specific changes to make>

**Files Read (Dependencies):**
- `src/<other>.rs`: <Why this file is read>

### Details

<Detailed implementation guidance, code examples if helpful>

```rust
// Example code structure
pub struct Example {
    pub field: Type,
}
```

### Acceptance Criteria

1. <Measurable outcome - can be verified>
2. <Testable condition - can be unit tested>
3. <Behavior specification>

### Testing

<Test approach and example test cases>

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_example() {
        // Test implementation
    }
}
```

### Notes

- <Important considerations>
- <Edge cases to handle>
- <Future enhancements to defer>

---

## Completion Summary

**Status:** Done / Blocked / Failed
**Branch:** <current branch name>

### Files Modified

| File | Changes |
|------|---------|
| `src/path/file` | <what changed> |

### Notable Decisions/Tradeoffs

1. **<Decision>**: <Rationale and implications>

### Testing Performed

- <verification command> - Passed/Failed
- <test command> - Passed/Failed (X tests)
- <lint command> - Passed/Failed

(See `docs/DEVELOPMENT.md` for project-specific verification commands)

### Risks/Limitations

1. **<Risk>**: <Description and mitigation if any>
```

---

## Documentation Update Task Template

**Location:** `workflow/plans/<type>/<name>/<phase>/tasks/<##-update-docs>.md`

Use this template when a task is specifically for updating core project documentation. These tasks are routed to the `doc_maintainer` agent by the conductor.

```markdown
## Task: Update Documentation for <Feature/Change>

**Agent:** doc_maintainer

**Objective**: Update core project documentation to reflect changes from implementation tasks

**Depends on**: <all implementation task slugs that this doc update covers>

**Estimated Time**: <X-Y hours>

### Scope

**Files Modified (Write):**

Name the **unit** doc, not the root index — see SKILL.md "Doc routing". On a flat project these are the base `docs/*.md`.

- `docs/<UNIT>_ARCHITECTURE.md` (or `<package>/docs/ARCHITECTURE.md`): <what changed inside this unit>
- `docs/ARCHITECTURE.md`: <ONLY if a cross-unit dependency, a new unit, or a link changed — otherwise omit>
- `docs/CODE_STANDARDS.md`: <what new patterns/conventions to document>
- `docs/DEVELOPMENT.md`: <what new build steps/commands to document>

**Files Read (Dependencies):**
- `docs/DOC_POLICY.md`: structure, budgets, and the unit → doc-path mapping
- `~/.claude/skills/doc-standards/schemas.md`: Content boundary rules
- <implementation task files for change context>

### Change Context

Summarize what implementation changes require doc updates:

1. **<Change area>**: <description of what changed and which doc needs updating>

### Acceptance Criteria

1. Updated docs accurately reflect the implementation changes
2. No content boundary violations (architecture content only in ARCHITECTURE.md, etc.)
3. All required sections present per schemas.md
4. Every doc still under the cap in force (per `docs/DOC_POLICY.md`)
5. Detail landed in the unit doc, not the root index; cross-references valid and every unit doc linked from the index

### Notes

- Follow content boundaries strictly — see ~/.claude/skills/doc-standards/schemas.md
- Make targeted edits, do not rewrite entire documents
- If unsure whether content belongs in a particular doc, consult the Content Boundary Quick Reference
```

---

## Status Icons Reference

| Status | Icon |
|--------|------|
| Not Started | (blank) |
| In Progress | 🔄 |
| Done | ✅ |
| Blocked | ⚠️ |
| Failed | ❌ |

## File Naming Conventions

- **Plans:** `PLAN.md` (features) or `BUG.md` (bugs)
- **Task Index:** `TASKS.md`
- **Tasks:** `##-task-slug.md` (e.g., `01-add-filter-types.md`)
- **Slugs:** lowercase, hyphen-separated, descriptive
