# Code Review Document Templates

Reference templates for creating code review documents. These ensure thorough, consistent, and actionable reviews.

---

## Feature Review Template

**Location:** `workflow/reviews/features/<feature-name>/REVIEW.md`

```markdown
# Feature Review: <Feature Name>

**Review Date:** <YYYY-MM-DD>
**Reviewer:** Code Review Orchestrator
**Task Files Reviewed:** <count> tasks
**Files Changed:** <count> files

---

## Executive Summary

**Overall Verdict:** ✅ APPROVED / ⚠️ NEEDS WORK / ❌ REJECTED

<2-3 sentence summary of the feature implementation and review outcome>

---

## Changes Overview

### Task Files Reviewed

| Task | Status | Files Modified |
|------|--------|----------------|
| `<task-path>` | Done/Blocked | <count> |

### Files Changed

<Output of git diff --stat or similar>

---

## Subagent Review Summaries

### Architecture Enforcer
**Verdict:** ✅ PASS / 🟠 CONCERNS / ❌ FAIL

<Summary of architectural compliance findings>

**Key Findings:**
- <finding 1>
- <finding 2>

### Code Quality Inspector
**Verdict:** ✅ PASS / 🟠 CONCERNS / ❌ FAIL

<Summary of code quality findings>

**Quality Scores:**
| Metric | Score |
|--------|-------|
| Language Idioms | ⭐⭐⭐⭐⭐ |
| Error Handling | ⭐⭐⭐⭐⭐ |
| Testing | ⭐⭐⭐⭐⭐ |
| Documentation | ⭐⭐⭐⭐⭐ |
| Maintainability | ⭐⭐⭐⭐⭐ |

### Logic & Reasoning Checker
**Verdict:** ✅ PASS / 🟠 CONCERNS / ❌ FAIL

<Summary of logical consistency findings>

**Key Findings:**
- <finding 1>
- <finding 2>

### Risks & Tradeoffs Analyzer
**Verdict:** ✅ PASS / 🟠 CONCERNS / ❌ FAIL

<Summary of risk analysis>

**Identified Risks:**
| Risk | Severity | Mitigated? |
|------|----------|------------|
| <risk> | High/Medium/Low | Yes/No |

### Security Reviewer
**Verdict:** ✅ PASS / 🟠 CONCERNS / ❌ FAIL

<Summary of security findings>

**Security Findings:**
| Finding | Category | Severity |
|---------|----------|----------|
| <finding> | <Injection/Credentials/Auth/Input/Crypto> | Critical/High/Medium/Low |

### Documentation Freshness
**Status:** ✅ Up to date / ⚠️ Updates needed

| Doc | Needs Update? | Reason |
|-----|--------------|--------|
| ARCHITECTURE.md | Yes/No | <new modules, changed layers, etc.> |
| CODE_STANDARDS.md | Yes/No | <new patterns, conventions> |
| DEVELOPMENT.md | Yes/No | <new build steps, deps, commands> |

---

## Consolidated Issues

### 🔴 Critical Issues (Must Fix)

<Issues that MUST be resolved before merge>

1. **[Source: <agent>] <Issue Title>**
   - **File:** `<path>:<line>`
   - **Problem:** <description>
   - **Required Action:** <what must be done>

### 🟠 Major Issues (Should Fix)

<Issues that should be resolved but aren't blocking>

1. **[Source: <agent>] <Issue Title>**
   - **File:** `<path>`
   - **Problem:** <description>
   - **Recommended Action:** <what should be done>

### 🟡 Minor Issues (Consider Fixing)

<Non-blocking improvements>

1. **[Source: <agent>] <Issue Title>**
   - **Suggestion:** <improvement>

---

## Review Checklist

- [ ] **Architecture Compliance**: Changes follow layer boundaries and design patterns (see `docs/ARCHITECTURE.md`)
- [ ] **Code Quality**: Language idioms, error handling, and project conventions followed (see `docs/CODE_STANDARDS.md`)
- [ ] **Logical Consistency**: No contradictions, complete state handling
- [ ] **Security**: No vulnerabilities, credentials secured, input validated at boundaries
- [ ] **Risk Mitigation**: Documented risks have adequate mitigations
- [ ] **Testing Coverage**: New code has appropriate test coverage
- [ ] **Documentation**: Public APIs documented, significant decisions explained
- [ ] **Doc Freshness**: Relevant project docs updated if architecture/standards/build changed

---

## Actionable Items

<Numbered list of specific actions required for approval>

### Required for Approval

1. [ ] **<Action Item>**
   - Files: `<affected files>`
   - Details: <what needs to change>

2. [ ] **<Action Item>**
   - Files: `<affected files>`
   - Details: <what needs to change>

### Recommended Improvements

1. [ ] **<Improvement>**
   - Rationale: <why this would help>

---

## Conclusion

**Final Assessment:** <Detailed conclusion about the implementation>

**Next Steps:**
1. <step 1>
2. <step 2>

**Blocking Issues Count:** <N>
**Re-review Required:** Yes/No
```

---

## Bug Fix Review Template

**Location:** `workflow/reviews/bugs/<bug-name>/REVIEW.md`

