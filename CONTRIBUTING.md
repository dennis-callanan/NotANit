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
