import copy
import importlib.util
import json
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "engine_registry.py"
SPEC = importlib.util.spec_from_file_location("engine_registry", SCRIPT)
registry = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = registry
SPEC.loader.exec_module(registry)


def load(office):
    return registry.load(office)


def test_every_office_record_is_valid():
    problems = registry.check_all()

    assert problems == []
    assert len(registry.OFFICES) == 4


def test_rubric_weights_add_up_to_one_hundred():
    for office in registry.OFFICES:
        record = load(office)
        assert sum(registry.weights(record).values()) == 100, office


def test_totals_are_recomputed_not_read_from_the_file():
    record = copy.deepcopy(load("asr"))
    candidate = next(item for item in record["candidates"] if item["id"] == "assemblyai-universal-3-5-pro")
    candidate["total"] = 1000

    assert registry.total(record, candidate) == 91


def test_ranking_is_sorted_by_total_then_accuracy():
    rows = registry.rank(load("translation"))
    totals = [row["total"] for row in rows]

    assert totals == sorted(totals, reverse=True)
    assert rows[0]["id"] == "assemblyai-gateway-gemini-2-5-flash-lite"


def test_every_selected_primary_passes_the_threshold():
    for office in registry.OFFICES:
        record = load(office)
        primary = record["selection"]["primary"]
        chosen = next(row for row in registry.rank(record) if row["id"] == primary)
        assert chosen["passes"], f"{office} primary below the pass mark"


def test_validation_rejects_a_rubric_that_does_not_sum_to_one_hundred():
    record = copy.deepcopy(load("asr"))
    record["rubric"]["dimensions"][0]["weight"] = 29

    assert any("add up to 100" in item for item in registry.validate(record))


def test_validation_rejects_a_score_above_its_weight():
    record = copy.deepcopy(load("voice-clone"))
    record["candidates"][0]["scores"]["similarity"] = 31

    assert any("outside 0..30" in item for item in registry.validate(record))


def test_validation_requires_an_https_citation_per_candidate():
    record = copy.deepcopy(load("voice-burn"))
    record["candidates"][0]["evidence"] = [{"url": "http://example.test", "observed_at": "2026-10-27"}]

    assert any("evidence url must be https" in item for item in registry.validate(record))


def test_validation_rejects_an_unknown_selection():
    record = copy.deepcopy(load("translation"))
    record["selection"]["primary"] = "not-a-real-engine"

    assert any("selection.primary is not a candidate" in item for item in registry.validate(record))


def test_markdown_lists_rank_score_and_selection():
    record = load("asr")
    page = registry.render(record)

    assert "## 排名" in page
    assert "assemblyai-universal-3-5-pro" in page
    assert "## 逐维度得分" in page
    assert "## 选型" in page
    assert "<https://" in page


def test_json_command_lists_ranked_rows(capsys):
    code = registry.main(["json", "--office", "voice-clone"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload[0]["rank"] == 1
    assert payload[0]["id"] == "cosyvoice-3-open"
    assert all(row["passes"] for row in payload)


def test_check_reports_a_missing_record(tmp_path):
    problems = registry.check_all(tmp_path)

    assert problems
    assert all("not found" in item for item in problems)
