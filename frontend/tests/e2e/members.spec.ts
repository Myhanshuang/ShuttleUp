import {test,expect} from '@playwright/test';

test('host removes and restores an activity member',async({page})=>{
  const identity=await (await page.request.post('/api/v1/auth/guest',{data:{display_name:'主持人'}})).json();
  const headers={'X-CSRF-Token':identity.csrf_token};
  const activity=await (await page.request.post('/api/v1/activities',{headers,data:{title:'成员管理体验'}})).json();
  await page.request.post(`/api/v1/activities/${activity.id}/participants/offline`,{headers,data:{display_name:'测试球友'}});
  await page.goto(`/a/${activity.id}`);
  const row=page.locator('.list-row').filter({hasText:'测试球友'});
  await row.getByRole('button',{name:'移除成员'}).click();
  await page.getByRole('dialog',{name:'确认成员变更'}).getByRole('button',{name:'确认移除'}).click();
  await expect(row).toContainText('已移除');
  await row.getByRole('button',{name:'恢复成员'}).click();
  await page.getByRole('dialog',{name:'确认成员变更'}).getByRole('button',{name:'确认恢复'}).click();
  await expect(row.getByRole('button',{name:'移除成员'})).toBeVisible();
});
