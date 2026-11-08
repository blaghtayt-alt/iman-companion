# Current book preparation and publication

The [Books table](https://blaghtayt-alt.github.io/iman-companion/books/) and
[language download pages](downloads/) are generated from verified Word/PDF
pairs. Existing published editions remain available while a new or changed
collection is being prepared. A preparation artifact is not a public release.

The existing `build-word-books.yml` workflow now builds eligible current
materials, preserves preparation artifacts, accepts checked final files, and
updates the persistent download tables. Its four collection types are Quran
tadabbur, the new extended Essential Iman Hadiths, current Seerah, and Articles.
The Arabic adapters cover 47 Articles, 286 Hadith lessons in 12 chapters, and
the three current supplied adult Seerah chapters. Historical, held, and
superseded material does not become eligible merely because a file exists.

## What happens automatically

An approved material publication or a relevant push to `main` runs the same
publisher. It validates the current source identities and bindings, normalizes
eligible reader material, builds editable Word files and independent PDFs with
the pinned fonts and covers, and checks their contents and reference targets.
Exact registered whole-material additions and corrections can join the
existing adapters without replacing unrelated current material.

`reviewed-books.json` declares eligible scopes and their requirements.
`prepared-library.json` records exact prepared candidates and every remaining
check. `published-library.json` records verified public pairs. Successful
publication removes only the completed scopes from the preparation queue and
regenerates the applicable category links and language bundles.

## Completing a prepared edition

Preparation does not create a Microsoft Word receipt or visual acceptance.
An owned desktop with Microsoft Word must paginate the exact candidate, check
its contents targets, and export its Word visual proof. Every page of the final
PDF and Word proof must be inspected, and the actual reviewer must supply
acceptance tied to those exact file hashes. Source-reference holds must also
be resolved. Neither a passing layout script nor an earlier edition's review
substitutes for that evidence.

`finalize_prepared.py` verifies the immutable preparation, permitted Word
pagination changes, real Word receipt, current source bindings, and final
visual acceptance. `release_candidate_intake.py` packages and checks the
handoff. The existing workflow accepts the exact transfer asset through the
`finalized_release`, `finalized_asset`, and `finalized_sha256` inputs; the same
publisher then releases eligible pairs and refreshes the tables.

See [AUTOMATIC-PREPARATION.md](AUTOMATIC-PREPARATION.md) for the complete
commands, source-publication contract, and review handoff. Full reader text,
quotation roles, source attributions, qualifications, and original order must
be preserved. Non-Arabic summaries remain AI translated and require
verification. Test fixtures and layout probes are never downloadable books.
