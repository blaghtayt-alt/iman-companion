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

All twenty configured languages use the same automatic source intake for all
four categories. The translated Hadith adapters prepare the fifty reviewed
translations of lessons 01-002 through 01-004, eleven eligible first-lesson
readers and the current Filipino lesson 01-005. Each language retains its actual
lesson subset, original numbering and source qualifications. The reviewed Quran
adapters also restore 124 current units previously omitted by the exporters.
The subsequent current-source intake adds English Article 1 and Seerah 1,
Hadith 1 in Japanese, English and Turkish, and Article 1 in Spanish, French,
Indonesian, Malay, Russian and Turkish. The selection now contains 636 units
across 50 eligible book scopes. Eligibility is separate from released files:
the live table and publication manifest show which exact editions have passed
the final checks. French Hadith 1 remains pending its distinct final review;
absent first-lesson readers are reported explicitly.
See [the source coverage record](current-reviewed-imports.md)
for the exact restored material, exclusions and release status.

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

Each run saves `language-readiness.json` and reports all eighty language/category
combinations in its publication receipt. It distinguishes eligible source,
unbound material, explicit holds, legacy editions, and missing current
translations. When an approved source transaction supplies the first current
material for a missing language/category, the same workflow creates its scope
and prepares it automatically.

## A4 pages and scannable audio codes

New book builds use true A4 pages (210 by 297 mm) with 18 mm body margins. The
original cover is centered and fitted without stretching or cropping. Each
applicable material's opening page reserves a separate title and audio-card row,
so the card cannot float over reader text. The QR is at least 38 mm square,
including a four-module clear border; longer identifiers enlarge the card
instead of shrinking its modules. Right-to-left and left-to-right languages
place the card on the appropriate outer side.

Existing audio books are queued for the A4/QR upgrade. Their previous verified
downloads stay available until the replacement passes its Word, PDF and visual
checks. Unchanged books without audio retain their verified files until their
next normal rebuild. A code is inserted only when an exact matching approved
audio asset exists.

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
