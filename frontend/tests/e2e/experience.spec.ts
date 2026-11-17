import {test,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import path from 'node:path';

test('时间块编辑、恢复继承及活动内保存返回',async({page})=>{
  const identity=await(await page.request.post('/api/v1/auth/guest',{data:{display_name:'时间编辑球友'}})).json();
  const headers={'X-CSRF-Token':identity.csrf_token};
  const a=await(await page.request.post('/api/v1/activities',{headers,data:{title:'单次时间体验'}})).json();
  const rule=(state:string,source:string)=>({state,source,kind:'once',activity_id:source==='activity'?a.id:null,start_at:`${a.date_from}T18:00:00+08:00`,end_at:`${a.date_from}T20:00:00+08:00`});
  await page.request.post('/api/v1/me/availability/rules',{headers,data:{expected_revision:0,rules:[rule('free','one_off'),rule('busy','activity')]}});
  await page.goto(`/me/time?activity_id=${a.id}`);
  await expect(page.getByRole('list',{name:'本次活动流程'})).toBeVisible();
  await expect(page.getByRole('heading',{name:'本次空闲时间',exact:true})).toBeVisible();
  if(test.info().project.name==='mobile')await expect(page.locator('.day-calendar')).toBeVisible();
  await expect(page.locator('.time-cell.busy').first()).toBeVisible();
  await page.locator(`[data-slot="36"][data-day="${a.date_from}"]`).click();
  await expect(page.getByRole('heading',{name:'编辑选中时段'})).toBeVisible();
  await page.getByLabel('开始',{exact:true}).fill('19:00');
  await page.getByRole('button',{name:'清除本次覆盖，恢复个人时间'}).click();
  await expect(page.locator('.draft-item')).toContainText('19:00–20:00');
  const save=page.getByRole('button',{name:'保存 1 段时间',exact:true});
  const box=await save.boundingBox();
  expect(box!.y+box!.height).toBeLessThanOrEqual(page.viewportSize()!.height);
  await save.click();
  await expect(page.getByRole('status')).toContainText('时间已保存');
  await expect(page.locator('.time-cell.busy')).toHaveCount(2);
  await expect(page.locator('.time-cell.free.inherited')).toHaveCount(2);
  await page.locator(`[data-slot="36"][data-day="${a.date_from}"]`).scrollIntoViewIfNeeded();
  await page.screenshot({path:`/tmp/shuttleup-six-time-${test.info().project.name}.png`,fullPage:true});
  await page.locator(`[data-slot="38"][data-day="${a.date_from}"]`).click();
  await page.getByLabel('时段状态').selectOption('uncertain');
  await page.getByRole('button',{name:'加入待保存 · 不确定'}).click();
  await page.getByRole('button',{name:'保存并返回活动'}).click();
  await expect(page).toHaveURL(new RegExp(`/a/${a.id}$`));
  await expect(page.getByRole('heading',{name:'单次时间体验',exact:true})).toBeVisible();
  const rows=(await(await page.request.get(`/api/v1/me/availability?activity_id=${a.id}`)).json()).rules;
  expect(rows.some((r:any)=>r.state==='uncertain'&&r.source==='activity')).toBeTruthy();
  expect(rows.filter((r:any)=>r.source==='one_off')[0].state).toBe('free');
});

test('预览时长、明确名单、实际日期和结清流程',async({page,browser})=>{
  const identity=await(await page.request.post('/api/v1/auth/guest',{data:{display_name:'方案主持人'}})).json();
  const headers={'X-CSRF-Token':identity.csrf_token};
  const a=await(await page.request.post('/api/v1/activities',{headers,data:{title:'方案决策体验',min_players:2,max_players:2,duration_minutes:120}})).json();
  const guestContext=await browser.newContext();
  const joined=await(await guestContext.request.post(`http://127.0.0.1:8010/api/v1/invites/${a.invite_token}/join`,{data:{display_name:'球友甲',availability:[{date:a.date_from,start:'08:00',end:'09:00'}]}})).json();
  const third=await(await page.request.post(`/api/v1/activities/${a.id}/participants/offline`,{headers,data:{display_name:'球友乙'}})).json();
  const seeded=JSON.parse(execFileSync(path.resolve('..','.venv/bin/python'),['-c',`
import sys,json
from datetime import date,timedelta,datetime
from sqlalchemy import create_engine,select
from sqlalchemy.orm import Session
from shuttleup.models import Activity,Participant,ProviderConfig,Venue,VenueSnapshot,AvailabilityRule,now_ms
with Session(create_engine('sqlite:////tmp/shuttleup-e2e.db')) as db:
    a=db.get(Activity,sys.argv[1]);day=(date.fromisoformat(a.date_from)+timedelta(days=2)).isoformat()
    p=ProviderConfig(key='preview-ui-'+a.id,adapter_key='manual',label='体验来源',fresh_for_seconds=3600)
    db.add(p);db.flush();v=Venue(provider_id=p.id,external_venue_id='demo',name='体验羽毛球馆');db.add(v);db.flush()
    a.venue_preferences=[v.id]
    left=day+'T18:00:00+08:00';right=day+'T19:00:00+08:00'
    db.add(VenueSnapshot(venue_id=v.id,local_date=day,revision=1,content_hash='demo',last_attempt_at=now_ms(),last_success_at=now_ms(),next_poll_at=now_ms()+3600000,coverage={'complete':True,'identity_mode':'court'},slots=[{'external_slot_id':'one','court_id':'c1','starts_at':left,'ends_at':right,'status':'available','price_cents':4000}]))
    for person in db.scalars(select(Participant).where(Participant.activity_id==a.id)):
        db.add(AvailabilityRule(user_id=person.user_id,activity_id=a.id,source='activity',state='free',kind='once',start_at=int(datetime.fromisoformat(left).timestamp()*1000),end_at=int(datetime.fromisoformat(right).timestamp()*1000),edit_seq=1))
    db.commit();print(json.dumps({'day':day}))
`,a.id],{encoding:'utf8'}));
  await page.goto(`/a/${a.id}`);
  await expect(page.getByLabel('活动打球时长（分钟）')).toHaveCount(0);
  await page.getByRole('button',{name:'预览调整打球时长'}).click();
  await page.getByLabel('预览打球时长').selectOption('60');
  await page.getByRole('button',{name:'预览方案',exact:true}).click();
  await expect(page.getByText('120 → 60 分钟')).toBeVisible();
  expect((await(await page.request.get(`/api/v1/activities/${a.id}`)).json()).duration_minutes).toBe(120);
  await page.getByRole('button',{name:'采用 60 分钟，重新生成方案'}).click();
  await page.getByRole('button',{name:'选择方案',exact:true}).click();
  const form=page.getByRole('form',{name:'确认方案与参加名单'});
  await expect(form).toContainText('已选 2 人');
  await page.screenshot({path:`/tmp/shuttleup-six-candidates-${test.info().project.name}.png`,fullPage:true});
  expect((await(await page.request.get(`/api/v1/activities/${a.id}`)).json()).status).toBe('collecting');
  await form.getByLabel('球友甲',{exact:true}).uncheck();
  await form.getByLabel('球友乙',{exact:true}).check();
  await form.getByRole('button',{name:'确认名单并进入订场'}).click();
  await expect(page.getByRole('list',{name:'本次活动流程'}).locator('[aria-current="step"]')).toContainText('订场确认');
  const selected=(await(await page.request.get(`/api/v1/activities/${a.id}`)).json()).current_plan;
  expect(selected.roster_participant_ids).toContain(third.id);
  expect(selected.roster_participant_ids).not.toContain(joined.activity.my_participant_id);
  await page.getByRole('button',{name:'确认参加',exact:true}).click();
  await page.getByLabel('实际球场（多个用逗号分隔）').fill('c1');
  await page.getByRole('button',{name:'登记已订场',exact:true}).click();
  await page.goto('/');
  await expect(page.locator('.court-banner')).toHaveCount(0);
  const card=page.locator('.activity-card').filter({hasText:'方案决策体验'});
  await expect(card).toContainText(seeded.day);
  await expect(card).toContainText('18:00–19:00');
  await expect(card).toContainText('体验羽毛球馆');
  await page.screenshot({path:`/tmp/shuttleup-six-home-${test.info().project.name}.png`,fullPage:true});
  let current=await(await page.request.get(`/api/v1/activities/${a.id}`)).json();
  await page.request.post(`/api/v1/activities/${a.id}/finish`,{headers,data:{expected_version:current.version}});
  const members=(await(await page.request.get(`/api/v1/activities/${a.id}/participants`)).json()).items;
  await page.request.put(`/api/v1/activities/${a.id}/attendance`,{headers,data:{verify:true,entries:members.map((p:any)=>({participant_id:p.id,state:selected.roster_participant_ids.includes(p.id)?'present':'absent'}))}});
  current=await(await page.request.get(`/api/v1/activities/${a.id}`)).json();
  const published=await page.request.post(`/api/v1/activities/${a.id}/bill/publish`,{headers:{...headers,'Idempotency-Key':crypto.randomUUID()},data:{expected_generation:current.bill_generation}});
  expect(published.ok()).toBeTruthy();
  await page.goto(`/a/${a.id}/bill`);
  const progress=page.getByRole('list',{name:'本次活动流程'});
  await expect(progress).toContainText('全部结清');
  await expect(progress.locator('[aria-current="step"]')).toHaveCount(0);
  await expect(progress.locator('.done')).toHaveCount(4);
  await guestContext.close();
});

test('取消活动不显示已完成订场和打球',async({page})=>{
  const identity=await(await page.request.post('/api/v1/auth/guest',{data:{display_name:'取消测试'}})).json();
  const headers={'X-CSRF-Token':identity.csrf_token};
  const a=await(await page.request.post('/api/v1/activities',{headers,data:{title:'取消流程'}})).json();
  await page.request.post(`/api/v1/activities/${a.id}/cancel`,{headers,data:{expected_version:a.version,reason:'改日再约'}});
  await page.goto(`/a/${a.id}`);
  const progress=page.getByRole('list',{name:'本次活动流程'});
  await expect(progress).toContainText('活动已取消');
  await expect(progress.locator('.done')).toHaveCount(0);
  await expect(progress).not.toContainText('到场打球');
});

test('邮箱找回入口、验证码与密码确认反馈',async({page})=>{
  await page.route('**/api/v1/auth/options',r=>r.fulfill({json:{email_registration:true}}));
  await page.route('**/api/v1/auth/password/code',r=>r.fulfill({status:202,json:{challenge_id:'12345678-1234-1234-1234-123456789012',retry_after:60}}));
  await page.route('**/api/v1/auth/password/reset',r=>{
    expect(r.request().postDataJSON()).toMatchObject({email:'player@example.com',code:'123456',password:'replacement-password'});
    return r.fulfill({json:{message:'密码已重设'}});
  });
  await page.goto('/login');
  await page.getByRole('link',{name:'忘记密码？'}).click();
  await page.getByLabel('注册邮箱').fill('player@example.com');
  await page.getByRole('button',{name:'发送验证码',exact:true}).click();
  await expect(page.getByRole('status')).toContainText('如果该邮箱已注册');
  await page.getByLabel('邮箱验证码').fill('123456');
  await page.getByLabel('新密码',{exact:true}).fill('replacement-password');
  await page.getByLabel('再次输入新密码').fill('different-password');
  await expect(page.getByRole('button',{name:'重设密码',exact:true})).toBeDisabled();
  await page.getByLabel('再次输入新密码').fill('replacement-password');
  await page.getByRole('button',{name:'重设密码',exact:true}).click();
  await expect(page.getByRole('heading',{name:'密码已重设'})).toBeVisible();
  await expect(page.getByText('原有活动和身份均已保留。所有设备需要用新密码重新登录。')).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
});

test('球友更新实时反馈且保留主持人未保存的活动设置',async({page,browser})=>{
  const identity=await(await page.request.post('/api/v1/auth/guest',{data:{display_name:'协作主持人'}})).json();
  const headers={'X-CSRF-Token':identity.csrf_token};
  const a=await(await page.request.post('/api/v1/activities',{headers,data:{title:'多人同步体验'}})).json();
  const other=await browser.newContext();
  const joined=await(await other.request.post(`http://127.0.0.1:8010/api/v1/invites/${a.invite_token}/join`,{data:{display_name:'同步球友',availability:[{date:a.date_from,start:'08:00',end:'09:00'}]}})).json();
  await page.goto(`/a/${a.id}`);
  await page.getByRole('button',{name:'调整活动安排',exact:true}).click();
  await page.getByLabel('活动打球时长（分钟）').fill('60');
  await other.request.post('http://127.0.0.1:8010/api/v1/me/availability/rules',{headers:{'X-CSRF-Token':joined.csrf_token},data:{expected_revision:1,rules:[{state:'free',source:'activity',activity_id:a.id,kind:'once',start_at:`${a.date_from}T18:00:00+08:00`,end_at:`${a.date_from}T20:00:00+08:00`}]}});
  await expect(page.locator('.change-notice')).toContainText('球友更新了空闲时间');
  await expect(page.getByLabel('活动打球时长（分钟）')).toHaveValue('60');
  await expect(page.locator('.activity-updates summary')).toContainText('同步球友更新了空闲时间');
  await other.close();
});
