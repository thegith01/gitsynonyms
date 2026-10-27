import copy
import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "publishing_registry.py"
SPEC = importlib.util.spec_from_file_location("publishing_registry", SCRIPT)
publishing = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = publishing
SPEC.loader.exec_module(publishing)


def base():
    return copy.deepcopy(publishing.load())


def test_the_shipped_registry_is_valid():
    assert publishing.validate(publishing.load()) == []


def test_coverage_is_over_one_hundred_platforms():
    report = publishing.stats(publishing.load())

    assert report["total"] >= 100
    assert all(count >= 20 for count in report["by_kind"].values())


def test_a_duplicate_id_is_rejected():
    data = base()
    data["platforms"].append(copy.deepcopy(data["platforms"][0]))

    problems = publishing.validate(data)

    assert any("duplicate id" in problem for problem in problems)


def test_platform_urls_must_use_https():
    data = base()
    data["platforms"][0]["url"] = "http://example.com"

    problems = publishing.validate(data)

    assert any("url must be https" in problem for problem in problems)


def test_a_kind_must_reach_its_minimum():
    data = base()
    data["platforms"] = [
        row for row in data["platforms"] if row["kind"] != "paper"
    ] + [row for row in data["platforms"] if row["kind"] == "paper"][:5]

    problems = publishing.validate(data)

    assert any("kind paper has 5" in problem for problem in problems)


def test_an_unknown_kind_is_rejected():
    data = base()
    data["platforms"][0]["kind"] = "podcast"

    problems = publishing.validate(data)

    assert any("kind must be one of" in problem for problem in problems)


def test_every_platform_needs_a_name():
    data = base()
    data["platforms"][0]["name"] = "  "

    problems = publishing.validate(data)

    assert any("name is required" in problem for problem in problems)


def test_stats_summarize_kind_region_and_status():
    report = publishing.stats(publishing.load())

    assert set(report["by_kind"]) <= publishing.KINDS
    assert report["by_status"]["registered"] >= 1
    assert report["total"] == sum(report["by_kind"].values())
