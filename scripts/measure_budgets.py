#!/usr/bin/env python3
import gzip
import json
import resource
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from shuttleup.venues.candidates import generate_candidates


def bundles():
    assets=ROOT/'backend/shuttleup/static/assets';js=sum(len(gzip.compress(p.read_bytes())) for p in assets.glob('*.js'));css=sum(len(gzip.compress(p.read_bytes())) for p in assets.glob('*.css'));return {'all_js_gzip_kb':round(js/1024,2),'all_css_gzip_kb':round(css/1024,2)}


def candidate_benchmark():
    start=datetime(2026,9,19,18,tzinfo=timezone(timedelta(hours=8)));people=[{'id':f'p{i}','required':i<2,'state_for':lambda _s,_e:'free'} for i in range(30)];days=[]
    for venue_index in range(3):
        for day in range(14):
            s=start+timedelta(days=day);slots=[]
            for court in range(3):
                for hour in range(4):
                    a=s+timedelta(hours=hour);b=a+timedelta(hours=1);slots.append({'external_slot_id':f'{venue_index}-{day}-{court}-{hour}','court_id':f'c{court}','starts_at':a.isoformat(),'ends_at':b.isoformat(),'status':'available','price_cents':6000,'remaining_count':1})
            days.append({'venue_id':f'v{venue_index}','venue_name':f'场馆{venue_index}','coverage':{'identity_mode':'court'},'slots':slots,'fresh':True})
    activity={'version':1,'duration_minutes':120,'min_players':4,'max_players':6,'court_count':2,'venue_preferences':['v0','v1','v2']};samples=[]
    for _ in range(25):
        begin=time.perf_counter();generate_candidates(activity,people,days,start-timedelta(days=1));samples.append((time.perf_counter()-begin)*1000)
    return {'candidate_p50_ms':round(statistics.median(samples),2),'candidate_p95_ms':round(sorted(samples)[int(len(samples)*.95)-1],2),'idle_process_rss_mb':round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,2)}


if __name__=='__main__':print(json.dumps({**bundles(),**candidate_benchmark()},ensure_ascii=False,indent=2))

