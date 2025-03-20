# AWS GROBID Deploy

Deploy GROBID on AWS EC2 using Python.

**Note:** The deployed GROBID service is publicly available on the internet. It is best practice to always teardown the instance when not in use. Spinning up new instances is fast and easy.

## Usage

```python
import aws_grobid

# Create a new GROBID instance and wait for it to be ready
# This generally takes about 6 minutes
# Instance is automatically torn down if the
# GROBID service is not available within 7 minutes
instance_details = aws_grobid.deploy_and_wait_for_ready()

# You can also specify the instance type, region, tags, etc.
# instance_details = aws_grobid.deploy_and_wait_for_ready(
#   instance_type="m5.2xlarge",  # default: "m6a.4xlarge"
#   region="us-east-2",  # default: "us-west-2"
#   tags={"awsApplication": "..."},  # default: None
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

## TODO

- Add support for GROBID base vs Software Mentions deployment
- Add CLI