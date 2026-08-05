"""Config normalization and sidebar prefs."""

from __future__ import annotations

from markdown_serve.config import DEFAULT_CONFIG, _normalize, update_config


def test_normalize_adds_sidebar_defaults():
    cfg = _normalize({"theme": "dark"})
    assert cfg["sidebars"] == {"files_collapsed": False, "toc_collapsed": False}
    assert cfg["theme"] == "dark"


def test_normalize_keeps_sidebar_bools():
    cfg = _normalize(
        {
            "sidebars": {"files_collapsed": True, "toc_collapsed": 1},
        }
    )
    assert cfg["sidebars"]["files_collapsed"] is True
    assert cfg["sidebars"]["toc_collapsed"] is True


def test_update_config_merges_sidebars(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    monkeypatch.setattr("markdown_serve.config.CONFIG_PATH", path)
    path.write_text(
        '{"theme":"light","styles":{"light":"default","dark":"nord"},'
        '"fonts":{"sans":["sans-serif"],"mono":["monospace"]}}\n',
        encoding="utf-8",
    )
    cfg = update_config({"sidebars": {"files_collapsed": True}})
    assert cfg["sidebars"]["files_collapsed"] is True
    assert cfg["sidebars"]["toc_collapsed"] is False
    cfg2 = update_config({"sidebars": {"toc_collapsed": True}})
    assert cfg2["sidebars"] == {"files_collapsed": True, "toc_collapsed": True}


def test_default_config_has_sidebars():
    assert "sidebars" in DEFAULT_CONFIG
