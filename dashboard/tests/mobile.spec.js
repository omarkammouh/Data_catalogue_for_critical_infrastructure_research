// Exercise the published HTTP-only loader, deferred full metadata and failures.
const {test,expect}=require('@playwright/test');
const fs=require('fs'),path=require('path'),http=require('http'),cp=require('child_process');
const directory=path.resolve(__dirname,'../dist-test/mobile');
let server,url;
test.beforeAll(async()=>{
 cp.execFileSync('python3',['build.py','--project','tests/fixtures','--out',path.join(directory,'index.html'),'--data-file','catalogue-data','--lazy-details','--date','2026-09-24','--no-bundle'],{cwd:path.resolve(__dirname,'..')});
 server=http.createServer((req,res)=>{
  const filename=path.resolve(directory,'.'+new URL(req.url,'http://localhost').pathname);
  const file=filename===directory?path.join(directory,'index.html'):filename;
  if(!file.startsWith(directory+path.sep)||!fs.existsSync(file)){res.writeHead(404).end();return;}
  res.setHeader('Content-Type',file.endsWith('.html')?'text/html':'application/json');fs.createReadStream(file).pipe(res);
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 url='http://127.0.0.1:'+server.address().port+'/';
});
test.afterAll(async()=>{if(server)await new Promise(resolve=>server.close(resolve));});

test('startup fetches no details; entry and both exports retain full metadata',async({page})=>{
 const requested=[];page.on('request',r=>requested.push(r.url()));
 await page.goto(url);await page.locator('#app[data-state="ready"]').waitFor();
 expect(requested.filter(x=>/records-[a-f0-9]+\.json/.test(x))).toEqual([]);
 const count=await page.evaluate(()=>window.__catalogue.engine.size);
 const source=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../dist-test/bundle.json'),'utf8'));
 expect(count).toBe(source.records.length);
 await page.goto(url+'?r=data-synth-grid-topology');await expect(page.locator('.detail')).toBeVisible();
 await expect(page.locator('.detail')).toContainText(source.records.find(r=>r.id==='data-synth-grid-topology').description);
 await page.goto(url+'?catalogues=mobility-database,hdx&catalogues.all=1');
 await page.locator('#app[data-state="ready"]').waitFor();
 for(const format of ['json','csv']){
  await page.click('#export-toggle');const pending=page.waitForEvent('download');await page.click('#export-'+format);
  const file=await (await pending).path(),text=fs.readFileSync(file,'utf8');
  if(format==='json'){
   const rows=JSON.parse(text).records;expect(rows).toEqual(source.records.filter(r=>r.id==='data-synth-grid-topology'));
   expect(rows[0].catalogue_membership_evidence).toBeTruthy();expect(rows[0]._words).toBeUndefined();
  }else expect(text).toContain('data-synth-grid-topology');
 }
});

test('failed detail load can retry and leaves search available',async({page})=>{
 let fail=true;await page.route('**/records-*.json',route=>fail?route.fulfill({status:503,body:'Unavailable'}):route.continue());
 await page.goto(url+'?r=data-synth-grid-topology');await expect(page.locator('.state.error')).toBeVisible();
 fail=false;await page.getByRole('button',{name:'Reload',exact:true}).click();await expect(page.locator('.detail')).toBeVisible();
 await page.getByRole('button',{name:'Back to results'}).click();await expect(page.locator('.card').first()).toBeVisible();
});

test('incomplete compact index never displays partial results',async({page})=>{
 await page.route('**/catalogue-data-*.json',async route=>{
  const response=await route.fetch();const body=await response.json();
  if(body.meta)body.meta.counts.total++;
  await route.fulfill({response,json:body});
 });
 await page.goto(url);await expect(page.locator('.state.error')).toBeVisible();expect(await page.locator('.card').count()).toBe(0);
});

test('leaving a pending detail page cannot replace the results',async({page})=>{
 let release;const gate=new Promise(resolve=>release=resolve);
 await page.route('**/records-*.json',async route=>{await gate;await route.continue();});
 await page.goto(url+'?r=data-synth-grid-topology');await page.locator('#app[data-state="ready"]').waitFor();
 await page.getByRole('button',{name:'Back to results'}).click();release();
 await expect(page.locator('.card').first()).toBeVisible();await expect(page.locator('.detail')).toHaveCount(0);
});

test('large filter lists create controls only for visible values',async({page})=>{
 await page.route('**/catalogue-data-*.json',async route=>{
  const response=await route.fetch(),body=await response.json();
  if(body.facets){const f=body.facets.find(f=>f.id==='provider');
   for(let i=0;i<1000;i++)f.values.push({value:'extra-'+i,label:'Extra provider '+i,count:0});}
  await route.fulfill({response,json:body});
 });
 await page.goto(url);await page.locator('#app[data-state="ready"]').waitFor();
 const facet=page.locator('details[data-facet="provider"]');
 await facet.locator('summary').click();
 expect(await facet.locator('input[data-value]').count()).toBeLessThan(20);
 await facet.getByRole('button',{name:'Show 200 more',exact:true}).click();
 expect(await facet.locator('input[data-value]').count()).toBeLessThan(220);
 await facet.getByRole('button',{name:'Show fewer',exact:true}).click();
 expect(await facet.locator('input[data-value]').count()).toBeLessThan(20);
 await facet.locator('input[type=search]').fill('Extra provider 999');
 await expect(facet.locator('input[data-value="extra-999"]')).toBeVisible();
 await expect(facet.locator('input[data-value="extra-999"]')).toBeDisabled();
 expect(await facet.locator('input[data-value]').count()).toBe(1);
});
