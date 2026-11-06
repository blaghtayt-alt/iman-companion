# Arabic Quran-reader source catalog

This is a metadata-only reference catalog and review queue for the installed Arabic Quran reader. It is a source-audit handoff, not a publish-ready hadith text collection. No application files or shared registry are changed by this handoff.

## Files

- `PUBLIC-CATALOG.json` contains citation-reference families, source locators, provenance, candidate parents and source-specific assessments.
- `PUBLIC-OPEN-LEADS.json` contains bibliographic locators and quoted-report leads that need further classification.
- `PRIVATE-AUDIT-AND-COVERAGE.json` records validation results and input hashes. `PRIVATE-SCOPE-INVENTORY.json` and `PRIVATE-CITATION-OCCURRENCES.json` retain local document paths and source contexts for verification. The `PRIVATE-SOURCE-CHECK-*` files and other private evidence retain captured source-page projections and must not be published as catalog content.
- `MANIFEST.json` identifies the handoff files and their hashes. The Python files document the repeatable extraction, catalog construction, lead review and validation process.

## What was covered

The installed snapshot has 141 active surah-and-mode groups. At least one filed source document matched a runtime hash for 126 groups; 15 groups had no matching filed document identified in this bounded inventory. The 16 recently verified source documents were rehashed and checked against the recorded installed and public readback receipts. Their recorded public reader links are pinned to commit `99ea5d3813df6b5ce27943181eb3823643f0a52e`.

The bounded extraction identifies 1,794 occurrences of explicitly numbered, named source citations, including 209 occurrences in the selected 16 documents. It groups them into 883 printed reference keys, including 128 represented in the selected 16, and separately catalogs one attributed Companion saying. Of the 1,794 occurrences, 1,608 have a verified original document XML paragraph; 186 remain unlinked. All 209 selected-16 numbered occurrences are paragraph-linked. The paragraph index is zero-based across all Word `w:p` elements in `word/document.xml`.

The wider search was limited to the recorded installed snapshot, filed originals and identified local source packets. Citation forms outside the parser, unnumbered reports and source texts in other repositories or lesson envelopes have not been exhaustively inventoried. Thirty-five of 36 separately collected bibliographic occurrences remain unclassified. Nine selected-16 quoted-report leads were reviewed: eight are related to reference families in their source paragraph, and one is identified separately as an attributed Companion saying. These counts describe only the bounded leads, not all possible unnumbered quotations.

## How to interpret the records

A `familyId` represents a printed collection-and-locator key, not a verified common narration. A family may contain different chains, narrators, wordings or editions, and a number can be a range or a volume/page locator. The main `variantId` remains unresolved unless otherwise specified. Quran verses, tafsir and historical or Companion statements must not automatically be treated as Prophetic hadith.

Each occurrence records the reader location and its printed citation. A source document hash and paragraph index appear only where that paragraph link was verified. Reader URLs exist only for the 16 source-hash-matched public readbacks; the audit did not independently compare each public JSON paragraph. Source links point to inspected pages or previously captured source packets, but a collection-number match by itself does not establish that the complete variant matches the occurrence.

The archived Bukhari and Muslim provider candidates use sequential provider IDs taken from actual archived rows, alongside the provider's separate Arabic number. Their URL syntax follows the [hadith-api documentation](https://github.com/fawazahmed0/hadith-api); each derived endpoint has not been fetched independently. HadeethEnc candidates are linked where a nearby Arabic fragment matches the archived parent after normalization and the source collection is named, but that does not establish the chain or full wording. Inspect the parent and select the appropriate variant before reuse.

Among the 128 recent numbered keys, 109 have at least one candidate from the bounded sources and 19 do not. Across all 883 numbered keys, the corresponding counts are 680 and 203. Candidate availability is not confirmation of an exact match or proof that a source is unavailable elsewhere. Some unresolved locators are ranges or page references rather than individual hadith numbers.

Grades are scoped to the cited source and evaluator; they are not a blanket authenticity verdict. In particular, qualified assessments remain qualified and different evaluators remain separate. Native-language parent links are candidates for review, not permission to copy passages, proof of an exact variant, or a substitute for translation review. Arabic report text and native translations are intentionally omitted.

All source records are citation traces, not doctrinal or publication approval. The identified Companion saying is traced to al-Zamakhshari's Quran commentary *al-Kashshaf*. Al-Zamakhshari adhered to Muʿtazili theology, although scholars differ in their assessment of how it appears throughout the commentary; see this [academic study](https://www.cambridge.org/core/journals/bulletin-of-the-school-of-oriental-and-african-studies/article/abs/you-cant-tell-a-book-by-its-author-a-study-of-mutazilite-theology-in-alzamakhsharis-d-5381144-kashshaf/C9535823813C6FF60BC6A2779BEE5ACA). The commentary attribution does not establish an independently authenticated chain. Any newly adopted religious meaning needs the project's qualified Sunni review. No tafsir source, reader attribution or scholarly saying is automatically approved or promoted to a verified Prophetic report.

The existing public starter catalog indexes lesson envelopes, not individual hadith records. A finite check of the two Arabic parents explicitly identified in English lesson 003 found no numbered-key matches. This does not establish that the other 883 keys are absent from every existing source envelope or bank.

## Validation and next review

The handoff check rehashed the 16 selected originals, reconciled the complete 1,794-occurrence multiset, checked all 1,608 linked occurrences against 91 original document hashes and their recorded XML paragraphs, and verified all 953 archived provider candidate rows and derived locators. The private audit identifies the pinned inputs and exact checks. A public-field scan checked for local file paths and private context fields.

Unresolved citation metadata may be published as a clearly labelled research index with its existing limitations and non-approval statuses. Before adopting, quoting, or integrating any candidate as religious content, classify its citation and report type; verify its full narrator, chain, wording, and variant against an appropriate parent; preserve evaluator-specific qualifications; and review native-language wording and applicable source conditions. The 35 unresolved bibliographic occurrences and 186 unlinked reader occurrences remain open. This catalog alone makes no claim that the installed reader's entire set of reports is complete or authenticated.
