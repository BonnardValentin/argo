from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import httpx

from argos.models import RawArtifact, Source

GITHUB_API = "https://api.github.com"


class GitHubIngestor:
    """Deterministic GitHub fetcher. No LLM, no transformation — raw in, raw out."""

    def __init__(self, token: str, *, timeout: float = 30.0) -> None:
        self._client = httpx.Client(
            base_url=GITHUB_API,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GitHubIngestor":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def iter_pulls(
        self,
        owner: str,
        repo: str,
        *,
        state: str = "closed",
        since: datetime | None = None,
        max_items: int | None = None,
    ) -> Iterator[RawArtifact]:
        """Yield merged/closed pull requests as RawArtifacts.

        We only keep merged PRs — unmerged ones rarely carry a decision worth
        extracting. Comments are fetched per PR so the extractor sees the full
        discussion, not just the description.
        """
        count = 0
        for pr in self._paginate(
            f"/repos/{owner}/{repo}/pulls",
            params={"state": state, "sort": "updated", "direction": "desc", "per_page": 50},
        ):
            if state == "closed" and not pr.get("merged_at"):
                continue
            updated_at = _parse_dt(pr.get("updated_at"))
            if since and updated_at and updated_at < since:
                break  # list is sorted desc by updated_at

            comments = self._fetch_pr_comments(owner, repo, pr["number"])
            yield RawArtifact(
                source=Source(
                    kind="github_pr",
                    url=pr["html_url"],
                    ref=f"{owner}/{repo}#{pr['number']}",
                    fetched_at=datetime.now(timezone.utc),
                ),
                title=pr.get("title", ""),
                body=pr.get("body") or "",
                author=(pr.get("user") or {}).get("login"),
                created_at=_parse_dt(pr.get("created_at")),
                extras={
                    "merged_at": pr.get("merged_at"),
                    "labels": [l["name"] for l in pr.get("labels", [])],
                    "additions": pr.get("additions"),
                    "deletions": pr.get("deletions"),
                    "changed_files": pr.get("changed_files"),
                    "comments": comments,
                },
            )
            count += 1
            if max_items and count >= max_items:
                return

    def iter_issues(
        self,
        owner: str,
        repo: str,
        *,
        state: str = "closed",
        since: datetime | None = None,
        max_items: int | None = None,
    ) -> Iterator[RawArtifact]:
        """Yield issues (excluding PRs, which the issues endpoint also returns)."""
        count = 0
        params: dict[str, str | int] = {
            "state": state,
            "sort": "updated",
            "direction": "desc",
            "per_page": 50,
        }
        if since:
            params["since"] = since.astimezone(timezone.utc).isoformat()

        for issue in self._paginate(f"/repos/{owner}/{repo}/issues", params=params):
            if "pull_request" in issue:
                continue  # issues endpoint conflates PRs; skip them
            comments = self._fetch_issue_comments(owner, repo, issue["number"])
            yield RawArtifact(
                source=Source(
                    kind="github_issue",
                    url=issue["html_url"],
                    ref=f"{owner}/{repo}#{issue['number']}",
                    fetched_at=datetime.now(timezone.utc),
                ),
                title=issue.get("title", ""),
                body=issue.get("body") or "",
                author=(issue.get("user") or {}).get("login"),
                created_at=_parse_dt(issue.get("created_at")),
                extras={
                    "closed_at": issue.get("closed_at"),
                    "labels": [l["name"] for l in issue.get("labels", [])],
                    "comments": comments,
                },
            )
            count += 1
            if max_items and count >= max_items:
                return

    def _fetch_pr_comments(self, owner: str, repo: str, number: int) -> list[dict]:
        # Issue-style comments on the PR (code review comments intentionally
        # excluded for now — they're noisy and line-anchored).
        return [
            {"author": (c.get("user") or {}).get("login"), "body": c.get("body") or ""}
            for c in self._paginate(f"/repos/{owner}/{repo}/issues/{number}/comments")
        ]

    def _fetch_issue_comments(self, owner: str, repo: str, number: int) -> list[dict]:
        return [
            {"author": (c.get("user") or {}).get("login"), "body": c.get("body") or ""}
            for c in self._paginate(f"/repos/{owner}/{repo}/issues/{number}/comments")
        ]

    def _paginate(self, path: str, params: dict | None = None) -> Iterator[dict]:
        url: str | None = path
        local_params = dict(params or {})
        while url:
            resp = self._client.get(url, params=local_params if url == path else None)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list):
                return
            yield from data
            url = _next_link(resp.headers.get("link"))


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        section = part.strip()
        if section.endswith('rel="next"'):
            start = section.find("<") + 1
            end = section.find(">")
            if start and end != -1:
                return section[start:end]
    return None
