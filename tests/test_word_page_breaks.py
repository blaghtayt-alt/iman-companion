"""Conservative structural fixtures; actual Word A/B proof is separate evidence."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from lxml import etree as E

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "books"))
import normalize_word_page_breaks as repair

W = repair.W


def el(tag, **attrs):
    return E.Element(W + tag, {W + k: v for k, v in attrs.items()})


def paragraph(text="نص عربي tanzil.net", hard_break=False, bidi="1"):
    p = el("p")
    props = el("pPr")
    props.append(el("pStyle", val="Normal"))
    if bidi is not None:
        props.append(el("bidi", val=bidi))
    p.append(props)
    r = el("r")
    rpr = el("rPr")
    rpr.append(el("rFonts", ascii="ExactFont", cs="ExactArabic"))
    rpr.append(el("sz", val="24"))
    r.append(rpr)
    t = el("t")
    t.text = text
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    r.append(t)
    p.append(r)
    if hard_break:
        final_run = el("r")
        final_run.append(el("br", type="page"))
        p.append(final_run)
    return p


def document(*children):
    root = E.Element(W + "document", nsmap={"w": W[1:-1]})
    body = E.SubElement(root, W + "body")
    body.extend(children)
    body.append(el("sectPr"))
    return E.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def body_of(raw):
    return E.fromstring(raw).find(W + "body")


class PageBreakTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def assert_skipped(self, raw, reason, language="ar"):
        result, report = repair.normalize_document_xml(raw, language)
        self.assertEqual(result, raw)
        self.assertEqual(report["movedPageBreaks"], 0)
        self.assertIn(reason, [row["reason"] for row in report["skippedPageBreaks"]])

    def package(self, name="book.docx", xml=None):
        path = self.folder / name
        if xml is None:
            xml = document(paragraph(hard_break=True), paragraph("الفصل التالي"))
        parts = [("word/_rels/document.xml.rels", b'<Relationships><r Id="b"/><r Id="a"/></Relationships>'),
                 ("word/fonts/exact.odttf", bytes(range(256))),
                 ("word/document.xml", xml),
                 ("word/footnotes.xml", b'<footnotes>unchanged exact note bytes</footnotes>'),
                 ("word/styles.xml", b'<styles>exact styles</styles>')]
        with ZipFile(path, "x") as z:
            z.comment = b"keep archive comment"
            for member, raw in parts:
                info = ZipInfo(member, (2020, 1, 2, 3, 4, 6))
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0o100640 << 16
                info.comment = b"keep member comment"
                z.writestr(info, raw)
        return path

    def test_moves_transition_and_preserves_reader_nodes_and_properties(self):
        prior = paragraph("حقوق النص القرآني ©\u00a0\u202a2007–2026\u202c tanzil.net", True)
        prior.insert(1, el("bookmarkStart", id="7", name="source_anchor"))
        prior[-2].append(el("footnoteReference", id="42"))
        prior[-2].append(el("fldChar", fldCharType="end"))
        prior.insert(len(prior) - 1, el("bookmarkEnd", id="7"))
        following = paragraph("الفصل التالي")
        ppr = following.find(W + "pPr")
        ppr.insert(1, el("keepNext"))
        ppr.insert(2, el("keepLines"))
        ppr.append(el("spacing", before="80", after="120"))
        original = document(prior, following)
        output, report = repair.normalize_document_xml(original, "ar")
        actual = body_of(output)
        self.assertEqual(report["movedPageBreaks"], 1)
        self.assertEqual(list(E.fromstring(original).itertext()), list(E.fromstring(output).itertext()))
        expected_prior = deepcopy(prior)
        expected_prior[-1].remove(expected_prior[-1][-1])
        self.assertEqual(E.tostring(actual[0]), E.tostring(expected_prior))
        props = actual[1].find(W + "pPr")
        self.assertEqual(props.find(W + "pageBreakBefore").get(W + "val"), "1")
        self.assertEqual([E.QName(n).localname for n in props],
                         ["pStyle", "keepNext", "keepLines", "pageBreakBefore", "bidi", "spacing"])
        props.remove(props.find(W + "pageBreakBefore"))
        self.assertEqual(E.tostring(actual[1]), E.tostring(following))

    def test_terminal_break_in_text_run_keeps_all_run_content(self):
        prior = paragraph()
        prior[-1].append(el("br", type="page"))
        raw = document(prior, paragraph("next"))
        output, report = repair.normalize_document_xml(raw, "ur")
        self.assertEqual(report["movedPageBreaks"], 1)
        self.assertEqual(E.tostring(body_of(output)[0]),
                         E.tostring(body_of(document(paragraph()))[0]))

    def test_no_next_properties_are_created_without_reordering_text(self):
        following = paragraph("next")
        following.remove(following[0])
        output, report = repair.normalize_document_xml(document(paragraph(hard_break=True), following), "fa")
        self.assertEqual(report["movedPageBreaks"], 1)
        p = body_of(output)[1]
        self.assertEqual(p[0].tag, W + "pPr")
        p.remove(p[0])
        self.assertEqual(E.tostring(p), E.tostring(following))

    def test_adjacent_eligible_transitions_and_second_pass_are_stable(self):
        raw = document(paragraph("one", True), paragraph("two", True), paragraph("three"))
        output, report = repair.normalize_document_xml(raw, "ar")
        self.assertEqual(report["movedPageBreaks"], 2)
        again, second = repair.normalize_document_xml(output, "ar")
        self.assertEqual(again, output)
        self.assertEqual(second["movedPageBreaks"], 0)

    def test_multiple_hard_breaks_are_not_collapsed(self):
        prior = paragraph(hard_break=True)
        prior[-1].insert(0, el("br", type="page"))
        self.assert_skipped(document(prior, paragraph()), "multiple-hard-page-breaks")

    def test_line_break_is_retained_and_is_not_a_page_break(self):
        prior = paragraph()
        prior[-1].append(el("br"))
        raw = document(prior, paragraph())
        self.assertEqual(repair.normalize_document_xml(raw, "ar")[0], raw)
        prior[-1].append(el("br", type="page"))
        output, report = repair.normalize_document_xml(document(prior, paragraph()), "ar")
        self.assertEqual(report["movedPageBreaks"], 1)
        breaks = list(body_of(output)[0].iter(W + "br"))
        self.assertEqual(len(breaks), 1)
        self.assertIsNone(breaks[0].get(W + "type"))

    def test_existing_false_break_before_is_set_true(self):
        for value in ("0", "false", "off"):
            with self.subTest(value=value):
                following = paragraph()
                following[0].insert(1, el("pageBreakBefore", val=value))
                output, report = repair.normalize_document_xml(document(paragraph(hard_break=True), following), "ar")
                self.assertEqual(report["movedPageBreaks"], 1)
                self.assertEqual(body_of(output)[1][0].find(W + "pageBreakBefore").get(W + "val"), "1")

    def test_existing_true_break_before_preserves_possible_two_transitions(self):
        for value in (None, "1", "true", "on"):
            with self.subTest(value=value):
                following = paragraph()
                following[0].insert(1, el("pageBreakBefore", **({"val": value} if value is not None else {})))
                self.assert_skipped(document(paragraph(hard_break=True), following),
                                    "next-page-break-before-already-true")

    def test_suffix_after_break_is_never_dropped(self):
        for suffix in ("visible", "", " "):
            with self.subTest(suffix=suffix):
                prior = paragraph(hard_break=True)
                t = el("t")
                t.text = suffix
                prior[-1].append(t)
                self.assert_skipped(document(prior, paragraph()), "nonterminal-or-ambiguous-page-break")
        prior = paragraph(hard_break=True)
        prior.append(el("r"))
        self.assert_skipped(document(prior, paragraph()), "nonterminal-or-ambiguous-page-break")

    def test_break_inside_hyperlink_or_with_child_content_is_not_moved(self):
        prior = paragraph(hard_break=True)
        trailing = prior[-1]
        prior.remove(trailing)
        link = el("hyperlink", anchor="a")
        link.append(trailing)
        prior.append(link)
        self.assert_skipped(document(prior, paragraph()), "nonterminal-or-ambiguous-page-break")
        prior = paragraph(hard_break=True)
        prior[-1][-1].append(el("t"))
        self.assert_skipped(document(prior, paragraph()), "nonterminal-or-ambiguous-page-break")

    def test_nonparagraph_siblings_and_body_markers_are_boundaries(self):
        for next_node in (el("tbl"), el("bookmarkStart", id="9", name="anchor"),
                          el("bookmarkEnd", id="9"), el("commentRangeEnd", id="9"), el("sectPr")):
            with self.subTest(tag=next_node.tag):
                self.assert_skipped(document(paragraph(hard_break=True), next_node, paragraph()),
                                    "next-body-sibling-is-not-a-paragraph")

    def test_section_properties_in_either_paragraph_are_boundaries(self):
        for which in (0, 1):
            with self.subTest(which=which):
                ps = [paragraph(hard_break=True), paragraph()]
                ps[which][0].append(el("sectPr"))
                self.assert_skipped(document(*ps), "section-boundary")

    def test_table_cell_paragraph_is_never_normalized(self):
        table = el("tbl")
        cell = E.SubElement(E.SubElement(table, W + "tr"), W + "tc")
        cell.extend([paragraph(hard_break=True), paragraph()])
        raw = document(table)
        self.assertEqual(repair.normalize_document_xml(raw, "ar")[0], raw)

    def test_scope_empty_text_and_direction_are_conservative(self):
        raw = document(paragraph(hard_break=True), paragraph())
        self.assertEqual(repair.normalize_document_xml(raw, "en")[0], raw)
        self.assert_skipped(document(paragraph(" \t", True), paragraph()), "empty-paragraph")
        for direction in (None, "0", "false", "off", "invalid"):
            with self.subTest(direction=direction):
                self.assert_skipped(document(paragraph(hard_break=True, bidi=direction), paragraph()),
                                    "paragraph-not-explicitly-rtl")

    def test_ambiguous_properties_are_not_repaired(self):
        following = paragraph()
        following[0].extend([el("pageBreakBefore", val="0"), el("pageBreakBefore", val="0")])
        self.assert_skipped(document(paragraph(hard_break=True), following), "ambiguous-next-page-break-before")
        for value in ("invalid", "2"):
            following = paragraph()
            following[0].append(el("pageBreakBefore", val=value))
            self.assert_skipped(document(paragraph(hard_break=True), following), "ambiguous-next-page-break-before")
        following = paragraph()
        following.append(el("pPr"))
        self.assert_skipped(document(paragraph(hard_break=True), following), "ambiguous-paragraph-properties")

    def test_package_payloads_member_order_and_metadata_are_preserved(self):
        path = self.package()
        with ZipFile(path) as z:
            names, comment = z.namelist(), z.comment
            parts = {n: z.read(n) for n in names}
            metadata = [(i.date_time, i.external_attr, i.comment, i.compress_type) for i in z.infolist()]
        report = repair.normalize(path, "ar")
        self.assertEqual(report["movedPageBreaks"], 1)
        with ZipFile(path) as z:
            self.assertEqual(z.namelist(), names)
            self.assertEqual(z.comment, comment)
            self.assertEqual([(i.date_time, i.external_attr, i.comment, i.compress_type) for i in z.infolist()], metadata)
            for name in names:
                if name != "word/document.xml":
                    self.assertEqual(z.read(name), parts[name])
            self.assertNotEqual(z.read("word/document.xml"), parts["word/document.xml"])
        first = path.read_bytes()
        self.assertEqual(repair.normalize(path, "ar")["movedPageBreaks"], 0)
        self.assertEqual(path.read_bytes(), first)

    def test_duplicate_package_members_fail_without_replacing_original(self):
        path = self.package()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with ZipFile(path, "a") as z:
                z.writestr("word/document.xml", b"duplicate")
        original = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            repair.normalize(path, "ar")
        self.assertEqual(path.read_bytes(), original)

    def test_concurrent_source_change_is_preserved_and_temporary_removed(self):
        path = self.package()
        original_function = repair.normalize_document_xml
        def concurrent_change(raw, language):
            result = original_function(raw, language)
            path.write_bytes(b"newer foreign content")
            return result
        with patch.object(repair, "normalize_document_xml", side_effect=concurrent_change):
            with self.assertRaisesRegex(ValueError, "changed during"):
                repair.normalize(path, "ar")
        self.assertEqual(path.read_bytes(), b"newer foreign content")
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), [path.name])

    def test_folder_index_validates_all_paths_before_mutation(self):
        path = self.package()
        original = path.read_bytes()
        for name in ("../escape.docx", "sub/book.docx", "sub\\book.docx", "C:escape.docx"):
            with self.subTest(name=name):
                (self.folder / "index.json").write_text(json.dumps({"books": [
                    {"file": path.name, "language": "ar"}, {"file": name, "language": "ar"}]}))
                with self.assertRaises(ValueError):
                    repair.normalize_folder(self.folder)
                self.assertEqual(path.read_bytes(), original)

    def test_folder_index_normalizes_rtl_and_leaves_ltr_byte_exact(self):
        rtl, ltr = self.package("rtl.docx"), self.package("ltr.docx")
        original_ltr = ltr.read_bytes()
        (self.folder / "index.json").write_text(json.dumps({"books": [
            {"file": rtl.name, "language": "ar"}, {"file": ltr.name, "language": "en"}]}))
        report = repair.normalize_folder(self.folder)
        self.assertEqual(report["normalizedBooks"], 1)
        self.assertEqual(report["movedPageBreaks"], 1)
        self.assertEqual(ltr.read_bytes(), original_ltr)

    def test_xml_dtd_and_missing_body_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "DTD"):
            repair.normalize_document_xml(b'<!DOCTYPE w:document [<!ENTITY x "bad">]>' +
                document(paragraph()).split(b"?>", 1)[1], "ar")
        with self.assertRaisesRegex(ValueError, "body"):
            repair.normalize_document_xml(E.tostring(E.Element(W + "document")), "ar")


if __name__ == "__main__":
    unittest.main()
