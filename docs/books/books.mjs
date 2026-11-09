import {COPY} from './copy.mjs';
export const LANGUAGES=['en','ar','ur','id','ms','bn','tr','fr','pt-BR','hi','ru','es','fa','de','zh-CN','uz','th','vi','ja','fil'];
const COLLECTIONS=['tadabbur-extended','hadith','seerah','articles'];
const ALIASES={pt:'pt-BR','pt-br':'pt-BR',zh:'zh-CN','zh-cn':'zh-CN','zh-hans':'zh-CN',tl:'fil'};
export function canonicalLanguage(value){
  if(typeof value!=='string')return null;
  const key=value.trim().replaceAll('_','-').toLowerCase();
  return ALIASES[key]||LANGUAGES.find(lang=>lang.toLowerCase()===key)||LANGUAGES.find(lang=>lang===key.split('-')[0])||null;
}
export function resolveLanguage(search,preferred=[]){
  const requested=canonicalLanguage(new URLSearchParams(search).get('lang'));
  return requested||preferred.map(canonicalLanguage).find(Boolean)||'en';
}
export function downloadURL(value,language,extension,collection=null){
  try{
    const url=new URL(value);if(url.origin!=='https://github.com'||url.search||url.hash)return null;
    const prefix='/blaghtayt-alt/iman-companion/releases/download/';if(!url.pathname.startsWith(prefix))return null;
    const segments=url.pathname.slice(prefix.length).split('/');if(segments.length!==2||!segments[0])return null;
    const filename=decodeURIComponent(segments[1]);
    const valid=(collection?[collection]:[...COLLECTIONS,'all-books']).map(type=>`Iman_Companion_${language}_${type}.${extension}`);
    return valid.includes(filename)?url.href:null;
  }catch{return null;}
}
export function contentCoverage(book){
  const coverage=book.coverage;if(coverage==null)return null;
  if(coverage.schema!=='iman-book-content-coverage-v1'||coverage.language!==book.language||coverage.collection!==book.collection)throw Error('Incorrect coverage identity');
  const ids=value=>Array.isArray(value)&&value.every(id=>typeof id==='string'&&id.length>0)&&new Set(value).size===value.length;
  if(!ids(coverage.includedIds)||!ids(coverage.sourceIds)||!ids(coverage.catalogIds)||!ids(coverage.selectedIds))throw Error('Invalid coverage inventory');
  if(!Array.isArray(book.contents)||coverage.includedIds.length!==book.units||JSON.stringify(coverage.includedIds)!==JSON.stringify(book.contents.map(unit=>String(unit.id))))throw Error('Coverage differs from the actual download');
  if(!Array.isArray(coverage.missingCurrent)||!Array.isArray(coverage.absentEarlierLessons))throw Error('Missing coverage reconciliation');
  const reasons=['source-not-catalogued','source-not-bound','awaiting-book-release','review-incomplete'];
  if(coverage.missingCurrent.some(row=>!reasons.includes(row.reason)||typeof row.id!=='string'||coverage.includedIds.includes(row.id)))throw Error('Invalid missing-content state');
  if(coverage.absentEarlierLessons.some(row=>row.reason!=='current-source-not-installed'||typeof row.id!=='string'||coverage.sourceIds.includes(row.id)||coverage.includedIds.includes(row.id)))throw Error('Absent source is already included or installed');
  const copy=coverage.presentation;
  if(!copy||typeof copy.includedLabel!=='string'||!copy.includedLabel||typeof copy.statusLabel!=='string'||!Array.isArray(copy.notes)||copy.notes.some(note=>typeof note!=='string'||!note))throw Error('Missing native coverage labels');
  if(!copy.unitLabels||Array.isArray(copy.unitLabels)||Object.entries(copy.unitLabels).some(([id,label])=>!coverage.includedIds.includes(id)||typeof label!=='string'||!label))throw Error('Invalid numbered contents');
  for(const unit of book.contents){if(unit.numberLabel!==undefined&&unit.numberLabel!==copy.unitLabels[String(unit.id)])throw Error('Contents number differs from coverage');}
  return coverage;
}
export function viewModel(catalog,language){
  if(catalog?.schema!=='iman-book-downloads-v1'||!LANGUAGES.includes(language))throw Error('Invalid catalogue');
  const locale=catalog.languages?.[language];if(!locale||locale.language!==language||!Array.isArray(locale.books))throw Error('Missing locale');
  const seen=new Set();const books=locale.books.map(book=>{
    if(book.language!==language||!COLLECTIONS.includes(book.collection)||seen.has(book.collection))throw Error('Incorrect book identity');
    seen.add(book.collection);const docx=downloadURL(book.docx,language,'docx',book.collection),pdf=downloadURL(book.pdf,language,'pdf',book.collection);
    if(!docx||!pdf||!book.title||!Number.isInteger(book.units)||book.units<1)throw Error('Invalid book download');
    return {...book,docx,pdf,coverage:contentCoverage(book)};
  });
  let bundle=null;if(locale.bundle){
    const source=locale.bundle;const zip=downloadURL(source.zip,language,'zip'),docx=downloadURL(source.docx,language,'docx'),pdf=downloadURL(source.pdf,language,'pdf');
    if(!zip||!docx||!pdf||source.parts!==books.length)throw Error('Invalid combined downloads');
    bundle={zip,docx,pdf};
  }
  return {...locale,books,bundle,updated:catalog.updated};
}
function number(value,locale){return String(value).replace(/[0-9]/g,digit=>(locale.digits||'0123456789')[Number(digit)]);}
function text(id,value){document.getElementById(id).textContent=value;}
function localAsset(value){const url=new URL(value,location.href);if(url.origin!==location.origin||!url.pathname.includes('/books/assets/'))throw Error('Invalid book asset');return url.href;}
async function fonts(locale){
  if(!locale.font)return;
  const family=`Iman Download ${locale.language}`;document.documentElement.style.setProperty('--book-font',`"${family}"`);
  const regular=new FontFace(family,`url("${localAsset(locale.font.regular)}")`,{weight:'400'}),bold=new FontFace(family,`url("${localAsset(locale.font.bold)}")`,{weight:'700'});
  try{const loaded=await Promise.all([regular.load(),bold.load()]);loaded.forEach(font=>document.fonts.add(font));}catch{/* Keep native system shaping if a font download is interrupted. */}
}
export async function mount(){
  let language=resolveLanguage(location.search,navigator.languages||[navigator.language]);let catalog;let current;
  const select=document.getElementById('language'),dialog=document.getElementById('download-dialog');
  function labels(){
    const copy=COPY[language];document.documentElement.lang=language;document.documentElement.dir=['ar','ur','fa'].includes(language)?'rtl':'ltr';
    if(!current){text('brand',copy.library);text('title',copy.library);document.title=copy.library;}
    for(const[id,key]of[['language-label','language'],['description','intro'],['eyebrow','library'],['combined','together'],['dialog-title','question'],['merged-label','merged'],['zip-label','zip'],['close','close'],['retry','retry']])text(id,copy[key]);
    select.setAttribute('aria-label',copy.language);select.value=language;
  }
  function render(){
    labels();current=viewModel(catalog,language);const copy=COPY[language];text('brand',current.brand);text('title',current.title);document.title=current.title;
    document.getElementById('books').replaceChildren();text('status',current.books.length?'':copy.empty);text('updated','');document.getElementById('retry').hidden=true;
    for(const book of current.books){
      const card=document.createElement('article');card.className='book';card.dataset.collection=book.collection;
      const wrap=document.createElement('div');wrap.className='cover-wrap';const image=document.createElement('img');image.className='cover';image.src=localAsset(book.cover);image.alt=book.title;image.width=432;image.height=648;image.loading=current.books.indexOf(book)===0?'eager':'lazy';wrap.append(image);card.append(wrap);
      const heading=document.createElement('h2');heading.textContent=book.title;card.append(heading);
      if(book.statusLabel){const status=document.createElement('p');status.className='notice';status.textContent=book.statusLabel;card.append(status);}
      const coverage=book.coverage?.presentation;
      if(coverage?.statusLabel){const status=document.createElement('p');status.className='notice';status.textContent=coverage.statusLabel;card.append(status);}
      if(book.contents?.length){const contents=document.createElement('details');contents.className='contents';const summary=document.createElement('summary');summary.textContent=current.included;const list=document.createElement('ul');for(const unit of book.contents){const item=document.createElement('li');item.textContent=unit.numberLabel?`${unit.numberLabel} · ${unit.title}`:unit.title;list.append(item);}contents.append(summary,list);card.append(contents);}
      const meta=document.createElement('p');meta.className='metadata';const count=document.createElement('span');count.textContent=coverage?.includedLabel||`${current.included}: ${number(book.units,current)}`;meta.append(count);
      if(book.pages){const pages=document.createElement('span');pages.textContent=`${copy.pages}: ${number(book.pages,current)}`;meta.append(pages);}card.append(meta);
      if(coverage?.notes.length){const notes=document.createElement('ul');notes.className='contents';for(const text of coverage.notes){const note=document.createElement('li');note.textContent=text;notes.append(note);}card.append(notes);}
      if(book.audio){const note=document.createElement('p');note.className='audio-note';note.textContent=copy.audio;card.append(note);}
      const links=document.createElement('div');links.className='downloads';
      for(const[type,kind]of[['pdf','primary'],['docx','secondary']]){const link=document.createElement('a');link.className=kind;link.href=book[type];link.setAttribute('download','');link.textContent=current.downloads[type];links.append(link);}card.append(links);document.getElementById('books').append(card);
    }
    document.getElementById('combined').hidden=!current.bundle;
    if(current.updated){try{text('updated',`${copy.updated}: ${number(new Intl.DateTimeFormat(language,{dateStyle:'medium'}).format(new Date(current.updated)),current)}`);}catch{}}
    void fonts(current);
  }
  async function load(){
    labels();try{const response=await fetch('catalog.json',{cache:'no-store'});if(!response.ok)throw Error('Catalogue unavailable');catalog=await response.json();
      select.replaceChildren(...LANGUAGES.map(lang=>{const option=document.createElement('option');option.value=lang;option.textContent=catalog.languages?.[lang]?.name||lang;return option;}));render();
    }catch{labels();document.getElementById('books').replaceChildren();document.getElementById('combined').hidden=true;text('status',COPY[language].error);document.getElementById('retry').hidden=false;}
  }
  select.addEventListener('change',()=>{language=canonicalLanguage(select.value)||language;const url=new URL(location.href);url.searchParams.set('lang',language);history.replaceState(null,'',url);if(dialog.open)dialog.close();render();});
  document.getElementById('retry').addEventListener('click',load);
  document.getElementById('combined').addEventListener('click',()=>{
    if(!current?.bundle)return;const bundle=current.bundle;text('dialog-hint',current.title);document.getElementById('choices').hidden=false;document.getElementById('merged-formats').hidden=true;
    document.getElementById('zip-choice').href=bundle.zip;
    for(const type of['pdf','docx']){const link=document.getElementById('merged-'+type);link.href=bundle[type];link.textContent=current.downloads[type];}dialog.showModal();
  });
  document.getElementById('merged-choice').addEventListener('click',()=>{document.getElementById('choices').hidden=true;document.getElementById('merged-formats').hidden=false;});
  document.getElementById('close').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close();});
  await load();
}
if(typeof document!=='undefined')void mount();
