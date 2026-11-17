import { test, expect } from '@playwright/test';

test('WakeUp previews times before explicit confirmation and clears rejected previews', async ({ page }) => {
  await page.request.post('/api/v1/auth/guest', { data: { display_name: '课表预览测试' } });
  let confirmed = false;
  let invalid = false;
  await page.route('**/api/v1/me/imports/wakeup/preview', route => route.fulfill(invalid ? {
    status: 502, json: { detail: { code: 'WAKEUP_INVALID_TIME', message: '第 12 节结束时间必须晚于开始时间。' } },
  } : { json: {
    preview_id: 'preview', term: { start: '2026-09-07', end: '2026-10-04' },
    summary: { course_count: 1, occurrence_count: 1 },
    busy_occurrences: [{ starts_at: '2026-09-09T08:00:00+08:00', ends_at: '2026-09-09T08:45:00+08:00', preview_title: '示例课程' }],
  } }));
  await page.route('**/api/v1/me/imports/wakeup/confirm', route => {
    confirmed = true;
    return route.fulfill({ json: { id: 'import', revision: 1 } });
  });
  await page.goto('/me/time');
  await page.getByText('从 WakeUp 导入课表', { exact: true }).click();
  await page.getByLabel('分享文字或口令').fill('0123456789abcdef0123456789abcdef');
  await page.getByRole('button', { name: '预览课表', exact: true }).click();
  await expect(page.getByText('1 门课程', { exact: false })).toBeVisible();
  expect(confirmed).toBe(false);
  await page.getByText('查看繁忙时段明细', { exact: false }).click();
  await expect(page.getByText('2026-09-09 08:00–08:45 · 示例课程')).toBeVisible();
  invalid = true;
  await page.getByRole('button', { name: '预览课表', exact: true }).click();
  await expect(page.getByText('第 12 节结束时间必须晚于开始时间。', { exact: true }).first()).toBeVisible();
  await expect(page.getByRole('button', { name: '确认导入', exact: true })).toHaveCount(0);
  invalid = false;
  await page.getByRole('button', { name: '预览课表', exact: true }).click();
  await page.getByRole('button', { name: '确认导入', exact: true }).click();
  await expect.poll(() => confirmed).toBe(true);
});
