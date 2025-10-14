#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import sys

from aws_grobid import (
    GROBIDDeploymentConfigs,
    deploy_and_wait_for_ready,
    terminate_instance,
)


def parse_tags(tag_args: list[str] | None) -> dict[str, str] | None:
    if not tag_args:
        return None
    tags: dict[str, str] = {}
    for t in tag_args:
        if "=" not in t:
            raise argparse.ArgumentTypeError(
                f"Invalid tag '{t}'. Expected format key=value"
            )
        k, v = t.split("=", 1)  # split on first '=' only
        if not k:
            raise argparse.ArgumentTypeError("Tag key cannot be empty")
        tags[k] = v
    return tags


def cmd_deploy(args: argparse.Namespace) -> int:
    # Configure logging to show progress
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config_map = {
        "crf": GROBIDDeploymentConfigs.grobid_crf,
        "full": GROBIDDeploymentConfigs.grobid_full,
        "software": GROBIDDeploymentConfigs.software_mentions,
        # Backwards-compatible alias (deprecated)
        "lite": GROBIDDeploymentConfigs.grobid_crf,
    }
    grobid_config = config_map[args.config]

    print("🚀 Starting deployment of GROBID server...")
    print(f"   Configuration: {args.config}")
    print(f"   Instance type: {args.instance_type}")
    print(f"   Region: {args.region}")
    print(f"   Storage size: {args.storage_size} GiB")
    if args.profile:
        print(f"   AWS profile: {args.profile}")
    print()

    instance = deploy_and_wait_for_ready(
        grobid_config=grobid_config,
        instance_type=args.instance_type,
        storage_size=args.storage_size,
        region=args.region,
        tags=parse_tags(args.tag),
        timeout=args.timeout,
        interval=args.interval,
        profile_name=args.profile,
    )

    print()
    print("✅ Deployment completed successfully!")
    print(
        json.dumps(
            {
                "region": instance.region,
                "instance_id": instance.instance_id,
                "instance_type": instance.instance_type,
                "public_ip": instance.public_ip,
                "public_dns": instance.public_dns,
                "api_url": instance.api_url,
            },
            indent=2,
        )
    )
    return 0


def cmd_terminate(args: argparse.Namespace) -> int:
    # Configure logging to show progress
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    print("🛑 Terminating EC2 instance...")
    print(f"   Instance ID: {args.instance_id}")
    print(f"   Region: {args.region}")
    if args.profile:
        print(f"   AWS profile: {args.profile}")
    print()

    terminate_instance(
        region=args.region, instance_id=args.instance_id, profile_name=args.profile
    )

    print("✅ Instance termination initiated successfully!")
    print(json.dumps({"terminated": True, "instance_id": args.instance_id}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="AWS GROBID deployment helper")
    sub = p.add_subparsers(dest="command", required=True)

    p_deploy = sub.add_parser("deploy", help="Deploy a GROBID server and wait ready")
    p_deploy.add_argument(
        "--config",
        choices=["crf", "full", "software", "lite"],
        default="crf",
        help=(
            "Which pre-canned GROBID config to deploy "
            "(use 'crf'; 'lite' is deprecated)"
        ),
    )
    p_deploy.add_argument(
        "--instance-type",
        default="m6a.4xlarge",
        help="EC2 instance type",
    )
    p_deploy.add_argument(
        "--storage-size",
        type=int,
        default=28,
        help="EBS volume size in GiB",
    )
    p_deploy.add_argument(
        "--region",
        default="us-west-2",
        help="AWS region",
    )
    p_deploy.add_argument(
        "--tag",
        action="append",
        help="Tag in key=value form (can be used multiple times)",
    )
    p_deploy.add_argument(
        "--timeout",
        type=int,
        default=420,
        help="Seconds to wait for service to become ready",
    )
    p_deploy.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Seconds between readiness checks",
    )
    p_deploy.add_argument(
        "--profile",
        help="AWS profile name from credentials file",
    )
    p_deploy.set_defaults(func=cmd_deploy)

    p_term = sub.add_parser("terminate", help="Terminate an EC2 instance")
    p_term.add_argument("--region", required=True)
    p_term.add_argument("--instance-id", required=True)
    p_term.add_argument(
        "--profile",
        help="AWS profile name from credentials file",
    )
    p_term.set_defaults(func=cmd_terminate)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
