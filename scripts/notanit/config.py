"""Configuration loading and defaults.

Precedence for every value is: environment variable > config file
(``config.yaml``) > built-in default. Nothing here is specific to any one
organisation; org-specific values are supplied via env vars or a config file at
runtime.
"""

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Built-in defaults (override these via the config file or env vars)
# ---------------------------------------------------------------------------

# Lexical theme buckets. A comment is assigned to the first theme whose keyword
# it contains. Override the whole map via the config file's "theme_keywords".
DEFAULT_THEME_KEYWORDS: dict[str, list[str]] = {
    "testing": ["test", "spec", "coverage", "regression", "mock", "stub", "assert"],
    "error_handling": ["error", "exception", "raise", "catch", "handle", "graceful"],
    "types": ["type hint", "typing", "mypy", "annotation", "typed"],
    "documentation": ["docstring", "comment", "doc", "readme", "changelog"],
    "naming": ["naming", "rename", "variable name", "function name", "misleading"],
    "code_structure": ["extract", "refactor", "split", "too long", "complexity", "abstraction"],
    "security": ["secret", "credential", "token", "auth", "permission", "sensitive"],
    "performance": ["n+1", "query", "performance", "slow", "cache", "batch"],
}

# Low-signal comments dropped before clustering. Override via "noise_patterns".
DEFAULT_NOISE_PATTERNS: list[str] = [
    "lgtm", "looks good", "approved", "thanks", "thank you", "rebase",
    "merge conflict", "pipeline", "please merge", "👍", "+1", "wip",
    "addressing", "done", "fixed", "will do", "good point",
]

DEFAULT_MIN_COMMENT_LENGTH = 20

# Provider defaults
DEFAULT_LLM_PROVIDER = "anthropic"
DEFAULT_SCM_PROVIDER = "gitlab"

DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
DEFAULT_ANTHROPIC_BASE = "https://api.anthropic.com"
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"

DEFAULT_BEDROCK_MODEL = "us.anthropic.claude-sonnet-4-6"
DEFAULT_BEDROCK_REGION = "us-east-1"
DEFAULT_BEDROCK_ANTHROPIC_VERSION = "bedrock-2023-05-31"

DEFAULT_SCM_URLS = {
    "gitlab": "https://gitlab.com",
    "github": "https://api.github.com",
}

DEFAULT_MAX_TOKENS = 4096


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ScmConfig:
    provider: str  # "gitlab" | "github"
    url: str
    token: str
    project_path: str  # e.g. "mygroup/myrepo" or "owner/repo"
    # TLS verification passed straight to ``requests``: True (verify against the
    # default CA bundle), False (skip verification — insecure), or a path to a
    # CA-bundle PEM. Set a path when a corporate TLS-inspection proxy re-signs
    # traffic with a private root CA that the default bundle doesn't trust.
    verify: bool | str = True


@dataclass
class LLMConfig:
    provider: str  # "anthropic" | "bedrock"
    model_id: str
    max_tokens: int = DEFAULT_MAX_TOKENS
    # Anthropic direct API
    api_key: str = ""
    api_base: str = DEFAULT_ANTHROPIC_BASE
    anthropic_version: str = DEFAULT_ANTHROPIC_VERSION
    # AWS Bedrock
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_session_token: str = ""  # required only for temporary (STS) credentials
    aws_region: str = DEFAULT_BEDROCK_REGION
    aws_role_arn: str = ""
    bedrock_anthropic_version: str = DEFAULT_BEDROCK_ANTHROPIC_VERSION


@dataclass
class PipelineConfig:
    target_root: str = "."  # folder holding the target_files to read/edit (in Docker, the mounted path)
    weeks: int = 8
    target_files: list[str] = field(default_factory=lambda: ["AGENTS.md"])
    max_changes: int = 3
    min_mr_occurrences: int = 3
    min_comment_length: int = DEFAULT_MIN_COMMENT_LENGTH
    theme_keywords: dict[str, list[str]] = field(
        default_factory=lambda: dict(DEFAULT_THEME_KEYWORDS)
    )
    noise_patterns: list[str] = field(
        default_factory=lambda: list(DEFAULT_NOISE_PATTERNS)
    )
    # Optional free-text instructions appended to the LLM prompt, e.g.
    # "Prefer imperative phrasing" or "Never propose changes about formatting".
    extra_guidance: str = ""


