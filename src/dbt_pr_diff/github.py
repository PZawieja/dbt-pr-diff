import json
import os
import urllib.request

from dbt_pr_diff.render import MARKER

API = os.environ.get("GITHUB_API_URL", "https://api.github.com")


def _request(method: str, url: str, token: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read() or b"null")


def pr_number() -> int | None:
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path or not os.path.exists(path):
        return None
    with open(path) as f:
        event = json.load(f)
    return (event.get("pull_request") or {}).get("number")


def upsert_comment(body: str, repo: str, number: int, token: str) -> str:
    base = f"{API}/repos/{repo}/issues"
    page = 1
    while True:
        comments = _request(
            "GET", f"{base}/{number}/comments?per_page=100&page={page}", token
        )
        for comment in comments:
            if MARKER in (comment.get("body") or ""):
                _request(
                    "PATCH", f"{base}/comments/{comment['id']}", token, {"body": body}
                )
                return "updated"
        if len(comments) < 100:
            break
        page += 1
    _request("POST", f"{base}/{number}/comments", token, {"body": body})
    return "created"
