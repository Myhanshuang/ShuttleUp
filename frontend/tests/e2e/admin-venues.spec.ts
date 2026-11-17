import {test, expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import path from 'node:path';

test('管理员添加编辑并启停场馆', async ({page})=>{
  const guest=await(await page.request.post('/api/v1/auth/guest',{data:{display_name:'场馆管理员'}})).json();
  execFileSync(path.resolve('..','.venv/bin/python'),['-c',`
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from shuttleup.models import User, ProviderConfig
engine=create_engine('sqlite:////tmp/shuttleup-e2e.db')
with Session(engine) as db:
    user=db.get(User,sys.argv[1]);user.is_admin=True
    db.add(ProviderConfig(key='ui-'+user.id,adapter_key='manual',label='界面测试来源 '+user.id))
    db.commit()
`,guest.user.id]);
  await page.goto('/admin/venues');
  await expect(page.getByRole('heading',{name:'场馆管理',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'添加场馆',exact:true}).click();
  const form=page.getByRole('form',{name:'添加场馆',exact:true});
  const name=`管理测试球馆-${guest.user.id.slice(0,8)}`;
  await form.getByLabel('场馆名称').fill(name);
  await form.getByLabel('场馆来源',{exact:true}).selectOption({label:'界面测试来源 '+guest.user.id});
  await form.getByLabel('来源内的场馆编号').fill('gym');
  await form.getByLabel('参考价格（元 / 小时）').fill('60');
  await form.getByLabel('地址',{exact:true}).fill('球馆路 1 号');
  await form.getByRole('button',{name:'保存场馆'}).click();
  let card=page.getByRole('article',{name:`场馆 ${name}`,exact:true});
  await expect(card).toBeVisible();
  await card.getByRole('button',{name:'编辑资料'}).click();
  await page.getByRole('form',{name:'编辑场馆'}).getByLabel('场馆名称').fill(name+'更新');
  await page.getByRole('button',{name:'保存场馆'}).click();
  card=page.getByRole('article',{name:`场馆 ${name}更新`,exact:true});
  await card.getByRole('button',{name:'停用场馆'}).click();
  await page.getByRole('dialog',{name:'确认停用场馆'}).getByRole('button',{name:'确认停用',exact:true}).click();
  await expect(card.getByText('已停用',{exact:true})).toBeVisible();
  expect((await page.request.get('/api/v1/venues').then(r=>r.json())).items.some((v:any)=>v.name===name+'更新')).toBeFalsy();
  await card.getByRole('button',{name:'启用场馆'}).click();
  await expect(card.getByText('已启用',{exact:true})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
});

test('普通球友不能进入场馆管理',async({page})=>{
  await page.request.post('/api/v1/auth/guest',{data:{display_name:'普通球友'}});
  await page.goto('/admin/venues');
  await expect(page.getByRole('heading',{name:'需要管理员权限'})).toBeVisible();
  await expect(page.locator('nav a[href="/admin/venues"]')).toHaveCount(0);
  expect((await page.request.get('/api/v1/settings/venues')).status()).toBe(403);
});
