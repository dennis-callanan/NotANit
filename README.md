<!-- banner -->
<p align="center">
  <img src="./assets/banner.svg" alt="NotANit" width="100%">
</p>

<h1 align="center">NotANit</h1>

<p align="center">
  <em>&ldquo;Just a nit, but&hellip;&rdquo; — the comments that aren't nits become your standards.<br/>Keep your <code>AGENTS.md</code> (or any guidance doc) honest by learning from how your team <strong>actually</strong> reviews code.</em>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white">
  <img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-22c55e">
  <img alt="SCM providers" src="https://img.shields.io/badge/SCM-GitLab%20%7C%20GitHub-fc6d26?logo=gitlab&logoColor=white">
  <img alt="LLM providers" src="https://img.shields.io/badge/LLM-Anthropic%20%7C%20Bedrock-a07cff">
  <img alt="Read-only" src="https://img.shields.io/badge/repo%20access-read--only-0ea5e9">
  <img alt="PRs welcome" src="https://img.shields.io/badge/PRs-welcome-ff69b4">
</p>

<p align="center">
  <a href="#-quick-start">Quick start</a> ·
  <a href="#-how-it-works">How it works</a> ·
  <a href="#%EF%B8%8F-configuration">Configuration</a> ·
  <a href="#-providers">Providers</a> ·
  <a href="#-customisation">Customisation</a> ·
  <a href="#-safety">Safety</a>
</p>

---

## What it does

Coding-guidance docs rot. The team agrees on a convention in code review, but the
`AGENTS.md` / `CONTRIBUTING.md` / style guide never catches up — so the same notes
get written by hand on every PR.

**NotANit** closes that loop. Point it at a repository and it:

1. 📥 **Loads** your guidance docs from a local checkout (`AGENTS.md` by default — or any files you name).
2. 💬 **Reads** review comments from recently **merged** PRs/MRs via the GitLab or GitHub API, dropping noise (`lgtm`, `thanks`, one-liners…).
3. 🧩 **Clusters** comments into recurring themes (testing, error handling, naming…) and keeps only themes that recur across enough PRs.
4. 🤖 **Asks an LLM** (Anthropic API or AWS Bedrock) to propose **small, conservative** additions to the docs.
5. 📄 **Writes** an evidence report, raw proposals, and a preview diff to an output directory — **for you to review**.

It **never** writes to your repo or to your SCM host. Every output is staged for a human.

---

## ✨ Highlights

- **Provider-agnostic** — GitLab *and* GitHub out of the box; one factory away from more.
- **Bring your own LLM** — Anthropic Messages API (zero extra deps) or AWS Bedrock (with optional role assumption).
- **Configure everything** — flags, env vars, or a JSON/YAML config file, with clear precedence. Themes, noise filters, target docs, and even the prompt guidance are all configurable.
- **Works with any doc layout** — `AGENTS.md`, `CONTRIBUTING.md`, `docs/style/*.md`, whatever your team uses.
- **Safe by design** — read-only against your repo and SCM; the LLM is constrained to additive suggestions.

---

## 🚀 Quick start

> Run from the project root so the package imports resolve.

```bash
git clone https://github.com/<your-org>/notanit.git
cd notanit
pip install -r requirements.txt

# --- credentials (see Configuration below) ---
export SCM_TOKEN=<your read-only SCM token>      # GitLab read_api / GitHub repo:read
export ANTHROPIC_API_KEY=<your anthropic key>    # or use the Bedrock provider

# --- a local clone of the repo whose docs you want to update ---
git clone https://github.com/acme/widgets.git /tmp/widgets

# --- run ---
python3 -m scripts.notanit.main \
  --scm github \
  --project acme/widgets \
  --repo-root /tmp/widgets \
  --target-files AGENTS.md \
  --weeks 8
```

Prefer a file over flags? Copy [`config.example.yaml`](./config.example.yaml) to
`config.yaml`, edit it, and run with `--config config.yaml`.

### Output

Written to `<repo-root>/<output-dir>/` (default `proposals/`):

