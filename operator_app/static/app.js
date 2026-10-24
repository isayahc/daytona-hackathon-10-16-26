/* Local event workspace backed by the Python API. Research imports are tab-local. */
'use strict';
const reports = new Map();
let data, selectedId = 'e1', filter = 'all', month = 9, year = 2026, map;
const markers = new Map();
const $ = id => document.getElementById(id);
const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money = value => value == null ? 'Not set' : new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:0}).format(value);
const date = value => new Date(value).toLocaleDateString('en-US',{month:'short',day:'numeric',timeZone:'America/New_York'});
const time = value => new Date(value).toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit',timeZone:'America/New_York'});
const dayKey = value => new Intl.DateTimeFormat('en-CA',{year:'numeric',month:'2-digit',day:'2-digit',timeZone:'America/New_York'}).format(new Date(value));
function modal(title, body) { $('dialog-content').innerHTML = `<span class="tag">DEMO · NO EXTERNAL ACTION</span><h2>${esc(title)}</h2><p>${esc(body)}</p>`; $('detail-dialog').showModal(); }
function selectEvent(id, moveMonth = true) {
  selectedId = id;
  const event = data.events.find(e => e.id === id);
  if (moveMonth) { const parts = dayKey(event.starts_at).split('-'); year = Number(parts[0]); month = Number(parts[1])-1; }
  render();
  if (map && markers.has(event.venue_id)) { const marker = markers.get(event.venue_id); map.panTo(marker.getLatLng()); marker.openPopup(); }
}
function renderMetrics() {
 const event = data.events.find(e => e.id === selectedId);
 const values = [
 ['Funding secured',money(event.funding_secured_usd),`of ${money(event.budget_usd)} planned budget`,event.budget_usd ? (event.funding_secured_usd ?? 0)/event.budget_usd : 0],
 ['Registrations',event.registration_count ?? 'Not recorded',event.registration_target == null ? 'Target not set' : `of ${event.registration_target} intended participants`,event.registration_target ? (event.registration_count ?? 0)/event.registration_target : 0],
 ['Event date',date(event.starts_at),`${time(event.starts_at)} ET · ${event.status}`,null],
 ['Intended outcomes',event.intended_outcomes.length,'Evidence collection starts with the plan',null]];
 $('kpis').innerHTML=values.map(([label,value,note,progress])=>`<div class="kpi"><label>${esc(label)}</label><strong>${esc(value)}</strong><small>${esc(note)}</small>${progress!==null?`<div class="progress"><span style="width:${Math.min(100,progress*100)}%"></span></div>`:''}</div>`).join('');
}
function renderCalendar() {
 $('month-label').textContent = new Date(year,month).toLocaleDateString('en-US',{month:'long',year:'numeric'});
 const first = new Date(year,month,1).getDay(), days = new Date(year,month+1,0).getDate();
 const selected = data.events.find(e=>e.id===selectedId);
 $('calendar').innerHTML='<span class="blank"></span>'.repeat(first)+Array.from({length:days},(_,i)=>{
  const key=`${year}-${String(month+1).padStart(2,'0')}-${String(i+1).padStart(2,'0')}`;
  const events=data.events.filter(e=>dayKey(e.starts_at)===key);
  return `<button class="${events.length?'has-event':''} ${dayKey(selected.starts_at)===key?'selected':''} ${key===data.demo_date?'today':''}" data-day="${key}" aria-label="${key}${events.length ? ': '+esc(events.map(e=>e.title).join(', ')) : ': no sample events'}" aria-pressed="${dayKey(selected.starts_at)===key}">${i+1}</button>`;
 }).join('');
 $('calendar').querySelectorAll('button').forEach(b=>b.onclick=()=>{
  const event=data.events.find(e=>dayKey(e.starts_at)===b.dataset.day);
  if(event) selectEvent(event.id,false); else modal('No sample events',`There are no events in this demo on ${b.dataset.day}. Use Plan an event to create a local draft.`);
 });
 const visible=data.events.filter(e=>dayKey(e.starts_at).startsWith(`${year}-${String(month+1).padStart(2,'0')}`));
  $('agenda').innerHTML=visible.length?visible.map(e=>`<button class="agenda-item ${e.id===selectedId?'selected':''}" data-event="${e.id}" aria-pressed="${e.id===selectedId}"><span class="date-block"><small>${date(e.starts_at).split(' ')[0]}</small>${dayKey(e.starts_at).slice(-2)}</span><span><strong>${esc(e.title)}</strong><small>${time(e.starts_at)} ET · ${esc(data.venues.find(v=>v.id===e.venue_id)?.location?.borough||'Venue needed')}</small></span></button>`).join(''):'<p class="empty">No sample events this month.</p>';
 $('agenda').querySelectorAll('button').forEach(b=>b.onclick=()=>selectEvent(b.dataset.event));
}
function renderActivity() {
 const options=[['all','All updates'],['message','Messages'],['task','Tasks'],['funding','Funding'],['outcome','Outcomes']];
 $('filters').innerHTML=options.map(([key,label])=>`<button class="${filter===key?'active':''}" aria-pressed="${filter===key}" data-filter="${key}">${label}</button>`).join('');
 $('filters').querySelectorAll('button').forEach(b=>b.onclick=()=>{filter=b.dataset.filter;renderActivity();});
 const activities=data.activities.filter(a=>a.event_id===selectedId&&(filter==='all'||a.kind===filter));
 const icons={message:'↗',task:'✓',funding:'$',outcome:'◈'};
 $('activity').innerHTML=activities.length?activities.map(a=>`<article class="activity-row"><div class="activity-icon">${icons[a.kind]}</div><div class="activity-copy"><div class="activity-top"><strong>${esc(a.title)}</strong><span class="channel">${esc(a.channel)} · mock</span></div><p>${esc(a.body)}</p><div class="activity-meta">${esc(a.actor)} · ${date(a.occurred_at)}</div><button class="text-button" data-activity="${a.id}">${esc(a.action_label)} →</button></div></article>`).join(''):'<p class="empty">No sample updates in this category for this event.</p>';
 $('activity').querySelectorAll('button').forEach(b=>b.onclick=()=>{const a=data.activities.find(a=>a.id===b.dataset.activity);modal(a.title,`${a.body}\n\nSource: ${a.channel} (fictional sample). No account is connected.\n\n${a.kind==='message'?'Message sending will use the reviewed outreach workflow; this preview cannot send or reply.':'Task updates and reporting are read-only in this skeleton.'}`);});
}
function renderDetail() {
  const e=data.events.find(e=>e.id===selectedId),v=data.venues.find(v=>v.id===e.venue_id);
  const personNames = ids => ids.map(id => data.people.find(p=>p.id===id)?.name || id).join(', ');
  const sponsors = (e.sponsor_ids || []).map(id => data.sponsors.find(s=>s.id===id)).filter(Boolean);
  const catering = data.catering.find(c=>c.id===e.catering_id);
  $('event-detail').innerHTML=`<div class="detail-content"><span class="tag">${e.is_mock ? 'SAMPLE · ' : 'LOCAL DRAFT · '}${esc(e.status.toUpperCase())}</span><h3>${esc(e.title)}</h3><p>${esc(e.summary)}</p><div class="detail-fact"><span>When</span>${esc(date(e.starts_at))} · ${esc(time(e.starts_at))} ET</div><div class="detail-fact"><span>Venue</span>${esc(v?.name||'Not selected')}</div><div class="detail-fact"><span>Availability</span>${e.is_mock ? 'Unverified · sample venue' : 'No venue selected'}</div><p>${esc(e.audience)}</p><strong>What this could enable</strong><ul>${e.intended_outcomes.map(o=>`<li>${esc(o)}</li>`).join('')}</ul><div class="next-action"><strong>Next action</strong><br>Confirm resources and define the evidence you will collect before making commitments.</div></div>`;
  $('event-detail').querySelector('.detail-content').insertAdjacentHTML('beforeend',
    `<h4>Event ecosystem</h4><div class="detail-fact"><span>Organizer</span>${esc(e.is_mock ? data.organization.name : 'Local organizer')} · ${esc(data.organization.kind)}</div>
    <div class="detail-fact"><span>People</span>${esc(personNames(e.organizer_person_ids || []) || 'Not assigned')}</div>
    <div class="detail-fact"><span>Sponsors</span>${esc(sponsors.map(s=>`${s.name} (${s.status})`).join(', ') || 'Not selected')}</div>
    <div class="detail-fact"><span>Catering</span>${esc(catering ? `${catering.provider_name} (${catering.status})` : 'Not selected')}</div>
    <div class="detail-fact"><span>Attended</span>${esc(personNames(e.attendee_ids || []) || 'No attendance recorded')}</div>
    <div class="detail-fact"><span>Source documents</span>${esc((e.source_urls || []).join(', ') || 'None linked')}</div>`);
  $('venue-list').innerHTML=data.venues.map(v=>`<button class="venue-chip ${v.id===e.venue_id?'selected':''}" data-venue="${v.id}" aria-pressed="${v.id===e.venue_id}">${esc(v.name)}<small>${esc(v.location?.borough || 'Location not set')} · ${v.capacity ?? 'Unknown capacity'} people · mock</small></button>`).join('');
 $('venue-list').querySelectorAll('button').forEach(b=>b.onclick=()=>{const event=data.events.find(e=>e.venue_id===b.dataset.venue);if(event)selectEvent(event.id);});
}
function render(){
 renderMetrics();renderCalendar();renderActivity();renderDetail();renderResearch();
 $('event-select').innerHTML=data.events.map(e=>`<option value="${esc(e.id)}">${esc(e.title)}</option>`).join('');
 $('event-select').value=selectedId;
 $('event-provenance').textContent=data.events.find(e=>e.id===selectedId).is_mock ? 'Fictional sample' : 'Saved locally · draft';
}
function setupMap(){
 if(!window.L){$('map').hidden=true;$('map-fallback').hidden=false;return;}
 map=L.map('map',{scrollWheelZoom:false}).setView([40.718,-73.957],11);
 const tiles=L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap contributors'}).addTo(map);
 tiles.on('tileerror',()=>{$('map-fallback').hidden=false;});
  data.venues.forEach(v=>{
   if (!v.location) return;
  const marker=L.circleMarker([v.location.latitude,v.location.longitude],{radius:10,color:'#fff',weight:3,fillColor:'#315b45',fillOpacity:1}).addTo(map);
  marker.bindPopup(`<strong>${esc(v.name)}</strong><br>${esc(v.location.borough)} · fictional venue<br>${v.capacity} people · availability unverified`);
  marker.on('click',()=>{const e=data.events.find(e=>e.venue_id===v.id);if(e)selectEvent(e.id);});markers.set(v.id,marker);
 });
}
$('prev-month').onclick=()=>{if(--month<0){month=11;year--;}renderCalendar();};
$('next-month').onclick=()=>{if(++month>11){month=0;year++;}renderCalendar();};
$('all-events').onclick=()=>modal('All sample events',data.events.map(e=>`${date(e.starts_at)} · ${e.title}`).join('\n'));
$('plan-button').disabled=true;
$('plan-button').onclick=()=>{ $('form-error').hidden=true; $('plan-dialog').showModal(); };
document.querySelectorAll('.close-dialog').forEach(b=>b.onclick=()=>b.closest('dialog').close());
$('event-select').onchange=e=>selectEvent(e.target.value);
$('plan-form').onsubmit=async event=>{
 event.preventDefault();
 const form=event.target, values=Object.fromEntries(new FormData(form));
 const payload={title:values.title,summary:values.summary,audience:values.audience,
 starts_at:`${values.day}T${values.time}:00${values.offset}`,
 budget_usd:values.budget_usd===''?null:Number(values.budget_usd),
 registration_target:values.registration_target===''?null:Number(values.registration_target)};
 const button=form.querySelector('[type=submit]');button.disabled=true;button.textContent='Saving…';
 try {
  const response=await fetch('/api/events',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const result=await response.json();if(!response.ok)throw new Error(result.error||'Could not save draft.');
  data.events.push(result);selectEvent(result.id);form.reset();$('plan-dialog').close();
 } catch(error){$('form-error').textContent=error.message;$('form-error').hidden=false;}
 finally{button.disabled=false;button.textContent='Save event draft →';}
};
function downloadJSON(value,name){
 const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));
 const link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
