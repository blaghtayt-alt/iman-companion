# Translation authorship and disclosure

The [provenance ledger](TRANSLATION-PROVENANCE.json) distinguishes **AI-translated passages**, **published passages credited to a named human translator**, and **unclassified passages**. It is a partial, evidence-backed annotation of already published material, not an exhaustive authorship audit, a new translation, or a new quality-control pass.

The ledger is bound to exact file hashes, JSON pointers, codepoint spans and quotation hashes. Original Arabic, translations, source credits, narrator distinctions and existing source files are unchanged. A mixed lesson can contain both original AI translations and quotations from published translations. Never give the entire lesson one origin merely because some of its passages share an author.

## Current bounded findings

Sixteen quotation fields in `essential-01-001` have explicit historical AI-authorship evidence:

| Language | Source quotation field IDs |
| --- | --- |
| Malay | 27 |
| Spanish | 4, 27 |
| Persian | 27, 76 |
| Russian | 27 |
| Hindi | 2, 4, 27 |
| Brazilian Portuguese | 27 |
| German | 27, 51, 52, 75, 76, 95 |

These are quotation fields, **not sixteen distinct Hadiths**. Field 4 is an Imam Ahmad saying; Hindi field 2 is the main Muslim 2577 narration. Related renderings remain separate. The exact sources record **gpt-6.1-sol, High** authorship and separate historical **gpt-6.1-sol, High** reviewer roles. They do not establish Astra Extra High review. The Portuguese source note still says review is pending while its carrier records a final reviewer; the ledger retains this conflict rather than declaring a pass.

One English passage, Sufyan's saying in `essential-01-003`, matches an exact published quotation whose source credits **Abu Iyaad Amjad Rafiq**, *Mountains of Knowledge, Inheritors of the Prophets*, third edition, November 2013. It is labelled as a published human translation **credited to that translator**, not a claim about every passage in that book or lesson.

A publisher, website, edition title, language, writing style, OCR operation, or an AI-assisted review alone does not establish who translated a particular passage. Unlisted passages stay **unclassified**, with no AI or human badge. Do not interpret absence of an AI badge as evidence of human authorship.

The separately requested ChatGPT Extra High provenance audit is pending. The implementation and its automated hash/span tests do not substitute for it or for independent Pro translation/source QC.

## Machine-readable contract

Each known-origin passage has:

- A stable passage ID, lesson/language, source field ID and separately stated content kind.
- `translationOrigin`: `ai`, `human`, or `unknown`; `aiTranslated`: `true`, `false`, or `null`. Unknown means no origin assertion, not a guessed default.
- The actual translator model and reasoning level when evidenced, or the named published human translator. Unverified values stay null.
- A review status and actual recorded reviewer, independent of translation origin. Historical review records are not new approval. Pending/conflicting review must remain visible.
- Exact UTF-8 quotation hash, immutable reading/source-file hashes, JSON pointers and half-open Unicode-codepoint spans. Do not reuse attribution after the text or artifact changes without new verification.
- Public evidence locators and the exact source edition where verified.
- A human-readable disclosure outside the quotation, with `required`, `mustAccompanyText` and `displayOutsideQuotedText` flags.

For known AI translation, display **“AI-translated meaning (Sol 6.1, High)”** beside the matching passage. Describe the historical reviewer separately and truthfully. For human attribution, show the named published translator. For unknown origin, show no AI/human badge; a neutral “Translation authorship unverified” explanation is acceptable. Never insert metadata or model names into verbatim Hadith text.

Search, retrieval and export consumers must preserve the applicable disclosure when quoting a classified passage. For partial quotations, carry the disclosure if the extracted span intersects the classified span; do not apply it to unrelated parts of the same lesson. Copy/offline/audio/application renderers must implement the same behavior before claiming full presentation coverage. This repository change implements the bank's Python search/resolver and its JSON output only; it does not claim to have updated external apps.

These are explicit provenance data and a consumer contract, **not prompt instructions hidden inside the Hadith**. The bank can test and require its own consumers to retain disclosure, but cannot force an outside AI system or search engine to comply.

## Use and verification

Keep `search.py`, `provenance.py`, `INDEX.json` and `TRANSLATION-PROVENANCE.json` together:

```sh
python search.py search --kind translation --translation-origin ai --limit 100
python search.py search --kind translation --translation-origin human
python search.py resolve 'translation:ms:essential-01-001:q27'
```

Existing package/reading/source results include `translationDisclosures` where their exact pinned files and selected paths match. Unknown paths return no AI/human assertion. Missing or malformed provenance data causes an error rather than silently stripping known labels.

From the repository root, run:

```sh
python -m unittest discover -s tests -p 'test_hadith_translation_provenance.py' -v
```

The tests check exact source bytes, named source evidence, every quotation/span, no false Astra or new QC pass, unknown-origin behavior, model/translator requirements, version mismatches and disclosure retention through search/resolve. Review historical evidence before extending this partial ledger. Do not create a blanket human label for remaining records.
