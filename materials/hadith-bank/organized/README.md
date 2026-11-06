# Browse the hadith source bank

[Browse the 12 authored chapters and 286 lesson topics](BROWSE.md), or search the [public metadata index](INDEX.json). The [JSON Schema](INDEX.schema.json) describes the index; [search.py](search.py) is a dependency-free Python 3 search and locator tool.

Chapter and lesson titles are authored catalogue navigation. A title alone does not establish publication, text availability, review, authentication, or permission to reuse a lesson. Review values reflect the app catalogue when recorded; unknown values are `null`. Only explicitly linked published readings and source catalogs are presented as released. A topic or lesson can contain multiple sources and is not automatically one hadith.

The current index distinguishes:

- **Published lesson source packages:** 29 language/lesson packages, with links to the existing source envelopes or source files and their review notices.
- **Reading-only entries:** 19 published readings for which the corresponding complete source envelope was not located. These are not complete source packages.
- **Source metadata:** 617 records of titles, references, and exact locators within the released source packages. These records are **not 617 authenticated hadiths**. Their general content type remains unclassified; they may describe a Quran source, commentary, an attributed saying, scholarship, a quotation, a narration, or a lesson. Inspect the original source and its conditions before use. The index is not a complete full-text search of every source body.
- **Quran-reader citation keys:** 884 keys comprising 883 numbered references and one separately attributed Companion saying, with 1,795 recorded occurrences in total. They represent citations as recorded, not verified narration families, chains, editions, or identity matches. Their `contentKind`, printed source, attribution, source-specific grades, and qualifications remain distinct. A Quran occurrence identifies usage, not the topic or type of a hadith. Some links and matches are explicitly qualified or unverified; preserve those qualifications.

No two records are merged merely because their numbers, titles, or normalized words match. Existing human verification and source-condition notices continue to apply.

## Search and resolve

Place `search.py` beside `INDEX.json` and run it using Python 3. Supply `--index PATH` before the subcommand to choose another copy. Matching ignores Unicode combining marks and case but does not change stored text.

```text
python search.py search --kind chapter --limit 12
python search.py search --kind lesson --chapter essential-08 --limit 40
python search.py search "Muslim 2654" --kind package --language de
python search.py search "2654" --kind source --language en
python search.py search --kind reference --surah 82 --mode extended
python search.py search --kind reference --content-kind companion_saying_attributed_not_prophetic
python search.py resolve "source:en:essential-01-003:0:/arabicHadithParents/0" --pointer "/arabicHadithParents/0/reference"
python search.py resolve "package:de:essential-01-003" --pointer "/title"
```

Search supports `--kind`, `--language`, `--chapter`, `--collection`, `--status`, `--content-kind`, `--surah`, `--mode`, and `--limit`. Quran `--surah` and `--mode` filters apply to usage occurrences. A null reader locator means an exact public reader link was not verified; it is not an invitation to invent one.

A source record's locator names a pinned published file and either a JSON pointer within it or a named, hashed JSON member inside a source envelope plus a pointer in that member. On explicit `resolve`, the tool fetches that pinned file from the existing public repository and checks its SHA-256 and length; it also checks the member hash when applicable. The requested value is then displayed for direct inspection. Source conditions and the surrounding context remain in the linked package; the resolver does not create a new translation or grant rights.

The package catalog and readings are pinned to the commits recorded in the index. The separate Arabic Quran citation catalogue is also identified there. [Publication manifest](PUBLICATION-MANIFEST.json) lists this release's exact files and hashes.
