import registry
import coord_cli


def test_claim_then_list(tmp_path, capsys):
    p = tmp_path / "c.json"
    assert coord_cli.run(
        ["claim", "--session", "s1", "--kind", "file_glob",
         "--value", "autogis/adapters/cli.py"], p) == 0
    coord_cli.run(["list"], p)
    out = capsys.readouterr().out
    assert "s1" in out and "autogis/adapters/cli.py" in out


def test_release(tmp_path):
    p = tmp_path / "c.json"
    registry.claim(p, "s1", "branch", "feat/x")
    assert coord_cli.run(["release", "--session", "s1"], p) == 0
    assert registry.list_claims(p, include_stale=True) == []
