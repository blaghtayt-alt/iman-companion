# Automatic preparation and verified release

The existing `build-word-books.yml` source-push workflow is the only public writer.
It reacts to `materials/**` and `books/**`, consumes exact approved source
transactions, prepares affected books, inserts eligible audio QR panels, and
regenerates the verified library, bundles and twenty language download tables.
There is no new schedule, inbound service, runner registration or credential.

## Source transaction contract

The source publisher must commit the source, original review evidence, exact
normalized `iman-book-unit-v1` reader snapshot and an
`iman-approved-material-publication-v1` envelope **in the same source commit**.
Put the envelope under `materials/book-publication-intake/*.json`. It uses the
same contract as `publish_approved_material.py`: exact source/review/reader SHA256
bindings, existing whole-material approval identity and reviewer, source identity,
language, explicit canonical order, and an optimistic `expectedCatalogSHA256`.
No source producer may replace a review role, remove a qualification, drop a
meaning note, or treat merely uploaded/draft/held content as approved.

The workflow calls `material_publication_intake.py` before audio discovery and
book indexing. Every envelope is validated before registration; its immutable
original handoff and receipt remain bound to the resulting current reader unit.
Independent envelopes may share the workflow's initial catalogue hash. Conflicting
envelopes for one material are both rejected. Processed envelope hashes are
idempotent. Corrections archive the previous reader snapshot and replace its
catalogue identity, rather than duplicate it. Existing declared scope holds remain
unchanged. A first approved material in a known language/category automatically
creates a preparation-only scope; untyped legacy rows remain UNKNOWN.

Raw source files without this approved envelope are not automatically approved
or guessed into a book. The source producer must emit the envelope as part of its
normal approved publication transaction. Installing this consumer alone does not
prove that every external source producer has adopted that contract.

For a Git-based source publication, `source_publication_transaction.py` is a
single-commit entry point. Supply the approved envelope and the exact expected
Git head and the expected remote URL. Add `expectedSourceBase` to the envelope
with one `{path, sha256}` entry for each source binding: use the prior tracked
source SHA-256 observed for the review, or `null` only for a genuinely new path.
The publisher validates the exact source,
review and reader bytes, verifies the catalogue and source baselines, and puts
the sources, original public-safe review evidence, normalized reader, catalogue,
scope and intake history into one commit. `--publish` pushes that commit as a
fast-forward; without it the command validates only. The user's working tree
and ordinary Git index are not changed. An advanced head, source, review record
or local input aborts rather than replacing later work. Use an exact-byte checkout (without automatic newline
conversion) and include only evidence already authorized for public release.
The command requires the source publisher's existing Git authentication; it
does not install credentials or infer reviews from an uploaded source.

When the publisher uses the authenticated GitHub connector instead of local Git
credentials, `source_publication_connector.cjs` wraps the same transaction. Load
the wrapper from `git show <exact-head>:books/source_publication_connector.cjs`,
not from an unchecked working copy, then call `publishReviewedSourceWithConnector`
with `root`, `handoff`, `expectedHead`, a new private `bundle` directory, the
absolute `python` executable and a commit `message`. The caller supplies the
existing connector tools interface. The bridge verifies every book Python module
against the exact Git head, runs in isolated Python mode, checks the immutable
bundle and current source inputs again before publishing, and advances `main`
only as a fast-forward with the expected head. Changed source or code aborts.
This provides a safe entry point; external source producers still need to adopt it.

## Membership and order

Quran books use canonical surah order and exact canonical Arabic ayahs. Full
surah readers retain their existing complete-ayah requirement. Intentionally
selected reviewed commentary requires an exact `reviewedCoverage` object, also
present as `approval.coverage` in its original envelope:

```json
{
  "schema": "iman-reviewed-quran-coverage-v1",
  "surah": 18,
  "ayahKeys": ["18:1", "18:3"],
  "scopeLabel": "A native-language selected-ayah label included in the reviewed title",
  "introduction": {"state": "included", "readerTextSHA256": "<exact reviewed introduction text hash>"}
}
```

