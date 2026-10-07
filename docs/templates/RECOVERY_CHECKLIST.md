# Round 1 recovery evidence checklist

- [ ] Preserve the original database, dumps, signed manifests and signing keys.
- [ ] Identify the approved round/attempt, rules digest and last known checkpoint.
- [ ] Restore to a new `tth_recovery_*` database and migrate it separately.
- [ ] Confirm restored team sessions are revoked and session versions incremented.
- [ ] Keep recovery traffic isolated from the working application's database.
- [ ] Compare signed record inventories; list missing, changed and additional records.
- [ ] Check team-retained receipts against exact stored decisions.
- [ ] Review control events, live/frozen phases, cutoff and active elapsed time.
- [ ] Account for changes after the last checkpoint; absence from a checkpoint is not proof of nonexistence.
- [ ] Review numbered paper slips, assigned desks and writer-isolation evidence if paper was used.
- [ ] Have a different authorized verifier approve reconciliation and close retained coverage incidents explicitly.
- [ ] Recheck standings, appeal status and qualification before releasing the recovered copy.
- [ ] Keep any unresolved gap material and block finalization; preserve conflicting copies.

Record incident IDs, private evidence references, maker/reviewer names, timestamps and disposition in the application. Decide any transition to the recovered copy as a separate operational action after validation.
