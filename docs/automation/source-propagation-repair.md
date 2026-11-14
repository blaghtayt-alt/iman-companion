# Source propagation repair — 14 November 2026

## Evidence and boundary

The implementation started from main `02873884cfd7862949460fe46d0626ee9a7fbe35`.
The preserved read-only audit is `Iman_Companion_Read_Only_Audit_2026-11-14.xlsx`.
The Arabic Fatiha 1:1 approved replacement was already in source; published book
bytes still contained the earlier paragraph. Other languages and collections
also had edited or uncatalogued readers. The historical review/source pins were
not updated through approved publication transactions, and source validation
ran before intake. Pages could succeed while book publication failed.

`books/regressions/source-propagation-20261114.json` records all 20 Fatiha source
comparisons and 283 material-file changes from the audit. Translation excerpts
are observed committed text, not newly invented review acceptance.
`source-reconciliation-20261114.json` preserves the latest 55 review entries in
271–329 (283, 288, 311 and 316 are absent from that file). Only the independently
recovered exact user correction at position 305 is applied by this repair.
Other wording conflicts remain explicit pending decisions.

## Automatic path

1. An approved publisher submits the existing exact source-publication
   transaction, including its reader and genuine review evidence.
2. Intake validates independent handoffs before source selection. A conflicting
   or invalid handoff is rejected; valid independent ones can be checkpointed.
   A normal fast-forward push and expected HEAD reject concurrent overwrites.
3. Code regressions use historical fixtures whose SHA256 pins are checked.
   The live app/source coverage audit separately rejects unapproved drift.
   An exact approved typed successor may supersede an historical baseline;
   the original audit is never overwritten or treated as a new approval.
4. Each scope enforces the existing source, coverage, provenance, reference and
   export gates. Eligible outputs enter the preparation queue. Repeated intake
   and unchanged preparations are idempotent.
5. Genuine Word and final visual checks bind the final candidate bytes. Existing
   release holds remain effective. Finalization intake publishes only accepted
   candidates and updates the individual and combined download inventory.
6. A separate status checkpoint runs even after a failure. Each notice is bound
   to the advertised DOCX and PDF hashes; missing/mismatched status never means
   current. Existing public editions can remain explicitly old while an update
   is pending. Withdrawn/removed members cannot use that retention path.
7. Download health hashes actual HTTP response bodies and every combined ZIP
   member even if the source freshness audit fails. Integrity and currency are
   separate results; an old file can pass integrity and remain pending.

## Required human work

Whole-material/translation review decisions and resolving conflicting approved
wording remain human decisions. Real Word execution needs the owned Windows
device; it was observed offline during this repair. Final visual acceptance is
for the final Word/PDF bytes, not a review of source text or a green website job.
Neither source registration nor publication is claimed complete merely because
the machinery and its synthetic lifecycle regressions pass.

## Operational reports

Actions artifacts include source-intake and source-update-status reports,
app-book coverage, preparation/publication receipts, renderer evidence and live
byte audits. The status report lists exact stale paths and expected/actual hashes,
missing current readers, selected IDs and required next actions. Rejected intake
keeps its path and exception. Source-authority conflicts require a new exact
handoff; stale Word/visual receipts require checking the new candidate bytes.
