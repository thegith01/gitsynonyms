from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "download_source_video.py"
SPEC = importlib.util.spec_from_file_location("download_source_video", SCRIPT)
assert SPEC.loader is not None
download = importlib.util.module_from_spec(SPEC)
sys.modules["download_source_video"] = download
SPEC.loader.exec_module(download)


def test_progress_size_counts_partial_and_finished_files(tmp_path):
    target = tmp_path / "abc.source.%(ext)s"
    (tmp_path / "abc.source.mp4.part").write_bytes(b"x" * 10)
    (tmp_path / "abc.source.mp4").write_bytes(b"y" * 5)
    (tmp_path / "other.source.mp4").write_bytes(b"z" * 99)

    assert download._progress_size(target) == 15


def test_smoke_test_simulates_through_the_proxy(monkeypatch):
    seen = {}

    class Result:
        returncode = 0
        stdout = "abc\n"
        stderr = ""

    def fake_run(command, capture_output, text, timeout):
        seen["command"] = command
        seen["timeout"] = timeout
        return Result()

    monkeypatch.setattr(download.subprocess, "run", fake_run)

    ok, note = download.smoke_test("https://www.youtube.com/watch?v=abc", "1.2.3.4:80", 45, None)

    assert ok
    assert "screen ok" in note
    assert "--simulate" in seen["command"]
    assert seen["timeout"] == 45
    assert seen["command"][seen["command"].index("--proxy") + 1] == "1.2.3.4:80"


def _run_proxy_phase(monkeypatch, tmp_path, screen_results, download_results):
    calls: list[tuple[str, str, str]] = []
    proxies = list(screen_results)

    monkeypatch.setattr(download, "candidate_proxies", lambda limit: proxies)
    monkeypatch.setattr(
        download, "probe", lambda candidates: [(proxy, 0.1 * (index + 1))
                                               for index, proxy in enumerate(candidates)]
    )
    monkeypatch.setattr(
        download, "smoke_test",
        lambda url, proxy, timeout, cookies: screen_results[proxy],
    )

    def fake_try(url, target, fmt, proxy, timeout, cookies, client="default"):
        if proxy is None:
            return False, "direct: timeout after 900s", 0
        calls.append((proxy, fmt, client))
        return download_results.get((proxy, fmt, client),
                                    (False, f"{proxy}: timeout after 900s", 0))

    monkeypatch.setattr(download, "try_download", fake_try)
    monkeypatch.setattr(
        sys, "argv",
        ["download_source_video.py", "--video-id", "abc", "--output-dir", str(tmp_path)],
    )

    return download.main(), calls


def test_unreachable_proxy_costs_one_timeout_not_twelve(tmp_path, monkeypatch):
    code, calls = _run_proxy_phase(
        monkeypatch, tmp_path,
        screen_results={"1.1.1.1:80": (True, "1.1.1.1:80: screen ok"),
                        "2.2.2.2:80": (True, "2.2.2.2:80: screen ok")},
        download_results={},  # every attempt times out before writing a byte
    )

    assert code == 1
    # Each proxy is abandoned after its first zero-byte timeout instead of
    # being retried with all four clients across all three formats.
    assert [call[0] for call in calls] == ["1.1.1.1:80", "2.2.2.2:80"]


def test_proxy_that_fails_screening_is_never_downloaded(tmp_path, monkeypatch):
    code, calls = _run_proxy_phase(
        monkeypatch, tmp_path,
        screen_results={"1.1.1.1:80": (False, "1.1.1.1:80: screen 403")},
        download_results={},
    )

    assert code == 1
    assert calls == []


def test_first_screened_proxy_that_moves_bytes_wins(tmp_path, monkeypatch):
    good = ("1.1.1.1:80", "bv*[height>=1080]+ba/b[height>=1080]", "default")
    created = tmp_path / "abc.source.mp4"

    def fake_try(url, target, fmt, proxy, timeout, cookies, client="default"):
        if proxy is None:
            return False, "direct: timeout after 900s", 0
        created.write_bytes(b"x" * 32)
        return True, f"{proxy} [{client}]: ok in 12s", 32

    monkeypatch.setattr(download, "candidate_proxies", lambda limit: ["9.9.9.9:80", "1.1.1.1:80"])
    monkeypatch.setattr(download, "probe", lambda candidates: [("9.9.9.9:80", 0.1), ("1.1.1.1:80", 0.2)])
    monkeypatch.setattr(
        download, "smoke_test",
        lambda url, proxy, timeout, cookies: (
            (False, f"{proxy}: screen 502") if proxy == "9.9.9.9:80" else (True, f"{proxy}: screen ok")
        ),
    )
    monkeypatch.setattr(download, "try_download", fake_try)
    monkeypatch.setattr(
        sys, "argv",
        ["download_source_video.py", "--video-id", "abc", "--output-dir", str(tmp_path)],
    )

    assert download.main() == 0
    assert created.exists()


def test_main_reports_success_only_with_a_produced_file(tmp_path, monkeypatch):
    good = ("1.1.1.1:80", "bv*[height>=1080]+ba/b[height>=1080]", "default")
    created = tmp_path / "abc.source.mp4"

    def fake_try(url, target, fmt, proxy, timeout, cookies, client="default"):
        if proxy is None:
            return False, "direct: timeout after 900s", 0
        created.write_bytes(b"x" * 32)
        return True, "1.1.1.1:80 [default]: ok in 12s", 32

    monkeypatch.setattr(download, "candidate_proxies", lambda limit: ["1.1.1.1:80"])
    monkeypatch.setattr(download, "probe", lambda candidates: [("1.1.1.1:80", 0.1)])
    monkeypatch.setattr(download, "smoke_test", lambda url, proxy, timeout, cookies: (True, "ok"))
    monkeypatch.setattr(download, "try_download", fake_try)
    monkeypatch.setattr(
        sys, "argv",
        ["download_source_video.py", "--video-id", "abc", "--output-dir", str(tmp_path)],
    )

    assert download.main() == 0
