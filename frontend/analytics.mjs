export function analyze(data, f = {}, today = new Intl.DateTimeFormat('en-CA', {timeZone:'America/New_York'}).format(new Date())) {
  const rows=n=>(data.tabs[n]||[]).slice(1).map((r,i)=>({r,row:i+2})).filter(x=>x.r.some(v=>v!==null&&v!==''));
  const sum=(a,k)=>a.reduce((n,x)=>n+x[k],0), issues=[],seen=new Set();
  const questions=rows('Question Log').flatMap(({r,row})=>{
    const [date,set,number,domain,topic,answer,key,result,confidence,error,notes]=r,id=[date,set,number].join('|');
    if(!/^\d{4}-\d{2}-\d{2}$/.test(date||'')||!set||!number||!['0','1'].includes(String(result))||!answer||!key){issues.push('Incomplete Question Log row '+row);return [];}
    if(seen.has(id)){issues.push('Duplicate Question Log row '+row);return [];}seen.add(id);
    if((answer===key)!==(String(result)==='1')){issues.push('Conflicting score at row '+row);return [];}
    const series=/^CA2-(New|Bonus)\b/.test(set)&&/series=CA2-New/.test(notes||'')&&/attempt=1\b/.test(notes||'')?'new':/^CA2-Review\b/.test(set)?'review':'history';
    const canonical=/gradient/i.test(topic)?'A–a gradient':/adrenal/i.test(topic)?'Adrenal insufficiency / crisis':/LVOT/i.test(topic)?'Dynamic LVOT obstruction':topic;
    return [{date,set,number,domain,topic,canonical,answer,key,correct:+result,confidence:confidence||'Not recorded',error:error||'Not recorded',notes:notes||'',difficulty:(notes||'').match(/difficulty=(application|integration)/)?.[1]||null,level:(notes||'').match(/level=(basic|advanced)/)?.[1]||null,series,row}];
  });
  const ss=new Set();
  const sessions=rows('Sessions').map(({r,row})=>({date:r[0],name:r[1],status:r[2],total:+r[3],correct:+r[4],complete:r[5]==='Yes',notes:r[7]||'',row})).filter(s=>{
    if(s.status!=='Verified')return true;const k=s.date+'|'+s.name;
    if(ss.has(k)||!Number.isInteger(s.total)||s.total<=0||!Number.isInteger(s.correct)||s.correct<0||s.correct>s.total){issues.push('Invalid or duplicate Sessions row '+s.row);return false;}ss.add(k);return true;
  });
  const verified=sessions.filter(s=>s.status==='Verified'),total=sum(verified,'total'),correct=sum(verified,'correct');
  const inDate=d=>(!f.from||d>=f.from)&&(!f.to||d<=f.to);
  const match=t=>!f.topic||String(t).toLowerCase().includes(f.topic.toLowerCase());
  const selected=questions.filter(q=>inDate(q.date)&&match(q.domain+' '+q.topic+' '+q.canonical)&&(!f.series||q.series===f.series));
  const itemScope=!!(f.topic||f.series), ds=verified.filter(s=>inDate(s.date));
  const selectedTotal=itemScope?selected.length:sum(ds,'total'),selectedCorrect=itemScope?sum(selected,'correct'):sum(ds,'correct');
  const shift=(d,n)=>{const x=new Date(d+'T12:00:00Z');x.setUTCDate(x.getUTCDate()+n);return x.toISOString().slice(0,10);};
  const days=[...new Set(verified.filter(s=>s.complete&&/^\d{4}-\d{2}-\d{2}$/.test(s.date)).map(s=>s.date))].sort();
  let run=0,longest=0;days.forEach((d,i)=>{run=i&&shift(days[i-1],1)===d?run+1:1;longest=Math.max(longest,run);});
  const lastDay=days.at(-1),current=lastDay===today||lastDay===shift(today,-1)?run:0;
  const domains=[...new Set(selected.map(q=>q.domain))].map(name=>{const a=selected.filter(q=>q.domain===name);return {name,total:a.length,correct:sum(a,'correct')};}).sort((a,b)=>a.correct/a.total-b.correct/b.total);
  const topics=[...new Set(selected.map(q=>q.canonical))].map(name=>{const a=selected.filter(q=>q.canonical===name);return {name,total:a.length,correct:sum(a,'correct'),last:a.at(-1),misses:a.filter(q=>!q.correct)};}).sort((a,b)=>a.correct/a.total-b.correct/b.total);
  const trends=[...new Set(selected.map(q=>q.date))].sort().map(date=>{const a=selected.filter(q=>q.date===date);return {date,total:a.length,correct:sum(a,'correct')};});
  const reviewMatch=t=>match(t)||({Respiratory:/gradient|V\/Q|TRALI/i,Cardiovascular:/LVOTO|carotid/i,Endocrine:/adrenal/i,'Pharmacology / neuromuscular':/TOF|blockade|myasthenia|LAST/i,'Obstetric anesthesia':/obstetric|spinal hypotension/i,'Dynamic LVOT obstruction':/LVOTO/i,'Adrenal insufficiency / crisis':/adrenal/i,'Residual neuromuscular blockade in MG':/TOF|blockade|myasthenia/i,'Spinal hypotension with bradycardia':/spinal hypotension/i}[f.topic]?.test(t));
  const review=rows('Review Queue').map(({r,row})=>({date:r[0]||'',topic:r[1],reason:r[2],method:r[3],status:r[4],last:r[5],next:r[6],row})).filter(r=>reviewMatch(r.topic+' '+r.reason)&&(!r.date||inDate(r.date)));
  const planned=review.filter(r=>r.status==='Planned').sort((a,b)=>a.date.localeCompare(b.date)),due=planned.filter(r=>r.date&&r.date<=today),backlog=review.filter(r=>r.status==='Backlog');
  const errors=[...new Set(selected.filter(q=>!q.correct).map(q=>q.error))].map(name=>({name,total:selected.filter(q=>!q.correct&&q.error===name).length}));
  const checks=[
    {name:'Database score totals',pass:String(total)===String(data.tabs.Dashboard?.[4]?.[1])&&String(correct)===String(data.tabs.Dashboard?.[5]?.[1]),detail:correct+' / '+total+' verified'},
    {name:'Logged sets ↔ verified session scores',pass:verified.filter(s=>questions.some(q=>q.set===s.name)).every(s=>{const a=questions.filter(q=>q.set===s.name);return a.length===s.total&&sum(a,'correct')===s.correct;}),detail:questions.length+' individual records reconciled'},
    {name:'Distinct recorded completion dates',pass:days.length===Number(data.tabs.Dashboard?.[7]?.[1]),detail:days.length+' recorded completion dates'},
    {name:'Row integrity',pass:issues.length===0,detail:issues.length?issues.join('; '):'No duplicate or conflicting graded rows'}
  ];
  return {total,correct,questions,sessions,selected,selectedTotal,selectedCorrect,itemScope,days,current,longest,lastDay,domains,topics,trends,review,planned,due,backlog,errors,checks,issues,pending:sessions.filter(s=>s.status!=='Verified').length,aggregateOnly:total-questions.length,today};
}
