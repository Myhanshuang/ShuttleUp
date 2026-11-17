import {test,expect} from '@playwright/test';

test('activity bill stays scoped to that activity and navigation context',async({page})=>{
 const identity=await (await page.request.post('/api/v1/auth/guest',{data:{display_name:'结算测试'}})).json();
 const headers={'X-CSRF-Token':identity.csrf_token};
 const activities=[];
 for (const title of ['第一场球','第二场球']) {
  const a=await (await page.request.post('/api/v1/activities',{headers,data:{title}})).json();activities.push(a);
  const expense=await page.request.post(`/api/v1/activities/${a.id}/expenses`,{headers:{...headers,'Idempotency-Key':crypto.randomUUID()},data:{kind:'extra',description:`${title}的支出`,amount_cents:1000,payer_participant_id:a.my_participant_id,split_mode:'equal',split_scope:'attendees',shares:[]}});
  expect(expense.ok()).toBeTruthy();
 }
 const second=await (await page.request.get(`/api/v1/activities/${activities[1].id}`)).json();
 await page.request.post(`/api/v1/activities/${second.id}/cancel`,{headers,data:{reason:'测试取消后的结算流程',expected_version:second.version}});
 await page.goto(`/a/${activities[0].id}`);
 await expect(page.getByRole('list',{name:'本次活动流程'}).locator('[aria-current="step"]')).toContainText('收集时间');
 await page.getByRole('link',{name:'本次活动费用与结算'}).click();
 await expect(page.getByRole('list',{name:'本次活动流程'}).locator('[aria-current="step"]')).toContainText('收集时间');
 await expect(page).toHaveURL(new RegExp(`/a/${activities[0].id}/bill$`));
 await expect(page.getByRole('heading',{name:'第一场球',exact:true})).toBeVisible();
 await expect(page.getByText('第一场球的支出',{exact:true})).toBeVisible();
 await expect(page.getByText('第二场球的支出',{exact:true})).toHaveCount(0);
 await expect(page.locator('nav a[href="/"]')).toHaveClass(/active/);
 await expect(page.locator('nav a[href="/bills"]')).not.toHaveClass(/active/);
 await page.getByLabel('说明',{exact:true}).fill('未保存的第一场费用');
 // Exercise an in-app route change without reloading the React tree.
 await page.evaluate(id=>{history.pushState({},'',`/a/${id}/bill`);dispatchEvent(new PopStateEvent('popstate'));},activities[1].id);
 await expect(page.getByRole('heading',{name:'第二场球',exact:true})).toBeVisible();
 await expect(page.getByRole('list',{name:'本次活动流程'}).locator('[aria-current="step"]')).toContainText('核对与结算');
 await expect(page.getByText('第二场球的支出',{exact:true})).toBeVisible();
 await expect(page.getByText('第一场球的支出',{exact:true})).toHaveCount(0);
 await expect(page.getByLabel('说明',{exact:true})).toHaveValue('球钱');
 await expect(page.getByRole('link',{name:'← 返回本次活动'})).toHaveAttribute('href',`/a/${activities[1].id}`);
});
