# Action Items: <Feature/Bug Name>

**Review Date:** <YYYY-MM-DD>
**Review Document:** [`REVIEW.md`](./REVIEW.md)
**Verdict:** ❌ REJECTED / ⚠️ NEEDS WORK

---

## Summary

**Total Issues:** <count>
- 🔴 Critical: <count>
- 🟠 Major: <count>
- 🟡 Minor: <count>

**Estimated Rework Effort:** Small (< 1 hour) / Medium (1-4 hours) / Large (> 4 hours)

---

## 🔴 Critical Issues (Must Fix Before Merge)

These issues BLOCK the merge. All must be resolved.

### 1. <Issue Title>

| Attribute | Value |
|-----------|-------|
| **Source** | <Architecture Enforcer / Code Quality Inspector / Logic Checker / Bug Fix Reviewer / Risks Analyzer> |
| **File** | `<path/to/file>` |
| **Line** | <line number or range> |
| **Severity** | 🔴 Critical |

**Problem:**
<Detailed description of what is wrong>

**Why It's Critical:**
<Why this must be fixed - crash risk, data corruption, security, architecture violation, etc.>

**Required Fix:**
<Specific, actionable steps to fix this issue>

**Verification:**
- [ ] <How to verify the fix is correct>
- [ ] <Test to run or behavior to check>

---

### 2. <Issue Title>

| Attribute | Value |
|-----------|-------|
| **Source** | <agent name> |
| **File** | `<path>` |
| **Line** | <line> |
| **Severity** | 🔴 Critical |

**Problem:**
<description>

**Why It's Critical:**
<explanation>

**Required Fix:**
<steps>

**Verification:**
- [ ] <verification step>

---

## 🟠 Major Issues (Should Fix Before Merge)

These issues are significant and should be addressed. Exceptions require justification.

### 1. <Issue Title>

| Attribute | Value |
|-----------|-------|
| **Source** | <agent name> |
| **File** | `<path>` |
| **Severity** | 🟠 Major |

**Problem:**
<description>

**Impact:**
<What could go wrong if not fixed>

**Recommended Fix:**
<How to address this>

**If Deferred:**
- Track in: <issue tracker location>
- Mitigation: <temporary workaround if any>

---

## 🟡 Minor Issues (Consider Fixing)

These are non-blocking improvements. Address if time permits.

### 1. <Issue Title>
- **File:** `<path>`
- **Suggestion:** <what could be improved>
- **Benefit:** <why it would help>

### 2. <Issue Title>
- **File:** `<path>`
- **Suggestion:** <improvement>
- **Benefit:** <benefit>

---

## Files Requiring Changes

| File | Issues | Priority |
|------|--------|----------|
| `<path/to/file1>` | #1, #3 | High |
| `<path/to/file2>` | #2 | High |
| `<path/to/file3>` | #4, #5 | Medium |

---

## Rework Checklist

Complete all items before requesting re-review:

### Critical Fixes
- [ ] Issue #1: <brief description>
- [ ] Issue #2: <brief description>

### Major Fixes
- [ ] Issue #3: <brief description>
- [ ] Issue #4: <brief description>

### Quality Gates

Run verification commands from `docs/DEVELOPMENT.md`:
- [ ] Format command — Code is formatted
- [ ] Check command — No compilation errors
- [ ] Test command — All tests pass
- [ ] Lint command — No warnings

### Documentation
- [ ] Task completion summary updated with new changes
- [ ] Any new public APIs documented

---

## Re-review Instructions

After addressing the issues above:

1. **Update the task file** completion summary with:
   - Additional files modified
   - New decisions/tradeoffs if any
   - Updated test results

2. **Run verification commands** (see `docs/DEVELOPMENT.md` for project-specific commands):
   ```bash
   # Example: format, check, test, lint
   ```

3. **Self-check:**
   - [ ] All critical issues resolved
   - [ ] All major issues resolved or justified
   - [ ] Code compiles and tests pass
   - [ ] No new warnings introduced

4. **Request re-review** by mentioning the reviewer skill

---

## Notes

<Any additional context, clarifications, or guidance for the implementer>

---

**Original Review:** [`REVIEW.md`](./REVIEW.md)
**Task File:** `<path/to/task.md>`
**Reviewer:** Code Review Orchestrator