| File | What it is |
| --- | --- |
| `review-evidence-<date>.md` | Human-readable report: each proposal with rationale, evidence, confidence, and the themes analysed. **Start here.** |
| `proposals-<date>.json` | Raw structured proposals. |
| `best-practices-<date>.patch` | A readable **preview** of where text would be inserted. |

> **The `.patch` is a preview, not a guaranteed `git apply`-able patch.** Review the
> evidence report and edit the docs yourself.

---

## 🛠 How it works

```
   ┌─────────────┐   ┌──────────────┐   ┌──────────────┐   ┌─────────────┐   ┌───────────────┐
   │  Guidance   │   │  Merged PRs  │   │   Cluster    │   │     LLM     │   │   Proposals   │
   │   docs      │   │  / MRs       │   │  by theme    │   │  proposes   │   │  + evidence   │
   │ (local)     │   │ (read-only)  │   │  + threshold │   │  additions  │   │  (for review) │
   └──────┬──────┘   └──────┬───────┘   └──────┬───────┘   └──────┬──────┘   └───────┬───────┘
          │                 │                  │                  │                  │
          └─────────────────┴───────► clustering ►───────────────┴───────► writes ──┘
```

The pipeline lives in `scripts/notanit/`:

```
main.py          # CLI entry point, writes output artefacts
config.py        # config loading (flags > env > file > defaults) + dataclasses
doc_loader.py    # reads target doc files from the local checkout
scm.py           # provider-agnostic ReviewComment + client factory
gitlab_client.py # GitLab API: merged-MR review comments (+ noise filter)
github_client.py # GitHub API: merged-PR review + issue comments
pipeline.py      # clustering, prompt building, patch generation, orchestration
llm_client.py    # pluggable LLM providers (Anthropic API, AWS Bedrock)
```

---

## ⚙️ Configuration

Every value resolves with this precedence:

> **CLI flag → environment variable → config file (`--config`) → built-in default**

### CLI flags

