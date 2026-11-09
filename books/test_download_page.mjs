import assert from 'node:assert/strict';
import {LANGUAGES,canonicalLanguage,resolveLanguage,downloadURL,viewModel,contentCoverage} from '../docs/books/books.mjs';
import {COPY} from '../docs/books/copy.mjs';
assert.equal(LANGUAGES.length,20);assert.deepEqual(Object.keys(COPY).sort(),[...LANGUAGES].sort());
for(const lang of LANGUAGES){
  assert.equal(resolveLanguage(`?lang=${lang}`,['en']),lang);assert.equal(canonicalLanguage(lang),lang);
  const file=extension=>`https://github.com/blaghtayt-alt/iman-companion/releases/download/verified/Iman_Companion_${lang}_tadabbur-extended.${extension}`;
  const book={language:lang,collection:'tadabbur-extended',title:COPY[lang].library,units:1,docx:file('docx'),pdf:file('pdf')};
  const catalog={schema:'iman-book-downloads-v1',languages:{[lang]:{language:lang,books:[book],bundle:{docx:book.docx,pdf:book.pdf,zip:`https://github.com/blaghtayt-alt/iman-companion/releases/download/verified/Iman_Companion_${lang}_all-books.zip`,parts:1}}}};
  assert.equal(viewModel(catalog,lang).books.length,1);assert.equal(viewModel(catalog,lang).bundle.docx,book.docx);
  const wrong=structuredClone(catalog);wrong.languages[lang].books[0].docx=file('docx').replace(`_${lang}_`,'_unknown_');assert.throws(()=>viewModel(wrong,lang));
  assert.equal(downloadURL(file('pdf')+'?redirect=other',lang,'pdf'),null);assert.equal(downloadURL(file('pdf').replace('https:','http:'),lang,'pdf'),null);
  const empty={schema:catalog.schema,languages:{[lang]:{language:lang,books:[],bundle:null}}};assert.equal(viewModel(empty,lang).books.length,0);assert.equal(viewModel(empty,lang).bundle,null);
  const collections=['tadabbur-extended','hadith','seerah','articles'];
  const multiple=structuredClone(catalog),row=multiple.languages[lang];
  row.books=collections.map(collection=>({...book,collection,docx:file('docx').replace('tadabbur-extended',collection),pdf:file('pdf').replace('tadabbur-extended',collection)}));
  row.bundle={...row.bundle,parts:4,docx:file('docx').replace('tadabbur-extended','all-books'),pdf:file('pdf').replace('tadabbur-extended','all-books')};
  assert.deepEqual(viewModel(multiple,lang).books.map(item=>item.collection),collections);assert.equal(viewModel(multiple,lang).bundle.docx,row.bundle.docx);
  for(const collection of collections){
    const switched=structuredClone(multiple);switched.languages[lang].books.find(item=>item.collection===collection).pdf=file('pdf').replace(`_${lang}_`,'_unknown_');assert.throws(()=>viewModel(switched,lang));
  }
  const partial=structuredClone(multiple);partial.languages[lang].bundle.parts=3;assert.throws(()=>viewModel(partial,lang));
  const duplicate=structuredClone(multiple);duplicate.languages[lang].books[3]=duplicate.languages[lang].books[2];assert.throws(()=>viewModel(duplicate,lang));
  const covered=structuredClone(catalog),coveredBook=covered.languages[lang].books[0];
  coveredBook.contents=[{id:'112:extended',title:COPY[lang].library,numberLabel:'112'}];
  coveredBook.coverage={schema:'iman-book-content-coverage-v1',language:lang,collection:'tadabbur-extended',
    sourceIds:['1:extended','112:extended'],catalogIds:['1:extended','112:extended'],selectedIds:['112:extended'],includedIds:['112:extended'],
    missingCurrent:[{id:'1:extended',reason:'source-not-bound'}],absentEarlierLessons:[],
    presentation:{includedLabel:'112',statusLabel:COPY[lang].library,notes:['1'],unitLabels:{'112:extended':'112'}}};
  assert.equal(viewModel(covered,lang).books[0].coverage.presentation.includedLabel,'112');
  const falseIncluded=structuredClone(coveredBook);falseIncluded.coverage.includedIds=['1:extended'];assert.throws(()=>contentCoverage(falseIncluded));
  const wrongNumbers=structuredClone(coveredBook);wrongNumbers.contents[0].numberLabel='1';assert.throws(()=>contentCoverage(wrongNumbers));
  const alreadyIncluded=structuredClone(coveredBook);alreadyIncluded.coverage.missingCurrent[0].id='112:extended';assert.throws(()=>contentCoverage(alreadyIncluded));
  const absentInstalled=structuredClone(coveredBook);absentInstalled.coverage.absentEarlierLessons=[{id:'1:extended',reason:'current-source-not-installed'}];assert.throws(()=>contentCoverage(absentInstalled));
  assert.ok(Object.values(COPY[lang]).every(x=>typeof x==='string'&&x.length));
  if(['ar','ur','fa','bn','hi','ru','zh-CN','th','ja'].includes(lang))assert.ok(Object.values(COPY[lang]).every(x=>!/[A-Za-z]/.test(x)),lang+' copy leaked English');
}
assert.equal(canonicalLanguage('pt_BR'),'pt-BR');assert.equal(canonicalLanguage('zh-Hans'),'zh-CN');assert.equal(canonicalLanguage('tl'),'fil');assert.equal(canonicalLanguage('ar-SA'),'ar');assert.equal(resolveLanguage('?lang=ja',['ar']),'ja');
console.log('20 native download routes, four-category inventories, book identities, exact numbered coverage, combined choices and empty-language behavior passed.');
