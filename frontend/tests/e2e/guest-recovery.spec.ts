import { test, expect } from '@playwright/test';

test('游客换设备恢复保留身份并换发恢复码', async ({ page, browser }) => {
  await page.goto('/login');
  await page.getByRole('button', {name:'暂不注册，以游客身份继续'}).click();
  await page.getByLabel('你的昵称').fill('恢复测试球友');
  await page.getByRole('button', {name:'确认以游客继续'}).click();
  const saved = page.getByRole('complementary', {name:'保存游客恢复码'});
  await expect(saved).toBeVisible();
  const code = await saved.getByLabel('游客恢复码', {exact:true}).inputValue();
  const original = await page.request.get('/api/v1/session').then(r => r.json());
  await page.getByRole('button', {name:'我已保存恢复码'}).click();
  await page.goto('/me');
  await expect(page.getByRole('heading', {name:'保留游客身份'})).toBeVisible();
  await expect(page.getByRole('button', {name:'绑定邮箱', exact:true})).toBeVisible();
  const context = await browser.newContext();
  try {
    const other = await context.newPage();
    await other.goto('http://127.0.0.1:8010/login');
    await other.getByRole('button', {name:'用恢复码找回游客身份'}).click();
    await other.getByLabel('游客恢复码', {exact:true}).fill(code);
    await other.getByRole('button', {name:'恢复身份', exact:true}).click();
    const banner = other.getByRole('complementary', {name:'保存游客恢复码'});
    await expect(banner).toBeVisible();
    expect(await banner.getByLabel('游客恢复码', {exact:true}).inputValue()).not.toBe(code);
    const restored = await other.request.get('http://127.0.0.1:8010/api/v1/session').then(r => r.json());
    expect(restored.user.id).toBe(original.user.id);
    expect((await page.request.get('/api/v1/session').then(r => r.json())).user).toBeNull();
  } finally { await context.close(); }
});
