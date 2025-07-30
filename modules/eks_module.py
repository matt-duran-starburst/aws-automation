"""
EKS cluster management module for the Platform CLI tool.
Handles EKS cluster creation, scaling, and lifecycle management.
"""

import click
import json
import os
import subprocess
import yaml
from datetime import datetime
import boto3
from botocore.exceptions import ClientError

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import PlatformConfig


def scale_eks_nodegroups(cluster_name, region, scale_to):
    """Scale EKS node groups up or down"""
    try:
        eks = boto3.client('eks', region_name=region)

        # Get all node groups for the cluster
        response = eks.list_nodegroups(clusterName=cluster_name)
        nodegroups = response['nodegroups']

        results = []
        for ng_name in nodegroups:
            try:
                if scale_to == 0:
                    # Scale down - set desired capacity to 0
                    eks.update_nodegroup_config(
                        clusterName=cluster_name,
                        nodegroupName=ng_name,
                        scalingConfig={
                            'desiredSize': 0
                        }
                    )
                    results.append(f"✅ Scaled down node group: {ng_name}")
                else:
                    # Scale up - get original desired capacity from tags or use 1
                    ng_response = eks.describe_nodegroup(
                        clusterName=cluster_name,
                        nodegroupName=ng_name
                    )

                    # Try to get original size from tags, default to 1
                    original_size = 1
                    if 'coordinator' in ng_name:
                        original_size = 1
                    elif 'worker' in ng_name:
                        original_size = 1  # Could be configurable
                    elif 'base' in ng_name:
                        original_size = 1

                    eks.update_nodegroup_config(
                        clusterName=cluster_name,
                        nodegroupName=ng_name,
                        scalingConfig={
                            'desiredSize': original_size
                        }
                    )
                    results.append(f"✅ Scaled up node group: {ng_name} to {original_size}")

            except Exception as e:
                results.append(f"❌ Error scaling {ng_name}: {e}")

        return results

    except Exception as e:
        raise Exception(f"Failed to scale node groups: {e}")


