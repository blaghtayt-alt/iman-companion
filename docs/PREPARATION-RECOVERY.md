# Recover an interrupted preparation batch

`tools/recover_prepared_batch.py` checks completed preparations from an Actions
artifact and produces a proposed queue plus a recovery audit. It does not change
the repository queue, run Word, approve a review, or publish files.

The preparation controller checkpoints its report between scopes, but writes the
queue after the scope loop. Cancellation can therefore leave valid completed
`prepared-snapshot.json` folders in the uploaded artifact without matching queue
entries. The Word batch planner correctly refuses those unqueued preparations.
This recovery command supplies the missing, reviewable queue proposal.

The helper lives outside `books/`, so adding it does not change preparation code
fingerprints. It keeps original snapshot rows and fingerprints unchanged. A
source, approval, configuration, or rendering-code change still requires fresh
preparation, even if the old artifact contains a complete PDF and Word pair.

## Required inputs

Use the current repository checkout and two immutable files saved outside it:

- The original ZIP downloaded from the chosen
  `current-book-publication-<run>-<attempt>` Actions artifact. Recompressing an
  extracted directory changes the artifact digest and is not supported.
- The exact selected artifact's metadata from the authenticated GitHub artifact
  API or connected GitHub tool. Save the single artifact object, or an
  `artifacts` response containing exactly that one object.

The metadata must include `id`, `name`, `size_in_bytes`, `digest`, `url`,
`archive_download_url`, `expired`, `expires_at`, and the `workflow_run` fields
`id`, `repository_id`, `head_repository_id`, `head_branch`, and `head_sha`.
For example, the selected-object API endpoint is
`GET /repos/OWNER/REPOSITORY/actions/artifacts/ARTIFACT_ID`; its ZIP endpoint adds
`/zip`. Preserve the API's original `sha256:...` digest.

**The metadata is a separately fetched trusted input.** The command does not
contact GitHub or authenticate a locally supplied JSON file. Do not construct
metadata from an untrusted ZIP or substitute a hash calculated from altered
contents. The command checks the ZIP against that independently obtained digest,
size, repository, production main-branch run, attempt, source commit, and expiry.
Each original snapshot must name the same artifact and source commit.

Run the helper from the same checkout supplied as `--root`. A Git working tree
is not required: current source fingerprints, rather than the checkout's commit
name, establish whether a preparation remains current. The original run's
source commit may precede a later queue or documentation commit.

Choose an output directory outside the repository and separate from both input
files. The command rejects overlapping paths, symlink paths, unsafe or duplicate
ZIP members, and excessive archive expansion. Allow space for an isolated copy
of current sources and the extracted artifact during validation. Git history,
caches, virtual environments and dependency directories are excluded from the
source copy; a required input missing from that copy fails validation.

## Produce the proposal

```bash
python tools/recover_prepared_batch.py --root . --archive /work/original-artifact.zip --artifact-metadata /work/artifact-api.json --out /work/recovery-proposal
```

The expected repository defaults to `blaghtayt-alt/iman-companion`. An intentional
installation in another repository must specify `--repository OWNER/REPOSITORY`
and use matching API metadata.

The command creates:

| Output | Purpose |
| --- | --- |
| `proposed-prepared-library.json` | The complete existing queue plus independently validated, nonconflicting original entries. |
| `recovery-audit.json` | Artifact and API-file hashes, the original queue hash, proposed queue hash, recovered scopes, conflicts, failures, incomplete folders and pending review holds. |
| `prepared/<scope>/` | Exact copies of the six files required by the existing preparation planner. |
| `handoffs/<scope>.json` | The original planner's exact hash-bound handoff for each accepted scope. |

Validation uses `finalize_prepared.plan` against an isolated copy of current
sources. Only the isolated queue contains a proposed entry during this check.
The original archive, source files, current queue and preparation snapshots stay
unchanged. A scope with invalid identity, changed files, stale sources, missing
Word or visual review holds, or a conflicting current queue entry is rejected.
Independent valid scopes can still appear in the proposal. Original source and
scope release holds remain intact.

Every current queue entry is preserved, including entries unrelated to the
selected artifact and stale entries awaiting a rebuild. An identical existing
entry is reported as `alreadyCurrent`; a different existing entry for the same
scope is a conflict and is never replaced automatically. If no entry is added,
the proposed queue preserves the current queue's exact bytes.

Exit status is zero when at least one scope is recovered or already current and
no scope is rejected. Status one can still leave a useful partial proposal;
consult the audit. Envelope errors, changed inputs during validation, or unsafe
archives produce no proposal. Repeating unchanged inputs into the same output
is idempotent. Different existing output is preserved and requires a fresh
output directory.

## Integrate and continue

Review the audit and proposed queue through the project's existing queue commit
process. Before integrating, the current `books/prepared-library.json` must still
have the audit's `baseQueueSHA256`; if it changed, produce a new proposal. A null
base hash means the queue file did not exist. Recheck current source fingerprints
as part of integration. Do not resolve a conflict by changing an artifact's
fingerprint, source commit, or original review holds.

After the exact proposal is accepted into the current checkout, its recovered
copies can go directly to the existing batch stage-only command:

```bash
python tools/finalize_word_batch.py --root . --artifact /work/recovery-proposal/prepared --out /work/word-batch --stage-only
```

Native Microsoft Word finalization on the owned desktop, inspection of every
page in both formats, exact visual acceptance, source-reference resolution and
the existing publication gates still follow the
[Word batch finalization guide](WORD-BATCH-FINALIZATION.md). Recovery produces no
Word receipt or visual acceptance file and never treats an incomplete build
checkpoint as a release.
