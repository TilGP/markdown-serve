"""Config normalization and sidebar prefs."""

from __future__ import annotations

from markdown_serve.config import (
    DEFAULT_CONFIG,
    _normalize,
    update_config,
    wrap_css_vars,
)


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


def test_normalize_adds_wrap_defaults():
    cfg = _normalize({})
    assert cfg["text"] == {"wrap": True, "width": 90}
    assert cfg["tables"] == {"wrap": True, "width": 80}


def test_normalize_clamps_and_coerces_wrap():
    cfg = _normalize(
        {
            "text": {"wrap": 0, "width": "9999"},
            "tables": {"wrap": "yes", "width": "not-a-number"},
        }
    )
    assert cfg["text"] == {"wrap": False, "width": 300}
    assert cfg["tables"] == {"wrap": True, "width": 80}
    assert _normalize({"text": {"width": 1}})["text"]["width"] == 20
    assert _normalize({"text": "junk"})["text"] == DEFAULT_CONFIG["text"]


def test_update_config_merges_wrap(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    monkeypatch.setattr("markdown_serve.config.CONFIG_PATH", path)
    path.write_text('{"theme":"light"}\n', encoding="utf-8")
    cfg = update_config({"tables": {"wrap": False}})
    assert cfg["tables"] == {"wrap": False, "width": 80}
    assert cfg["text"] == {"wrap": True, "width": 90}
    cfg2 = update_config({"text": {"width": 60}})
    assert cfg2["text"] == {"wrap": True, "width": 60}
    assert cfg2["tables"] == {"wrap": False, "width": 80}


def test_wrap_css_vars():
    css = wrap_css_vars(_normalize({"text": {"wrap": False, "width": 70}}))
    assert "--text-width: 70ch;" in css
    assert "--text-max-width: none;" in css
    assert "--table-cell-max-width: 80ch;" in css
    assert "--table-cell-white-space: normal;" in css
    css_nowrap = wrap_css_vars(_normalize({"tables": {"wrap": False}}))
    assert "--table-cell-max-width: none;" in css_nowrap
    assert "--table-cell-white-space: nowrap;" in css_nowrap
