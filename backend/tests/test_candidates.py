from datetime import datetime
from zoneinfo import ZoneInfo

from shuttleup.venues.candidates import cover_court, generate_candidates

TZ=ZoneInfo("Asia/Shanghai")
def slot(sid,court,start,end,price=6000): return {"external_slot_id":sid,"court_id":court,"starts_at":f"2026-09-19T{start}:00+08:00","ends_at":f"2026-09-19T{end}:00+08:00","status":"available","price_cents":price,"remaining_count":1}


def test_cannot_stitch_two_different_courts():
    slots=[slot("a","c1","18:00","19:00"),slot("b","c2","19:00","20:00")]
    start=datetime.fromisoformat("2026-09-19T18:00:00+08:00"); end=datetime.fromisoformat("2026-09-19T20:00:00+08:00")
    assert cover_court(slots,"c1",start,end) is None and cover_court(slots,"c2",start,end) is None


def test_candidate_requires_core_member_and_named_continuous_court():
    slots=[slot("a","c1","18:00","19:00"),slot("b","c1","19:00","20:00")]
    activity={"version":1,"duration_minutes":120,"min_players":4,"max_players":4,"court_count":1,"venue_preferences":["v1"]}
    people=[{"id":f"p{i}","required":i==0,"state_for":lambda s,e:"free"} for i in range(6)]
    day={"venue_id":"v1","venue_name":"球馆","coverage":{"identity_mode":"court"},"slots":slots,"fresh":True,"last_success_at":"2026-09-18T12:00:00+08:00","fresh_until":"2026-09-18T12:02:00+08:00"}
    result=generate_candidates(activity,people,[day],datetime.fromisoformat("2026-09-18T12:00:00+08:00"))
    assert len(result["candidates"])==1 and len(result["candidates"][0]["eligible_participant_ids"])==6
    people[0]["state_for"]=lambda s,e:"busy"
    result=generate_candidates(activity,people,[day],datetime.fromisoformat("2026-09-18T12:00:00+08:00"))
    assert not result["candidates"] and result["other_windows"][0]["classification"]=="insufficient_players"



def test_daily_window_filters_daytime_and_late_end():
    activity={'version':1,'duration_minutes':60,'min_players':2,'max_players':4,'court_count':1,
              'venue_preferences':['v'],'timezone':'Asia/Shanghai',
              'daily_windows':[{'weekdays':[6],'start_time':'18:00','end_time':'19:00'}]}
    people=[{'id':str(i),'required':False,'state_for':lambda a,b:'free'} for i in range(2)]
    day={'venue_id':'v','venue_name':'测试','local_date':'2026-09-19','coverage':{'identity_mode':'court'},'fresh':True,
         'slots':[slot('a','c','17:00','18:00'),slot('b','c','18:00','19:00'),slot('c','c','19:00','20:00')]}
    result=generate_candidates(activity,people,[day],datetime.fromisoformat('2026-09-18T12:00:00+08:00'))
    assert len(result['candidates'])==1
    assert result['candidates'][0]['starts_at']=='2026-09-19T18:00:00+08:00'
    activity['daily_windows'][0]['weekdays']=[7]
    assert not generate_candidates(activity,people,[day],datetime.fromisoformat('2026-09-18T12:00:00+08:00'))['candidates']


def test_missing_slots_still_reports_people_windows_and_excess_core_members():
    activity={'version':1,'duration_minutes':60,'min_players':2,'max_players':2,'court_count':1,
              'venue_preferences':['v'],'timezone':'Asia/Shanghai',
              'daily_windows':[{'weekdays':[6],'start_time':'18:00','end_time':'19:00'}]}
    people=[{'id':str(i),'required':True,'state_for':lambda a,b:'free'} for i in range(2)]
    day={'venue_id':'v','venue_name':'测试','local_date':'2026-09-19','coverage':{'identity_mode':'court'},'fresh':False,'slots':[]}
    now=datetime.fromisoformat('2026-09-18T12:00:00+08:00')
    assert generate_candidates(activity,people,[day],now)['other_windows'][0]['classification']=='people_only'
    people.append({'id':'extra','required':True,'state_for':lambda a,b:'free'})
    day.update(fresh=True,slots=[slot('a','c','18:00','19:00')])
    result=generate_candidates(activity,people,[day],now)
    assert not result['candidates'] and result['other_windows'][0]['classification']=='too_many_required'
