/** Backend transport only. The existing Sites audience remains owner-private. */
export function createBackendProxy(){
 return {async handle(request,env){
  const url=new URL(request.url);
  if(!url.pathname.startsWith('/api/'))return null;
  const headers={'cache-control':'private, no-store, max-age=0','x-content-type-options':'nosniff'};
  if(!env.ITE_BACKEND_URL||!env.ITE_BACKEND_TOKEN)return Response.json({error:'Private backend is not configured. No answers have been saved.'},{status:503,headers});
  const origin=request.headers.get('origin');
  if((origin&&origin!==url.origin)||request.headers.get('sec-fetch-site')==='cross-site')return Response.json({error:'Same-origin request required.'},{status:403,headers});
  const allowed=['/api/study','/api/data','/api/workflow','/api/agent','/api/submit'];
  if(!allowed.includes(url.pathname))return Response.json({error:'Not found.'},{status:404,headers});
  const target=new URL(env.ITE_BACKEND_URL);
  if(target.protocol!=='https:'||target.username||target.password||target.pathname!=='/'||target.search||target.hash)return Response.json({error:'Invalid backend configuration.'},{status:503,headers});
  target.pathname=url.pathname;
  const forward=new Headers({'x-ite-gateway-token':env.ITE_BACKEND_TOKEN});
  for(const key of ['content-type','origin','sec-fetch-site','oai-authenticated-user-id'])if(request.headers.has(key))forward.set(key,request.headers.get(key));
  try{
   const upstream=await fetch(target,{method:request.method,headers:forward,body:['GET','HEAD'].includes(request.method)?undefined:request.body,redirect:'error',signal:AbortSignal.timeout(20000)});
   return new Response(upstream.body,{status:upstream.status,headers:{...headers,'content-type':'application/json'}});
  }catch{return Response.json({error:'Study storage is temporarily unavailable. Retry checks your saved first attempt before creating one.'},{status:503,headers});}
 }};
}
