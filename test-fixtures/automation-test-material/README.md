# Temporary automation test material

This folder contains exactly two synthetic English Article materials. Both use
the exact title `automation test material`; each has one body paragraph containing
only `TEST`. They are authored test data, not religious source material or a
translation. The technical review records describe only this narrow test.

The intended document has two TEST body pages plus the normal production cover,
contents, headings and page-number furniture. The unchanged English template
also retains its usual front-matter translation notice. That is template
furniture; the authored TEST text is not a translation. Rendering and actual
Word review must establish pagination; this README is not a visual approval.

## Run the isolated preparation

Use a Python environment with `books/requirements.txt` installed and the normal
pinned renderer available. The selected pinned assets must already be installed;
the runner does not download anything. Run from the repository:

```bash
PYTHONDONTWRITEBYTECODE=1 python -B test-fixtures/automation-test-material/run.py \
  --root . \
  --out "$RUNNER_TEMP/automation-test-run" \
  --uno-python /usr/bin/python3
```

The output must be a new directory outside the input repository. If the installed
assets are in a different checkout, add `--assets-root /absolute/asset-checkout`.
Every selected font, cover and canonical text asset must match the current
production configuration's exact SHA-256. `--stage-only` exercises genuine source
intake and the local Git commits without rendering or creating a preparation.

The read-only `test-book-automation.yml` workflow invokes the same runner. The
runner copies unchanged production Python modules into a fresh local Git root,
with no remote or copied credentials. It creates an empty synthetic catalog,
registers the two exact reviewed test inputs through
`material_publication_intake.py`, and invokes `automatic_publication.py build`.
Its initial source, post-intake source and prepared-queue commits have separate
identities. Production tracked files, catalog, library, bundles and queue are
hashed before and after the run.

Only the isolated English configuration is scoped: its Article title is
`automation test material`, and its audio registry is empty. The required
production fonts and Article cover stay pinned.
The isolated declaration has `automaticRelease: false` and a technical TEST-only
release hold. No production declarations or source files are edited.

## Transfer and actual Word review

A successful build produces:

- `preparation/en-articles/` and the genuine build report.
- `handoff.json` bound by the normal `finalize_prepared.py plan` command.
- `word-launch-manifest.json`, including exact code, fixture, asset, queue and
  preparation bindings.
- `isolated-root.bundle` and `isolated-root-files.json` for the minimal synthetic
  Git root, including only its required code, assets and TEST data.
- `provenance.json`, `source-intake-report.json`, `isolated-test-receipt.json`,
  `transfer-files.json` and `transfer.zip`.

The ZIP omits the duplicate working tree and all original repository material.
It contains no `.git` directory or credentials. To restore its bundle, use a new
owned directory and fetch the bundle directly, without configuring a remote:

```bash
mkdir "$AUTOMATION_TEST_ROOT"
git -C "$AUTOMATION_TEST_ROOT" init -b technical-test
git -C "$AUTOMATION_TEST_ROOT" fetch /absolute/isolated-root.bundle technical-test
git -C "$AUTOMATION_TEST_ROOT" reset --hard FETCH_HEAD
```

Verify the package, restored file inventory and Word-launch manifest hashes
before running the separate owned-desktop Word helper. CI does not run Microsoft
Word or inspect pages. The actual Word proof, visual diagnostic review and normal
pack/extract checks are separate steps. This runner never creates an acceptance,
invokes `publish`, calls `ensure_main`, configures a remote, or uploads anything.
The false release declaration and explicit hold must remain. A normal finalizer
must reject this test; such rejection is an expected guard result, not a public
publication success.

## Remove after verification

Keep the small technical result and cleanup receipt outside this folder. Remove
only the owned temporary test output/Word directories and, after the requested
verification is complete, this fixture folder and
`.github/workflows/test-book-automation.yml`. Do not remove or modify real
materials, source reviews, publication history, existing releases or downloaded
books. Recheck the production catalog, library, bundles, queue and real source
bindings against the recorded baseline. No live source registration needs to be
undone because the test never registers its materials in production.
