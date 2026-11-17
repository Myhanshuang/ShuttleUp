import { expect, test } from "@playwright/test";

test("account-first login, activity workflow and scoped visual availability", async ({
  page,
}) => {
  const failures: string[] = [];
  page.on("pageerror", (e) => failures.push(e.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "一起约场球" })).toBeVisible();
  await page.getByRole("button", { name: "＋ 发起约球" }).click();
  await expect(
    page.getByRole("heading", { name: "登录 ShuttleUp" }),
  ).toBeVisible();
  await expect(page.getByLabel("你的昵称")).toHaveCount(0);
  await page.getByRole("button", { name: "暂不注册，以游客身份继续" }).click();
  await page.getByLabel("你的昵称").fill("端到端球友");
  await page.getByRole("button", { name: "确认以游客继续" }).click();
  await page.getByRole("button", { name: "＋ 发起约球" }).click();
  await page.getByLabel("活动标题").fill("周六夜场");
  await page.getByRole("button", { name: "创建活动并邀请球友" }).click();
  await expect(
    page.getByRole("heading", { name: "周六夜场", exact: true }),
  ).toBeVisible();
  const activityUrl = page.url();
  await expect(page.getByText(/活动短号/)).toBeVisible();
  await expect(page.getByRole("button", { name: "我已到场" })).toHaveCount(0);
  await page
    .getByRole("link", { name: "填写本次空闲时间", exact: true })
    .click();
  await expect(page.getByLabel("作用范围")).toHaveValue("activity");
  await expect(page.locator(".calendar")).toBeVisible();
  await page.getByRole("button", { name: "加入待保存 · 空闲" }).click();
  await expect(page.locator(".draft-item")).toContainText("18:00–20:00");
  await page
    .getByRole("button", { name: "保存 1 段时间", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("时间已保存");
  await expect(page.locator(".draft-item")).toHaveCount(0);
  const rules = await page.evaluate(
    async () =>
      (await (await fetch("/api/v1/me/availability" + location.search)).json())
        .rules,
  );
  expect(rules).toHaveLength(1);
  expect(rules[0].source).toBe("activity");
  await page.screenshot({
    path: `/tmp/shuttleup-react-time-${test.info().project.name}.png`,
    fullPage: true,
  });
  await page.goto("/me/time");
  await expect(page.locator(".calendar")).toBeVisible();
  const personal = await page.evaluate(
    async () => (await (await fetch("/api/v1/me/availability")).json()).rules,
  );
  expect(personal).toHaveLength(0);
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "周六夜场", exact: true }),
  ).toBeVisible();
  await page.screenshot({ path: `/tmp/shuttleup-react-home-${test.info().project.name}.png` });
  await page.goto(activityUrl);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(failures).toEqual([]);
});

test("guest is explicitly optional; calendar selection can be undone", async ({
  page,
}) => {
  await page.goto("/login?next=/me/time");
  await page.getByRole("button", { name: "暂不注册，以游客身份继续" }).click();
  await page.getByLabel("你的昵称").fill("临时球友");
  await page
    .getByRole("button", { name: "确认以游客继续", exact: true })
    .click();
  await expect(page.locator(".calendar")).toBeVisible();
  const cell = page.locator('[data-slot="36"]').first();
  await cell.scrollIntoViewIfNeeded();
  await cell.click();
  await expect(page.locator(".draft-item")).toContainText("18:00–18:30");
  await page.getByRole("button", { name: "撤销上一段" }).click();
  await expect(page.locator(".draft-item")).toHaveCount(0);
  if (test.info().project.name === "desktop") {
    await page.locator('[data-slot="39"]').first().scrollIntoViewIfNeeded();
    const a = await cell.boundingBox(),
      b = await page.locator('[data-slot="39"]').first().boundingBox();
    await page.mouse.move(a!.x + 20, a!.y + 10);
    await page.mouse.down();
    await page.mouse.move(b!.x + 20, b!.y + 10, { steps: 5 });
    await page.mouse.up();
    await expect(page.locator(".draft-item")).toContainText("18:00–20:00");
  }
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test('uncertain is selectable, unknown is default, and calendar is 08–22', async ({ page }) => {
  await page.goto('/login?next=/me/time');
  await page.getByRole('button', { name: '暂不注册，以游客身份继续' }).click();
  await page.getByLabel('你的昵称').fill('时间范围');
  await page.getByRole('button', { name: '确认以游客继续', exact: true }).click();
  await expect(page.locator('.calendar')).toBeVisible();
  const columns = test.info().project.name === 'mobile' ? 1 : 7;
  await expect(page.locator('[data-slot="16"]')).toHaveCount(columns);
  await expect(page.locator('[data-slot="43"]')).toHaveCount(columns);
  await expect(page.locator('[data-slot="15"], [data-slot="44"]')).toHaveCount(0);
  await expect(page.locator('.swatch')).toHaveCount(3);
  await page.getByRole('button', { name: '不确定', exact: true }).click();
  await page.getByRole('button', { name: '加入待保存 · 不确定' }).click();
  await page.getByRole('button', { name: '保存 1 段时间', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('时间已保存');
  await expect(page.locator('.time-cell.uncertain')).toHaveCount(4);
  await expect(page.locator('.time-cell.unknown')).toHaveCount(28 * columns - 4);
});
