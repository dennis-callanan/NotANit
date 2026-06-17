from datetime import datetime, timedelta, timezone

import requests

from .scm import ReviewComment, is_noise, raise_for_auth


class GitLabClient:
    def __init__(
        self,
        url: str,
        token: str,
        project_path: str,
        noise_patterns: list[str],
        min_comment_length: int,
        verify: bool | str = True,
    ):
        self.base_url = url.rstrip("/")
        self.headers = {"PRIVATE-TOKEN": token}
        # URL-encode the project path for the API
        self.project_id = requests.utils.quote(project_path, safe="")
        self.noise_patterns = noise_patterns
        self.min_comment_length = min_comment_length
        self.verify = verify

    def _get(self, path: str, params: dict | None = None) -> list | dict:
        url = f"{self.base_url}/api/v4/{path}"
        results = []
        params = params or {}
        params.setdefault("per_page", 100)
        page = 1

        while True:
            params["page"] = page
            resp = requests.get(url, headers=self.headers, params=params, verify=self.verify)
            raise_for_auth(resp, "GitLab")
            resp.raise_for_status()
            data = resp.json()

            if isinstance(data, dict):
                return data
            if not data:
                break

            results.extend(data)
            if len(data) < params["per_page"]:
                break
            page += 1

        return results

    def fetch_review_comments(self, weeks: int) -> list[ReviewComment]:
        since = (
            datetime.now(timezone.utc) - timedelta(weeks=weeks)
        ).isoformat()

        mrs = self._get(
            f"projects/{self.project_id}/merge_requests",
            params={
                "state": "merged",
                "updated_after": since,
                "scope": "all",
            },
        )

        comments: list[ReviewComment] = []

        for mr in mrs:
            mr_iid = mr["iid"]
            mr_title = mr["title"]

            notes = self._get(
                f"projects/{self.project_id}/merge_requests/{mr_iid}/notes",
                params={"sort": "asc"},
            )

            for note in notes:
                # Skip system notes (e.g. "resolved thread")
                if note.get("system", False):
                    continue
                body = note.get("body", "").strip()
                if not body or is_noise(
                    body, self.noise_patterns, self.min_comment_length
                ):
                    continue

                comments.append(
                    ReviewComment(
                        mr_iid=mr_iid,
                        mr_title=mr_title,
                        author=note["author"]["username"],
                        body=body,
                        created_at=note["created_at"],
                    )
                )

        return comments
