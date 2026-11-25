"""CLI 退出码与 sources 子命令测试（临时数据库，不访问网络）。

argparse 的 --help 与参数错误通过 SystemExit 抛出，这里断言其退出码；
业务路径调用 main() 并断言返回值。
"""

import pytest

from smart_proxy_manager.cli import main


def test_help_exit_code_zero(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    assert "spm" in capsys.readouterr().out


def test_unknown_argument_exit_code_two():
    with pytest.raises(SystemExit) as excinfo:
        main(["--definitely-not-a-flag"])
    assert excinfo.value.code == 2


def test_no_command_returns_two():
    assert main([]) == 2


def test_sources_list_empty(tmp_path, capsys):
    db = tmp_path / "spm.db"
    assert main(["--db", str(db), "sources", "list"]) == 0
    assert "暂无来源" in capsys.readouterr().out


def test_sources_add_then_list(tmp_path, capsys):
    db = tmp_path / "spm.db"
    rc = main(
        [
            "--db", str(db), "sources", "add",
            "--name", "mine", "--kind", "url",
            "--location", "https://example.com/sub",
        ]
    )
    assert rc == 0
    capsys.readouterr()

    assert main(["--db", str(db), "sources", "list"]) == 0
    out = capsys.readouterr().out
    assert "mine" in out
    assert "私人" in out


def test_sources_add_duplicate_name_returns_one(tmp_path, capsys):
    db = tmp_path / "spm.db"
    args = [
        "--db", str(db), "sources", "add",
        "--name", "dup", "--kind", "file", "--location", "a.yaml",
    ]
    assert main(args) == 0
    capsys.readouterr()
    assert main(args) == 1
    assert "已存在" in capsys.readouterr().err


def test_sources_add_bad_kind_exit_code_two(tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        main(
            [
                "--db", str(tmp_path / "spm.db"), "sources", "add",
                "--name", "x", "--kind", "ftp", "--location", "ftp://x",
            ]
        )
    assert excinfo.value.code == 2
