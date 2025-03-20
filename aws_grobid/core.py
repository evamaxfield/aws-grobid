#!/usr/bin/env python

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

import boto3
import boto3.session
import requests
from dataclasses_json import DataClassJsonMixin
from dotenv import load_dotenv
from jinja2 import Template

#######################################################################################

# Static files
STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_STARTUP_SCRIPT_TEMPLATE_PATH = STATIC_DIR / "startup-script.jinja"
NVIDIA_DOCKER_INSTALLATION_PATH = STATIC_DIR / "nvidia-docker-install.sh"
UBUNTU_AMI_DATA_PATH = STATIC_DIR / "ubuntu-amis.json"

GPU_INSTANCE_TYPES = [
    "P",
    "G",
    "Trn",
    "Inf",
    "DL",
    "F",
    "VT",
]

#######################################################################################

log = logging.getLogger(__name__)

#######################################################################################


def get_default_vpc_id(ec2_client: boto3.session.Session.client) -> str:
    """Get the default VPC ID for the region."""
    response = ec2_client.describe_vpcs(
        Filters=[{"Name": "isDefault", "Values": ["true"]}]
    )
    if not response["Vpcs"]:
        raise ValueError("No default VPC found in this region")
    return response["Vpcs"][0]["VpcId"]  # Return the first default VPC ID (if any)


def create_security_group(
    ec2_client: boto3.session.Session.client,
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
    ec2_client: boto3.session.Session.client,
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
    ec2_client: boto3.session.Session.client,
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
    ec2_client: boto3.session.Session.client,
    ec2_resource: boto3.session.Session.resource,
    region: str,
    security_group_id: str,
    instance_type: str,
    instance_name: str,
    storage_size: int,
    docker_image: str,
    api_port: int,
    startup_script_template_path: str,
) -> boto3.resources.factory.ec2.Instance:
    """Launch an EC2 instance with the specified settings."""
    # Parse instance type
    instance_type_details = _parse_instance_type(instance_type)

    # Determine if GPU instance requested from instance type
    is_gpu_instance = any(
        gpu.lower() in instance_type_details.primary_type.lower()
        for gpu in GPU_INSTANCE_TYPES
    )
    if is_gpu_instance:
        log.debug(f"Detected GPU instance type: {instance_type}")
        # Need to install nvidia-docker on the instance
        with open(NVIDIA_DOCKER_INSTALLATION_PATH) as open_f:
            nvidia_docker_installation = open_f.read()
        gpu_attach = "--gpus all --init --ulimit core=0"

        # Handle larger storage requirement
        if storage_size < 75:
            log.warning(
                "GPU instances require a minimum storage size of 75GB. "
                "Increasing storage size to meet requirement."
            )
            storage_size = 96

    else:
        log.debug(f"Detected non-GPU instance type: {instance_type}")
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

    print("\n" * 4)
    print(startup_script)
    print("\n" * 4)

    # Load the AMI data from the JSON file
    with open(UBUNTU_AMI_DATA_PATH) as f:
        ami_data = json.load(f)

    # Determine if we are looking for arm64 or x86_64/amd64 architecture
    # based on the instance type
    if "g" in instance_type_details.attachments:
        selected_arch = "arm64"
    else:
        selected_arch = "amd64"

    # Iter over ami data to find image id
    # for the specified region and architecture and gpu
    # example ami piece:
    vm_image_id = ""
    for ami_piece in ami_data:
        if (
            ami_piece["region"] == region
            and ami_piece["arch"] == selected_arch
            and ami_piece["gpu"] == is_gpu_instance
        ):
            vm_image_id = ami_piece["ami_id"]
            break

    # Handle not found
    if len(vm_image_id) == 0:
        raise ValueError(
            f"No AMI found for region {region}, "
            f"architecture {selected_arch}, "
            f"and GPU {is_gpu_instance} combination"
        )

    print("detected vm_image_id: ", vm_image_id)

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
class EC2InstanceDetails(DataClassJsonMixin):
    instance: boto3.session.Session.resource.Instance
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
    instance_name: str = "grobid-software-mentions-api-server",
    docker_image: str = "grobid/software-mentions:0.8.1",
    api_port: int = 8060,
    security_group_name: str = "grobid-software-mentions-api-server-sg",
    security_group_description: str = (
        "Security group for GROBID Software Mentions API server"
    ),
    startup_script_template_path: str = str(DEFAULT_STARTUP_SCRIPT_TEMPLATE_PATH),
) -> EC2InstanceDetails:
    """Launch a GROBID Software Mentions API EC2 instance."""
    # Always load the environment variables from the .env file
    # as they may contain AWS credentials
    load_dotenv()

    # Create boto3 clients and resources
    ec2_client = boto3.client("ec2", region_name=region)
    ec2_resource = boto3.resource("ec2", region_name=region)

    # Create security group
    log.debug("Creating security group...")
    security_group_id = create_security_group(
        ec2_client=ec2_client,
        name=security_group_name,
        description=security_group_description,
    )
    log.debug(f"Created security group: {security_group_id}")

    # Authorize security group ingress rules
    log.debug("Adding security group rules...")
    add_security_group_rules(
        ec2_client=ec2_client,
        security_group_id=security_group_id,
        api_port=api_port,
    )

    # Launch EC2 instance
    log.debug("Launching EC2 instance...")
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
    )
    log.debug(f"Instance {instance.id} is now launching")
    log.debug("Waiting for instance to be running...")

    # Wait for the instance to be running
    instance.wait_until_running()

    # Reload the instance attributes
    instance.load()

    # Log the instance details
    log.debug(f"Instance {instance.id} is now running")
    log.debug(f"Public IP address: {instance.public_ip_address}")
    log.debug(f"Public DNS: {instance.public_dns_name}")
    log.debug(f"Access your API at: http://{instance.public_ip_address}:{api_port}")

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
) -> None:
    """Terminate the specified EC2 instance."""
    # Always load the environment variables from the .env file
    # as they may contain AWS credentials
    load_dotenv()

    log.debug(f"Terminating instance {instance_id} in region {region}...")
    ec2_client = boto3.client("ec2", region_name=region)
    ec2_client.terminate_instances(InstanceIds=[instance_id])
    log.debug(f"Instance {instance_id} is now terminating")


