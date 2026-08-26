# Backlog triage

Run this sweep at the start of every research phase (State 1), not only when a
plan already has findings to draw on. It is pipeline discipline, not project
state: the ledger of open and deferred action items is only useful if every
plan actually reads it.

1. **Research-phase sweep.** Open with 1-2 `search_context` queries scoped to
   the plan's subject — e.g. `search_context(project_id, "OSC 52 clipboard
   write handling")` — before any list paging. This is the dedup pass: has
   this already been filed or discussed, what deferred items relate, what
   research artifact already covers it. Each hit's `source_type` and
   `source_id` (a `task`, `project_document`, `review_round`, `action_item`,
   or `research_artifact`) name the targeted follow-up fetch — `get_task` for
   a task, `get_project_doc` for a doc, `zabctl get reviewrounds --project
   <id>` for a review round, `zabctl describe researchartifacts <id>` for a
   research artifact's full body, or `zabctl get actionitems --project <id>`
   for an action item (all three `zabctl` surfaces need a host that carries
   `zabctl`; otherwise read the record in a Zabin client) — snippet first,
   full fetch only for the specific hit that looks relevant (two-stage).
   `get reviewrounds` and `get actionitems` return only id/verdict/round or
   severity/status and a truncated title, never the full finding text; when
   that listing is all that is reachable, judge relevance from the metadata
   and snippet alone rather than assuming a full read happened. A
   keyword-only note in the response means the semantic index was
   unavailable and the hits are BM25-only — still usable, say so in the
   plan's findings.

   Then enumerate open and deferred action items through the executable
   listing surface (`zabctl get actionitems --project <id>
   --status open` and `--status deferred` on hosts that carry `zabctl`; note
   that no MCP tool enumerates action items — `get_pipeline_state` returns an
   open-only top-10 and `search_context` is retrieval, not enumeration). The
   listing carries ID, severity, status, a truncated title, and the
   review-round/task joins — it does not carry file paths or bodies, so judge
   relevance from the title and, for any candidate the title cannot settle,
   read its itemization artifact (`rsa_…`, which batch items must cite —
   rule 3) or its full text in a Zabin client before deciding. An item naming
   a touched file is never left silent: fold it into the plan (a task, or an
   acceptance criterion citing its `action_item_id`), or re-defer it via
   `update_action_item` with a dated `resolution_note` explaining why it
   stays out of scope.

   Retrieval-first applies to this dedup/prior-art pass only: once a
   specific action item or card is the thing being folded into the plan or
   implemented, read it in full (`get_task`, `get_project_doc`, `zabctl get
   reviewrounds`, or `zabctl describe researchartifacts <id>`) rather than
   trusting the 800-char snippet — the search index is supporting context,
   never the record itself.

2. **Aging rule.** At each plan's State 8 close-out, list deferred items whose
   `created_at` predates the last 3 *completed* plans — this is a CANDIDATE
   list, not a close list. From it, close via `update_action_item`
   `status:"wont_fix"` (`resolution_note` "aged out <date>: untouched across
   3 plans; reopen deliberately if still wanted") only the MINOR-severity
   candidates you did NOT touch in this plan's own step-1 sweep — an item you
   re-deferred this cycle is exempt this cycle (you know your own writes; no
   read surface exposes `resolution_note` dates yet, so the exemption is
   evaluable only for the running plan's own triage). Name every closed item
   AND every surviving candidate in the close-out report. Major and critical
   candidates are always named, never auto-closed: their review history may
   precede current priorities.

3. **Batch hygiene.** A batch minor finding ("N minors, deferred") must name
   its itemization artifact (`rsa_…`) in its `body` so a later sweep can read
   the individual list — an un-cited batch is untriageable.
