# Iman Companion source and book publication

Work from a freshly verified HEAD. Preserve unrelated concurrent edits. Use an
isolated branch, checkpoint commits, expected-head updates and non-force pushes.
Do not change another writer's branch or overwrite a release asset.

## Approved source changes

Use `books/source_publication_transaction.py` for an approved source publication.
The transaction must include the exact source files, normalized complete reader,
original whole-material review evidence, catalogue registration and approval
handoff together. Its connector bundle supports the same expected-head lease.
Never update a hash merely to make an old approval fit new text. Never generate
a whole-material, translation, scholarly, Word or visual approval from a commit
message, discovery result or earlier assistant claim.

Raw material that is awaiting review may be committed with an explicit pending
state. The workflow discovers it, reports the missing handoff and marks affected
downloads as awaiting an update. It does not silently admit it to a book.

Preserve every current source qualification and literal reference. Use exact
approved corrections; stop the affected material when review versions conflict.
Complete independent scopes while the conflict is resolved.

## Validation and publication

The workflow consumes valid intake before selection, checkpoints registration,
tests code against isolated hash-checked fixtures, and audits the live source
inventory independently. Each production book still requires complete approved
selection, exact source/provenance hashes and export verification. Source-audit
failures are actionable failures, never approval to publish another version.

New prepared Word/PDF files require the real Microsoft Word receipt and final
visual acceptance for those exact bytes. Preserve all scope release holds.
Use the existing finalization intake for accepted candidates. Do not manufacture
receipts or substitute a Linux renderer for actual Word acceptance.

Verify actual public download bodies with `tools/check_live_book_bytes.py`,
including all members of each combined ZIP. A successful Pages deployment,
HTTP HEAD, or a matching old release digest does not prove current source text.
The pending status must be refreshed even when validation or preparation fails.
