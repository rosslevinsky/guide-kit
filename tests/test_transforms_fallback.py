"""The single-entry `post_pandoc_html` fallback in _apply_transforms is load-bearing.

accounting-guide/transforms.py defines only `post_pandoc_html` (no per-output
split), and build.py must still honour it for BOTH the pdf and web targets
(build.py:230 fallback path, plan.md:194/:283). Pinned here, in the kit, before
the convergence lane that depends on it. No render needed — _apply_transforms is
exercised directly with a stubbed hook module.
"""
import build


class _SingleEntry:
    @staticmethod
    def post_pandoc_html(html: str) -> str:
        return html + "<!--SINGLE-->"


class _PerOutput:
    @staticmethod
    def post_pandoc_html(html: str) -> str:
        return html + "<!--SINGLE-->"

    @staticmethod
    def post_pandoc_html_for_pdf(html: str) -> str:
        return html + "<!--PDF-->"


def test_single_entry_used_for_both_targets(monkeypatch):
    monkeypatch.setattr(build, "_load_transforms", lambda: _SingleEntry)
    assert build._apply_transforms("BODY", "pdf") == "BODY<!--SINGLE-->"
    assert build._apply_transforms("BODY", "web") == "BODY<!--SINGLE-->"


def test_per_output_takes_precedence_but_falls_back_per_target(monkeypatch):
    monkeypatch.setattr(build, "_load_transforms", lambda: _PerOutput)
    # pdf has a per-output entry point; web does not, so web falls back to single.
    assert build._apply_transforms("B", "pdf") == "B<!--PDF-->"
    assert build._apply_transforms("B", "web") == "B<!--SINGLE-->"


def test_no_hook_passes_through(monkeypatch):
    monkeypatch.setattr(build, "_load_transforms", lambda: None)
    assert build._apply_transforms("B", "pdf") == "B"
    assert build._apply_transforms("B", "web") == "B"
