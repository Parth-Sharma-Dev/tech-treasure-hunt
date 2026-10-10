# Actual event content preparation

10 October 2026: the organizer supplied the real round names, Round 1 riddle PDF,
Round 2 quiz DOCX and five CSE faculty contacts. Physical rehearsal is planned for
11 October; this record does not certify that rehearsal.

| Round | Name | Database ID | Imported content |
|---|---|---|---|
| 1 | QR Mission Hunt | 13 | 13 riddle missions |
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
pairs are still awaited. Requested behavior is retained privately with the riddle source.

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