| Flag | Default | Description |
| --- | --- | --- |
| `--project` | *(required)* | Project path: `group/repo` (GitLab) or `owner/repo` (GitHub). |
| `--repo-root` | `.` | Local path to the checked-out repo (used to read the docs). |
| `--scm` | `gitlab` | SCM provider: `gitlab` or `github`. |
| `--scm-url` | per provider | API base URL (see [Providers](#-providers)). |
| `--provider` | `anthropic` | LLM provider: `anthropic` or `bedrock`. |
| `--model` | per provider | Model ID. |
| `--target-files` | `AGENTS.md` | One or more repo-relative doc paths (space-separated). |
| `--weeks` | `8` | Weeks of merged history to analyse. |
| `--min-mr-occurrences` | `3` | A theme must appear in at least this many distinct PRs/MRs. |
| `--max-proposals` | `3` | Maximum proposed changes per run. |
| `--output-dir` | `proposals` | Output directory, relative to `--repo-root`. |
| `--config` | — | Path to a JSON/YAML config file. |

### Environment variables

**SCM**

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `SCM_PROVIDER` | no | `gitlab` | `gitlab` or `github`. |
| `SCM_TOKEN` | **yes\*** | — | Read-only token. Provider-specific fallbacks below. |
| `SCM_URL` | no | per provider | API base URL. |
| `GITLAB_TOKEN` / `GITLAB_URL` | — | — | Used when provider is `gitlab` and `SCM_*` unset. |
| `GITHUB_TOKEN` / `GITHUB_URL` | — | — | Used when provider is `github` and `SCM_*` unset. |

<sub>\* A token is required, supplied via `SCM_TOKEN` or the provider-specific variable.</sub>

**LLM — Anthropic API** (default provider)

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `ANTHROPIC_API_KEY` | **yes** | — | Your Anthropic API key. |
| `LLM_MODEL_ID` / `ANTHROPIC_MODEL_ID` | no | `claude-sonnet-4-6` | Model ID. |
| `ANTHROPIC_BASE_URL` | no | `https://api.anthropic.com` | Override for proxies/gateways. |
| `ANTHROPIC_VERSION` | no | `2023-06-01` | Anthropic API version header. |
| `LLM_MAX_TOKENS` | no | `4096` | Max output tokens. |

**LLM — AWS Bedrock** (`--provider bedrock`)

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | **yes** | — | AWS credentials. |
| `LLM_MODEL_ID` / `AWS_BEDROCK_MODEL_ID` | no | `us.anthropic.claude-sonnet-4-6` | Bedrock model / inference-profile ID. |
| `AWS_BEDROCK_REGION` / `AWS_REGION` | no | `us-east-1` | Bedrock region. |
| `AWS_BEDROCK_ROLE_ARN` | no | — | Role assumed before calling Bedrock. Leave empty to use the keys directly. |
| `AWS_BEDROCK_ANTHROPIC_VERSION` | no | `bedrock-2023-05-31` | Bedrock Anthropic API version. |

> 💡 Keep secrets in environment variables rather than committing them to a config file.

---

## 🔌 Providers

### SCM

| Provider | `--scm` | Default API base | `--project` format | Token scope |
| --- | --- | --- | --- | --- |
| GitLab (SaaS or self-hosted) | `gitlab` | `https://gitlab.com` | `group/subgroup/repo` | `read_api` |
| GitHub (.com or Enterprise) | `github` | `https://api.github.com` | `owner/repo` | `repo` read |

- **Self-hosted GitLab:** `--scm-url https://gitlab.example.com`
- **GitHub Enterprise:** `--scm-url https://github.example.com/api/v3`

Adding a provider is a matter of writing a client with a
`fetch_review_comments(weeks)` method that returns `ReviewComment` objects and
registering it in `scm.py:build_scm_client`.

### LLM

| Provider | `--provider` | Dependency | Notes |
| --- | --- | --- | --- |
| Anthropic API | `anthropic` | `requests` only | Simplest setup; the default. |
| AWS Bedrock | `bedrock` | `boto3` | Anthropic models on Bedrock, with optional `AWS_BEDROCK_ROLE_ARN` assumption. |

Add one by writing a `_call_<provider>` function in `llm_client.py` and
registering it in the `_PROVIDERS` map.

---

## 🎛 Customisation

Different teams write standards differently — so the analysis is fully tunable
via the config file (no code edits needed):

- **`target_files`** — point at whatever docs your team keeps: `AGENTS.md`,
  `CONTRIBUTING.md`, `docs/engineering/*.md`, multiple files at once.
- **`theme_keywords`** — the lexical buckets. A comment is assigned to the
  **first** theme whose keyword it contains. Replace these to match how *your*
  team reviews.
- **`noise_patterns`** + **`min_comment_length`** — drop more low-signal chatter.
- **`min_mr_occurrences`** / **`max_proposals`** / **`weeks`** — sensitivity and volume.
- **`extra_guidance`** — free-text instructions appended to the LLM prompt to
  steer tone or scope (e.g. *"Prefer imperative phrasing; never propose
  formatting rules"*) without touching code.

See [`config.example.yaml`](./config.example.yaml) and
[`config.example.json`](./config.example.json) for the full, annotated shape.

**Getting more signal from a small or quiet repo:**

```bash
python3 -m scripts.notanit.main \
  --scm gitlab --project acme/widgets --repo-root /tmp/widgets \
  --target-files AGENTS.md CONTRIBUTING.md \
  --weeks 26 \
  --min-mr-occurrences 1
```

> Target files that don't exist in the repo are skipped with a warning — double-check the paths match what's actually committed.

---

## 🔒 Safety

- **Read-only** against your SCM host and against your repo.
- The LLM is instructed to propose **only small additions/clarifications**, never to rewrite or remove existing content.
- **All** output is staged in the output directory for human review before any doc is changed.

---

## 📦 Requirements

- Python 3.10+
- `pip install -r requirements.txt` — `requests` (required); `boto3` (Bedrock only); `pyyaml` (YAML config only)
- A read-only SCM token (GitLab `read_api` or GitHub `repo` read)
- An LLM credential (Anthropic API key **or** AWS Bedrock access)
- A local clone of the target repo (to read the doc files)

---

## 🤝 Contributing

Issues and PRs are welcome — especially new SCM/LLM providers and better theme
clustering. The codebase is small, dependency-light, and provider boundaries are
clean by design.

## 📄 License

[MIT](./LICENSE) © 2026 Dennis Callanan
