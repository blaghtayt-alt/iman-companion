# Current app material reconciliation

The catalog contains 338 records outside the four book categories currently
handled by the automation. This ledger accounts for all 338 records and keeps
their remaining work visible. It does not add book categories, create source
approvals, or treat an older export as the current app edition.

The source audit uses immutable commit
`b1388fb7b70d4e0178ebf49975e0eb21c2e86022`. The current app v111 base-reader
runtime is unavailable in the accessible repository. Its reported Windows
workspace is offline. The repository's optional language packs contain media;
their README says interface and reading text remain in the base app. Source
publication and review records can therefore be verified here, while exact
current app membership still requires the current reader inventory.

## Complete partition of the 338 records

| Collection | Catalog records | Actual supplied coverage | Verified source evidence | Remaining decision |
| --- | ---: | --- | --- | --- |
| Under-5 teaching course | 120 | Six units and 39 lessons in each of 20 languages | Original Arabic editorial review; 19 translated course review records; course/unit agreement and existing hash checks below | Map the current app course and reconcile the Turkish approved-course hash before any new export adapter |
| Ibn al-Qayyim sayings | 20 | 37 sayings with separate explanations per language, 740 items total | Exact source files, source/attribution records, five explicit whole-collection model-review catalog qualifications; other languages retain their existing qualifications | Match the distinct current 37-saying app edition and obtain adequate whole-collection review bindings for each language |
| Historical Hadith reading collection | 7 | 1,209 report bodies across seven language collections | Explicit archive declaration in the Hadith README, with original per-report source/review metadata | Keep historical; no automatic restoration as Essential Hadith or Heart Reminder |
| Heart Reminder Hadith readings | 186 | 36 protected report identities in five languages, four additional forgiveness readings, two corrected source readings | All 184 indexed wording/segment hashes verified; two additional corrected readings match their selected source records | Match the later Heart v1.2/current app component, preserving replacement and source distinctions |
| Heart Reminder Quran packets | 5 | 418 eligible whole language placements, two held Vietnamese placements, 557 published verse bodies | Exact packet and source-credit files; all eligible placement keys are present | Match current Heart placements and source selection; retain both Vietnamese holds |
| **Total** | **338** | **61 collection/language scopes** | **All catalog JSON and Markdown paths checked and hashed** | **No additional book scope enabled by this audit** |

These counts are catalog records, not interchangeable counts of lessons,
narrations, verse bodies or books. The seven historical collection records are
explicitly archived. The other 331 records require a current app mapping; this
ledger does not label all of them obsolete or certify all of them for release.

## Under-5: reviewed course source, separate teaching category

The source files are `materials/under-5/{language}/unit-01.json` through
`unit-06.json`, their Markdown readings, and `course.json`. The course has 39
lessons, 45 headings and 1,262 body positions per language. The source/review
record is `materials/under-5/SOURCE-NOTES.json`; the public index is
`materials/under-5/README.md`.

All 114 translated unit objects exactly match their corresponding course units.
The six Arabic unit readers retain the same titles and complete lesson objects
as the Arabic course. The Arabic course's raw hash matches the recorded amended
reading edition. Thirteen translated course files match their recorded complete
course hashes: English, French, Hindi, Russian, Spanish, Persian, German,
Simplified Chinese, Uzbek, Thai, Vietnamese, Japanese and Filipino.

Indonesian, Malay, Brazilian Portuguese, Urdu and Bengali match the separately
recorded `appReadingProjectionSha256`: omit only the appended
`translationProvenance` object, then serialize the remaining object using compact
insertion-order JSON with `ensure_ascii=False`. This verifies the declared app
reading projection without claiming that its wrapper has the original approved
candidate file's hash. Together these checks cover 19 of the 20 courses.

The Turkish export retains its original distinct-review statement and recorded
`approvedTurkishCourseSha256`, but that original hash was not reconstructed from
the accessible course. This remains a specific evidence-reconciliation task;
the audit does not infer that Turkish text changed or supply a replacement hash.

Japanese has particularly explicit public evidence:

- `materials/under-5/ja/course.json` matches the recorded approved course hash
  `9357fc2d6be57a8fdeb10323f1a3f89061df3b19e0f8cf3a04015bf1a75381d9`.
- `materials/under-5/ja/PUBLIC-SOURCE-PROJECTION625.json` and
  `JAPANESE-SOURCE-NOTE625.txt` retain the complete source and qualification
  context.
- Its existing final-review record explicitly says runtime/publication was not
  performed by that reviewer. Later public course availability does not turn
  that earlier record into evidence of current app v111 deployment.

All six audio recordings remain in preparation. The course is teaching material
for an adult to read with a young child; it should remain identifiable as that
category when mapped to downloads.

## Ibn al-Qayyim: preserve the distinct 37-item edition

The exact readers are `materials/ibn-al-qayyim/{language}.json` and `.md`; every
one of the 20 JSON files contains 37 items with separate quotation/excerpt and
explanation fields. The index and scope are in
`materials/ibn-al-qayyim/README.md` and
`materials/catalog.json#sayingsCollectionUpdate`.

The catalog explicitly labels Uzbek, Thai, Vietnamese, Japanese and Filipino as
`independently-model-reviewed-not-human-certified`. Fourteen other translated
collections retain the broader `ai-translated-needs-verification` label; Arabic
is recorded as source text. The five newer language files carry richer public
source records, including selected publication information, source conditions,
reading order and meaning/excerpt notices. Some individual approved-object
hashes exist, but this audit does not upgrade them into a verified whole-
collection approval for all 37 items in every language.

Item `iq-11` retains the human-supplied Arabic explanation separately from the
reported quotation. The source record preserves the qualification
`reported-in-book-personal-authorship-unresolved`. Its explanation must not be
attributed to the quotation's reported author. These qualifications are part of
the current source and must survive a future reader conversion.

