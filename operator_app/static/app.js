/* Read-only mock workspace. All state derives from the Python models/API. */
'use strict';
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
 ['Funding secured',money(event.funding_secured_usd),`of ${money(event.budget_usd)} sample budget`,event.budget_usd ? event.funding_secured_usd/event.budget_usd : 0],
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
  if(event) selectEvent(event.id,false); else modal('No sample events',`There are no events in this demo on ${b.dataset.day}. Event creation is planned for a future iteration.`);
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
  $('event-detail').innerHTML=`<div class="detail-content"><span class="tag">${esc(e.status.toUpperCase())}</span><h3>${esc(e.title)}</h3><p>${esc(e.summary)}</p><div class="detail-fact"><span>When</span>${esc(date(e.starts_at))} · ${esc(time(e.starts_at))} ET</div><div class="detail-fact"><span>Venue</span>${esc(v?.name||'Not selected')}</div><div class="detail-fact"><span>Availability</span>Unverified · mock venue</div><p>${esc(e.audience)}</p><strong>What this could enable</strong><ul>${e.intended_outcomes.map(o=>`<li>${esc(o)}</li>`).join('')}</ul><div class="next-action"><strong>Next action</strong><br>Confirm resources and define the evidence you will collect before making commitments.</div></div>`;
  $('event-detail').querySelector('.detail-content').insertAdjacentHTML('beforeend',
    `<h4>Event ecosystem</h4><div class="detail-fact"><span>Organizer</span>${esc(data.organization.name)} · ${esc(data.organization.kind)}</div>
    <div class="detail-fact"><span>People</span>${esc(personNames(e.organizer_person_ids || []) || 'Not assigned')}</div>
    <div class="detail-fact"><span>Sponsors</span>${esc(sponsors.map(s=>`${s.name} (${s.status})`).join(', ') || 'Not selected')}</div>
    <div class="detail-fact"><span>Catering</span>${esc(catering ? `${catering.provider_name} (${catering.status})` : 'Not selected')}</div>
    <div class="detail-fact"><span>Attended</span>${esc(personNames(e.attendee_ids || []) || 'No attendance recorded')}</div>
    <div class="detail-fact"><span>Source documents</span>${esc((e.source_urls || []).join(', ') || 'None linked')}</div>`);
  $('venue-list').innerHTML=data.venues.map(v=>`<button class="venue-chip ${v.id===e.venue_id?'selected':''}" data-venue="${v.id}" aria-pressed="${v.id===e.venue_id}">${esc(v.name)}<small>${esc(v.location?.borough || 'Location not set')} · ${v.capacity ?? 'Unknown capacity'} people · mock</small></button>`).join('');
 $('venue-list').querySelectorAll('button').forEach(b=>b.onclick=()=>{const event=data.events.find(e=>e.venue_id===b.dataset.venue);if(event)selectEvent(event.id);});
}
function render(){renderMetrics();renderCalendar();renderActivity();renderDetail();}
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
$('plan-button').onclick=()=>modal('Plan your next event','Explore the proposed Community Energy & Resilience Workshop on November 14. It links a nonprofit organizer, candidate sponsor, catering plan, and the DOE Solar Energy source. Timing and resources are illustrative.\n\nEvent editing and booking are not connected in this preview.');
document.querySelectorAll('.close-dialog').forEach(b=>b.onclick=()=>$('detail-dialog').close());
fetch('/api/workspace').then(r=>{if(!r.ok)throw new Error('Workspace unavailable');return r.json();}).then(result=>{data=result;render();setupMap();}).catch(()=>{$('load-error').hidden=false;$('load-error').textContent='Could not load the sample workspace. Start the Python app and reload this page.';});
