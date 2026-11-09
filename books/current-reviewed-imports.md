# Current reviewed material restored to book preparation

The export adapters previously selected 489 reader units. Some current reviewed
readers were omitted because their source formats differed from the supported
formats; Filipino Essential Hadith 5 also lacked its central catalogue entry.
This change selects 625 units across the existing four public book categories,
adding 136 current source units without importing superseded editions.

## Restored sources

| Material | Added units | Languages and scope |
| --- | ---: | --- |
| Essential Hadith 1 | 11 | Bengali, German, Spanish, Persian, Hindi, Indonesian, Malay, Brazilian Portuguese, Russian, Urdu and Uzbek |
| Essential Hadith 5 | 1 | Filipino; original source lesson number 5 is retained |
| Quran entries with current Arabic revision hashes | 112 | English, Urdu, Indonesian, Malay, Bengali, Turkish, French and Brazilian Portuguese; 14 existing surah scopes per language |
| Complete current Fatiha packets | 11 | Hindi, Russian, Spanish, Persian, German, Simplified Chinese, Uzbek, Thai, Vietnamese, Filipino and Japanese |
| Complete current Qiyamah packet | 1 | Japanese; all 40 supplied verses and their bounded notes |

The 14 entries-map surah scopes are 1, 15, 17, 40, 55, 61, 62, 63, 68, 93, 98,
99, 101 and 103. A selected-ayah source remains a selected-ayah edition. The
adapter does not imply that every verse of those surahs has commentary.

The three inventories in `books/source-projections/current-*.json` bind the
exact current source files, catalogue identities, existing review qualifications
and relevant Arabic source conditions. A changed, withdrawn or superseded input
cannot silently reuse the earlier binding. These are records of existing source
eligibility; they create no new translation approval or human certification.

## Content and source preservation

The restored Quran readers preserve all 8,105 source paragraphs and 5,978
original citation groups. Original publisher labels, URLs, translation credits,
notes and qualifications retain their exact source strings. Exceptions to native
script checks require an exact approved source field and the unit's own input
bindings; they do not create a general Latin-text or URL exception.

All 11 first-Hadith readers retain their 49 commentary sections, complete main
narration and declared notes. Uzbek's current export contract also requires its
source context. Its separate appendix preserves all 99 complete source parents,
10 publisher notes, four readable public source companions, the source-notes
document and 35 exact qualification fields. The two required publisher credit
links keep both their original labels and destinations. Private research,
rejected publications and internal review workpapers are excluded.

Fatiha's separate source carriers remain hash-bound. Material explicitly confined
to those source carriers is not promoted into the ordinary reviewed reading.
Shared Qiyamah publication notes may be printed once, with every source occurrence
mapped to its printed location; repeated verse-specific notes retain their verse
anchors.

## Remaining gaps and excluded history

- French Hadith 1 has an outer reviewed label but a current inner status of
  `COMPLETE_AUTHOR558_SUCCESSOR_PENDING_ACTUAL_DISTINCT_FINAL`, with
  `independentFinalClaimed: false`. It is reported as review-incomplete.
- No current canonical first-Hadith reader is present in this repository for
  English, Turkish, Simplified Chinese, Thai, Vietnamese, Filipino or Japanese.
  Their later lessons retain their original numbering. This does not determine
  the state of a separately installed app.
- Hadith 4 is absent from the current repository sources for Bengali, Filipino,
  Hindi, Thai, Urdu, Vietnamese and Simplified Chinese.
- Older Seerah editions remain excluded from the revised current adult edition.
  Historical standalone articles replaced by merged current articles are not
  restored.

## Published editions and release behavior

At this change, 42 verified books contain 489 units. The 136 additions affect
31 editions: 19 Quran books and 12 Hadith books. Existing verified downloads keep
their exact files, hashes and included-unit lists while expanded editions await
their normal release checks. A continuity fix preserves the full catalogue review
metadata and related source-language rows when validating an earlier edition.

Download pages now distinguish the contents of the actual released file from
newly selected material awaiting release, incomplete review and absent current
sources. They show explicit lesson or surah numbers and mark partial editions.
No previously released file is represented as containing the new additions.

The changes preserve the actual Microsoft Word layout and final visual acceptance
requirements. A successful source import, DOCX serialization test or diagnostic
PDF is not a finished-book approval. Expanded files must pass those existing gates
before replacing the published downloads.

## Regression coverage

The workflow includes source-preservation tests for all restored formats,
negative tests for altered sources and review qualifications, exact note and
hyperlink serialization, rejection of swapped credit destinations, source-cache
invalidation, coverage diagnostics and continuity of earlier verified editions.
The current source formats are exercised against the repository's actual
published readers, including every restored Quran scope and first-Hadith language.
