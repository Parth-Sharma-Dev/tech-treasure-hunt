# M8: supervised Round 3 coding

Implemented 8 October 2026. Participants use approved Python/C tools on the lab machine, then save source or text responses on the website. The website stores and freezes work, calculates marks from recorded lab verdicts, and publishes independently reviewed results. It does not execute participant code or provide an online runner.

## Prepare a round

1. In Django admin, configure Round 3 delivery as **Supervised Python/C competition (CODING)**. The real competition requires 45 active minutes and advancement count 10. Demo attempts may use explicitly approved shorter durations/cuts.
2. Assign the normal round owners, allowed tools, appeal/retention rules and supporting policies. Set the native coding policies below.
3. Add Coding tasks. Their category totals must be OUTPUT 15, DEBUG 25, FILL 20, SHORT 30 and LOGIC 10, totaling 100. There may be multiple questions in a category, up to 100 total tasks.
4. Each task needs a prompt, allowed response languages, points, a version and a private lab rubric. Debugging/fill/short tasks support PYTHON/C; output/logic tasks can also accept TEXT. Keep actual answers and hidden tests out of prompts/starter code.
5. A different verifier independently checks every task and its private rubric using **Independently verify selected coding tasks and lab rubric**. Draft edits clear verification. Released tasks cannot be edited, deleted or moved to another attempt.
6. Independently approve rules and mark READY. The task set, versions, test definitions and language settings become part of the frozen rules digest.

Required native policies, in addition to the normal required round policies:

```json
{
  "submission_policy": "locked_final_with_cutoff_autofinalize",
  "ranking_policy": "score_correct_tasks_final_time",
  "qualification_tie_policy": "block_exact_ties",
  "one_workstation_per_team": true,
  "score_precision": 3,
  "language_versions": {
    "PYTHON": "Organizer-approved lab Python version",
    "C": "Organizer-approved C standard and compiler version"
  }
}
```

Short coding tasks require a fixed private rubric such as:

```json
{
  "test_cases": [
    {"id": "case-1", "input": "private input", "expected": "private expected output"},
    {"id": "case-2", "input": "another private input", "expected": "another expected output"}
  ]
}
```

IDs must be unique, with at most 256 cases and a 64 KiB private rubric per task. Other categories use the approved all-or-nothing rubric. Partial SHORT marks are points × passed cases / total cases, rounded to three decimal places using half-up rounding. Fully correct task count requires all cases or the full non-SHORT verdict; rounded partial marks do not imply a fully correct task.

The manual's score → fully correct tasks → earlier final submission ordering is enforced. Equal final metrics remain tied. The default `block_exact_ties` keeps an unresolved qualification boundary provisional. Organizers may explicitly approve `supervised_reserve_task` before READY if they adopt an additional reserve procedure; the platform does not silently invent it. Reserve evidence/order affects qualification only, not original marks or final timestamps.

## Qualification and workstation assignment

Round 2's latest attempt must have independently published FINAL qualifiers. Opening/starting coding play requires at least one eligible team. Neither the seed command nor workstation assignment grants eligibility. Round 2's external score-entry/publication workflow remains M9, so current main-database Round 3 activation waits for that predecessor. Isolated tests use a clearly synthetic qualifying fixture rather than altering the application database.

Teams log in on their assigned lab browser. On **Open coding workspace** (`/rounds/{database-round-id}/coding`), they see their browser reference. Use `/staff/coding` as the controller to choose that active qualified session, record the physical workstation label and supporting station evidence, and assign it. A workstation label cannot be assigned to a second team. Reassignment is versioned/audited; a different old browser cannot keep saving work.

Only the assigned browser receives private tasks and writes during play. The supervisor must verify the physical one-machine arrangement; session binding is not hardware attestation. Lab networking must permit access to the competition site or its approved LAN deployment while enforcing the manual's other internet/AI restrictions.

## Participant saves and final submission

- Tasks open after LIVE for qualified assigned sessions. READY/LOBBY and unassigned/unqualified sessions receive no private task set.
- Use the textarea or upload a `.py`, `.c` or text response, select the allowed language and save. Source/text responses are bounded to 64 KiB each. File paths are not stored or executed.
- Changed responses autosave after a short idle interval; **Save response** also works manually. Every accepted save appends an immutable revision with its source hash, admission time and active elapsed time.
- Expected revisions reject stale writes from another tab. A successful save is durable only after the displayed acknowledgment. Local typing is not a submitted response.
- Unknown saves preserve their UUID/payload in session storage. Reload checks the latest saved action; **Retry same save** reuses the original request. A definite stale error requires reviewing confirmed saved work before replacing it.
- **Final submit and lock work** checks the complete saved revision vector and permanently freezes it. No later response can replace that final work. Keep its confirmation digest.
- At deadline or explicit ending, the last acknowledged revisions are finalized at the actual cutoff. Unsaved/late edits are excluded. Teams with no acknowledged responses receive an explicit NO_SUBMISSION record and zero marks, without an invented competitive submission time.
- The assigned live page can recover cutoff finalization when it observes expiry. Round-ending controls also finalize all eligible/participating teams under locks. Schedule the expiry command for users who close the browser; delayed persistence always uses the original cutoff.

