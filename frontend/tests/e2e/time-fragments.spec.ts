import { test, expect } from '@playwright/test';

test('fragmented courses keep labels inside their own time segment', async ({ page }) => {
  await page.request.post('/api/v1/auth/guest', { data: { display_name: '零散课表测试' } });
  await page.route('**/api/v1/me/availability?*', route => {
    const from = new URL(route.request().url()).searchParams.get('from_') || new Date().toLocaleDateString('en-CA', {timeZone:'Asia/Shanghai'});
    const day = from.slice(0, 10);
    return route.fulfill({ json: { revision: 0, rules: [], resolved: [
      { start: `${day}T08:00:00+08:00`, end: `${day}T08:10:00+08:00`, state: 'busy', source: 'course' },
      { start: `${day}T08:20:00+08:00`, end: `${day}T08:25:00+08:00`, state: 'busy', source: 'course' },
      { start: `${day}T08:35:00+08:00`, end: `${day}T09:00:00+08:00`, state: 'busy', source: 'course' },
    ] } });
  });
  await page.goto('/me/time');
  const fragmented = page.locator('[data-slot="16"]').first();
  await expect(fragmented).toHaveAttribute('aria-label', /08:10–08:20 未知/);
  await expect(fragmented).toHaveText('');
  const longer = page.locator('[data-slot="17"]').first();
  const label = longer.locator('.time-segment-label');
  await expect(label).toHaveText('繁忙');
  const box = await longer.boundingBox();
  const textBox = await label.boundingBox();
  expect(textBox!.y).toBeGreaterThan(box!.y + box!.height * 0.14);
  expect(textBox!.y + textBox!.height).toBeLessThanOrEqual(box!.y + box!.height + 1);
  await expect(longer).toHaveAttribute('title', /08:30–08:35 未知.*08:35–09:00 繁忙/);
  await page.screenshot({ path: `/tmp/shuttleup-time-fragments-${test.info().project.name}.png` });
});
