'use strict';
const $ = (s, root = document) => root.querySelector(s);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const csrf = $('meta[name="csrf-token"]').content;
const isAdmin = $('meta[name="access-mode"]')?.content === 'admin';
document.body.classList.toggle('public-view', !isAdmin);
const content = $('#page-content');
let page = '', channels = [], logRows = [], logCursor = 0, logJob = '', logPaused = false, logBusy = false, pageGeneration = 0;
const pages = {
  overview:['Overview','Everything happening across your video pipeline.','＋ New job'],
  jobs:['Jobs','Track every run, from discovery to publication.','＋ New job'],
  library:['Video library','Your source videos, finished edits and published Shorts.',null],
  channels:['Channels','Choose what to follow and where your videos go.','＋ Add channel'],
  schedules:['Schedules','Set a rhythm for your content. All times are shown in UTC.','＋ Add schedule'],
  console:['Live console','A single view of events across your workspace.',null],
  analytics:['Analytics','Real numbers from your video operations.',null],
  settings:['Settings','Your workspace connection, account and deployment status.',null]
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
function date(value){ if(!value)return '—';const d=new Date(value.includes('T')?value:value.replace(' ','T')+'Z');return Number.isNaN(d.valueOf())?'—':d.toLocaleString(undefined,{timeZone:'UTC',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}); }
function badge(status){const color=['published','connected','success','enabled'].includes(status)?'green':['queued','ready','needs_attention'].includes(status)?'amber':['failed','error'].includes(status)?'red':'';return `<span class="badge ${color}">${esc(status.replaceAll('_',' '))}</span>`;}
function empty(title, text, action='', symbol='▤'){return `<div class="empty"><span class="empty-symbol">${symbol}</span><h3>${esc(title)}</h3><p>${esc(text)}</p>${action}</div>`;}
function stat(label,value,foot,icon='◫'){return `<article class="stat"><div class="stat-top"><span>${esc(label)}</span><span class="stat-icon">${icon}</span></div><div class="stat-value">${esc(value)}</div><div class="stat-bottom">${foot}</div></article>`;}
function panel(title,sub,body,extra=''){return `<section class="panel"><div class="panel-header"><div><h2>${title}</h2>${sub?`<p class="panel-sub">${sub}</p>`:''}</div>${extra}</div>${body}</section>`;}
function jobsTable(rows, compact=false){
  if(!rows.length)return empty('Your first run starts here','Add a source channel, then queue a job. Its progress will appear here.','<button class="button small" data-command="new-job">＋ Queue a job</button>','▷');
  return `<div class="table-wrap"><table><thead><tr><th>Job / Channel</th><th>Status</th>${compact?'':'<th>Stage</th>'}<th>Created</th><th></th></tr></thead><tbody>${rows.map(j=>`<tr><td><strong>#${j.id} · ${esc(j.channel_name)}</strong><small>${esc(j.title||j.handle)}</small></td><td>${badge(j.status)}</td>${compact?'':`<td>${esc(j.stage)}</td>`}<td>${date(j.created_at)}</td><td><div class="table-actions"><button class="button small" data-command="job-log" data-id="${j.id}">Logs</button>${j.status==='queued'?`<button class="button small danger" data-command="cancel-job" data-id="${j.id}">Cancel</button>`:''}</div></td></tr>`).join('')}</tbody></table></div>`;
}
function synced(){ $('#connection-pill').innerHTML='<span class="status-dot"></span> Connected';$('#last-sync').textContent='Last synced '+new Date().toLocaleTimeString(undefined,{timeZone:'UTC'})+' UTC'; }

async function render(){
  const generation=++pageGeneration;
  const requested=(location.hash.slice(1)||'overview').split('?')[0];
  page=Object.hasOwn(pages,requested)?requested:'overview';
  const [title,description,action]=pages[page];
  $('#crumb').textContent=title;$('#page-title').textContent=title;$('#page-description').textContent=description;
  document.title=`${title} · Astra Video`;
  $('#primary-action').hidden=!action||!isAdmin;$('#primary-action').textContent=action||'';
  document.querySelectorAll('[data-page]').forEach(a=>a.classList.toggle('active',a.dataset.page===page));
  $('.sidebar').classList.remove('open');
  $('#sidebar-scrim').hidden=true;$('#menu-toggle').setAttribute('aria-expanded','false');
  content.innerHTML='<div class="loading">Loading your workspace…</div>';
  try {
    let html='';
    if(page==='overview'){
      const d=await api('overview');const s=d.stats;
      $('#nav-queue').textContent=s.queued;
      html=`<div class="stats-grid">${stat('Published today',s.published_today,'Completed publications · UTC','↗')}${stat('In the queue',s.queued,'Waiting for a worker','≡')}${stat('Active channels',s.channels,'Sources you are following','◎')}${stat('Needs attention',s.failed,'Failed or unresolved jobs','!')}</div>`;
      const steps='<div class="pipeline">'+[['◎','Discover','Find new Shorts'],['↓','Download','Save source video'],['✧','Edit','Rewrite & render'],['↗','Publish','Upload to YouTube']].map(([icon,t,sub])=>`<div class="pipeline-step"><div class="step-icon">${icon}</div><strong>${t}</strong><small>${sub}</small></div>`).join('')+'</div><div class="pipeline-note"><span class="status-dot amber"></span> Pipeline is waiting for the VPS runner and extension.</div>';
      const health='<div class="health-body">'+[['◫','Dashboard','connected'],['▥','MySQL database','connected'],['⌘','VPS runner','not connected'],['◎','Chrome extension','not connected']].map(([i,t,s])=>`<div class="health-row"><span><span class="health-icon">${i}</span>${t}</span>${badge(s)}</div>`).join('')+'</div>';
      const events=d.events.length?'<div class="activity-list">'+d.events.slice(0,5).map(e=>`<div class="activity"><span class="activity-dot"></span><div><p>${esc(e.message)}</p><small>${date(e.created_at)} · ${esc(e.source)}</small></div></div>`).join('')+'</div>':empty('Nothing to report yet','Workspace activity will appear as you add channels and jobs.');
      html+=`<div class="dashboard-grid"><div>${panel('Your pipeline','One connected workflow, four stages',steps,'<span class="badge">Not connected</span>')}${panel('Recent jobs','The latest runs in your workspace',jobsTable(d.jobs,true),'<a class="text-link" href="#jobs">View all jobs →</a>')}</div><div class="right-column">${panel('System health','Connections that power your pipeline',health)}${panel('Activity','Latest workspace events',events,'<a class="text-link" href="#console">Open console ↗</a>')}</div></div>`;
    } else if(page==='jobs'){
      const d=await api('jobs');html=panel('All jobs',`${d.items.length} recent jobs`,jobsTable(d.items));
    } else if(page==='channels'){
      const d=await api('channels');channels=d.items;
      html=channels.length?'<div class="cards-grid">'+channels.map(c=>`<article class="panel channel-card"><div class="channel-head"><span class="channel-avatar">◎</span>${badge(Number(c.enabled)?'enabled':'paused')}</div><h3>${esc(c.name)}</h3><p class="muted">${esc(c.handle)}</p><div class="channel-details"><span>Destination <b>${esc(c.destination||'Not configured')}</b></span><span>Editing preset <b>${esc(c.preset)}</b></span><span>Jobs <b>${c.jobs_count}</b></span><span>Publishing <b>Manual approval</b></span></div><div class="channel-actions"><button class="button small" data-command="queue-channel" data-id="${c.id}" ${Number(c.enabled)?'':'disabled'}>Queue job</button><button class="button small" data-command="toggle-channel" data-id="${c.id}">${Number(c.enabled)?'Pause':'Enable'}</button></div></article>`).join('')+'</div>':panel('Source channels','Build your content sources',empty('Follow your first channel','Add a YouTube @handle and select an editing preset.','<button class="button small" data-command="new-channel">＋ Add channel</button>','◎'));
    } else if(page==='schedules'){
      const d=await api('schedules');html=panel('Recurring runs','Schedules are stored. The VPS runner is required to execute them.',d.items.length?`<div class="table-wrap"><table><thead><tr><th>Channel</th><th>Frequency</th><th>Status</th><th>Next due · UTC</th><th></th></tr></thead><tbody>${d.items.map(s=>`<tr><td><strong>${esc(s.channel_name)}</strong><small>${esc(s.handle)}</small></td><td>Every ${s.interval_minutes} min</td><td>${badge(Number(s.enabled)?'enabled':'paused')}</td><td>${date(s.next_run)}</td><td><button class="button small" data-command="toggle-schedule" data-id="${s.id}">${Number(s.enabled)?'Pause':'Enable'}</button></td></tr>`).join('')}</tbody></table></div>`:empty('A consistent rhythm starts here','Choose a channel and how often it should be checked.','<button class="button small" data-command="new-schedule">＋ Add schedule</button>','◷'));
    } else if(page==='library'){
      const d=await api('jobs');const videos=d.items.filter(j=>j.source_video_id);
      html=panel('Processed videos','Video metadata appears when the runner reports a discovered source.',videos.length?`<div class="table-wrap"><table><thead><tr><th>Video</th><th>Channel</th><th>Status</th><th>Published</th></tr></thead><tbody>${videos.map(v=>`<tr><td><strong>${esc(v.title||v.original_title||v.source_video_id)}</strong><small>${esc(v.source_video_id)}</small></td><td>${esc(v.channel_name)}</td><td>${badge(v.status)}</td><td>${v.published_url && /^https:\/\/(www\.)?youtube\.com\//.test(v.published_url)?`<a class="text-link" href="${esc(v.published_url)}" target="_blank" rel="noopener">Open video ↗</a>`:'—'}</td></tr>`).join('')}</tbody></table></div>`:empty('Your video library is clear','Discovered and processed videos will appear here once automation is connected.','','▤'));
    } else if(page==='console'){
      logRows=[];logCursor=0;logPaused=false;
      html=`<section class="panel"><div class="toolbar"><div class="toolbar-group"><input id="log-search" aria-label="Search logs" placeholder="Search console…"><select id="log-level" aria-label="Filter level"><option value="">All levels</option><option>info</option><option>success</option><option>warning</option><option>error</option></select><input id="log-job" type="number" min="1" aria-label="Job ID filter" placeholder="Job ID" value="${esc(logJob)}"></div><div class="toolbar-group"><button class="button small" id="pause-log">Pause</button><button class="button small" id="download-log">↓ Export</button></div></div><div id="console-output" class="console" role="log" aria-live="off"><span class="console-empty">Connecting to workspace events…</span></div><div class="console-footer"><span id="console-status">● Connecting</span><label class="checkbox-label"><input type="checkbox" id="autoscroll" checked>Auto-scroll</label></div></section>`;
    } else if(page==='analytics'){
      const d=await api('analytics');const s=d.totals;const completed=Number(s.published)+Number(s.failed);
      html=`<div class="stats-grid">${stat('Total jobs',s.jobs,'All recorded jobs','≡')}${stat('Published',s.published,'Confirmed publications','↗')}${stat('Success rate',completed?Math.round(Number(s.published)/completed*100)+'%':'—','Published / completed attempts','◫')}${stat('Average duration',s.average_seconds?Math.round(s.average_seconds/60)+' min':'—','From queued to published','◷')}</div>`;
      const map=new Map(d.days.map(day=>[day.day,day]));let bars='';const max=Math.max(1,...d.days.map(x=>Number(x.jobs)));
      for(let i=29;i>=0;i--){const day=new Date();day.setUTCDate(day.getUTCDate()-i);const key=day.toISOString().slice(0,10);const count=Number(map.get(key)?.jobs||0);bars+=`<div class="chart-bar-wrap"><progress class="chart-bar" value="${count}" max="${max}" title="${key}: ${count} jobs" aria-label="${key}: ${count} jobs"></progress>${i%5===0?`<span class="chart-day">${key.slice(5)}</span>`:''}</div>`;}
      html+=panel('Job volume','Last 30 days · UTC',`<div class="analytics-chart">${bars}${Number(s.jobs)?'':'<div class="chart-empty">Your first job will start this chart.</div>'}</div>`);
      html+='<div class="notice analytics-notice"><span class="notice-icon">i</span><div><strong>Operational analytics</strong><p>YouTube views, watch time and subscriber metrics need a separate authorized YouTube Analytics integration.</p></div></div>';
    } else if(page==='settings'){
      const d=await api('settings');
      html=`<div class="settings-grid">${panel('Workspace','Deployment and connection information','<div class="settings-section"><div class="health-row"><span>Version</span>'+badge(d.version)+'</div><div class="health-row"><span>Database</span>'+badge('connected')+'</div><div class="health-row"><span>Time storage & display</span><span>UTC</span></div><div class="health-row"><span>Dashboard</span>'+badge('connected')+'</div><p>Your channels, schedules, jobs and console events are stored in MySQL. Media files will remain on the VPS.</p></div>')}${panel('Automation setup','Pending implementation and VPS connection','<div class="settings-section"><p>This release provides the hosted dashboard and database. It does not execute scheduled jobs or operate Chrome yet.</p><ol class="setup-list"><li>Build and install the persistent VPS runner.</li><li>Load and pair the Chrome extension.</li><li>Validate download, editing and upload.</li><li>Enable scheduling after an end-to-end test.</li></ol><p>The existing Task Scheduler tasks have not been changed.</p></div>')}${panel('Account security','Update your administrator password','<form id="password-form" class="settings-section"><label>Current password<input name="current" type="password" autocomplete="current-password" required></label><label>New password<input name="password" type="password" minlength="14" autocomplete="new-password" required></label><button type="submit" class="button primary">Update password</button></form>')}</div>`;
    }
    if(generation!==pageGeneration)return;
    content.innerHTML=html;synced();
    if(!isAdmin){
      content.querySelectorAll('[data-command]').forEach(button=>{if(!['job-log','refresh'].includes(button.dataset.command))button.remove();});
      $('#password-form')?.closest('.panel')?.remove();
    }
    if(page==='console'){await pollLogs();$('#log-search').addEventListener('input',paintLogs);$('#log-level').addEventListener('change',paintLogs);$('#log-job').addEventListener('change',()=>{logJob=$('#log-job').value;logRows=[];logCursor=0;pollLogs();});$('#pause-log').onclick=()=>{logPaused=!logPaused;$('#pause-log').textContent=logPaused?'Resume':'Pause';$('#console-status').textContent=logPaused?'Ⅱ Paused':'● Connected · checks every 2s';};$('#download-log').onclick=downloadLogs;}
    if(page==='settings'&&isAdmin)$('#password-form').onsubmit=async e=>{e.preventDefault();try{await api('password_change',Object.fromEntries(new FormData(e.target)));e.target.reset();toast('Password updated.');}catch(error){toast(error.message);}};
  } catch(error){if(generation!==pageGeneration)return;$('#connection-pill').textContent='Connection issue';content.innerHTML=`<div class="error" role="alert">${esc(error.message)} <button class="button small" data-command="refresh">Try again</button></div>`;}
}

async function pollLogs(){
  if(page!=='console'||logPaused||document.hidden||logBusy)return;
  logBusy=true;const job=logJob;const generation=pageGeneration;
  try{const d=await api('logs',null,`&after=${logCursor}&job=${encodeURIComponent(job)}`);if(page!=='console'||job!==logJob||generation!==pageGeneration)return;
    for(const row of d.items){if(Number(row.id)>logCursor){logRows.push(row);logCursor=Number(row.id);}}
    logRows=logRows.slice(-2000);paintLogs();$('#console-status').textContent='● Connected · checks every 2s';synced();
  }catch(error){if($('#console-status'))$('#console-status').textContent='Reconnecting · '+error.message;}finally{logBusy=false;}
}
function paintLogs(){const node=$('#console-output');if(!node)return;const search=($('#log-search')?.value||'').toLowerCase();const level=$('#log-level')?.value||'';const filtered=logRows.filter(r=>(!level||r.level===level)&&`${r.message} ${r.source}`.toLowerCase().includes(search));node.innerHTML=filtered.length?filtered.map(r=>`<div class="console-line"><span class="console-time">${esc(r.created_at.slice(11))}</span><span class="console-time">${r.job_id?'#'+r.job_id:'system'}</span><span class="console-source">${esc(r.source)}</span><span class="console-level ${esc(r.level)}">${esc(r.level.toUpperCase())}</span><span class="console-message">${esc(r.message)}</span></div>`).join(''):'<span class="console-empty">No matching events. New workspace events will appear here.</span>';if($('#autoscroll')?.checked)node.scrollTop=node.scrollHeight;}
function downloadLogs(){const text=logRows.map(r=>`${r.created_at} UTC\t${r.job_id||'system'}\t${r.source}\t${r.level}\t${r.message}`).join('\n');const url=URL.createObjectURL(new Blob([text],{type:'text/plain;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='astra-console-'+new Date().toISOString().slice(0,10)+'.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}

async function modal(type){
  if(!isAdmin)return;
  try{
    if(type!=='channel'){channels=(await api('channels')).items.filter(c=>Number(c.enabled));if(!channels.length){toast('Add an enabled channel first.');type='channel';}}
    const titles={job:'Queue a new job',channel:'Add a source channel',schedule:'Create a schedule'};$('#modal-title').textContent=titles[type];$('#modal-error').hidden=true;
    const options=channels.map(c=>`<option value="${c.id}">${esc(c.name)} · ${esc(c.handle)}</option>`).join('');
    $('#modal-fields').innerHTML=type==='channel'?'<label>Channel name<input name="name" placeholder="Clips Edge" maxlength="120" required></label><label>YouTube handle<input name="handle" placeholder="@Clips_Edge" required></label><label>Destination channel<input name="destination" placeholder="Your destination channel name or ID" maxlength="120"></label><label>Editing preset<select name="preset">'+['vivid','punch','warm','cool','bright','fade','cinematic','clarity','bw','vignette','none'].map(x=>`<option>${x}</option>`).join('')+'</select></label><p class="form-hint">Automatic publishing is off. This release saves channel configuration only.</p>':`<label>Source channel<select name="channel_id" required>${options}</select></label>${type==='schedule'?'<label>Check every (minutes)<input name="interval_minutes" type="number" min="5" max="43200" value="60" required></label>':''}<p class="form-hint">${type==='schedule'?'The schedule will be stored and can be paused. It will not execute until the VPS runner is connected.':'The job will enter the queue and wait for the VPS runner and Chrome extension.'}</p>`;
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
$('#refresh').onclick=render;
if($('#logout'))$('#logout').onclick=async()=>{try{await api('logout',{});location.href='index.php';}catch(error){toast(error.message);}};
content.addEventListener('click',async e=>{const button=e.target.closest('[data-command]');if(!button)return;const cmd=button.dataset.command;const id=Number(button.dataset.id);try{
  if(cmd==='new-job')return modal('job');if(cmd==='new-channel')return modal('channel');if(cmd==='new-schedule')return modal('schedule');if(cmd==='refresh')return render();
  if(cmd==='job-log'){logJob=String(id);location.hash='console';return;}
  button.disabled=true;
  if(cmd==='queue-channel'){const d=await api('queue',{channel_id:id});toast(`Job #${d.id} is queued.`);}
  if(cmd==='toggle-channel')await api('channel_toggle',{id});if(cmd==='toggle-schedule')await api('schedule_toggle',{id});if(cmd==='cancel-job'){await api('job_cancel',{id});toast('Queued job cancelled.');}
  await render();
}catch(error){toast(error.message);button.disabled=false;}});
window.addEventListener('hashchange',render);
setInterval(pollLogs,2000);
setInterval(()=>{if(!document.hidden&&page==='overview'&&!$('#modal').open)render();},30000);
render();
