'use strict';
let operationsState = null;
let serverOffset = 0;
const AGENT_INFO = {
  fetch: {name:'Fetch agent', icon:'↓', color:'cyan', label:'DISCOVERY', detail:'Latest 5 videos · duplicates filtered'},
  editor: {name:'Editor agent', icon:'✦', color:'violet', label:'PRODUCTION', detail:'Edit every new video · one at a time'},
  uploader: {name:'Upload agent', icon:'↗', color:'coral', label:'PUBLISHING', detail:'3 daily posts · verified edits only'}
};
const operationPages = ['overview','jobs','schedules','library','errors'];
const utcDate = value => new Date(value && (value.includes('T') ? value : value.replace(' ','T')+'Z'));
const slClock = value => utcDate(value).toLocaleTimeString('en-GB',{timeZone:'Asia/Colombo',hour:'2-digit',minute:'2-digit',second:'2-digit'});
const slDay = value => utcDate(value).toLocaleDateString('en-GB',{timeZone:'Asia/Colombo',day:'numeric',month:'short'});

function opButton(action,text,extra='',kind='') {
  return `<button class="button ${kind}" data-op="${action}" ${extra} ${isAdmin?'':'disabled title="Sign in to control automation"'}>${text}</button>`;
}
function duration(until) {
  const seconds=Math.max(0,Math.ceil((utcDate(until).getTime()-Date.now()-serverOffset)/1000));
  if(!Number.isFinite(seconds)) return '—';
  if(seconds===0) return 'Due now';
  const h=Math.floor(seconds/3600),m=Math.floor(seconds%3600/60),s=seconds%60;
  return `${String(h).padStart(2,'0')}<i>h</i> ${String(m).padStart(2,'0')}<i>m</i> ${String(s).padStart(2,'0')}<i>s</i>`;
}
function countdown(until,label) {
  return `<div class="agent-countdown"><span>${label}</span><strong data-countdown="${esc(until||'')}">${until?duration(until):'Waiting for videos'}</strong></div>`;
}
function tickClocks(){
  document.querySelectorAll('[data-countdown]').forEach(node=>{if(node.dataset.countdown)node.innerHTML=duration(node.dataset.countdown);});
  document.querySelectorAll('[data-sl-clock]').forEach(node=>node.textContent=new Date(Date.now()+serverOffset).toLocaleTimeString('en-GB',{timeZone:'Asia/Colombo'}));
}
setInterval(tickClocks,1000);

