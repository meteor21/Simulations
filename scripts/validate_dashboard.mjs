#!/usr/bin/env node
// Exercise the self-contained dashboard in Chromium without third-party JS packages.
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, writeFile, mkdir, rm, access} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {createServer} from 'node:http';
import path from 'node:path';

const args=Object.fromEntries(process.argv.slice(2).reduce((pairs,item,index,all)=>{
  if(index%2===0)pairs.push([item,all[index+1]]);return pairs;
},[]));
assert(args['--site']&&args['--report'],'Use --site DIR --report JSON [--screenshots DIR]');
const site=path.resolve(args['--site']), reportPath=path.resolve(args['--report']);
const data=JSON.parse(await readFile(path.join(site,'data.json'),'utf8'));
let executable=process.env.CHROMIUM_PATH;
if(!executable){for(const option of ['/usr/bin/chromium','/usr/bin/google-chrome','/opt/google/chrome/chrome']){
  try{await access(option);executable=option;break}catch{}
}}
assert(executable,'Chromium/Google Chrome is required for dashboard browser validation');
const profile=await mkdtemp(path.join(tmpdir(),'midterm-dashboard-browser-'));
const errors=[], checks=[], requests=[];
// Serve only the public generated site. Local file navigation is disabled by
// some managed browsers; HTTP matches the actual Pages deployment environment.
const allowed=new Set(['index.html','data.json','candidate_coverage.csv','coverage.svg','pipeline.svg','budget.svg','README.md']);
const server=createServer(async(req,res)=>{
 const name=new URL(req.url,'http://localhost').pathname.slice(1)||'index.html';
 if(!allowed.has(name)){res.writeHead(404);res.end();return}
 try{const content=await readFile(path.join(site,name));const type=name.endsWith('.html')?'text/html':name.endsWith('.json')?'application/json':name.endsWith('.svg')?'image/svg+xml':'text/plain';res.writeHead(200,{'Content-Type':type+'; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});res.end(content)}catch{res.writeHead(404);res.end()}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const origin='http://127.0.0.1:'+server.address().port;
const browser=spawn(executable,['--headless=new','--no-sandbox','--disable-dev-shm-usage',
  '--disable-background-networking','--no-first-run','--no-default-browser-check',
  '--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{stdio:['ignore','ignore','pipe']});
let ws;
try{
 const endpoint=await new Promise((resolve,reject)=>{
  const timer=setTimeout(()=>reject(new Error('Chromium did not start within 20 seconds')),20000);
  let stderr='';
  browser.once('error',error=>{clearTimeout(timer);reject(error)});
  browser.once('exit',code=>{clearTimeout(timer);reject(new Error('Chromium exited before readiness: '+code))});
  browser.stderr.on('data',chunk=>{stderr+=chunk.toString();const match=stderr.match(/DevTools listening on (ws:\/\/[^\s]+)/);if(match){clearTimeout(timer);resolve(match[1])}});
 });
 ws=new WebSocket(endpoint);await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject});
 let sequence=0, sessionId;const pending=new Map();
 ws.onmessage=event=>{const message=JSON.parse(event.data);if(message.id){const waiting=pending.get(message.id);if(waiting){pending.delete(message.id);clearTimeout(waiting.timer);message.error?waiting.reject(new Error(message.error.message)):waiting.resolve(message.result)}}
  else if(message.method==='Runtime.exceptionThrown')errors.push(message.params.exceptionDetails.text+' '+(message.params.exceptionDetails.exception?.description||''));
  else if(message.method==='Network.requestWillBeSent')requests.push(message.params.request.url);
 };
 const send=(method,params={},withSession=true)=>new Promise((resolve,reject)=>{
  const id=++sequence;const timer=setTimeout(()=>{pending.delete(id);reject(new Error('Timed out: '+method))},20000);
  pending.set(id,{resolve,reject,timer});ws.send(JSON.stringify({id,method,params,...(withSession&&sessionId?{sessionId}:{})}));
 });
 const target=await send('Target.createTarget',{url:'about:blank'},false);
 sessionId=(await send('Target.attachToTarget',{targetId:target.targetId,flatten:true},false)).sessionId;
 await send('Runtime.enable');await send('Page.enable');await send('Network.enable');
 const evaluate=async expression=>{const result=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw new Error(result.exceptionDetails.text);return result.result.value};
 await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1080,deviceScaleFactor:1,mobile:false});
 const navigation=await send('Page.navigate',{url:origin+'/index.html'});
 assert(!navigation.errorText,'Dashboard navigation failed: '+navigation.errorText);
 for(let i=0;i<100;i++){if(await evaluate('window.__dashboardReady===true'))break;await new Promise(resolve=>setTimeout(resolve,50))}
 const ready=await evaluate('window.__dashboardReady');
 if(!ready)console.error('Dashboard browser state:',await evaluate('JSON.stringify({url:location.href,title:document.title,scriptCount:document.scripts.length,body:document.body?.textContent.slice(0,300)})'));
 assert.equal(ready,true,'Dashboard JS did not initialize');
 const check=(name,actual,expected)=>{assert.deepEqual(actual,expected,name);checks.push(name)};
 check('all selected candidates render',await evaluate('document.querySelectorAll("[data-candidate-row]").length'),data.candidates.length);
 check('saved URL count agrees with data',await evaluate('document.querySelector("#stat-articles").textContent'),String(data.summary.article_urls));
 check('missing scores are not filled with neutral values',await evaluate('document.querySelectorAll(".score-missing").length'),data.candidates.filter(c=>c.features.media_recency_score===null).length);
 const first=data.candidates[0];
 await evaluate(`document.querySelector('#candidate-search').value=${JSON.stringify(first.candidate_id)};document.querySelector('#candidate-search').dispatchEvent(new Event('input'))`);
 check('search selects the intended identity',await evaluate('Array.from(document.querySelectorAll("[data-candidate-row]")).map(x=>x.dataset.candidateRow)'),[first.candidate_id]);
 await evaluate('document.querySelector(".candidate-open").click()');
 check('candidate evidence opens',await evaluate('!document.querySelector("#candidate-detail").hidden'),true);
 check('opened candidate evidence is visible',await evaluate('(()=>{const r=document.querySelector("#candidate-detail").getBoundingClientRect();return r.top>=0&&r.top<window.innerHeight})()'),true);
 check('candidate detail preserves review warning',await evaluate('document.querySelector("#candidate-detail").textContent.includes("search associations")'),true);
 await evaluate('document.querySelector("#candidate-search").value="NONEXISTENT-CANDIDATE-XYZ";document.querySelector("#candidate-search").dispatchEvent(new Event("input"))');
 check('empty filters show an explicit empty state',await evaluate('!document.querySelector("#candidate-empty").hidden'),true);
 await evaluate('document.querySelector("#candidate-search").value="";document.querySelector("#candidate-search").dispatchEvent(new Event("input"))');
 await evaluate(`document.querySelector('#state-filter').value=${JSON.stringify(first.state)};document.querySelector('#state-filter').dispatchEvent(new Event('change'))`);
 check('state filter changes the cohort view',await evaluate('document.querySelectorAll("[data-candidate-row]").length'),data.candidates.filter(c=>c.state===first.state).length);
 await evaluate('document.querySelector("#state-filter").value="";document.querySelector("#state-filter").dispatchEvent(new Event("change"))');
 await evaluate('document.querySelector("[data-unit=candidates]").click()');
 check('coverage can switch to candidate counts',await evaluate('document.querySelector("[data-unit=candidates]").getAttribute("aria-pressed")'),'true');
 await evaluate('document.querySelector("[data-unit=urls]").click();document.querySelector("[data-source-mode=all]").click()');
 check('source catalog includes all public profiles',await evaluate('document.querySelectorAll(".source-card").length'),data.sources.length);
 await evaluate('document.querySelector("[data-source-mode=attempted]").click()');
 check('source lookup view excludes unrequested profiles',await evaluate('document.querySelectorAll(".source-card").length'),data.sources.filter(s=>s.resolution_status!=='not_requested').length);
 check('desktop has no document overflow',await evaluate('document.documentElement.scrollWidth<=window.innerWidth'),true);
 const screenshot=async name=>{if(args['--screenshots']){await mkdir(args['--screenshots'],{recursive:true});const result=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});await writeFile(path.join(args['--screenshots'],name+'.png'),Buffer.from(result.data,'base64'))}};
 await evaluate('window.scrollTo({top:0,behavior:"instant"})');
 await screenshot('desktop');
 await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
 await evaluate('window.scrollTo(0,0)');await new Promise(resolve=>setTimeout(resolve,150));
 check('mobile has no document overflow',await evaluate('document.documentElement.scrollWidth<=window.innerWidth'),true);
 check('mobile retains all candidate rows',await evaluate('document.querySelectorAll("[data-candidate-row]").length'),data.candidates.length);
 await screenshot('mobile');
 check('no page script errors',errors,[]);
 check('no external data, CDN, or provider requests',requests.filter(url=>!url.startsWith(origin+'/')&&!url.startsWith('data:')),[]);
 await mkdir(path.dirname(reportPath),{recursive:true});
 await writeFile(reportPath,JSON.stringify({status:'passed',checks,selected_candidates:data.candidates.length,
  article_urls:data.summary.article_urls,external_page_requests:0,script_errors:errors,
  source_run_id:data.provenance.source_run_id,analysis_run_id:data.provenance.analysis_run_id},null,2)+'\n');
 console.log(JSON.stringify({status:'passed',browser_checks:checks.length,selected_candidates:data.candidates.length,external_page_requests:0}));
}catch(error){
 await mkdir(path.dirname(reportPath),{recursive:true});
 await writeFile(reportPath,JSON.stringify({status:'failed',checks,script_errors:errors,error:String(error)},null,2)+'\n');
 if(errors.length)console.error(JSON.stringify({script_errors:errors}));
 throw error;
}finally{
 if(ws)ws.close();browser.kill('SIGTERM');
 await new Promise(resolve=>server.close(resolve));
 await new Promise(resolve=>{if(browser.exitCode!==null)return resolve();browser.once('exit',resolve);setTimeout(resolve,3000)});
 await rm(profile,{recursive:true,force:true});
}
