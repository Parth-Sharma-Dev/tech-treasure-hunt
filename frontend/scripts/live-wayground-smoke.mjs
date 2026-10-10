import { chromium,expect } from '@playwright/test';
const backend=process.env.TTH_BACKEND_URL,round=process.env.TTH_WAYGROUND_ROUND,file=process.env.TTH_WAYGROUND_FILE;
if (!backend || !round || !file) throw new Error('Use the isolated Wayground browser fixture.');
const origin='http://127.0.0.1:5173',browser=await chromium.launch(),contexts=[];
try {
  async function context() {
    const ctx=await browser.newContext(); contexts.push(ctx);
    for (const path of ['api','admin']) await ctx.route(`${origin}/${path}/**`,async route=>{
      const url=new URL(route.request().url());
      await route.fulfill({ response:await route.fetch({ url:`${backend}${url.pathname}${url.search}`,maxRedirects:0 }) });
    });
    return ctx;
  }
  async function staff(user,path) {
    const ctx=await context(),page=await ctx.newPage();
    await page.goto(`${origin}/admin/login/?next=${encodeURIComponent(path)}`);
    await page.locator('#id_username').fill(user); await page.locator('#id_password').fill('test-only');
    await page.getByRole('button',{ name:'Log in',exact:true }).click(); return page;
  }
  const maker=await staff('external-maker',`/staff/scores?round=${round}`);
  await maker.getByLabel('Private intake or correction reason').fill('Original exported workbook with explicit participant mapping');
  await maker.getByLabel('Wayground Excel export').setInputFiles(file);
  await maker.getByRole('button',{ name:'Read Wayground workbook' }).click();
  await expect(maker.getByText('7000 platform points',{ exact:false })).toBeVisible();
  await maker.getByLabel('Team for Player 0').selectOption('EXT-0');
  await maker.getByLabel('Team for Player 1').selectOption('EXT-1');
  await maker.getByLabel('Team for Player 2').selectOption('__EXCLUDE__');
  await maker.getByLabel('Exclusion reason for Player 2').fill('Not a qualifying fixture team');
  const intake=maker.waitForResponse(r=>r.url().endsWith('/imports/validate') && r.request().method()==='POST');
  await maker.getByRole('button',{ name:'Dry-run Wayground scores' }).click();
  const batch=(await (await intake).json()).batch_id;
  const reviewer=await staff('external-reviewer',`/staff/scores?round=${round}`);
  await reviewer.getByText(`Batch ${batch} · awaiting review`,{ exact:true }).click();
  await reviewer.getByLabel('Private review decision').fill('Original Score, reported time and exclusions independently checked');
  await reviewer.getByRole('checkbox',{ name:'I checked every original score sheet, team, mark and tie metric.' }).check();
  const committed=reviewer.waitForResponse(r=>r.url().endsWith(`/imports/${batch}/commit`) && r.request().method()==='POST');
  await reviewer.getByRole('button',{ name:`Commit reviewed batch ${batch}` }).click(); expect((await committed).ok()).toBeTruthy();
  await maker.goto(`${origin}/staff/results?round=${round}`);
  await maker.getByLabel('Public publication summary',{ exact:true }).fill('Raw exported platform points reviewed');
  const proposed=maker.waitForResponse(r=>r.url().endsWith('/publish') && r.request().method()==='POST');
  await maker.getByRole('button',{ name:'Submit result proposal' }).click(); const id=(await (await proposed).json()).proposal_id;
  await reviewer.goto(`${origin}/staff/results?round=${round}`);
  await reviewer.getByLabel('Public review summary',{ exact:true }).fill('Independent original-export publication review');
  await reviewer.getByRole('checkbox',{ name:'I independently checked the standings, roster, cut and supporting evidence.' }).check();
  const published=reviewer.waitForResponse(r=>r.url().endsWith('/publish') && r.request().method()==='POST');
  await reviewer.getByRole('button',{ name:`Approve and publish proposal ${id}` }).click(); expect((await published).ok()).toBeTruthy();
  const team=await context(),page=await team.newPage(); await page.goto(`${origin}/login`);
  await page.getByLabel('Team code',{ exact:true }).fill('EXT-0'); await page.getByLabel('Password',{ exact:true }).fill('test-only');
  const login=page.waitForResponse(r=>r.url().endsWith('/api/auth/login') && r.request().method()==='POST');
  await page.getByRole('button',{ name:'Sign in',exact:true }).click(); expect((await login).ok()).toBeTruthy();
  await page.waitForURL('**/lobby'); await page.goto(`${origin}/rounds/${round}/results`);
  await expect(page.getByRole('heading',{ name:'Provisional results · revision 1' })).toBeVisible();
  await expect(page.getByRole('columnheader',{ name:'Reported answering duration' })).toBeVisible();
  await expect(page.getByRole('cell',{ name:'7000',exact:true })).toBeVisible();
  await expect(page.getByText('9999999.999',{ exact:false })).toHaveCount(0);
  console.log('Real workbook upload, mapping/exclusion, independent commit and raw-score publication passed.');
} finally { for (const ctx of contexts) await ctx.unrouteAll({ behavior:'wait' }); await browser.close(); }
