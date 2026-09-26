'use strict';
const $ = (s, root = document) => root.querySelector(s);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const csrf = $('meta[name="csrf-token"]').content;
const isAdmin = $('meta[name="access-mode"]')?.content === 'admin';
document.body.classList.toggle('public-view', !isAdmin);
const content = $('#page-content');
let page = '', channels = [], logRows = [], logCursor = 0, logJob = '', logPaused = false, logBusy = false, pageGeneration = 0;
const pages = {
  overview:['Overview','What is running now and what happens next.',null],
  jobs:['Queue','Every fetch, edit and upload task, one at a time.',null],
  library:['Videos','Each video and the stages it has completed.',null],
  channels:['Channels','Source channels to follow and where videos go.','+ Add channel'],
  schedules:['Schedule','Daily fetch and post times in Sri Lanka time.',null],
  errors:['Errors','Blocked tasks, skipped videos and worker failures.',null],
  console:['Console','Live events from the dashboard and workers.',null],
  analytics:['Analytics','Job volume and results from your pipeline.',null],
  settings:['Settings','Connection, workers and account.',null]
};

async function api(action, body, query = '') {
  const response = await fetch(`api.php?action=${encodeURIComponent(action)}${query}`, {
    method:body ? 'POST':'GET', credentials:'same-origin', cache:'no-store',
    headers:body ? {'Content-Type':'application/json','X-CSRF-Token':csrf}:{},
    ...(body ? {body:JSON.stringify(body)}:{})
  });
  const data = await response.json().catch(() => ({error:'The server returned an invalid response.'}));
  if(response.status===401){ location.href='login.php'; throw new Error('Your session expired.'); }
  if(!response.ok) throw new Error(data.error || 'Request failed.');
  return data;
}
function toast(message){ const node=$('#toast');node.textContent=message;node.hidden=false;clearTimeout(toast.timer);toast.timer=setTimeout(()=>node.hidden=true,4500); }
function absoluteDate(value){ if(!value)return '—';const d=new Date(value.includes('T')?value:value.replace(' ','T')+'Z');return Number.isNaN(d.valueOf())?'—':d.toLocaleString('en-GB',{timeZone:'Asia/Colombo',year:'numeric',month:'short',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false})+' SL'; }
// Colour carries meaning only: green done, blue working, amber needs you, red failed.
function relativeTime(value){
  const ms=new Date(value.includes('T')?value:value.replace(' ','T')+'Z').getTime();
  const seconds=Math.round((Date.now()+serverOffset-ms)/1000),amount=Math.abs(seconds);
  if(!Number.isFinite(seconds))return '';
  if(amount<60)return seconds<0?'in less than a minute':'just now';
  const size=amount<3600?60:amount<86400?3600:86400;
  const n=Math.floor(amount/size),unit=size===60?'min':size===3600?'hr':'day';
  const label=`${n} ${unit}${n===1?'':'s'}`;
  return seconds<0?'in '+label:label+' ago';
}
function date(value){
  if(!value)return '—';
  return `<span class="timestamp">${absoluteDate(value)}<small data-relative="${esc(value)}">${relativeTime(value)}</small></span>`;
}
function badge(status){const s=String(status??'');const color=['published','connected','success','enabled','completed','downloaded'].includes(s)?'green':['running','editing','uploading','downloading','verifying','ready','info'].includes(s)?'blue':['needs_attention','paused','warning','stopping'].includes(s)?'amber':['failed','error','blocked','stalled'].includes(s)?'red':'';const label=s.replaceAll('_',' ');return `<span class="badge ${color}"><b></b>${esc(label.charAt(0).toUpperCase()+label.slice(1))}</span>`;}
function empty(title, text, action='', symbol=icon('video')){return `<div class="empty"><span class="empty-symbol">${symbol}</span><h3>${esc(title)}</h3><p>${esc(text)}</p>${action}</div>`;}
function stat(label,value,foot){return `<article class="kpi"><span class="kpi-label">${esc(label)}</span><strong class="kpi-value">${esc(value)}</strong><small>${foot}</small></article>`;}
function panel(title,sub,body,extra=''){return `<section class="panel"><div class="panel-header"><div><h2>${title}</h2>${sub?`<p class="panel-sub">${sub}</p>`:''}</div>${extra}</div>${body}</section>`;}
function jobsTable(rows, compact=false){
  if(!rows.length)return empty('Your first run starts here','Add a source channel, then queue a job. Its progress will appear here.','<button class="button small" data-command="new-job">＋ Queue a job</button>','▷');
  return `<div class="table-wrap"><table><thead><tr><th>Job / Channel</th><th>Status</th>${compact?'':'<th>Stage</th>'}<th>Created</th><th></th></tr></thead><tbody>${rows.map(j=>`<tr><td><strong>#${j.id} · ${esc(j.channel_name)}</strong><small>${esc(j.title||j.handle)}</small></td><td>${badge(j.status)}</td>${compact?'':`<td>${esc(j.stage)}</td>`}<td>${date(j.created_at)}</td><td><div class="table-actions"><button class="button small" data-command="job-log" data-id="${j.id}">Logs</button>${j.status==='queued'?`<button class="button small danger" data-command="cancel-job" data-id="${j.id}">Cancel</button>`:''}</div></td></tr>`).join('')}</tbody></table></div>`;
}
function synced(){ $('#connection-pill').innerHTML='<span class="status-dot"></span>Live';$('#last-sync').textContent='Last synced '+new Date().toLocaleTimeString(undefined,{timeZone:'Asia/Colombo'})+' SL time'; }

