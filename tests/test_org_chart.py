import copy
import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "org_chart.py"
SPEC = importlib.util.spec_from_file_location("org_chart", SCRIPT)
chart = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = chart
SPEC.loader.exec_module(chart)


def base():
    return copy.deepcopy(chart.load())


def unit(data, uid):
    return next(row for row in data["units"] if row["id"] == uid)


def test_the_shipped_chart_is_valid():
    assert chart.validate(chart.load()) == []


def test_modules_one_two_three_are_ministry_level():
    data = chart.load()
    for uid in ("dept-module1", "dept-module2", "dept-module3"):
        assert unit(data, uid)["level"] == "部"


def test_every_division_belongs_to_a_department():
    data = chart.load()
    index = {row["id"]: row for row in data["units"]}
    divisions = [row for row in data["units"] if row["level"] == "司"]
    assert divisions
    for row in divisions:
        assert index[row["parent"]]["level"] == "部"


def test_a_division_cannot_sit_directly_under_control():
    data = base()
    unit(data, "div-resources")["parent"] = None

    problems = chart.validate(data)

    assert any("must belong to a 部" in problem for problem in problems)


def test_a_section_cannot_skip_its_division():
    data = base()
    unit(data, "sec-asr")["parent"] = "dept-module2"

    problems = chart.validate(data)

    assert any("处 must belong to a 司" in problem for problem in problems)


def test_names_must_carry_their_level_suffix():
    data = base()
    unit(data, "sec-asr")["name"] = "语音转写"

    problems = chart.validate(data)

    assert any("must end with 处" in problem for problem in problems)


def test_a_department_needs_at_least_one_division():
    data = base()
    data["units"] = [
        row for row in data["units"] if row.get("parent") != "dept-module3"
    ]
    data["units"].append(
        {"id": "div-orphan", "name": "空司", "level": "司", "parent": "dept-module1"}
    )

    problems = chart.validate(data)

    assert any("dept-module3: every 部 needs at least one 司" in problem for problem in problems)


def test_duplicate_ids_are_rejected():
    data = base()
    data["units"].append(
        {"id": "sec-asr", "name": "重复处", "level": "处", "parent": "div-subtitles"}
    )

    problems = chart.validate(data)

    assert any("unique" in problem for problem in problems)


def test_only_the_supervision_division_may_report_to_control():
    data = base()
    unit(data, "div-pdca")["reports_to"] = "总控"

    problems = chart.validate(data)

    assert problems == []

    data = base()
    unit(data, "sec-audit")["reports_to"] = "总控"

    problems = chart.validate(data)

    assert any("only a 司 may report" in problem for problem in problems)


def test_stats_count_every_level():
    report = chart.stats(chart.load())

    assert report["total"] == len(chart.load()["units"])
    assert set(report["by_level"]) == set(chart.LEVELS)
    assert report["by_level"]["部"] == 4
    assert report["by_level"]["司"] >= 12


def test_tree_renders_the_ladder():
    text = chart.render_tree(chart.load())

    assert text.splitlines()[0] == "总控"
    assert "模块1：情报与素材部 [部]" in text
    assert "ASR处 [处]" in text


def test_path_walks_from_department_to_unit(capsys):
    assert chart.main(["path", "--unit", "sec-asr"]) == 0

    out = capsys.readouterr().out.strip()
    assert out.startswith("总控")
    assert "模块2：视频处理部 [部]" in out
    assert "字幕制作司 [司]" in out
    assert out.endswith("ASR处 [处]")
