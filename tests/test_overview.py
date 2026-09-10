"""Tests for the LLM-free structural overview."""

import pytest

from server.overview import build_overview


@pytest.fixture
def project(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project.scripts]\ndemo = "pkg.cli:main"\n', encoding="utf-8"
    )
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "pkg" / "core.py").write_text(
        '"""The shared core."""\n\n\ndef helper():\n    return 1\n', encoding="utf-8"
    )
    (tmp_path / "pkg" / "cli.py").write_text(
        "from .core import helper\n\n\ndef main():\n    return helper()\n", encoding="utf-8"
    )
    (tmp_path / "pkg" / "web.py").write_text(
        "from pkg.core import helper\n\n\ndef serve():\n    return helper()\n", encoding="utf-8"
    )
    (tmp_path / "pkg" / "lonely.py").write_text("VALUE = 1\n", encoding="utf-8")
    return tmp_path


def test_counts_languages_and_totals(project):
    data = build_overview(project)
    langs = {row["language"]: row for row in data["languages"]}

    assert "Python" in langs
    assert langs["Python"]["files"] == 5
    assert data["totals"]["files"] > 0


def test_ranks_the_most_depended_on_module_first(project):
    """Both relative and absolute intra-project imports must count."""
    data = build_overview(project)
    top = data["core_modules"][0]

    assert top["path"] == "pkg/core.py"
    assert top["imported_by"] == 2
    assert top["summary"] == "The shared core."


def test_finds_entry_points_including_console_scripts(project):
    paths = [row["path"] for row in build_overview(project)["entry_points"]]
    assert "pkg/cli.py" in paths


def test_reading_route_starts_with_docs_then_config(project):
    route = build_overview(project)["reading_route"]
    paths = [step["path"] for step in route]

    assert paths[0] == "README.md"
    assert paths[1] == "pyproject.toml"
    assert "pkg/core.py" in paths          # the core lands in the route
    assert all(step["why"] for step in route)


def test_reading_route_never_repeats_a_file(project):
    paths = [step["path"] for step in build_overview(project)["reading_route"]]
    assert len(paths) == len(set(paths))


def test_isolated_files_are_flagged(project):
    data = build_overview(project)
    assert "pkg/lonely.py" in data["orphans"]
    assert "pkg/core.py" not in data["orphans"]


def test_third_party_imports_are_ignored(tmp_path):
    (tmp_path / "a.py").write_text("import os\nimport requests\n", encoding="utf-8")
    data = build_overview(tmp_path)
    assert data["core_modules"] == []      # nothing in-project was imported


def test_unparseable_python_does_not_break_the_scan(tmp_path):
    (tmp_path / "broken.py").write_text("def (((\n", encoding="utf-8")
    (tmp_path / "fine.py").write_text("def ok():\n    return 1\n", encoding="utf-8")

    data = build_overview(tmp_path)
    assert data["totals"]["files"] == 2
