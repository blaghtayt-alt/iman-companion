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

Actual Word finalization and final visual release acceptance remain release
steps on the existing owned desktop. The optional desktop worker is not part of
this deployment. This patch automates preparation and queueing; it does not
install an unattended Windows bridge or claim unattended visual approval.

## Preserving existing verified downloads

An additive approved member queues a replacement while retaining the exact
previously verified limited edition. Its language page and download interface
show only the included units and a native notice that new material awaits release
checks. New content is never claimed to be in old files. Changes to any included
source, review, audio, settings, identity, hold or withdrawal fail closed. Unknown
legacy membership cannot use the additive exception. A checked replacement pair
switches the row atomically; combined bundles and tables use verified pair hashes
only. Personal selected Japanese/Urdu requests remain outside the public library.