The remaining task is an exact mapping to the current app's distinct 37-saying
edition, with per-language review/source bindings. Generic category names and
historical publication alone do not establish the current runtime bytes.

## Heart Reminder: verify the current component before restoring exports

The repository exports 36 protected Hadith report identities in Uzbek, Thai,
Vietnamese, Japanese and Filipino: 180 readings. Four further readings of
`forgiveness.hadith.03` are present in English, French, Brazilian Portuguese and
Russian. Two corrected readings add French `rizq.hadith.01` and Brazilian
Portuguese `purpose.hadith.02`, giving 186 catalog rows.

The exact paths are
`materials/hadith/heart-reminder/{topic}-{number}/{language}.json` and `.md`.
`source-index.json` contains 184 indexed records. Its 20
`exactPublishedReaderSha256` values match the corresponding `reading.hadith`
strings; all 164 sets of `exactPublishedQuoteSegmentSha256` values match their
current source-reading fields. These checks bind the published Hadith wording
or segments, while notes, selected parent texts and source conditions remain
separately preserved in the hashed source files.

The two additional corrections are explicitly documented in
`materials/hadith/heart-reminder/source-correction911/README.md`,
`SELECTED-SOURCE-RECORDS911.json`, `HEART-SOURCE-CARRIER908.json` and
`HEC-CONDITIONS908.json`. Their current reading text includes the exact selected
wording. Both retain an existing independent model-assisted final-review
statement and the human-verification qualification.

The user identified a later Heart v1.2 replacement of older incomplete material.
Consequently, these verified source exports still require comparison with the
current Heart component's protected identities, source versions, complete reader
bodies and companion files. Matching a topic label is insufficient to establish
that an old reader survived the replacement. This audit makes no restoration or
current-runtime claim for the 186 exports.

The five Quran packets live at
`materials/hadith/heart-reminder/quran/{uz,th,vi,ja,fil}.json` with Markdown
readings. They contain 418 eligible whole placements and two held Vietnamese
placements: `desire.ayah.01` (24:30–31) and `sabr.ayah.04` (16:127). There are 557
published verse bodies; the source index records 558 independently reviewed
bodies, including one Vietnamese body withheld with its whole placement.

Every eligible placement's verse keys exist in its packet, and all referenced
credit IDs exist in `source-credits.json`. Japanese placements 2:155–157 and
2:216 require an explicit Sato source selection; Tokyo remains the eligible
default elsewhere. Keep `placements.json`, `tokyo-113-companion.json` and
`sato-155-context.json` with those source choices. These are Heart selections,
with their own placement rules and holds, rather than additional extended Quran
commentary chapters.

## Historical Hadith: an explicit archive

`materials/hadith/README.md` explicitly calls the earlier 303-report Arabic
collection an archive with existing per-language coverage. Its seven aggregate
readers are:

| Language | Path | Reports |
| --- | --- | ---: |
| Arabic | `materials/hadith/ar.json` | 303 |
| Hindi | `materials/hadith/hi.json` | 176 |
| Russian | `materials/hadith/ru.json` | 181 |
| Spanish | `materials/hadith/es.json` | 158 |
| Persian | `materials/hadith/fa.json` | 177 |
| German | `materials/hadith/de.json` | 127 |
| Simplified Chinese | `materials/hadith/zh-CN.json` | 87 |

The README also says this collection does not replace the app's Heart Reminder
selections. Per-item review or published-source status remains useful historical
evidence, but it does not make these seven aggregate files current Essential
Hadith lessons.

## Japanese Hadith 1: identity remains unresolved

The current Arabic Essential lesson `essential-01-001` is the reading on divine
justice, self-sufficiency and the servants' dependence, referenced to Muslim
2577. Japanese Heart IDs `approval.hadith.01` and `purpose.hadith.01` instead
refer to the intentions report, Bukhari 1 / Muslim 1907a. Their final number does
not make them the missing Essential lesson.

No matching Muslim 2577 Japanese source was found in the Japanese source bank,
Heart exports, Seerah first-pair readers, extended Quran readers, sayings or
Under-5 source directories. There is no Japanese aggregate file among the seven
historical Hadith collections. `materials/hadith-bank/ja/catalog.json` explicitly
records lesson 001 as having no published structured reading at its canonical
path; its indexed whole source envelope is lesson 003. The current Japanese
Essential source files remain lessons 002–004.

This is an accessible-source finding. It does not establish that a reviewed
Japanese first lesson is absent from the current app. Its exact app reader,
source companions, review record and edition identity must be recovered and
matched before the automation can faithfully include it. No new translation or
renumbered substitute is introduced by this reconciliation.

A bounded continuity/file lookup also searched the exact Muslim 2577 identity,
the Japanese injustice wording and the Essential lesson identifier. It did not
identify an accessible reviewed Japanese reader or its handoff package. The
conversation-history service was unavailable, and a follow-up content lookup in
two possible Hadith extractor files failed with a closed connection. Those
service limits leave source recovery unfinished; they are not evidence that the
reader never existed.

## Outstanding automation work

The readiness report must keep these unmapped collection/language scopes and
their catalog counts visible. A complete current app export should identify each
reader's collection, language, stable material ID, edition/replacement state and
source hashes, together with its actual reader and required companions. Compare
those identities with this ledger, resolve the Turkish course and any remaining
whole-collection review bindings, then add only the confirmed current editions
through explicit source inventories and their normal Word/visual release gates.

An exported source, a catalog row, a finished render and a released download are
different stages. This ledger records the source evidence and unfinished
reconciliation work without changing any of those stages into an approval.
