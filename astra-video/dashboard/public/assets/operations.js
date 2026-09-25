'use strict';
let operationsState = null;
let serverOffset = 0;
// Inline SVG icons: the CSP blocks icon fonts and external images.
const ICONS = {
  overview:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  queue:'<path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01"/>',
  video:'<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="m10 9.5 4.5 2.5-4.5 2.5z"/>',
  alert:'<path d="M10.3 4 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 4a2 2 0 0 0-3.4 0z"/><path d="M12 9v4.5M12 17.5h.01"/>',
  channels:'<rect x="2.5" y="7" width="19" height="13.5" rx="2.5"/><path d="m16.5 2.5-4.5 4.5-4.5-4.5"/>',
  clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  console:'<path d="m5 17 5-5-5-5M12.5 19H19"/>',
  analytics:'<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  settings:'<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1.5 14h5M9.5 8h5M17.5 16h5"/>',
  fetch:'<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>',
  editor:'<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4 8.1 15.9M14.5 14.5 20 20M8.1 8.1 12 12"/>',
  uploader:'<path d="M12 21V9M7 14l5-5 5 5M5 3h14"/>',
  play:'<path d="M7 4.5v15l12-7.5z"/>',
  pause:'<path d="M8 5v14M16 5v14"/>',
  stop:'<rect x="6" y="6" width="12" height="12" rx="1.5"/>',
  refresh:'<path d="M20.5 12a8.5 8.5 0 1 1-2.5-6L20.5 8.5"/><path d="M20.5 3.5v5h-5"/>',
  retry:'<path d="M3.5 12a8.5 8.5 0 1 0 2.5-6L3.5 8.5"/><path d="M3.5 3.5v5h5"/>',
  menu:'<path d="M3 6h18M3 12h18M3 18h18"/>',
  x:'<path d="M18 6 6 18M6 6l12 12"/>',
  check:'<path d="M20 6 9 17l-5-5"/>',
  external:'<path d="M7 17 17 7M8 7h9v9"/>',
  logout:'<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
  lock:'<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  log:'<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8M8 17h5"/>',
  arrow:'<path d="M5 12h14M13 6l6 6-6 6"/>',
  skip:'<path d="m5 5 9 7-9 7zM18 5v14"/>',
  edit:'<path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  download:'<path d="M12 3v12M7 10l5 5 5-5M4 21h16"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',
  server:'<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/>'
};
function icon(name){ return `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]||''}</svg>`; }
document.querySelectorAll('[data-icon]').forEach(node=>{node.innerHTML=icon(node.dataset.icon);});

const AGENT_INFO = {
  fetch: {name:'Fetch', icon:'fetch', detail:'Latest 5 videos, skips duplicates', run:'Fetch now'},
  editor: {name:'Editor', icon:'editor', detail:'Edits every new video', run:'Edit new videos'},
  uploader: {name:'Upload', icon:'uploader', detail:'Up to 3 posts a day', run:'Upload now'}
};
const STATE_LABEL = {waiting:'Ready', offline:'Offline', paused:'Paused', running:'Running', stopping:'Stopping', stalled:'Stalled'};
const operationPages = ['overview','jobs','schedules','library','errors'];
const utcDate = value => new Date(value && (value.includes('T') ? value : value.replace(' ','T')+'Z'));
const slClock = value => utcDate(value).toLocaleTimeString('en-GB',{timeZone:'Asia/Colombo',hour:'2-digit',minute:'2-digit',second:'2-digit'});
const slDay = value => utcDate(value).toLocaleDateString('en-GB',{timeZone:'Asia/Colombo',day:'numeric',month:'short'});

// Public visitors get no controls at all rather than a wall of disabled buttons.
function opButton(action,text,extra='',kind='') {
  if(!isAdmin) return '';
  return `<button class="button ${kind}" data-op="${action}" ${extra}>${text}</button>`;
}
function duration(until) {
  const seconds=Math.max(0,Math.ceil((utcDate(until).getTime()-Date.now()-serverOffset)/1000));
  if(!Number.isFinite(seconds)) return '—';
  if(seconds===0) return 'Due now';
  const h=Math.floor(seconds/3600),m=Math.floor(seconds%3600/60),s=seconds%60;
  return `${String(h).padStart(2,'0')}<i>h</i> ${String(m).padStart(2,'0')}<i>m</i> ${String(s).padStart(2,'0')}<i>s</i>`;
}
function tickClocks(){
  document.querySelectorAll('[data-countdown]').forEach(node=>{if(node.dataset.countdown)node.innerHTML=duration(node.dataset.countdown);});
  document.querySelectorAll('[data-sl-clock]').forEach(node=>node.textContent=new Date(Date.now()+serverOffset).toLocaleTimeString('en-GB',{timeZone:'Asia/Colombo'}));
}
setInterval(tickClocks,1000);