If the reviewed material contains no introduction, declare its state as
`not-in-reviewed-material`. Existing prose is not filled in or silently omitted.
Wrong surah/ayah bounds, duplicates, reordered sections, altered/missing
introductions and undeclared partial coverage fail validation.

Hadith and Seerah use an explicit global sequence or explicit chapter/lesson
hierarchy. Compound IDs never derive order from their final digit run. To use a
hierarchy, supply `ordering: {kind: "chapter-lesson", chapter: 2, lesson: 1}`;
alternatively use `ordering: {kind: "global-sequence", sequence: 17}` matching
`order`. Duplicate positions and mixed ambiguous schemes are rejected. Articles
use their explicit source number. The builder regenerates contents, native page
numbers, footnotes and credits on each changed eligible membership.

## Prepared candidates and release

`books/prepared-library.json` records `prepared-awaiting-release-qc`, exact
source/approval/settings/code fingerprints, included units, checked pair hashes,
and the GitHub artifact location. Prepared snapshots use a separate schema and
`releaseVerified: false`; they cannot enter public release capture or tables.
Missing actual Microsoft Word QC, visual acceptance or complete source references
are named pending checks. Real source, font, QR, bounds or rendering failures stay
failures. No Word or visual approval is manufactured by the Linux renderer.

Artifacts are retained for ninety days. A no-change run skips rendering only if
its exact source bindings still match and the artifact still exists and is not
expired. Expired/deleted artifacts are rebuilt. Local proof runs additionally
check the exact local pair bytes. The current source-push job serializes work;
the sole publisher rechecks main before release/table commits, so a competing
source or metadata commit cannot publish an old-head candidate.

Each external command has a ten-minute limit. The Linux controller gives it a
dedicated process group and retires that group on timeout, including descendants
that outlive the command or close their output pipes. A timed-out scope keeps its
partial files under `failed-preparations`; it gains no preparation or release
snapshot, and other scopes continue. The preparation phase has a seventy-minute
budget within the ninety-minute job, reserving time for queue updates, publication
bookkeeping and artifact upload. Unattempted scopes after that budget are reported
for retry rather than accepted as prepared.

The controller flushes scope and command progress and atomically checkpoints
`build-report.json` between scopes. A runner interruption leaves completed
per-folder preparation snapshots and an explicitly incomplete report for recovery;
it does not commit the queue or grant release approval. Publication rejects an
incomplete checkpoint. Before the pinned Linux renderer imports a document, a
guarded package pass replaces only the exact generated RTL page-number formula
with an ordinary live PAGE field. Every other package part is preserved. Unknown
footer content fails without modifying the file. The existing native footer,
field refresh, contents convergence and source checks still run in their original
order.

Pinned font and cover archives use the authenticated GitHub release-asset API
when the existing `GH_TOKEN` is available. The installer resolves the exact tag,
filename and public URL, bounds metadata and binary transfers, and still verifies
the original SHA-256 before extracting anything. The renderer regression step
uses its existing read-only repository token. Environments without that token
retain the original public URLs with bounded reads; archive pins are unchanged.

Actual Word finalization and final visual release acceptance remain release
steps on the existing owned desktop. The optional desktop worker is not part of
this deployment. The checked handoff below connects those completed checks to
the existing publisher; it does not install an unattended Windows bridge or
claim unattended visual approval.

### Current material adapters

The current Arabic Articles adapter covers the 47 installed article readings.
The new-adult Seerah adapter covers its three current chapters. The Arabic
Essential Hadith adapter now covers all 286 lessons in 12 chapters under
`materials/hadith/essential-ar/`. Its compact source projection binds the exact
catalogue, chapter JSON, lesson JSON and Markdown bytes. It carries all chapter
introductions and bibliographies once per chapter, source formatting roles,
reference qualifications, and original provenance. Source-reference preservation
is audited separately from machine classification: exact original book/page
notes, shared citations and repeated quoted phrases remain valid source content
even when the narrow parser cannot assign a structured identity. Such cases are
reported as nonblocking classification/placement diagnostics. A website record
ID is never substituted for an original narration number.

