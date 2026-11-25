import json
from types import SimpleNamespace

from dbt_pr_diff import github, summary
from dbt_pr_diff.render import MARKER


def test_upsert_updates_existing_comment(monkeypatch):
    calls = []

    def fake(method, url, token, body=None):
        calls.append((method, url))
        if method == "GET":
            return [{"id": 1, "body": "hi"}, {"id": 7, "body": f"{MARKER}\nold"}]
        return {}

    monkeypatch.setattr(github, "_request", fake)
    assert github.upsert_comment("new", "o/r", 3, "t") == "updated"
    assert calls[-1] == ("PATCH", f"{github.API}/repos/o/r/issues/comments/7")


def test_upsert_creates_when_missing(monkeypatch):
    calls = []

    def fake(method, url, token, body=None):
        calls.append(method)
        return [] if method == "GET" else {}

    monkeypatch.setattr(github, "_request", fake)
    assert github.upsert_comment("new", "o/r", 3, "t") == "created"
    assert calls == ["GET", "POST"]


def test_pr_number_from_event(tmp_path, monkeypatch):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"number": 12}}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    assert github.pr_number() == 12


def test_summary_skipped_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert summary.summarize("{}") is None


def test_summary_uses_haiku_with_numbers_only(monkeypatch):
    import anthropic

    seen = {}

    class FakeMessages:
        def create(self, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text="- rows up 66%")],
            )

    class FakeClient:
        messages = FakeMessages()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    assert summary.summarize('{"models": []}') == "- rows up 66%"
    assert seen["model"] == "claude-haiku-5-5"
    assert seen["messages"][0]["content"] == '{"models": []}'
    assert "temperature" not in seen