function pipelineButton(d){
  if(!isAdmin) return `<a href="login.php" class="button">${icon('lock')}Sign in to control</a>`;
  return d.paused?opButton('pipeline-start',icon('play')+'Start pipeline','','primary'):opButton('pipeline-stop',icon('stop')+'Stop pipeline','','danger');
}
function controlBar(d){
  const tone=d.paused||!d.online?'amber':'';
  return `<div class="controlbar"><div class="controlbar-status"><span class="status-dot ${tone}"></span><strong>${d.paused?'Pipeline paused':d.online?'Pipeline on':'Pipeline on · waiting for VPS'}</strong><span class="controlbar-note">One task runs at a time</span></div>${pipelineButton(d)}</div>`;
}

function agentNow(a,d){
  const isEditor=a.name==='editor';
  if(['running','stopping','stalled'].includes(a.state)&&d.active){
    const editing=isEditor&&a.state==='running';
    const minutes=Math.max(0,Math.floor((Date.now()+serverOffset-utcDate(d.active.started_at))/60000));
    const main=a.state==='running'?(editing?'Editing…':a.progress+'%'):a.state==='stopping'?'Stopping…':'Needs attention';
    return `<div class="now"><strong>${main}</strong><small>Task #${d.active.id} · ${minutes} min elapsed</small><small>Heartbeat ${Number(d.active.heartbeat_age)}s ago</small>${editing?'':`<progress class="bar" value="${a.progress}" max="100"></progress>`}</div>`;
  }
  if(isEditor)return a.queued?`<div class="now"><strong>${a.queued} <i>queued</i></strong><small>Ready to edit</small></div>`:'<span class="muted-text">After the next download</span>';
  if(!a.next_run)return '<span class="muted-text">Not scheduled</span>';
  return `<div class="now"><strong class="countdown" data-countdown="${esc(a.next_run)}">${duration(a.next_run)}</strong><small>${date(a.next_run)}</small></div>`;
}

function agentsTable(d){
  return `<div class="table-wrap"><table class="data agents-table"><thead><tr><th>Agent</th><th>Status</th><th>Next run</th><th>Daily times</th><th class="col-last">Last finished</th>${isAdmin?'<th><span class="sr-only">Actions</span></th>':''}</tr></thead><tbody>${d.agents.map(a=>{
    const info=AGENT_INFO[a.name],isEditor=a.name==='editor';
    const note=a.state==='offline'?'Worker not connected':a.state==='paused'?'Next slot shown as planned':a.state==='stalled'?'Heartbeat lost · slot stays locked':a.state==='stopping'?'Finishing current work':a.state==='waiting'&&d.active?'Waits for the active task':a.name==='uploader'&&a.state==='waiting'&&!d.ready?'No edited video ready yet':'';
    const toggle=opButton('agent-toggle',Number(a.enabled)?icon('pause')+'Pause':icon('play')+'Enable',`data-agent="${a.name}" data-next="${Number(a.enabled)?'stop':'start'}"`,'small');
    return `<tr class="${a.state==='running'?'is-running':''}"><td class="cell-main" data-label="Agent"><div class="agent-cell"><span class="icon-box">${icon(info.icon)}</span><div><strong>${info.name}</strong><small>${info.detail}</small></div></div></td><td data-label="Status"><div><span class="state state-${esc(a.state)}"><b></b>${STATE_LABEL[a.state]||esc(a.state)}</span>${note?`<small class="cell-note">${note}</small>`:''}</div></td><td data-label="Next run">${agentNow(a,d)}</td><td data-label="Daily times">${isEditor?'<span class="muted-text">After each download</span>':`<div class="slots">${a.display_slots.map(t=>`<span class="slot">${esc(t)}</span>`).join('')}</div>`}</td><td data-label="Last finished" class="nowrap col-last">${a.last_finished?date(a.last_finished):'<span class="muted-text">Not run yet</span>'}</td>${isAdmin?`<td class="actions-cell"><div class="row-actions">${toggle}${opButton('run',info.run,`data-agent="${a.name}"`,'small')}</div></td>`:''}</tr>`;
  }).join('')}</tbody></table></div>`;
}

