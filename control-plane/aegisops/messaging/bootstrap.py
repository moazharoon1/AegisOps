"""Idempotent seeding of the emulated AWS resources (single source of truth).

Run by the platform bootstrap Job on every `make up` (LocalStack community state is not
persistent) and usable from a workstation:

    uv run --no-sync python -m aegisops.messaging.bootstrap \
        --endpoint http://localhost:4566 --payment-key-file .data/bootstrap/payment-api-key

The payment key file holds the synthetic `sk_canary_...` credential. Its value is only ever
written to Secrets Manager here; it is never printed or logged.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, EndpointConnectionError

log = logging.getLogger("aegisops.bootstrap")

PAYMENT_SECRET_NAME = "shop/payment-api-key"  # noqa: S105 - a secret *name*, not a value


@dataclass(frozen=True)
class QueueSpec:
    name: str
    dlq: str
    max_receive_count: int
    visibility_timeout_s: int = 30


QUEUES: tuple[QueueSpec, ...] = (
    QueueSpec("payment-events", "payment-events-dlq", max_receive_count=3),
    QueueSpec("aegisops-workflow", "aegisops-workflow-dlq", max_receive_count=5, visibility_timeout_s=120),
)
EVENT_BUS = "aegisops-events"
WORKFLOW_RULE = "aegisops-workflow-route"
WORKFLOW_SOURCE = "aegisops.control-plane"
ARTIFACT_BUCKET = "aegisops-artifacts"


def _clients(endpoint: str, region: str) -> dict[str, object]:
    cfg = Config(retries={"max_attempts": 5, "mode": "standard"}, connect_timeout=5, read_timeout=15)
    kwargs = dict(
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id="test",
        aws_secret_access_key="test",  # noqa: S106 - LocalStack dummy credentials
        config=cfg,
    )
    return {name: boto3.client(name, **kwargs) for name in ("sqs", "events", "s3", "secretsmanager")}


def wait_for_endpoint(endpoint: str, region: str, timeout_s: float = 120.0) -> None:
    sqs = _clients(endpoint, region)["sqs"]
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            sqs.list_queues()  # type: ignore[attr-defined]
            return
        except (EndpointConnectionError, ClientError) as exc:
            if time.monotonic() > deadline:
                raise RuntimeError(f"AWS emulator at {endpoint} not reachable: {exc}") from exc
            time.sleep(2)


def _queue_arn(sqs, url: str) -> str:
    return sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]


def ensure_queues(sqs) -> dict[str, str]:
    urls: dict[str, str] = {}
    for spec in QUEUES:
        dlq_url = sqs.create_queue(QueueName=spec.dlq)["QueueUrl"]
        urls[spec.dlq] = dlq_url
        redrive = json.dumps(
            {"deadLetterTargetArn": _queue_arn(sqs, dlq_url), "maxReceiveCount": str(spec.max_receive_count)}
        )
        url = sqs.create_queue(QueueName=spec.name)["QueueUrl"]
        # set_queue_attributes (not create_queue attributes) so re-runs repair drifted configuration
        sqs.set_queue_attributes(
            QueueUrl=url,
            Attributes={"RedrivePolicy": redrive, "VisibilityTimeout": str(spec.visibility_timeout_s)},
        )
        urls[spec.name] = url
    return urls


def ensure_event_routing(events, sqs, workflow_queue_url: str) -> None:
    try:
        events.create_event_bus(Name=EVENT_BUS)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceAlreadyExistsException":
            raise
    events.put_rule(
        Name=WORKFLOW_RULE,
        EventBusName=EVENT_BUS,
        EventPattern=json.dumps({"source": [WORKFLOW_SOURCE]}),
        State="ENABLED",
    )
    events.put_targets(
        Rule=WORKFLOW_RULE,
        EventBusName=EVENT_BUS,
        Targets=[{"Id": "aegisops-workflow-queue", "Arn": _queue_arn(sqs, workflow_queue_url)}],
    )


def ensure_bucket(s3) -> None:
    try:
        s3.create_bucket(Bucket=ARTIFACT_BUCKET)
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
            raise


def ensure_payment_secret(secrets, payment_key: str) -> str:
    """Create the secret if absent. If present with a *different* AWSCURRENT value (e.g. a scenario
    left an invalid version active across an emulator restart), restore the known-valid value as a
    new AWSCURRENT version. Returns "created" | "unchanged" | "restored"."""
    try:
        secrets.describe_secret(SecretId=PAYMENT_SECRET_NAME)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        secrets.create_secret(
            Name=PAYMENT_SECRET_NAME,
            Description="Synthetic payment provider API key used by checkout-service (demo credential).",
            SecretString=payment_key,
        )
        return "created"
    current = secrets.get_secret_value(SecretId=PAYMENT_SECRET_NAME)["SecretString"]
    if current == payment_key:
        return "unchanged"
    secrets.put_secret_value(SecretId=PAYMENT_SECRET_NAME, SecretString=payment_key)
    return "restored"


def ensure_aws_resources(endpoint: str, region: str = "us-east-1", payment_key: str | None = None) -> dict[str, object]:
    wait_for_endpoint(endpoint, region)
    c = _clients(endpoint, region)
    urls = ensure_queues(c["sqs"])
    ensure_event_routing(c["events"], c["sqs"], urls["aegisops-workflow"])
    ensure_bucket(c["s3"])
    secret_state = ensure_payment_secret(c["secretsmanager"], payment_key) if payment_key else "skipped"
    return {"queues": sorted(urls), "event_bus": EVENT_BUS, "bucket": ARTIFACT_BUCKET, "payment_secret": secret_state}


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed emulated AWS resources for AegisOps (idempotent).")
    parser.add_argument("--endpoint", default="http://aws-sim.cloud-sim.svc.cluster.local:4566")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--payment-key-file", type=Path, default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    key = args.payment_key_file.read_text().strip() if args.payment_key_file else None
    result = ensure_aws_resources(args.endpoint, args.region, key)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
