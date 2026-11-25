import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
from pathlib import Path

import yaml

from dbt_pr_diff import github, manifest, render, summary, thresholds
from dbt_pr_diff.diff import ModelDiff, connect, diff_model

PROFILE_TEMPLATE = """{name}:
  target: pr_diff
  outputs:
    pr_diff:
      type: duckdb
      path: "{{{{ env_var('DBT_PR_DIFF_DB') }}}}"
      threads: 4
"""


def log(msg: str) -> None:
    print(f"dbt-pr-diff: {msg}", file=sys.stderr)


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def dbt_bin() -> str:
    local = Path(sys.executable).parent / "dbt"
    return str(local) if local.exists() else "dbt"


def dbt(
    args: list[str], project: Path, profiles: Path, target: Path, db: Path, logs: Path
) -> str:
    env = {**os.environ, "DBT_PR_DIFF_DB": str(db), "DBT_DUCKDB_PATH": str(db)}
    cmd = [
        dbt_bin(),
        *args,
        "--project-dir",
        str(project),
        "--profiles-dir",
        str(profiles),
        "--target-path",
        str(target),
        "--log-path",
        str(logs),
    ]
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        sys.stderr.write(result.stdout[-4000:] + result.stderr[-2000:])
        raise SystemExit(f"dbt-pr-diff: `dbt {' '.join(args)}` failed in {project}")
    return result.stdout


def write_profile(project: Path, out: Path) -> Path:
    name = yaml.safe_load((project / "dbt_project.yml").read_text())["profile"]
    profiles = out / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    (profiles / "profiles.yml").write_text(PROFILE_TEMPLATE.format(name=name))
    return profiles


def build(
    project: Path, db: Path, target: Path, out: Path, profiles: Path | None
) -> None:
    db.unlink(missing_ok=True)
    profiles = profiles or write_profile(project, out)
    steps = [["seed"], ["run"]]
    if (project / "packages.yml").exists() or (project / "dependencies.yml").exists():
        steps.insert(0, ["deps"])
    for step in steps:
        dbt(step, project, profiles, target, db, out / "logs")


def select(
    project: Path,
    selector: str,
    state: Path,
    target: Path,
    out: Path,
    db: Path,
    profiles: Path | None,
) -> list[str]:
    profiles = profiles or write_profile(project, out)
    stdout = dbt(
        [
            "--quiet",
            "ls",
            "--resource-type",
            "model",
            "--select",
            selector,
            "--state",
            str(state),
            "--output",
            "json",
            "--output-keys",
            "unique_id",
        ],
        project,
        profiles,
        target,
        db,
        out / "logs",
    )
    ids = []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            ids.append(json.loads(line)["unique_id"])
    return sorted(ids)


def head_name() -> str:
    if os.environ.get("GITHUB_HEAD_REF"):
        return os.environ["GITHUB_HEAD_REF"]
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    return "HEAD" if branch == "HEAD" else branch


def is_fork_pr() -> bool:
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path or not os.path.exists(path):
        return False
    event = json.loads(Path(path).read_text())
    head_repo = ((event.get("pull_request") or {}).get("head") or {}).get("repo")
    return bool(head_repo) and head_repo.get("full_name") != os.environ.get(
        "GITHUB_REPOSITORY"
    )


def post(markdown: str) -> None:
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    number = github.pr_number()
    if not (token and repo and number):
        log("not running on a pull request with GITHUB_TOKEN, skipping comment")
        return
    if is_fork_pr():
        log("pull request from a fork has a read-only token, see the step summary")
        return
    try:
        log(f"comment {github.upsert_comment(markdown, repo, number, token)}")
    except urllib.error.HTTPError as exc:
        log(
            f"could not comment ({exc.code}); does the job have `pull-requests: write`?"
        )


