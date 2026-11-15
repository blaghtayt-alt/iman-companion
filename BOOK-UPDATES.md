# Updating material and its downloadable books

The user can give a chat one instruction:

> Apply these approved corrections to the current material and affected
> translations, and update the individual and combined downloadable books.

The editing chat owns the complete path below. No second request to the book
chat is required. This uses the existing publisher, not a second export system.

1. Read `AGENTS.md`, verify fresh `main` and coordinate shared writers. Preserve
   the exact current source, original BEFORE/AFTER text, reviewer decisions,
   qualifiers, citations and a versioned change log. Work in an isolated tree.
2. Match the approved correction to exact source fields. Reuse prior whole-reader
   review plus its actual finite correction decisions only where their complete
   scope and byte bindings establish the current reader. Do not infer approval
   from a file's presence, a commit title or a previous chat's completion claim.
   Leave conflicting or unmatched passages untouched and identify the decision.
3. For each eligible source/language, supply the complete normalized reader and
   genuine original review evidence in an
   `iman-approved-material-publication-v1` handoff. Preserve all existing book
   members and original canonical order. Include exact source baselines and the
   fresh catalogue hash. Source snapshots without the reader registration are
   incomplete work; unknown readers must not silently disappear from a book.
4. Use `books/source_publication_transaction.py` (or its existing connector
   bundle), first in dry-run mode. It validates source baselines, the original
   whole-material approval, complete reader coverage and current catalogue, and
   publishes the source, reader, evidence and intake as one non-force Git change.
   Do not edit an old approval's hashes to fit new text. The
   [existing command and handoff contract](books/AUTOMATIC-PREPARATION.md) is the
   authority; this guide does not relax or replace it.
5. The existing `build-word-books.yml` consumes the intake, normalizes eligible
   scopes, builds DOCX/PDF candidates and checkpoints each scope independently.
   Inspect the actual intake, coverage, preparation and source-update reports.
   A green website or accessible old download is not a rebuilt current book.
6. Obtain genuine Microsoft Word readback and final visual acceptance for the
   exact candidate bytes through a route authorized by the user. Never launch
   local Word if the user has prohibited it. Never substitute a synthetic receipt,
   an older edition's review or LibreOffice output for Word acceptance. Keep the
   candidate queued when this gate cannot be completed; other accepted scopes
   can proceed independently.
7. Submit the accepted candidate through the existing finalization intake. The
   publisher atomically refreshes individual assets, DOCX/PDF/ZIP language
   bundles, source fingerprints, catalogue links and hash-bound pending notices.
   Keep previous verified editions clearly pending until their replacements pass.
8. Download the actual advertised bytes again. Run
   `tools/check_live_book_bytes.py`, verify exact full BEFORE absent / approved
   AFTER present in both formats, and verify every affected combined ZIP member.
   For PDF, inspect real extracted/rendered text; a correct filename, HTTP status
   or metadata digest alone does not prove the paragraph changed. Check source
   quotations, references, introductions, first/last entries, coverage and order.

Report the actual source and release commits, exact source/reader and candidate
hashes, acceptance receipts, public URLs and download hashes. Distinguish
**source updated**, **reader registered**, **candidate prepared**, **accepted**
and **publicly released**. An unresolved step must state its precise blocker.

The 1–329 Tadabbur corrections are not to be reverted during this process.
Retain their reviewed changes, translations, protected quotations, source
qualifications and the explicit deletion instruction for item 276. A newer
document is not automatically authoritative over an explicit approved decision.
