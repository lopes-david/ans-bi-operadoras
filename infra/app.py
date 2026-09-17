#!/usr/bin/env python3
"""App CDK. Conta e região vêm do ambiente (AWS_PROFILE / AWS_DEFAULT_REGION)."""

import os

import aws_cdk as cdk
from stack import AnsBiStack

app = cdk.App()
AnsBiStack(
    app,
    app.node.try_get_context("stackName"),
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION") or os.environ.get("AWS_DEFAULT_REGION"),
    ),
    description="ANS BI: pipeline serverless de dados abertos da ANS (S3 + Lambda + Athena + CloudFront)",
)
cdk.Tags.of(app).add("project", "ans-bi-operadoras")
app.synth()
