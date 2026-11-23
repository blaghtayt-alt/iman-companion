# Private approved Arabic Tadabbur passage review — 23 November 2026

**NOT A RELEASE. NOT THE COMPLETE 84-SURAH BOOK. NOT REGISTERED FOR PUBLIC DOWNLOADS.**

This books-only review candidate is a private preparation snapshot proposed for editorial and Word-layout inspection. It leaves app content, visibility, source prose, current reader registration, published-library metadata, and download URLs untouched.

## Exact source and approval evidence

- Source Git commit: `6ee7f24bfc39c8332f26683f044db183e4c90adb` (later main commits inspected only changed translated Fatir, not these Arabic paragraphs).
- Al-Baqarah **2:106, 109, 110, 114, 115, 122, 124, 125**: `materials/tadabbur/finite-corrections/2026-11-23-baqarah-owner-v3.json`; 20/20 exact SHA-256 paragraph matches.
- Al-Ma'idah **5:67 paragraph 1**: `materials/tadabbur/finite-corrections/2026-11-23-owner-followup.json`; exact SHA-256 match.
- Al-'Ankabut **29:43 paragraph 1**: `materials/tadabbur/finite-corrections/2026-11-23-fatir-ankabut-owner-v3.json`; exact SHA-256 match. Later paragraphs are not asserted approved here.
- Fatir **35:2, 9, 10, 14, 15, 16, 18, 19, 25, 27, 37, 43**: `materials/tadabbur/finite-corrections/2026-11-23-fatir-ankabut-owner-v3.json` and `2026-11-23-fatir-latest-owner-b10.json`; 60/60 exact SHA-256 paragraph matches.

**Result: 22 selected ayahs and 82 approved Arabic commentary paragraphs.** The source ayah quotation and its original commentary paragraph text, order, punctuation and inline citations were carried without rewriting. Any current app-hidden flag is not treated as independent approval: inclusion is authorized by the named owner-review receipt and exact paragraph hashes.

## Actual output files and validation

- Word: `Iman_Tadabbur_Approved_Arabic_Passages_Private_20261123.docx`
  - SHA-256: `df0743f771fb81a806f616d36b606b7f662c71b008aececd9c430120e45f2124`
  - Reopened and validated: 82/82 approved paragraphs present verbatim in source order
  - 139 bidirectional paragraph tags and 139 RTL run tags
- PDF: `Iman_Tadabbur_Approved_Arabic_Passages_Private_20261123.pdf`
  - Exported by actual Microsoft Word from this DOCX, 16 A4 pages
  - SHA-256: `f553c76434fb6ad6c3b235592c781be28c45911824aad6273d7cf730750d32fe`
  - All 16 pages rendered; no blank-text pages; sampled first/interior/last pages visually checked
- Manifest: `Iman_Tadabbur_Approved_Arabic_Passages_Private_20261123.manifest.json`
  - Each source JSON file and approval receipt is SHA-256 bound by ayah and paragraph
  - No matching prior BEFORE full-paragraph SHA-256 from the inspected owner receipts appears in the DOCX

## Specific evidence still missing (not duplicate wording approval)

- **18:12 paragraph 1** — owner receipt approves a bounded corrected phrase only, explicitly excluding the entire surrounding paragraph. To include the whole paragraph, Iman Maestro/source reviewer must supply its independently reviewed whole-paragraph release scope.
- **18:50 paragraph 1** — same separate bounded-phrase limitation and same reviewer obligation.
- **English/French 98:intro paragraph 7** — the Nov 16 receipt contains an independent-review digest but not the actual original review artifact or exact current-reader publication envelope. Iman Maestro/source-review custodian must supply that evidence; do not ask the owner to reapprove unchanged 98:1.
- Full Arabic 84-surah compilation — stale review/source bindings for unrelated members require exact source-bound whole-reader registration by the books integrator. Passing these 82 paragraph checks does not waive that release gate.

## Merge and release restriction

**Do not merge or deploy this PR without the owner's explicit approval.** It is not processed into `books/published-library.json`, `books/downloads`, or `docs/books/catalog.json`. The existing publisher must still complete source registration, complete-edition selection, real final Microsoft Word readback, full visual inspection, and verified download URLs before publication.
