import assert from 'node:assert/strict';
import {LANGUAGES,canonicalLanguage,resolveLanguage,downloadURL,viewModel} from '../docs/books/books.mjs';
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
  assert.ok(Object.values(COPY[lang]).every(x=>typeof x==='string'&&x.length));
  if(['ar','ur','fa','bn','hi','ru','zh-CN','th','ja'].includes(lang))assert.ok(Object.values(COPY[lang]).every(x=>!/[A-Za-z]/.test(x)),lang+' copy leaked English');
}
assert.equal(canonicalLanguage('pt_BR'),'pt-BR');assert.equal(canonicalLanguage('zh-Hans'),'zh-CN');assert.equal(canonicalLanguage('tl'),'fil');assert.equal(canonicalLanguage('ar-SA'),'ar');assert.equal(resolveLanguage('?lang=ja',['ar']),'ja');
console.log('20 native download routes, book identities, combined choices and empty-language behavior passed.');
