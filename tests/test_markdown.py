from reportlab.platypus import ListFlowable, Paragraph, Table

from ytexplain.render.markdown import MarkdownRenderer, inline
from ytexplain.render.pdf import build_styles


def make_renderer() -> MarkdownRenderer:
    return MarkdownRenderer(build_styles(), 400.0)


def test_inline_escapes_before_markup():
    assert inline("5 < 6 & 7 > 2") == "5 &lt; 6 &amp; 7 &gt; 2"


def test_inline_bold_italic_and_link():
    assert inline("**bold** and *thin*") == "<b>bold</b> and <i>thin</i>"
    assert '<link href="https://x.dev"' in inline("[docs](https://x.dev)")


def test_code_span_is_not_reinterpreted_as_markup():
    # Asterisks and angle brackets inside code must survive verbatim.
    rendered = inline("use `a<b> *not* bold`")
    assert "a&lt;b&gt; *not* bold" in rendered
    assert "<b>" not in rendered


def test_headings_respect_min_level():
    renderer = make_renderer()
    assert renderer.render("## Sub")[0].style.name == "H2"
    assert renderer.render("## Sub", min_heading=3)[0].style.name == "H3"
    assert renderer.render("# Top", min_heading=3)[0].style.name == "H3"


def count_lists(flowable) -> int:
    """ReportLab wraps list items in several container types, so walk generically."""
    total = 1 if isinstance(flowable, ListFlowable) else 0
    for attribute in ("_content", "_flowables", "_flowable"):
        child = flowable.__dict__.get(attribute)
        if child is None:
            continue
        children = child if isinstance(child, (list, tuple)) else [child]
        total += sum(count_lists(item) for item in children)
    return total


def test_nested_lists_nest():
    flat = make_renderer().render("- one\n- two")
    nested = make_renderer().render("- one\n  - inner\n- two")
    assert isinstance(nested[0], ListFlowable)
    assert count_lists(nested[0]) == count_lists(flat[0]) + 1


def test_ordered_list_is_numbered():
    flows = make_renderer().render("1. first\n2. second")
    assert flows[0]._bulletType == "1"


def test_table_with_header_becomes_table_flowable():
    flows = make_renderer().render("| a | b |\n| --- | --- |\n| 1 | 2 |")
    tables = [f for f in flows if isinstance(f, Table)]
    assert len(tables) == 1
    assert len(tables[0]._cellvalues) == 2


def test_code_fence_is_preserved_verbatim():
    flows = make_renderer().render("```python\nif x < 1:\n    pass\n```")
    frame = next(f for f in flows if isinstance(f, Table))
    code = frame._cellvalues[0][0]
    assert "if x &lt; 1:" in code.text


def test_paragraph_joins_soft_wrapped_lines():
    flows = make_renderer().render("one line\nsame paragraph\n\nnew one")
    paragraphs = [f for f in flows if isinstance(f, Paragraph)]
    assert paragraphs[0].text == "one line same paragraph"
    assert len(paragraphs) == 2
