import {test,expect} from '@playwright/test';
test('join requires availability below the button',async({page})=>{
 const host=await(await page.request.post('/api/v1/auth/guest',{data:{display_name:'邀请人'}})).json();
 const a=await(await page.request.post('/api/v1/activities',{headers:{'X-CSRF-Token':host.csrf_token},data:{title:'先填时间'}})).json();
 await page.context().clearCookies();
 await page.request.post('/api/v1/auth/guest',{data:{display_name:'加入者'}});
 await page.goto(a.invite_url);
 const join=page.getByRole('button',{name:'加入活动',exact:true});
 await expect(join).toBeDisabled();
 const section=page.getByRole('region',{name:'加入前填写空闲时间'});
 expect((await section.boundingBox())!.y).toBeGreaterThan((await join.boundingBox())!.y);
 await page.getByLabel('开始时间').fill('18:00');
 await page.getByLabel('结束时间').fill('20:00');
 await expect(join).toBeEnabled();
 await join.click();
 await expect(page).toHaveURL(new RegExp(`/a/${a.id}$`));
 const times=await(await page.request.get(`/api/v1/me/availability?activity_id=${a.id}`)).json();
 expect(times.rules.some((r:any)=>r.source==='activity'&&r.state==='free')).toBeTruthy();
});
