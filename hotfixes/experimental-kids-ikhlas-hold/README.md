# Children’s Al-Ikhlas lesson hold

This scoped hotfix removes one unqualified experimental children’s lesson from the lesson list and removes its eight legacy audio-approval records. It preserves the remaining lessons, Quran and adult reflection content, language packs, and saved data. It contains no lesson text or audio.

`contract.json` pins the public runtime baseline and the exact before and after hashes for five files. To generate the replacements into a new directory, run:

```sh
python apply.py /path/to/approved-runtime /path/to/new-output-directory
```

The generator reads the source snapshot without changing it, rejects any file that does not match the pinned input, checks the scope and output hashes, and writes only the five replacement files. It does not deploy the website, alter published archives, or change device caches. A site maintainer must verify the live baseline and use the site’s release process to apply and validate the result.