async function render(background=false){
  const generation=++pageGeneration;
  const requested=(location.hash.slice(1)||'overview').split('?')[0];
  page=Object.hasOwn(pages,requested)?requested:'overview';
  const [title,description,action]=pages[page];
  document.body.dataset.view=page;
  $('#crumb').textContent=title;$('#page-title').textContent=title;$('#page-description').textContent=description;
  document.title=`${title} · Astra Video`;
  $('#primary-action').hidden=!action||!isAdmin;$('#primary-action').textContent=action||'';
  document.querySelectorAll('[data-page]').forEach(a=>a.classList.toggle('active',a.dataset.page===page));
  if(!background){
    $('.sidebar').classList.remove('open');$('#sidebar-scrim').hidden=true;$('#menu-toggle').setAttribute('aria-expanded','false');
    content.innerHTML='<div class="loading">Loading your workspace…</div>';
  }
  try {
    let html='';
    if(operationPages.includes(page)){
      html=await renderOperations(page);
    } else if(page==='channels'){
      const d=await api('channels');channels=d.items;
      html=channels.length?panel('Source channels',`${channels.length} channel${channels.length===1?'':'s'}`,'<div class="table-wrap"><table class="data"><thead><tr><th>Channel</th><th>Destination</th><th>Preset</th><th class="num">Jobs</th><th>Status</th><th><span class="sr-only">Actions</span></th></tr></thead><tbody>'+channels.map(c=>`<tr><td class="cell-main" data-label="Channel"><div class="agent-cell"><span class="icon-box">${icon('channels')}</span><div><strong>${esc(c.name)}</strong><small>${esc(c.handle)}</small></div></div></td><td data-label="Destination" class="wrap-anywhere">${esc(c.destination||'Not configured')}</td><td data-label="Preset"><span class="agent-tag plain">${esc(c.preset)}</span></td><td class="num" data-label="Jobs">${c.jobs_count}</td><td data-label="Status">${badge(Number(c.enabled)?'enabled':'paused')}</td><td class="actions-cell"><div class="row-actions channel-actions"><button class="button small" data-command="queue-channel" data-id="${c.id}" ${Number(c.enabled)?'':'disabled'}>${icon('fetch')}Queue job</button><button class="button small" data-command="toggle-channel" data-id="${c.id}">${Number(c.enabled)?icon('pause')+'Pause':icon('play')+'Enable'}</button></div></td></tr>`).join('')+'</tbody></table></div>'):panel('Source channels','',empty('Follow your first channel','Add a YouTube @handle and pick an editing preset.',`<button class="button small primary" data-command="new-channel">${icon('plus')}Add channel</button>`,icon('channels')));
    } else if(page==='console'){
      logRows=[];logCursor=0;logPaused=false;
      html=`<section class="panel"><div class="toolbar"><div class="toolbar-group"><input id="log-search" type="search" aria-label="Search logs" placeholder="Search events…"><select id="log-level" aria-label="Filter level"><option value="">All levels</option><option>info</option><option>success</option><option>warning</option><option>error</option></select><input id="log-job" type="number" min="1" aria-label="Job ID filter" placeholder="Job ID" value="${esc(logJob)}"></div><div class="toolbar-group"><button class="button small" id="pause-log">Pause</button><button class="button small" id="download-log">${icon('download')}Export</button></div></div><div id="console-output" class="console" role="log" aria-live="off"><span class="console-empty">Connecting to workspace events…</span></div><div class="console-footer"><span id="console-status">Connecting…</span><label class="checkbox-label"><input type="checkbox" id="autoscroll" checked>Auto-scroll</label></div></section>`;
    } else if(page==='analytics'){
      const d=await api('analytics');const s=d.totals;const completed=Number(s.published)+Number(s.failed);
      html=`<div class="kpi-grid">${stat('Total jobs',s.jobs,'All recorded jobs')}${stat('Published',s.published,'Confirmed on YouTube')}${stat('Success rate',completed?Math.round(Number(s.published)/completed*100)+'%':'—','Published ÷ finished attempts')}${stat('Average time',s.average_seconds?Math.round(s.average_seconds/60)+' min':'—','Queued to published')}</div>`;
      const map=new Map(d.days.map(day=>[day.day,day]));let bars='';const max=Math.max(1,...d.days.map(x=>Number(x.jobs)));
      for(let i=29;i>=0;i--){const day=new Date();day.setTime(day.getTime()+19800000-i*86400000);const key=day.toISOString().slice(0,10);const count=Number(map.get(key)?.jobs||0);bars+=`<div class="chart-bar-wrap"><progress class="chart-bar" value="${count}" max="${max}" title="${key}: ${count} jobs" aria-label="${key}: ${count} jobs"></progress>${i%5===0?`<span class="chart-day">${key.slice(5)}</span>`:''}</div>`;}
      html+=panel('Job volume','Last 30 days · Sri Lanka time',`<div class="analytics-chart">${bars}${Number(s.jobs)?'':'<div class="chart-empty">Your first job will start this chart.</div>'}</div>`);
      html+='<p class="footnote">Views, watch time and subscribers need a separate YouTube Analytics connection.</p>';
    } else if(page==='settings'){
      const d=await api('settings');
      const workers=(d.workers||[]).length?'<div class="table-wrap"><table class="data"><thead><tr><th>Worker</th><th>Agents</th><th>Version</th><th>Last seen</th></tr></thead><tbody>'+d.workers.map(w=>`<tr><td class="cell-main" data-label="Worker"><div class="agent-cell"><span class="icon-box">${icon('server')}</span><strong class="wrap-anywhere">${esc(w.name)}</strong></div></td><td data-label="Agents">${esc(String(w.kind||'').split(',').join(', '))}</td><td data-label="Version">${esc(w.version||'—')}</td><td data-label="Last seen" class="nowrap">${date(w.last_seen)}</td></tr>`).join('')+'</tbody></table></div>':empty('No worker connected','Run start.cmd on your VPS to connect the runner.','',icon('server'));
      html=`<div class="settings-grid">${panel('Workspace','','<dl class="kv"><div><dt>Version</dt><dd>'+esc(d.version)+'</dd></div><div><dt>Database</dt><dd>'+badge('connected')+'</dd></div><div><dt>Dashboard</dt><dd>'+badge('connected')+'</dd></div><div><dt>Display time</dt><dd>Sri Lanka · UTC+05:30</dd></div></dl><p class="panel-text">Channels, schedules, jobs and events are stored in MySQL. Media files stay on the VPS.</p>')}${panel('VPS workers','Machines that run the agents',workers)}${panel('Automation setup','Steps to run the pipeline end to end','<ol class="setup-list"><li>Install the VPS runner and keep start.cmd running.</li><li>Load and pair the Chrome extension.</li><li>Test download, editing and upload once.</li><li>Turn on the schedule after a full test.</li></ol><p class="panel-text">The existing Task Scheduler tasks are unchanged.</p>')}${panel('Account security','Change the administrator password','<form id="password-form" class="form-panel"><label>Current password<input name="current" type="password" autocomplete="current-password" required></label><label>New password<input name="password" type="password" minlength="14" autocomplete="new-password" required></label><p class="form-hint">At least 14 characters.</p><button type="submit" class="button primary">Update password</button></form>')}</div>`;
    }
    if(generation!==pageGeneration)return;
    content.innerHTML=html;synced();if(operationPages.includes(page))bindOperations();
    if(!isAdmin){
      content.querySelectorAll('[data-command]').forEach(button=>{if(!['job-log','refresh'].includes(button.dataset.command))button.remove();});
      $('#password-form')?.closest('.panel')?.remove();
    }
    if(page==='console'){await pollLogs();$('#log-search').addEventListener('input',paintLogs);$('#log-level').addEventListener('change',paintLogs);$('#log-job').addEventListener('change',()=>{logJob=$('#log-job').value;logRows=[];logCursor=0;pollLogs();});$('#pause-log').onclick=()=>{logPaused=!logPaused;$('#pause-log').textContent=logPaused?'Resume':'Pause';$('#console-status').textContent=logPaused?'Paused':'Live · checks every 2s';};$('#download-log').onclick=downloadLogs;}
    if(page==='settings'&&isAdmin)$('#password-form').onsubmit=async e=>{e.preventDefault();try{await api('password_change',Object.fromEntries(new FormData(e.target)));e.target.reset();toast('Password updated.');}catch(error){toast(error.message);}};
  } catch(error){if(generation!==pageGeneration)return;$('#connection-pill').innerHTML='<span class="status-dot red"></span>Connection issue';content.innerHTML=`<div class="error" role="alert">${esc(error.message)} <button class="button small" data-command="refresh">Try again</button></div>`;}
}