$('export-brief').onclick=()=>{
 const event=data.events.find(e=>e.id===selectedId);
 downloadJSON({organization:event.is_mock?data.organization:{id:'local-organizer',name:'Local organizer',kind:'nonprofit',is_mock:false},event,
 location:'New York City',objectives:event.summary||'Identify suitable venues, sponsors, public contacts, catering, and event propositions. Flag unknowns.',max_candidates:5},'event-brief.json');
};
function safeLink(value){
 try{const url=new URL(value);return ['http:','https:'].includes(url.protocol)&&!url.username&&!url.password?url.href:null;}catch{return null;}
}
function renderResearch(){
 const report=reports.get(selectedId);
 if(!report){$('research-results').innerHTML='<div class="research-empty"><span>01 / Define the event</span><span>02 / Research five categories</span><span>03 / Review the evidence</span></div><p class="empty">No report imported for this event. Imported reports remain in this tab only.</p>';return;}
 $('research-results').innerHTML=`<div class="report-summary"><strong>Run ${esc(report.run_id)}</strong><span class="tag">${esc(report.status)}</span><span>${esc(report.generated_at)}</span></div>`+
 report.workers.map(worker=>`<details class="research-group" open><summary>${esc(worker.role)} <span class="tag">${esc(worker.status)}</span></summary>${worker.error?`<p class="empty">${esc(worker.error)}</p>`:''}${(report.findings[worker.role]||[]).map(candidate=>`<article class="candidate"><h3>${esc(candidate.name)}</h3><p>${esc(candidate.rationale)}</p><span class="tag">${esc(candidate.evidence_status||'unverified')} · proposed</span><dl>${Object.entries(candidate.details||{}).map(([k,v])=>`<dt>${esc(k.replaceAll('_',' '))}</dt><dd>${esc(typeof v==='object'?JSON.stringify(v):v)}</dd>`).join('')}</dl><div class="source-links">${(candidate.source_urls||[]).map(url=>safeLink(url)?`<a href="${esc(safeLink(url))}" target="_blank" rel="noopener noreferrer">${esc(url)} ↗</a>`:'<span>Invalid source URL omitted</span>').join('')}</div></article>`).join('')||'<p class="empty">No candidates returned.</p>'}${worker.findings?.open_questions?.length?`<div class="open-questions"><strong>Still to resolve</strong><ul>${worker.findings.open_questions.map(q=>`<li>${esc(q)}</li>`).join('')}</ul></div>`:''}</details>`).join('');
}
$('report-file').onchange=async event=>{
 const file=event.target.files[0];if(!file)return;
 try{
  if(file.size>2_000_000)throw new Error('Choose a report smaller than 2 MB.');
  const report=JSON.parse(await file.text());
  if(!report||!Array.isArray(report.workers)||typeof report.findings!=='object'||!report.findings||Array.isArray(report.findings)||!['completed','partial','failed'].includes(report.status)||typeof report.run_id!=='string')throw new Error('Choose a JSON report generated by agent_runtime.research.');
  if(!data.events.some(e=>e.id===report.event_id))throw new Error('This report belongs to an event that is not in this workspace.');
  for(const worker of report.workers){
   const candidates=report.findings[worker.role];
   if(typeof worker.role!=='string'||typeof worker.status!=='string'||!Array.isArray(candidates)||candidates.some(c=>!c||typeof c.name!=='string'||typeof c.rationale!=='string'||!Array.isArray(c.source_urls)||c.source_urls.some(u=>typeof u!=='string'))||(worker.findings?.open_questions && !Array.isArray(worker.findings.open_questions)))throw new Error('The report has invalid candidate or worker fields.');
  }
  reports.set(report.event_id,report);selectEvent(report.event_id);
  $('research-status').textContent='Report imported. Sources remain proposals; verify before making commitments.';
 }catch(error){$('research-status').textContent=error.message;}
 finally{event.target.value='';}
};
document.querySelectorAll('.nav').forEach(link=>link.onclick=()=>{document.querySelectorAll('.nav').forEach(item=>item.classList.toggle('active',item===link));});
fetch('/api/workspace').then(r=>{if(!r.ok)throw new Error('Workspace unavailable');return r.json();}).then(result=>{data=result;selectedId=data.events[0].id;render();setupMap();$('plan-button').disabled=false;$('event-select').disabled=false;$('export-brief').disabled=false;}).catch(()=>{$('load-error').hidden=false;$('load-error').textContent='Could not load the sample workspace. Start the Python app and reload this page.';});

