import assert from 'node:assert/strict';
import {createBackendProxy} from '../gateway/proxy.mjs';
const api=createBackendProxy();
const origin='https://private.example';
const env={ITE_BACKEND_URL:'https://backend.example',ITE_BACKEND_TOKEN:'fixture-secret'};
const missing=await api.handle(new Request(origin+'/api/study'),{});
assert.equal(missing.status,503);
assert.equal(await api.handle(new Request(origin+'/'),env),null);
assert.equal((await api.handle(new Request(origin+'/api/submit',{method:'POST',headers:{origin:'https://evil.example'}}),env)).status,403);
const oldFetch=globalThis.fetch;
let forwarded;
globalThis.fetch=async(url,options)=>{forwarded={url:String(url),options};return Response.json({saved:true});};
try{
 const r=await api.handle(new Request(origin+'/api/submit',{method:'POST',headers:{'oai-authenticated-user-id':'fixture-owner','content-type':'application/json','cookie':'must-not-forward','x-ite-gateway-token':'attacker'},body:'{}'}),env);
 assert.equal(r.status,200);
 assert.equal(forwarded.url,'https://backend.example/api/submit');
 assert.equal(forwarded.options.headers.get('x-ite-gateway-token'),'fixture-secret');
 assert.equal(forwarded.options.headers.get('oai-authenticated-user-id'),'fixture-owner');
 assert.equal(forwarded.options.headers.get('cookie'),null);
 assert.equal(r.headers.get('x-ite-gateway-token'),null);
 assert.equal((await api.handle(new Request(origin+'/api/other'),env)).status,404);
 globalThis.fetch=async()=>{throw new Error('Fixture failure');};
 assert.equal((await api.handle(new Request(origin+'/api/study'),env)).status,503);
}finally{globalThis.fetch=oldFetch;}
console.log('Private gateway authentication, header isolation, origin rejection and failure handling passed.');