function agentCards(d){
  const nextFetch=d.agents.find(a=>a.name==='fetch')?.next_run;
  return `<div class="agent-grid">${d.agents.map(a=>{
    const info=AGENT_INFO[a.name];
    const isEditor=a.name==='editor';
    let time=a.next_run,label='Next scheduled '+(a.name==='fetch'?'fetch':'post');
    if(isEditor){ time=null;label=a.queued?'Ready in the edit queue':'Starts when a new download is ready'; }
    let clock=countdown(time,label);
    if(isEditor&&a.queued)clock=`<div class="agent-countdown"><span>${label}</span><strong>${a.queued} <i>videos</i></strong></div>`;
    if(a.state==='running'||a.state==='stopping'||a.state==='stalled'){
      const editing=isEditor&&a.state==='running';
      const minutes=Math.max(0,Math.floor((Date.now()+serverOffset-utcDate(d.active.started_at))/60000));
      clock=`<div class="agent-countdown"><span>Current task #${d.active.id} · ${minutes} min elapsed</span><strong>${a.state==='running'?(editing?'Editing…':a.progress+'%'):a.state==='stopping'?'Stopping…':'Needs attention'}</strong>${editing?'<small>Rewrite / render · percentage unavailable</small>':`<progress value="${a.progress}" max="100"></progress>`}<span>Runner heartbeat ${Number(d.active.heartbeat_age)}s ago</span></div>`;
    }
    return `<article class="agent-card ${info.color} ${a.state==='running'?'is-running':''}"><div class="agent-card-top"><div class="agent-symbol"><span>${info.icon}</span></div><span class="agent-state ${esc(a.state)}"><b></b>${esc(a.state)}</span></div><p class="agent-label">${info.label}</p><h2>${info.name}</h2><p class="agent-description">${info.detail}</p>${clock}<div class="agent-schedule">${isEditor?'All downloaded videos → edit queue':a.display_slots.map(t=>`<span>${t}</span>`).join('')+'<small>SL time</small>'}</div><div class="agent-meta"><span>In queue <b>${a.queued}</b></span><span>Last finished <b>${a.last_finished?date(a.last_finished):'Not run yet'}</b></span></div><p class="agent-execution-note">${a.state==='offline'?'Schedule saved · worker not connected':a.state==='paused'?'Paused · countdown shows the planned slot':a.state==='stalled'?'Heartbeat lost · execution slot stays locked':a.name==='uploader'&&!d.ready?'No eligible video yet · next slot is planned':a.state==='running'?'Working in the shared execution slot':(d.active?'Waiting for the active task to finish':'Ready · waiting for eligible work')}</p><div class="agent-controls">${opButton('agent-toggle',Number(a.enabled)?'Ⅱ Pause':'▶ Enable',`data-agent="${a.name}" data-next="${Number(a.enabled)?'stop':'start'}"`)}${opButton('run',isEditor?'Edit new videos':a.name==='fetch'?'Fetch now':'Upload now',`data-agent="${a.name}"`)}</div></article>`;
  }).join('')}</div>`;
}

function controlBar(d){
  return `<div class="mission-toolbar"><div class="mission-status"><span class="status-dot ${d.paused||!d.online?'amber':''}"></span><strong>${d.paused?'Pipeline paused':d.online?'Pipeline enabled':'Enabled · waiting for worker'}</strong><span class="safe-chip">⌁ One shared execution slot</span></div><div class="mission-actions">${opButton('pipeline-start','▶ Start all','','primary')}${opButton('pipeline-stop','■ Stop all','','danger')}${isAdmin?'':'<a href="login.php" class="button">⌑ Sign in to control</a>'}</div></div>`;
}

function workspaceStatus(d){
  const active=d.agents.find(a=>['running','stopping','stalled'].includes(a.state));
  const title=active?.state==='stalled'?'Worker needs attention':active?.state==='stopping'?'Finishing the stop request':d.paused?'Automation is paused':!d.online?'Connect your VPS to begin':active?`${AGENT_INFO[active.name].name} is working`:d.blocked?'Some videos need your attention':'Ready for the next run';
  const detail=active?`Task #${d.active.id} · ${d.active.title||'Open the queue for stage details.'}`:d.paused?'Resume automation when you are ready.':!d.online?'Keep start.cmd running and pair the Chrome extension on your VPS.':d.blocked?'Review failed or skipped work in Errors. Eligible videos can continue.':'New videos move from fetch to edit, then wait for a publishing slot.';
  $('.worker-card').innerHTML=`<span class="status-dot ${!d.online?'amber':''}"></span><strong>${d.online?'VPS connected':'VPS offline'}</strong><small>Last checked ${slClock(d.server_time)} SL</small>`;
  $('#notice').hidden=true;
  return {title,detail,active};
}

function overviewHero(d,clock){
  const status=workspaceStatus(d),post=d.agents.find(a=>a.name==='uploader');
  return `<section class="overview-hero"><div class="hero-copy"><span class="mission-tag">YOUR AUTOMATION, AT A GLANCE</span><h2>${esc(status.title)}</h2><p>${esc(status.detail)}</p><div class="hero-links"><a class="button primary" href="${status.active?'#jobs':d.blocked?'#errors':!d.online?'#settings':'#jobs'}">${status.active?'View active task':d.blocked?'Review errors':!d.online?'Connection setup':'View queue'} →</a><a class="text-link" href="#console">Live console ↗</a></div></div><div class="hero-next"><span class="mission-tag">NEXT PLANNED POST</span><strong data-countdown="${esc(post?.next_run||'')}">${post?.next_run?duration(post.next_run):'Not scheduled'}</strong><p>${date(post?.next_run)} · Sri Lanka</p><small>${d.paused?'Automation paused':!d.online?'Waiting for VPS':!Number(post?.enabled)?'Upload agent paused':d.ready?`${d.ready} video(s) ready`:'Waiting for a finished edit'} · slot is not a guarantee</small></div></section><div class="section-heading"><div><h2>Pipeline overview</h2><p>01 Fetch <span>→</span> 02 Edit <span>→</span> 03 Publish · one task at a time</p></div>${clock}</div>`;
}

