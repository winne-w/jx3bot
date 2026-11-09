const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const path = require('path');
// Run with Node; this exercises the exact page functions without browser or network.
const root = path.resolve(__dirname, '../../..');
const html = fs.readFileSync(path.join(root,'public/jjc-synced-matches.html'),'utf8');
const functions = html.slice(html.indexOf('        async function loadMoreMatches()'),html.indexOf('        function pollLatestMatches('));
function setup(){
  const buttons = new Map();
  const ctx = vm.createContext({console, URLSearchParams, Promise, requests:[], rows:['page1','page2'], statuses:[], latestRefresh:{state:'disabled',enabled:false}, currentRole:{server:'梦江南',name:'角色甲'}, currentPagination:{page:2,hasMore:true,isLoading:false}, refreshGeneration:0, searchToken:1, refreshInFlight:false,pageSize:20,syncedMatchesApiBase:'list',syncedRefreshApiBase:'refresh', document:{getElementById(id){if(!buttons.has(id))buttons.set(id,{disabled:false,textContent:''});return buttons.get(id);}},stopLatestPolling(){ctx.refreshGeneration++;ctx.refreshInFlight=false;},buildGetUrl(base,server,name,query){return {base,server,name,...query};},fetchJson(url,options){return new Promise((resolve,reject)=>ctx.requests.push({url,options,resolve,reject}));},renderMatches(data,append){ctx.rows=append?[...ctx.rows,...data.rows]:data.rows;ctx.currentPagination={page:data.page,hasMore:true,isLoading:false};},setStatus(message){ctx.statuses.push(message);},latestStatusText(){return 'disabled';},pollLatestMatches(){}});
  vm.runInContext(functions,ctx);
  return ctx;
}
const response=(page)=>({rows:['page'+page],page});
async function flush(){await Promise.resolve();await Promise.resolve();}
const results=[];
async function run(name,fn){try{await fn();results.push({case:name,result:'PASS'});}catch(e){results.push({case:name,result:'FAIL',error:e.message});}}
(async()=>{
 await run('refresh then more cannot produce page1 plus page3',async()=>{
  const c=setup();const refreshing=c.refreshCurrentMatches();const more=c.loadMoreMatches();
  assert.equal(c.requests[0].url.page,1);
  const third=c.requests.find(r=>r.url.page===3);
  c.requests[0].resolve(response(1));await refreshing;
  if(third)third.resolve(response(3));await more;
  assert.ok(!(c.rows.includes('page3')&&!c.rows.includes('page2')),JSON.stringify({rows:c.rows,requests:c.requests.map(r=>r.url.page)}));
 });
 await run('more then refresh waits for pagination before refreshing',async()=>{
  const c=setup();const more=c.loadMoreMatches();const refresh=c.refreshCurrentMatches();
  assert.equal(c.requests[0].url.page,3);
  const first=c.requests.find(r=>r.url.page===1);
  if(first){first.resolve(response(1));await refresh;}
  c.requests[0].resolve(response(3));await more;await refresh;
  assert.ok(!(c.rows.includes('page3')&&!c.rows.includes('page2')),JSON.stringify({rows:c.rows,requests:c.requests.map(r=>r.url.page)}));
 });
 await run('old role more response cannot append to new role',async()=>{
  const c=setup();const more=c.loadMoreMatches();
  c.searchToken++;c.refreshGeneration++;c.currentRole={server:'梦江南',name:'角色乙'};c.rows=['new-role-page1'];c.currentPagination={page:1,hasMore:true,isLoading:false};
  c.requests[0].resolve(response(3));await more;
  assert.deepEqual(Array.from(c.rows),['new-role-page1']);assert.equal(c.currentPagination.page,1);
 });
 await run('old role more failure cannot alter new pagination state',async()=>{
  const c=setup();const more=c.loadMoreMatches();
  c.searchToken++;c.refreshGeneration++;c.currentRole={server:'梦江南',name:'角色乙'};c.rows=['new-role-page1'];c.currentPagination={page:1,hasMore:true,isLoading:true};
  c.requests[0].reject(Error('network unavailable'));await more;
  assert.equal(c.currentPagination.isLoading,true);
 });
 console.log(JSON.stringify({source:path.join(root,'public/jjc-synced-matches.html'),results},null,2));
 if(results.some(r=>r.result==='FAIL'))process.exitCode=1;
})();
