# Automatic checks for every book download table

The existing `Publish current multilingual books` workflow remains the only
current publication writer. It prepares eligible source updates, accepts exact
finalized candidates, publishes verified files, and regenerates the root Books
table, all twenty native language tables, the public catalog and language bundles.
Root `README.md` changes now trigger the same workflow, so editing the root
download table cannot silently leave it out of sync with the generated tables.

`Verify published book downloads` is a separate read-only health check. It runs
after the current publisher completes on `main`, at minute 23 every six hours
(UTC), and on manual dispatch. It checks the actual committed inventories and
deployed files, in addition to the existing synthetic generator tests. It does
not create approvals, alter source selection, modify the preparation queue,
release books, repair remote assets, or send messages.

## What the check compares

`tools/check_book_downloads.py` derives expected downloads from the published
library and bundle manifests. It checks all configured languages and all four
collection cells per language. Its counts come from those inventories rather
than a fixed number of books.

- The root Books table and every native table must match their verified book
  contents, native labels and bundle destinations.
- Catalog entries must agree with each published scope, included identity,
  file hash, Word/PDF URL and combined inventory. Prepared additions remain
  described as pending until the normal release process publishes them.
- Every referenced local cover, font and frontend file must be present. The
  deployed catalog and static files must match the checked repository bytes.
- Live GitHub release metadata must identify public, uploaded assets with the
  expected filenames, SHA-256 values and inventory.
- Every public book and bundle download URL must pass a bounded HTTP check.
  This proves HTTP availability at the time of the check; it does not download
  and independently hash every complete book or ZIP again.

The workflow also passes the real catalog through the same JavaScript language
view model used by the download page. This catches a catalog that passes the
backend checks but cannot be accepted by the public interface.

## Run locally

From an exact checkout, with the existing book requirements installed:

```bash
python tools/check_book_downloads.py --root . --json /tmp/book-downloads.json
```

The default is local validation only. It must not be described as a fresh
internet check. To include live release metadata, public download responses and
the deployed site:

```bash
python tools/check_book_downloads.py --root . \
  --verify-releases --verify-downloads \
  --site-url https://blaghtayt-alt.github.io/iman-companion/books/ \
  --json /tmp/book-downloads.json
```

Use the existing read-only `GH_TOKEN` for authenticated GitHub release metadata
where available. The report must be written outside the checkout. The tool
never replaces a catalog, table or release record while validating it.

## Deployment timing and failures

The health workflow follows completion of the publisher, rather than the first
Pages build caused by a source push. This avoids comparing old tables while a
long book preparation is still running. It allows six attempts with thirty
seconds between attempts for Pages propagation. Each retry checks a fresh
`main` checkout. A changed authoritative head during a successful audit causes
a retry instead of labeling the earlier checkout current.

Only health jobs replace older health jobs. Their concurrency group is separate
from the serialized publication writer. The health workflow has read-only
repository permissions and checks trusted `main`; it does not execute a pull
request's head or download its artifacts.

Each run saves per-attempt JSON reports and a final summary as the
`book-download-health-<run>-<attempt>` Actions artifact. A requested check that
fails, is blocked or cannot reach its endpoint does not become a pass. A network
timeout is reported separately from evidence that an asset is missing. The
report records the checked commit and the scope of its verification.

For a generated-table mismatch, correct the underlying inventory or generator
and run the existing publisher. For an unreachable release or Pages deployment,
inspect that service's recorded failure before retrying. The periodic checker
detects a problem; it does not create a second publication path.

## What a passing result means

All represented downloads and generated table states agree and the requested
online checks passed at the recorded time. The root table separately counts
published language/category editions and the combinations without a published
pair, with a subtotal for each collection. Native tables say that an absent
edition is not yet published; absence does not assert that a build is running.
A passing download
check does not approve missing translations, assert that every authored
manuscript is installed, replace actual Microsoft Word checks, or issue final
visual acceptance for a candidate.

The diagnostic, its tests and workflow are outside the non-test `books/*.py`
modules used by preparation fingerprints. Adding these checks does not require
rebuilding already reviewed candidates.
