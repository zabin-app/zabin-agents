# Domain Profiles

Each profile tells the [studio overlay](../SKILL.md) how one medium maps onto the conductor's phases, cards, waves, gates, and review dimensions. A profile is a default, not a rule: the plan may adapt it, and every creative-direction choice it implies (length, format, audience) is confirmed by the human in State 1.

## Evidence labels

Guidance below is labelled by where it comes from:

- **Source** — backed by a cited publication or platform documentation.
- **Practice** — common craft or production practice, or this pack's own convention. It is a sensible default, not an established fact; adjust it to the project's bible.

Sources cited:

| Key | Reference | What it supports here |
|---|---|---|
| [AR] | Huot et al., *Agents' Room: Narrative Generation through Multi-step Collaboration*, arXiv:2410.02603 | Decomposing narrative writing into planning and writing subtasks handled by specialized agents improves long stories over single-pass generation. |
| [DOC] | Yang et al., *DOC: Improving Long Story Coherence With Detailed Outline Control*, arXiv:2212.10077 | A detailed, hierarchical outline written before drafting, and drafting held to it, improves long-range plot coherence and outline relevance. |
| [DRAM] | Mirowski et al., *Co-Writing Screenplays and Theatre Scripts with Language Models* (Dramatron), arXiv:2209.14958 | Hierarchical script generation — title, characters, story beats, location descriptions, then dialogue — builds the structural context long-form scripts need. |
| [YT-RET] | YouTube Help, *Measure key moments for audience retention*, support.google.com/youtube/answer/9314415 | The Intro metric is the share of viewers still watching after the first 30 seconds; a strong intro matches the title and thumbnail's promise; compelling content should come earlier because audience size typically decreases over a video. |
| [YT-CH] | YouTube Help, *Video Chapters*, support.google.com/youtube/answer/9884579 | Manual chapters are timestamps in the description: the first starts at 00:00, at least three in ascending order, each at least 10 seconds long. |
| [FTN] | Fountain syntax, fountain.io/syntax | Plain-text screenplay markup: scene headings, character cues, dialogue, transitions. |

## Shared conventions

These apply to every profile.

- **Outline before draft.** Every profile has an outline or brief phase that completes and merges before drafting starts, and drafting cards cite the outline unit they realize. Source: [DOC], [DRAM], [AR].
- **Bible as shared state.** Producers read the bible and report new facts; only `bible_keeper` cards write it. This plays the role of the shared scratchpad that coordinates specialized agents in [AR]. Practice: the split into producer and bible keeper is this pack's convention.
- **Bible phase first when absent.** Phase 0 records the approved creative-direction decisions (voice, format, audience, length budget) so every later card can name its `bible_paths`.
- **Card size.** One card produces one unit — a chapter or scene, one script segment, one screenplay scene or a short run of scenes — small enough for one validator pass. Practice.
- **Budgets with tolerance.** Each drafting card states a length budget and tolerance (for example 3,000 words ±15%); the assembly length gate checks the total. Practice.
- **Assembly gates.** Every profile defines `order`, `length`, and `coverage` checks; a profile adds `format` or another check where it has a mechanical rule. Gate names are `wave-<n>-assembly-<check>`. Assembled output is written under the run's artifact root, never into the repository.
- **Review dimension models.** Dimensions use the registry tier of their role: `fact_rights` is `deep` (`opus` in the Claude Code adapter); `structure`, `craft`, `continuity`, and `audience` are `balanced` (`sonnet`).

Dimension keys and their roles:

| Key | Registry role | Agent type (Claude Code) |
|---|---|---|
| `structure` | `structure_reviewer` | `structure-reviewer` |
| `craft` | `craft_reviewer` | `craft-reviewer` |
| `continuity` | `continuity_checker` | `continuity-checker` |
| `fact_rights` | `fact_rights_reviewer` | `fact-rights-reviewer` |
| `audience` | `audience_reviewer` | `audience-reviewer` |

## Book (fiction)

### Phase template

