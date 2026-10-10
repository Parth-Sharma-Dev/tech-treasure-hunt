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
code yields a keyword for Round 2; ties use earlier completion. **The existing
mission-bound scoring implementation does not implement this independent code
pool.** Its gameplay, concurrency, score/keyword, correction and recovery behavior
must be updated and validated before these real missions are released. Code/keyword
pairs are now stored in the independent pool described below. Requested behavior
is retained privately with the riddle source.

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

This completes content ingestion for the supplied material. **Participant gameplay
still uses the old mission-bound validator/scorer.** Punctuation submission support,
the independent claim transaction, exclusive claims across teams, the three-success
limit, code-based keyword delivery, standings and signed evidence/recovery must be
implemented and tested before live rehearsal. No code claim or competitive score
was created by importing the inventory.
