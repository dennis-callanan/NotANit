from datetime import datetime, timedelta, timezone

import requests

from .scm import ReviewComment, is_noise


class GitHubClient:
    """Fetches review comments from merged pull requests via the GitHub REST API.

    ``url`` is the API base (``https://api.github.com`` for github.com, or
    ``https://<host>/api/v3`` for GitHub Enterprise). ``project_path`` is
    ``owner/repo``.
    """

    def __init__(
        self,
        url: str,
        token: str,
        project_path: str,
        noise_patterns: list[str],
        min_comment_length: int,
    ):
        self.base_url = url.rstrip("/")
        self.repo = project_path.strip("/")
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self.noise_patterns = noise_patterns
        self.min_comment_length = min_comment_length

    def _get(self, path: str, params: dict | None = None) -> list:
        url = f"{self.base_url}/{path.lstrip('/')}"
        results: list = []
        params = dict(params or {})
        params.setdefault("per_page", 100)
        page = 1

        while True:
            params["page"] = page
            resp = requests.get(url, headers=self.headers, params=params)
            resp.raise_for_status()
            data = resp.json()
            if not data:
                break
            results.extend(data)
            if len(data) < params["per_page"]:
                break
            page += 1

        return results

    def fetch_review_comments(self, weeks: int) -> list[ReviewComment]:
        since = datetime.now(timezone.utc) - timedelta(weeks=weeks)

        # Closed PRs, most-recently-updated first. We stop paging once we're
        # past the cutoff window.
        comments: list[ReviewComment] = []
        page = 1
        per_page = 100
        done = False

        while not done:
            prs = requests.get(
                f"{self.base_url}/repos/{self.repo}/pulls",
                headers=self.headers,
                params={
                    "state": "closed",
                    "sort": "updated",
                    "direction": "desc",
                    "per_page": per_page,
                    "page": page,
                },
            )
            prs.raise_for_status()
            batch = prs.json()
            if not batch:
                break

            for pr in batch:
                updated = _parse_ts(pr.get("updated_at"))
                if updated and updated < since:
                    done = True
                    break
                if not pr.get("merged_at"):
                    continue
                comments.extend(self._comments_for_pr(pr))

            if len(batch) < per_page:
                break
            page += 1

        return comments

    def _comments_for_pr(self, pr: dict) -> list[ReviewComment]:
        number = pr["number"]
        title = pr["title"]
        out: list[ReviewComment] = []

        # Inline diff review comments + general PR discussion comments.
        notes = self._get(f"repos/{self.repo}/pulls/{number}/comments")
        notes += self._get(f"repos/{self.repo}/issues/{number}/comments")

        for note in notes:
            body = (note.get("body") or "").strip()
            if not body or is_noise(
                body, self.noise_patterns, self.min_comment_length
            ):
                continue
            author = (note.get("user") or {}).get("login", "unknown")
            out.append(
                ReviewComment(
                    mr_iid=number,
                    mr_title=title,
                    author=author,
                    body=body,
                    created_at=note.get("created_at", ""),
                )
            )
        return out


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    # GitHub returns e.g. "2024-01-31T12:00:00Z"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
