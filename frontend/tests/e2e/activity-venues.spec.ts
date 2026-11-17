import {test,expect} from '@playwright/test';

test('host can select a venue at creation and edit it later',async({page})=>{
  await page.request.post('/api/v1/auth/guest',{data:{display_name:'场馆选择测试'}});
  await page.route('**/api/v1/venues',r=>r.fulfill({json:{items:[{id:'test-choice',name:'测试场馆'}]}}));
  let selected:string[]=[];
  await page.route('**/api/v1/activities',async r=>{
    if(r.request().method()!=='POST'){await r.continue();return;}
    const data=r.request().postDataJSON();selected=data.venue_preferences;
    const upstream=await r.fetch({postData:{...data,venue_preferences:[]}});
    await r.fulfill({response:upstream});
  });
  await page.goto('/');await page.getByRole('button',{name:'＋ 发起约球'}).click();
  await page.getByLabel('测试场馆').check();
  await page.getByRole('button',{name:'创建活动并邀请球友'}).click();
  await page.getByRole('button',{name:'调整活动安排',exact:true}).click();
  await expect(page.getByRole('button',{name:'保存活动场馆'})).toBeVisible();
  expect(selected).toEqual(['test-choice']);
  const aid=page.url().split('/').pop();
  await page.route(`**/api/v1/activities/${aid}`,async r=>{
    if(r.request().method()!=='PATCH'){await r.continue();return;}
    selected=r.request().postDataJSON().venue_preferences;
    const upstream=await r.fetch({postData:{...r.request().postDataJSON(),venue_preferences:[]}});
    await r.fulfill({response:upstream});
  });
  await page.getByLabel('测试场馆').check();
  await page.getByRole('button',{name:'保存活动场馆'}).click();
  await expect(page.getByRole('status')).toContainText('活动场馆已保存');
  expect(selected).toEqual(['test-choice']);
});

test('host shortens activity duration separately from personal availability',async({page})=>{
  const identity=await (await page.request.post('/api/v1/auth/guest',{data:{display_name:'时长测试'}})).json();
  const a=await (await page.request.post('/api/v1/activities',{headers:{'X-CSRF-Token':identity.csrf_token},data:{title:'时长妥协',duration_minutes:120}})).json();
  await page.goto(`/a/${a.id}`);
  await expect(page.getByRole('heading',{name:'活动安排 · 全体成员'})).toBeVisible();
  await expect(page.getByRole('link',{name:'修改我的本次空闲时间'})).toHaveAttribute('href',`/me/time?activity_id=${a.id}`);
  await page.getByRole('button',{name:'调整活动安排',exact:true}).click();
  await page.getByLabel('活动打球时长（分钟）').fill('60');
  await page.getByRole('button',{name:'保存活动安排'}).click();
  await expect(page.getByText(/每次打球 60 分钟/)).toBeVisible();
  await expect(page.getByRole('status')).toContainText('活动安排已保存');
  const saved=await (await page.request.get(`/api/v1/activities/${a.id}`)).json();
  expect(saved.duration_minutes).toBe(60);
});