@dataclass
class Config:
    scm: ScmConfig
    llm: LLMConfig
    pipeline: PipelineConfig


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------

def load_config_file(path: str | None) -> dict[str, Any]:
    """Load a YAML config file into a dict. Returns {} if no path."""
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    if p.suffix.lower() not in (".yaml", ".yml"):
        raise ValueError(
            f"Config file must be YAML (.yaml/.yml), got '{p.suffix}'. "
            "See config.example.yaml."
        )
    try:
        import yaml  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "YAML config requires PyYAML. Install it: pip install pyyaml"
        ) from e
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("Config file must contain a top-level mapping.")
    return data


def _first(*values: Any) -> Any:
    """Return the first value that is not None."""
    for v in values:
        if v is not None:
            return v
    return None


# Matches a ${VAR} environment reference inside a YAML string value.
_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _validate_scm_token(provider: str, url: str, token: str) -> None:
    """Catch a token that is structurally malformed (and so can never
    authenticate) before the API returns a bare ``401``. A wrong-but-well-formed
    token is left for the runtime auth check — only the API can authoritatively
    say whether a token is valid.
    """
    # Structural problems are always fatal — these can never authenticate.
    problem = None
    if not token:
        problem = "is empty"
    elif token != token.strip():
        problem = "has leading/trailing whitespace"
    elif any(c.isspace() for c in token):
        problem = "contains an internal space or newline (likely a copy/paste truncation)"
    elif token[0] in "'\"" or token[-1] in "'\"":
        problem = "is wrapped in quotes — remove them; .env values are not quoted"
    elif "${" in token:
        problem = "still contains an unresolved ${VAR} reference — the env var is not set"
    if problem:
        raise EnvironmentError(
            f"SCM token {problem}. Set a valid token in SCM_TOKEN (.env)."
        )

    # Prefix is only a hint: it's the modern default (GitLab ``glpat-`` etc.,
    # GitHub ``ghp_``/``github_pat_``) but is instance-configurable, absent on
    # older tokens, and differs by token type. So warn — never fail — on a
    # mismatch, and don't claim the value is definitely wrong.
    common = {"gitlab": ("glpat-",), "github": ("ghp_", "github_pat_", "gho_", "ghs_")}.get(provider)
    if common and not token.startswith(common):
        pretty = " or ".join(repr(p) for p in common)
        print(
            f"[warning] SCM token does not start with the usual {provider} prefix "
            f"({pretty}). That's fine for older, self-managed, or non-PAT tokens, "
            f"but if you just copied a personal access token, double-check it wasn't "
            f"truncated. If the repo is on a self-managed {provider} instance, set "
            f"scm.url to that host.",
            file=sys.stderr,
        )

# Credential fields. They SHOULD be written as ${ENV_VAR} references so the value
# lives in the environment (.env), not the committed config. A literal value here
# is a secret about to be committed, and is flagged.
_SECRET_FILE_PATHS = (
    ("scm", "token"),
    ("llm", "anthropic", "api_key"),
    ("llm", "bedrock", "aws_access_key_id"),
    ("llm", "bedrock", "aws_secret_access_key"),
    ("llm", "bedrock", "aws_session_token"),
)


def _dig(node: Any, path: tuple[str, ...]) -> Any:
    """Walk a nested dict by ``path``; return None if any step is missing."""
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _interpolate(value: Any) -> Any:
    """Recursively replace ``${VAR}`` references in strings with env values.

    ``.env`` has already been loaded into the environment by this point, so a
    reference resolves from ``.env`` first, then the real shell environment. A
    value that is *exactly* one ``${VAR}`` resolves to None when VAR is unset (so
    it counts as "absent" for precedence); a mixed string substitutes an unset
    reference with an empty string.
    """
    if isinstance(value, str):
        whole = _ENV_REF.fullmatch(value.strip())
        if whole:
            return os.environ.get(whole.group(1))
        return _ENV_REF.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _interpolate(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(v) for v in value]
    return value


