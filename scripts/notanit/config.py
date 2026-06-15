"""Configuration loading and defaults.

Precedence for every value is: explicit CLI flag > environment variable >
config file (``--config``) > built-in default. Nothing here is specific to any
one organisation; org-specific values are supplied via env vars or a config
file at runtime.
"""

import json
import os
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
    aws_region: str = DEFAULT_BEDROCK_REGION
    aws_role_arn: str = ""
    bedrock_anthropic_version: str = DEFAULT_BEDROCK_ANTHROPIC_VERSION


@dataclass
class PipelineConfig:
    weeks: int = 8
    target_files: list[str] = field(default_factory=lambda: ["AGENTS.md"])
    output_dir: str = "proposals"
    max_proposals: int = 3
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
    """Load a JSON or YAML config file into a dict. Returns {} if no path."""
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "YAML config requires PyYAML. Install it (`pip install pyyaml`) "
                "or use a .json config file instead."
            ) from e
        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Config file must contain a top-level object/mapping.")
    return data


def _first(*values: Any) -> Any:
    """Return the first value that is not None."""
    for v in values:
        if v is not None:
            return v
    return None


def load_config(
    *,
    cli: dict[str, Any] | None = None,
    file_cfg: dict[str, Any] | None = None,
) -> Config:
    """Build a Config from CLI args, env vars, a config file, and defaults.

    ``cli`` is a dict of explicitly-provided CLI values (None where the flag was
    not given). ``file_cfg`` is the parsed config file (see ``load_config_file``).
    """
    cli = cli or {}
    file_cfg = file_cfg or {}
    env = os.environ.get

    scm_file = file_cfg.get("scm", {})
    llm_file = file_cfg.get("llm", {})
    pipe_file = file_cfg.get("pipeline", {})

    # --- SCM ---------------------------------------------------------------
    scm_provider = _first(
        cli.get("scm"), env("SCM_PROVIDER"), scm_file.get("provider"),
        DEFAULT_SCM_PROVIDER,
    )
    scm_url = _first(
        cli.get("scm_url"), env("SCM_URL"),
        env("GITLAB_URL") if scm_provider == "gitlab" else None,
        env("GITHUB_URL") if scm_provider == "github" else None,
        scm_file.get("url"),
        DEFAULT_SCM_URLS.get(scm_provider, ""),
    )
    scm_token = _first(
        env("SCM_TOKEN"),
        env("GITLAB_TOKEN") if scm_provider == "gitlab" else None,
        env("GITHUB_TOKEN") if scm_provider == "github" else None,
        scm_file.get("token"),
    )
    project_path = _first(cli.get("project"), scm_file.get("project_path"))
    if not project_path:
        raise EnvironmentError(
            "No project specified. Pass --project or set scm.project_path in the config file."
        )
    if not scm_token:
        raise EnvironmentError(
            f"No SCM token found. Set SCM_TOKEN (or "
            f"{'GITLAB_TOKEN' if scm_provider == 'gitlab' else 'GITHUB_TOKEN'})."
        )

    scm = ScmConfig(
        provider=scm_provider,
        url=scm_url,
        token=scm_token,
        project_path=project_path,
    )

    # --- LLM ---------------------------------------------------------------
    llm_provider = _first(
        cli.get("provider"), env("LLM_PROVIDER"), llm_file.get("provider"),
        DEFAULT_LLM_PROVIDER,
    )

    if llm_provider == "anthropic":
        llm = LLMConfig(
            provider="anthropic",
            model_id=_first(
                cli.get("model"), env("LLM_MODEL_ID"), env("ANTHROPIC_MODEL_ID"),
                llm_file.get("model_id"), DEFAULT_ANTHROPIC_MODEL,
            ),
            max_tokens=int(_first(env("LLM_MAX_TOKENS"), llm_file.get("max_tokens"), DEFAULT_MAX_TOKENS)),
            api_key=_first(env("ANTHROPIC_API_KEY"), llm_file.get("api_key"), ""),
            api_base=_first(env("ANTHROPIC_BASE_URL"), llm_file.get("api_base"), DEFAULT_ANTHROPIC_BASE),
            anthropic_version=_first(
                env("ANTHROPIC_VERSION"), llm_file.get("anthropic_version"),
                DEFAULT_ANTHROPIC_VERSION,
            ),
        )
        if not llm.api_key:
            raise EnvironmentError(
                "LLM provider is 'anthropic' but ANTHROPIC_API_KEY is not set."
            )
    elif llm_provider == "bedrock":
        access_key = _first(
            env("AWS_ACCESS_KEY_ID"), llm_file.get("aws_access_key_id"),
        )
        secret_key = _first(
            env("AWS_SECRET_ACCESS_KEY"), llm_file.get("aws_secret_access_key"),
        )
        if not access_key or not secret_key:
            raise EnvironmentError(
                "LLM provider is 'bedrock' but AWS credentials are not set "
                "(AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY)."
            )
        llm = LLMConfig(
            provider="bedrock",
            model_id=_first(
                cli.get("model"), env("LLM_MODEL_ID"), env("AWS_BEDROCK_MODEL_ID"),
                llm_file.get("model_id"), DEFAULT_BEDROCK_MODEL,
            ),
            max_tokens=int(_first(env("LLM_MAX_TOKENS"), llm_file.get("max_tokens"), DEFAULT_MAX_TOKENS)),
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            aws_region=_first(env("AWS_BEDROCK_REGION"), env("AWS_REGION"), llm_file.get("aws_region"), DEFAULT_BEDROCK_REGION),
            aws_role_arn=_first(env("AWS_BEDROCK_ROLE_ARN"), llm_file.get("aws_role_arn"), ""),
            bedrock_anthropic_version=_first(
                env("AWS_BEDROCK_ANTHROPIC_VERSION"), llm_file.get("anthropic_version"),
                DEFAULT_BEDROCK_ANTHROPIC_VERSION,
            ),
        )
    else:
        raise ValueError(
            f"Unknown LLM provider '{llm_provider}'. Use 'anthropic' or 'bedrock'."
        )

    # --- Pipeline ----------------------------------------------------------
    defaults = PipelineConfig()
    pipeline = PipelineConfig(
        weeks=int(_first(cli.get("weeks"), pipe_file.get("weeks"), defaults.weeks)),
        target_files=_first(cli.get("target_files"), pipe_file.get("target_files"), defaults.target_files),
        output_dir=_first(cli.get("output_dir"), pipe_file.get("output_dir"), defaults.output_dir),
        max_proposals=int(_first(cli.get("max_proposals"), pipe_file.get("max_proposals"), defaults.max_proposals)),
        min_mr_occurrences=int(_first(cli.get("min_mr_occurrences"), pipe_file.get("min_mr_occurrences"), defaults.min_mr_occurrences)),
        min_comment_length=int(_first(pipe_file.get("min_comment_length"), defaults.min_comment_length)),
        theme_keywords=_first(pipe_file.get("theme_keywords"), defaults.theme_keywords),
        noise_patterns=_first(pipe_file.get("noise_patterns"), defaults.noise_patterns),
        extra_guidance=_first(pipe_file.get("extra_guidance"), defaults.extra_guidance),
    )

    return Config(scm=scm, llm=llm, pipeline=pipeline)