async function pollLogs(){
  if(page!=='console'||logPaused||document.hidden||logBusy)return;
  logBusy=true;const job=logJob;const generation=pageGeneration;
  try{const d=await api('logs',null,`&after=${logCursor}&job=${encodeURIComponent(job)}`);if(page!=='console'||job!==logJob||generation!==pageGeneration)return;
    for(const row of d.items){if(Number(row.id)>logCursor){logRows.push(row);logCursor=Number(row.id);}}
    logRows=logRows.slice(-2000);paintLogs();$('#console-status').textContent='Live · checks every 2s';synced();
  }catch(error){if($('#console-status'))$('#console-status').textContent='Reconnecting · '+error.message;}finally{logBusy=false;}
}
function paintLogs(){const node=$('#console-output');if(!node)return;const search=($('#log-search')?.value||'').toLowerCase();const level=$('#log-level')?.value||'';const filtered=logRows.filter(r=>(!level||r.level===level)&&`${r.message} ${r.source}`.toLowerCase().includes(search));node.innerHTML=filtered.length?filtered.map(r=>`<div class="console-line"><span class="console-time">${esc(slClock(r.created_at))}</span><span class="console-job">${r.job_id?'#'+esc(r.job_id):'—'}</span><span class="console-source">${esc(r.source)}</span><span class="console-level ${esc(r.level)}">${esc(r.level)}</span><span class="console-message">${esc(r.message)}</span></div>`).join(''):'<span class="console-empty">No matching events. New workspace events will appear here.</span>';if($('#autoscroll')?.checked)node.scrollTop=node.scrollHeight;}
function downloadLogs(){const text=logRows.map(r=>`${absoluteDate(r.created_at)}\t${r.job_id||'system'}\t${r.source}\t${r.level}\t${r.message}`).join('\n');const url=URL.createObjectURL(new Blob([text],{type:'text/plain;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='astra-console-'+new Date().toISOString().slice(0,10)+'.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}

async function modal(type){
  if(!isAdmin)return;
  try{
    if(type!=='channel'){channels=(await api('channels')).items.filter(c=>Number(c.enabled));if(!channels.length){toast('Add an enabled channel first.');type='channel';}}
    const titles={job:'Queue a new job',channel:'Add a source channel',schedule:'Create a schedule'};$('#modal-title').textContent=titles[type];$('#modal-error').hidden=true;
    const options=channels.map(c=>`<option value="${c.id}">${esc(c.name)} · ${esc(c.handle)}</option>`).join('');
    $('#modal-fields').innerHTML=type==='channel'?'<label>Channel name<input name="name" placeholder="Clips Edge" maxlength="120" required></label><label>YouTube handle<input name="handle" placeholder="@Clips_Edge" required></label><label>Destination channel<input name="destination" placeholder="Your destination channel name or ID" maxlength="120"></label><label>Editing preset<select name="preset">'+['vivid','punch','warm','cool','bright','fade','cinematic','clarity','bw','vignette','none'].map(x=>`<option>${x}</option>`).join('')+'</select></label><p class="form-hint">The fetch agent checks this channel for new videos.</p>':`<label>Source channel<select name="channel_id" required>${options}</select></label>${type==='schedule'?'<label>Check every (minutes)<input name="interval_minutes" type="number" min="5" max="43200" value="60" required></label>':''}<p class="form-hint">${type==='schedule'?'The schedule will be stored and can be paused. It will not execute until the VPS runner is connected.':'The job will enter the queue and wait for the VPS runner and Chrome extension.'}</p>`;
    $('#modal-submit').textContent=type==='job'?'Queue job':'Save';$('#modal').showModal();
    $('#modal-form').onsubmit=async e=>{e.preventDefault();const submit=$('#modal-submit');submit.disabled=true;try{const payload=Object.fromEntries(new FormData(e.target));const result=await api({channel:'channel_save',schedule:'schedule_save',job:'queue'}[type],payload);$('#modal').close();toast(type==='job'?`Job #${result.id} is queued.`:'Saved to your workspace.');await render();}catch(error){$('#modal-error').textContent=error.message;$('#modal-error').hidden=false;}finally{submit.disabled=false;}};
  }catch(error){toast(error.message);}
}
$('#primary-action').onclick=()=>modal(page==='channels'?'channel':page==='schedules'?'schedule':'job');
$('#modal-close').onclick=$('#modal-cancel').onclick=()=>$('#modal').close();
function closeMenu(){ $('.sidebar').classList.remove('open');$('#sidebar-scrim').hidden=true;$('#menu-toggle').setAttribute('aria-expanded','false'); }
$('#menu-toggle').onclick=()=>{const open=$('.sidebar').classList.toggle('open');$('#sidebar-scrim').hidden=!open;$('#menu-toggle').setAttribute('aria-expanded',String(open));};
$('#sidebar-scrim').onclick=closeMenu;
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeMenu();});
$('#refresh').onclick=()=>render();
if($('#logout'))$('#logout').onclick=async()=>{try{await api('logout',{});location.href='index.php';}catch(error){toast(error.message);}};
content.addEventListener('click',async e=>{const button=e.target.closest('[data-command]');if(!button)return;const cmd=button.dataset.command;const id=Number(button.dataset.id);try{
  if(cmd==='new-job')return modal('job');if(cmd==='new-channel')return modal('channel');if(cmd==='new-schedule')return modal('schedule');if(cmd==='refresh')return render();
  if(cmd==='job-log'){logJob=String(id);location.hash='console';return;}
  button.disabled=true;
  if(cmd==='queue-channel'){const d=await api('queue',{channel_id:id});toast(`Job #${d.id} is queued.`);}
  if(cmd==='toggle-channel')await api('channel_toggle',{id});if(cmd==='toggle-schedule')await api('schedule_toggle',{id});if(cmd==='cancel-job'){await api('job_cancel',{id});toast('Queued job cancelled.');}
  await render();
}catch(error){toast(error.message);button.disabled=false;}});
window.addEventListener('hashchange',()=>render());
setInterval(pollLogs,2000);

render();
