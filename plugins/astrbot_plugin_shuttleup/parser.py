from __future__ import annotations

import re

COMMANDS={"帮助":"help","绑定":"identity.bind","关联":"context.bind","创建":"activity.create","活动":"activity.list","切换":"activity.switch","当前":"activity.current","加入":"participant.join","退出":"participant.leave","课表":"schedule.open","有空":"availability.set","没空":"availability.set","时间":"availability.summary","推荐":"candidate.list","场地":"venue.list","选择":"plan.open_select","已订":"booking.open_create","参加":"rsvp.set","不参加":"rsvp.set","到场":"attendance.set","缺席":"attendance.set","记账":"expense.create","账单":"bill.show","已付":"payment.claim","收款":"payment.confirm","结算":"bill.open_publish","结束":"activity.open_finish","取消":"activity.open_cancel"}


def parse(text: str)->dict:
    parts=text.strip().split()
    if parts and parts[0] in ("/羽球","羽球"):parts=parts[1:]
    if not parts or parts[0] not in COMMANDS:return {"command":"help","args":{}}
    word=parts.pop(0); command=COMMANDS[word]; args={}; activity_code=None
    if "--活动" in parts:
        index=parts.index("--活动")
        if index+1>=len(parts):raise ValueError("--活动 后需要活动短号")
        activity_code=parts[index+1].upper(); del parts[index:index+2]
    if word in ("绑定","关联"):
        if not parts:raise ValueError(f"示例：/羽球 {word} ABCD2345EFGH")
        args["code"]=parts[0]
    elif word=="创建":args["title"]=" ".join(parts) or "羽毛球约球"
    elif word=="切换":
        if not parts:raise ValueError("示例：/羽球 切换 B6R2")
        activity_code=parts[0].upper()
    elif word in ("有空","没空"):
        if len(parts)<2 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",parts[0]) or not re.fullmatch(r"\d{2}:\d{2}-\d{2}:\d{2}",parts[1]):raise ValueError("示例：/羽球 有空 2026-09-19 18:00-20:00")
        args={"date":parts[0],"time":parts[1],"state":"free" if word=="有空" else "busy","personal":"--个人" in parts}
    elif word in ("参加","不参加"):args["response"]="yes" if word=="参加" else "no"
    elif word in ("到场","缺席"):args["state"]="present" if word=="到场" else "absent"
    elif word=="记账":
        if len(parts)<2:raise ValueError("示例：/羽球 记账 AA 48 球钱")
        args={"kind":parts[0],"value":parts[1],"description":" ".join(parts[2:])}
        if parts[0]=="指定":command="expense.open_split"
    elif word in ("已付","收款"):
        if not parts:raise ValueError(f"示例：/羽球 {word} T4J8")
        args={"code":parts[0]}
        if len(parts)>1:args["amount"]=parts[1]
    return {"command":command,"activity_code":activity_code,"args":args}
