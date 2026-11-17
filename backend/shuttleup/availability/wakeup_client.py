"""Read a user-supplied WakeUp share; never log request bodies or upstream errors."""
import asyncio
import base64
import json
from types import SimpleNamespace

import httpx

from . import wakeup_crypto as crypto

HOST = "https://api.wakeup.fun"
VERSION = 450  # Public 6.1.70 client profile, verified against a live share.
MAX_RESPONSE = 2 * 1024 * 1024


class WakeUpError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


async def post(client, path, body):
    async with client.stream("POST", HOST + path, content=body.encode()) as response:
        if response.status_code == 429:
            raise WakeUpError("WAKEUP_RATE_LIMITED", "WakeUp 请求过于频繁，请稍后再试。")
        response.raise_for_status()
        data = bytearray()
        async for chunk in response.aiter_bytes():
            data.extend(chunk)
            if len(data) > MAX_RESPONSE:
                raise WakeUpError("WAKEUP_INVALID_DATA", "课表数据过大，无法导入。")
        result = json.loads(data)
        if not isinstance(result, dict):
            raise ValueError("response shape")
        return result


async def fetch_share(code):
    cuid = crypto.cuid_from_android_id("0000000000000000")
    adid = crypto.adid_from_android_id("0000000000000000")
    args = SimpleNamespace(area="", screensize="1080x2400", cuid=cuid, city="",
        abis="arm64-v8a", channel="100271a", app_bit="64", device_id="",
        public_token="1_XPXQH3c5HRPtFHkSwi3sCCURmT25QfxM", adid=adid,
        province="", app_id="wakeup", download_type="1", sdk=35,
        device="Pixel 7", brand="google", operatorid="")
    common = crypto.make_common_params(args, {"version_code": VERSION,
        "package": "com.suda.yzune.wakeupschedule", "version_name": "6.1.70"})
    headers = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept-Encoding": "gzip, deflate", "na__zyb_source__": "wakeup",
        "zyb-cuid": cuid, "zyb-adid": adid}
    try:
        async with asyncio.timeout(35), httpx.AsyncClient(timeout=15,
                follow_redirects=False, trust_env=False, headers=headers) as client:
            sign, random_value, _ = crypto.make_sign_a(cuid, "318c6d4f74655d4f032fb0466bcfdfbc")
            response = await post(client, crypto.ANTISPAM_PATH,
                crypto.build_antispam_request(sign, common)["body"])
            sign_b = crypto.extract_sign_b(response)
            if not sign_b:
                raise WakeUpError("WAKEUP_PROTOCOL_REJECTED", "WakeUp 未接受当前接口请求，请稍后重试或联系管理员。")
            token, _ = crypto.token_from_sign_b(sign_b, random_value)
            request = crypto.build_share_request(code, token, VERSION, common)
            response = await post(client, crypto.SHARE_PATH, request["body"])
            if response.get("errNo") != 0:
                raise WakeUpError("WAKEUP_SHARE_UNAVAILABLE", "无法读取分享，请检查口令或在 WakeUp 中重新分享。")
            encrypted = response.get("data")
            if isinstance(encrypted, dict): encrypted = encrypted.get("data")
            decoded = json.loads(crypto.rc4_crypt(base64.b64decode(encrypted, validate=True), request["rc4_key"]))
            share = decoded.get("shareData")
            if not isinstance(share, str) or not share.strip():
                raise WakeUpError("WAKEUP_SHARE_UNAVAILABLE", "分享已失效或课表为空，请在 WakeUp 中重新分享。")
            return json.dumps({"shareData": share}, ensure_ascii=False).encode()
    except WakeUpError:
        raise
    except (httpx.TimeoutException, TimeoutError):
        raise WakeUpError("WAKEUP_TIMEOUT", "连接 WakeUp 超时，请稍后重试。") from None
    except httpx.HTTPError:
        raise WakeUpError("WAKEUP_NETWORK_ERROR", "无法连接 WakeUp 分享服务，请稍后重试。") from None
    except (ValueError, TypeError, KeyError, IndexError, UnicodeError):
        raise WakeUpError("WAKEUP_INVALID_DATA", "WakeUp 响应格式不兼容，未导入任何课程。") from None