def _warn_if_literal_secrets(file_cfg: dict[str, Any]) -> None:
    """Warn if a credential field holds a literal value instead of a ${VAR} ref."""
    literal = [
        ".".join(p)
        for p in _SECRET_FILE_PATHS
        if isinstance((v := _dig(file_cfg, p)), str) and v and not _ENV_REF.search(v)
    ]
    if literal:
        print(
            "[warning] Literal secret value(s) in the config file: "
            f"{', '.join(literal)}. Use a ${{ENV_VAR}} reference instead and keep "
            "the value in .env (see .env.example).",
            file=sys.stderr,
        )


def load_config(*, file_cfg: dict[str, Any] | None = None) -> Config:
    """Build a Config from the YAML config and built-in defaults.

    Resolution is: config file > built-in default. All configuration lives in the
    file (with ``${VAR}`` references resolved from the environment).

    The config file may use ``${VAR}`` references anywhere; each is resolved from
    the environment (``.env`` first, then the shell) before this runs. Credentials
    are referenced this way — ``token: ${SCM_TOKEN}`` — so the config documents
    what's required while the secret value stays in ``.env``. If a credential field
    is omitted from the file, its conventional env var is used as a fallback.

    Provider-specific LLM settings live under ``llm.anthropic`` / ``llm.bedrock``;
    only the block matching ``llm.provider`` is read.

    ``file_cfg`` is the parsed config file (see ``load_config_file``).
    """
    file_cfg = file_cfg or {}
    env = os.environ.get

    _warn_if_literal_secrets(file_cfg)   # check before ${VAR} refs are resolved
    file_cfg = _interpolate(file_cfg)

    scm_file = file_cfg.get("scm", {})
    llm_file = file_cfg.get("llm", {})
    pipe_file = file_cfg.get("pipeline", {})

    # --- SCM ---------------------------------------------------------------
    scm_provider = _first(scm_file.get("provider"), DEFAULT_SCM_PROVIDER)
    scm_url = _first(scm_file.get("url"), DEFAULT_SCM_URLS.get(scm_provider, ""))
    project_path = scm_file.get("project_path")
    # Credential: config reference (e.g. ${SCM_TOKEN}), else the env var directly.
    scm_token = _first(
        scm_file.get("token"),
        env("SCM_TOKEN"),
        env("GITLAB_TOKEN") if scm_provider == "gitlab" else None,
        env("GITHUB_TOKEN") if scm_provider == "github" else None,
    )
    # TLS verification. A ``ca_bundle`` path (e.g. a corporate root CA) wins; else
    # ``verify_tls: false`` disables verification entirely (insecure, last resort);
    # otherwise verify normally. When verify is left True, requests still honours
    # the REQUESTS_CA_BUNDLE / CURL_CA_BUNDLE env vars.
    scm_ca_bundle = scm_file.get("ca_bundle")
    scm_verify_tls = scm_file.get("verify_tls")
    if scm_ca_bundle:
        scm_verify: bool | str = scm_ca_bundle
    elif scm_verify_tls is False:
        scm_verify = False
    else:
        scm_verify = True

    if not project_path:
        raise EnvironmentError(
            "No project specified. Set scm.project_path in the config file."
        )
    if not scm_token:
        raise EnvironmentError(
            f"No SCM token found. Reference it in the config (token: ${{SCM_TOKEN}}) "
            f"or set SCM_TOKEN (or "
            f"{'GITLAB_TOKEN' if scm_provider == 'gitlab' else 'GITHUB_TOKEN'}) "
            f"in your .env file."
        )
    _validate_scm_token(scm_provider, scm_url, scm_token)

    scm = ScmConfig(
        provider=scm_provider,
        url=scm_url,
        token=scm_token,
        project_path=project_path,
        verify=scm_verify,
    )

    # --- LLM ---------------------------------------------------------------
    # Shared settings live at the top of `llm`; provider-specific settings live
    # in the `llm.anthropic` / `llm.bedrock` sub-blocks. Only the active one is read.
    max_tokens = int(_first(llm_file.get("max_tokens"), DEFAULT_MAX_TOKENS))
    anthropic_file = llm_file.get("anthropic", {}) or {}
    bedrock_file = llm_file.get("bedrock", {}) or {}

    # Provider selection: an explicit `llm.provider` always wins. Otherwise it's
    # inferred from whichever block is configured — only ambiguous (an error) when
    # both are populated, and falling back to the default when neither is.
    configured = [n for n, blk in (("anthropic", anthropic_file), ("bedrock", bedrock_file)) if blk]
    explicit_provider = llm_file.get("provider")
    if explicit_provider:
        llm_provider = explicit_provider
    elif len(configured) == 1:
        llm_provider = configured[0]
    elif not configured:
        llm_provider = DEFAULT_LLM_PROVIDER
    else:
        raise EnvironmentError(
            "Both llm.anthropic and llm.bedrock are configured — set llm.provider "
            "to choose which one to use."
        )

    if llm_provider == "anthropic":
        llm = LLMConfig(
            provider="anthropic",
            model_id=_first(anthropic_file.get("model_id"), DEFAULT_ANTHROPIC_MODEL),
            max_tokens=max_tokens,
            api_base=_first(anthropic_file.get("api_base"), DEFAULT_ANTHROPIC_BASE),
            anthropic_version=_first(anthropic_file.get("api_version"), DEFAULT_ANTHROPIC_VERSION),
            # Credential: config reference (e.g. ${ANTHROPIC_API_KEY}), else env var.
            api_key=_first(anthropic_file.get("api_key"), env("ANTHROPIC_API_KEY"), ""),
        )
        if not llm.api_key:
            raise EnvironmentError(
                "LLM provider is 'anthropic' but no API key found. Reference it in "
                "the config (anthropic.api_key: ${ANTHROPIC_API_KEY}) or set "
                "ANTHROPIC_API_KEY in your .env file."
            )
    elif llm_provider == "bedrock":
        # Credentials: config reference (e.g. ${AWS_ACCESS_KEY_ID}), else env var.
        access_key = _first(bedrock_file.get("aws_access_key_id"), env("AWS_ACCESS_KEY_ID"))
        secret_key = _first(bedrock_file.get("aws_secret_access_key"), env("AWS_SECRET_ACCESS_KEY"))
        if not access_key or not secret_key:
            raise EnvironmentError(
                "LLM provider is 'bedrock' but no AWS credentials found. Reference "
                "them in the config (bedrock.aws_access_key_id: ${AWS_ACCESS_KEY_ID}, "
                "aws_secret_access_key: ${AWS_SECRET_ACCESS_KEY}) or set those vars in .env."
            )
        llm = LLMConfig(
            provider="bedrock",
            model_id=_first(bedrock_file.get("model_id"), DEFAULT_BEDROCK_MODEL),
            max_tokens=max_tokens,
            aws_region=_first(bedrock_file.get("aws_region"), DEFAULT_BEDROCK_REGION),
            aws_role_arn=_first(bedrock_file.get("aws_role_arn"), ""),
            bedrock_anthropic_version=_first(bedrock_file.get("api_version"), DEFAULT_BEDROCK_ANTHROPIC_VERSION),
            # Credentials: config reference, else env var.
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            aws_session_token=_first(bedrock_file.get("aws_session_token"), env("AWS_SESSION_TOKEN"), ""),
        )
    else:
        raise ValueError(
            f"Unknown LLM provider '{llm_provider}'. Use 'anthropic' or 'bedrock'."
        )

    # --- Pipeline ----------------------------------------------------------
    defaults = PipelineConfig()
    pipeline = PipelineConfig(
        target_root=_first(pipe_file.get("target_root"), defaults.target_root),
        weeks=int(_first(pipe_file.get("weeks"), defaults.weeks)),
        target_files=_first(pipe_file.get("target_files"), defaults.target_files),
        max_changes=int(_first(pipe_file.get("max_changes"), defaults.max_changes)),
        min_mr_occurrences=int(_first(pipe_file.get("min_mr_occurrences"), defaults.min_mr_occurrences)),
        min_comment_length=int(_first(pipe_file.get("min_comment_length"), defaults.min_comment_length)),
        theme_keywords=_first(pipe_file.get("theme_keywords"), defaults.theme_keywords),
        noise_patterns=_first(pipe_file.get("noise_patterns"), defaults.noise_patterns),
        extra_guidance=_first(pipe_file.get("extra_guidance"), defaults.extra_guidance),
    )

    return Config(scm=scm, llm=llm, pipeline=pipeline)
