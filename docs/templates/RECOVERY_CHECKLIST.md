# Round 1–5 recovery evidence checklist

- [ ] Preserve the original database, dumps, signed manifests and signing keys.
- [ ] Identify the approved round/attempt, rules digest and last known checkpoint.
- [ ] Restore to a new `tth_recovery_*` database and migrate it separately.
- [ ] Confirm restored team sessions are revoked and session versions incremented.
- [ ] Keep recovery traffic isolated from the working application's database.
- [ ] Stop/persist all LIVE/FROZEN cohort rounds before reconciliation revokes shared access.
- [ ] Compare signed record inventories; list missing, changed and additional records.
- [ ] Check team-retained receipts against exact stored decisions.
- [ ] Review control events, live/frozen phases, cutoff and active elapsed time.
- [ ] Account for changes after the last checkpoint; absence from a checkpoint is not proof of nonexistence.
- [ ] Review numbered paper slips, assigned desks and writer-isolation evidence if paper was used.
- [ ] For Round 3, verify every saved source revision, final/cutoff/no-submission record, source hash, workstation and reviewed judgment.
- [ ] For Rounds 2/4, verify original committed batches, score revisions, question voids and faculty criterion sheets.
- [ ] For Round 5, use a v3 checkpoint and establish its exact signed Round 1–4 final carry-over dependencies before approval.
- [ ] Verify frozen question/reveal versions, every window/closure, original press UUID/timestamps, host completion/priority evidence and reviewed original/superseding ledgers.
- [ ] Reproduce stage/carried totals, original last-correct completion and retained provisional/final winner; confirm empty next-round qualifiers and only one event winner.
- [ ] Confirm restored windows remain closed, historical session tombstones are revoked and old requests cannot create presses in a new window.
- [ ] Verify frozen faculty panels/slots and retained faculty/roster approvals; reconcile missing account identities separately.
- [ ] Preserve withdrawal/disqualification restrictions and revoke sessions created during review; never restore login cookies.
- [ ] Have a different authorized verifier approve reconciliation and close retained coverage incidents explicitly.
- [ ] Recheck standings, appeal status and qualification before releasing the recovered copy.
- [ ] Keep any unresolved gap material and block finalization; preserve conflicting copies.

Record incident IDs, private evidence references, maker/reviewer names, timestamps and disposition in the application. Decide any transition to the recovered copy as a separate operational action after validation.
