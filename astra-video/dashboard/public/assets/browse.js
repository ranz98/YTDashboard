'use strict';
const browseFilters={
  library:{stage:'all',range:'all',from:'',to:'',sort:'activity'},
  jobs:{stage:'all',state:'all',range:'all',from:'',to:'',sort:'activity'}
};
let browseRows=[],browseTotal=0,browseMore=false,browseLoading=false,browseGeneration=0,browseOffset=0;
let errorSnapshot=null,showDismissed=false;
const dismissKey='astra.dismissed-errors.v1';
function dismissedErrors(){try{return new Set(JSON.parse(localStorage.getItem(dismissKey)||'[]'));}catch{return new Set();}}
const errorKey=(kind,row)=>`${kind}:${row.id}:${row.state||row.level}:${row.finished_at||row.started_at||row.created_at||''}`;
function choices(values,selected){return values.map(([value,label])=>`<option value="${value}" ${selected===value?'selected':''}>${label}</option>`).join('');}
function browseControls(view){
  const f=browseFilters[view],video=view==='library';
  const tabs=video?[['all','All videos'],['fetched','Fetched'],['edited','Edited'],['uploaded','Uploaded']]:[['all','All agents'],['fetch','Fetch'],['editor','Edit'],['uploader','Upload']];
  return `<div class="browse-controls"><div class="browse-tabs" role="group" aria-label="${video?'Video stage':'Queue agent'}">${tabs.map(([value,label])=>`<button class="filter-chip ${f.stage===value?'selected':''}" data-browse-stage="${value}" aria-pressed="${f.stage===value}">${label}</button>`).join('')}</div><div class="browse-fields"><label>Date range<select data-browse-field="range">${choices([['all','All time'],['today','Today'],['yesterday','Yesterday'],['week','This week'],['month','This month'],['custom','Choose dates']],f.range)}</select></label>${f.range==='custom'?`<label>From (Sri Lanka)<input type="date" data-browse-field="from" value="${esc(f.from)}"></label><label>To (Sri Lanka)<input type="date" data-browse-field="to" value="${esc(f.to)}"></label>`:''}${video?'':`<label>Task status<select data-browse-field="state">${choices(['all','queued','running','completed','failed','skipped','blocked','cancelled','needs_attention'].map(x=>[x,x==='all'?'All statuses':x.replaceAll('_',' ')]),f.state)}</select></label>`}<label>Sort by<select data-browse-field="sort">${choices([['activity','Recent activity'],['latest','Latest added'],['oldest','Oldest added']],f.sort)}</select></label><button class="button small" data-browse-reset>Reset filters</button></div><p class="footnote">${video?'Tabs include every video that completed that stage. Uploaded means publication confirmed. Dates match the selected stage; All videos uses the fetched date.':'Dates match the task’s latest activity: finished, started, or created time.'} This week starts Monday. All times are Asia/Colombo (UTC+05:30).</p></div>`;
}
async function browseFetch(view,offset){
  const f=browseFilters[view];
  return api(view==='library'?'video_list':'task_list',null,'&'+new URLSearchParams({...f,offset}));
}
function browseTable(view){return browseRows.length?(view==='library'?videoCards(browseRows):taskCards(browseRows)):empty('No matches for these filters','Choose a wider date range or another stage.','','');}
function browseFooter(){return `<span>${browseRows.length} of ${browseTotal} shown</span>${browseMore?'<button class="button small" data-browse-more>Load 100 more</button>':'<span>End of results</span>'}`;}
async function renderBrowse(view){
  const generation=++browseGeneration;browseLoading=false;
  const f=browseFilters[view];
  if(f.range==='custom'&&(!f.from||!f.to||f.from>f.to))return browseControls(view)+empty('Choose a date range','Select both dates, with the end on or after the start.');
  const result=await browseFetch(view,0);
  if(generation!==browseGeneration)return '';
  browseRows=result.items;browseOffset=result.items.length;browseTotal=result.total;browseMore=result.has_more;
  return browseControls(view)+panel(view==='library'?'Videos':'Execution queue','Scroll inside the list. Load more for older results. Refresh to see new activity.',`<div class="browse-scroll" id="browse-list" tabindex="0" aria-label="${view==='library'?'Videos':'Tasks'} — scrollable results">${browseTable(view)}</div><div class="browse-footer" id="browse-footer">${browseFooter()}</div>`);
}
function renderErrorReview(e){
  errorSnapshot=e;
  const dismissed=dismissedErrors();
  const tasks=e.tasks.filter(t=>showDismissed||!dismissed.has(errorKey('task',t)));
  const events=e.events.filter(t=>showDismissed||!dismissed.has(errorKey('event',t)));
  const hidden=e.tasks.length+e.events.length-tasks.length-events.length;
  return `<div class="error-review-controls"><div><h2>${tasks.length} tasks need review</h2><p class="footnote">Clearing hides these notices in this browser. It does not retry work, unblock a video, or remove logs. New failures still appear.</p></div><div class="row-actions"><button class="button small" data-errors-clear ${!tasks.length&&!events.length?'disabled':''}>Clear visible errors</button><button class="button small" data-errors-toggle>${showDismissed?'Hide dismissed':'Show dismissed'}</button><button class="button small ghost" data-errors-restore>Restore all</button></div></div><p class="footnote">${hidden} notices hidden from this view. Blocked counts still show unresolved work. Event history below includes the latest 200 warnings and errors.</p>${panel('Blocked work','Check uncertain uploads on YouTube before retrying.',`<div class="browse-scroll" tabindex="0" aria-label="Blocked tasks">${tasks.length?taskCards(tasks):empty('No visible task errors','Dismissed work remains available with Show dismissed.')}</div>`)}${panel('Warnings & errors','Sri Lanka date and time',`<div class="browse-scroll" tabindex="0" aria-label="Warnings and errors">${eventsTable(events)}</div>`)}`;
}
document.addEventListener('change',async event=>{
  const field=event.target.dataset.browseField;if(!field||!browseFilters[page])return;
  browseFilters[page][field]=event.target.value;
  await render();
});
document.addEventListener('click',async event=>{
  const stage=event.target.closest('[data-browse-stage]');
  if(stage&&browseFilters[page]){browseFilters[page].stage=stage.dataset.browseStage;await render();return;}
  if(event.target.closest('[data-browse-reset]')&&browseFilters[page]){Object.assign(browseFilters[page],{stage:'all',state:'all',range:'all',from:'',to:'',sort:'activity'});await render();return;}
  const more=event.target.closest('[data-browse-more]');
  if(more&&!browseLoading){
    const view=page,generation=browseGeneration;browseLoading=true;more.disabled=true;
    try{const result=await browseFetch(view,browseOffset);if(page!==view||generation!==browseGeneration)return;
      const ids=new Set(browseRows.map(r=>String(r.id)));
      browseOffset+=result.items.length;browseRows.push(...result.items.filter(r=>!ids.has(String(r.id))));browseTotal=result.total;browseMore=result.has_more;
      const scroll=$('#browse-list').scrollTop;$('#browse-list').innerHTML=browseTable(view);$('#browse-list').scrollTop=scroll;$('#browse-footer').innerHTML=browseFooter();
    }catch(error){toast(error.message);more.disabled=false;}finally{if(generation===browseGeneration)browseLoading=false;}
    return;
  }
  if(!errorSnapshot||page!=='errors')return;
  try{
    if(event.target.closest('[data-errors-clear]')){
      const keys=dismissedErrors();errorSnapshot.tasks.forEach(t=>keys.add(errorKey('task',t)));errorSnapshot.events.forEach(t=>keys.add(errorKey('event',t)));
      localStorage.setItem(dismissKey,JSON.stringify([...keys].slice(-5000)));showDismissed=false;
    }else if(event.target.closest('[data-errors-toggle]'))showDismissed=!showDismissed;
    else if(event.target.closest('[data-errors-restore]')){localStorage.removeItem(dismissKey);showDismissed=false;}
    else return;
    content.innerHTML=renderErrorReview(errorSnapshot);
  }catch{toast('This browser could not save dismissed errors.');}
});