```markdown
# Bug Fix Review: <Bug Name>

**Review Date:** <YYYY-MM-DD>
**Reviewer:** Code Review Orchestrator
**Bug Task:** `<path/to/fix-*.md>`
**Files Changed:** <count> files

---

## Executive Summary

**Overall Verdict:** ✅ APPROVED / ⚠️ NEEDS WORK / ❌ REJECTED

<2-3 sentence summary of the fix and review outcome>

---

## Bug Context

### Original Problem
<Brief description of the bug from the task file>

### Root Cause
<What was identified as the root cause>

### Fix Approach
<How the fix addresses the root cause>

---

## Changes Overview

### Files Changed

| File | Changes |
|------|---------|
| `<path>` | <summary> |

---

## Subagent Review Summaries

### Bug Fix Reviewer
**Verdict:** ✅ PASS / 🟠 CONCERNS / ❌ FAIL

**Root Cause Addressed:** Yes/No/Partially

<Summary of bug fix validation>

**Acceptance Criteria:**
| Criterion | Met? |
|-----------|------|
| <criterion> | ✅/❌ |

### Architecture Enforcer
**Verdict:** ✅ PASS / 🟠 CONCERNS / ❌ FAIL

<Summary of architectural impact>

### Code Quality Inspector
**Verdict:** ✅ PASS / 🟠 CONCERNS / ❌ FAIL

<Summary of code quality>

### Logic & Reasoning Checker
**Verdict:** ✅ PASS / 🟠 CONCERNS / ❌ FAIL

<Summary of logical correctness>

### Risks & Tradeoffs Analyzer
**Verdict:** ✅ PASS / 🟠 CONCERNS / ❌ FAIL

**Regression Risk:** Low/Medium/High

<Summary of risks introduced by the fix>

### Security Reviewer
**Verdict:** ✅ PASS / 🟠 CONCERNS / ❌ FAIL

<Summary of security implications of the fix>

---

## Consolidated Issues

Note: Findings from multiple agents that reference the same code are deduplicated, with all source agents credited.

### 🔴 Critical Issues (Must Fix)

1. **[Source: <agent>] <Issue Title>**
   - **Problem:** <description>
   - **Required Action:** <what must be done>

### 🟠 Major Issues (Should Fix)

1. **[Source: <agent>] <Issue Title>**
   - **Problem:** <description>
   - **Recommended Action:** <what should be done>

### 🟡 Minor Issues

1. **<Issue>**: <suggestion>

---

## Regression Analysis

**Affected Code Paths:**
- <path 1>
- <path 2>

**Potential Side Effects:**
| Change | Possible Side Effect | Mitigated? |
|--------|---------------------|------------|
| <change> | <effect> | Yes/No |

**Test Coverage for Regression:**
- [ ] Existing tests still pass
- [ ] New tests added for the fix
- [ ] Edge cases covered

---

## Review Checklist

- [ ] **Root Cause Fixed**: The actual root cause is addressed, not just symptoms
- [ ] **No Regressions**: Fix doesn't break existing functionality
- [ ] **Complete Fix**: All affected code paths are handled
- [ ] **Tests Added**: Regression tests prevent reintroduction
- [ ] **Error Handling**: Failure cases handled gracefully

---

## Actionable Items

### Required for Approval

1. [ ] **<Action Item>**
   - Details: <what needs to change>

### Recommended

1. [ ] **<Improvement>**
   - Rationale: <why>

---

## Conclusion

**Fix Validity:** <Assessment of whether the fix is correct and complete>

**Next Steps:**
1. <step>

**Re-review Required:** Yes/No
```

---

## Quick Review Template

**Location:** `workflow/reviews/quick/<change-name>/REVIEW.md`

Use for small, focused changes that don't warrant full review.

```markdown
# Quick Review: <Change Name>

**Date:** <YYYY-MM-DD>
**Verdict:** ✅ APPROVED / ❌ REJECTED

## Changes
<Brief description>

## Files Modified
- `<file>`

## Review Notes
<Key observations>

## Issues
- <None / List issues>

## Approved: Yes/No
```

---

## Review Rejection Template

When changes are rejected, use this additional section:

```markdown
---

## ❌ REJECTION NOTICE

**Rejection Reason:** <Primary reason for rejection>

### Blocking Issues Summary

| # | Issue | Severity | File | Required Fix |
|---|-------|----------|------|--------------|
| 1 | <issue> | Critical | `<path>` | <fix> |
| 2 | <issue> | Critical | `<path>` | <fix> |

### Required Rework

The following must be addressed before re-review:

1. **<Rework Item 1>**
   - Current State: <what's wrong>
   - Required State: <what it should be>
   - Affected Files: `<files>`

2. **<Rework Item 2>**
   - Current State: <what's wrong>
   - Required State: <what it should be>
   - Affected Files: `<files>`

### Re-review Instructions

After addressing the above issues:
1. Update the task completion summary with new changes
2. Run `cargo fmt && cargo check && cargo test && cargo clippy`
3. Request re-review

**Estimated Rework Effort:** Small/Medium/Large
```
