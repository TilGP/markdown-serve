"""Signature fences link documented names, and definitions list their references."""

from __future__ import annotations

from markdown_serve.codedoc.xrefs import index_pages, render_codedoc_page


def _page(name: str, anchor: str, signature: str, *, level: str = "##") -> str:
    return "\n".join(
        [
            f'<a id="{anchor}"></a>',
            f"{level} {name}",
            "",
            "```cppdoc",
            signature,
            "```",
            "",
            f"Defined at [file:1]({name}.hpp?line=1).",
            "",
        ]
    )


def test_signature_links_qualified_names_and_lists_references() -> None:
    handler = _page("engine::EngineEtcdHandler", "engine-engineetcdhandler", "class EngineEtcdHandler")
    config = _page("engine::Config", "engine-config", "struct Config")
    caller = _page(
        "createEtcdHandler",
        "createetcdhandler",
        "shared_ptr<engine::EngineEtcdHandler> createEtcdHandler(const engine::Config &)",
    )
    pages = [
        ("engineapps/engine/server/engine_etcd_handler.hpp", handler),
        ("engineapps/engine/args.hpp", config),
        ("engineapps/engine/main.cpp", caller),
    ]
    index = index_pages(pages)
    html = render_codedoc_page(caller, "engineapps/engine/main.cpp", index)
    assert 'href="server/engine_etcd_handler.hpp#engine-engineetcdhandler"' in html
    assert 'href="args.hpp#engine-config"' in html
    assert "shared_ptr" in html
    assert 'href="main.cpp#createetcdhandler"' not in html
    assert "cppdoc-def" in html

    handler_html = render_codedoc_page(handler, "engineapps/engine/server/engine_etcd_handler.hpp", index)
    assert "Referenced by" in handler_html
    assert 'href="../main.cpp#createetcdhandler"' in handler_html


def test_legacy_cpp_signature_is_linked_and_example_code_is_not() -> None:
    config = _page("engine::Config", "engine-config", "struct Config")
    text = "\n".join(
        [
            '<a id="take"></a>',
            "## take",
            "",
            "```cpp",
            "void take(engine::Config)",
            "```",
            "",
            "```cpp",
            "engine::Config again;",
            "```",
            "",
            "Defined at [use.cpp:1](use.cpp?line=1).",
            "",
        ]
    )
    index = index_pages([("args.hpp", config), ("use.cpp", text)])
    html = render_codedoc_page(text, "use.cpp", index)
    assert html.count('class="cppdoc-def"') == 1
    assert 'href="args.hpp#engine-config"' in html
    assert "again" in html


def test_ambiguous_and_std_names_stay_plain() -> None:
    left = _page("engine::Config", "engine-config", "struct Config")
    right = _page("engine::Config", "engine-config-b", "struct Config")
    use = _page("run", "run", "void run(engine::Config, std::string)")
    index = index_pages(
        [
            ("a.hpp", left),
            ("b.hpp", right),
            ("c.cpp", use),
        ]
    )
    html = render_codedoc_page(use, "c.cpp", index)
    assert "cppdoc-def" not in html
    assert "string" in html


def test_kind_badge_in_heading_does_not_break_indexing() -> None:
    badge = '<span class="sym-kind" data-kind="struct" title="struct"></span>'
    config = _page(f"{badge}engine::Config", "engine-config", "struct Config")
    use = _page("take", "take", "void take(engine::Config)")
    index = index_pages([("args.hpp", config), ("use.cpp", use)])
    assert "engine::Config" in index.defs
    html = render_codedoc_page(use, "use.cpp", index)
    assert 'href="args.hpp#engine-config"' in html
    config_html = render_codedoc_page(config, "args.hpp", index)
    assert 'data-kind="struct"' in config_html
    assert "Referenced by" in config_html


def test_bare_constructor_name_links_to_the_class() -> None:
    cls = _page("engine::Widget", "engine-widget", "class Widget")
    ctor = _page("engine::Widget::Widget", "engine-widget-widget", "Widget()")
    index = index_pages([("widget.hpp", cls), ("widget.cpp", ctor)])
    html = render_codedoc_page(ctor, "widget.cpp", index)
    assert 'href="widget.hpp#engine-widget"' in html


def test_bare_name_links_when_one_symbol_owns_it() -> None:
    config = _page("engine::Config", "engine-config", "struct Config")
    use = _page("take", "take", "void take(Config)")
    index = index_pages([("args.hpp", config), ("use.cpp", use)])
    html = render_codedoc_page(use, "use.cpp", index)
    assert 'href="args.hpp#engine-config"' in html


def test_reference_list_is_capped() -> None:
    target = _page("engine::Config", "engine-config", "struct Config")
    pages = [("args.hpp", target)]
    for n in range(41):
        pages.append((f"use{n}.cpp", _page(f"use{n}", f"use-{n}", "void use(engine::Config)")))
    index = index_pages(pages)
    html = render_codedoc_page(target, "args.hpp", index)
    assert "and 1 more" in html
    assert html.count("use") > 0
