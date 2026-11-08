"""Keep terminal RTL page breaks out of the preceding text line.

LibreOffice can serialize a chapter's pageBreakBefore as an inline hard page
break at the end of the preceding paragraph. Word 16 in compatibility mode 12
can then overprint that RTL paragraph's last line. This preparation-only pass
restores the transition to the immediately following paragraph without editing
reader text, font runs, fields, anchors, notes, or other package members.

Run after the last LibreOffice save and before checks/prepared handoff creation.
The Word finalizer and its exact candidate-delta gate remain unchanged.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
from zipfile import ZipFile

from lxml import etree

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
RTL_LANGUAGES = frozenset({"ar", "ur", "fa"})
TRUE_VALUES = frozenset({"1", "true", "on"})
FALSE_VALUES = frozenset({"0", "false", "off"})


def _on_off(node):
    value = node.get(W + "val", "1")
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    return None


def _properties(paragraph):
    nodes = paragraph.findall(W + "pPr")
    if len(nodes) > 1 or (nodes and paragraph[0] is not nodes[0]):
        raise ValueError("ambiguous-paragraph-properties")
    return nodes[0] if nodes else None


def normalize_document_xml(raw, language):
    """Return (XML bytes, report); unchanged documents retain their exact bytes.

    Only an explicit RTL paragraph in an RTL book is eligible. A single hard
    page break must be the final element of its final direct run. Body-level
    markers, tables, section boundaries, multiple hard breaks, and any suffix
    after the break are left alone and reported instead of being guessed at.
    """
    report = {"language": language, "movedPageBreaks": 0,
              "skippedPageBreaks": [], "documentChanged": False}
    if language not in RTL_LANGUAGES:
        report["scopeSkipped"] = "not-an-rtl-language"
        return raw, report
    parser = etree.XMLParser(resolve_entities=False, no_network=True,
                             remove_blank_text=False, strip_cdata=False)
    root = etree.fromstring(raw, parser)
    if root.getroottree().docinfo.doctype:
        raise ValueError("Document XML must not contain a DTD")
    if root.tag != W + "document":
        raise ValueError("Not a Word document XML part")
    bodies = root.findall(W + "body")
    if len(bodies) != 1:
        raise ValueError("Missing or ambiguous Word document body")
    body = bodies[0]
    original = deepcopy(root)
    jobs = []

    def skip(index, reason):
        report["skippedPageBreaks"].append(
            {"bodyChildIndex0": index, "reason": reason})

    for index, paragraph in enumerate(body):
        if paragraph.tag != W + "p":
            continue
        hard_breaks = [n for n in paragraph.iter(W + "br")
                       if n.get(W + "type") == "page"]
        if not hard_breaks:
            continue
        if len(hard_breaks) != 1:
            skip(index, "multiple-hard-page-breaks")
            continue
        if not any((n.text or "").strip() for n in paragraph.iter(W + "t")):
            skip(index, "empty-paragraph")
            continue
        try:
            ppr = _properties(paragraph)
        except ValueError as error:
            skip(index, str(error))
            continue
        bidi = ppr.findall(W + "bidi") if ppr is not None else []
        if len(bidi) != 1 or _on_off(bidi[0]) is not True:
            skip(index, "paragraph-not-explicitly-rtl")
            continue
        br = hard_breaks[0]
        run = br.getparent()
        if (not len(paragraph) or paragraph[-1] is not run
                or run.tag != W + "r" or run[-1] is not br
                or set(br.attrib) != {W + "type"}
                or len(br) or (br.text or "").strip() or (br.tail or "").strip()):
            skip(index, "nonterminal-or-ambiguous-page-break")
            continue
        if index + 1 >= len(body) or body[index + 1].tag != W + "p":
            skip(index, "next-body-sibling-is-not-a-paragraph")
            continue
        following = body[index + 1]
        if (paragraph.find(".//" + W + "sectPr") is not None
                or following.find(".//" + W + "sectPr") is not None):
            skip(index, "section-boundary")
            continue
        try:
            next_ppr = _properties(following)
        except ValueError as error:
            skip(index, str(error))
            continue
        existing = next_ppr.findall(W + "pageBreakBefore") if next_ppr is not None else []
        if (len(existing) > 1 or (existing and
                (set(existing[0].attrib) - {W + "val"}
                 or _on_off(existing[0]) is None or len(existing[0])))):
            skip(index, "ambiguous-next-page-break-before")
            continue
        if existing and _on_off(existing[0]) is True:
            # Do not coalesce two possible intentional page transitions.
            skip(index, "next-page-break-before-already-true")
            continue
        jobs.append({"index": index, "paragraph": paragraph, "run": run,
                     "break": br, "originalBreak": deepcopy(br),
                     "following": following,
                     "originalNextProperties": deepcopy(next_ppr)})

    if not jobs:
        return raw, report

    for job in jobs:
        job["run"].remove(job["break"])
        following = job["following"]
        ppr = following.find(W + "pPr")
        if ppr is None:
            ppr = etree.Element(W + "pPr")
            following.insert(0, ppr)
        before = ppr.find(W + "pageBreakBefore")
        if before is None:
            before = etree.Element(W + "pageBreakBefore")
            # Preserve the order of every existing property. These three
            # properties precede pageBreakBefore in the OOXML schema.
            insert_at = 0
            for position, child in enumerate(ppr):
                if child.tag in {W + "pStyle", W + "keepNext", W + "keepLines"}:
                    insert_at = position + 1
            ppr.insert(insert_at, before)
            before.set(W + "val", "1")
        elif _on_off(before) is False:
            before.set(W + "val", "1")

    # Reversing exactly the planned break/property changes must recover the
    # entire XML tree. This covers text, fields, footnotes, bookmarks, ordering,
    # run/font properties, and all unrecognized nodes, not just visible text.
    restored = deepcopy(root)
    restored_body = restored.find(W + "body")
    for job in jobs:
        prior = restored_body[job["index"]]
        prior[-1].append(deepcopy(job["originalBreak"]))
        following = restored_body[job["index"] + 1]
        current = following.find(W + "pPr")
        if job["originalNextProperties"] is None:
            following.remove(current)
        else:
            following.replace(current, deepcopy(job["originalNextProperties"]))
    if etree.tostring(restored) != etree.tostring(original):
        raise ValueError("Unexpected XML change while normalizing page breaks")
    report["movedPageBreaks"] = len(jobs)
    report["movedFromBodyChildIndices0"] = [job["index"] for job in jobs]
    report["documentChanged"] = True
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8",
                          standalone=True), report


def normalize(file, language):
    """Atomically normalize one prepared DOCX; preserve all other ZIP members."""
    file = Path(file)
    original = file.read_bytes()
    with ZipFile(BytesIO(original)) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate DOCX package members")
        parts = {name: archive.read(name) for name in names}
        comment = archive.comment
    if "word/document.xml" not in parts:
        raise ValueError("Missing Word document XML part")
    repaired, report = normalize_document_xml(parts["word/document.xml"], language)
    report["file"] = file.name
    if not report["documentChanged"]:
        return report
    descriptor, pending = tempfile.mkstemp(prefix=".word-page-break-", suffix=".docx",
                                         dir=file.parent)
    try:
        with os.fdopen(descriptor, "w+b") as stream:
            with ZipFile(stream, "w") as archive:
                archive.comment = comment
                for info in infos:
                    data = repaired if info.filename == "word/document.xml" else parts[info.filename]
                    archive.writestr(deepcopy(info), data)
        with ZipFile(pending) as archive:
            if archive.namelist() != names or archive.comment != comment:
                raise ValueError("DOCX package member order changed")
            for name in names:
                expected = repaired if name == "word/document.xml" else parts[name]
                if archive.read(name) != expected:
                    raise ValueError("Unexpected DOCX package member change")
        if file.read_bytes() != original:
            raise ValueError("DOCX changed during page-break normalization")
        os.chmod(pending, file.stat().st_mode & 0o777)
        os.replace(pending, file)
    finally:
        if os.path.exists(pending):
            os.unlink(pending)
    return report


def normalize_folder(folder):
    folder = Path(folder).resolve()
    index = json.loads((folder / "index.json").read_text(encoding="utf-8-sig"))
    if not isinstance(index, dict) or not isinstance(index.get("books"), list):
        raise ValueError("Invalid book index")
    planned = []
    seen = set()
    # Validate every indexed path before the first mutation.
    for book in index["books"]:
        if not isinstance(book, dict) or not isinstance(book.get("file"), str):
            raise ValueError("Invalid indexed book")
        name, language = book["file"], book.get("language")
        if (not name or "/" in name or "\\" in name or ":" in name
                or Path(name).suffix.lower() != ".docx"
                or not isinstance(language, str) or not language):
            raise ValueError("Invalid indexed book path or language")
        file = folder / name
        if file.is_symlink() or file.resolve().parent != folder or not file.is_file():
            raise ValueError("Invalid indexed book path")
        if file.resolve() in seen:
            raise ValueError("Duplicate indexed book")
        seen.add(file.resolve())
        planned.append((file, language))
    reports = [normalize(file, language) for file, language in planned]
    return {"normalizedBooks": sum(bool(r["documentChanged"]) for r in reports),
            "movedPageBreaks": sum(r["movedPageBreaks"] for r in reports),
            "books": reports}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(normalize_folder(args.folder), ensure_ascii=False))


if __name__ == "__main__":
    main()
