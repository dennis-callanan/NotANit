# Contributing

## Get up and running

```bash
git clone https://github.com/<your-org>/notanit.git && cd notanit
pip install -r requirements.txt

cp config.example.yaml config.yaml   # set scm.project_path, provider, repo_root
cp .env.example .env                 # fill in the secret values

python3 -m scripts.notanit.main      # reads ./config.yaml and ./.env
```

That's it — there's no build step or test suite. Keep changes small and the
dependency list short (`requests` + `pyyaml`; `boto3` only for Bedrock).

## How it works

The pipeline runs as a single pass: load the docs → fetch review comments on
merged PRs/MRs → cluster them into recurring themes → ask the LLM for small,
additive edits → write those edits straight into the target files (review with
`git diff`). It reads your SCM read-only and only ever writes to the local doc
files named in `pipeline.target_files`.

The code lives in `scripts/notanit/`:

```
main.py          # CLI entry point, prints a summary of applied changes
config.py        # config loading (flags > env > file > defaults) + dataclasses
doc_loader.py    # reads target doc files from the local checkout
scm.py           # provider-agnostic ReviewComment + client factory
gitlab_client.py # GitLab API: merged-MR review comments (+ noise filter)
github_client.py # GitHub API: merged-PR review + issue comments
pipeline.py      # clustering, prompt building, applying edits, orchestration
llm_client.py    # pluggable LLM providers (Anthropic API, AWS Bedrock)
```

Provider boundaries are deliberately clean:

- **Add an SCM provider** — write a client with a `fetch_review_comments(weeks)`
  method that returns `ReviewComment` objects, and register it in
  `scm.py:build_scm_client`.
- **Add an LLM provider** — write a `_call_<provider>` function in
  `llm_client.py` and register it in the `_PROVIDERS` map.

## Publishing the Docker image

Images publish to `ghcr.io/<your-org>/notanit` automatically via
[`.github/workflows/docker-publish.yml`](./.github/workflows/docker-publish.yml) —
you don't push by hand:

- **Push to `main`** → publishes/updates the `latest` tag.
- **Push a version tag** → publishes a released version:

  ```bash
  git tag v1.2.3 && git push origin v1.2.3   # -> tags v1.2.3, 1.2, latest
  ```

Auth uses the built-in `GITHUB_TOKEN`, so there's nothing to configure.

**First publish only:** the new GHCR package is private. Make it public once via
the repo's **Packages** page → the package → **Package settings** →
**Change visibility** → *Public*.
