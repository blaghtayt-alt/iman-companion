# Language packs

These optional downloads contain illustrated book pages and available children’s teaching audio. They are separate from the [Word and PDF book library](../books/README.md). Interface and reading text stay in the base app.

## Current downloads

The published media packs below contain **95 available pages of Kalila and Dimna** and **19 pages of Alp Arslan**. Kalila has ten chapters; chapter ten currently contains five pages. Book pages, thumbnails and any teaching audio are kept in their own asset folders inside each ZIP.

Arabic, Urdu and Persian editions read right to left. The other published editions read left to right. Downloading a pack does not mean it has already been installed in the app.

| Language | Code | Kalila and Dimna | Alp Arslan | Media pack |
|---|---|---:|---:|---|
| العربية | `ar` | 95 | 19 | [Download ZIP](https://github.com/blaghtayt-alt/iman-companion/releases/download/language-packs-2026-10-24-alp-pages-10-19/iman-ar-10837f59083e978be38c.zip) · 185.9 MB |
| English | `en` | 95 | 19 | [Download ZIP](https://github.com/blaghtayt-alt/iman-companion/releases/download/language-packs-2026-10-24-alp-pages-10-19/iman-en-eeaf24e07c6d07753e4c.zip) · 143.8 MB |
| اردو | `ur` | 95 | 19 | [Download ZIP](https://github.com/blaghtayt-alt/iman-companion/releases/download/language-packs-2026-10-24-alp-pages-10-19/iman-ur-0a3b7c3900ded68a201e.zip) · 147.1 MB |
| Bahasa Indonesia | `id` | 95 | 19 | [Download ZIP](https://github.com/blaghtayt-alt/iman-companion/releases/download/language-packs-2026-10-24-alp-pages-10-19/iman-id-18ab7cd4ef92351959e7.zip) · 151.9 MB |
| Bahasa Melayu | `ms` | 95 | 19 | [Download ZIP](https://github.com/blaghtayt-alt/iman-companion/releases/download/language-packs-2026-10-24-alp-pages-10-19/iman-ms-da6f64877cda88ee875b.zip) · 152.6 MB |
| বাংলা | `bn` | 95 | 19 | [Download ZIP](https://github.com/blaghtayt-alt/iman-companion/releases/download/language-packs-2026-10-24-alp-pages-10-19/iman-bn-7dd4f5d56b56af3a103f.zip) · 148.5 MB |
| Türkçe | `tr` | 95 | 19 | [Download ZIP](https://github.com/blaghtayt-alt/iman-companion/releases/download/language-packs-2026-10-24-alp-pages-10-19/iman-tr-0bc3900b6baa00a85455.zip) · 143.5 MB |
| Français | `fr` | 95 | 19 | [Download ZIP](https://github.com/blaghtayt-alt/iman-companion/releases/download/language-packs-2026-10-24-alp-pages-10-19/iman-fr-116c9f0acfaa5668246e.zip) · 147.3 MB |
| Português do Brasil | `pt-BR` | 95 | 19 | [Download ZIP](https://github.com/blaghtayt-alt/iman-companion/releases/download/language-packs-2026-10-24-alp-pages-10-19/iman-pt-BR-378a12c2e487b2a0f238.zip) · 147.0 MB |
| हिन्दी | `hi` | 95 | 19 | [Download ZIP](https://github.com/blaghtayt-alt/iman-companion/releases/download/language-packs-2026-10-24-alp-pages-10-19/iman-hi-4315686548f564d38f92.zip) · 105.2 MB |
| Русский | `ru` | 95 | 19 | [Download ZIP](https://github.com/blaghtayt-alt/iman-companion/releases/download/language-packs-2026-10-24-alp-pages-10-19/iman-ru-6f42d728f3b7e18972db.zip) · 104.9 MB |
| Español | `es` | 95 | 19 | [Download ZIP](https://github.com/blaghtayt-alt/iman-companion/releases/download/language-packs-2026-10-24-alp-pages-10-19/iman-es-987c6f6601aa8101a2cf.zip) · 104.6 MB |
| فارسی | `fa` | 95 | 19 | [Download ZIP](https://github.com/blaghtayt-alt/iman-companion/releases/download/language-packs-2026-10-24-alp-pages-10-19/iman-fa-e1d87db40f9327df0fb3.zip) · 102.1 MB |
| Deutsch | `de` | 95 | 19 | [Download ZIP](https://github.com/blaghtayt-alt/iman-companion/releases/download/language-packs-2026-10-24-alp-pages-10-19/iman-de-d7593916cee2536f9cdb.zip) · 106.2 MB |
| 简体中文 | `zh-CN` | 95 | 19 | [Download ZIP](https://github.com/blaghtayt-alt/iman-companion/releases/download/language-packs-2026-10-24-alp-pages-10-19/iman-zh-CN-529bfda4e73a08384dbb.zip) · 106.0 MB |
| Oʻzbekcha | `uz` | — | — | No published illustrated-media pack |
| ไทย | `th` | — | — | No published illustrated-media pack |
| Tiếng Việt | `vi` | — | — | No published illustrated-media pack |
| 日本語 | `ja` | — | — | No published illustrated-media pack |
| Filipino | `fil` | — | — | No published illustrated-media pack |

The five rows without links are included so all 20 interface languages have an explicit status. Ready Word/PDF publications in those languages remain available through the separate book library.

The app reads the [current catalogue](catalog.json) and verifies ZIP and manifest checksums. Existing downloaded media remain separate from newly available downloads.

## Publishing an update

1. Deliver only reviewed media and its exact handoff, preserving existing app-relative paths and reading direction.
2. Build new versioned ZIPs with the distribution’s `tools/build-packs.py`; keep book media and teaching audio outside `base-app/`.
3. Upload the generated ZIPs to an immutable GitHub release and verify the actual downloads.
4. Publish the generated `catalog.json` only after its assets exist. Preserve increasing catalogue revisions and existing media paths.

See the distribution’s `INTEGRATION.md` for the current source folders and installation contract.