def run_eksctl_command(command, deployment_dir, config_file=None):
    """Run eksctl commands"""
    original_dir = os.getcwd()

    try:
        os.chdir(deployment_dir)

        if command == "create":
            cmd = ["eksctl", "create", "cluster", "-f", config_file]
        elif command == "delete":
            cmd = ["eksctl", "delete", "cluster", "-f", config_file]
        elif command == "get":
            cmd = ["eksctl", "get", "cluster"]
        else:
            raise ValueError(f"Unknown eksctl command: {command}")

        click.echo(f"🔄 Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return result.stdout

    except subprocess.CalledProcessError as e:
        click.echo(f"❌ eksctl {command} failed:")
        click.echo(e.stderr)
        raise click.Abort()
    finally:
        os.chdir(original_dir)


def generate_eksctl_config(deployment_id, owner, region, subnets, preset, expires_at, config):
    """Generate eksctl cluster configuration with length validation"""

    # Validate deployment_id length early
    if len(deployment_id) > 40:
        raise ValueError(f"Deployment ID too long ({len(deployment_id)} chars). Max 40 characters to avoid CloudFormation limits.")

    # Preset configurations
    presets = {
        "development": {
            "base_instances": ["m6g.xlarge", "m7g.xlarge"],
            "coordinator_instances": ["m6g.xlarge", "m7g.xlarge"],
            "worker_instances": ["m6g.xlarge", "m7g.xlarge"],
            "base_desired": 1,
            "coordinator_desired": 1,
            "worker_desired": 1,
            "worker_max": 2
        },
        "performance": {
            "base_instances": ["m6g.xlarge", "m7g.xlarge"],
            "coordinator_instances": ["m6g.2xlarge", "m7g.2xlarge"],
            "worker_instances": ["m6g.2xlarge", "m7g.2xlarge"],
            "base_desired": 1,
            "coordinator_desired": 1,
            "worker_desired": 2,
            "worker_max": 4
        },
        "demo": {
            "base_instances": ["t3.medium", "t3.large"],
            "coordinator_instances": ["t3.large", "t3.xlarge"],
            "worker_instances": ["t3.large", "t3.xlarge"],
            "base_desired": 1,
            "coordinator_desired": 1,
            "worker_desired": 1,
            "worker_max": 2
        }
    }

    preset_config = presets.get(preset, presets["development"])

    # Build subnet configuration
    vpc_subnets = {"private": {}}
    for subnet in subnets:
        if subnet['type'] == 'private':
            vpc_subnets["private"][subnet['az']] = {"id": subnet['id']}

    # Generate cluster tags from user config
    cluster_tags = dict(config.config.get("default_tags", {}))
    cluster_tags.update({
        "user": config.config.get("user_profile", {}).get("name", owner.split('@')[0]),
        "project": "platform-tool",
        "info": f"Platform tool deployment - {preset}",
        "expires": expires_at.isoformat(),
        "PlatformManaged": "true"
    })

    # Add user profile tags if available
    user_profile = config.config.get("user_profile", {})
    if user_profile.get("org"):
        cluster_tags["org"] = user_profile["org"]
    if user_profile.get("team"):
        cluster_tags["team"] = user_profile["team"]

    # Determine if we should use addon policies based on deployment_id length
    # If deployment_id is long, skip addon policies to avoid CloudFormation name length issues
    use_addon_policies = len(deployment_id) <= 30

    if not use_addon_policies:
        click.echo("⚠️  Skipping addon policies due to long cluster name to avoid CloudFormation limits")

    # Base IAM policies (always included)
    base_policy_arns = [
        "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
        "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
        "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
    ]

    # Generate eksctl config
    eksctl_config = {
        "apiVersion": "eksctl.io/v1alpha5",
        "kind": "ClusterConfig",
        "metadata": {
            "name": deployment_id,
            "region": region,
            "version": "1.30",
            "tags": cluster_tags
        },
        "vpc": {
            "subnets": vpc_subnets
        },
        "managedNodeGroups": []
    }

    # Create node group configurations
    node_groups = [
        {
            "name": f"{deployment_id}-base",
            "labels": {"apps": "base"},
            "instances": preset_config["base_instances"],
            "desired": preset_config["base_desired"],
            "max": 2
        },
        {
            "name": f"{deployment_id}-coord",  # Shortened from "coordinator"
            "labels": {"apps": "coordinator"},
            "instances": preset_config["coordinator_instances"],
            "desired": preset_config["coordinator_desired"],
            "max": 1
        },
        {
            "name": f"{deployment_id}-work",  # Shortened from "workers"
            "labels": {"apps": "workers"},
            "instances": preset_config["worker_instances"],
            "desired": preset_config["worker_desired"],
            "max": preset_config["worker_max"]
        }
    ]

    for ng_config in node_groups:
        node_group = {
            "name": ng_config["name"],
            "labels": ng_config["labels"],
            "tags": dict(cluster_tags),
            "availabilityZones": [list(vpc_subnets["private"].keys())[0]],
            "spot": True,
            "instanceTypes": ng_config["instances"],
            "desiredCapacity": ng_config["desired"],
            "minSize": 0,  # Allow scaling to 0
            "maxSize": ng_config["max"],
            "privateNetworking": True,
            "ssh": {
                "allow": True,
                "publicKeyName": config.config.get("default_key_name", "en-field-key")
            },
            "iam": {
                "attachPolicyARNs": base_policy_arns.copy()
            }
        }

        # Add addon policies only if deployment_id is short enough
        if use_addon_policies:
            node_group["iam"]["withAddonPolicies"] = {
                "autoScaler": True,
                "externalDNS": True,
                "certManager": True
            }

        eksctl_config["managedNodeGroups"].append(node_group)

    # Add custom IAM policy if account ID is available
    if config.config.get("aws_account_id"):
        custom_policy_arn = f"arn:aws:iam::{config.config['aws_account_id']}:policy/s3-eks-glue"
        for node_group in eksctl_config["managedNodeGroups"]:
            node_group["iam"]["attachPolicyARNs"].append(custom_policy_arn)

    return eksctl_config


def get_cluster_vpc_info(deployment_id, region):
    """Get VPC information for an existing EKS cluster"""
    try:
        # Use eksctl to get cluster information
        cmd = ["eksctl", "get", "cluster", "-n", deployment_id, "-r", region, "-o", "json"]
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        cluster_info = json.loads(result.stdout)

        # Extract VPC ID
        if not cluster_info or len(cluster_info) == 0:
            raise Exception("Could not get cluster information")

        vpc_id = cluster_info[0]["VPC"]["ID"]
        return vpc_id

    except subprocess.CalledProcessError as e:
        raise Exception(f"Error getting cluster information: {e.stderr}")
    except Exception as e:
        raise Exception(f"Error parsing cluster information: {str(e)}")


def update_kubeconfig(deployment_id, region):
    """Update kubeconfig for a deployment"""
    try:
        cmd = [
            "aws", "eks", "update-kubeconfig",
            "--region", region,
            "--name", deployment_id
        ]

        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return True, f"Kubeconfig updated for {deployment_id}"

    except subprocess.CalledProcessError as e:
        return False, f"Failed to update kubeconfig: {e}"