import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {viewModel,updateStatus,LANGUAGES} from '../docs/books/books.mjs';
const catalog=JSON.parse(readFileSync(new URL('../docs/books/catalog.json',import.meta.url)));
const status=JSON.parse(readFileSync(new URL('../docs/books/update-status.json',import.meta.url)));
for(const language of LANGUAGES){
  const model=viewModel(catalog,language,status);
  assert.equal(model.books.length,catalog.languages[language].books.length);
  for(const book of model.books){
    assert.equal(updateStatus(null,book).updatePending,true);
    assert.equal(updateStatus(status,{...book,sha256:'0'.repeat(64)}).state,'status-unverified');
  }
  if(model.bundle){
    assert.equal(model.bundle.updatePending,status.languages[language].bundleUpdatePending||model.books.some(b=>b.sourceUpdate.updatePending));
    // UI fixtures only: no real source or release acceptance is created.
    const fixture=structuredClone(status),locale=fixture.languages[language];
    for(const book of Object.values(locale.books)){book.updatePending=false;book.state='current';}
    locale.bundleUpdatePending=false;
    const current=viewModel(catalog,language,fixture);
    assert.equal(current.bundle.updatePending,false);
    assert.ok(current.books.every(book=>book.sourceUpdate.updatePending===false));
    const first=Object.values(locale.books)[0];
    if(first){
      first.updatePending=true;first.state='source-registration-blocked';
      assert.equal(viewModel(catalog,language,fixture).bundle.updatePending,true);
      first.updatePending=false;first.state='current';
    }
    locale.bundleLinks.docx+='-different-version';
    assert.equal(viewModel(catalog,language,fixture).bundle.updatePending,true);
    assert.equal(viewModel(catalog,language,null).bundle.updatePending,true);
  }
}
console.log('All 20 languages: current/pending transitions, hash bindings, missing-status fallback and combined downloads passed.');
