"""脱敏专项测试：假凭据不得出现在异常、错误列表、错误报告与 CLI 输出中。

样例凭据全部是 conftest 里的 FAKE-* 假值；断言方式为全文检索，
任何一处泄漏都会让测试失败。
"""

import httpx
import pytest

from smart_proxy_manager import fetcher, parser
from smart_proxy_manager.cli import main
from smart_proxy_manager.config_validate import (
    ConfigValidationError,
    write_validated_profile,
)
from smart_proxy_manager.redact import mask_secret, redact_text

from conftest import (
    ALL_FAKE_SECRETS,
    FAKE_SS_PASSWORD,
    FAKE_TOKEN,
    FAKE_TROJAN_PASSWORD,
    FAKE_UUID,
    ss_uri,
    trojan_uri,
    vmess_uri,
)


def _assert_no_secrets(text: str) -> None:
    for secret in ALL_FAKE_SECRETS:
        assert secret not in text


def test_mask_secret_reveals_nothing():
    masked = mask_secret(FAKE_SS_PASSWORD)
    assert FAKE_SS_PASSWORD not in masked
    assert masked.startswith("***")


def test_redact_text_masks_known_secrets_and_url_params():
    text = redact_text(
        f"下载 https://example.com/sub?token={FAKE_TOKEN}&x=1 失败，"
        f"密码 {FAKE_SS_PASSWORD}",
        secrets=[FAKE_SS_PASSWORD],
    )
    _assert_no_secrets(text)
    assert "x=1" in text  # 非敏感参数保留


def test_parser_errors_contain_no_credentials():
    content = "\n".join(
        [
            ss_uri(password=""),  # 无效（会在拼接时变成空密码）
            vmess_uri(uuid="bad-uuid"),
            "trojan://@nohost",
            trojan_uri(),
        ]
    )
    result = parser.parse_subscription(content)
    _assert_no_secrets("\n".join(result.errors))


def test_fetcher_error_for_token_url_is_redacted():
    def handler(req):
        return httpx.Response(404, text="not found")

    url = f"https://example.com/sub?token={FAKE_TOKEN}"
    with pytest.raises(fetcher.FetchError) as excinfo:
        fetcher.fetch_source(
            url, "url",
            resolver=lambda host: ["93.184.216.34"],
            transport=httpx.MockTransport(handler),
        )
    _assert_no_secrets(str(excinfo.value))
    assert "404" in str(excinfo.value)


def test_validation_error_and_report_contain_no_credentials(tmp_path):
    target = tmp_path / "profile.yaml"
    bad = (
        "mixed-port: 7890\n"
        "proxies:\n"
        f"  - {{name: x, type: ss, server: a.example.com, port: 8388,"
        f" cipher: aes-256-gcm, password: {FAKE_SS_PASSWORD}}}\n"
        f"  - {{name: y, type: trojan, server: b.example.com, port: 'bad',"
        f" password: {FAKE_TROJAN_PASSWORD}}}\n"
        f"  - {{name: z, type: vmess, server: c.example.com, port: 443,"
        f" uuid: {FAKE_UUID}}}\n"
    )
    with pytest.raises(ConfigValidationError) as excinfo:
        write_validated_profile(bad, target)
    _assert_no_secrets(str(excinfo.value))
    reports = list(tmp_path.glob("validation-error-*.txt"))
    assert reports, "校验失败应产生错误报告"
    _assert_no_secrets(reports[0].read_text(encoding="utf-8"))


def test_cli_outputs_contain_no_credentials(tmp_path, capsys):
    # 用含假凭据的订阅走完 update → stats → generate → validate，
    # 全程 stdout/stderr 都不得出现凭据明文。
    sub_file = tmp_path / "sub.txt"
    sub_file.write_text(
        "\n".join([ss_uri(), trojan_uri(), vmess_uri()]), encoding="utf-8"
    )
    db = tmp_path / "spm.db"
    out_file = tmp_path / "gen.yaml"
    assert main([
        "--db", str(db), "sources", "add", "--name", "priv",
        "--kind", "file", "--location", str(sub_file),
    ]) == 0
    assert main(["--db", str(db), "update", "priv"]) == 0
    assert main(["--db", str(db), "stats"]) == 0
    assert main([
        "--db", str(db), "generate", "--output", str(out_file),
    ]) == 0
    assert main(["validate", str(out_file)]) == 0
    captured = capsys.readouterr()
    _assert_no_secrets(captured.out)
    _assert_no_secrets(captured.err)
