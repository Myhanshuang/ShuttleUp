import asyncio
import contextlib
import httpx

try:
    from astrbot.api.event import filter, AstrMessageEvent
    from astrbot.api.star import Context, Star, register
    from astrbot.api.message_components import Plain
except ImportError:  # tests and packaging without AstrBot
    filter=type("Filter",(),{"command_group":staticmethod(lambda *_a,**_k: lambda cls: cls)})
    class Star: pass
    def register(*_a,**_k): return lambda cls: cls

from .parser import parse


@register("shuttleup","ShuttleUp","从约球到 AA 结清", "1.0.0")
class ShuttleUpPlugin(Star):
    def __init__(self,context,config):
        super().__init__(context); self.context=context; self.config=config; self.client=httpx.AsyncClient(base_url=config["base_url"].rstrip("/"),timeout=30); self.poll_task=asyncio.create_task(self.poll())

    @filter.command_group("羽球")
    async def shuttleup(self,event):
        try: parsed=parse(event.message_str)
        except ValueError as error: yield event.plain_result(str(error)); return
        payload={"bot_key":self.config.get("bot_key","main"),"platform_id":event.get_platform_name(),"sender_id":event.get_sender_id(),"umo":str(event.unified_msg_origin),"message_id":str(event.message_obj.message_id),**parsed}
        response=await self.client.post("/bot/v1/commands",json=payload,headers={"Authorization":f"Bearer {self.config['api_token']}","Idempotency-Key":f"astrbot:{payload['platform_id']}:{payload['message_id']}"}); data=response.json()
        if response.is_error: yield event.plain_result(data.get("detail",{}).get("message","操作失败")); return
        text=data["reply"]["text"]
        for link in data["reply"].get("links",[]): text+=f"\n{link['label']}：{self.config['base_url'].rstrip('/')}{link['path']}"
        yield event.plain_result(text)

    async def poll(self):
        while True:
            try:
                response=await self.client.get("/bot/v1/deliveries",params={"wait":25,"limit":20},headers={"Authorization":f"Bearer {self.config['api_token']}"})
                for item in response.json().get("items",[]):
                    try:
                        await self.context.send_message(item["umo"],Plain(item["text"])); await self.client.post(f"/bot/v1/deliveries/{item['id']}/ack",json={"lease_token":item["lease_token"]},headers={"Authorization":f"Bearer {self.config['api_token']}"})
                    except Exception as error: await self.client.post(f"/bot/v1/deliveries/{item['id']}/fail",json={"lease_token":item["lease_token"],"error":type(error).__name__},headers={"Authorization":f"Bearer {self.config['api_token']}"})
            except Exception: await asyncio.sleep(5)

    async def terminate(self):
        self.poll_task.cancel()
        with contextlib.suppress(asyncio.CancelledError): await self.poll_task
        await self.client.aclose()

