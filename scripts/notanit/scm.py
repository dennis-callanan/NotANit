"""Source-control-management abstraction.

Each provider client returns a list of ``ReviewComment`` objects with the same
shape, so the rest of the pipeline is provider-agnostic. Add a provider by
implementing a client with a ``fetch_review_comments(weeks)`` method and
registering it in ``build_scm_client``.
"""

from dataclasses import dataclass


@dataclass
class ReviewComment:
    mr_iid: int  # MR/PR number
    mr_title: str
    author: str
    body: str
    created_at: str


def raise_for_auth(resp, provider: str) -> None:
    """Turn an auth failure into an actionable message before ``raise_for_status``.

    A 401/403 here means the token was rejected even though it passed the
    config-time shape check — typically expired, revoked, lacking ``read_api``
    scope, or minted on a different (self-managed) host than ``scm.url``.
    """
    if resp.status_code in (401, 403):
        raise PermissionError(
            f"{provider} rejected the token ({resp.status_code}). Check that it is "
            f"not expired/revoked, has 'read_api' (GitLab) or 'repo' read (GitHub) "
            f"scope, and was created on the same host as scm.url."
        )


def is_noise(body: str, noise_patterns: list[str], min_length: int) -> bool:
    """True if a comment is too short or matches a low-signal pattern."""
    lowered = body.strip().lower()
    if len(lowered) < min_length:
        return True
    return any(pattern in lowered for pattern in noise_patterns)


def build_scm_client(scm_cfg, noise_patterns: list[str], min_comment_length: int):
    """Factory: return the right client for the configured provider."""
    provider = scm_cfg.provider
    if provider == "gitlab":
        from .gitlab_client import GitLabClient

        return GitLabClient(
            url=scm_cfg.url,
            token=scm_cfg.token,
            project_path=scm_cfg.project_path,
            noise_patterns=noise_patterns,
            min_comment_length=min_comment_length,
            verify=scm_cfg.verify,
        )
    if provider == "github":
        from .github_client import GitHubClient

        return GitHubClient(
            url=scm_cfg.url,
            token=scm_cfg.token,
            project_path=scm_cfg.project_path,
            noise_patterns=noise_patterns,
            min_comment_length=min_comment_length,
            verify=scm_cfg.verify,
        )
    raise ValueError(
        f"Unknown SCM provider '{provider}'. Use 'gitlab' or 'github'."
    )
