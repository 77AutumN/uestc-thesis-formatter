"""tests/test_assemble_kwargs.py — _build_assemble_kwargs alignment guard.

Goal: prevent step3_5_assemble and _reassemble_main_tex_after_refs from drifting.
The helper centralizes the assemble_main_tex kwarg shape; this test asserts:
  1. Helper output keys == assemble_main_tex parameter names (catches a future
     param added to assemble_main_tex but not to the helper).
  2. Two calls with identical inputs produce equal dicts (the alignment we want
     in production: both call sites can swap to the helper and stay in lockstep).
  3. self.bib_mode and the constant print_mode are injected from the helper
     (callers don't override).
"""
import inspect
import os
import sys

THIS = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.normpath(os.path.join(THIS, ".."))
SCRIPTS_DIR = os.path.join(SKILL_DIR, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from run_v2 import ThesisFormatterV2  # noqa: E402
from template_adapter import assemble_main_tex  # noqa: E402


class _Stub:
    """Minimal stand-in providing the only attribute the helper reads."""
    def __init__(self, bib_mode="standard"):
        self.bib_mode = bib_mode


def _sample_inputs():
    return dict(
        meta={"title_cn": "测试", "degree_type": "master"},
        chapter_files=["chapter/ch01", "chapter/ch02"],
        abstract_zh_body="中文摘要正文。",
        abstract_zh_keywords="关键词1，关键词2",
        abstract_en_body="English abstract body.",
        abstract_en_keywords="kw1, kw2",
        has_conclusion=True,
        has_accomplishments=False,
        cite_map={"1": "key1", "2": "key2"},
    )


# ============================================================
# Contract: helper kwargs cover assemble_main_tex signature
# ============================================================

def test_helper_output_matches_assemble_signature():
    """If a new param is added to assemble_main_tex, the helper must list it
    too — otherwise callers using the helper would silently drop it."""
    stub = _Stub()
    kwargs = ThesisFormatterV2._build_assemble_kwargs(stub, **_sample_inputs())
    sig = inspect.signature(assemble_main_tex)
    expected = set(sig.parameters.keys())
    assert set(kwargs.keys()) == expected, (
        f"helper kwargs drifted from assemble_main_tex signature\n"
        f"  helper: {sorted(kwargs.keys())}\n"
        f"  assemble: {sorted(expected)}\n"
        f"  missing in helper: {expected - set(kwargs.keys())}\n"
        f"  extra in helper:   {set(kwargs.keys()) - expected}"
    )


# ============================================================
# Alignment: identical inputs → identical kwargs (the desync guard)
# ============================================================

def test_two_calls_identical_inputs_produce_equal_kwargs():
    """The desync guard: if both call sites pass the same semantic args,
    the kwargs that hit assemble_main_tex must be byte-equal."""
    stub = _Stub(bib_mode="standard")
    inputs = _sample_inputs()
    a = ThesisFormatterV2._build_assemble_kwargs(stub, **inputs)
    b = ThesisFormatterV2._build_assemble_kwargs(stub, **inputs)
    assert a == b


def test_different_cite_map_produces_different_kwargs():
    """Sanity: helper isn't accidentally collapsing distinct inputs."""
    stub = _Stub()
    inputs = _sample_inputs()
    a = ThesisFormatterV2._build_assemble_kwargs(stub, **inputs)
    inputs["cite_map"] = {"1": "differentkey"}
    b = ThesisFormatterV2._build_assemble_kwargs(stub, **inputs)
    assert a != b
    assert a["cite_map"] != b["cite_map"]
    # other keys still equal
    for k in a:
        if k != "cite_map":
            assert a[k] == b[k]


# ============================================================
# Constants the helper owns (not caller-supplied)
# ============================================================

def test_helper_injects_bib_mode_from_self():
    """bib_mode comes from self.bib_mode, not caller."""
    inputs = _sample_inputs()
    stub_a = _Stub(bib_mode="standard")
    stub_b = _Stub(bib_mode="categorized")
    ka = ThesisFormatterV2._build_assemble_kwargs(stub_a, **inputs)
    kb = ThesisFormatterV2._build_assemble_kwargs(stub_b, **inputs)
    assert ka["bib_mode"] == "standard"
    assert kb["bib_mode"] == "categorized"


def test_helper_hardcodes_print_mode_nonprint():
    """print_mode is a constant — both call sites used 'nonprint' verbatim."""
    stub = _Stub()
    kwargs = ThesisFormatterV2._build_assemble_kwargs(stub, **_sample_inputs())
    assert kwargs["print_mode"] == "nonprint"


# ============================================================
# No side effects (helper purity)
# ============================================================

def test_helper_does_not_mutate_input_dicts():
    stub = _Stub()
    inputs = _sample_inputs()
    meta_before = dict(inputs["meta"])
    cite_map_before = dict(inputs["cite_map"])
    ThesisFormatterV2._build_assemble_kwargs(stub, **inputs)
    assert inputs["meta"] == meta_before
    assert inputs["cite_map"] == cite_map_before


def test_helper_handles_none_cite_map():
    """cite_map=None is the empty-references fallback path — must not crash."""
    stub = _Stub()
    inputs = _sample_inputs()
    inputs["cite_map"] = None
    kwargs = ThesisFormatterV2._build_assemble_kwargs(stub, **inputs)
    assert kwargs["cite_map"] is None
