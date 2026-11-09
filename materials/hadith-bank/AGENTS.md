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
