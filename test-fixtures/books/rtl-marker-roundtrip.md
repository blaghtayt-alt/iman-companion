# Arabic numeric citation rendering regression

`rtl-marker-roundtrip.b64` contains a small ZIP with one exact previously
prepared paragraph from Article 26, its source JSON, and its existing footnote.
The paragraph is `/articles/25/paragraphs/90` in the approved Arabic Articles
projection. Its literal citation is `[١٦]`. It retains the historical section
geometry that reproduces LibreOffice 24.2's split at the text direction change
(upstream Writer bug tdf#56408, fixed in LibreOffice 24.8).

The decoded ZIP SHA256 is
`7dd022448d514417d0db22c4564cb16b64f1586112882b48a90b2676d5dfc1b1`.
The original diagnostic run was 42497861626, from diagnostic PR29 commit
`a4a784bb8ab83ae49784dbf14f847131668f0f2d`. Both its original prepared input
and rebuilt input reproduced the split after two production renderer saves.

The integration check preserves source text and note order through the two
real UNO saves, pinned font restoration, and page-break normalization. It also
rebuilds the paragraph with the current text builder and tests two narrower
line widths. It verifies that both brackets and both native digits stay on
one baseline and emits page images for inspection. These files are diagnostic
fixtures, not release books or publication acceptance evidence.
