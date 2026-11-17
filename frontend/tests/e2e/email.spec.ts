import { test, expect } from '@playwright/test';

test('邮箱注册验证码及未配置状态', async ({ page }) => {
  await page.route('**/api/v1/auth/options', route => route.fulfill({json: {email_registration: true}}));
  await page.route('**/api/v1/auth/email/code', route => route.fulfill({status: 202, json: {challenge_id:'12345678-1234-1234-1234-123456789012', retry_after:60}}));
  await page.route('**/api/v1/auth/email/register', async route => {
    expect(route.request().postDataJSON()).toMatchObject({email:'player@example.com', code:'123456', display_name:'邮箱球友'});
    await route.fulfill({status:422, json:{detail:{code:'INVALID_EMAIL_CODE', message:'验证码不正确。'}}});
  });
  await page.goto('/login');
  await expect(page.getByLabel('用户名或邮箱')).toBeVisible();
  await page.getByRole('button', {name:'注册', exact:true}).click();
  await expect(page.getByRole('button', {name:'用户名注册', exact:true})).toHaveCount(0);
  await expect(page.getByLabel('用户名', {exact:true})).toHaveCount(0);
  await page.getByLabel('你的昵称').fill('邮箱球友');
  await page.getByLabel('邮箱', {exact:true}).fill('player@example.com');
  await page.getByRole('button', {name:'发送验证码', exact:true}).click();
  await expect(page.getByText('验证码已发送，请查看邮箱；10 分钟内有效。')).toBeVisible();
  await expect(page.getByRole('button', {name:/秒后可重发/})).toBeDisabled();
  await page.getByLabel('邮箱验证码').fill('123456');
  await page.getByLabel('密码', {exact:true}).fill('long-enough-password');
  await page.getByRole('button', {name:'创建账号', exact:true}).click();
  await expect(page.getByText('验证码不正确。')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.route('**/api/v1/auth/options', route => route.fulfill({json:{email_registration:false}}));
  await page.reload();
  await page.getByRole('button', {name:'注册', exact:true}).click();
  await expect(page.getByRole('button', {name:'用户名注册', exact:true})).toHaveCount(0);
  await expect(page.getByLabel('用户名', {exact:true})).toHaveCount(0);
  await expect(page.getByText('管理员尚未配置邮件发送服务，暂时无法获取验证码。')).toBeVisible();
  await expect(page.getByRole('button', {name:'发送验证码', exact:true})).toBeDisabled();
});