Articles, Hadith and the three current adult Seerah chapters are eligible for
finalization with mandatory actual Word and visual checks. All 28 Quran and
24 Hadith quotation segments in that Seerah edition now have source bindings;
its reference hold is resolved. Generate a fresh preparation with those exact
bindings before the final Word and visual checks. `automaticRelease` by itself
cannot supply Word receipts, complete missing references, or grant visual acceptance.

The translated Essential Hadith adapter separately covers fifty existing
independently model-reviewed lessons across all nineteen non-Arabic languages.
Its pinned inventory selects only the exact language sets in the published
01-002, 01-003 and 01-004 review groups. It preserves full reader text, original
lesson numbers, translator footnotes, credits and human-verification
qualifications. A non-native publisher name or reference locator is allowed
only through an exact source JSON pointer, source/inventory hashes and text
offsets; ordinary native-language furniture validation remains strict. The
first-lesson adapter separately binds eleven eligible 01-001 readers to their
exact current review records, preserves their full commentary and required
source companions, and retains the French reader's incomplete-final-review
status. A separate adapter restores the current Filipino 01-005 reader with its
original lesson number. Missing first-lesson readers remain explicit gaps.

The current Quran adapters restore 124 eligible units: 112 entries-map scopes,
eleven complete Fatiha packets and the complete Japanese Qiyamah packet. Their
inventories bind current Arabic revisions, exact source text, citations and
qualifications. Selected-ayah material stays explicitly partial. These adapters
bring the current selection to 625 units; [current-reviewed-imports.md](current-reviewed-imports.md)
records the 136 additions, affected 31 editions and exact exclusions. Previously
published pairs retain their original membership until expanded files pass the
normal Word and final visual checks.

Historical standalone article translations and legacy Seerah editions do not
join the current editions. The exact approved normalized reader transaction
above remains the automatic path for later material in any of the twenty
languages and four collections. `books/multilingual_readiness.py` reports every
one of these eighty combinations, including missing current translations,
unbound rows and explicit holds. The workflow saves that report as
`language-readiness.json` and includes it in both build and publication reports.
The initial installed-source inventory has forty-two ready scopes: Quran and
Hadith in twenty languages, plus current Arabic Seerah and Articles.

### A4 and audio layout

All fresh builds use A4 (210 by 297 mm), 18 mm body margins and 8 mm header/footer
distances. The source cover is centered and contained without distortion or
cropping. On the first page of an audio-backed material, a non-splitting title
and card row reserves the card's space in normal document flow. Its QR is at
least 38 mm square including four clear modules, with printed modules at least
0.6 mm wide. Long material identifiers enlarge the card instead of reducing
scan size. PDF checks verify actual page dimensions, cover proportions, printed
QR size and whitespace, decoded exact targets, and non-overlap with text.

The audio-layout upgrade queues affected existing books, while retaining their
old verified pair until the new exact files pass finalization. It does not
invalidate or force a rebuild of unrelated unchanged books without audio.
Russian, Vietnamese and Filipino Quran declarations now use the same bounded
review inventory as the other translated Quran editions. Their previously
verified pairs remain current only if the exact old member rows, pinned source
bytes and settings still match; an unbound legacy Fatiha row gains no approval.

Both `build-report.json` and `publication-report.json` include
`preparedAwaitingReleaseQC` for the **entire** pending queue, including unchanged
and superseded preparations. Each entry names its included unit count, pending
checks and artifact run. Prospective release URLs inside preparation metadata
are never presented as public downloads.

### Finalized candidate handoff

