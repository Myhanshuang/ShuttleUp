import asyncio
import contextlib

import httpx

try:
    from astrbot.api.event import filter, AstrMessageEvent, MessageChain
    from astrbot.api.star import Context, Star, register
except ImportError:  # Unit tests do not need an AstrBot installation.
    filter = type("Filter", (), {name: staticmethod(lambda *_a, **_k: lambda fn: fn) for name in ("command", "regex")})
    class Star:
        pass
    class AstrMessageEvent:
        pass
    def register(*_a, **_k):
        return lambda cls: cls

from .parser import parse


@register("shuttleup", "ShuttleUp", "公共约球入口：从群内发起到 AA 结清", "1.1.0")
class ShuttleUpPlugin(Star):
    def __init__(self, context, config):
        super().__init__(context)
        self.context = context
        self.config = config
        self.client = httpx.AsyncClient(base_url=config["base_url"].rstrip("/"), timeout=30)
        self.poll_task = asyncio.create_task(self.poll())

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.config['api_token']}"}

    @filter.command("绑定身份")
    async def bind_identity(self, event: AstrMessageEvent, nickname: str = ""):
        """为当前发送消息的 QQ 绑定一个 ShuttleUp 身份。"""
        try:
            parsed = parse(event.message_str)
            if parsed["command"] != "identity.create":
                parsed = parse(f"/绑定身份 {nickname}")
        except ValueError as error:
            yield event.plain_result(str(error))
            return
        async for result in self.execute(event, parsed):
            yield result

    @filter.command("发起约球")
    async def create_activity(self, event: AstrMessageEvent, title: str = "羽毛球约球"):
        """在当前群发起约球，无需先到网页注册。"""
        # Read the original text to preserve activity names containing spaces.
        parsed = parse(event.message_str)
        if parsed["command"] != "activity.create":
            parsed = parse(f"/发起约球 {title}")
        async for result in self.execute(event, parsed):
            yield result

    @filter.regex(r"^\s*/?羽球(?:\s|$)")
    async def shuttleup(self, event: AstrMessageEvent):
        try:
            parsed = parse(event.message_str)
        except ValueError as error:
            yield event.plain_result(str(error))
            return
        async for result in self.execute(event, parsed):
            yield result

    def linked_text(self, text, links):
        return text + "".join(f"\n{link['label']}：{self.config['base_url'].rstrip('/')}{link['path']}" for link in links)

    async def execute(self, event, parsed):
        payload = {
            "bot_key": self.config.get("bot_key", "main"),
            "platform_id": event.get_platform_id(),
            "sender_id": event.get_sender_id(),
            "sender_name": event.get_sender_name()[:40],
            "is_private": event.is_private_chat(),
            "umo": str(event.unified_msg_origin),
            "message_id": str(event.message_obj.message_id),
            **parsed,
        }
        try:
            response = await self.client.post("/bot/v1/commands", json=payload, headers={**self.headers, "Idempotency-Key": f"astrbot:{payload['platform_id']}:{payload['message_id']}"})
            data = response.json()
            if response.is_error:
                error = data.get("error") or data.get("detail") or {}
                yield event.plain_result(error.get("message", "请检查指令参数。") if isinstance(error, dict) else "请检查指令参数。")
                return
            reply = data["reply"]
            if reply.get("mode") == "private" and not event.is_private_chat():
                yield event.plain_result("请私聊我执行此指令。")
                return
            yield event.plain_result(self.linked_text(reply["text"], reply.get("links", [])))
        except (httpx.HTTPError, ValueError, KeyError):
            yield event.plain_result("ShuttleUp 暂时无法连接，请稍后重试。")

    async def poll(self):
        while True:
            try:
                response = await self.client.get("/bot/v1/deliveries", params={"wait": 25, "limit": 20}, headers=self.headers)
                response.raise_for_status()
                for item in response.json().get("items", []):
                    try:
                        text = self.linked_text(item["text"], item.get("links", []))
                        await self.context.send_message(item["umo"], MessageChain().message(text))
                        result = await self.client.post(f"/bot/v1/deliveries/{item['id']}/ack", json={"lease_token": item["lease_token"]}, headers=self.headers)
                        result.raise_for_status()
                    except Exception as error:
                        await self.client.post(f"/bot/v1/deliveries/{item['id']}/fail", json={"lease_token": item["lease_token"], "error": type(error).__name__}, headers=self.headers)
            except Exception:
                await asyncio.sleep(5)

    async def terminate(self):
        self.poll_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.poll_task
        await self.client.aclose()
