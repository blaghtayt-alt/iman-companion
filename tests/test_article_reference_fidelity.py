"""Original article citations survive adapter, Word notes and final validation."""
from copy import deepcopy
from pathlib import Path
import hashlib,json,shutil,sys,tempfile,unittest,zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'books'))
from adapt_ar_articles import generate,reference_groups,validate_reference_markers
from bibliography import native_text
from build_books import Footnotes,check_unit,embed_fonts,reference_text
from check_outputs import validate_footnotes
from docx import Document
from lxml import etree

DOI8='DOI: 10.1016/j.jpsychires.2015.10.017'
DOI9='DOI: 10.1002/wps.20499'
IDENTIFIERS=('ARW-250',DOI8,DOI9,'DOI: 10.4103/0253-7176.194905','L07','T07')
RESTORED=(1,2,4,6,9,14,18,19,31,36,38,39,43,45,46,47)

def sha(raw):return hashlib.sha256(raw).hexdigest()
def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8')

class ArticleReferenceFidelity(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        full=json.loads((ROOT/'books/source-projections/ar-articles.json').read_bytes())
        self.projection={**full,'articles':[a for a in full['articles'] if a['number'] in RESTORED]}
        selected={a['id'] for a in self.projection['articles']}
        self.catalog=json.loads((ROOT/'materials/catalog.json').read_bytes())
        self.catalog['entries']=[r for r in self.catalog['entries'] if r.get('collection')=='articles' and r.get('language')=='ar' and r.get('id') in selected]
        index=json.loads((ROOT/'materials/articles/prepared-ar/index.json').read_bytes())
        index['articles']=[r for r in index['articles'] if r['id'] in selected]
        dump(self.root/'materials/catalog.json',self.catalog)
        dump(self.root/'materials/articles/prepared-ar/index.json',index)
        for row in self.catalog['entries']:
            target=self.root/row['markdown'];target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/row['markdown'],target)
        self.declaration={'language':'ar','collection':'articles','adapter':'arabic-articles-v1',
                          'projection':'books/source-projections/ar-articles.json',
                          'materialIndex':'materials/articles/prepared-ar/index.json'}
        # This is a historical citation-fidelity fixture, not a live-source
        # approval. Reconstruct its exact projection in the temporary root;
        # a later source edit must fail production intake, not mask the
        # independent marker/qualification corruption exercised below.
        for article in self.projection['articles']:
            row=next(r for r in self.catalog['entries'] if r['id']==article['id'])
            item=next(r for r in index['articles'] if r['id']==article['id'])
            row.update(title=article['title'],sourceHashes=[article['sourceSHA256']],readingSHA256=article['readingSHA256'])
            item.update(title=article['title'],preparedSourceSHA256=article['sourceSHA256'],readingSHA256=article['readingSHA256'])
            self.refresh(article)
        dump(self.root/'materials/catalog.json',self.catalog)
        dump(self.root/'materials/articles/prepared-ar/index.json',index)
        self.refresh()

    def tearDown(self):self.temp.cleanup()

    def article(self,number):return next(a for a in self.projection['articles'] if a['number']==number)

    def refresh(self,material=None):
        if material is not None:
            row=next(r for r in self.catalog['entries'] if r['id']==material['id'])
            paragraphs=[('## ' if p['kind']=='heading' else '')+p['text'] for p in material['paragraphs']]
            text='\n\n'.join(['# '+material['title'],*paragraphs,'## المراجع',*[r['text'] for r in material['references']]])+'\n'
            path=self.root/row['markdown'];path.write_text(text,encoding='utf8');material['materialSHA256']=sha(path.read_bytes())
        path=self.root/self.declaration['projection'];dump(path,self.projection)
        self.declaration['projectionSHA256']=sha(path.read_bytes())

    def units(self):return generate(self.root,self.catalog,self.declaration)

    def test_original_titles_qualifications_and_dois_reach_their_exact_notes(self):
        units=self.units()
        for unit in units:
            article=self.article(unit['number']);blocks=unit['sections'][0]['blocks']
            self.assertEqual([b['text'] for b in blocks if b['kind']!='note'],[p['text'] for p in article['paragraphs']])
            self.assertEqual(unit['sourceHashes'],[article['sourceSHA256']])
            self.assertEqual(unit['provenance']['readingSHA256'],article['readingSHA256'])
            notes=[n for b in blocks for s in b.get('spans',[]) for n in s.get('noteTexts',[])]+[b['text'] for b in blocks if b['kind']=='note']
            for ref in article['references']:
                if not ref.get('continuationOf'):self.assertTrue(any(reference_text(ref['text']) in n for n in notes),ref['text'])
                for segment in ref['segments']:
                    if segment.get('externalLink'):self.assertTrue(any(segment['text'] in n for n in notes),segment['text'])
            if unit['number']==9:
                for number,doi in [('٨',DOI8),('٩',DOI9)]:
                    text=next(r['text'] for r in article['references'] if r['id']==number)
                    self.assertEqual(sum(text+'\n'+doi==n for n in notes),1)
                self.assertFalse(any(b['kind']=='note' and 'DOI:' in b['text'] for b in blocks))
        article6=next(u for u in units if u['number']==6)
        joined='\n'.join(n for b in article6['sections'][0]['blocks'] for s in b.get('spans',[]) for n in s.get('noteTexts',[]))
        self.assertIn('يُذكر لإثبات التسمية، لا للحكم بصحة المماثلة الفكرية.',joined)
        self.assertIn('بيانات النقل ليست بيانات الأرباح.',joined)

    def test_deleted_original_marker_positions_have_exact_reference_only_anchors(self):
        proof=self.projection['sourceReferenceProvenance'];verified=0
        for change in proof['restorations']:
            article=self.article(change['number'])
            for anchor in change['restoredBodyAnchors']:
                if anchor['bindingMode']!='exact-original-marker-position-with-no-visible-text-insertion':continue
                paragraph=article['paragraphs'][anchor['paragraphIndex']]
                marker='['+anchor['referenceId']+']';original=anchor['originalSourceParagraphText']
                self.assertEqual(original.replace(marker,''),paragraph['text'])
                self.assertNotIn(marker,paragraph['text'])
                self.assertEqual(sha(original.encode()),anchor['originalSourceParagraphSHA256'])
                offset=0;matches=[]
                for segment in paragraph['segments']:
                    offset+=len(segment['text'])
                    if segment.get('note')==anchor['referenceId']:matches.append(offset)
                self.assertEqual(matches,[anchor['codepointOffset']]);verified+=1
        self.assertEqual(verified,8)

    def test_only_editorial_format_instructions_remain_in_bound_provenance(self):
        ledger=self.projection['sourceReferenceProvenance']['omissionLedger']
        self.assertEqual(len(ledger),11)
        self.assertTrue(all(x['disposition']=='retained-in-bound-provenance-only' for x in ledger))
        originals=[r['text'] for a in self.projection['sourceReferenceProvenance']['originalSources'] for r in a['originalReferenceParagraphs']]
        for row in ledger:self.assertIn(row['text'],originals)

    def test_evidence_only_change_without_a_new_projection_binding_is_rejected(self):
        self.projection['sourceReferenceProvenance']['originalSources'][0]['sourceBytes']+=1
        dump(self.root/self.declaration['projection'],self.projection)
        with self.assertRaisesRegex(ValueError,'projection changed'):self.units()

    def test_identifier_bytes_survive_actual_docx_footnotes_and_final_checks(self):
        doc=Document();notes=Footnotes(doc,'ar','Iman Book Noto Naskh Arabic','Iman Book Noto Naskh Arabic')
        for unit in self.units():
            for block in unit['sections'][0]['blocks']:
                if block['kind']=='note':
                    notes.add(doc.paragraphs[-1],block['text'],preserved_identifiers=block.get('preservedIdentifiers',()))
                    continue
                p=doc.add_paragraph(block['text'])
                for index,span in enumerate(block.get('spans',[])):
                    for note_index,text in enumerate(span.get('noteTexts',[])):
                        ids=span.get('noteIdentifiers',[[] for _ in span.get('noteTexts',[])])[note_index]
                        notes.add(p,text,group=(index,note_index),preserved_identifiers=ids)
        target=self.root/'citation-proof.docx';doc.save(target);embed_fonts(target,{},notes.root)
        with zipfile.ZipFile(target) as archive:
            body=etree.fromstring(archive.read('word/document.xml'))
            actual=etree.fromstring(archive.read('word/footnotes.xml'))
        validate_footnotes(actual,body,notes.texts,'ar',preserved_identifiers=notes.identifiers)
        literal=''.join(actual.xpath('//w:t/text()',namespaces={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}))
        for identifier in IDENTIFIERS:self.assertIn(identifier,literal)
        with self.assertRaisesRegex(ValueError,'Latin-script'):validate_footnotes(actual,body,notes.texts,'ar')
        changed=deepcopy(actual);tampered=False
        for node in changed.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'):
            if node.text and 'ARW' in node.text:node.text=node.text.replace('ARW','ARX');tampered=True;break
        self.assertTrue(tampered)
        with self.assertRaises(ValueError):validate_footnotes(changed,body,notes.texts,'ar',preserved_identifiers=notes.identifiers)

    def test_undefined_visible_source_marker_cannot_pass_without_note_metadata(self):
        article=self.article(14)
        article['references']=[r for r in article['references'] if r['id']!='٣']
        for p in article['paragraphs']:
            for s in p['segments']:
                if s.get('note')=='٣':s.pop('note')
        self.refresh(article)
        with self.assertRaisesRegex(ValueError,'source marker has no reference'):self.units()

    def test_existing_reference_cannot_leave_its_visible_marker_unbound(self):
        article=self.article(14)
        for p in article['paragraphs']:
            for s in p['segments']:
                if s.get('note')=='٥':s.pop('note')
        self.refresh()
        with self.assertRaisesRegex(ValueError,'marker is not bound'):self.units()

    def test_composite_markers_require_every_number_to_keep_its_note_binding(self):
        article=self.article(47)
        for paragraph_index,number in [(40,'٥'),(103,'١٥')]:
            with self.subTest(paragraph=paragraph_index,number=number):
                original=deepcopy(article['paragraphs'][paragraph_index])
                for segment in article['paragraphs'][paragraph_index]['segments']:
                    if segment.get('note')==number:segment.pop('note')
                self.refresh()
                with self.assertRaisesRegex(ValueError,'marker is not bound'):self.units()
                article['paragraphs'][paragraph_index]=original

    def test_composite_marker_cannot_retain_an_undefined_reference_number(self):
        article=self.article(47)
        article['references']=[r for r in article['references'] if r['id']!='١٥']
        for segment in article['paragraphs'][103]['segments']:
            if segment.get('note')=='١٥':segment.pop('note')
        self.refresh(article)
        with self.assertRaisesRegex(ValueError,'source marker has no reference'):self.units()

    def test_existing_composite_marker_with_nbsp_keeps_each_source_binding(self):
        projection=json.loads((ROOT/'books/source-projections/ar-articles.json').read_bytes())
        article=next(a for a in projection['articles'] if a['number']==33)
        paragraph=deepcopy(article['paragraphs'][23]);groups=reference_groups(article['references'])
        self.assertIn('[٢،\u00a0٣]',paragraph['text'])
        validate_reference_markers(paragraph,groups)
        for segment in paragraph['segments']:
            if segment.get('note')=='٣':segment.pop('note')
        with self.assertRaisesRegex(ValueError,'marker is not bound'):validate_reference_markers(paragraph,groups)

    def test_continuation_requires_an_explicit_preceding_source_binding(self):
        article=self.article(9)
        next(r for r in article['references'] if r.get('continuationOf')=='٨')['continuationOf']='٩'
        self.refresh()
        with self.assertRaisesRegex(ValueError,'preceding source'):self.units()

    def test_ordinary_unnumbered_bibliography_is_not_guessed_as_a_continuation(self):
        article=self.article(9);text='مرجع مستقل في خاتمة المقال.'
        article['references'].append({'id':'','text':text,'segments':[]})
        self.refresh(article)
        unit=next(u for u in self.units() if u['number']==9)
        self.assertEqual(unit['sections'][0]['blocks'][-1],{'kind':'note','text':text})

    def test_declared_identifier_must_occur_exactly_in_that_source_reference(self):
        article=self.article(6)
        next(r for r in article['references'] if r['id']=='١٣')['preservedIdentifiers']=['ARW-251']
        self.refresh()
        with self.assertRaisesRegex(ValueError,'exact complete token'):self.units()

    def test_identifier_metadata_cannot_exempt_body_prose(self):
        unit=self.units()[0];block=unit['sections'][0]['blocks'][0]
        block['preservedIdentifiers']=['ARW-250']
        with self.assertRaisesRegex(ValueError,'only exempt literal reference notes'):check_unit(unit,unit)


class StrictIdentifierGuard(unittest.TestCase):
    def test_default_remains_strict_and_explicit_exact_tokens_remain_unchanged(self):
        for identifier in IDENTIFIERS:
            text='مرجع المصدر: '+identifier+'.'
            with self.subTest(identifier=identifier):
                with self.assertRaises(ValueError):native_text(text,'ar')
                self.assertEqual(native_text(text,'ar',preserved_identifiers=[identifier]),text)

    def test_changed_partial_or_arbitrary_latin_exemptions_fail(self):
        cases=[('DOI: 10.1002/wps.204990',[DOI9]),
               ('DOI: 10.1002/wps.20499.extra',[DOI9]),
               ('prefixARW-250',['ARW-250']),
               ('ARW-250 and untranslated prose',['ARW-250']),
               ('DOI: 10.1002/wps.20499',[DOI9,DOI9]),
               ('English source',['English source']),
               ('https://example.test',['https://example.test']),
               ('ARW-250','ARW-250')]
        for text,identifiers in cases:
            with self.subTest(text=text,identifiers=identifiers):
                with self.assertRaises(ValueError):native_text(text,'ar',preserved_identifiers=identifiers)

if __name__=='__main__':unittest.main()
