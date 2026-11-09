# Current reviewed Seerah editions

The book source inventory previously selected only the three revised Arabic
`new-adult` chapters. That restriction also excluded separately reviewed Seerah
readers in eleven other languages. Their existing publication records do not say
that the revised Arabic edition replaced those language editions.

This integration admits an explicit inventory of 68 existing chapters as
`current-lecture-sequence`. It preserves their original lecture sequence,
chapter numbers, titles, reader text, questions, source credits and qualifications.
The revised Arabic `new-adult` edition remains a separate source edition. These
translated chapters are not represented as translations of its three chapters.

## Exact membership and release state

| Language | Existing chapters admitted | Source format | Automatic preparation | Automatic release |
| --- | --- | --- | --- | --- |
| Hindi (`hi`) | 1–10 | Reviewed chapter envelopes | Enabled | Held: chapter 1 question review hashes |
| Russian (`ru`) | 1–10 | Reviewed chapter envelopes | Enabled | Held: chapter 1 question review hashes |
| Spanish (`es`) | 1–10 | Reviewed chapter envelopes | Enabled | Held: chapter 1 question review hashes |
| Persian (`fa`) | 1–10 | Reviewed chapter envelopes | Enabled | Held: chapter 1 question review hashes |
| German (`de`) | 1–9 | Reviewed chapter envelopes | Enabled | Held: chapter 1 question review hashes |
| Simplified Chinese (`zh-CN`) | 1–9 | Reviewed chapter envelopes | Enabled | Held: chapter 1 question review hashes |
| Uzbek (`uz`) | 1–2 | Reviewed first-pair readers | Enabled | Existing Word and visual gates apply |
| Thai (`th`) | 1–2 | Reviewed first-pair readers | Enabled | Existing Word and visual gates apply |
| Vietnamese (`vi`) | 1–2 | Reviewed first-pair readers | Enabled | Existing Word and visual gates apply |
| Japanese (`ja`) | 1–2 | Reviewed first-pair readers | Enabled | Existing Word and visual gates apply |
| Filipino (`fil`) | 1–2 | Reviewed first-pair readers | Enabled | Existing Word and visual gates apply |

The allowlist is finite. Adding an edition label to another catalog row does not
give that row the source bindings or review evidence needed for selection. The
catalog change adds the edition field to these 68 rows only; it does not alter
their original publication status, review qualifications or source files.

## Existing evidence

The immutable public source baseline is commit
`b1388fb7b70d4e0178ebf49975e0eb21c2e86022`. The source projection binds the exact
current JSON and Markdown readers, their accompanying public evidence and source
conditions, original catalog fields, and publication metadata. The new edition
label records the conversion's edition boundary; it is not presented as a field
that existed in the historical publication.

For the 58 chapter envelopes in Hindi, Russian, Spanish, Persian, German and
Simplified Chinese:

- Each original `review.status` is `approved-independent-ai-reviewed`, and each
  original `review.humanCertification` is `false`.
- All 58 current `content` objects match their recorded review hashes. Chapter 1
  uses `review.finalTranslationSha256`; later chapters use
  `review.integratedTranslationSHA256`.
- All 58 `review.sourceArabicSHA256` values match the corresponding original
  lecture-sequence Arabic chapter's `content` object. This comparison does not
  substitute the revised Arabic `new-adult` text.
- Every one of the 260 question translations in chapters 2 and later matches its
  recorded individual `review.questions[].translationSHA256` value.
- The source hash serialization for those checks is the original spaced,
  key-sorted JSON representation:
  `json.dumps(value, ensure_ascii=False, sort_keys=True).encode('utf8')`.

For the ten first-pair readers, the original catalog rows say
`current-app-edition`, and their source payloads say
`independently model-reviewed; human verification needed`. The existing
`seerahFirstPairs1003` records in both `materials/catalog.json` and
`materials/translation-status.json` explicitly describe the readings as
independently model-reviewed, installed locally and published. These original
qualifications remain in force.

`materials/translation-status.json` records the corresponding per-language
`seerahAppCoverage`. `materials/seerah/combined/README.md` identifies the newer
language chapters as reviewed current coverage, and the first-pair README names
the ten individual readers. These are source publication and integration
records. The current app v111 base-reader runtime was unavailable during this
audit, so the integration does not claim to have compared against that runtime.

## Chapter 1 question evidence that remains unresolved

The six chapter 1 envelopes contain recorded `finalQuestionsSha256` values that
do not reconstruct from the current exported questions using the available
source schemas. Their individual and combined published reader files contain
identical question payloads, but that equality alone does not establish the
historical review hash's original structure.

Eight individual hashes are verifiable for questions S1 and S2 in Hindi,
Russian, Spanish and Persian. Another twelve original individual approvals for
S33, S34 and S35 in those languages bind the existing flat question object:
`{'id': question['id'], **question['translation']}`. Its hash, using the same
spaced, key-sorted JSON serialization, matches the original
`review.extraQuestionsIndependentReview.records[].approvedTranslationSha256`.
Each matching original record has the same language and question ID, an approved
decision, verified answer order and `humanCertification: false`. The projection
retains that exact object shape and original review pointer; this is recovered
evidence, not a new approval.

