"""LLM client with pluggable providers.

Two providers are supported out of the box:

* ``anthropic`` — the direct Anthropic Messages API (uses ``requests``, no extra
  dependency). This is the default and the simplest to set up.
* ``bedrock``  — Anthropic models via AWS Bedrock, with optional role assumption
  (requires ``boto3``).

To add another provider, write a ``_call_<provider>`` function returning the
model's text and register it in ``call_llm``.
"""

import json

import requests

from .config import LLMConfig


def _call_anthropic(cfg: LLMConfig, prompt: str) -> str:
    resp = requests.post(
        f"{cfg.api_base.rstrip('/')}/v1/messages",
        headers={
            "x-api-key": cfg.api_key,
            "anthropic-version": cfg.anthropic_version,
            "content-type": "application/json",
        },
        json={
            "model": cfg.model_id,
            "max_tokens": cfg.max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


def _build_bedrock_client(cfg: LLMConfig):
    import boto3  # imported lazily so anthropic-only users don't need boto3

    if cfg.aws_role_arn:
        base_session = boto3.Session(
            aws_access_key_id=cfg.aws_access_key_id,
            aws_secret_access_key=cfg.aws_secret_access_key,
            region_name=cfg.aws_region,
        )
        sts = base_session.client("sts")
        assumed = sts.assume_role(
            RoleArn=cfg.aws_role_arn,
            RoleSessionName="notanit",
        )
        creds = assumed["Credentials"]
        session = boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=cfg.aws_region,
        )
    else:
        session = boto3.Session(
            aws_access_key_id=cfg.aws_access_key_id,
            aws_secret_access_key=cfg.aws_secret_access_key,
            region_name=cfg.aws_region,
        )

    return session.client("bedrock-runtime", region_name=cfg.aws_region)


def _call_bedrock(cfg: LLMConfig, prompt: str) -> str:
    client = _build_bedrock_client(cfg)
    body = {
        "anthropic_version": cfg.bedrock_anthropic_version,
        "max_tokens": cfg.max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    response = client.invoke_model(
        modelId=cfg.model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body),
    )
    result = json.loads(response["body"].read())
    return result["content"][0]["text"]


_PROVIDERS = {
    "anthropic": _call_anthropic,
    "bedrock": _call_bedrock,
}


def call_llm(cfg: LLMConfig, prompt: str) -> str:
    handler = _PROVIDERS.get(cfg.provider)
    if handler is None:
        raise ValueError(
            f"Unknown LLM provider '{cfg.provider}'. "
            f"Available: {', '.join(_PROVIDERS)}."
        )
    return handler(cfg, prompt)