function workspaceStatus(d){
  const active=d.agents.find(a=>['running','stopping','stalled'].includes(a.state));
  const title=active?.state==='stalled'?'Worker needs attention':active?.state==='stopping'?'Finishing the stop request':d.paused?'Automation is paused':!d.online?'Connect your VPS to begin':active?`${AGENT_INFO[active.name].name} agent is working`:d.blocked?'Some videos need your attention':'Ready for the next run';
  const detail=active?`Task #${d.active.id} · ${d.active.title||'Open the queue for stage details.'}`:d.paused?'Start the pipeline when you are ready.':!d.online?'Keep start.cmd running and pair the Chrome extension on your VPS.':d.blocked?'Review failed or skipped work in Errors. Other videos can continue.':'New videos go from fetch to edit, then wait for a posting slot.';
  $('.worker-card').innerHTML=`<span class="status-dot ${!d.online?'amber':''}"></span><strong>${d.online?'VPS connected':'VPS offline'}</strong><small>Checked ${slClock(d.server_time)} SL</small>`;
  $('#notice').hidden=true;
  return {title,detail,active};
}

function statusCard(d){
  const status=workspaceStatus(d);
  const tone=status.active?.state==='stalled'?'red':status.active?'blue':d.paused||!d.online||d.blocked?'amber':'green';
  const [href,label]=status.active?['#jobs','View active task']:d.blocked?['#errors','Review errors']:!d.online?['#settings','Connection setup']:['#jobs','View queue'];
  const kicker=d.paused?'Pipeline paused':d.online?'Pipeline on · VPS connected':'Pipeline on · VPS offline';
  return `<section class="status-card tone-${tone}"><div class="status-main"><span class="status-orb"><b></b></span><div><p class="status-kicker">${kicker}</p><h2>${esc(status.title)}</h2><p class="status-detail">${esc(status.detail)}</p></div></div><div class="status-actions"><a class="button" href="${href}">${label}${icon('arrow')}</a>${pipelineButton(d)}</div></section>`;
}

function stageTotals(d){
  const totals=d.totals||{};
  return `<div class="kpi-grid stage-totals">${[['fetched','Fetched videos','Downloads completed'],['edited','Edited videos','Edits completed'],['uploaded','Uploaded videos','Publication confirmed']].map(([stage,label,help])=>`<a class="kpi" href="#library" data-total-stage="${stage}"><span class="kpi-label">${label}</span><strong class="kpi-value">${Number(totals[stage]||0).toLocaleString('en-GB')}</strong><small>${help} · all time</small></a>`).join('')}</div>`;
}

function kpis(d){
  const post=d.agents.find(a=>a.name==='uploader');
  const queued=d.tasks.filter(t=>t.state==='queued').length;
  const postNote=d.paused?'Automation paused':!d.online?'Waiting for VPS':!Number(post?.enabled)?'Upload agent paused':d.ready?`${d.ready} video(s) ready`:'Waiting for a finished edit';
  return `<div class="kpi-grid"><div class="kpi"><span class="kpi-label">Next post</span><strong class="kpi-value countdown" data-countdown="${esc(post?.next_run||'')}">${post?.next_run?duration(post.next_run):'Not scheduled'}</strong><small>${post?.next_run?date(post.next_run)+' · ':''}${postNote}</small></div><a class="kpi" href="#jobs"><span class="kpi-label">Queued tasks</span><strong class="kpi-value">${queued}</strong><small>Waiting to run</small></a><a class="kpi" href="#library"><span class="kpi-label">Ready to post</span><strong class="kpi-value">${d.ready}</strong><small>Edited and titled</small></a><a class="kpi ${d.blocked?'is-alert':''}" href="#errors"><span class="kpi-label">Needs attention</span><strong class="kpi-value">${d.blocked}</strong><small>${d.blocked?'Review in Errors':'All clear'}</small></a></div>`;
}

