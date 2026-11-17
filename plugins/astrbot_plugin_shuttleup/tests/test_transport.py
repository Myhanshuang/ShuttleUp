import json
from types import SimpleNamespace

import httpx
import pytest

from plugins.astrbot_plugin_shuttleup.main import ShuttleUpPlugin


@pytest.mark.asyncio
async def test_direct_create_dispatches_platform_identity_and_group_context():
    payloads = []
    def handler(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={'reply': {'text': '活动已创建', 'links': []}})
    plugin = object.__new__(ShuttleUpPlugin)
    plugin.config = {'base_url': 'http://testserver', 'api_token': 'test'}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url='http://testserver') as client:
        plugin.client = client
        event = SimpleNamespace(message_str='/发起约球 周六 夜场', get_platform_id=lambda: 'qq-instance-1', get_sender_id=lambda: '123', get_sender_name=lambda: '小林', is_private_chat=lambda: False, unified_msg_origin='qq-instance-1:GroupMessage:456', message_obj=SimpleNamespace(message_id='789'), plain_result=lambda text: text)
        results = [r async for r in plugin.create_activity(event)]
    assert results == ['活动已创建']
    assert payloads[0]['args']['title'] == '周六 夜场'
    assert payloads[0]['platform_id'] == 'qq-instance-1'
    assert payloads[0]['is_private'] is False
