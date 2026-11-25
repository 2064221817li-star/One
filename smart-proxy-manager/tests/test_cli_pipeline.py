"""CLI 端到端离线冒烟：文件来源 update → stats → generate → validate。

样例订阅写在临时目录，数据库也在临时目录，全程不访问网络。
"""

import yaml

from smart_proxy_manager.cli import main

from conftest import base64_subscription, uri_subscription, yaml_subscription


def _add_file_source(db, name, path) -> None:
    assert main([
        "--db", str(db), "sources", "add", "--name", name,
        "--kind", "file", "--location", str(path),
    ]) == 0


def test_full_pipeline_with_two_sources(tmp_path, capsys):
    db = tmp_path / "spm.db"
    yaml_file = tmp_path / "nodes.yaml"
    yaml_file.write_text(yaml_subscription(), encoding="utf-8")
    b64_file = tmp_path / "nodes.txt"
    b64_file.write_text(base64_subscription(), encoding="utf-8")

    _add_file_source(db, "yaml-src", yaml_file)
    _add_file_source(db, "b64-src", b64_file)
    capsys.readouterr()

    # update 两个来源
    assert main(["--db", str(db), "update", "yaml-src"]) == 0
    out = capsys.readouterr().out
    assert "解析 2 条" in out and "新增 2" in out
    assert "跳过（协议不支持） 1" in out

    assert main(["--db", str(db), "update", "b64-src"]) == 0
    capsys.readouterr()

    # 重复 update：全部计为重复，不新增
    assert main(["--db", str(db), "update", "--all"]) == 0
    out = capsys.readouterr().out
    assert "新增 0" in out

    # stats：YAML 源 2 条 + B64 源 2 条，但 B64 的 ss/trojan 与
    # URI 样例不是同一批，这里两源共 4 条互不重复节点
    assert main(["--db", str(db), "stats"]) == 0
    out = capsys.readouterr().out
    assert "节点总数：4" in out
    assert "ss: 2" in out

    # generate 完整 profile 与 provider
    profile = tmp_path / "gen" / "profile.yaml"
    assert main([
        "--db", str(db), "generate", "--output", str(profile),
    ]) == 0
    capsys.readouterr()
    data = yaml.safe_load(profile.read_text(encoding="utf-8"))
    assert len(data["proxies"]) == 4
    assert "proxy-groups" in data

    provider = tmp_path / "gen" / "provider.yaml"
    assert main([
        "--db", str(db), "generate", "--provider-only",
        "--output", str(provider),
    ]) == 0
    capsys.readouterr()
    pdata = yaml.safe_load(provider.read_text(encoding="utf-8"))
    assert set(pdata.keys()) == {"proxies"}

    # validate 生成结果
    assert main(["validate", str(profile)]) == 0
    assert "校验通过" in capsys.readouterr().out


def test_update_uri_subscription_file(tmp_path, capsys):
    db = tmp_path / "spm.db"
    sub = tmp_path / "uri.txt"
    sub.write_text(uri_subscription(), encoding="utf-8")
    _add_file_source(db, "uri-src", sub)
    capsys.readouterr()
    assert main(["--db", str(db), "update", "uri-src"]) == 0
    out = capsys.readouterr().out
    assert "解析 4 条" in out
    assert "跳过（协议不支持） 2" in out
    assert "失败 2" in out


def test_update_missing_source_returns_one(tmp_path, capsys):
    db = tmp_path / "spm.db"
    assert main(["--db", str(db), "update", "不存在的来源"]) == 1
    assert "不存在" in capsys.readouterr().err


def test_update_missing_file_returns_one(tmp_path, capsys):
    db = tmp_path / "spm.db"
    _add_file_source(db, "gone", tmp_path / "not-there.yaml")
    capsys.readouterr()
    assert main(["--db", str(db), "update", "gone"]) == 1
    assert "不存在" in capsys.readouterr().err


def test_update_without_target_returns_two(tmp_path):
    assert main(["--db", str(tmp_path / "spm.db"), "update"]) == 2


def test_generate_without_nodes_returns_one(tmp_path, capsys):
    db = tmp_path / "spm.db"
    assert main(["--db", str(db), "generate"]) == 1
    assert "没有可用节点" in capsys.readouterr().err


def test_validate_bad_file_returns_one(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("secret: x\nproxies: []\n", encoding="utf-8")
    assert main(["validate", str(bad)]) == 1
    err = capsys.readouterr().err
    assert "控制面键" in err


def test_validate_missing_file_returns_one(tmp_path, capsys):
    assert main(["validate", str(tmp_path / "nope.yaml")]) == 1
    assert "不存在" in capsys.readouterr().err


def test_stats_empty_db(tmp_path, capsys):
    db = tmp_path / "spm.db"
    assert main(["--db", str(db), "stats"]) == 0
    assert "节点总数：0" in capsys.readouterr().out
