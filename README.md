# Iman Companion · رفيق الإيمان

I'm building Iman Companion to bring Quran reading, memorization, reflection, and Islamic learning into one app. This repository shares the educational material I've prepared for it so other readers, teachers, and app developers can use it too.

The collection includes tadabbur summaries, Seerah summaries, Hadith reading material, 37 sayings of Ibn al-Qayyim with explanations, and six teaching units for children under five. The project’s own eligible code and editorial work are open source; cited third-party texts retain their stated source terms and credits. You can read the Markdown files here or use the JSON files in your own project.

**The Ibn al-Qayyim sayings collection is complete: 37 readings in each of 20 languages.** Other collections remain at their stated coverage.

**All translated summaries are AI translated — needs verification.** Some have already been through separate model-assisted review, but that does not make them verified human translations. Please check the Arabic source, especially before teaching or publishing a translation.

## Downloads

[Updated offline language packs](https://github.com/blaghtayt-alt/iman-companion/releases/tag/language-packs-2026-10-24-alp-pages-10-19) are available as release downloads. The approved 19-page Alp Arslan excerpt is included in all 15 languages, with the original Arabic and the correct reading direction for each edition. Books and children’s teaching audio are grouped into one ZIP per language. Existing nine-page app builds need the updated app build to expose the new pages; see the [reader update notes](language-packs/metadata/alp-arslan/reader-update.md). The [earlier combined Seerah archive](https://github.com/blaghtayt-alt/iman-companion/releases/tag/language-packs-2026-10-20) contains chapters 1–22 in the original nine languages and chapter 1 in the six newer languages. Current reviewed chapters in Hindi, Russian, Spanish, Persian, German and Simplified Chinese are available directly in the repository. The Arabic archive appendix is labeled separately. See the [combined Seerah notes](materials/seerah/combined/README.md) for sources and coverage.

## Start here

- [Alp Arslan edition metadata](language-packs/metadata/alp-arslan/editions.json) and [delivery notes](language-packs/handoffs/alp-arslan)
- [Seerah chapters and current language coverage](materials/seerah/combined/README.md)
- [Japanese Al-Qiyamah reflections, 75:1–40, with sources](materials/tadabbur/ja/extended/075.md)
- [Arabic Al-A‘la Simplified reflections, 87:1–19, with sources](materials/tadabbur/ar/simplified/087.md)
- [Arabic Al-‘Alaq Simplified reflections, 96:1–19, with sources](materials/tadabbur/ar/simplified/096.md)
- [Arabic An-Naba Simplified reflections, 78:1–40, with sources](materials/tadabbur/ar/simplified/078.md)
- [Arabic Maryam Simplified reflections, 19:1–98, with sources](materials/tadabbur/ar/simplified/019.md)
- Updated Arabic Extended reflections: [Aal Imran](materials/tadabbur/ar/extended/003.md), [Al-Kahf](materials/tadabbur/ar/extended/018.md), [Al-Qasas](materials/tadabbur/ar/extended/028.md), [Ya-Sin](materials/tadabbur/ar/extended/036.md), [At-Taghabun](materials/tadabbur/ar/extended/064.md) and [An-Nazi‘at](materials/tadabbur/ar/extended/079.md).
- [Arabic Essential Iman Hadiths: 286 lessons in 12 chapters](materials/hadith/essential-ar/README.md)
- [Al-Fatiha extended reflections in German, Japanese, Filipino, Hindi, Simplified Chinese and Persian](materials/tadabbur/fatiha-extended/README.md).
- [Essential Iman Hadith 01-002: reviewed reading in all 20 app languages](materials/hadith/essential-01-002/README.md), with source and translation details. Previously published first-lesson source exports remain available in the [Hadith collection](materials/hadith/README.md).
- [Heart Reminder: selected reports and Quran passages in five languages](materials/hadith/heart-reminder/README.md)
- [Historical Hadith reading collection and translations](materials/hadith/README.md)
- [Sayings of Ibn al-Qayyim](materials/ibn-al-qayyim/README.md)
- [Under 5: six Arabic, English, French, Turkish, Indonesian, Malay, Brazilian Portuguese, Urdu, Bengali, Hindi, Russian, Spanish, Persian, German, Simplified Chinese, Uzbek, Thai, Vietnamese, Japanese and Filipino units, 39 lessons each](materials/under-5/README.md)
- [Browse all materials](materials/README.md)
- [Sources and how the summaries were prepared](materials/SOURCES-AND-METHOD.md)
- [Machine-readable catalog](materials/catalog.json)
- [Translation coverage and status](materials/translation-status.json)
- [Reuse terms](materials/REUSE.md)

## What's included

| Collection | Current coverage |
| --- | --- |
| Tadabbur in Arabic | 134 surah-and-mode documents, covering the available Extended and Simplified material |
| Tadabbur translations | 26 surah-and-mode documents in each of eight other languages, plus [Japanese Al-Qiyamah 75:1–40](materials/tadabbur/ja/extended/075.md) and 41 separate work-in-progress translation packages |
| Seerah | Chapters 1–22 in the original nine languages; [current coverage in the six newer languages](materials/seerah/combined/README.md). Arabic summaries of chapters 23–26 remain in the source archive |
| Hadith | [Arabic Essential course: 286 lessons](materials/hadith/essential-ar/README.md), plus the separate historical Arabic reference collection and translations at their stated per-language coverage |
| Ibn al-Qayyim | [Complete: 37 sayings and explanations in each of 20 languages](materials/ibn-al-qayyim/README.md) |
| Under 5 | [Six Arabic, English, French, Turkish, Indonesian, Malay, Brazilian Portuguese, Urdu, Bengali, Hindi, Russian, Spanish, Persian, German, Simplified Chinese, Uzbek, Thai, Vietnamese, Japanese and Filipino units, 39 lessons each](materials/under-5/README.md); audio in preparation |

The Ibn al-Qayyim sayings collection is complete in all 20 app languages. Other collections have different coverage: [the 286-lesson Arabic Essential Hadith course](materials/hadith/essential-ar/README.md) is available as a distinct collection; its first lesson is available in the current local app in English, French, Turkish, Indonesian, Malay, Brazilian Portuguese, Urdu, Bengali, Hindi, Russian, Spanish, Persian, German, Uzbek, Simplified Chinese, Thai, Vietnamese, Japanese and Filipino; its second lesson is installed locally and published in all 20 app languages; other Essential translations have the coverage noted in the collection index. Seerah chapters 1–2 are installed and published in Uzbek, Thai, Vietnamese, Japanese and Filipino; later chapters in those languages remain incomplete. Under 5 text is complete in all 20 app languages; its six audio recordings are in preparation. Coverage differs between collections. This is not a complete translation of every surah, and some Arabic sources contain selected ayahs only. The catalog gives the actual ayah counts and identifies introductions and archived chapters.

## Where the material comes from

The tadabbur collection grew out of Arabic lessons, mainly those of Ahmad Abd al-Mun'im on [إنه القرآن / Its The Quran](https://www.youtube.com/c/itsthequran), together with the additional sources named in individual documents. The Seerah summaries follow [Ahmed al-Sayed (أحمد السيد)](https://www.youtube.com/@alsayyed_ah)'s lecture sequence. The Under 5 units are my teaching materials, written for an adult to use with a young child.

These are prepared summaries and reflections, not official transcripts or publications endorsed by the speakers. Source references and Quran or hadith quotations are kept with the material wherever supplied.

## Using the material

My original editorial contributions and teaching materials are dedicated under [CC0 1.0](materials/LICENSE). You may copy, adapt, share, and use them in personal projects or commercial apps without asking permission. Credit is appreciated, but is not a condition of that dedication.

Quoted material and credited translations from other publishers keep their own rights and terms; CC0 cannot relicense someone else's work. See [Reuse terms](materials/REUSE.md) for the distinction. The repository's existing [MIT license](LICENSE) remains in place for code.

If you find a mistake, please open an issue with the language, file, surah and ayah or chapter, and your suggested correction. A source reference is especially helpful. Translation improvements should keep the Arabic meaning and its qualifications, rather than add a new interpretation.

[Project website](https://blaghtayt-alt.github.io/iman-companion/) · [Privacy policy](https://blaghtayt-alt.github.io/iman-companion/privacy/)

## Articles

- [Prepared Arabic articles 1–20 and their Islamic references](materials/articles/prepared-ar/README.md)
- [Earlier article and its translations](materials/articles/al-fitnah-al-muntazarah/README.md), retained for reference.

## Current Al-Ikhlas reflections

- [112:1–4 in English, French, Turkish, Indonesian, Malay, Brazilian Portuguese, Bengali, Hindi, Urdu, Russian, Spanish, Persian, German, Simplified Chinese, Uzbek, Thai, Vietnamese, Filipino and Japanese, with sources](materials/tadabbur/ikhlas-112/README.md)