| Phase | Cards | Role | Notes |
|---|---|---|---|
| 0 Bible (when absent) | style guide, characters, locations, timeline, glossary | `bible_keeper` | Records approved premise, tone, POV, tense, audience, length budget. |
| 1 Outline | premise and synopsis, chapter-and-scene outline | `producer` | A detailed hierarchical outline: acts → chapters → scenes, each with its beats. Source: [DOC]. |
| 2..k Drafting | one card per chapter (or per scene for long chapters) | `producer` | One phase per act or chapter range keeps waves reviewable. Practice. |
| between waves | bible updates from `bible_updates_needed` | `bible_keeper` | Never in the same wave as drafting. |
| k+1.. Revision | developmental, line, copyedit, proofread passes | `producer` | See [Editing order for books](#editing-order-for-books). |

### Artifact layout

```text
bible/style-guide.md
bible/characters/<name>.md
bible/locations/<place>.md
bible/timeline.md
bible/glossary.md
outline/outline.md
manuscript/chNN.md            # one file per chapter, or
manuscript/chNN/sMM.md        # one file per scene inside a chapter directory
```

`NN` and `MM` are zero-padded so lexical order is reading order.

### Parallelism

- Default: sequential. Consecutive chapters share narrative state — who knows what, where everyone is, what has changed — so each drafting card `depends_on` the previous one within its storyline. Practice.
- Parallel only when the outline fixes each unit's beats and the units do not depend on each other's text: separate POV storylines that do not meet in the range, or interludes. Practice, consistent with outline-controlled drafting in [DOC].
- Revision passes over different chapters are parallel-safe once the developmental pass has fixed structure.

### Review dimensions

- Default: `structure`, `craft`, `continuity`, `audience`.
- Optional: `fact_rights` — enable for historical fiction, real persons, real brands or places portrayed critically, quoted lyrics or poems, or sensitive subject matter.

### Assembly gates

| Check | What it verifies |
|---|---|
| `order` | `manuscript/` concatenates in outline order; every file maps to one outline unit. |
| `length` | Total words against the budget in the bible; each chapter within its card's tolerance. |
| `coverage` | Every outline chapter and scene has a file, and no file lacks an outline unit. |
| `format` | Chapter heading convention and scene-break marker as the style guide defines them. Practice. |

## Book (nonfiction)

### Phase template

| Phase | Cards | Role | Notes |
|---|---|---|---|
| 0 Bible (when absent) | thesis, voice, style guide, sources register, glossary | `bible_keeper` | Records the approved thesis, audience, reading level, and citation style. |
| 1 Research | per-chapter research notes and source lists | `producer` | Written from State 1 `external_researcher` evidence the cards cite; contested claims stay in plan risks. |
| 2 Outline | chapter-by-chapter argument outline | `producer` | Each chapter states its claim, evidence, and takeaway. Source: [DOC] for outline-first; the argument framing is practice. |
| 3..k Drafting | one card per chapter | `producer` | Parallel when the outline is fixed (below). |
| between waves | sources and terminology updates | `bible_keeper` | Sources register entries cite the research note they came from. |
| k+1.. Revision | developmental, line, copyedit, proofread | `producer` | See [Editing order for books](#editing-order-for-books). |

### Artifact layout

```text
bible/thesis.md
bible/voice.md
bible/style-guide.md
bible/sources.md              # citation keys → full references
bible/glossary.md
research/chNN-notes.md
outline/outline.md
manuscript/chNN.md
```

### Parallelism

- Chapters whose outline entries fix the argument and that cite disjoint material can draft in parallel. Practice.
- Chapters that build on a previous chapter's argument or definitions `depends_on` it.
- A chapter never drafts in the same wave as the research card for its own notes.

### Review dimensions

- Default: `structure`, `craft`, `fact_rights`, `audience`. `fact_rights` is **mandatory** for nonfiction.
- Optional: `continuity` — recommended for long books, where terminology and figures repeat across chapters.

### Assembly gates

| Check | What it verifies |
|---|---|
| `order` | Chapters concatenate in outline order. |
| `length` | Total words against budget; each chapter within tolerance. |
| `coverage` | Every outline chapter has a file and every file an outline entry. |
| `citations` | Every citation key used in `manuscript/` resolves in `bible/sources.md`. Practice. |

## YouTube video

### Phase template

| Phase | Cards | Role | Notes |
|---|---|---|---|
| 0 Bible (when absent) | channel voice, video format | `bible_keeper` | Format records target runtime, speaking rate, segment pattern, call-to-action policy. |
| 1 Research and brief | research brief with segment outline | `producer` | `external_researcher` evidence for claims, sources, and platform data. |
| 2 Packaging | title and hook options | `producer` | Before scripting: the opening must deliver what title and thumbnail promise. Source: [YT-RET]. |
| 3 Script | one card per segment | `producer` | Hook segment first in priority; others parallel once the brief fixes boundaries. |
| 4 Production | b-roll and shot list | `producer` | Depends on every script segment it covers. |
| 5 Publish | description with chapters | `producer` | Chapter timestamps derive from segment lengths. Source: [YT-CH]. |

### Artifact layout

```text
bible/voice.md
bible/format.md
research/brief.md
packaging/titles-hooks.md
script/NN-segment.md          # e.g. script/01-hook.md, script/02-context.md
production/broll-shotlist.md
publish/description-chapters.md
```

### Parallelism

- Segments draft in parallel once `research/brief.md` fixes each segment's purpose, claims, and runtime. A segment that pays off another (a callback, a reveal) `depends_on` it. Practice.
- The hook segment is reviewed against `packaging/titles-hooks.md`; draft it first or in the first wave. Source: [YT-RET] for why the first 30 seconds matter; the ordering is practice.
- Production and publish cards depend on the script cards they describe; never parallel with them.

### Review dimensions

- Default: `audience`, `fact_rights`, `structure`, `craft`. `audience` and `fact_rights` are **mandatory** for YouTube: claims, footage and music rights, and platform fitness are the main hazards.
- Optional: `continuity` — enable for a series where episodes share facts, running jokes, or characters.

### Assembly gates

| Check | What it verifies |
|---|---|
| `order` | `script/` concatenates in the brief's segment order. |
| `runtime` | Script words ÷ the speaking rate in `bible/format.md` against target runtime. Practice: measure your own rate; 130–160 words per minute is a common narration range. |
| `coverage` | Every segment in the brief has a script file; the shot list covers every segment. |
| `chapters` | `publish/description-chapters.md` starts at 00:00, lists at least three ascending timestamps, each chapter at least 10 seconds. Source: [YT-CH]. |
| `hook` | The first segment's runtime estimate fits the first 30 seconds and names the promise from the chosen title. Source: [YT-RET] for the 30-second window; the check itself is practice. |

## Short film and film

### Phase template

| Phase | Cards | Role | Notes |
|---|---|---|---|
| 0 Bible (when absent) | characters, world, tone and style, format | `bible_keeper` | Records the approved genre, runtime target, rating constraints. |
| 1 Development | logline and treatment, beat sheet | `producer` | Hierarchy first: logline, characters, beats, locations, then dialogue. Source: [DRAM]. |
| 2..k Screenplay | one card per scene or short scene run | `producer` | Act or sequence per phase. |
| k+1 Breakdown | one card per scene breakdown | `producer` | Cast, props, locations, wardrobe, effects per scene. |
| k+2 Production | shot list | `producer` | Depends on screenplay and breakdown of the scenes it covers. |

### Artifact layout

```text
bible/characters/<name>.md
bible/world.md
bible/tone.md
bible/format.md
development/logline-treatment.md
screenplay/sceneNNN.fountain
breakdown/sceneNNN.md
production/shotlist.md
```

`NNN` is zero-padded scene order. Screenplay files use Fountain. Source: [FTN].

### Parallelism

- Default: sequential within a sequence; scenes share characters' state and set up each other's payoffs. Practice.
- Parallel only for scenes the beat sheet fixes and that share no unresolved state (separate storylines, montage pieces). Source: [DRAM] for beats-before-dialogue; the parallelism rule is practice.
- Breakdown cards are parallel-safe with each other once their scenes have merged; each depends on its own scene.

### Review dimensions

- Default: `structure`, `craft`, `continuity`, `audience`. `craft` covers screenplay format.
- Optional: `fact_rights` — **mandatory** for documentary, biopic, or historical work, and for any script naming real people, brands, or licensed music.

### Assembly gates

| Check | What it verifies |
|---|---|
| `order` | `screenplay/` concatenates in beat-sheet order into one Fountain document. |
| `length` | Estimated runtime against target. Practice: about one formatted page per minute of screen time. |
| `coverage` | Every beat has a scene and every scene a breakdown; the shot list covers every scene. |
| `format` | Fountain lint: every scene starts with a scene heading (`INT.`/`EXT.` or a forced heading), character cues are uppercase, no stray markup. Source: [FTN] for the syntax; the lint selection is practice. |

## Editing order for books

Book revision runs from large to small so later passes do not polish text an earlier pass will cut. Practice: this is the conventional order of editorial passes in book publishing.

| Pass | Changes | Studio mapping |
|---|---|---|
| Developmental | Structure, arc or argument, pacing, chapter purpose, cuts and additions. | The State 6 review (round 0) of each drafting phase, led by `structure` (and `audience`). Taskable findings become producer cards in a dedicated revision phase; the follow-up ratchet then applies to that phase. |
| Line | Voice, sentence craft, clarity, rhythm, dialogue. | A revision phase reviewed with `craft` first; one producer card per chapter, parallel-safe once structure is fixed. |
| Copyedit | Consistency, grammar, usage, style-sheet conformance, facts in passing. | A revision phase reviewed with `continuity` and `craft` (plus `fact_rights` for nonfiction); the style sheet lives in `bible/style-guide.md`, kept current by `bible_keeper` cards. |
| Proofread | Typos and formatting on the near-final text. | A final light phase; `format` and `order` assembly gates carry most of the weight; review with `craft` only. |

Each pass is its own phase with its own `PHASE_BASE`, so each gets one review round 0 and at most two follow-up rounds — never a third round to fold a later pass into an earlier one.
