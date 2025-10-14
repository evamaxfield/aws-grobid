#!/usr/bin/env python

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import boto3
import requests
from dotenv import load_dotenv
from jinja2 import Template

if TYPE_CHECKING:
    from mypy_boto3_ec2 import EC2Client, EC2ServiceResource
    from mypy_boto3_ec2.service_resource import Instance as EC2Instance

#######################################################################################

# Static files
STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_STARTUP_SCRIPT_TEMPLATE_PATH = STATIC_DIR / "startup-script.jinja"
NVIDIA_DOCKER_INSTALLATION_PATH = STATIC_DIR / "nvidia-docker-install.sh"
UBUNTU_AMI_DATA_PATH = STATIC_DIR / "ubuntu-amis.json"

# Constants
GPU_INSTANCE_TYPES = [
    "p",  # NVIDIA GPU families (P*)
    "g",  # NVIDIA GPU families (G*)
]


@dataclass
class GROBIDDeploymentConfig:
    instance_name: str
    docker_image: str
    api_port: int
    security_group_name: str
    security_group_description: str


BASE_GROBID_CRF_DEPLOYMENT_CONFIG = GROBIDDeploymentConfig(
    instance_name="grobid-crf-api-server",
    docker_image="grobid/grobid:0.8.2-crf",
    api_port=8070,
    security_group_name="grobid-crf-api-server-sg",
    security_group_description="Security group for GROBID CRF API server",
)

BASE_GROBID_FULL_DEPLOYMENT_CONFIG = GROBIDDeploymentConfig(
    instance_name="grobid-full-api-server",
    docker_image="grobid/grobid:0.8.2-full",
    api_port=8070,
    security_group_name="grobid-full-api-server-sg",
    security_group_description="Security group for GROBID Full API server",
)

SOFTWARE_MENTIONS_DEPLOYMENT_CONFIG = GROBIDDeploymentConfig(
    instance_name="grobid-software-mentions-api-server",
    docker_image="lfoppiano/software-mentions:0.8.2",
    api_port=8060,
    security_group_name="grobid-software-mentions-api-server-sg",
    security_group_description="Security group for GROBID Software Mentions API server",
)


class GROBIDDeploymentConfigs:
    grobid_crf = BASE_GROBID_CRF_DEPLOYMENT_CONFIG
    grobid_full = BASE_GROBID_FULL_DEPLOYMENT_CONFIG
    software_mentions = SOFTWARE_MENTIONS_DEPLOYMENT_CONFIG


#######################################################################################

log = logging.getLogger(__name__)

#######################################################################################


def get_default_vpc_id(ec2_client: EC2Client) -> str:
    """Get the default VPC ID for the region."""
    response = ec2_client.describe_vpcs(
        Filters=[{"Name": "isDefault", "Values": ["true"]}]
    )
    if not response["Vpcs"]:
        raise ValueError("No default VPC found in this region")
    return response["Vpcs"][0]["VpcId"]  # Return the first default VPC ID (if any)


def create_security_group(
    ec2_client: EC2Client,
    name: str,
    description: str,
) -> str:
    """Create a security group in the specified VPC."""
    try:
        response = ec2_client.create_security_group(
            GroupName=name,
            Description=description,
            VpcId=get_default_vpc_id(ec2_client),
        )
        return response["GroupId"]
    except ec2_client.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "InvalidGroup.Duplicate":
            # Get the ID of the existing security group
            response = ec2_client.describe_security_groups(GroupNames=[name])
            return response["SecurityGroups"][0]["GroupId"]
        else:
            raise e


