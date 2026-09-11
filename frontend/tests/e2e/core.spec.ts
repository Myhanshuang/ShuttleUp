import { expect, test } from '@playwright/test'

test('guest creates an activity and can copy its invite', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('你的昵称').fill('端到端球友')
  await page.getByLabel('活动标题').fill('周六夜场')
  await page.getByRole('button', { name: '继续设置时间与场馆' }).click()
  await expect(page.getByRole('heading', { name: '周六夜场' })).toBeVisible()
  await expect(page.getByText(/活动短号/)).toBeVisible()
  await expect(page.locator('body')).not.toHaveCSS('overflow-x', 'scroll')
})

