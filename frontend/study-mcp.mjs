export function createStudyMcp(api){
 const actions=['context','publish_session','record_answers','mark_reviewed','plan_reviews','record_article','heartbeat'];
 return async function(request,env){
  const reply=(x,status=200)=>Response.json(x,{status,headers:{'cache-control':'no-store'}});
  if(request.method!=='POST')return reply({error:'POST required'},405);
  if(!request.headers.get('oai-authenticated-user-id'))return reply({error:'Sign in to the private study site.'},401);
  let p;try{const raw=await request.text();if(raw.length>250000)return reply({error:'Request too large'},413);p=JSON.parse(raw);}catch{return reply({jsonrpc:'2.0',id:null,error:{code:-32700,message:'Invalid JSON'}});}
  const ok=result=>reply({jsonrpc:'2.0',id:p.id??null,result});
  const fail=(code,message)=>reply({jsonrpc:'2.0',id:p.id??null,error:{code,message}});
  if(p.method==='server/discover')return ok({supportedVersions:['2026-07-28'],capabilities:{tools:{}}});
  if(p.method==='initialize')return ok({protocolVersion:p.params?.protocolVersion||'2026-07-28',capabilities:{tools:{}},serverInfo:{name:'Vincent ITE Study',version:'1.0.0'}});
  if(p.method?.startsWith('notifications/'))return new Response(null,{status:202});
  if(p.method==='ping')return ok({});
  if(p.method==='tools/list')return ok({tools:[{
   name:'ite_study',description:'Read or update Vincent’s private ITE database. Call context first for current records and complete action schemas. Publish the exact session before presenting its quiz in chat. When the user answers that stored set in ChatGPT, call record_answers with actual selections, then context to verify the saved result. Never infer answers, invent missing question text, overwrite first attempts, or claim synchronization without readback. The historical Google Sheet is archived.',
   inputSchema:{type:'object',properties:{action:{type:'string',enum:actions},payload:{description:'Action payload from workflow.actions returned by context; omitted for context.',anyOf:[{type:'object',additionalProperties:true},{type:'array',items:{type:'object',additionalProperties:true}}]}},required:['action'],additionalProperties:false}
  }]});
  if(p.method==='tools/call'){
   if(p.params?.name!=='ite_study'||!actions.includes(p.params?.arguments?.action))return fail(-32602,'Unknown tool or action');
   const headers=new Headers(request.headers);headers.delete('content-length');headers.set('content-type','application/json');
   const r=await api.handle(new Request(new URL('/api/agent',request.url),{method:'POST',headers,body:JSON.stringify(p.params.arguments)}),env);
   return ok({content:[{type:'text',text:await r.text()}],isError:!r.ok});
  }
  return fail(-32601,'Method not found');
 };
}