function taskCards(tasks,compact=false){
  if(!tasks.length)return empty('The queue is clear','Fetched videos move through edit and upload here. Skipped or failed work stays visible with its reason.','',icon('queue'));
  return `<div class="table-wrap"><table class="data"><thead><tr><th>Video / task</th><th>Agent</th><th>Status</th>${compact?'<th>Time (SL)</th>':'<th>Created (SL)</th><th>Scheduled (SL)</th><th>Started (SL)</th><th>Finished (SL)</th>'}<th><span class="sr-only">Actions</span></th></tr></thead><tbody>${tasks.map(t=>{
    const info=AGENT_INFO[t.agent];
    const canRetry=['failed','skipped','cancelled'].includes(t.state)&&t.agent!=='uploader';
    const done=t.agent==='uploader'&&t.state==='completed'?'Posted':'Finished';
    const when=t.finished_at?`${done} ${date(t.finished_at)}`:t.started_at?`Started ${date(t.started_at)}`:`Scheduled ${date(t.scheduled_at)}`;
    const planned=!compact&&(t.finished_at||t.started_at)&&t.scheduled_at?`<small class="cell-note">Scheduled ${date(t.scheduled_at)}</small>`:'';
    const actions=`${t.job_id?`<button class="button small ghost" data-command="job-log" data-id="${t.job_id}">${icon('log')}Logs</button>`:''}${t.state==='queued'?opButton('skip',icon('skip')+'Skip',`data-id="${t.id}"`,'small'):''}${canRetry?opButton('retry',icon('retry')+'Retry',`data-id="${t.id}"`,'small'):''}`;
    return `<tr><td class="cell-main" data-label="Video"><div class="cell-title">${esc(t.title||`${info.name} · ${t.channel_name}`)}</div><div class="cell-sub">#${t.id} · ${esc(t.channel_name)}</div>${t.reason?`<div class="reason">${icon('alert')}<span>${esc(t.reason)}</span></div>`:''}</td><td data-label="Agent"><span class="agent-tag">${icon(info.icon)}${info.name}</span></td><td data-label="Status">${badge(t.state)}</td>${compact?`<td data-label="Time (SL)" class="time-cell"><div>${when}${planned}</div></td>`:[ ['Created',t.created_at],['Scheduled',t.scheduled_at],['Started',t.started_at],[done,t.finished_at] ].map(([label,stamp])=>`<td class="time-cell" data-label="${label} (SL)">${date(stamp)}</td>`).join('')}<td class="actions-cell">${actions?`<div class="row-actions">${actions}</div>`:''}</td></tr>`;
  }).join('')}</tbody></table></div>`;
}

function videoCards(videos){
  if(!videos.length)return empty('No videos yet','Each fetched video appears here with a check for every finished stage.','',icon('video'));
  const step=(ok,label,stamp)=>`<td class="step-cell" data-label="${label}"><div class="stage-detail"><span class="step ${ok?'done':''}" title="${label}: ${ok?'done':'pending'}">${ok?icon('check'):''}</span><small>${ok?(stamp?date(stamp):'Complete · time not recorded'):'Pending'}</small></div></td>`;
  return `<div class="table-wrap"><table class="data videos-table"><thead><tr><th>Video</th><th class="center">Fetched (SL)</th><th class="center">Title verified (SL)</th><th class="center">Edited (SL)</th><th class="center">Uploaded (SL)</th><th>Status</th><th>Result</th></tr></thead><tbody>${videos.map(v=>{
    const link=v.published_url&&/^https:\/\/www\.youtube\.com\//.test(v.published_url)?` <a class="text-link" href="${esc(v.published_url)}" target="_blank" rel="noopener">View${icon('external')}</a>`:'';
    const result=v.published_at?'Posted '+date(v.published_at):v.edited_at?'Edited '+date(v.edited_at)+(v.blocked_reason?'':' · waiting for a slot'):'<span class="muted-text">Not posted</span>';
    return `<tr><td class="cell-main" data-label="Video"><div class="cell-title">${esc(v.title||v.original_title||v.source_video_id)}</div><div class="cell-sub">${esc(v.channel_name)} · ${esc(v.source_video_id)}</div>${v.blocked_reason?`<div class="reason red">${icon('alert')}<span>Cannot post: ${esc(v.blocked_reason)}</span></div>`:''}</td>${step(v.downloaded_at,'Fetched',v.downloaded_at)}${step(Number(v.title_ready),'Title verified',v.edited_at)}${step(v.edited_at,'Edited',v.edited_at)}${step(v.published_at,'Uploaded / published',v.published_at)}<td data-label="Status">${badge(v.status)}</td><td data-label="Result" class="result-cell"><div>${result}${link}<small class="cell-note">Last activity ${date(v.activity_at||v.updated_at)}</small></div></td></tr>`;
  }).join('')}</tbody></table></div>`;
}

function scanCards(rows){
  if(!rows.length)return empty('No channel check yet','The next fetch looks at the latest five videos and marks each as downloaded, duplicate or skipped.','',icon('channels'));
  return `<div class="table-wrap"><table class="data"><thead><tr><th>Video</th><th>Result</th><th>Checked</th><th>Note</th></tr></thead><tbody>${rows.map(v=>`<tr><td class="cell-main" data-label="Video"><div class="cell-title">${esc(v.title)}</div><div class="cell-sub">${esc(v.channel_name)} · ${esc(v.source_video_id)}</div></td><td data-label="Result">${badge(v.result)}</td><td data-label="Checked" class="nowrap">${date(v.checked_at)}</td><td data-label="Note">${v.reason?esc(v.reason):'<span class="muted-text">—</span>'}</td></tr>`).join('')}</tbody></table></div>`;
}

function eventsTable(events){
  if(!events.length)return empty('No warnings or errors','Worker failures and skipped post slots will appear here.','',icon('check'));
  return `<div class="table-wrap"><table class="data"><thead><tr><th>Time</th><th>Level</th><th>Source</th><th>Message</th><th>Video</th></tr></thead><tbody>${events.map(e=>`<tr><td data-label="Time" class="nowrap">${date(e.created_at)}</td><td data-label="Level">${badge(e.level)}</td><td data-label="Source"><span class="agent-tag plain">${esc(e.source)}</span></td><td class="cell-main message-cell" data-label="Message">${esc(e.message)}</td><td data-label="Video">${e.job_id?'#'+esc(e.job_id):'<span class="muted-text">—</span>'}</td></tr>`).join('')}</tbody></table></div>`;
}

async function renderOperations(view){
  const d=await api('operations');operationsState=d;serverOffset=Date.parse(d.server_time)-Date.now();
  workspaceStatus(d);
  const queued=d.tasks.filter(t=>t.state==='queued').length;
  $('#nav-queue').textContent=queued;$('#nav-queue').hidden=!queued;
  $('#nav-errors').textContent=d.blocked;$('#nav-errors').hidden=!d.blocked;
  if(view==='overview'){
    const v=await api('video_checks');
    const priority=t=>t.state==='running'?0:t.state==='queued'?1:2;
    const recent=[...d.tasks].sort((a,b)=>priority(a)-priority(b)||Number(b.id)-Number(a.id));
    return `${statusCard(d)}${kpis(d)}${stageTotals(d)}${panel('Agents','One task runs at a time · Sri Lanka time',agentsTable(d))}${panel('Queue','Running and waiting tasks first',taskCards(recent.slice(0,5),true),`<a class="text-link" href="#jobs">View all${icon('arrow')}</a>`)}${panel('Recent videos','A check means the stage is complete',videoCards(v.items.slice(0,5)),`<a class="text-link" href="#library">View all${icon('arrow')}</a>`)}`;
  }
  if(view==='jobs')return controlBar(d)+await renderBrowse('jobs');
  if(view==='library')return await renderBrowse('library')+panel('Latest channel check','The last five videos the fetch agent looked at',scanCards(d.latest_scan||[]));
  if(view==='schedules'){
    const rows=d.agents.map(a=>{
      const info=AGENT_INFO[a.name],isEditor=a.name==='editor';
      const agent=`<td class="cell-main" data-label="Agent"><div class="agent-cell"><span class="icon-box">${icon(info.icon)}</span><div><strong>${info.name}</strong><small>${info.detail}</small></div></div></td>`;
      if(isEditor)return `<tr>${agent}<td data-label="Daily times"><span class="muted-text">After each download, one at a time</span></td><td data-label="Next run">${a.queued?a.queued+' queued':'<span class="muted-text">—</span>'}</td><td data-label="Based on">Downloads</td><td data-label="Status">${badge(Number(a.enabled)?'enabled':'paused')}</td><td class="actions-cell"><div class="row-actions">${opButton('run','Queue all edits','data-agent="editor"','small')}</div></td></tr>`;
      return `<tr>${agent}<td data-label="Daily times"><div class="slots">${a.display_slots.map(t=>`<span class="slot">${esc(t)}</span>`).join('')}</div></td><td data-label="Next run" class="nowrap">${date(a.next_run)}</td><td data-label="Based on">${a.schedule_timezone==='America/New_York'?'US Eastern · auto daylight saving':'Fixed Sri Lanka times'}</td><td data-label="Status">${badge(Number(a.enabled)?'enabled':'paused')}</td><td class="actions-cell"><div class="row-actions">${opButton('schedule',icon('edit')+'Edit times',`data-agent="${a.name}"`,'small')}</div></td></tr>`;
    }).join('');
    return `${controlBar(d)}${panel('Daily schedule','3 fetches and 3 posts a day · shown in Sri Lanka time',`<div class="table-wrap"><table class="data"><thead><tr><th>Agent</th><th>Daily times</th><th>Next run</th><th>Based on</th><th>Status</th><th><span class="sr-only">Actions</span></th></tr></thead><tbody>${rows}</tbody></table></div>`)}<p class="footnote">Fetches run 45 minutes before each post so edits have time to finish. If no edited video is ready, that post slot is skipped.</p>`;
  }
  if(view==='errors')return renderErrorReview(await api('errors'));

}

function bindOperations(){tickClocks();}

async function operationDialog(type,agent,id){
  if(!isAdmin)return;
  const config=operationsState.agents.find(a=>a.name===agent);
  $('#modal-error').hidden=true;
  $('#modal-title').textContent=type==='schedule'?'Daily '+(agent==='fetch'?'fetch':'post')+' times':'Skip this task';
  $('#modal-fields').innerHTML=type==='schedule'?`<p class="form-hint">Enter three daily times in Sri Lanka time. Saved times stay fixed and no longer follow US daylight saving.</p><div class="form-row">${[0,1,2].map(i=>`<label>Time ${i+1}<input name="slot${i}" type="time" required value="${config.display_slots[i]||''}"></label>`).join('')}</div>`:'<label>Why skip this task?<input name="reason" required maxlength="1000" placeholder="e.g. Wrong video, do not post"></label><p class="form-hint">The video is kept out of the upload queue and the reason stays visible.</p>';
  $('#modal-submit').textContent=type==='schedule'?'Save times':'Skip task';$('#modal').showModal();
  $('#modal-form').onsubmit=async event=>{
    event.preventDefault();$('#modal-submit').disabled=true;
    try{const data=Object.fromEntries(new FormData(event.target));await api(type==='schedule'?'agent_schedule':'task_skip',type==='schedule'?{agent,slots:[data.slot0,data.slot1,data.slot2],timezone:'Asia/Colombo'}:{id,reason:data.reason});$('#modal').close();toast('Saved.');await render();}
    catch(error){$('#modal-error').textContent=error.message;$('#modal-error').hidden=false;}finally{$('#modal-submit').disabled=false;}
  };
}

document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-op]');if(!button||!isAdmin)return;
  const op=button.dataset.op,agent=button.dataset.agent,id=Number(button.dataset.id);
  if(op==='schedule'||op==='skip')return operationDialog(op,agent,id);
  button.disabled=true;
  try{
    if(op.startsWith('pipeline-'))await api('pipeline_control',{command:op==='pipeline-start'?'start':'stop'});
    if(op==='agent-toggle')await api('agent_control',{agent,command:button.dataset.next});
    if(op==='run')await api('agent_run',{agent,...(agent==='uploader'?{immediate:true}:{})});
    if(op==='retry')await api('task_retry',{id});
    toast(op==='pipeline-start'?'Pipeline enabled. A connected worker is required.':op==='pipeline-stop'?'Stop requested. The execution slot stays locked until active work stops.':op==='run'&&agent==='uploader'?'Upload queued for now. It starts when the worker and shared slot are available.':'Queue updated.');await render();
  }catch(error){toast(error.message);button.disabled=false;}
});
setInterval(()=>{
  if(operationPages.includes(page)&&!['jobs','library','errors'].includes(page)&&!document.hidden&&!$('#modal').open&&!$('.sidebar').classList.contains('open')&&!content.contains(document.activeElement))render(true);
},10000);
