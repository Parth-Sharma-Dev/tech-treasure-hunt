# Actual event content preparation

10 October 2026: the organizer supplied the real round names, Round 1 riddle PDF,
Round 2 quiz DOCX and five CSE faculty contacts. Physical rehearsal is planned for
11 October; this record does not certify that rehearsal.

| Round | Name | Database ID | Imported content |
|---|---|---|---|
| 1 | QR Mission Hunt | 13 | 25 locations: 13 riddles and 12 empty image/symbol placeholders; 168 independent codes |
| 2 | Tech Quiz | 14 | Private bank of 30 questions, four options each and organizer answer key |
| 3 | Crack The Code | 15 | Empty draft; actual tasks not supplied |
| 4 | Faculty Interaction | 16 | Five unpublished real faculty profiles with supplied contacts |
| 5 | Reach The Treasure | 17 | Empty draft; content to follow |

These are separate real-cohort DRAFT attempts. Existing demo attempts, released
rules, results and evidence are preserved. No real roster, approval, qualification,
scores or publication was created. Draft clocks/settings require event configuration;
their model defaults are not approved event durations.

Round 1 participant hints contain only the riddles. The PDF's location headings are
retained as private organizer location keys. Missions have no answer verifiers or
keywords, are unavailable and unverified, and have no assigned physical QR placement.
Random mission access tokens/fallback identifiers are navigation identifiers, not
the independent collectible answer codes. Image/symbol missions remain to be supplied.

The organizer clarified a new Round 1 contract: codes are independent of missions;
any mission page supplies a code input; a team can successfully claim at most three
codes; a code successfully claimed by one team cannot be claimed by another; each
code yields a keyword for Round 2; ties use earlier completion. This behavior is now
implemented for the independent-code rules; old frozen attempts retain their
mission-bound rules. Code/keyword pairs are stored in the independent pool described
below. Real missions remain drafts pending complete content and event configuration.

Round 2 remains an external quiz with Wayground raw Score and exported answering
duration for ties. The DOCX's "1 point each" note is retained as source text and does
not replace that confirmed results contract. No native website quiz was created.
The question bank and organizer answer key are stored in private `EventContentSource`
records, accessible through staff admin, with byte-exact originals and SHA-256
checksums. They are not added to participant responses. Faculty consent, photos,
public contact release and assignments are not inferred from draft ingestion.

The ignored `.local/actual-content-manifest-20261010.json` and extraction script
retain the prepared import privately. `import_event_content --manifest <path>
--actor <authorized-content-user>` validates original checksums, imports atomically,
refuses a changed original or existing released real rounds, and preserves organizer
edits on repeat import. Do not commit original files, answers, location keys or phones.
Original source records are immutable; revisions need a separate reviewed workflow.

Before applying migration 0018 and importing, a signed PostgreSQL backup was saved
privately at `.local/before-actual-content-20261010.dump`. Database verification
confirmed exact riddle/location text, complete keyed questions, original bytes,
faculty contacts, draft states and empty mission answers/keywords. Repeating the
import created no duplicate content. Importer, faculty-placeholder and portal
regression tests passed **11 checks**; Ruff, Django system checks and migration
drift checks passed. Actual gameplay/rehearsal remains untested for the new code rule.

## Independent codes and complete location inventory

Later on 10 October, the supplied CSV was validated and imported into `HuntCode`
for real Round 1 ID 13. All 168 codes are distinct even when ignoring ASCII letter
case, exactly six characters long and contain punctuation. Original case and
punctuation are preserved in storage. The organizer confirmed submissions should
ignore letter case while preserving punctuation. A database constraint prevents
case-only duplicate code identities within a round. Codes have no mission foreign
key or location assignment. The original CSV is retained byte-exactly in a private
`EventContentSource` record with checksum and the confirmed matching policy.

The organizer authorized random keyword assignment. Each code received one keyword
from the quiz topics; keywords may repeat between codes. Assignment occurs at import
and persists rather than changing at submission or repeat import. Mission-level
keywords and answer verifiers remain empty. A private code/keyword CSV is saved at
`.local/hunt-code-keywords-20261010.csv`; keep this organizer mapping private.

