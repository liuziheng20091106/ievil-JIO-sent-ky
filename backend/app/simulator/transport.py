"""模拟器的传输层：把「HTTP 请求」抽象成可替换的调用约定。

同一套虚拟玩家代码因此既能跑在进程内 TestClient（回归检查，快且无端口），
也能跑在真实 uvicorn 服务上（联调/压测，覆盖真实网络与并发）。
"""

import json
import urllib.error
import urllib.request


class TestClientTransport:
    """进程内 TestClient 适配；不需要监听端口，检查里用它最省事。"""

    def __init__(self, client):
        self.client = client

    def __call__(self, method, path, body, headers):
        response = self.client.request(
            method,
            path,
            content=None if body is None else json.dumps(body, ensure_ascii=False),
            headers={**headers, "Content-Type": "application/json"} if body is not None else headers,
        )
        payload = None
        if response.content:
            try:
                payload = response.json()
            except ValueError:
                payload = response.text
        return response.status_code, payload


class HttpTransport:
    """真实 HTTP 适配；用于对着已启动的 uvicorn 跑独立多进程模拟。"""

    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")

    def __call__(self, method, path, body, headers):
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(self.base_url + path, data=data, method=method)
        for key, value in headers.items():
            request.add_header(key, value)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                return response.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                payload = json.loads(raw) if raw else None
            except ValueError:
                payload = raw.decode("utf-8", "replace")
            return error.code, payload


def group_number(value):
    """把群号收敛成单个整数。

    服务端的 ``QQLogin.group_id`` 是 ``StrictInt``，命令行与环境变量传进来的却是
    字符串；``GAME_QQ_GROUP_ID`` 还允许逗号分隔多个群，这里取第一个群。
    """

    text = str(value).split(",")[0].strip()
    if not text.isdigit():
        raise RuntimeError(f"群号必须是数字：{value!r}")
    return int(text)


def gateway_authenticator(transport, gateway_token, group_id):
    """返回一个走真实网关接口的登录码核销函数。"""

    default_group = group_number(group_id)

    def authenticate(code, qq_id, nickname, group):
        status, payload = transport(
            "POST",
            "/api/internal/qq/login",
            {
                "code": code,
                "qq_id": qq_id,
                "nickname": nickname,
                "avatar_url": f"https://example.invalid/{qq_id}",
                "group_id": default_group if group is None else group_number(group),
            },
            {"X-Gateway-Token": gateway_token},
        )
        if status >= 400:
            raise RuntimeError(f"网关核销失败 {status}: {payload}")

    return authenticate
