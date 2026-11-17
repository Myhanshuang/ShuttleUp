import { test, expect } from '@playwright/test';

test('court grid shows current data and invalidates expired snapshots', async ({ page }) => {
  // Keep session handling real; the disposable e2e database stores this guest only.
  await page.request.post('/api/v1/auth/guest', {data:{display_name:'场地查看者'}});
  await page.route('**/api/v1/venues', route => route.fulfill({json:{items:[{id:'test-venue',name:'测试球馆',booking_url:''}]}}));
  const start = '2026-09-12T08:00:00+08:00', end = '2026-09-12T08:30:00+08:00';
  await page.route('**/api/v1/venues/test-venue/slots?*', route => route.fulfill({json:{
    fresh:true, fresh_until:new Date(Date.now()+1800).toISOString(), next_poll_at:new Date().toISOString(),
    last_success_at:new Date().toISOString(),last_error_code:null,coverage:{},slots:[
      {external_slot_id:'one',court_id:'one',court_name:'一号场',starts_at:start,ends_at:end,status:'available',price_cents:1250},
      {external_slot_id:'two',court_id:'two',court_name:'二号场',starts_at:start,ends_at:end,status:'unavailable',price_cents:1250}]
  }}));
  await page.goto('/venues');
  await expect(page.getByRole('heading',{name:'可用场地'})).toBeVisible();
  await expect(page.getByRole('cell', {name:'可用 ¥12.50',exact:true})).toBeVisible();
  await expect(page.getByText('数据未核实，不能作为可订依据', {exact:false})).toBeVisible({timeout:6000});
  await expect(page.getByRole('cell', {name:'可用 ¥12.50',exact:true})).toHaveCount(0);
});


test('admin starts renewal and automatically reloads after verification', async ({ page }) => {
  await page.route('**/api/v1/session', route => route.fulfill({json:{user:{id:'admin',display_name:'管理员',is_admin:true},csrf_token:'test'}}));
  await page.route('**/api/v1/venues', route => route.fulfill({json:{items:[{id:'local-venue',name:'本机场馆',provider_id:'local-source'}]}}));
  let loads = 0, phase = 'idle', paused = true;
  await page.route('**/api/v1/venues/local-venue/slots?*', route => {
    loads++;
    return route.fulfill({json:{fresh:false,fresh_until:null,last_success_at:null,next_poll_at:new Date().toISOString(),slots:[],last_error_code:paused?'AUTH_EXPIRED':null,coverage:{}}});
  });
  await page.route('**/api/v1/settings/providers/local-source/login', route => {
    if (route.request().method()==='POST') phase='waiting';
    else if (phase==='waiting') {phase='succeeded';paused=false;}
    return route.fulfill({json:{supported:true,paused,last_verified_at:paused?null:Date.now(),job:{id:'one',phase,message:phase==='succeeded'?'登录已更新并验证，查询已恢复。':''}}});
  });
  await page.goto('/venues');
  await expect(page.getByText('登录已失效，自动查询已暂停。')).toBeVisible();
  const before=loads;
  await page.getByRole('button',{name:'更新场馆登录'}).click();
  await expect(page.getByText('登录已更新并验证，查询已恢复。')).toBeVisible({timeout:6000});
  await expect.poll(()=>loads).toBeGreaterThan(before);
});