The complete inventory contains 25 locations. The original 13 riddle location keys
are preserved. Twelve additional locations have unavailable, unverified mission
placeholders with empty hints until their images/symbols arrive. The four huts use
temporary identifiers Jhopadi 1–4. Bus Stand and Gyan Mandir Corridor complete the
inventory. Location names remain private organizer metadata; they are not used as
the participant-facing hints.

`import_hunt_inventory --round 13 --csv <private-csv> --locations <private-json>
--actor <authorized-content-user>` validates counts, characters, case-insensitive
uniqueness and location ordering. It refuses released/demo targets and changed code
originals, preserves keywords on repeat import and rolls back location conflicts.
Migration 0019 and ingestion followed a private signed backup; another signed backup
after ingestion preserves random assignments. Exact codes, source bytes, all 25
locations, retained 13 riddles, empty placeholder clues and repeat-import stability
were verified in the application database. Ten focused inventory/import/portal
tests passed; Ruff, Django checks and migration drift checks passed.

This completed content ingestion for the supplied material. The subsequent gameplay
implementation below now connects the pool to participant submissions. No code claim
or competitive score was created by importing or configuring the actual inventory.

## Implemented independent-code gameplay

Round 1 ID 13 now has draft `independent-code-pool-v1` rules: `independent_pool`,
six printable ASCII characters, three successful claims maximum, one point per code,
168 codes, 25 locations and score-then-last-active-completion ranking. Letter case
is ignored; punctuation and leading characters are preserved. Duration, roster,
capacity, owners, advancement and other event inputs are still unapproved. The
round remains DRAFT with all clues unavailable/unverified and zero real claims.

During LIVE, eligible signed-in teams open a mission page and enter any valid pool
code there. A mission is a clue/navigation entry, not a scoring target. Several
codes can be submitted on the same page. The team lock enforces three successful
claims across all pages/tabs, and the code lock plus unique database link prevents
two teams claiming the same code. A duplicate owned code adds no credit; a code
claimed by another team reveals no keyword or claimant identity. Invalid codes do
not consume a successful slot. Existing wrong-attempt cooldown and rate controls
remain subject to approved rules. Paused, ended, expired, unopened, unavailable or
ineligible requests cannot claim a code. Identical retries recover the original
decision/receipt and never create another claim.

Each successful code gives its stored keyword and a signed receipt. Team progress
shows code claims and a score out of three; Round 2's released keyword list uses
code keywords. Closing or voiding a clue does not erase ownership or points earned
from an independent code. Standings rank by score descending, then original active
elapsed time of the last credited claim ascending; three-point teams use their
third-claim time. Pauses do not consume active time. Exact cutoff ties retain the
existing reviewed tie procedure. Provisional/final publication and qualification
retain independent review and appeal gates.

Rule approval freezes code digests, keyword mappings and source checksums. Another
verifier must approve an inventory prepared by the content maker. Signed exports
include source originals, independent codes, claims, decisions and receipts;
reviewed recovery reproduces the original code ownership, keyword mapping and
rankings. Legacy checkpoint inventories treat the new null code link as an absent
field so earlier mission evidence remains compatible. Legacy mission-answer
corrections and mission-based paper scoring are disabled for independent rounds;
pause and retain evidence/open an incident rather than using those incompatible
workflows. Older mission-bound attempts retain their existing workflows.

Validation: full backend **272 passed, 8 optional checks skipped**; full desktop/mobile
Chromium **134 passed**; final checkpoint/portal checks **22 passed**, final readiness
checks **20 passed**, final mission UI checks **12 passed**. Build, Ruff, Django system
and migration-drift checks passed. Tests use synthetic codes and isolated databases,
including same-code races, simultaneous third-slot requests, six claims on one
mission across two teams, timing-ranked final qualification and signed restore.
Migration 0020/0021 followed private signed backup
`.local/before-independent-gameplay-20261010.dump`; applying them and configuring
the real draft preserved 168 codes, 25 locations and zero actual claims. This is
local development validation; physical rehearsal is still scheduled separately.
