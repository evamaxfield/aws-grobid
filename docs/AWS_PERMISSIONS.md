# AWS Credentials and Permissions Guide

This guide outlines the AWS credentials and permissions required to use the `aws-grobid` tool for deploying GROBID on EC2 instances.

## Prerequisites

### 1. AWS Account
You need an active AWS account with appropriate permissions to create and manage EC2 instances.

### 2. AWS CLI Configuration
Configure your AWS credentials using one of the following methods:

#### Method A: AWS Profile (Recommended)
```bash
aws configure --profile your-profile-name
```
You'll be prompted for:
- AWS Access Key ID
- AWS Secret Access Key
- Default region name (e.g., `us-west-2`)
- Default output format (e.g., `json`)

#### Method B: Environment Variables
```bash
export AWS_ACCESS_KEY_ID=your_access_key
export AWS_SECRET_ACCESS_KEY=your_secret_key
export AWS_DEFAULT_REGION=us-west-2
```

#### Method C: AWS Credentials File
Create/edit `~/.aws/credentials`:
```ini
[your-profile-name]
aws_access_key_id = your_access_key
aws_secret_access_key = your_secret_key
```

Create/edit `~/.aws/config`:
```ini
[profile your-profile-name]
region = us-west-2
output = json
```

## Required IAM Permissions

The following IAM permissions are required for `aws-grobid` to function properly:

### Minimum Required Permissions
Create an IAM policy with the following permissions:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "ec2:DescribeVpcs",
                "ec2:DescribeSecurityGroups",
                "ec2:DescribeImages",
                "ec2:DescribeInstances",
                "ec2:DescribeSnapshots",
                "ec2:CreateSecurityGroup",
                "ec2:AuthorizeSecurityGroupIngress",
                "ec2:CreateTags",
                "ec2:RunInstances",
                "ec2:TerminateInstances",
                "ec2:CreateVolume",
                "ec2:DeleteVolume",
                "ec2:AttachVolume",
                "ec2:DescribeVolumes",
                "ec2:DescribeInstanceStatus",
                "ec2:DescribeInstanceAttribute",
                "ec2:DescribeInstanceTypes",
                "ec2:DescribeRegions",
                "ec2:DescribeAccountAttributes"
            ],
            "Resource": "*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "elasticloadbalancing:DescribeLoadBalancers",
                "elasticloadbalancing:DescribeTargetGroups"
            ],
            "Resource": "*"
        }
    ]
}
```

### AWS Managed Policy Alternative
For easier setup, you can use the AWS managed policy `AmazonEC2FullAccess`, though it provides more permissions than necessary:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": "ec2:*",
            "Resource": "*"
        }
    ]
}
```

## Recommended Best Practices

### 1. Use Least Privilege Principle
Only grant the permissions needed for the specific operations you'll perform.

### 2. Use IAM Roles for EC2 (Optional but Recommended)
For enhanced security, create an IAM role that EC2 instances can assume:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": "ec2.amazonaws.com"
            },
            "Action": "sts:AssumeRole"
        }
    ]
}
```

### 3. Resource Tagging
Consider adding resource tags to track costs and resources:
- `Project`: `grobid`
- `Owner`: `your-name`
- `Environment`: `development|production`

## Cost Considerations

### EC2 Instance Costs
- **t3.2xlarge**: ~$0.376/hour (us-west-2)
- **m6a.4xlarge**: ~$0.768/hour (us-west-2)
- GPU instances cost significantly more

### Additional Costs
- EBS storage: ~$0.08/GB-month for gp3
- Data transfer: ~$0.01/GB (first 100 GB/month free)
- Always terminate instances when not in use!

## Troubleshooting

### Common Permission Errors

#### 1. "UnauthorizedOperation" for EC2 actions
**Error**: `User is not authorized to perform: ec2:DescribeVpcs`
**Solution**: Add missing EC2 permissions to your IAM user/role.

#### 2. "InvalidGroup.Duplicate"
**Error**: Security group already exists
**Solution**: This is handled automatically by the tool.

#### 3. "InsufficientInstanceCapacity"
**Error**: No capacity available for instance type
**Solution**: Try a different instance type or region.

### Region-Specific Issues
Some instance types or AMIs may not be available in all regions. The default region is `us-west-2`, but you can specify a different region:

```bash
aws-grobid deploy --region us-east-1 --config crf
```

## Security Best Practices

### 1. Network Security
- The tool creates security groups that allow SSH (port 22), HTTPS (port 443), and the GROBID API port
- Consider restricting SSH access to specific IP ranges in production

### 2. Instance Security
- The deployed GROBID service will be publicly accessible
- Use IAM roles instead of access keys when possible
- Enable CloudTrail for audit logging

### 3. Cost Management
- Set up AWS Budgets to monitor spending
- Use AWS Cost Explorer to track EC2 costs
- Consider using AWS Savings Plans for predictable workloads

## Example IAM Policy Creation

### Using AWS Console
1. Go to IAM → Policies → Create policy
2. Switch to JSON tab
3. Paste the policy from the "Minimum Required Permissions" section
4. Name the policy (e.g., `GROBID-Deployment-Policy`)
5. Attach the policy to your IAM user or role

### Using AWS CLI
```bash
aws iam create-policy --policy-name GROBID-Deployment-Policy --policy-document file://policy.json
aws iam attach-user-policy --user-name your-username --policy-arn arn:aws:iam::ACCOUNT:policy/GROBID-Deployment-Policy
```

## Testing Your Configuration

### 1. Test AWS Credentials
```bash
aws sts get-caller-identity --profile your-profile-name
```

### 2. Test EC2 Permissions
```bash
aws ec2 describe-vpcs --profile your-profile-name
```

If these commands succeed, your credentials and permissions are properly configured.