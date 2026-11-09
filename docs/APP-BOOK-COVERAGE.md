# Check app material against book contents

`tools/check_app_book_coverage.py` compares an independently audited app inventory
with the current repository selection, preparation queue, and recorded public
books. It makes a missing source visible even when an item disappeared from both
the catalogue and the paths normally inspected by the exporter.

The initial baseline covers 277 current identities: 47 Arabic articles, 227
extended Quran language/surah scopes, and three revised Arabic Seerah chapters.
Language/surah scopes are separate identities; 227 does not mean 227 distinct
surahs or complete commentary on every ayah. Arabic Quran identity coverage and
the narrower exact-text comparisons are recorded separately in the baseline.

## Run the check

From a checkout of this repository:

```bash
python tools/check_app_book_coverage.py --root . --json /tmp/app-book-coverage.json
```

The existing publication workflow runs the check before its normal validation
and preserves the report as an Actions artifact. It uses the same publication
workflow and creates no additional release writer.

To verify that a local app still has the audited runtime bytes, also supply its
root:

```bash
python tools/check_app_book_coverage.py --root . --app-root /path/to/current-app --json /tmp/app-book-coverage.json
```

Without `--app-root`, the report compares books with a dated, pinned app baseline;
it does not assert that a user's installed app has been inspected. A changed
runtime pin requires a fresh app audit. The program never changes app files,
source files, the preparation queue, or release approvals.

## Interpret the report

An expected item absent from the catalogue or current selector is an integration
failure. Duplicate identities, same-count identity substitutions, changed source
bindings, and mismatched app pins also fail the check. A valid older public
edition may remain available while an expanded replacement is prepared: those
additional readers are reported as awaiting publication, not as already present
in the downloadable file.

Publication membership is checked against the repository's exact book/snapshot
records and their source bindings. This diagnostic does not download remote
assets and cannot certify that a URL currently responds or that a phone is
running a particular version. The ordinary release checks still verify final
Word/PDF files and required review evidence.

The baseline explicitly excludes superseded Seerah lecture chapters, retired
standalone article translations, unfinished translations, and simplified Quran
editions. Those exclusions are boundaries of this audited comparison, not new
review decisions. New eligible readers can be added through the normal reviewed
source intake; a baseline must never be weakened simply to hide a missing item.

The current Arabic app article dataset has a separately recorded reference gap:
the books preserve 23 restored reference paragraphs, three corrected truncated
reference paragraphs, and 14 original source anchors across 16 articles that the
audited app has not yet received. The baseline records this known difference;
it does not describe the app and book reference layers as identical.

The three current Arabic Seerah readers likewise have 52 quotation segments
whose source metadata was added to the book projection: 28 Quran and 24 Hadith
segments. Their app paragraph and segment texts match; the recorded difference
is the reference metadata, not missing quotations.

## Refresh evidence safely

Inspect the effective app loader and its current reader identities before
updating `docs/automation/current-app-book-baseline.json`. Raw bundled legacy
data may be gated or superseded. Record exact new data/loader hashes, source
bindings, and the scope of each comparison. Preserve the distinction between
identity verification and exact reader-text verification. Keep private review
transcripts, machine paths, source scans, and unpublished translation packages
out of the public baseline.

This diagnostic lives in `tools/`, `tests/`, and `docs/`; it does not alter the
non-test `books/*.py` files used in existing preparation fingerprints. Installing
it therefore does not require regenerating the 31 already prepared editions.
