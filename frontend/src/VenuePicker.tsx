import {useEffect,useState} from "react";
import {api} from "./api/client";
export default function VenuePicker({value,onChange}:{value:string[];onChange:(value:string[])=>void}) {
 const [venues,setVenues]=useState<{id:string;name:string}[]>([]),[error,setError]=useState("");
 useEffect(()=>{let active=true;api<{items:{id:string;name:string}[]}>("/venues").then(d=>{if(active)setVenues(d.items);}).catch(e=>{if(active)setError(e.message);});return()=>{active=false;};},[]);
 return <fieldset><legend>活动场馆</legend>{venues.map(v=><label key={v.id}><input type="checkbox" checked={value.includes(v.id)} onChange={e=>onChange(e.target.checked?[...value,v.id]:value.filter(id=>id!==v.id))}/>{v.name}</label>)}
 {error&&<p role="alert">{error}</p>}{!venues.length&&!error&&<p>暂无可选场馆，可先邀请成员填写时间。</p>}
 {!value.length&&<p className="muted">尚未选择场馆，暂时无法生成可订方案；之后可在活动中设置。</p>}</fieldset>;
}
