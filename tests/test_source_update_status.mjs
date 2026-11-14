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
  if(model.bundle)assert.equal(model.bundle.updatePending,status.languages[language].bundleUpdatePending||model.books.some(b=>b.sourceUpdate.updatePending));
}
const ar=viewModel(catalog,'ar',status);
assert.equal(ar.books.find(b=>b.collection==='tadabbur-extended').sourceUpdate.updatePending,true);
console.log('All 20 languages: hash-bound pending notices, missing-status fallback and combined downloads passed.');
