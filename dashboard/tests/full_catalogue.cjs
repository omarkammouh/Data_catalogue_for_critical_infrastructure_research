/* Full-catalogue checks against the same static files used by Pages. */
const {chromium,expect}=require('@playwright/test');
const fs=require('fs'),path=require('path'),http=require('http'),assert=require('assert');
const root=path.resolve(__dirname,'../..'),dist=path.join(root,'dashboard/dist');
const prefix='/Data_catalogue_for_critical_infrastructure_research/';
(async()=>{
 fs.mkdirSync(path.join(root,'.local'),{recursive:true});
 const html=fs.readFileSync(path.join(dist,'index.html'),'utf8');
 const parts=html.match(/data-src="([^"]+)"/)[1].split(' ');
 const bundle=JSON.parse(parts.map(x=>fs.readFileSync(path.join(dist,x),'utf8')).join(''));
 const snapshot=JSON.parse(fs.readFileSync(path.join(root,'catalog/snapshot.json')));
 assert.equal(bundle.records.length,snapshot.records);
 const server=http.createServer((req,res)=>{
  const pathname=new URL(req.url,'http://localhost').pathname;
  if(!pathname.startsWith(prefix)){res.writeHead(404).end();return;}
  const file=path.resolve(dist,decodeURIComponent(pathname.slice(prefix.length)||'index.html'));
  if(!file.startsWith(dist+path.sep)){res.writeHead(403).end();return;}
  if(!fs.existsSync(file)){res.writeHead(404).end();return;}
  res.setHeader('Content-Type',file.endsWith('.html')?'text/html':'application/json');fs.createReadStream(file).pipe(res);
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const local=`http://127.0.0.1:${server.address().port}${prefix}`;
 const url=process.env.CATALOGUE_URL||local;
 const browser=await chromium.launch();
 const context=await browser.newContext({viewport:{width:1440,height:960},colorScheme:'light'});
 const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
 const started=Date.now();
 try{
  await page.goto(url);await page.locator('#app[data-state="ready"]').waitFor({timeout:180000});
  const loadMs=Date.now()-started;
  assert.equal(await page.evaluate(()=>window.__catalogue.engine.size),snapshot.records);
  await expect(page.locator('#summary')).toContainText(snapshot.records.toLocaleString('en-US'));
  await page.locator('#app[data-text-index="ready"]').waitFor({timeout:180000});
  const cases=[];
  for(const type of ['data','model','platform','case_study'])for(const country of ['', 'NL','DE','US']){
   const facets={type:{values:[type],all:false}};if(country)facets.countries={values:[country],all:false};
   const ids=bundle.records.filter(r=>r.type===type&&(!country||(r.countries||[]).includes(country))).map(r=>r.id).sort();
   cases.push({state:{facets,text:'',sort:'name',dir:'asc'},ids});
  }
  const queries=[];
  for(const c of cases){const result=await page.evaluate(state=>{const r=window.__catalogue.engine.query(state);return {ids:r.ids,ms:r.ms};},c.state);assert.deepEqual(result.ids.sort(),c.ids);queries.push(result.ms);}
  fs.mkdirSync(path.join(root,'docs/images'),{recursive:true});
  if(!process.env.CATALOGUE_URL)await page.screenshot({animations:'disabled',path:path.join(root,'docs/images/dashboard.png')});
  await page.goto(url+'?type=model&sectors=energy.electricity');await page.locator('#app[data-state="ready"]').waitFor({timeout:180000});
  const expected=await page.locator('#summary').innerText();await page.reload();await page.locator('#app[data-state="ready"]').waitFor({timeout:180000});assert.equal(await page.locator('#summary').innerText(),expected);
  await page.locator('#q').fill('pandapower');await page.locator('#q').press('Enter');await expect(page.locator('.card').first()).toBeVisible();
  await page.click('#export-toggle');const download=page.waitForEvent('download');await page.click('#export-json');const file=await (await download).path();const exported=JSON.parse(fs.readFileSync(file,'utf8'));assert((exported.records||[]).length>0);
  await page.goto(url+'?r=model-epanet');await page.locator('#app[data-state="ready"]').waitFor({timeout:180000});await expect(page.locator('.detail')).toContainText('EPANET');
  await page.emulateMedia({colorScheme:'dark'});await page.screenshot({animations:'disabled',path:path.join(root,'.local/full-dark.png')});
  await page.setViewportSize({width:390,height:844});await page.screenshot({animations:'disabled',path:path.join(root,'.local/full-mobile.png')});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'Horizontal overflow at phone width');
  const axe=fs.readFileSync(require.resolve('axe-core/axe.min.js'),'utf8');await page.addScriptTag({content:axe});
  const violations=await page.evaluate(async()=> (await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}})).violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.length})));
  assert.deepEqual(violations,[]);
  assert.deepEqual(errors,[]);
  // One failed part must not leave a partial catalogue on screen.
  const broken=await context.newPage();await broken.route('**/catalogue-data-1.json',route=>route.fulfill({status:503,body:'Unavailable'}));await broken.goto(url);await expect(broken.locator('.state.error')).toBeVisible({timeout:60000});await expect(broken.getByRole('button',{name:'Reload',exact:true})).toBeVisible();assert.equal(await broken.locator('.card').count(),0);await broken.close();
  queries.sort((a,b)=>a-b);const report={url,records:snapshot.records,load_ms:loadMs,reference_queries:queries.length,query_median_ms:queries[Math.floor(queries.length/2)],query_max_ms:queries.at(-1),console_errors:errors,accessibility_violations:violations,checks:['URL reload','search','JSON export','record details','dark','mobile','missing chunk']};
  fs.writeFileSync(path.join(root,'.local',process.env.CATALOGUE_URL?'live-browser.json':'full-browser.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
 }finally{await browser.close();server.close();}
})().catch(e=>{console.error(e);process.exit(1)});