def add_security_group_rules(
    ec2_client: EC2Client,
    security_group_id: str,
    api_port: int,
) -> None:
    """Add ingress rules to the security group."""
    try:
        ec2_client.authorize_security_group_ingress(
            GroupId=security_group_id,
            IpPermissions=[
                {
                    "IpProtocol": "tcp",
                    "FromPort": 22,
                    "ToPort": 22,
                    "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                },
                {
                    "IpProtocol": "tcp",
                    "FromPort": 443,
                    "ToPort": 443,
                    "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                },
                {
                    "IpProtocol": "tcp",
                    "FromPort": api_port,
                    "ToPort": api_port,
                    "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                },
            ],
        )
    except ec2_client.exceptions.ClientError as e:
        # Only raise the exception if it's not a duplicate permission error
        if e.response["Error"]["Code"] != "InvalidPermission.Duplicate":
            raise e


def get_image_default_snapshot_id(
    ec2_client: EC2Client,
    vm_image_id: str,
) -> str:
    """Get the default snapshot ID for the specified base image."""
    response = ec2_client.describe_images(ImageIds=[vm_image_id])
    if not response["Images"]:
        raise ValueError(f"No image found with ID {vm_image_id}")
    return response["Images"][0]["BlockDeviceMappings"][0]["Ebs"]["SnapshotId"]


@dataclass
class InstanceTypeDetails:
    primary_type: str
    attachments: str
    size: str


def _parse_instance_type(instance_type: str) -> InstanceTypeDetails:
    # Split instance type into
    # primary type (e.g. "M5")
    # attachments (e.g. "a", "g")
    # and size (e.g. "2xlarge")
    match = re.match(
        r"^([a-zA-Z]+)([0-9]{1})([a-zA-Z\-]*)\.([a-zA-Z0-9]+)$",
        instance_type,
    )

    # Primary type is groups 1 and 2
    # Attachments is group 3
    # Size is group 4
    if match:
        primary_type = match.group(1) + match.group(2)
        attachments = match.group(3)
        size = match.group(4)
        return InstanceTypeDetails(
            primary_type=primary_type, attachments=attachments, size=size
        )

    raise ValueError(f"Instance type {instance_type} does not match expected format")


def launch_instance(
    ec2_client: EC2Client,
    ec2_resource: EC2ServiceResource,
    region: str,
    security_group_id: str,
    instance_type: str,
    instance_name: str,
    storage_size: int,
    docker_image: str,
    api_port: int,
    startup_script_template_path: str,
    tags: list[str] | dict[str, str] | None = None,
) -> EC2Instance:
    """Launch an EC2 instance with the specified settings."""
    # Parse instance type
    instance_type_details = _parse_instance_type(instance_type)

    # Determine if NVIDIA GPU instance requested from primary family
    primary = instance_type_details.primary_type.lower()
    is_nvidia_gpu_instance = primary.startswith("g") or primary.startswith("p")
    if is_nvidia_gpu_instance:
        log.debug(f"Detected NVIDIA GPU instance type: {instance_type}")
        # Need to install nvidia-docker on the instance
        with open(NVIDIA_DOCKER_INSTALLATION_PATH) as open_f:
            nvidia_docker_installation = open_f.read()
        gpu_attach = "--gpus all --init --ulimit core=0"

        # Handle larger storage requirement
        if storage_size < 75:
            log.warning(
                "NVIDIA GPU instances require a minimum storage size of 75GB. "
                "Increasing storage size to meet requirement."
            )
            storage_size = 96

    else:
        log.debug(f"Detected non-NVIDIA-GPU instance type: {instance_type}")
        nvidia_docker_installation = ""
        gpu_attach = ""

    # Load the startup script template
    with open(startup_script_template_path) as f:
        startup_script_template = Template(f.read())

    # Render the startup script with the specified Docker image
    startup_script = startup_script_template.render(
        docker_image=docker_image,
        api_port=api_port,
        gpu_attach=gpu_attach,
        nvidia_docker_install=nvidia_docker_installation,
    )

    # Load the AMI data from the JSON file
    with open(UBUNTU_AMI_DATA_PATH) as f:
        ami_data = json.load(f)

    # Determine if we are looking for arm64 or x86_64/amd64 architecture
    # based on the instance type attachments ("g" suffix indicates Graviton/ARM)
    if "g" in instance_type_details.attachments:
        selected_arch = "arm64"
    else:
        selected_arch = "amd64"

    # Iter over ami data to find image id
    # for the specified region and architecture and gpu
    vm_image_id = ""
    for ami_piece in ami_data:
        if (
            ami_piece["region"] == region
            and ami_piece["arch"] == selected_arch
            and ami_piece["gpu"] == is_nvidia_gpu_instance
        ):
            vm_image_id = ami_piece["ami_id"]
            break

    # Handle not found
    if len(vm_image_id) == 0:
        raise ValueError(
            f"No AMI found for region {region}, "
            f"architecture {selected_arch}, "
            f"and GPU {is_nvidia_gpu_instance} combination"
        )

    # Parse tags
    if tags is None:
        tags = []
    if isinstance(tags, list):
        # Split each key-value pair into a new item in a dict
        parsed_tags = [
            {"Key": tag.split("=", 1)[0], "Value": tag.split("=", 1)[1]} for tag in tags
        ]
    elif isinstance(tags, dict):
        parsed_tags = [{"Key": k, "Value": v} for k, v in tags.items()]
    else:
        raise ValueError("Tags must be a list or dict")

    # Create the EC2 instance
    instances = ec2_resource.create_instances(
        ImageId=vm_image_id,
        InstanceType=instance_type,
        BlockDeviceMappings=[
            {
                "DeviceName": "/dev/sda1",
                "Ebs": {
                    "Encrypted": False,
                    "DeleteOnTermination": True,
                    "Iops": 3000,
                    "SnapshotId": get_image_default_snapshot_id(
                        ec2_client,
                        vm_image_id=vm_image_id,
                    ),
                    "VolumeSize": storage_size,
                    "VolumeType": "gp3",
                    "Throughput": 125,
                },
            }
        ],
        NetworkInterfaces=[
            {
                "AssociatePublicIpAddress": True,
                "DeviceIndex": 0,
                "Groups": [security_group_id],
            }
        ],
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [
                    {
                        "Key": "Name",
                        "Value": instance_name,
                    },
                    *parsed_tags,  # Unpack the tags list
                ],
            }
        ],
        MetadataOptions={
            "HttpEndpoint": "enabled",
            "HttpPutResponseHopLimit": 2,
            "HttpTokens": "required",
        },
        PrivateDnsNameOptions={
            "HostnameType": "ip-name",
            "EnableResourceNameDnsARecord": True,
            "EnableResourceNameDnsAAAARecord": False,
        },
        MinCount=1,
        MaxCount=1,
        UserData=startup_script,
    )

    return instances[0]


#######################################################################################


@dataclass
class EC2InstanceDetails:
    instance: EC2Instance
    region: str
    instance_id: str
    instance_type: str
    public_ip: str
    public_dns: str
    api_url: str


def launch_grobid_api_instance(
    region: str = "us-west-2",
    instance_type: str = "m6a.4xlarge",
    storage_size: int = 28,
    tags: list[str] | dict[str, str] | None = None,
    instance_name: str = "grobid-software-mentions-api-server",
    docker_image: str = "lfoppiano/software-mentions:0.8.2",
    api_port: int = 8060,
    security_group_name: str = "grobid-software-mentions-api-server-sg",
    security_group_description: str = (
        "Security group for GROBID Software Mentions API server"
    ),
    startup_script_template_path: str = str(DEFAULT_STARTUP_SCRIPT_TEMPLATE_PATH),
    profile_name: str | None = None,
) -> EC2InstanceDetails:
    """Launch a GROBID Software Mentions API EC2 instance."""
    # Always load the environment variables from the .env file
    # as they may contain AWS credentials
    load_dotenv()

    log.info(f"🔧 Setting up AWS session for region {region}")
    # Create boto3 clients and resources
    if profile_name:
        session = boto3.Session(profile_name=profile_name, region_name=region)
        log.info(f"   Using AWS profile: {profile_name}")
    else:
        session = boto3.Session(region_name=region)

    ec2_client = session.client("ec2")
    ec2_resource = session.resource("ec2")

    # Create security group
    log.info(f"🛡️  Creating security group: {security_group_name}")
    security_group_id = create_security_group(
        ec2_client=ec2_client,
        name=security_group_name,
        description=security_group_description,
    )
    log.info(f"   Security group created with ID: {security_group_id}")

    # Authorize security group ingress rules
    log.info(f"🔐 Configuring security group rules for ports 22, 443, and {api_port}")
    add_security_group_rules(
        ec2_client=ec2_client,
        security_group_id=security_group_id,
        api_port=api_port,
    )

    # Launch EC2 instance
    log.info(f"🚀 Launching EC2 instance {instance_name} ({instance_type})")
    log.info(f"   Docker image: {docker_image}")
    log.info(f"   Storage size: {storage_size} GiB")
    instance = launch_instance(
        ec2_client=ec2_client,
        ec2_resource=ec2_resource,
        region=region,
        security_group_id=security_group_id,
        instance_type=instance_type,
        instance_name=instance_name,
        storage_size=storage_size,
        docker_image=docker_image,
        api_port=api_port,
        startup_script_template_path=startup_script_template_path,
        tags=tags,
    )
    log.info(f"   Instance launch initiated: {instance.id}")
    log.info("⏳ Waiting for instance to enter 'running' state...")

    # Wait for the instance to be running
    instance.wait_until_running()

    # Reload the instance attributes
    instance.load()

    # Log the instance details
    log.info(f"✅ Instance {instance.id} is now running")
    log.info(f"   Public IP: {instance.public_ip_address}")
    log.info(f"   Public DNS: {instance.public_dns_name}")
    log.info(f"   API URL: http://{instance.public_ip_address}:{api_port}")

    return EC2InstanceDetails(
        instance=instance,
        region=region,
        instance_id=instance.id,
        instance_type=instance.instance_type,
        public_ip=instance.public_ip_address,
        public_dns=instance.public_dns_name,
        api_url=f"http://{instance.public_ip_address}:{api_port}",
    )


def terminate_instance(
    region: str,
    instance_id: str,
    profile_name: str | None = None,
) -> None:
    """Terminate the specified EC2 instance."""
    # Always load the environment variables from the .env file
    # as they may contain AWS credentials
    load_dotenv()

    log.info(f"🔧 Setting up AWS session for region {region}")
    if profile_name:
        session = boto3.Session(profile_name=profile_name, region_name=region)
        log.info(f"   Using AWS profile: {profile_name}")
    else:
        session = boto3.Session(region_name=region)

    ec2_client = session.client("ec2")
    log.info(f"🛑 Terminating instance {instance_id}...")
    ec2_client.terminate_instances(InstanceIds=[instance_id])
    log.info(f"✅ Instance {instance_id} termination initiated")


def wait_for_service_ready(
    docker_image: str,
    api_url: str,
    timeout: int = 420,  # 7 minutes
    interval: int = 10,
) -> None:
    """Wait for the GROBID API service to be ready."""
    # Determine API isalive URL by docker image name
    if "software-mentions" in docker_image:
        alive_url = f"{api_url}/service/isalive"
    else:
        alive_url = f"{api_url}/api/isalive"

    log.info(f"🔍 Waiting for GROBID service to become ready at {api_url}")
    log.info(f"   Health check endpoint: {alive_url}")
    log.info(f"   Timeout: {timeout} seconds, checking every {interval} seconds")

    start_time = time.time()
    attempts = 0
    while True:
        attempts += 1
        try:
            response = requests.get(alive_url, timeout=5)
            if response.status_code == 200:
                elapsed_time = int(time.time() - start_time)
                log.info(
                    f"✅ Service is ready! (took {elapsed_time}s, {attempts} attempts)"
                )
                return
        except requests.RequestException as e:
            elapsed_time = int(time.time() - start_time)
            log.info(
                f"   Attempt {attempts} ({elapsed_time}s elapsed): "
                f"Service not ready yet - {e}"
            )

        if time.time() - start_time > timeout:
            raise TimeoutError(f"Service did not become ready within {timeout} seconds")

        time.sleep(interval)


#######################################################################################


def deploy_and_wait_for_ready(
    grobid_config: GROBIDDeploymentConfig = GROBIDDeploymentConfigs.grobid_crf,
    instance_type: str = "m6a.4xlarge",
    storage_size: int = 28,
    region: str = "us-west-2",
    tags: list[str] | dict[str, str] | None = None,
    startup_script_template_path: str = str(DEFAULT_STARTUP_SCRIPT_TEMPLATE_PATH),
    timeout: int = 420,  # 7 minutes
    interval: int = 10,  # seconds
    profile_name: str | None = None,
) -> EC2InstanceDetails:
    """
    Deploy GROBID server and wait for it to be ready.

    Defaults to deploying the CRF-only model GROBID server.

    Parameters
    ----------
    grobid_config : GROBIDDeploymentConfig
        The deployment configuration to use.
    instance_type : str
        The AWS instance type to deploy.
    storage_size : int
        The size of the storage volume to attach to the instance
    region : str
        The AWS region to deploy the instance in.
    tags : list[str] | dict[str, str] | None
        Tags to apply to the instance.
    startup_script_template_path : str
        Path to the Jinja2 template file for the startup script.
    timeout : int
        The maximum time to wait for the service to be ready. Default: 7 minutes.
    interval : int
        The time to wait between checks for the service being ready.
    profile_name : str | None
        The AWS profile name to use for authentication.
    """
    log.info("🎯 Starting GROBID deployment process...")

    # Deploy
    instance_details = launch_grobid_api_instance(
        region=region,
        instance_type=instance_type,
        storage_size=storage_size,
        tags=tags,
        instance_name=grobid_config.instance_name,
        docker_image=grobid_config.docker_image,
        api_port=grobid_config.api_port,
        security_group_name=grobid_config.security_group_name,
        security_group_description=grobid_config.security_group_description,
        startup_script_template_path=startup_script_template_path,
        profile_name=profile_name,
    )

    log.info(
        "🐳 Instance is running, now waiting for Docker container "
        "to start and service to be ready..."
    )

    # Wait for the service to be ready
    try:
        wait_for_service_ready(
            docker_image=grobid_config.docker_image,
            api_url=instance_details.api_url,
            timeout=timeout,
            interval=interval,
        )
    except TimeoutError as e:
        log.error(f"❌ Service did not become ready: {e}")
        log.error(
            f"🧹 Cleaning up: terminating instance {instance_details.instance_id}",
        )
        terminate_instance(
            region=region,
            instance_id=instance_details.instance_id,
            profile_name=profile_name,
        )
        raise e

    # All clear!
    log.info(
        f"🎉 GROBID API is fully ready and accessible at {instance_details.api_url}"
    )
    return instance_details
