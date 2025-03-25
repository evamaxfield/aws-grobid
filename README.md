# AWS GROBID Deploy

Deploy GROBID on AWS EC2 using Python.

**Note:** The deployed GROBID service is publicly available on the internet. It is best practice to always teardown the instance when not in use. Spinning up new instances is fast and easy.

## Usage

```python
import aws_grobid

# There are a few different pre-canned configurations available:

# Base GROBID service w/ CRF only models
# aws_grobid.GROBIDDeploymentConfigs.grobid_lite

# Base GROBID service w/ Deep Learning models
# aws_grobid.GROBIDDeploymentConfigs.grobid_full

# Software Mentions annotation service w/ Deep Learning models
# aws_grobid.GROBIDDeploymentConfigs.software_mentions

# Create a new GROBID instance and wait for it to be ready
# This generally takes about 6 minutes
# Instance is automatically torn down if the
# GROBID service is not available within 7 minutes
instance_details = aws_grobid.deploy_and_wait_for_ready(
  deployment_config=aws_grobid.DeploymentConfigs.grobid_lite,
)

# You can also specify the instance type, region, tags, etc.
# instance_details = aws_grobid.deploy_and_wait_for_ready(
#   deployment_config=aws_grobid.DeploymentConfigs.grobid_full,
#   instance_type='c5.4xlarge',
#   region='us-east-1',
#   tags={'awsApplication': 'arn:...'},
#   timeout=300,  # 5 minutes
# )

# Use the instance to process a PDF file
# The API URL is available from:
# instance_details.api_url
# ...

# Teardown the instance when done
aws_grobid.terminate_instance(
  region=instance_details.region,
  instance_id=instance_details.instance_id
)
```

When providing an instance type that has GPUs available, we automatically pass the GPU flag to the GROBID service. This allows GROBID to utilize the GPU for processing, which can significantly speed up the extraction of information from documents.

**Note:** The first time you make a call to the GROBID service, it may take a minute or so to warm up the service. Subsequent calls will be much faster.

We additionally will automatically pick up `.env` controlled envionment variables. This is useful for setting the `AWS_PROFILE` or `AWS_SECRET_ACCESS_KEY` and `AWS_ACCESS_KEY_ID` environment variables.