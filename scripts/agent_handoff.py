"""GitHub-only, fail-closed PR handoff after existing CI (no LLM or product access).

This is a metadata coordinator, NOT an agent executor or independent AI reviewer.
The workflow runs this file from the default branch, never PR code.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

MARKER = "<!-- oge-agent-handoff:v1 -->"
BOT_LOGIN = "github-actions[bot]"
REQUIRED_JOBS = frozenset({"quality", "oge15-linux-render"})
MAX_REPAIR_CYCLES = 3
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class Decision:
    pr_number: int
    head_sha: str
    ci_run_id: int | None
    ci_conclusion: str
    review: str
    repair_cycles: int
    status: str

    def as_dict(self) -> dict[str, Any]:
        return {"schema_version": 1, "pr_number": self.pr_number,
                "head_sha": self.head_sha, "ci_run_id": self.ci_run_id,
                "ci_conclusion": self.ci_conclusion, "required_ci_jobs": sorted(REQUIRED_JOBS),
                "review": self.review, "repair_cycles": self.repair_cycles,
                "max_repair_cycles": MAX_REPAIR_CYCLES, "status": self.status,
                "executor_connected": False, "automated_review_connected": False,
                "automated_fix_connected": False, "production_release_allowed": False}


def next_repair_cycle(current: int) -> int:
    """Entry point for a future, explicitly authorized executor handoff."""
    if (not isinstance(current, int) or isinstance(current, bool)
            or not 0 <= current < MAX_REPAIR_CYCLES):
        raise ValueError("repair-cycle limit reached or invalid counter")
    return current + 1


def previous_cycles(previous: dict[str, Any] | None, pr_number: int) -> int:
    if previous is None:
        return 0
    if previous.get("schema_version") != 1 or previous.get("pr_number") != pr_number:
        raise ValueError("invalid or mismatched durable state")
    value = previous.get("repair_cycles")
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= MAX_REPAIR_CYCLES:
        raise ValueError("invalid durable repair counter; refusing to overwrite")
    return value


def current_review(reviews: list[dict[str, Any]], author: str, head_sha: str) -> str:
    """Only an independent, current-head APPROVED review passes; comments do not."""
    latest: dict[str, dict[str, Any]] = {}
    for item in sorted(reviews, key=lambda r: (str(r.get("submitted_at") or ""),
                                               int(r.get("id") or 0))):
        login = str((item.get("user") or {}).get("login") or "")
        if not login or login.lower() == author.lower():
            continue
        state = str(item.get("state") or "").upper()
        if state in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED", "COMMENTED"}:
            latest[login.lower()] = item
    if any(str(r.get("state")).upper() == "CHANGES_REQUESTED" for r in latest.values()):
        return "changes_requested"
    if any(str(r.get("state")).upper() == "APPROVED" and r.get("commit_id") == head_sha
           for r in latest.values()):
        return "approved_current_head"
    return "awaiting_independent_approval"


def evaluate(pr: dict[str, Any], run: dict[str, Any] | None,
             jobs: list[dict[str, Any]], reviews: list[dict[str, Any]],
             previous: dict[str, Any] | None = None) -> Decision:
    number = pr["number"]
    sha = pr["head"]["sha"]
    cycles = previous_cycles(previous, number)
    author = str(pr["user"]["login"])
    labels = {label["name"] for label in pr.get("labels", [])}
    review = current_review(reviews, author, sha)
    ci_run_id = run["id"] if run else None
    ci_conclusion = "missing"
    ci_status = "awaiting_ci"

    if run is not None:
        if run.get("head_sha") != sha or run.get("name") != "CI" or \
                run.get("event") != "pull_request" or not any(
                    assoc.get("number") == number for assoc in run.get("pull_requests", [])
                ):
            raise ValueError("CI run is stale or unrelated to the current PR/head")
        ci_conclusion = str(run.get("conclusion") or "pending")
        if run.get("status") == "completed":
            jobs_by_name = {j["name"]: j for j in jobs}
            good_jobs = REQUIRED_JOBS.issubset(jobs_by_name) and all(
                jobs_by_name[n].get("status") == "completed"
                and jobs_by_name[n].get("conclusion") == "success"
                for n in REQUIRED_JOBS
            )
            ci_status = "ci_passed" if ci_conclusion == "success" and good_jobs else "blocked_ci"

    if pr.get("state") != "open":
        status = "closed"
    elif "agent:blocked" in labels:
        status = "blocked_manual"
    elif pr.get("draft"):
        status = "blocked_draft"
    elif ci_status != "ci_passed":
        status = ci_status
    elif review == "changes_requested":
        status = "blocked_review"
    elif review != "approved_current_head":
        status = "awaiting_independent_review"
    else:
        status = "ready_for_human_acceptance"

    if cycles >= MAX_REPAIR_CYCLES and status in {"blocked_ci", "blocked_review"}:
        status = "blocked_max_repairs"
    return Decision(number, sha, ci_run_id, ci_conclusion, review, cycles, status)


def render_comment(decision: Decision) -> str:
    data = json.dumps(decision.as_dict(), ensure_ascii=False, indent=2, sort_keys=True)
    guidance = {
        "awaiting_ci": "Ожидается полный CI для текущего commit SHA.",
        "blocked_ci": "CI не прошёл или обязательные jobs отсутствуют. Нужны исправления.",
        "awaiting_independent_review": (
            "CI пройден. Нужен независимый APPROVED review текущего commit."
        ),
        "blocked_review": "Независимый reviewer запросил изменения.",
        "ready_for_human_acceptance": (
            "CI и независимый review пройдены. Только человек решает о merge/release."
        ),
        "blocked_manual": "Владелец поставил метку agent:blocked.",
        "blocked_draft": "PR пока в статусе Draft.",
        "blocked_max_repairs": "Лимит трёх исправлений исчерпан; нужна эскалация человеку.",
        "closed": "PR закрыт; автоматических действий нет.",
    }
    return (f"{MARKER}\n### OGE Agent Handoff · {decision.status}\n\n"
            f"{guidance[decision.status]}\n\n"
            "Автоматически: оценка CI, review и запись состояния. "
            "**Не подключено:** исполнитель, AI-review, исправления и merge.\n\n"
            f"```json\n{data}\n```\n")


def parse_state(body: str) -> dict[str, Any]:
    if not body.startswith(MARKER):
        raise ValueError("missing state marker")
    match = re.search(r"```json\s*(\{.*?\})\s*```", body, re.DOTALL)
    if not match:
        raise ValueError("malformed state comment")
    obj = json.loads(match.group(1))
    if not isinstance(obj, dict):
        raise ValueError("state is not an object")
    return obj


class GitHub:
    def __init__(self, repository: str, token: str):
        if not REPOSITORY_PATTERN.fullmatch(repository):
            raise ValueError("invalid repository name")
        if not token:
            raise ValueError("GITHUB_TOKEN is required for live metadata reads")
        self.base = f"https://api.github.com/repos/{repository}"
        self.token = token

    def request(self, path: str, method: str = "GET", payload: dict[str, Any] | None = None) -> Any:
        if not path.startswith("/") or "//" in path or ".." in path:
            raise ValueError("invalid GitHub API path")
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(self.base + path, data=data, method=method,
                          headers={"Authorization": f"Bearer {self.token}",
                                   "Accept": "application/vnd.github+json",
                                   "X-GitHub-Api-Version": "2022-11-28",
                                   "Content-Type": "application/json",
                                   "User-Agent": "oge-agent-handoff-v1"})
        try:
            with urlopen(request, timeout=25) as response:
                return json.load(response)
        except HTTPError as exc:
            # Never print response bodies: they could include sensitive data.
            raise RuntimeError(f"GitHub API {method} {path}: HTTP {exc.code}") from exc

    def paginated(self, path: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for page in range(1, 11):
            sep = "&" if "?" in path else "?"
            batch = self.request(f"{path}{sep}per_page=100&page={page}")
            if not isinstance(batch, list):
                raise ValueError("expected list from GitHub API")
            items.extend(batch)
            if len(batch) < 100:
                return items
        raise ValueError("GitHub pagination cap reached; refusing partial review/state")


def find_latest_ci(api: GitHub, number: int, sha: str) -> dict[str, Any] | None:
    runs = api.request(f"/actions/runs?head_sha={quote(sha)}&event=pull_request&per_page=100")
    matching = [run for run in runs.get("workflow_runs", [])
                if run.get("name") == "CI" and run.get("head_sha") == sha
                and any(p.get("number") == number for p in run.get("pull_requests", []))]
    return max(matching, key=lambda r: (r.get("created_at") or "", r["id"]), default=None)


def find_bot_state(comments: list[dict[str, Any]]) -> tuple[int | None, dict[str, Any] | None]:
    matches = [c for c in comments if (c.get("body") or "").startswith(MARKER)
               and (c.get("user") or {}).get("login") == BOT_LOGIN]
    if not matches:
        return None, None
    if len(matches) > 1:
        raise ValueError("multiple bot state comments; manual cleanup required")
    found = matches[0]
    return found["id"], parse_state(found["body"])


def summary(message: str) -> None:
    print(message)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as fh:
            fh.write(message + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", type=int)
    parser.add_argument("--run-id", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fixture", type=Path, help="offline read-only acceptance simulation")
    args = parser.parse_args()

    if args.fixture:
        fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
        decision = evaluate(fixture["pr"], fixture.get("ci_run"), fixture.get("jobs", []),
                            fixture.get("reviews", []), fixture.get("previous"))
        summary(render_comment(decision))
        return 0

    repository = os.environ.get("GITHUB_REPOSITORY", "")
    api = GitHub(repository, os.environ.get("GITHUB_TOKEN", ""))
    if not args.pr or args.pr < 1:
        raise ValueError("valid --pr required")
    pr = api.request(f"/pulls/{args.pr}")
    if pr.get("state") != "open":
        summary("PR is closed; no action.")
        return 0
    sha = pr["head"]["sha"]
    latest = find_latest_ci(api, args.pr, sha)
    if args.run_id is not None and (latest is None or latest.get("id") != args.run_id):
        summary("Ignoring stale/overlapped CI completion; newest CI run owns state.")
        return 0
    run = latest
    jobs: list[dict[str, Any]] = []
    if run is not None:
        job_response = api.request(f"/actions/runs/{run['id']}/jobs?per_page=100")
        if job_response.get("total_count", 0) > 100:
            raise ValueError("too many CI jobs; refusing incomplete gate")
        jobs = job_response["jobs"]
    reviews = api.paginated(f"/pulls/{args.pr}/reviews")
    comments = api.paginated(f"/issues/{args.pr}/comments")
    comment_id, prev_state = find_bot_state(comments)
    decision = evaluate(pr, run, jobs, reviews, prev_state)
    body = render_comment(decision)
    summary(body)
    if args.dry_run:
        summary("Dry-run: no GitHub changes.")
    elif comment_id is None:
        api.request(f"/issues/{args.pr}/comments", "POST", {"body": body})
        summary("Created durable PR state comment.")
    else:
        old_body = next(c["body"] for c in comments if c["id"] == comment_id)
        if old_body != body:
            api.request(f"/issues/comments/{comment_id}", "PATCH", {"body": body})
            summary("Updated durable PR state comment.")
        else:
            summary("Idempotent replay: state unchanged, no write.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, OSError) as error:
        print(f"Agent handoff blocked: {error}", file=sys.stderr)
        sys.exit(1)
