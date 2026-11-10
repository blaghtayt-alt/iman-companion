"""Adversarial lifecycle fixtures, never real Word evidence or release approvals.

The external renderer/indexer are isolated. Exact hashes, source snapshots,
package comparisons, Word receipt parsing, proof page counts and publication
handoff run for real against synthetic files confined to TemporaryDirectory.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED
import copy
import json
import shutil
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'books'))
import finalize_prepared as finish
import automatic_publication as publication
from preparation_queue import record
from published_library import read, sha
from word_layout_check import verify as verify_word
from pypdf import PdfWriter
from pypdf.generic import (ArrayObject, DecodedStreamObject, DictionaryObject,
                           NameObject, NumberObject, TextStringObject)


class FinalizePreparedTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'repo'
        self.prepared = Path(self.temp.name) / 'prepared'
        self.candidate = Path(self.temp.name) / 'candidate'
        self.out = Path(self.temp.name) / 'out'
        self.prepared.mkdir()
        self.source_commit, self.commit = 'a' * 40, 'b' * 40
        self.repo, self.tag = 'example/fixture', 'books-fixture-1'
        self.docx = 'Iman_Companion_en_articles.docx'
        self.pdf = 'Iman_Companion_en_articles.pdf'
        self.handoff = Path(self.temp.name) / 'handoff.json'
        self.acceptance = Path(self.temp.name) / 'visual-acceptance.json'
        self.after_checks = None
        self.changed_manifest = None
        self.commands = []
        environment = patch.dict('os.environ', {'GITHUB_RUN_ID': '', 'GITHUB_RUN_ATTEMPT': '', 'GITHUB_REPOSITORY': ''})
        environment.start()
        self.addCleanup(environment.stop)
        self.write(self.root / 'books/config.json', {'languages': {'en': {'font': 'Latin'}},
                                                    'fonts': {'FiqhSymbols': {'family': 'Synthetic Fiqh Symbols'}}})
        self.declarations = {'schema': 'iman-reviewed-books-v1', 'books': [
            {'language': 'en', 'collection': 'articles', 'state': 'reviewed-current',
             'automaticBuild': True, 'automaticRelease': True, 'requireActualWordLayout': True,
             'requireFinalVisualAcceptance': True}]}
        self.write(self.root / 'books/reviewed-books.json', self.declarations)
        self.write(self.root / 'materials/article.json', {'text': 'Fixture reader text.'})
        self.write(self.root / 'materials/catalog.json', {'entries': [
            {'collection': 'articles', 'language': 'en', 'id': 'article-1',
             'status': 'published', 'json': 'materials/article.json'}]})
        (self.root / 'books/render_fixture.py').write_text('# fixture rendering code\n')
        unit = {'id': 'article-1', 'readerTextSHA256': sha(b'Fixture reader text.'),
                'sourceHashes': [sha((self.root / 'materials/article.json').read_bytes())],
                'inputBindings': [{'path': 'materials/article.json',
                                   'sha256': sha((self.root / 'materials/article.json').read_bytes())}]}
        self.write(self.root / 'books/units/en.json', unit)
        self.manifest = {'schema': 'iman-book-manifest-v1', 'sourceCommit': self.source_commit,
                         'previewOnly': False, 'scope': {'language': 'en', 'collection': 'articles'},
                         'catalogSHA256': 'c' * 64, 'reviewedBooksSHA256': 'd' * 64,
                         'units': [{'language': 'en', 'collection': 'articles', 'id': unit['id'],
                                    'path': 'books/units/en.json',
                                    'sha256': sha((self.root / 'books/units/en.json').read_bytes())}]}
        self.write(self.root / 'books/manifest.json', self.manifest)
        self.make_docx(self.prepared / self.docx, 2)
        self.make_pdf(self.prepared / self.pdf, 3)
        self.write(self.prepared / (self.docx + '.reader-checks.json'),
                   {'body': ['Fixture reader text.'], 'footnotes': ['Fixture source.']})
        self.write(self.prepared / 'source-manifest.json', self.manifest)
        self.index = {'sourceCommit': self.source_commit, 'previewOnly': False, 'books': [
            {'language': 'en', 'collection': 'articles', 'file': self.docx,
             'sourceCommit': self.source_commit, 'units': [{k: unit[k] for k in ('id', 'readerTextSHA256', 'sourceHashes')}],
             'sha256': sha((self.prepared / self.docx).read_bytes()),
             'pdfSha256': sha((self.prepared / self.pdf).read_bytes()),
             'preparationVerified': True, 'exportVerified': False, 'previewOnly': False}]}
        self.queue()
        shutil.copytree(self.prepared, self.candidate)
        self.make_docx(self.candidate / self.docx, 3)
        self.make_pdf(self.candidate / finish.PROOF, 3)
        self.word_receipt()
        self.handoff_and_acceptance()

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        finish.write_json(path, value)

    def make_pdf(self, path, pages):
        path.parent.mkdir(parents=True, exist_ok=True)
        writer = PdfWriter()
        for _ in range(pages):
            writer.add_blank_page(width=432, height=648)
        # A genuine synthetic PDF link and painted label exercise the existing
        # independent PDF/Word contents verifier at the publication boundary.
        annotation = DictionaryObject({NameObject('/Subtype'): NameObject('/Link'),
            NameObject('/Rect'): ArrayObject([NumberObject(n) for n in (10, 497, 315, 512)]),
            NameObject('/Dest'): ArrayObject([writer.pages[1].indirect_reference, NameObject('/Fit')]),
            NameObject('/Contents'): TextStringObject('SYNTHETIC CHAPTER\t2')})
        writer.pages[0][NameObject('/Annots')] = ArrayObject([writer._add_object(annotation)])
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica')})
        writer.pages[0][NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):
            DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(b'BT /F1 10 Tf 300 500 Td (2) Tj ET')
        writer.pages[0][NameObject('/Contents')] = writer._add_object(stream)
        with path.open('wb') as stream:
            writer.write(stream)

    def make_docx(self, path, page, text='Fixture reader text.'):
        xml = f'''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:p><w:pPr><w:pStyle w:val="TOC1"/></w:pPr><w:hyperlink w:anchor="lesson1"><w:r><w:t>Fixture chapter</w:t></w:r><w:r><w:tab/></w:r><w:r><w:t>{page}</w:t></w:r></w:hyperlink></w:p>
<w:p><w:bookmarkStart w:name="lesson1" w:id="1"/><w:r><w:t>{text}</w:t></w:r></w:p>
</w:body></w:document>'''
        with ZipFile(path, 'w', ZIP_DEFLATED) as archive:
            archive.writestr('word/document.xml', xml.encode())
            archive.writestr('word/styles.xml', b'<fixture-styles/>')
            archive.writestr('word/footnotes.xml', b'<fixture-footnotes>Fixture source.</fixture-footnotes>')
            archive.writestr('word/media/qr.bin', b'fixture-QR-bytes')

    def word_receipt(self, application='Microsoft Word', digest=None):
        self.receipt = {'schema': 'iman-word-layout-readback-v1',
                        'scope': 'SYNTHETIC TEST FIXTURE, NOT ACTUAL WORD EVIDENCE', 'language': 'en',
                        'docxSHA256': digest or sha((self.candidate / self.docx).read_bytes()),
                        'engine': {'application': application, 'version': 'fixture', 'build': 'fixture'},
                        'readOnly': True, 'savedByWord': False, 'pages': 3,
                        'contents': [{'anchor': 'lesson1', 'cachedPage': 3, 'actualPage': 3, 'physicalPage': 3}]}
        self.write(self.candidate / (self.docx + '.word-layout.json'), self.receipt)

    def queue(self, checks=None):
        self.write(self.prepared / 'index.json', self.index)
        row = record(self.root, self.index, self.prepared, self.source_commit, checks or [
            {'check': 'actual-word-layout'}, {'check': 'final-visual-inspection'}])
        self.write(self.root / 'books/prepared-library.json', {'schema': 'iman-book-preparation-queue-v1', 'entries': [row]})

    def handoff_and_acceptance(self):
        handoff = finish.plan(self.root, self.prepared)
        self.write(self.handoff, handoff)
        acceptance = finish.acceptance_template(handoff, self.candidate)
        acceptance.update(accepted=True, allPdfPagesInspected=True, allWordPagesInspected=True,
                          reviewer='SYNTHETIC FIXTURE ONLY', reviewedAt='2025-01-01T00:00:00+00:00')
        self.write(self.acceptance, acceptance)

    def external(self, args, root):
        args = list(map(str, args))
        self.commands.append(args)
        if args[1] == 'books/index_units.py':
            self.assertEqual(args[args.index('--commit') + 1], self.source_commit)
            self.write(self.root / 'books/manifest.json', self.changed_manifest or self.manifest)
        elif args[1] == 'books/check_outputs.py':
            folder = Path(args[args.index('--folder') + 1])
            index = read(folder / 'index.json')
            book = index['books'][0]
            book.update(exportVerified=True, sha256=sha((folder / self.docx).read_bytes()),
                        pdfSha256=sha((folder / self.pdf).read_bytes()), pages=3,
                        wordContentsVerification=verify_word(folder / self.docx, folder / (self.docx + '.word-layout.json')),
                        pdfContentsVerification={'matchedEntries': 1, 'visibleLabelsMatched': 1})
            self.write(folder / 'index.json', index)
            if self.after_checks:
                self.after_checks(folder)
        else:
            self.fail('Unexpected external command: ' + repr(args))
        return ''

    def finalize(self):
        with patch.object(finish, 'git_head', return_value=self.commit), patch.object(finish, 'execute', side_effect=self.external):
            return finish.finalize(self.root, self.prepared, self.candidate, self.handoff,
                                   self.acceptance, self.out, self.commit, self.repo, self.tag)

    def assert_not_staged(self):
        self.assertFalse((self.out / 'en-articles-finalized').exists())
        if (self.out / 'build-report.json').exists():
            self.assertEqual(read(self.out / 'build-report.json')['built'], [])

    def test_final_word_cache_can_change_and_existing_publisher_consumes_result(self):
        before_queue = (self.root / 'books/prepared-library.json').read_bytes()
        before_original = (self.prepared / self.docx).read_bytes()
        result = self.finalize()
        self.assertNotEqual(result['preparedDocxSHA256'], result['docxSHA256'])
        self.assertEqual(result['sourceCommit'], self.source_commit)
        self.assertEqual(result['publicationCommit'], self.commit)
        self.assertEqual((self.root / 'books/prepared-library.json').read_bytes(), before_queue)
        self.assertEqual((self.prepared / self.docx).read_bytes(), before_original)
        entries, assets = publication.candidates(self.root, self.out, self.tag)
        self.assertEqual(len(entries), 1)
        self.assertEqual({p.suffix for p in assets}, {'.docx', '.pdf'})
        self.assertEqual(entries[0]['book']['sha256'], result['docxSHA256'])
        self.assertEqual(entries[0]['book']['wordContentsVerification']['matchedEntries'], 1)
        evidence = finish.verify_final_visual_acceptance(self.out / result['folder'], entries[0]['book'])
        self.assertEqual(evidence['acceptanceSHA256'], result['visualAcceptanceSHA256'])
        self.assertEqual(evidence['wordProofSHA256'], result['wordProofSHA256'])

    def test_template_never_grants_visual_acceptance(self):
        template = finish.acceptance_template(read(self.handoff), self.candidate)
        self.assertFalse(template['accepted'])
        self.assertFalse(template['allPdfPagesInspected'])
        self.assertFalse(template['allWordPagesInspected'])
        self.write(self.acceptance, template)
        with self.assertRaisesRegex(ValueError, 'Explicit visual acceptance'):
            self.finalize()
        self.assert_not_staged()

    def test_review_evidence_rejects_duplicate_json_fields(self):
        original = self.acceptance.read_text()
        self.acceptance.write_text(original[:-2] + ', "accepted": true}\n')
        with self.assertRaisesRegex(ValueError, 'Duplicate field in review evidence'):
            self.finalize()

    def test_source_changes_invalidate_preparation(self):
        self.write(self.root / 'materials/article.json', {'text': 'Changed source.'})
        with self.assertRaisesRegex(ValueError, 'inputs changed'):
            self.finalize()
        self.assert_not_staged()

    def test_rendering_code_change_invalidates_preparation(self):
        (self.root / 'books/render_fixture.py').write_text('# different renderer\n')
        with self.assertRaisesRegex(ValueError, 'inputs changed'):
            self.finalize()

    def test_prepared_pair_hash_cannot_be_replaced(self):
        self.make_docx(self.prepared / self.docx, 2, 'Different preparation.')
        with self.assertRaisesRegex(ValueError, 'Original prepared pair changed'):
            self.finalize()

    def test_handoff_cannot_be_modified(self):
        data = read(self.handoff)
        data['sourceCommit'] = 'f' * 40
        self.write(self.handoff, data)
        with self.assertRaisesRegex(ValueError, 'Handoff changed'):
            self.finalize()

    def test_final_pdf_change_after_review_is_rejected(self):
        self.make_pdf(self.candidate / self.pdf, 4)
        with self.assertRaisesRegex(ValueError, 'pdfSHA256'):
            self.finalize()
        self.assert_not_staged()

    def test_source_hold_is_not_cleared_by_candidate_metadata(self):
        self.index['books'][0]['referenceReadiness'] = {
            'units': 1, 'auditedUnits': 1, 'unboundQuranSegments': 1, 'unboundHadithSegments': 0}
        self.queue([{'check': 'source-references'}])
        candidate_index = copy.deepcopy(self.index)
        candidate_index['books'][0]['referenceReadiness']['unboundQuranSegments'] = 0
        self.write(self.candidate / 'index.json', candidate_index)
        self.handoff_and_acceptance()
        with self.assertRaisesRegex(ValueError, 'source citations are incomplete'):
            self.finalize()
        self.assertEqual(self.commands, [])

    def test_release_hold_requires_existing_scope_authorization(self):
        self.declarations['books'][0]['automaticRelease'] = False
        self.write(self.root / 'books/reviewed-books.json', self.declarations)
        self.queue([{'check': 'scope-release-hold'}])
        self.handoff_and_acceptance()
        with self.assertRaisesRegex(ValueError, 'Scope release hold remains'):
            self.finalize()
        self.assertFalse(read(self.root / 'books/reviewed-books.json')['books'][0]['automaticRelease'])

    def test_unknown_pending_check_is_not_ignored(self):
        self.queue([{'check': 'new-project-hold'}])
        self.handoff_and_acceptance()
        with self.assertRaisesRegex(ValueError, 'Unresolved preparation checks'):
            self.finalize()

    def test_non_word_renderer_cannot_supply_word_receipt(self):
        self.word_receipt(application='LibreOffice')
        self.handoff_and_acceptance()
        with self.assertRaisesRegex(ValueError, 'actual read-only Word'):
            self.finalize()

    def test_word_receipt_must_match_final_docx(self):
        self.word_receipt(digest='0' * 64)
        self.handoff_and_acceptance()
        with self.assertRaisesRegex(ValueError, 'exact final file'):
            self.finalize()

    def test_word_proof_page_count_must_match_readback(self):
        self.make_pdf(self.candidate / finish.PROOF, 4)
        self.handoff_and_acceptance()
        with self.assertRaisesRegex(ValueError, 'proof page count'):
            self.finalize()

    def test_acceptance_and_receipt_cannot_authorize_reader_rewriting(self):
        self.make_docx(self.candidate / self.docx, 3, 'Injected text.')
        self.word_receipt()
        self.handoff_and_acceptance()
        with self.assertRaisesRegex(ValueError, 'outside permitted pagination'):
            self.finalize()
        self.assert_not_staged()

    def test_added_package_part_is_rejected(self):
        with ZipFile(self.candidate / self.docx, 'a') as archive:
            archive.writestr('word/extra.xml', b'<extra/>')
        self.word_receipt()
        self.handoff_and_acceptance()
        with self.assertRaisesRegex(ValueError, 'package membership changed'):
            self.finalize()

    def test_footnotes_fonts_and_qr_bytes_cannot_change_under_layout_approval(self):
        for name in ('word/footnotes.xml', 'word/styles.xml', 'word/media/qr.bin'):
            with self.subTest(part=name):
                self.make_docx(self.candidate / self.docx, 3)
                with ZipFile(self.candidate / self.docx) as archive:
                    parts = {n: archive.read(n) for n in archive.namelist()}
                parts[name] = b'changed content'
                with ZipFile(self.candidate / self.docx, 'w', ZIP_DEFLATED) as archive:
                    for part, raw in parts.items():
                        archive.writestr(part, raw)
                self.word_receipt()
                self.handoff_and_acceptance()
                with self.assertRaisesRegex(ValueError, 'outside permitted pagination'):
                    self.finalize()
                self.assert_not_staged()

    def test_symbolic_link_in_candidate_is_rejected(self):
        original = self.candidate / self.pdf
        outside = Path(self.temp.name) / 'outside.pdf'
        original.rename(outside)
        original.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'symbolic links'):
            self.finalize()

    def test_manifest_scope_unit_change_is_rejected(self):
        self.changed_manifest = copy.deepcopy(self.manifest)
        self.changed_manifest['units'][0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'Regenerated source manifest differs'):
            self.finalize()
        self.assert_not_staged()

    def test_unrelated_global_manifest_hashes_can_advance(self):
        self.changed_manifest = copy.deepcopy(self.manifest)
        self.changed_manifest.update(catalogSHA256='e' * 64, reviewedBooksSHA256='f' * 64)
        result = self.finalize()
        self.assertEqual(result['sourceCommit'], self.source_commit)

    def test_changed_source_during_checks_never_stages_candidate(self):
        self.after_checks = lambda _: self.write(self.root / 'materials/article.json', {'text': 'Later source.'})
        with self.assertRaisesRegex(ValueError, 'input.*changed'):
            self.finalize()
        self.assert_not_staged()

    def test_changed_acceptance_during_checks_never_stages_candidate(self):
        def change(_):
            value = read(self.acceptance)
            value['accepted'] = False
            self.write(self.acceptance, value)
        self.after_checks = change
        with self.assertRaisesRegex(ValueError, 'acceptance changed during'):
            self.finalize()
        self.assert_not_staged()

    def test_renderer_failure_never_upgrades_index_or_report(self):
        def fail(_):
            raise ValueError('Fixture independent export failure')
        self.after_checks = fail
        with self.assertRaisesRegex(ValueError, 'independent export failure'):
            self.finalize()
        self.assert_not_staged()
        self.assertFalse(read(self.prepared / 'index.json')['books'][0]['exportVerified'])

    def test_duplicate_scope_is_not_added_twice(self):
        self.finalize()
        before = (self.out / 'build-report.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'already has a finalized candidate'):
            self.finalize()
        self.assertEqual((self.out / 'build-report.json').read_bytes(), before)

    def test_persisted_visual_evidence_is_rechecked_before_publication(self):
        result = self.finalize()
        folder = self.out / result['folder']
        book = read(folder / 'library-snapshot.json')['entries'][0]['book']
        approval = read(folder / 'visual-acceptance.json')
        approval['reviewer'] = 'Different fixture reviewer'
        self.write(folder / 'visual-acceptance.json', approval)
        with self.assertRaisesRegex(ValueError, 'captured release evidence'):
            finish.verify_final_visual_acceptance(folder, book)

    def test_persisted_visual_evidence_cannot_cover_changed_book_hashes(self):
        result = self.finalize()
        folder = self.out / result['folder']
        book = read(folder / 'library-snapshot.json')['entries'][0]['book']
        book['pdfSha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'indexed final pair hashes'):
            finish.verify_final_visual_acceptance(folder, book)

    def test_persisted_visual_evidence_cannot_be_omitted(self):
        result = self.finalize()
        folder = self.out / result['folder']
        book = read(folder / 'library-snapshot.json')['entries'][0]['book']
        book.pop('finalVisualAcceptance')
        with self.assertRaisesRegex(ValueError, 'captured release evidence'):
            finish.verify_final_visual_acceptance(folder, book)

    def test_concurrent_build_report_update_is_preserved(self):
        original = {'sourceCommit': self.commit, 'built': [], 'failed': []}
        self.write(self.out / 'build-report.json', original)
        concurrent = {**original, 'concurrentNote': 'Another scope advanced.'}
        self.after_checks = lambda _: self.write(self.out / 'build-report.json', concurrent)
        with self.assertRaisesRegex(ValueError, 'Build report changed during'):
            self.finalize()
        self.assert_not_staged()
        self.assertEqual(read(self.out / 'build-report.json'), concurrent)

    def test_publication_head_advance_is_rejected(self):
        with patch.object(finish, 'git_head', side_effect=[self.commit, 'c' * 40]), patch.object(finish, 'execute', side_effect=self.external):
            with self.assertRaisesRegex(ValueError, 'checkout changed during'):
                finish.finalize(self.root, self.prepared, self.candidate, self.handoff,
                                self.acceptance, self.out, self.commit, self.repo, self.tag)
        self.assert_not_staged()


if __name__ == '__main__':
    unittest.main()