Use the latest committed preparation queue and the matching Actions artifact.
Keep each downloaded scope folder unchanged as `prepared/`; make a separate
`candidate/` copy for Word finalization. The original DOCX and the final Word
DOCX have separate hashes because the Word finalizer may change numeric contents
caches and native page-number furniture. Reader text, footnotes, QR content and
unrelated package parts must remain unchanged.

For an Arabic Articles candidate, run these commands from an exact current
checkout on the owned Windows desktop (paths are illustrative):

```powershell
python books/finalize_prepared.py plan --root . --prepared review-bundle/ar-articles/prepared --handoff review-bundle/ar-articles/handoff.json
python books/finalize_word.py --root . --docx review-bundle/ar-articles/candidate/Iman_Companion_ar_articles.docx --language ar --proof-dir review-bundle/ar-articles/candidate/word-proof
python books/finalize_prepared.py acceptance-template --handoff review-bundle/ar-articles/handoff.json --candidate review-bundle/ar-articles/candidate --acceptance review-bundle/ar-articles/visual-acceptance.json
```

The template binds the exact final DOCX, PDF, Word receipt and Word visual proof,
but leaves all acceptance fields false. After inspecting both complete final
formats, the actual reviewer records their identity, timezone-aware review time
and explicit acceptance in that file. Keep the canonical PDF separate from
`candidate/word-proof/Word-visual-proof.pdf`; their pagination can legitimately
differ. The finalizer checks both independently.

Create `review-bundle/bundle.json` describing one or more independently checked
scopes. Every path is relative to that bundle directory:

```json
{
  "schema": "iman-finalized-book-intake-v1",
  "scopes": [{
    "language": "ar",
    "collection": "articles",
    "prepared": "ar-articles/prepared",
    "candidate": "ar-articles/candidate",
    "handoff": "ar-articles/handoff.json",
    "acceptance": "ar-articles/visual-acceptance.json"
  }]
}
```

Package the bundle with the repository helper. It adds an exact per-file
inventory, validates confined paths and prints the archive SHA256. Upload that
ZIP through the desktop's existing GitHub authentication to an owner-created
**draft** release. The draft is only a transfer location, not a public book.

```powershell
python books/release_candidate_intake.py pack --bundle review-bundle --out finalized-books.zip
gh release create book-review-20261108 --repo blaghtayt-alt/iman-companion --draft --latest=false --title "Book review transfer" --notes "Exact owned-desktop candidate bundle; not public downloads."
gh release upload book-review-20261108 finalized-books.zip --repo blaghtayt-alt/iman-companion
gh workflow run build-word-books.yml --repo blaghtayt-alt/iman-companion --ref main -f finalized_release=book-review-20261108 -f finalized_asset=finalized-books.zip -f finalized_sha256=REPLACE_WITH_PRINTED_SHA256
```

Use a new transfer tag or asset for a new candidate; do not overwrite evidence.
The existing workflow downloads only the named ZIP, verifies its exact hash and
payload inventory, then calls the finalization intake. It reindexes the original
source, validates the current scoped fingerprint, reruns export/font/reference/
contents checks, checks the actual Word receipt and final visual acceptance,
and adds successful candidates to `build-report.json` under `built`. The sole
publisher then uploads immutable public pairs, verifies their remote hashes,
regenerates the four-category tables and affected language bundles, and removes
only successfully published scopes from the preparation queue. An individual
candidate QC failure remains in the report while other valid scopes continue.

Expired artifacts, changed sources, changed rendering code, changed scope
declarations or changed relevant settings require a fresh preparation. An old
desktop bundle cannot override the new queue. Unrelated changes in another
language do not invalidate an unchanged scoped handoff. No intake command
creates source approval, toggles a release hold, or accepts its own visual
template. A rejected transfer or malformed bundle is reported as an intake
failure; independent preparation and existing verified downloads still continue.

## Transfer through the connected GitHub account

