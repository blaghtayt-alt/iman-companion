# Hadith Bank contributor and agent rules

These rules apply to the Hadith and sayings bank in this directory and its descendants. Read them before creating, translating, extracting, reviewing, or publishing bank records. Existing source-specific conditions and stricter review or reuse restrictions remain in force.

## Explicit AI translation attribution

- Clearly label every AI-generated translation as **AI-translated**. Never present it as a published human translation, a verbatim source quotation, or verified human scholarship.
- The requested workflow for newly AI-translated Hadith is **Sol 6.1 translation**, followed by **Astra Extra High review**.
- After both steps actually occurred and are evidenced for the exact text version, display: **"AI-translated by Sol 6.1; reviewed by Astra Extra High. Human verification remains needed."**
- Before the review is completed, display: **"AI-translated by Sol 6.1; Astra Extra High review pending. Human verification remains needed."** Use the actual translator model instead if an older record used another model.
- Never attribute translation or review to a model that was not used. If model provenance is unavailable, label it unknown; do not backfill Sol 6.1 or Astra Extra High as a blanket claim. Do not silently substitute a model when the requested one is unavailable.
- Review is not proof of authenticity, a scholarly certification, human review, or permission to republish a translation.

## Separate text, metadata, and evidence

Keep verbatim Arabic, translation, isnad, commentary, footnotes, and attribution metadata in distinct fields. Display labels beside the translation or in its metadata, never inside the original Hadith wording.

For AI-translated records retain, at minimum:
- `translation_origin: "ai"`
- actual `translator_model`
- actual `reviewer_model` and `review_reasoning_level`
- `review_status` (pending, passed, failed, or unknown)
- source reference and exact source version
- translation artifact/version or hash
- review evidence, date, coverage, corrections, and reviewed artifact/version or hash

Use unknown/null for unavailable facts. A record's reviewer model and review evidence must correspond to its exact final text, not a different draft.

## Published translations and OCR

Verbatim extraction/OCR of a published translation is **not** a new AI translation. Preserve the original translator, publication, edition, pages, wording, and rights. Record AI-assisted OCR/extraction and its review separately. If AI translates a gap or generates explanatory text, keep that passage distinct and apply the explicit AI translation label to it.

## Separate Pro QC before bank upload

Use Pro chats for the extraction and independent QC workflow. Before extracted artifacts are added to the bank, a **separate Pro QC chat** must compare the exact candidate dataset against its original PDF or verified digital source. An extraction chat's self-review or a claimed in-thread reviewer does not replace this independent check. Record actual coverage and unresolved errors; sampling is not full-book verification.

Only upload final QC-passed artifacts when the target visibility and source/translation reuse rights permit it. Do not publish private evidence or copyrighted source PDFs merely because they are downloadable. Preserve original sources and all existing publication boundaries.

These instructions establish a workflow and truthful labeling requirement; they do not certify or relabel existing records retroactively.

## Original Arabic and complete source coverage

- Include the **verified original Arabic text and its source with every Hadith**. Do not omit any original source cited by the supplied materials or identified during source verification. A translation alone is not a complete bank record.
- Preserve each verified Arabic wording, isnad where present, and edition/version. Keep distinct narrations and textual variants separately identified and linked; never collapse conflicting wording into a synthetic quotation.
- Trace each source in a structured source list: collection/work, author/compiler where known, book/chapter, Hadith/reference number and numbering scheme, edition/publisher, volume and printed/PDF page or stable digital locator, and verification evidence/status. Preserve all cited original references, not just the first or easiest one. Record unavailable details as unknown.
- Distinguish the directly checked Arabic source from secondary citations and cross-references. Do not claim direct verification when only a translation or secondary reference was checked. Never invent a citation or back-translate and label the result original Arabic.
- Keep original Arabic, translations, commentary, and source metadata in separate fields. Link each translation to the precise Arabic version it represents; document unresolved alignment rather than guessing.
- Before publication, perform a **source-completeness audit** for every record and the full candidate corpus. Reconcile every supplied/cited source against the record source lists, and account for missing texts, variants, references, duplicates and exclusions in an audit manifest. Completeness claims must state the checked corpus, editions, coverage, and limitations; do not claim that every source worldwide has been found without evidence.
- Mark missing or unverified Arabic text, source attribution, or translation-to-source alignment explicitly. Keep such records in a non-published work queue and block publication of incomplete-attribution records until resolved. Preserve the unresolved evidence; do not drop a source merely to pass the gate.
- The separate Pro QC review must verify Arabic/source alignment and source-list completeness as well as extraction accuracy. This is a requirement for future work, not a claim that existing bank records have already passed this audit.


## Comprehensive inclusion without destructive deduplication

- Include all additional Hadith found in the verified source materials, not only items already represented in the bank or initially selected for translation. Inventory each source and reconcile its Hadith coverage, including additions, against the imported records. Unverified items remain in the work queue under the publication gates above.
- Preserve every distinct narrator chain and every book/source occurrence as a separately identifiable, evidence-backed record, even when the Hadith wording is identical. Retain collection, edition, reference/numbering, pages or locator, and the chain as actually supplied; missing chain details remain unknown, never reconstructed as fact.
- Link parallel wording, narrations, chains and source occurrences through explicit relationship/group identifiers. Shared text storage or search grouping may be used only if it retains every occurrence, chain, provenance and variant intact. Never destructively deduplicate records merely because their wording matches.
- The completeness audit and separate Pro QC must reconcile all source occurrences and narrator chains, not just unique text counts. Document evidence-backed inclusion, unresolved gaps and justified exclusions; do not silently discard an additional Hadith, chain or occurrence.


## Shared Pro-chat concurrency limit

- Run **at most three active Pro chats in total** for this bank, collectively across extraction, metadata enrichment, and separate QC. This is a shared limit across all workers, not three chats per worker or per phase.
- Coordinate starts through a shared active-work register or a single coordinator. Before starting or resuming work in a chat, confirm the global active count and reserve a free slot so concurrent workers cannot exceed the limit. Treat unknown or unverified status as occupied until resolved; never assume capacity.
- Do not interrupt, cancel, or send new instructions into currently running jobs to enforce the limit. If existing work already exceeds three active chats, let it finish and start no additional work until confirmed capacity is available.
- Release a slot only after the chat is verified idle/completed or otherwise confirmed no longer active. Keep queued extraction, metadata and independent Pro QC work waiting when no slot is available. This limit does not relax the requirement for separate QC or any publication gate.

## Evidence-backed AI versus human attribution

The user's later direction requires truthful passage-level classification of existing and future translations. Consult `organized/TRANSLATION-PROVENANCE.md` and its version-bound ledger. Label AI only with affirmative authorship evidence; label human only with a verified named translator/edition and an exact source match. A book-level credit does not automatically classify all passages. OCR or AI review of a published translation does not make it AI-translated. Leave unverified origin unlabelled (null/unknown), never human by default.

Preserve the actual historical model and reasoning settings. Do not replace historical Sol High review with Astra Extra High merely because the desired new workflow names Astra. An attribution annotation is not a new translation QC approval; preserve unresolved or conflicting review states. Evidence-backed classification may annotate an existing passage, but must not certify it or change its wording. The separately requested Extra High audit remains pending until it actually occurs.

Keep visible disclosures and machine-readable attribution outside verbatim text and carry them through bank search, retrieval and exports. Do not claim tags can force external AI behavior. Unknown fields receive no AI/human badge. Add exact source/version/span hashes and supporting evidence for new labels, run the provenance tests, and do not apply a passage's label to the whole mixed lesson.
