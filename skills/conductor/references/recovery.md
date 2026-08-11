# Zabin-First Recovery

Zabin is authoritative. The Phase 1 checkpoint is a minimal, redacted snapshot for state that the live read model cannot reconstruct; it is not a task ledger, plan document, review ledger, or source of ambient project identity.

The executable contract is [recovery-checkpoint.schema.json](../../../schemas/recovery-checkpoint.schema.json), implemented by [recovery_checkpoint.py](../../../scripts/recovery_checkpoint.py).

## Recovery order

1. Pin the explicit `project_id` and rediscover required MCP capabilities.
2. Read Zabin first: `get_pickup_context`, `get_pipeline_state`, paged `list_tasks`, paged `list_workspaces`, relevant `get_plan` pages, and `get_task` for active cards.
3. Inspect git with host read capabilities: primary branch/SHA/status, worktree list, branch heads, and commit ancestry. Do not mutate yet.
4. Construct the complete checkpoint key from known ids and SHA.
5. Load and validate the local checkpoint through the versioned recovery module.
6. Reconcile the authoritative Zabin projection with the checkpoint without writing either side.
7. Resume only after identity, lifecycle status, lease owner, phase/wave bases, verdicts, gates, action items, summaries, and commit mappings are consistent or their absence is explicitly understood.

Never read the checkpoint before Zabin and never copy local values into Zabin merely because they are present.

## Complete checkpoint identity

```json
{
  "project_id": "prj_example",
  "plan_id": "fplan_example",
  "phase_id": "pph_example",
  "wave_id": "wav_example",
  "task_id": "tsk_example",
  "sha": "42a4056677e5bcdc00b42dcb62cfa4cf0d4ddbb1"
}
```

All six fields are required. A guessed id or SHA selects the wrong checkpoint and is a hard stop.

## Required checkpoint shape

The current schema is `1.0.0` and requires every top-level field below:

```json
{
  "$schema": "https://zabin.dev/schemas/recovery-checkpoint.schema.json",
  "schema_version": "1.0.0",
  "key": {
    "project_id": "prj_example",
    "plan_id": "fplan_example",
    "phase_id": "pph_example",
    "wave_id": "wav_example",
    "task_id": "tsk_example",
    "sha": "42a4056677e5bcdc00b42dcb62cfa4cf0d4ddbb1"
  },
  "phase_base": "3423bbe9a5a596c558898d43b6cd2bc7fb491b1c",
  "payload_references": [],
  "task_verdict": {
    "round": 0,
    "verdict": null,
    "evidence": []
  },
  "gate_snapshots": [],
  "completion_summary_evidence": [],
  "action_item_resolutions": [],
  "commit_mappings": [],
  "retired_fields": []
}
```

Use the module's `build_checkpoint`, snapshot encoder, validator, redaction, atomic store, and reconciliation functions. Do not hand-roll a looser JSON file.

Checkpoint content is limited to:

- exact `phase_base`;
- full-payload references with content digests for research/review evidence;
- the task verdict and its evidence reference;
- closed, encoded gate snapshots;
- completion-summary evidence references;
- action-item resolution status and evidence;
- source, recorded, and merged commit mappings;
- explicit tombstones for retired fields.

No secret, bearer value, cookie, session id, credential, private key, or raw environment belongs in a checkpoint. Storage redacts recognized secret material and writes atomically with restrictive permissions.

## Reconciliation outcomes

| Outcome | Meaning | Action |
|---|---|---|
| `absent` | Neither source has the requested state. | Stop if the state is required; otherwise start a new, explicit lifecycle. |
| `consistent` | Canonicalized values agree. | Resume from authoritative Zabin state. |
| `zabin_only` | Zabin has state and no checkpoint exists. | Use Zabin; create a checkpoint only for a documented future read-model gap. |
| `checkpoint_only` | Local evidence exists but Zabin has no matching state. | Fail closed. Do not upload it automatically; verify project/key and escalate. |
| `conflict` | Both exist and differ. | Fail closed, preserve both redacted projections, and request an explicit resolution. |

Reconciliation reads Zabin before local state and never overwrites either side on conflict.

## Resume decision table

| Authoritative task state | Recovery action |
|---|---|
| `ready`, unclaimed | Eligible for a fresh worker after spec, dependency, workspace, and overlap checks. |
| `queued` or `executing`, live lease | Worker is active; monitor rather than duplicate dispatch. |
| `queued` or `executing`, expired lease | Wait for reaping to return it to `ready`, then re-read and dispatch. |
| `in_review`, held or expired-but-unreaped lease | Reconcile worker summary/commit/workspace evidence, run or recover validation, then use the conductor terminal hop under the worker name. |
| `validated`, held or expired-but-unreaped lease | Reconcile merge and integration evidence; complete only if all required gates passed. |
| `needs_rework` | Preserve the lease/branch evidence and follow the explicit rework path; never force a fresh claim while unready. |
| `completed` | Reconcile release hygiene, merge mapping, gates, and blockers; do not replay source work. |
| conflicting owner/status/workspace | Stop. Never steal a lease or rewrite another actor's workspace row. |

## Recovering bases and rounds

`PHASE_BASE` and each `WAVE_BASE` determine review and integration diff ranges. Recover them only from consistent Zabin wave records, git ancestry, and a matching checkpoint. If no unique value exists, stop; a plausible SHA is not evidence.

The latest scoped `record_review_round` in `get_pipeline_state` is the only follow-up counter. Checkpoint review evidence may prove what was reviewed, but it never creates a missing round or authorizes round 3.

## Schema evolution

Load checkpoints through explicit one-version-at-a-time migrations. Unknown versions, missing migrations, noncanonical snapshots, unsafe identities, and unexpected fields are errors. When a field becomes available from Zabin, remove it only through a `retired_fields` tombstone naming the reason and replacement.

Do not keep compatibility fields indefinitely and do not create a new Markdown fallback ledger.