The remaining ten individual chapter 1 question bindings are unreconciled:

| Languages | Questions with unreconciled individual review bindings |
| --- | --- |
| German, Simplified Chinese | S1, S2, S33, S34 and S35 in each language |

No aggregate `finalQuestionsSha256` equivalence has been established for any of
the six languages, and this audit does not conclude that the question text
changed. It retains the exact current questions, all original recorded hashes
and the original review qualification. The projection exposes the unresolved
aggregate evidence and ten unresolved individual bindings; all six corresponding
declarations set `automaticRelease` to `false` and name the chapter and question issue in
`releaseHold`. Preparation includes every question so the complete candidate
can be inspected. The release hold requires reconciliation of the exact
historical review binding; it is not cleared by a successful render or by
restating the outer reviewed label.

## Preservation contract

The reader conversion retains the complete supplied chapter order and all
reader blocks. It keeps source quotations, notes, glossary entries, questions
and answer choices, source credits, links, edition and publisher information,
variant distinctions and source conditions bound to their original fields.
Existing editorial translations stay distinct from quoted published wording.
Research metadata and original unresolved qualifications remain identifiable;
they do not become new translation approvals.

Across the 68 chapters, this includes all 3,845 supplied typed reader blocks,
36 additional source-only notes, 340 questions with 1,020 answer choices, 19
reader-note entries and 24 glossary entries. Public edition reviewer credits and
the Vietnamese/Thai channel credits retain their original names, URLs and
relationship qualifications. Shared source and reuse conditions appear with
chapter 1 in each language, including the opening grant that defines which
editorial contributions the reuse permission covers.

All original source JSON and Markdown bytes remain unchanged. Their exact hashes
are part of the inventory. The new source format uses the existing scoped
publication mechanism; an unbound source, changed review record, retired catalog
row or different edition must not silently reuse these bindings.

German chapter 4 also contains a raw whole-page PDF research extraction at
`review.quoteProvenance[1].originalPageText`. It includes eleven nonprinting
backspace controls and unrelated neighboring reports. That exact extraction
remains hash-bound source evidence with an explicit evidence-only disposition.
The book includes the separately supplied selected Bukhari 2262 reading, complete
publisher footnote 366, page 214, edition, source URL, permission and original
normalization qualification. Source bytes are not stripped or rewritten to make
the research extraction printable. A corpus regression serializes every emitted
title, heading and block into DOCX, saves it and reopens it to verify exact text.

All eleven declarations require actual Microsoft Word layout verification and
final visual acceptance. This integration creates neither translation approval
nor human certification, and it does not mark a prepared file as a released
download.

Reference readiness remains separate from literal text preservation. Exact
supplied locators and original paragraph-and-quotation review witnesses bind
references where the source supports them. A repeated quotation keeps its
existing parent passage range when no individual verse number was supplied.
The Persian chapter 3 quotation at original block 20 binds to the immediately
following source label `بقره: ۱۹۹` through the exact Persian surah name at
`books/assets/surah-names.json` → `fa[1]`, yielding the original reference 2:199.
The name table is hash-bound, and its exact locator and source pointer remain in
the evidence. This preserves the supplied independent-AI-meaning qualification.
All 68 chapters now have zero unresolved reference counters; the six separate
question-review release holds remain in force.

## Coverage boundaries

The prior 625 selected units consisted of 227 extended Quran readers, 348
Essential Hadith readers, three revised Arabic Seerah chapters and 47 current
Arabic articles. Adding these 68 exact Seerah readers brings the preparation
inventory to 693 units across 53 scopes. The existing 42 released editions with
489 units retain their own exact membership until replacements complete all
applicable gates.

The source audit also confirmed that all 13 repository languages with Essential
Hadith 4 already include that lesson in their published snapshots. Bengali,
Filipino, Hindi, Thai, Urdu, Vietnamese and Simplified Chinese have no canonical
lesson 4 source in this checkout. This repository finding does not settle the
contents of a separately installed app. First-Hadith source recovery is tracked
separately.

All 227 registered extended Quran sources and all 47 current Arabic articles are
already selected. The article inventory includes the unnumbered 47th article.
All 47 raw material hashes and semantic reading hashes were verified. The older
standalone article has an explicit supersession record linking it to current
Arabic article 26; those historical translations are not translations of the
current merged article.

Another 198 Seerah source-package rows remain outside this change: 22 chapters
each in Arabic, English, French, Turkish, Indonesian, Malay, Brazilian Portuguese,
Urdu and Bengali. Their exact current review and app-edition status has not been
established by this audit. All 198 source-package wrappers lack an independent
review envelope; English chapter 1 additionally records a specific Rowwad
quotation/source correction, which is not a whole-chapter review record. They
are not admitted by a general legacy rule or
declared obsolete merely because Arabic has a revised edition. Four additional
Arabic chapters, 23–26, are explicitly stored as source archives. The extended
Quran selection also does not import the separate simplified edition or
work-in-progress wrappers as if they were newly reviewed extended readers.

The existing 31-scope preparation run remains tied to its immutable source
commit. This integration does not rewrite its fingerprints, snapshots or source
commit to make older preparations appear current.
