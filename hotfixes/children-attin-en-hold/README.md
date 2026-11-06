# Temporary English children's At-Tin lesson hold

This narrow patch hides the experimental English children's At-Tin explanation and removes its English audio approval until the source mismatch is corrected and reviewed. It preserves the lesson source data and audio archives, every other language, the Qur'an, adult content, and saved data.

`contract.json` pins the exact public snapshot and six output files. Generate the replacements into a new directory:

```sh
python apply.py /path/to/pinned-public-snapshot /path/to/new-output-directory
```

The generator refuses changed source files and writes no content if a pin fails. It does not deploy a website; a site maintainer must verify the current site baseline, apply the generated replacements through the site's release process, and test the English and unaffected languages.
