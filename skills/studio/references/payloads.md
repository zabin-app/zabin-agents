# Studio Payload Examples

Argument objects for the calls the [studio overlay](../SKILL.md) changes. Everything else — startup reads, plan shell, approval check, board, overlap, waves, verdicts, status hops, review rounds, action items — uses the conductor's [payload examples](../../conductor/references/payload-examples.md) and [planning payloads](../../conductor/templates.md) unchanged.

MCP objects below are the `arguments` of the named public tool and are host-neutral. Program objects (`research-sweep`, `implement-wave`, `review-diff`, `followup-investigate`) are the `args` shapes of the [Claude Code adapter](../../conductor/references/claude.md#workflow-programs), whose agent types are the kebab-case spelling of the registry ids. Replace example ids, paths, and SHAs; runtime-discovered schemas take precedence if the service evolves.

The running example is a YouTube explainer: a project at `/srv/creative/tide-explainer`, with an approved bible (`bible/voice.md`, `bible/format.md`), a merged research brief, and chosen packaging.

## Creative-direction question

`ask_user_questions` — State 1. Agents may research and propose the options; the human chooses.

```json
{
  "project_id": "prj_example",
  "questions": [
    {
      "prompt": "Target runtime for the tide explainer?",
      "options": ["6-8 minutes", "10-12 minutes", "Under 60 seconds (Shorts)"]
    },
    {
      "prompt": "Primary audience?",
      "options": ["Curious general viewers", "High-school science students", "Sailors and coastal residents"]
    }
  ]
}
```

Carry the answers into the plan's `decisions` section, citing the question, so a Bible-phase card can record them.

## `research-sweep`: mixed sources

State 1. `project-researcher` answers from the project's own files and history; `external-researcher` answers from outside sources and platform documentation.

```json
{
  "questions": [
    {
      "label": "voice-rules",
      "agentType": "project-researcher",
      "q": "What does bible/voice.md require for openings, second-person address, and on-screen text, and do earlier scripts under script/ follow it?"
    },
    {
      "label": "format-budget",
      "agentType": "project-researcher",
      "q": "What runtime, speaking rate, and segment pattern does bible/format.md declare, and what did the most recent merged script actually measure?"
    },
    {
      "label": "tide-mechanism",
      "agentType": "external-researcher",
      "q": "What is the accepted explanation of why most coasts see two high tides a day, and which primary or authoritative sources state it?"
    },
    {
      "label": "chapter-rules",
      "agentType": "external-researcher",
      "q": "What does YouTube's own help documentation require for manual video chapters in a description?"
    }
  ]
}
```

Persist the synthesis with `record_research_artifact` as the conductor requires; verified claims may enter the brief, contested ones go to plan risks.

## `add_phase_tasks`: two script segments and a bible card

State 2. The Script phase of the YouTube profile (here `phase_index` 3). The two segments are parallel because the brief fixes their boundaries; the bible card `depends_on` both, so it never shares a wave with drafting.

```json
{
  "project_id": "prj_example",
  "plan_id": "fplan_example",
  "phase_index": 3,
  "tasks": [
    {
      "title": "Script segment 01: hook",
      "description": "Objective: write the opening hook of the tide explainer. Acceptance: (1) 60-75 words, which is 24-30 seconds at the 150 wpm speaking rate in bible/format.md; (2) the first sentence states the promise of the chosen title T2 in packaging/titles-hooks.md; (3) no channel intro, greeting, or subscribe request before that promise; (4) ends on the question segment 02 answers, as listed for segment 02 in research/brief.md; (5) conforms to bible/voice.md (second person, present tense, no jargon without a gloss) and bible/format.md (segment file layout: VO lines, then bracketed ON-SCREEN notes). Write only script/01-hook.md. Read: bible/voice.md, bible/format.md, research/brief.md, packaging/titles-hooks.md. Report any new recurring phrase or fact under bible_updates_needed; do not edit bible/. Verification: wc -w on the VO lines.",
      "complexity": "moderate",
      "labels": ["script", "hook"],
      "write_files": ["script/01-hook.md"],
      "depends_on": []
    },
    {
      "title": "Script segment 02: why two tides",
      "description": "Objective: write segment 02, which explains why most coasts see two high tides a day. Acceptance: (1) 380-460 words, which is 2.5-3 minutes at 150 wpm per bible/format.md; (2) covers claims C1-C3 from research/brief.md section 2 and no other factual claims; (3) every claim carries its source key from research/brief.md in a bracketed SOURCE note; (4) includes at least two ON-SCREEN notes describing the diagram beats listed for segment 02 in research/brief.md; (5) ends with the transition line into segment 03 named in the brief; (6) conforms to bible/voice.md and bible/format.md. Write only script/02-why-two-tides.md. Read: bible/voice.md, bible/format.md, research/brief.md. Report new terms or facts under bible_updates_needed; do not edit bible/. Verification: wc -w on the VO lines; grep each SOURCE key against research/brief.md.",
      "complexity": "moderate",
      "labels": ["script"],
      "write_files": ["script/02-why-two-tides.md"],
      "depends_on": []
    },
    {
      "title": "Bible: record terms and phrasing from segments 01-02",
      "description": "Objective: record in the bible the facts the merged segments 01 and 02 established, from their bible_updates_needed reports. Acceptance: (1) every new term used in script/01-hook.md or script/02-why-two-tides.md and absent from bible/voice.md gets a glossary-style entry in bible/voice.md with its gloss; (2) any recurring sign-off or catchphrase they introduce is recorded under the voice rules; (3) every entry cites its source as path:line in the merged script; (4) conflicts with existing entries are kept, marked, and reported, never overwritten; (5) bible/voice.md stays under 400 lines. Write only bible/voice.md. Read: script/01-hook.md, script/02-why-two-tides.md, bible/voice.md. Verification: wc -l bible/voice.md; search the changed lines for a source citation on each entry.",
      "complexity": "simple",
      "labels": ["bible"],
      "write_files": ["bible/voice.md"],
      "depends_on": [0, 1]
    }
  ]
}
```

## `implement-wave`: producer and artifact validator

State 4, the wave holding the two segments. `content` is the identity stub only; the card fetched with `start_task` is the producer's single spec. `objective`, `acceptanceCriteria`, and `writeFiles` go to the validator stage alone, `biblePaths` lists the bible files the validator checks conformance against (also named in `acceptanceCriteria`); the validator also receives the producer's returned `docUpdatesNeeded`. `validatorType: artifact-validator` is mandatory on every studio call.

```json
{
  "workingBranch": "main",
  "baseRef": "5d1c0a7e9b2f4c6d8e0a1b3c5d7e9f1a2b4c6d8e",
  "validatorType": "artifact-validator",
  "validatorModel": "haiku",
  "tasks": [
    {
      "slug": "seg-01-hook",
      "complexity": "medium",
      "agentType": "producer",
      "worktreePath": "/srv/creative/tide-explainer/.claude/worktrees/seg-01-hook",
      "content": "ZABIN DISPATCH — identity stub (the card is your only spec; fetch it with start_task). project_id: prj_example. task_id: tsk_seg01. agent_name: producer-seg-01-hook. MCP surface: worker. worktree: /srv/creative/tide-explainer/.claude/worktrees/seg-01-hook. branch: studio/seg-01-hook. base_branch: main. base_sha: 5d1c0a7e9b2f4c6d8e0a1b3c5d7e9f1a2b4c6d8e. lease_ttl_secs: 3600. Lifecycle: start_task, produce only write_files, self-verify, commit, finish_task; keep the lease at in_review. Report new facts in docUpdatesNeeded (bible_updates_needed); never edit bible/.",
      "objective": "Write the opening hook of the tide explainer.",
      "acceptanceCriteria": [
        "60-75 words of VO (24-30 seconds at 150 wpm per bible/format.md).",
        "First sentence states the promise of title T2 in packaging/titles-hooks.md.",
        "No channel intro, greeting, or subscribe request before that promise.",
        "Ends on the question research/brief.md lists for segment 02.",
        "Conforms to bible/voice.md and bible/format.md; quote any conflicting line."
      ],
      "biblePaths": ["bible/voice.md", "bible/format.md"],
      "writeFiles": ["script/01-hook.md"]
    },
    {
      "slug": "seg-02-why-two-tides",
      "complexity": "medium",
      "agentType": "producer",
      "worktreePath": "/srv/creative/tide-explainer/.claude/worktrees/seg-02-why-two-tides",
      "content": "ZABIN DISPATCH — identity stub (the card is your only spec; fetch it with start_task). project_id: prj_example. task_id: tsk_seg02. agent_name: producer-seg-02. MCP surface: worker. worktree: /srv/creative/tide-explainer/.claude/worktrees/seg-02-why-two-tides. branch: studio/seg-02-why-two-tides. base_branch: main. base_sha: 5d1c0a7e9b2f4c6d8e0a1b3c5d7e9f1a2b4c6d8e. lease_ttl_secs: 3600. Lifecycle: start_task, produce only write_files, self-verify, commit, finish_task; keep the lease at in_review. Report new facts in docUpdatesNeeded (bible_updates_needed); never edit bible/.",
      "objective": "Write segment 02 explaining why most coasts see two high tides a day.",
      "acceptanceCriteria": [
        "380-460 words of VO (2.5-3 minutes at 150 wpm per bible/format.md).",
        "Covers claims C1-C3 from research/brief.md section 2 and no other factual claims.",
        "Every claim carries a SOURCE key that exists in research/brief.md.",
        "At least two ON-SCREEN notes matching the diagram beats in research/brief.md.",
        "Ends with the transition line into segment 03 named in research/brief.md.",
        "Conforms to bible/voice.md and bible/format.md; quote any conflicting line."
      ],
      "biblePaths": ["bible/voice.md", "bible/format.md"],
      "writeFiles": ["script/02-why-two-tides.md"]
    }
  ]
}
```

The bible card runs in a later wave with `"agentType": "bible-keeper"` and the same `validatorType`. Translate the program's `qualityGate`, `status`, and validator verdict to MCP vocabulary exactly as the adapter note's table says.

## Assembly gates

State 4 integration gates after the wave merges, via `record_gate_results`, phase-scoped and named `wave-<n>-assembly-<check>`. The commands write only under the run's artifact root (`$ARTIFACT_ROOT`, outside the repository).

```json
{
  "project_id": "prj_example",
  "entries": [
    {
      "phase_id": "pph_script",
      "name": "wave-1-assembly-order",
      "command": "cat $(ls script/*.md | sort) > $ARTIFACT_ROOT/script-assembled.md",
      "status": "passed",
      "detail": "Segments 01-02 assembled in brief order; segments 03-05 pending in later waves."
    },
    {
      "phase_id": "pph_script",
      "name": "wave-1-assembly-runtime",
      "command": "wc -w on the VO lines of $ARTIFACT_ROOT/script-assembled.md",
      "status": "passed",
      "detail": "Running total 512 VO words = 3.4 min at 150 wpm; on track for the 8 min budget."
    },
    {
      "phase_id": "pph_script",
      "name": "wave-1-assembly-coverage",
      "command": "compare research/brief.md segment list with script/ file names",
      "status": "passed",
      "detail": "Every segment due by this wave has a file; no orphan script files."
    }
  ]
}
```

Check every entry's outcome in `results` by index, as the conductor requires for any batch.

## `review-diff`: YouTube dimension set

State 6 over the Script phase. `dimensions` replaces the code reviewers; `docs` points every reviewer at the bible.

```json
{
  "diffRange": "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678..HEAD",
  "changeType": "feature",
  "taskFiles": [],
  "docs": ["bible/voice.md", "bible/format.md", "research/brief.md", "packaging/titles-hooks.md"],
  "dimensions": [
    { "key": "audience", "agentType": "audience-reviewer", "model": "sonnet" },
    { "key": "fact_rights", "agentType": "fact-rights-reviewer", "model": "opus" },
    { "key": "structure", "agentType": "structure-reviewer", "model": "sonnet" },
    { "key": "craft", "agentType": "craft-reviewer", "model": "sonnet" }
  ]
}
```

Add `{ "key": "continuity", "agentType": "continuity-checker", "model": "sonnet" }` for a series. Check the result for `refused` (verdict `null`) and `missingDimensions`: either blocks approval and the run must be repeated, never read as a pass. Record the normalized verdict with `record_review_round` and file findings with `add_action_items` as the conductor's State 6 requires.

## `followup-investigate`

State 7, round 1, for confirmed Critical and Major findings only. The top-level `agentType` is `project-researcher`; each `fact_rights` finding about a real-world fact is routed with a per-issue `agentType: external-researcher` and self-contained text, because that agent cannot read the project.

```json
{
  "agentType": "project-researcher",
  "issues": [
    {
      "label": "c2-unsourced",
      "agentType": "external-researcher",
      "text": "Self-contained fact check. Artifact script/02-why-two-tides.md:14 claims: \"the Moon's pull is the only cause of the second tidal bulge\". The project's own source statement (research/brief.md C2) says the second bulge arises from the difference in gravitational pull across Earth relative to the Earth-Moon system. Determine from authoritative sources whether the artifact's claim is accurate, and cite the sources."
    },
    {
      "label": "hook-promise",
      "text": "Major (audience): script/01-hook.md:1-3 opens with a greeting before the promise of title T2; bible/format.md:8 requires the promise first."
    }
  ]
}
```

Taskable diagnoses become `producer` fix cards on the named script files (or `bible_keeper` cards when the bible itself is wrong), each carrying its `action_item_id`.