def wait_for_service_ready(
    api_url: str,
    timeout: int = 420,  # 7 minutes
    interval: int = 10,
) -> None:
    """Wait for the GROBID API service to be ready."""
    log.debug(f"Waiting for service at {api_url} to be ready...")
    alive_url = f"{api_url}/service/isalive"
    start_time = time.time()
    while True:
        try:
            response = requests.get(alive_url)
            if response.status_code == 200:
                log.debug("Service is ready")
                return
        except requests.RequestException as e:
            log.debug(f"Service not ready yet: {e}")

        elapsed_time = time.time() - start_time
        if elapsed_time > timeout:
            raise TimeoutError(f"Service did not become ready within {timeout} seconds")

        time.sleep(interval)


#######################################################################################


def deploy_and_wait_for_ready(
    region: str = "us-west-2",
    instance_type: str = "m6a.4xlarge",
    storage_size: int = 28,
    instance_name: str = "grobid-software-mentions-api-server",
    docker_image: str = "grobid/software-mentions:0.8.1",
    api_port: int = 8060,
    security_group_name: str = "grobid-software-mentions-api-server-sg",
    security_group_description: str = (
        "Security group for GROBID Software Mentions API server"
    ),
    startup_script_template_path: str = str(DEFAULT_STARTUP_SCRIPT_TEMPLATE_PATH),
    timeout: int = 420,  # 7 minutes
    interval: int = 10,  # seconds
) -> EC2InstanceDetails:
    """Deploy GROBID Software Mentions API and wait for it to be ready."""
    # Deploy
    instance_details = launch_grobid_api_instance(
        region=region,
        instance_type=instance_type,
        storage_size=storage_size,
        instance_name=instance_name,
        docker_image=docker_image,
        api_port=api_port,
        security_group_name=security_group_name,
        security_group_description=security_group_description,
        startup_script_template_path=startup_script_template_path,
    )

    # Wait for the service to be ready
    try:
        wait_for_service_ready(
            api_url=instance_details.api_url,
            timeout=timeout,
            interval=interval,
        )
    except TimeoutError as e:
        log.error(f"Service did not become ready: {e}")
        terminate_instance(region=region, instance_id=instance_details.instance_id)
        raise e

    # All clear!
    log.info(f"GROBID API is ready at {instance_details.api_url}")
    return instance_details
