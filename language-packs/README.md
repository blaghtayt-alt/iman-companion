# Language packs

These optional downloads contain book pages and children’s teaching audio for Iman Companion. The interface and reading text remain in the base app.

The app checks [catalog.json](catalog.json) weekly when it is open or resumed. Users can download an update or keep the version already saved. It never downloads media automatically.

## Publishing an update

1. Put reviewed media in `language-packs/source/<language>/`, keeping its existing app-relative paths.
2. Run the distribution’s `tools/build-packs.py` with the new GitHub release URL.
3. Upload all generated ZIPs to that release and verify their downloads.
4. Only then replace this folder’s `catalog.json` with the generated catalogue. Keep its increasing revision, SHA-256 checksums and complete path mapping.

Keep existing paths available so older app versions can continue to read their books. Do not put draft media or full book images into the base app. Detailed delivery conventions are in the distribution’s `INTEGRATION.md`.

Current downloads: [Alp Arslan revised opening — all 15 language packs](https://github.com/blaghtayt-alt/iman-companion/releases/tag/language-packs-2026-10-20-alp-revision).

Alp Arslan includes the approved nine-page opening in all 15 languages. Arabic, Urdu and Persian read right to left; the other editions read left to right. See the [edition metadata](metadata/alp-arslan/editions.json) and [reviewed delivery notes](handoffs/alp-arslan).
