/** Compile the recovered UI, with the existing private Site as gateway. */
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {analyze} from '../frontend/analytics.mjs';
import {client} from '../frontend/client.mjs';
import {studyClient} from '../frontend/study-client.mjs';
import {createStudyMcp} from '../frontend/study-mcp.mjs';
import {createBackendProxy} from '../gateway/proxy.mjs';
const read=path=>readFile(new URL('../frontend/'+path,import.meta.url),'utf8');
const analytics=(await read('dashboard.html')).replace('/*APP_SCRIPT*/',analyze.toString()+'\n('+client.toString()+')();');
const study=(await read('study.html')).replace('/*STUDY_SCRIPT*/',analyze.toString()+'\n('+studyClient.toString()+')();');
const code=`const page=${JSON.stringify(analytics)},studyPage=${JSON.stringify(study)},api=(${createBackendProxy.toString()})(),mcp=(${createStudyMcp.toString()})(api);
export default {async fetch(request,env){
 const url=new URL(request.url),headers={'cache-control':'private, no-store, max-age=0','x-content-type-options':'nosniff','referrer-policy':'same-origin'};
 if(url.pathname==='/mcp')return mcp(request,env);
 const response=await api.handle(request,env);if(response)return response;
 if(!['GET','HEAD'].includes(request.method))return new Response('Method not allowed',{status:405,headers});
 if(url.pathname==='/favicon.ico')return new Response(null,{status:204,headers});
 if(!['/','/analytics'].includes(url.pathname))return new Response('Not found',{status:404,headers});
 return new Response(request.method==='HEAD'?null:url.pathname==='/'?studyPage:page,{headers:{...headers,'content-type':'text/html; charset=utf-8','content-security-policy':"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'self'"}});
}};`;
await mkdir(new URL('../dist/server/',import.meta.url),{recursive:true});
await writeFile(new URL('../dist/server/index.js',import.meta.url),code);
console.log('Built recovered UI and private gateway. No deployment or source data included.');
