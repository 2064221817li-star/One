"""Fetcher 测试：本地文件 + httpx MockTransport，全程离线。

SSRF 相关用例通过注入假解析器控制解析结果，不做真实 DNS 查询。
"""

import httpx
import pytest

from smart_proxy_manager import fetcher
from smart_proxy_manager.fetcher import FetchError


def public_resolver(host: str) -> list[str]:
    return ["93.184.216.34"]


def private_resolver(host: str) -> list[str]:
    return ["10.0.0.8"]


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_fetch_local_file(tmp_path):
    path = tmp_path / "sub.txt"
    path.write_text("ss://abc", encoding="utf-8")
    assert fetcher.fetch_source(str(path), "file") == "ss://abc"


def test_fetch_local_file_missing(tmp_path):
    with pytest.raises(FetchError, match="不存在"):
        fetcher.fetch_source(str(tmp_path / "nope.txt"), "file")


def test_fetch_local_file_empty(tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("   \n", encoding="utf-8")
    with pytest.raises(FetchError, match="为空"):
        fetcher.fetch_source(str(path), "file")


def test_fetch_http_ok():
    transport = _transport(lambda req: httpx.Response(200, text="hello-sub"))
    text = fetcher.fetch_source(
        "https://example.com/sub", "url",
        resolver=public_resolver, transport=transport,
    )
    assert text == "hello-sub"


def test_fetch_http_status_error_hides_token():
    transport = _transport(lambda req: httpx.Response(500, text="boom"))
    with pytest.raises(FetchError) as excinfo:
        fetcher.fetch_source(
            "https://example.com/sub?token=FAKE-SUB-TOKEN-abcdef", "url",
            resolver=public_resolver, transport=transport,
        )
    message = str(excinfo.value)
    assert "HTTP 500" in message
    assert "FAKE-SUB-TOKEN-abcdef" not in message


def test_fetch_http_empty_body():
    transport = _transport(lambda req: httpx.Response(200, text=""))
    with pytest.raises(FetchError, match="为空"):
        fetcher.fetch_source(
            "https://example.com/sub", "url",
            resolver=public_resolver, transport=transport,
        )


def test_fetch_http_oversize():
    transport = _transport(lambda req: httpx.Response(200, text="x" * 64))
    with pytest.raises(FetchError, match="过大"):
        fetcher.fetch_source(
            "https://example.com/sub", "url", max_bytes=10,
            resolver=public_resolver, transport=transport,
        )


def test_fetch_http_timeout():
    def handler(req):
        raise httpx.ConnectTimeout("slow", request=req)

    with pytest.raises(FetchError, match="超时"):
        fetcher.fetch_source(
            "https://example.com/sub", "url",
            resolver=public_resolver, transport=_transport(handler),
        )


def test_fetch_redirect_followed_and_each_hop_checked():
    def handler(req):
        if req.url.path == "/old":
            return httpx.Response(302, headers={"location": "/new"})
        return httpx.Response(200, text="after-redirect")

    text = fetcher.fetch_source(
        "https://example.com/old", "url",
        resolver=public_resolver, transport=_transport(handler),
    )
    assert text == "after-redirect"


def test_fetch_redirect_limit():
    def handler(req):
        return httpx.Response(302, headers={"location": "/loop"})

    with pytest.raises(FetchError, match="重定向次数超过上限"):
        fetcher.fetch_source(
            "https://example.com/loop", "url", max_redirects=3,
            resolver=public_resolver, transport=_transport(handler),
        )


def test_fetch_redirect_to_private_blocked():
    def handler(req):
        return httpx.Response(
            302, headers={"location": "http://127.0.0.1:7890/admin"}
        )

    with pytest.raises(FetchError, match="非公网"):
        fetcher.fetch_source(
            "https://example.com/jump", "url",
            resolver=public_resolver, transport=_transport(handler),
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:7890/sub",
        "http://[::1]/sub",
        "http://192.168.1.10/sub",
        "http://169.254.1.1/sub",
        "http://10.1.2.3/sub",
    ],
)
def test_fetch_private_literal_blocked_by_default(url):
    transport = _transport(lambda req: httpx.Response(200, text="x"))
    with pytest.raises(FetchError, match="非公网"):
        fetcher.fetch_source(
            url, "url", resolver=public_resolver, transport=transport
        )


def test_fetch_domain_resolving_to_private_blocked():
    transport = _transport(lambda req: httpx.Response(200, text="x"))
    with pytest.raises(FetchError, match="非公网"):
        fetcher.fetch_source(
            "https://evil.example.com/sub", "url",
            resolver=private_resolver, transport=transport,
        )


def test_fetch_private_allowed_with_explicit_switch():
    transport = _transport(lambda req: httpx.Response(200, text="lan-sub"))
    text = fetcher.fetch_source(
        "http://192.168.1.10/sub", "url", allow_private=True,
        resolver=public_resolver, transport=transport,
    )
    assert text == "lan-sub"


def test_fetch_non_http_scheme_rejected():
    with pytest.raises(FetchError, match="只支持"):
        fetcher.fetch_source(
            "ftp://example.com/sub", "url",
            resolver=public_resolver,
            transport=_transport(lambda req: httpx.Response(200, text="x")),
        )


def test_fetch_unknown_kind():
    with pytest.raises(FetchError, match="未知来源类型"):
        fetcher.fetch_source("whatever", "carrier-pigeon")
