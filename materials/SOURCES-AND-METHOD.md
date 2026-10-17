# Sources and preparation

## Tadabbur

The Arabic source documents are the starting point. Most are based on Ahmad Abd al-Mun'im's lessons on [إنه القرآن / Its The Quran](https://www.youtube.com/c/itsthequran). Some combine more than one lecture or teacher. A filename that mentions multiple sources should not be read as attributing every sentence to one speaker. The supplied references and source filenames are retained in the JSON entries.

There are two reading modes:

- **Extended:** the fuller discussion, including explanations, examples, connections, and qualifications. Newer documents marked “Source Rich” were prepared to retain more of that source material. Older Extended entries are included too; the mode name alone does not certify a Source Rich edition.
- **Simplified:** the material supplied for the shorter reading mode. It keeps the main reflection and relevant evidence. A few documents placed in the Simplified source folder still describe themselves internally as expanded or Source Rich. Their wording has been preserved; their folder placement determines the app mode.

The aim of summarizing is to remove repetition and make the discussion readable without replacing its meaning. Quran quotations, related verses, hadith, examples, and the speaker's qualifications need to remain distinguishable. A reference should not imply that an example is itself scripture or that a reflection is a direct quotation from a scholar.

For the latest imports, every source paragraph was accounted for. Headings and front matter were separated from the reading text. Long paragraphs were divided at punctuation for the app, with their original characters, paragraph identifiers, and offsets preserved. Color annotations were checked separately from wording. This import check establishes fidelity to the supplied document; it is not a scholarly authenticity certification of every statement in it.

The JSON uses four semantic color roles. Markdown keeps readable plain text.

| Role | Color | Meaning |
| --- | --- | --- |
| `current-ayah` | Purple `#7C3AED` | Words quoted from the ayah being discussed |
| `meaning` | Green `#059669` | The main reflection and lessons |
| `example` | Orange `#D97706` | Supporting examples and explanations in Extended mode |
| `related` | Blue `#2563EB` | Related Quran verses and hadith |

Simplified mode has no orange category. The original wording takes priority over a color annotation; a wrong color is a correction to the annotation, not a reason to rewrite the source.

## Seerah

The summaries follow Ahmad al-Sayyid's Seerah lecture sequence. The lecture is the backbone of each chapter. The writing is intended for someone reading the story for the first time: people, events, and references should be introduced before they are relied on. Where a passage refers to an ayah, its relevant wording and reference should be included rather than left unexplained.

The summaries aim for a connected narrative, not personal study notes or a fictional retelling. Extra context should serve the source account and be supported. The current app edition supplies chapters 1–22. The four later Arabic chapters are kept under `source-archive` because they have not been integrated into that edition.

## Under 5

The six Arabic units are published from the supplied teaching documents. Their questions, pauses, examples, and adult prompts are part of the material. They are meant for a parent or teacher to adapt to the child's understanding. No translated edition of these units is claimed in this release.

## Translation and review

Arabic remains the reference text. AI-assisted translation and review aim to preserve the full meaning, names, evidence, qualifications, and distinction between quoted text and explanation. The intended review process uses a separate reviewer to compare the translation with Arabic, flag omissions or additions, check religious terminology, and improve unnatural wording. Work-in-progress files have not necessarily completed that process.

All non-Arabic summaries are published as **AI translated — needs verification**, including those that have passed model-assisted checks. Any `internalReviewStatus` or other historical review metadata records workflow progress, not human certification. Quran or hadith translations quoted from a credited publisher are separate source quotations; their credit must not be replaced with an AI authorship claim.

The `work-in-progress` directory preserves newer translation drafts. They may overlap older editions already in the app and should not silently replace them. Check the source hash and status before combining versions.

## Files and coverage

Markdown is for reading; JSON preserves blocks, semantic spans, source metadata, and entry identifiers where available. File pairs contain the same reading text. The [catalog](catalog.json) records the published coverage and the app snapshot hashes. A missing ayah or language is not permission to invent a reflection, and a document with selected ayahs should not be described as a complete surah commentary.