A desktop GitHub login is not required when the connected account can create
Git blobs and commits. The same publisher accepts pinned transfer manifests
under `materials/book-finalization-intake/<archiveSHA256>.json` on a normal
source push. This is a transport option; it supplies no Word or visual approval.

First complete the current preparation's actual Word and visual checks. Then
make a minimal transfer on the owned desktop, before uploading any bytes:

```powershell
python books/connector_candidate_transfer.py prepare --root . --bundle review-bundle --out connector-transfer --repo blaghtayt-alt/iman-companion
```

The command checks the current handoff and supplied acceptance, copies only
the six required preparation files, four final candidate files, and exact
handoff/acceptance files, and packages them through the existing archive helper.
It excludes local diagnostic logs, process audits, and other files. Required
metadata containing `localArtifacts` or absolute machine paths is rejected.
It does not sanitize or rewrite accepted evidence. Use a committed Actions
preparation; keep local audits outside the review bundle. Review the actual
reviewer identity in the acceptance before public transfer.

The output contains `finalized-books.zip`, ordered `chunks/0000.b64` files,
and a ready manifest named for the archive SHA256. Each manifest has this form:

```json
{
  "schema": "iman-book-connector-transfer-v1",
  "repository": "blaghtayt-alt/iman-companion",
  "archiveSHA256": "<64 lowercase hex digits>",
  "archiveBytes": 12345,
  "chunks": [
    {"blobSHA": "<40 lowercase hex digits>", "sha256": "<64 lowercase hex digits>", "bytes": 12345}
  ],
  "scopes": [
    {"language": "ar", "collection": "articles", "sourceCommit": "<preparation commit>", "inputFingerprint": "<exact preparation fingerprint>"}
  ]
}
```

For each ordered chunk, call the existing GitHub connector's `create_blob`
with `encoding: "base64"`, the unchanged file content, and this repository.
The returned blob SHA must equal the precomputed `blobSHA`; stop on any
mismatch. Upload every chunk before committing the unchanged manifest to its
printed `commitPath`. Do not put chunk data or desktop paths in that manifest.
Use a reviewed branch/PR or an authorized fast-forward with the current expected
head. The manifest's relevant main push starts the existing workflow; there is
no separate scheduler, credential or inbound service.

The workflow retrieves only the named Git blobs from its own repository.
It independently checks each Git object SHA, SHA256 and exact byte count,
then the ordered archive's SHA256, size, safe ZIP inventory and exact declared
scopes. It rejects stale preparations, ambiguous pending transfers and extra
payload files. The existing finalizer still validates the current source,
unchanged reader content, real Word receipt and exact final visual acceptance.
Individual failed transfers remain visible without preventing independent
valid pairs from reaching the normal publisher.

Only after the normal publisher verifies the public pair assets does it write
a per-scope receipt under `materials/book-finalization-intake-history/`, in the
same commit as the catalog/library update. Already consumed scopes are skipped
without downloading their chunks again; a failed scope is not consumed.
Historical manifests and receipts stay immutable evidence. The transport limit
is 512 MiB per archive, 8 MiB per chunk and 4,096 ordered chunks; the default
upload chunk is 512 KiB.

Merge all renderer and transfer code before generating fresh preparations:
the preparation signature includes every non-test `books/*.py` module.
A later metadata-only transfer commit can use an unchanged current preparation.
Do not advance main while its publication job is running.

## Preserving existing verified downloads

An additive approved member queues a replacement while retaining the exact
previously verified limited edition. Its language page and download interface
show only the included units and a native notice that new material awaits release
checks. New content is never claimed to be in old files. Changes to any included
source, review, audio, settings, identity, hold or withdrawal fail closed. Unknown
legacy membership cannot use the additive exception. A checked replacement pair
switches the row atomically; combined bundles and tables use verified pair hashes
only. Personal selected Japanese/Urdu requests remain outside the public library.
