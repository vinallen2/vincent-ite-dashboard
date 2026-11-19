import {bindings,defineConfig} from 'cf/config';

// No public address or preview is enabled by this migration configuration.
// Enable a protected backend route only after the owner's visibility approval.
export default defineConfig({
 accountId:'061bf03211ae483522d432899df26af8',
 worker:{
  name:'vincent-ite-python',
  entrypoint:'./main.py',
  compatibilityDate:'2026-08-28',
  compatibilityFlags:['python_workers'],
  workersDev:false,
  previewUrls:false,
  env:{
   DB:bindings.d1({id:'866ed7d4-1216-4368-9490-b3636a8291f2',name:'vincent-ite-dashboard'}),
   GATEWAY_TOKEN:bindings.secret(),
   SITE_ORIGIN:bindings.text('https://vincent-ite-study-dashboard.grittypeach1026.chatgpt.site')
  }
 }
});
