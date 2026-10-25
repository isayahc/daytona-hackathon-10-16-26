/* Optional end-to-end check. Start the server with a disposable --database first. */
const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:1080}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(process.env.OPERATOR_URL || 'http://127.0.0.1:8080');await page.waitForFunction(()=>!document.querySelector('#plan-button').disabled);
 await page.getByRole('button',{name:'Plan an event',exact:false}).click();
 await page.locator('[name=title]').fill('Brooklyn repair day');await page.locator('[name=day]').fill('2026-11-14');await page.locator('[name=offset]').selectOption('-05:00');await page.locator('[name=summary]').fill('Repair household goods with neighbors.');await page.locator('[name=budget_usd]').fill('250');await page.locator('[name=registration_target]').fill('30');await page.getByRole('button',{name:'Save event draft'}).click();await page.waitForFunction(()=>!document.querySelector('#plan-dialog').open);const id=await page.locator('#event-select').inputValue();
 await page.reload();await page.waitForFunction(()=>!document.querySelector('#event-select').disabled);await page.locator('#event-select').selectOption(id);await page.getByText('Saved locally · draft').waitFor();
 const report={run_id:'test-run',event_id:id,status:'partial',generated_at:'2026-10-24',workers:[{role:'venues',status:'completed',findings:{open_questions:['Confirm capacity.']}},{role:'sponsors',status:'failed',error:'Provider unavailable'}],findings:{venues:[{name:'Candidate community hall',rationale:'A place to gather.',details:{capacity:40},source_urls:['https://example.com','javascript:alert(1)'],evidence_status:'unverified'}],sponsors:[]}};
 await page.locator('#report-file').setInputFiles({name:'report.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(report))});await page.getByText('Candidate community hall').waitFor();if(await page.locator('a[href^="javascript:"]').count())throw Error('unsafe link');
 const downloadPromise=page.waitForEvent('download');await page.locator('#export-brief').click();await (await downloadPromise).saveAs(require('path').join(require('os').tmpdir(),'ui-brief.json'));
 await page.screenshot({path:require('path').join(require('os').tmpdir(),'operator-desktop.png'),fullPage:true});await page.setViewportSize({width:390,height:844});await page.screenshot({path:require('path').join(require('os').tmpdir(),'operator-mobile.png'),fullPage:true});
 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth);if(overflow)throw Error('mobile horizontal overflow');if(errors.length)throw Error(errors.join('\n'));
 console.log(JSON.stringify({savedDraft:id,persistence:true,report:true,export:true,mobileOverflow:overflow,browserErrors:errors}));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