function taskCards(tasks){
  if(!tasks.length)return empty('Your queue is clear','Each fetched video will move through download, edit and upload. Skipped or failed work remains visible with its reason.','','≡');
  return `<div class="queue-list">${tasks.map(t=>{
    const info=AGENT_INFO[t.agent];
    const canRetry=['failed','skipped','cancelled'].includes(t.state)&&t.agent!=='uploader';
    return `<article class="queue-row"><span class="queue-symbol ${info.color}">${info.icon}</span><div class="queue-main"><div class="queue-title"><strong>${esc(t.title||t.channel_name)}</strong>${badge(t.state)}</div><p>#${t.id} · ${esc(info.name)} · ${esc(t.channel_name)}</p>${t.reason?`<div class="queue-reason">⚠ ${esc(t.reason)}</div>`:''}<div class="queue-times"><span>Scheduled ${date(t.scheduled_at)}</span>${t.started_at?`<span>Started ${date(t.started_at)}</span>`:''}${t.finished_at?`<span>${t.agent==='uploader'&&t.state==='completed'?'Posted':'Finished'} ${date(t.finished_at)}</span>`:''}</div></div><div class="queue-actions">${t.job_id?`<button class="button small" data-command="job-log" data-id="${t.job_id}">Logs</button>`:''}${t.state==='queued'?opButton('skip','Skip',`data-id="${t.id}"`,'small'):''}${canRetry?opButton('retry','Retry',`data-id="${t.id}"`,'small'):''}</div></article>`;
  }).join('')}</div>`;
}

function videoCards(videos){
  if(!videos.length)return empty('Waiting for the first five-video check','New videos will show their title, stage checkmarks and actual posting time. Duplicate video IDs will not create another job.','','▶');
  const check=(ok,label)=>`<span class="video-check ${ok?'done':'pending'}"><b>${ok?'✓':'○'}</b>${label}</span>`;
  return `<div class="video-check-list">${videos.map(v=>`<article class="video-check-card"><div class="video-top"><span class="video-icon">▶</span><div><h3>${esc(v.title||v.original_title||v.source_video_id)}</h3><p>${esc(v.channel_name)} · ${esc(v.source_video_id)}</p></div>${badge(v.status)}</div><div class="video-checks">${check(v.downloaded_at,'Downloaded')}${check(Number(v.title_ready),'Title ready')}${check(v.edited_at,'Editor complete')}${check(v.published_at,'Uploader complete')}</div>${v.blocked_reason?`<p class="queue-reason">⛔ Cannot post: ${esc(v.blocked_reason)}</p>`:''}<div class="video-footer"><span>${v.published_at?'Posted '+date(v.published_at):v.edited_at?'Edited '+date(v.edited_at)+' · awaiting a post slot':'Not posted'}</span>${v.published_url&&/^https:\/\/www\.youtube\.com\//.test(v.published_url)?`<a class="text-link" href="${esc(v.published_url)}" target="_blank" rel="noopener">View post ↗</a>`:''}</div></article>`).join('')}</div>`;
}

function scanCards(rows){
  if(!rows.length)return empty('No channel scan yet','The next fetch will inspect five recent videos and label each one as downloaded, duplicate or skipped.','','◎');
  return `<div class="queue-list">${rows.map(v=>`<article class="queue-row"><span class="queue-symbol cyan">${v.result==='duplicate'?'↺':v.result==='downloaded'?'✓':'!'}</span><div class="queue-main"><div class="queue-title"><strong>${esc(v.title)}</strong>${badge(v.result)}</div><p>${esc(v.channel_name)} · ${esc(v.source_video_id)}</p><div class="queue-times">Checked ${date(v.checked_at)}</div>${v.reason?`<p class="queue-reason">${esc(v.reason)}</p>`:''}</div></article>`).join('')}</div>`;
}

async function renderOperations(view){
  const d=await api('operations');operationsState=d;serverOffset=Date.parse(d.server_time)-Date.now();
  workspaceStatus(d);
  $('#nav-queue').textContent=d.tasks.filter(t=>t.state==='queued').length;
  $('#nav-errors').textContent=d.blocked;
  const clock=`<div class="local-time"><span>◷ SRI LANKA</span><strong data-sl-clock></strong><small>Asia/Colombo · UTC+05:30</small></div>`;
  const note=`<div class="operations-note"><span>◈</span><p><strong>Latest 5 → deduplicate → edit all → 3 daily posts.</strong> ${d.active?'One task owns the execution slot. Other agents wait.':'One agent works at a time; failed and skipped videos cannot post.'}</p></div>`;
  if(view==='overview'){
    const v=await api('video_checks');
    const priority=t=>t.state==='running'?0:t.state==='queued'?1:2;
    const recent=[...d.tasks].sort((a,b)=>priority(a)-priority(b)||Number(b.id)-Number(a.id));
    return `${overviewHero(d,clock)}${controlBar(d)}${agentCards(d)}<div class="ops-stats"><a href="#jobs"><b>${d.tasks.filter(t=>t.state==='queued').length}</b><span>Queued tasks ↗</span></a><a href="#library"><b>${d.ready}</b><span>Ready to post ↗</span></a><a href="#errors" class="${d.blocked?'has-errors':''}"><b>${d.blocked}</b><span>Need attention ↗</span></a><a href="#library"><b>${d.published.length}</b><span>Recent confirmed posts ↗</span></a></div><div class="ops-bottom-grid">${panel('Queue activity','Active and waiting tasks first',taskCards(recent.slice(0,4)),'<a class="text-link" href="#jobs">Full queue →</a>')}${panel('Video progress','Checkmarks confirm each completed stage',videoCards(v.items.slice(0,4)),'<a class="text-link" href="#library">All videos →</a>')}</div>`;
  }
  if(view==='jobs')return `${controlBar(d)}${note}<div class="queue-filters"><button data-queue-filter="all" class="filter-chip selected">All ${d.tasks.length}</button>${['queued','running','completed','skipped','failed','blocked','needs_attention'].map(s=>`<button data-queue-filter="${s}" class="filter-chip">${s.replaceAll('_',' ')} <b>${d.tasks.filter(t=>t.state===s).length}</b></button>`).join('')}</div>${panel('Execution queue','Oldest ready task first. Uploads require a completed edit and title.',`<div id="task-list">${taskCards(d.tasks)}</div>`)}<div class="operations-note"><span>⛔</span><p>If a worker disconnects mid-task, its slot stays locked. A stale process cannot be replaced by a second overlapping process.</p></div>`;
  if(view==='library'){const v=await api('video_checks');return panel('Latest five observations','Downloaded, duplicate and skipped source videos',scanCards(d.latest_scan||[]))+panel('Video checklist',`${v.items.length} tracked videos · every date is Sri Lanka time`,videoCards(v.items));}
  if(view==='schedules'){
    const schedule=d.agents.filter(a=>a.name!=='editor');
    return `${controlBar(d)}<div class="schedule-intro"><div><span class="mission-tag">3 FETCHES / 3 POSTS PER DAY</span><h2>Built around US viewing hours.</h2><p>US Eastern noon, evening and late evening are a starting hypothesis. Use your channel’s audience report to tune the schedule.</p></div>${clock}</div><div class="schedule-grid">${schedule.map(a=>`<section class="panel schedule-panel ${AGENT_INFO[a.name].color}"><div class="panel-header"><h2>${a.name==='fetch'?'↓ Fetch windows':'↗ Posting windows'}</h2>${badge(Number(a.enabled)?'enabled':'paused')}</div><div class="schedule-slots">${a.display_slots.map((slot,i)=>`<div><span>WINDOW 0${i+1}</span><strong>${slot}</strong><small>Sri Lanka time</small></div>`).join('')}</div><p class="schedule-explain">${a.name==='fetch'?'Inspect the latest five Shorts and download unseen videos.':'Post the oldest eligible edit. If none is ready, record a skipped slot.'}</p><p class="schedule-zone">${a.schedule_timezone==='America/New_York'?'US daylight saving changes are applied automatically.':'These are fixed Sri Lanka clock times.'}</p><div class="schedule-bottom"><span>Next ${date(a.next_run)}</span>${opButton('schedule','Edit times',`data-agent="${a.name}"`,'small')}</div></section>`).join('')}</div>${panel('✦ Editor schedule','Event-driven: after download, before publication','<div class="editor-policy"><span class="policy-orbit">✦</span><div><h3>Edit everything new</h3><p>Every downloaded video gets its own edit task. The editor drains the queue one at a time. The next edit starts when its download is complete and the shared execution slot is free.</p></div>'+opButton('run','Queue all edits','data-agent="editor"')+'</div>')}<div class="operations-note"><span>i</span><p>Fetches are 45 minutes before their matching post windows by default. That is preparation time, not a guarantee: an unfinished edit waits for a later post slot.</p></div>`;
  }
  if(view==='errors'){
    const e=await api('errors');
    const runningStale=e.tasks.filter(t=>t.state==='running').length;
    return `<div class="error-summary"><div class="error-orb">!</div><div><h2>${e.tasks.length?e.tasks.length+' tasks need a look':'No task errors recorded'}</h2><p>${runningStale?'A worker heartbeat was lost. The execution slot is still locked.':'Skipped, failed and uncertain uploads are held here until reviewed.'}</p></div>${badge(e.tasks.length?'needs_attention':'success')}</div>${panel('Blocked work','Skipped videos cannot be posted. Uncertain uploads require reconciliation.',taskCards(e.tasks.map(t=>({...t,scheduled_at:t.started_at,channel_name:t.channel_name}))))}${panel('Warnings & errors','Latest 200 events · Sri Lanka time',e.events.length?'<div class="error-events">'+e.events.map(e=>`<article class="error-event"><span class="error-event-icon">${e.level==='error'?'⛔':'⚠'}</span><div><strong>${esc(e.message)}</strong><p>${date(e.created_at)} · ${esc(e.source)}${e.job_id?' · video #'+e.job_id:''}</p></div>${badge(e.level)}</article>`).join('')+'</div>':empty('No warnings or errors','Real worker failures and skipped post slots will appear here.','','✓'))}`;
  }
}

function bindOperations(){tickClocks();}

async function operationDialog(type,agent,id){
  if(!isAdmin)return;
  const config=operationsState.agents.find(a=>a.name===agent);
  $('#modal-error').hidden=true;
  $('#modal-title').textContent=type==='schedule'?'Daily '+(agent==='fetch'?'fetch':'post')+' times':'Skip this task';
  $('#modal-fields').innerHTML=type==='schedule'?`<p class="form-hint">Enter exactly three daily times in Sri Lanka time. Saving changes uses fixed Sri Lanka times rather than automatic US daylight saving adjustments.</p>${[0,1,2].map(i=>`<label>Window ${i+1}<input name="slot${i}" type="time" required value="${config.display_slots[i]||''}"></label>`).join('')}`:'<label>Why should this task be skipped?<input name="reason" required maxlength="1000" placeholder="Explain why this video must not be posted"></label><p class="form-hint">The video is held out of the upload queue. Its reason remains visible.</p>';
  $('#modal-submit').textContent=type==='schedule'?'Save schedule':'Skip task';$('#modal').showModal();
  $('#modal-form').onsubmit=async event=>{
    event.preventDefault();$('#modal-submit').disabled=true;
    try{const data=Object.fromEntries(new FormData(event.target));await api(type==='schedule'?'agent_schedule':'task_skip',type==='schedule'?{agent,slots:[data.slot0,data.slot1,data.slot2],timezone:'Asia/Colombo'}:{id,reason:data.reason});$('#modal').close();toast('Saved.');await render();}
    catch(error){$('#modal-error').textContent=error.message;$('#modal-error').hidden=false;}finally{$('#modal-submit').disabled=false;}
  };
}

document.addEventListener('click',async event=>{
  const filter=event.target.closest('[data-queue-filter]');
  if(filter){document.querySelectorAll('[data-queue-filter]').forEach(n=>n.classList.toggle('selected',n===filter));$('#task-list').innerHTML=taskCards(operationsState.tasks.filter(t=>filter.dataset.queueFilter==='all'||t.state===filter.dataset.queueFilter));return;}
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
  if(operationPages.includes(page)&&!document.hidden&&!$('#modal').open&&!$('.sidebar').classList.contains('open')&&!content.contains(document.activeElement))render(true);
},10000);
