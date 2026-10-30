import {GaussianViewer} from './viewer.js';
const $=id=>document.getElementById(id);
let scene,viewer,selectedView=0,sceneBase='sample/',notes=[],files=[],fileRecords=[],apiAvailable=false,jobId,sceneKey;
let activeTab='workspace';
const text=(id,value)=>$(id).textContent=value;
const number=value=>Number.isFinite(value)?value.toLocaleString(undefined,{maximumFractionDigits:2}):'Not evaluated';
const finite=(v,size)=>Array.isArray(v)&&v.length===size&&v.every(Number.isFinite);
let toastTimer;
function toast(message,error=false){text('toast',message);$('toast').classList.toggle('error',error);$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,6500);}
function showTab(tab){activeTab=tab;document.querySelectorAll('.tab-panel').forEach(el=>el.hidden=el.id!==`${tab}-panel`);document.querySelectorAll('[data-tab]').forEach(el=>{el.classList.toggle('active',el.dataset.tab===tab);el.setAttribute('aria-current',el.dataset.tab===tab?'page':'false');});const titles={workspace:['Scene reconstruction desk','Inspect the scene. Trace the sources. Document the limitations.'],evidence:['Source inventory','Begin with the original. Trace every transformation.'],validation:['Validation & limitations','Understand the experiment before interpreting its result.'],notes:['Review notes & hypotheses','Keep source observations and interpretations in separate layers.']};$('page-title').replaceChildren(document.createTextNode(titles[tab][0]));const dot=document.createElement('span');dot.textContent='.';$('page-title').append(dot);text('page-description',titles[tab][1]);text('breadcrumb',{workspace:'Reconstruction',evidence:'Source inventory',validation:'Validation',notes:'Review notes'}[tab]);if(tab==='workspace')viewer?.draw();}
document.querySelectorAll('[data-tab]').forEach(el=>el.addEventListener('click',()=>showTab(el.dataset.tab)));
document.querySelectorAll('[data-open]').forEach(el=>el.addEventListener('click',()=>showTab(el.dataset.open)));
$('inspect-sources').addEventListener('click',()=>showTab('evidence'));
function safeAsset(path){if(typeof path!=='string'||!path||!/^[a-zA-Z0-9][a-zA-Z0-9_./-]*$/.test(path)||path.split('/').includes('..'))return '';return sceneBase+path;}
function image(id,path){const url=safeAsset(path);$(id).hidden=!url;if(url)$(id).src=url;else $(id).removeAttribute('src');}
function download(name,value){const blob=new Blob([JSON.stringify(value,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function sha(buffer){return [...new Uint8Array(await crypto.subtle.digest('SHA-256',buffer))].map(v=>v.toString(16).padStart(2,'0')).join('');}
function validateScene(value){
  const n=value?.positions?.length;
  if(value?.schema_version!==1||!Number.isInteger(n)||n<1||n>20000)throw Error('Scene must have schema_version 1 and 1–20,000 Gaussians.');
  if(!value.positions.every(v=>finite(v,3)&&v.every(x=>Math.abs(x)<1e6))||!Array.isArray(value.colors)||value.colors.length!==n||!value.colors.every(v=>finite(v,3)&&v.every(x=>x>=0&&x<=1))||!Array.isArray(value.scales)||value.scales.length!==n||!value.scales.every(v=>Number.isFinite(v)&&v>0&&v<1e5)||!Array.isArray(value.opacity)||value.opacity.length!==n||!value.opacity.every(v=>Number.isFinite(v)&&v>=0&&v<=1))throw Error('Invalid or non-finite Gaussian data.');
  if(!Array.isArray(value.views)||value.views.length>200||!value.views.every(v=>typeof v.id==='string'&&v.id.length<250&&(!v.camera||(finite(v.camera.eye,3)&&v.camera.eye.every(x=>Math.abs(x)<1e6)))))throw Error('Invalid view records.');
  if(!Array.isArray(value.cameras)||value.cameras.length>200||!value.cameras.every(c=>Array.isArray(c.R)&&c.R.length===3&&c.R.every(r=>finite(r,3))&&finite(c.t,3)&&finite(c.intrinsics,4)))throw Error('Invalid cameras.');
  return value;
}
async function loadScene(value,base){
  validateScene(value);scene=value;sceneBase=base;selectedView=0;sceneKey=await sha(new TextEncoder().encode(JSON.stringify({positions:scene.positions,sources:scene.manifest?.sources})));notes=[];
  try{const saved=JSON.parse(localStorage.getItem('scenetrace-notes-'+sceneKey)||'[]');if(Array.isArray(saved))notes=saved.filter(n=>n&&typeof n.id==='string'&&typeof n.text==='string'&&n.text.length<=1500&&['observation','hypothesis'].includes(n.type)&&typeof n.source==='string'&&typeof n.at==='string').slice(0,200);}catch{}
  viewer?.setScene(scene);text('scene-title',scene.kind==='synthetic'?'Archive room':scene.dataset?'CrossRow · public-photo test':'Imported reconstruction');text('scene-kind',scene.kind==='synthetic'?'SYNTHETIC':scene.dataset?'REAL CAPTURES / STAGED':'UNVALIDATED');text('gaussian-count',number(scene.positions.length));text('view-count',scene.metrics?.source_files||scene.views.length);text('view-caption',scene.metrics?.registered_cameras?`${scene.metrics.registered_cameras} registered / ${scene.metrics.heldout_source_views} withheld`:`${scene.views.filter(v=>v.split==='train').length} training / ${scene.views.filter(v=>v.split==='held-out').length} held out`);text('psnr',Number.isFinite(scene.metrics?.heldout_psnr_db)?`${scene.metrics.heldout_psnr_db.toFixed(2)} dB`:'Not evaluated');text('hash-count',`${(scene.manifest?.sources||[]).filter(s=>s.sha256).length} recorded`);text('render-status',`${scene.positions.length.toLocaleString()} Gaussians · ${scene.metrics?.source_files||scene.views.length} source files · WebGL preview`);
  const disclosure=document.querySelector('.disclosure p');disclosure.textContent=scene.kind==='synthetic'?'Synthetic demonstration. Known geometry and cameras; RGB fitted from six rendered views. Two views are held out. This is an optimizer test, not forensic validation.':'Imported research reconstruction. Geometry and scale are unvalidated. Inspect its source manifest and limitations before interpreting the scene.';if(scene.dataset)disclosure.textContent='Real camera captures · staged crime scene. CrossRow research dataset, 128 original photographs. Camera poses estimated by COLMAP. Not an actual criminal case; scale and geometry remain unvalidated.';document.querySelector('.disclosure-tag').textContent=scene.kind==='synthetic'?'NO REAL CASE DATA':'REVIEW BEFORE SHARING';
  $('psnr').nextElementSibling.textContent=scene.kind==='synthetic'?'Synthetic, same renderer':'No held-out localization';
  $('source-preview').alt=scene.kind==='synthetic'?'Selected synthetic source view':'Selected reconstruction derivative';
  renderFilmstrip();renderInventory();renderValidation();renderNotes();
  $('note-source').replaceChildren();for(const v of scene.views){const option=document.createElement('option');option.value=v.id;option.textContent=v.id;$('note-source').append(option);}
  if(scene.views.length)selectView(0,false);showTab(activeTab);
}
function renderFilmstrip(){
  $('filmstrip').replaceChildren();scene.views.forEach((v,i)=>{const button=document.createElement('button');button.className='view-button'+(v.split==='held-out'?' heldout':'');button.setAttribute('aria-label',`Inspect ${v.id}, ${v.split}`);const img=document.createElement('img');const url=safeAsset(v.image);if(url)img.src=url;img.alt=v.id;const label=document.createElement('span');label.textContent=`${String(i+1).padStart(2,'0')} / ${v.split==='held-out'?'TEST':'TRAIN'}`;const dot=document.createElement('i');dot.className='dot';label.append(dot);button.append(img,label);button.addEventListener('click',()=>selectView(i,true));$('filmstrip').append(button);});
}
function selectView(index,jump){
  selectedView=index;const v=scene.views[index];document.querySelectorAll('.view-button').forEach((b,i)=>{b.classList.toggle('active',i===index);b.setAttribute('aria-pressed',String(i===index));});image('source-preview',v.image);text('source-id',`VIEW ${String(index+1).padStart(2,'0')}`);text('source-name',v.image?.split('/').pop()||v.id);text('split-label',v.split==='held-out'?'HELD OUT':'TRAIN');text('source-origin',scene.kind==='synthetic'?'Procedural renderer':scene.dataset?'CrossRow · camera capture':'Selected derivative');text('camera-status',scene.kind==='synthetic'?'Known synthetic pose':'COLMAP estimate');text('source-split',v.split==='held-out'?'Held-out evaluation':'Training observation');const frame=scene.manifest?.frames?.find(f=>f.image===v.id);text('source-hash',v.sha256||frame?.sha256||'Hash not supplied');if(jump)viewer?.camera(v.camera||scene.cameras.find(c=>c.id===v.id));$('note-source').value=v.id;
}
function renderInventory(){const records=fileRecords.length?fileRecords:scene.manifest?.sources||[];text('inventory-title',fileRecords.length?'Selected local source records':scene.kind==='synthetic'?'Synthetic source records':'Imported source manifest');$('inventory-rows').replaceChildren();for(const record of records){const row=document.createElement('tr');for(const value of [record.name,record.bytes?`${(record.bytes/1024).toFixed(1)} KiB`:record.origin||'Original source',record.sha256||'Not supplied',record.status||'Hash recorded']){const cell=document.createElement('td');const el=document.createElement(value===record.sha256?'code':'span');el.textContent=String(value);cell.append(el);row.append(cell);}$('inventory-rows').append(row);}}
function renderValidation(){
  const m=scene.metrics||{};const reduction=Number.isFinite(m.train_mse_before)&&m.train_mse_before>0?(1-m.train_mse_after/m.train_mse_before)*100:null;
  $('validation-stats').replaceChildren();for(const [label,value,caption] of [['HELD-OUT PSNR',Number.isFinite(m.heldout_psnr_db)?`${m.heldout_psnr_db.toFixed(2)} dB`:'Not evaluated','Appearance agreement only'],['TRAIN MSE REDUCTION',reduction!==null?`${reduction.toFixed(2)}%`:'Not evaluated','Fixed geometry · fitted RGB'],['GEOMETRY VALIDATION','Not measured','No independent scale reference']]){const card=document.createElement('div');card.className='validation-stat';for(const [tag,content]of [['span',label],['strong',value],['small',caption]]){const el=document.createElement(tag);el.textContent=content;card.append(el);}$('validation-stats').append(card);}
  text('evaluation-caveat',m.evaluation_caveat||m.heldout_evaluation||'No independent held-out evaluation was supplied.');text('metrics-json',JSON.stringify(m,null,2));$('limitations').replaceChildren();for(const limitation of scene.limitations||[]){const li=document.createElement('li');li.textContent=String(limitation);$('limitations').append(li);}
  const heldout=scene.views.filter(v=>v.split==='held-out'&&v.render);$('comparison-view').replaceChildren();for(const view of heldout){const opt=document.createElement('option');opt.value=view.id;opt.textContent=view.id;$('comparison-view').append(opt);}
  const comparison=$('comparison-view').closest('.panel-card');comparison.hidden=!heldout.length;const display=()=>{const view=heldout.find(v=>v.id===$('comparison-view').value);if(view){image('compare-source',view.image);image('compare-render',view.render);}};$('comparison-view').onchange=display;display();
  document.querySelector('.validation-heading .eyebrow').textContent=scene.kind==='synthetic'?'REPRODUCIBLE EXPERIMENT / SEED 17':'IMPORTED RESEARCH ARTIFACT';
  document.querySelector('.validation-heading p').textContent=scene.kind==='synthetic'?'Training targets are separate from held-out appearance evaluation. Geometry and poses are supplied in this synthetic experiment.':'Review the reported training metrics and registration results. Independent held-out localization and scale validation are not implemented for uploaded scenes.';
}
function renderNotes(){text('note-count',`${notes.length} NOTES`);$('note-list').replaceChildren();if(!notes.length){const empty=document.createElement('div');empty.className='empty-state';empty.textContent='No review notes yet.\nAdd an observation or a clearly labeled hypothesis.';$('note-list').append(empty);return;}for(const note of notes){const article=document.createElement('article');article.className='note-entry '+note.type;const header=document.createElement('header');header.textContent=note.type==='hypothesis'?'HYPOTHESIS / INTERPRETATION':'SOURCE OBSERVATION';const remove=document.createElement('button');remove.textContent='Remove';remove.setAttribute('aria-label','Remove review note');remove.addEventListener('click',()=>{notes=notes.filter(n=>n.id!==note.id);storeNotes();renderNotes();});header.append(remove);const p=document.createElement('p');p.textContent=note.text;const meta=document.createElement('small');meta.textContent=`${note.source} · ${new Date(note.at).toLocaleString()}`;article.append(header,p,meta);$('note-list').append(article);}}
function storeNotes(){try{localStorage.setItem('scenetrace-notes-'+sceneKey,JSON.stringify(notes));}catch{toast('Browser storage is unavailable. Export your review to retain notes.',true);}}
$('note-form').addEventListener('submit',event=>{event.preventDefault();const content=$('note-text').value.trim(),source=$('note-source').value;if(!content||!source)return;if(notes.length>=200){toast('Maximum 200 notes per scene.',true);return;}notes.unshift({id:crypto.randomUUID(),type:$('note-type').value,source,text:content,at:new Date().toISOString()});storeNotes();renderNotes();$('note-text').value='';toast('Review note saved in this browser.');});
$('reset-view').addEventListener('click',()=>viewer?.reset());
for(const [id,mode]of [['mode-splats',0],['mode-points',1]])$(id).addEventListener('click',()=>{viewer?.setMode(mode);$('mode-splats').classList.toggle('selected',mode===0);$('mode-points').classList.toggle('selected',mode===1);});
$('export').addEventListener('click',()=>{if(!scene)return;download('scenetrace-review.json',{schema_version:1,exported_at:new Date().toISOString(),scene_fingerprint:sceneKey,label:scene.label,kind:scene.kind,manifest:scene.manifest,metrics:scene.metrics,limitations:scene.limitations,notes,local_inventory:fileRecords,disclosure:'Research review bundle, not forensic certification. Source names and hashes may be sensitive.'});toast('Review exported with provenance, limitations, and both annotation layers.');});
$('export-manifest').addEventListener('click',()=>download('scenetrace-manifest.json',fileRecords.length?{schema_version:1,kind:'browser-local-inventory',sources:fileRecords}:scene.manifest));
async function sample(){const res=await fetch('sample/scene.json');if(!res.ok)throw Error('Sample scene could not be loaded.');await loadScene(await res.json(),'sample/');}
$('sample-button').addEventListener('click',()=>sample().then(()=>toast('Synthetic reference experiment loaded.')).catch(e=>toast(e.message,true)));
$('import-scene').addEventListener('click',()=>$('scene-input').click());
$('scene-input').addEventListener('change',async()=>{try{const file=$('scene-input').files[0];if(!file)return;if(file.size>20*1024*1024)throw Error('Scene JSON limit is 20 MiB.');const value=JSON.parse(await file.text());await loadScene(value,'');toast('Scene imported. Relative source images require the local service; JSON does not embed media.');}catch(e){toast(e.message,true);}finally{$('scene-input').value='';}});
$('media-input').addEventListener('change',async()=>{files=[];fileRecords=[];$('run-job').disabled=true;try{const selected=[...$('media-input').files];if(selected.length>200||selected.reduce((s,f)=>s+f.size,0)>1024*1024*1024)throw Error('Choose at most 200 files totaling 1 GiB.');text('upload-caption','Hashing source bytes…');for(const file of selected){if(!/\.(jpe?g|png|webp|mp4|mov|avi|webm)$/i.test(file.name))throw Error('Unsupported media extension.');fileRecords.push({name:file.name,bytes:file.size,sha256:await sha(await file.arrayBuffer()),status:'Inventoried locally'});}files=selected;renderInventory();text('upload-caption',`${files.length} sources · ${apiAvailable?'local service ready':'hosted demo: local service required'}`);$('run-job').disabled=!apiAvailable||(files.length<4&&!files.some(f=>/\.(mp4|mov|avi|webm)$/i.test(f.name)));toast(`${files.length} files hashed locally. Original bytes unchanged.`);}catch(e){toast(e.message,true);text('upload-caption','Selection failed; choose files again.');}});
$('run-job').addEventListener('click',async()=>{if(!apiAvailable||(files.length<4&&!files.some(f=>/\.(mp4|mov|avi|webm)$/i.test(f.name))))return;$('run-job').disabled=true;$('job-status').hidden=false;$('job-status').classList.remove('error');text('job-status','Submitting to local COLMAP worker…');try{const form=new FormData();files.forEach(f=>form.append('files',f));const response=await fetch('/api/jobs',{method:'POST',headers:{'X-SceneTrace':'local-workbench'},body:form});const result=await response.json();if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'Job could not be submitted');jobId=result.id;await pollJob();}catch(e){text('job-status',e.message);$('job-status').classList.add('error');$('run-job').disabled=false;}});
async function pollJob(){const deadline=Date.now()+1850000;while(Date.now()<deadline){const response=await fetch(`/api/jobs/${jobId}`);if(!response.ok)throw Error('Worker status unavailable.');const result=await response.json();text('job-status',`${result.status.toUpperCase()} · ${result.error||'COLMAP camera recovery → fixed Gaussian RGB fitting. This may take several minutes.'}`);if(['failed','succeeded'].includes(result.status)){$('download-bundle').hidden=false;$('run-job').disabled=false;if(result.status==='failed'){$('job-status').classList.add('error');return;}const res=await fetch(result.scene);if(!res.ok)throw Error('Scene artifact unavailable.');await loadScene(await res.json(),`/api/jobs/${jobId}/assets/`);showTab('workspace');toast('Local reconstruction complete. Inspect its limitations and source coverage.');return;}await new Promise(resolve=>setTimeout(resolve,2000));}throw Error('Status polling ended. Inspect the local job directory.');}
$('download-bundle').addEventListener('click',()=>{if(jobId){const link=document.createElement('a');link.href=`/api/jobs/${jobId}/bundle`;link.download='scenetrace-review.zip';link.click();}});
async function start(){try{viewer=new GaussianViewer($('viewport'),message=>{text('viewer-error',message);$('viewer-error').hidden=false;});}catch(e){text('viewer-error',e.message);$('viewer-error').hidden=false;}
  try{await sample();}catch(e){toast(e.message,true);text('render-status','Scene unavailable');}
  try{const response=await fetch('/api/health');if(response.ok){const info=await response.json();apiAvailable=info.mode==='local-single-user';$('public-dataset').hidden=!info.public_test;}}catch{}
  text('service-status',apiAvailable?'Local worker connected':'Hosted review demo');text('upload-caption',apiAvailable?'Select 4–200 photos or a video':'Hosted demo · reconstruct with local service');
  if(apiAvailable&&new URLSearchParams(location.search).get('dataset')==='crossrow')await loadPublicTest();
}
start();

async function loadPublicTest(){
  try{
    const response=await fetch('/api/public-test');if(!response.ok)throw Error('Public-photo experiment is unavailable.');
    const info=await response.json();
    if(info.status!=='succeeded'){
      showTab('evidence');$('job-status').hidden=false;
      text('job-status',`PUBLIC-PHOTO TEST: ${info.status.toUpperCase()}. ${info.error||'Processing has not produced a scene yet.'} No valid reconstruction is displayed for this test.`);
      $('job-status').classList.toggle('error',info.status==='failed');
      try{const response=await fetch(`/api/jobs/${info.id}/assets/manifest.json`);if(response.ok){const manifest=await response.json();fileRecords=manifest.sources;renderInventory();renderPublicGallery(manifest,info.id);}}catch{}
      toast(`Public-photo test: ${info.status}. No substitute scene is used.`,true);return;
    }
    const result=await fetch(info.scene);if(!result.ok)throw Error('Reconstruction artifact unavailable.');
    const value=await result.json();value.dataset=info.dataset;value.license=info.license;jobId=info.asset_base?null:info.id;
    if(info.quality==='insufficient_coverage'){
      value.limitations.unshift(`INSUFFICIENT COVERAGE: only ${value.metrics.registered_cameras} of ${value.metrics.sfm_input_views} SfM input views registered. This partial artifact is not a usable reconstruction of the entire scene.`);
      value.metrics.quality_status='insufficient_coverage';
    }
    value.limitations.push('CrossRow: real photographs of a simulated crime scene; not an actual criminal case.','CC BY-NC-ND 4.0: local noncommercial research; scene media and adapted output are not republished.');
    await loadScene(value,info.asset_base||`/api/jobs/${info.id}/assets/`);renderPublicGallery(value.manifest,info.id,info.asset_base);showTab('workspace');
    if(info.quality==='insufficient_coverage'){
      document.querySelector('.disclosure p').textContent=`INSUFFICIENT COVERAGE · ${value.metrics.registered_cameras} of ${value.metrics.sfm_input_views} camera poses recovered from 128 genuine staged-scene photos. Partial artifact only; not a reconstruction of the full scene.`;
      text('scene-kind','INCOMPLETE / REAL CAPTURES');
    }
    toast('128 real photographs processed. The partial result has insufficient coverage.',true);
  }catch(error){toast(error.message,true);}
}
$('public-dataset').addEventListener('click',loadPublicTest);

function renderPublicGallery(manifest,id,base){
  let gallery=$('public-photo-gallery');
  if(!gallery){gallery=document.createElement('section');gallery.id='public-photo-gallery';gallery.className='panel-card public-photo-gallery';$('evidence-panel').append(gallery);}
  gallery.replaceChildren();const heading=document.createElement('div');heading.className='card-heading';
  const title=document.createElement('strong');title.textContent='CrossRow · genuine camera photographs / staged scene';heading.append(title);gallery.append(heading);
  const note=document.createElement('p');note.className='panel-body';note.textContent='Local research viewing only · CC BY-NC-ND 4.0 · Rinaldi, Gauld, Nic Daeid · DOI 10.15132/10000293. These previews are recorded orientation/size derivatives of original photographs, not AI images or a successful 3D reconstruction.';gallery.append(note);
  const grid=document.createElement('div');grid.className='public-photo-grid';
  for(const frame of manifest.frames.filter(f=>f.decision==='selected')){
    if(!/^view-\d+\.png$/.test(frame.image))continue;
    const link=document.createElement('a');link.href=(base||`/api/jobs/${id}/assets/`)+`images/${frame.image}`;link.target='_blank';link.rel='noopener';
    const image=document.createElement('img');image.src=link.href;image.loading='lazy';image.alt='CrossRow camera photograph '+frame.image;
    const label=document.createElement('span');label.textContent=frame.image;link.append(image,label);grid.append(link);
  }
  gallery.append(grid);
}