```powershell
.venv/Scripts/python backend/manage.py end_expired_rounds --actor DEMO-content
```

Pause/resume uses the shared active clock. End also works while paused, freezing current saved work without adding frozen time. Deadline admission is read from PostgreSQL after Round → Team locks. Finalized work remains immutable across reload/retries/restarts; historical own final work is readable after play closes.

## Lab judging and independent review

1. End/persist the round. On `/staff/coding`, expand a frozen submission and download its exact source/rubric JSON if needed. Evaluate those immutable versions in the approved lab tools.
2. Mark all-or-nothing correctness for OUTPUT/DEBUG/FILL/LOGIC. For SHORT, select only the fixed hidden case IDs that passed. Unsaved tasks cannot receive marks.
3. Supply lab execution references and supervisor final-time evidence. The proposal binds each task version/source hash and the supervisor identity/time captured at final submission; users cannot invent earlier final timestamps.
4. Propose the lab judgment. A different authorized verifier independently checks source, tests, marks and time evidence, then approves or rejects it.
5. Approved judgments append immutable revisions. Rejudging supersedes the effective marks instead of adding points. Rejected/stale proposals do not replace the previous approved score.
6. On `/staff/results`, select Round 3 and use the normal two-person provisional/final publication workflow. All saved bundles need reviewed judgments; pending lab proposals, evidence gaps, material incidents, unresolved ties and the appeal window block finalization.

Rank uses score descending, fully correct tasks descending, then earlier supervisor-confirmed final submission. Team-code ordering stabilizes display only. Published tables include fully correct count and the precise final timestamp. Private source, rubrics, test IDs/log references and pending judgments are not participant results.

Changed scoring metrics require revised provisional results and a restarted appeal window. Final publication creates immutable qualifiers, which gate Round 4. Post-final rejudging is rejected; later-round supersession/adjudication remains a separate workflow.

## Demo preparation and local state

```powershell
.venv/Scripts/python backend/manage.py seed_coding_demo --actor DEMO-content
```

This DEBUG/demo-only command prepares five synthetic tasks and the native draft. It preserves existing task sets and refuses released attempts. It does not verify tasks, approve rules, publish information/results or fabricate Round 2 qualification. Confirm actual lab toolchain versions before verification.

Migrations 0011–0012 are applied locally, with a private signed backup at `.local/m8-before-migration-20261008.dump`. The main database has five unverified demo tasks; Round 3 remains DRAFT and Round 1 remains READY. Other competition data was not reset.

## Endpoints and evidence boundaries

| Endpoint | Purpose |
|---|---|
| GET /api/rounds/{id}/coding/submission | Own gated workspace, browser/station status, saved versions and final confirmation |
| POST /api/rounds/{id}/coding/tasks/{task}/response | Versioned, idempotent source/text save |
| POST /api/rounds/{id}/coding/finalize | Lock saved versions or recover cutoff finalization |
| GET /api/staff/coding/rounds | Authorized native coding attempts |
| GET /api/staff/rounds/{id}/coding | Workstation/submission/judgment desk |
| POST /api/staff/rounds/{id}/coding/workstation | Audited controller assignment/reassignment |
| GET /api/staff/rounds/{id}/coding/submissions/{submission} | Private frozen source and fixed rubric for lab judging |
| POST /api/staff/rounds/{id}/coding/judgment | Propose/approve/reject lab verdicts |

All writes require CSRF and action UUIDs. Staff pending actions preserve the original request for recovery. Existing publication APIs now support native Round 3 as well as Round 1. Current Round 1 signed reconciliation bundles remain Round 1 tooling; native coding recovery/export manifests are still part of M10, while full PostgreSQL backups include the new records.

Validation: 148 backend tests passed with all three real-browser integrations enabled; one opt-in load test was skipped. Eighty desktop/mobile browser checks, typecheck/build, Ruff, Django checks and migration checks passed. The new real-browser journey covers assignment → saved response → final lock → lab judgment → independent review → provisional publication. Backend tests additionally cover final qualification, exact ties, revised appeals and simultaneous same-revision saves. Real lab execution/network/physical supervision and deployed capacity require a separate rehearsal with actual content and tools.
