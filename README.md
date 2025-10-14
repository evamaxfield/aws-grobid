# AWS GROBID Deploy

Deploy GROBID on AWS EC2 using Python.

**Note:** The deployed EC2 GROBID service will be publicly available on the internet. It is best practice (and more "economically sustainable") to always teardown the instance when not in use. Spinning up new instances is fast and easy.

## Prerequisites

Before using this tool, ensure you have:

1. **AWS Account** with appropriate permissions (see [AWS_PERMISSIONS.md](AWS_PERMISSIONS.md))
2. **AWS Credentials** configured via AWS profiles or environment variables
3. **Required IAM Permissions** for EC2 operations

### Quick Setup
```bash
# Configure AWS profile
aws configure --profile your-profile-name

# Test your credentials
aws sts get-caller-identity --profile your-profile-name
```

For detailed setup instructions, see the [AWS Permissions Guide](AWS_PERMISSIONS.md).

## Usage (Python)

```python
import json

import aws_grobid
import requests

# There are a few different pre-canned configurations available:

# Base GROBID service w/ CRF only models
# aws_grobid.GROBIDDeploymentConfigs.grobid_crf

# Base GROBID service w/ Deep Learning models
# aws_grobid.GROBIDDeploymentConfigs.grobid_full

# Software Mentions annotation service w/ Deep Learning models
# aws_grobid.GROBIDDeploymentConfigs.software_mentions
# NOTE: You also need to change the URL endpoint specified below for Software mentions

# Create a new GROBID instance and wait for it to be ready
# This generally takes about 6 minutes
# Instance is automatically torn down if the
# GROBID service is not available within 7 minutes
instance_details = aws_grobid.deploy_and_wait_for_ready(
  grobid_config=aws_grobid.GROBIDDeploymentConfigs.grobid_crf,
)

# You can also specify the instance type, region, tags, etc.
# instance_details = aws_grobid.deploy_and_wait_for_ready(
#   grobid_config=aws_grobid.GROBIDDeploymentConfigs.grobid_full,
#   instance_type='c5.4xlarge',
#   region='us-east-1',
#   tags={'awsApplication': 'arn:...'},
#   timeout=420,  # 7 minutes
# )

# Use the instance to process a PDF file
# The API URL is available from:
# instance_details.api_url
# ...

# Example request to GROBID Server for Annotation
with open("example.pdf", "rb") as open_pdf:
  response = requests.post(
    # NOTE: Use f"{instance_details.api_url}/service/annotateSoftwarePDF" for Software mentions
    f"{instance_details.api_url}/api/processFulltextDocument",
    files={"input": open_pdf},
    data={"disambiguate": 1},
    timeout=180,  # 3 minutes
  )
  response.raise_for_status()
  response_data = response.json()

# Write response to JSON
with open("example-output.json", "w") as open_json:
  json.dump(response_data, open_json)

# Teardown the instance when done
aws_grobid.terminate_instance(
  region=instance_details.region,
  instance_id=instance_details.instance_id
)
```

When providing an instance type that has NVIDIA GPUs available (G* or P* families), we automatically pass the GPU flag to Docker so GROBID can use the GPU.

Note: The first call to the GROBID service may take a minute or so to warm up. Subsequent calls are much faster.

We automatically pick up `.env`-controlled environment variables. This is useful for setting `AWS_PROFILE` or `AWS_SECRET_ACCESS_KEY` and `AWS_ACCESS_KEY_ID`.

## CLI

After installing the package, a CLI is available as `aws-grobid`.

- Deploy and wait until ready (prints instance details as JSON):

```bash
# Deploy with default credentials
aws-grobid deploy --config crf --instance-type m6a.4xlarge --region us-west-2 \
  --tag awsApplication=example --timeout 420

# Deploy with specific AWS profile
aws-grobid deploy --config crf --instance-type m6a.4xlarge --region us-west-2 \
  --tag awsApplication=example --timeout 420 --profile your-profile-name
```

- Terminate an instance:

```bash
# Terminate with default credentials
aws-grobid terminate --region us-west-2 --instance-id i-0123456789abcdef0

# Terminate with specific AWS profile
aws-grobid terminate --region us-west-2 --instance-id i-0123456789abcdef0 \
  --profile your-profile-name
```

Note: 'lite' remains available as a deprecated alias for 'crf' for backward compatibility.

## Optional: better typing in editors

If you want precise types for the boto3 clients/resources in your IDE or mypy, install the dev extras:

```bash
pip install -e ".[dev]"
```

This includes `boto3-stubs[ec2]` and enables rich autocompletion and type checking without affecting runtime.