# Finalize prepared books as a batch

`tools/finalize_word_batch.py` stages current preparations and runs the existing
Microsoft Word finalizer serially on the owned Windows desktop. One scope's
failure does not prevent the remaining selected scopes from completing. It does
not publish, edit the repository's preparation queue, provide source approval,
or accept a visual review.

The helper lives outside `books/`, so installing it does not change the render
code fingerprint of an already prepared book.

## Inputs

Use a current repository checkout and an extracted
`current-book-publication-<run>-<attempt>` Actions artifact. The artifact folder
must contain its scope folders directly, for example `ar-hadith/` and
`en-hadith/`. Keep the downloaded artifact unchanged. Choose a separate working
directory outside the repository, with enough space for immutable staged copies
and final candidates. The output cannot contain the repository either, and it
must not overlap the extracted artifact directory.

Run the helper from the same checkout supplied by `--root`. The CLI rejects a
different checkout, so the planner, queue validators and native Word finalizer
all use the selected checkout's code. When changing checkout, invoke that
checkout's own `tools/finalize_word_batch.py`.

By default, the helper selects the current queued scopes present in that
artifact. Repeat `--scope LANGUAGE/COLLECTION` to select particular scopes. A
stale or mismatched scope is reported and preserved; the helper never guesses a
replacement or adopts a different preparation under an existing batch identity.

## Stage without running Word

This mode also works on Linux and validates each scope through the existing
`finalize_prepared.plan` gate:

```bash
python tools/finalize_word_batch.py --root . --artifact /path/to/extracted-artifact --out /path/to/word-batch --stage-only
```

Staging creates `staged/<language>-<collection>/prepared/`, an initial
`candidate/` copy, and the exact `handoff.json`. No Word receipt, proof, visual
acceptance or publishable release is produced by staging.

## Run the batch on Windows

Install Microsoft Word and the existing Python dependencies, including
`pywin32`, on the owned desktop. Install the project's pinned fonts through the
existing setup. Run from the checked-out repository:

```powershell
python tools/finalize_word_batch.py --root . --artifact C:\Books\extracted-artifact --out C:\Books\word-batch
```

For a selection:

```powershell
python tools/finalize_word_batch.py --root . --artifact C:\Books\extracted-artifact --out C:\Books\word-batch --scope ar/hadith --scope en/hadith
```

The helper calls `books/finalize_word.py` for one scope at a time. Word operates
on a separate attempt copy. A failed or interrupted attempt cannot replace the
immutable preparation or the initial staged candidate. Completed candidates
must pass the existing exact-file Word receipt, proof page-count and reader
preservation checks before entering `bundle/`.

Progress is printed as each scope starts and completes. `state.json` records
hash-bound checkpoints; `report.json` identifies successful and failed scopes.
These local files and the operating-system lock stay outside `bundle/`. The
lock prevents overlapping workers for the same output and releases when the
process exits; no stale lock file needs deleting.

## Resume and review

Repeat the same command to resume. Matching completed scopes skip Word after
their current source, original preparation, final files and receipts are
revalidated. Failed scopes retry from unchanged staged inputs. Tampered files,
changed source or a different preparation are rejected without overwriting
them. When a source changes, obtain its fresh preparation and use a new output
directory.

Each successful scope receives `bundle/<scope>/visual-acceptance.json` with
`accepted`, `allPdfPagesInspected` and `allWordPagesInspected` all **false**;
reviewer and review time are blank. Inspect every page of both the canonical
PDF and `candidate/word-proof/Word-visual-proof.pdf`, then record the actual
reviewer, a timezone-aware review time and the explicit acceptance. Word and
the canonical PDF can paginate differently.

Resume preserves existing reviewer edits when all file and handoff identities
still match. It never resets accepted evidence to an empty template. A supplied
accepted review must also satisfy the existing acceptance validator.

`bundle/bundle.json` uses the existing finalized-candidate intake schema and
includes successfully completed Word scopes. It does **not** imply that their
visual review has been completed. Source/reference holds remain enforced by
the normal finalizer.

After the actual reviews are complete, feed **only `word-batch/bundle`** to the
existing `connector_candidate_transfer.py prepare` or
`release_candidate_intake.py pack` procedure in
[AUTOMATIC-PREPARATION.md](../books/AUTOMATIC-PREPARATION.md). The outer batch
directory is local working state and is not a transfer bundle. This helper
does not upload or dispatch anything.

Exit status is nonzero if any scope fails. Successful independent candidates
remain available. If a previously completed candidate is changed or becomes
stale, the batch reports the bundle as invalid until that evidence is resolved;
it does not silently publish or discard the old files.

## Focused verification

```bash
python tests/test_finalize_word_batch.py
```

The tests use clearly marked synthetic temporary files and mock only native
Word execution. They exercise real queue/planning, hashing, receipt parsing,
package preservation, failure isolation, lock exclusion, bundle validation and
resume behavior. A passing test is not evidence of Word execution or visual
review for a real book.