def compare(args: argparse.Namespace) -> int:
    rules = thresholds.parse(args.fail_on or "")
    root = Path(git("rev-parse", "--show-toplevel"))
    project = Path(args.project_dir).resolve()
    rel = project.relative_to(root)
    out = (root / args.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    profiles = Path(args.profiles_dir).resolve() if args.profiles_dir else None

    base_sha = git("rev-parse", "--short", args.base_ref)
    head_sha = git("rev-parse", "--short", "HEAD")
    if os.environ.get("GITHUB_HEAD_REF") and os.environ.get("GITHUB_EVENT_PATH"):
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        sha = ((event.get("pull_request") or {}).get("head") or {}).get("sha")
        head_sha = sha[:7] if sha else head_sha
    if args.base_db:
        base_db = Path(args.base_db).resolve()
        base_target = Path(args.base_state).resolve()
    else:
        worktree = out / "base-src"
        if worktree.exists():
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                cwd=root,
                check=False,
                capture_output=True,
            )
            shutil.rmtree(worktree, ignore_errors=True)
        git("worktree", "add", "--detach", str(worktree), args.base_ref, cwd=root)
        base_db, base_target = out / "base.duckdb", out / "base-target"
        log(f"building base {args.base_ref} ({base_sha})")
        try:
            build(worktree / rel, base_db, base_target, out, profiles)
        finally:
            git("worktree", "remove", "--force", str(worktree), cwd=root)

    head_db, head_target = out / "head.duckdb", out / "head-target"
    log(f"building head ({head_sha})")
    build(project, head_db, head_target, out, profiles)

    selected = select(
        project, args.select, base_target, head_target, out, head_db, profiles
    )
    head_manifest = manifest.load(head_target)
    base_manifest = manifest.load(base_target)
    removed = manifest.model_ids(base_manifest) - manifest.model_ids(head_manifest)

    con = connect(str(base_db), str(head_db))
    diffs: list[ModelDiff] = [
        diff_model(con, manifest.spec(head_manifest, uid)) for uid in selected
    ]
    diffs += [
        ModelDiff(name=base_manifest["nodes"][uid]["name"], status="removed", keys=[])
        for uid in sorted(removed)
    ]
    breaches = thresholds.evaluate(rules, diffs)

    ai = None
    if not args.no_ai and any(d.has_changes for d in diffs):
        ai = summary.summarize(render.to_json(diffs, breaches, samples=False))
    markdown = render.markdown(
        diffs,
        breaches,
        base_label=f"{args.base_ref.removeprefix('origin/')} ({base_sha})",
        head_label=f"{head_name()} ({head_sha})",
        ai_summary=ai,
    )
    (out / "pr-diff.md").write_text(markdown)
    (out / "pr-diff.json").write_text(render.to_json(diffs, breaches))
    print(markdown)

    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a") as f:
            f.write(markdown)
    if args.comment:
        post(markdown)
    if breaches:
        log(f"{len(breaches)} fail_on check(s) breached")
        return 1
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="dbt-pr-diff")
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("compare", help="build base and head, diff changed models")
    c.add_argument("--base-ref", default="main")
    c.add_argument("--project-dir", default=".")
    c.add_argument("--select", default="state:modified+")
    c.add_argument("--fail-on", default="")
    c.add_argument("--out-dir", default=".pr-diff")
    c.add_argument(
        "--profiles-dir",
        help="use your own profiles.yml instead of a generated DuckDB profile",
    )
    c.add_argument("--base-db", help="existing base DuckDB file, skips base build")
    c.add_argument(
        "--base-state",
        help="target dir with the base manifest.json, required with --base-db",
    )
    c.add_argument("--comment", action="store_true", help="upsert a PR comment")
    c.add_argument("--no-ai", action="store_true", help="skip the AI summary")
    args = parser.parse_args(argv)
    if args.base_db and not args.base_state:
        parser.error("--base-db needs --base-state")
    try:
        thresholds.parse(args.fail_on)
    except ValueError as exc:
        parser.error(str(exc))
    sys.exit(compare(args))


if __name__ == "__main__":
    main()
