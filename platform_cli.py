#!/usr/bin/env python3
"""
Platform CLI Tool for AWS EKS/Starburst Deployments
MVP Version - EKS cluster creation with eksctl

Renamed from platform.py to platform_cli.py to avoid stdlib conflict
"""

import click
import json
import os
import subprocess
import uuid
import yaml
from datetime import datetime, timedelta
import boto3
from botocore.exceptions import NoCredentialsError

class PlatformConfig:
    """Handle platform configuration"""

    def __init__(self):
        self.config_path = CONFIG_FILE
        self.config = self.load_config()

    def load_config(self):
        if self.config_path.exists():
            with open(self.config_path, 'r') as f:
                return json.load(f)
        return DEFAULT_CONFIG

    def save_config(self):
        with open(self.config_path, 'w') as f:
            json.dump(self.config, f, indent=2)


def validate_aws_credentials():
    """Ensure AWS credentials are available and get account info"""
    try:
        session = boto3.Session()
        sts = session.client('sts')
        identity = sts.get_caller_identity()
        click.echo(f"✅ AWS credentials valid: {identity['Arn']}")

        # Update config with account ID
        config = PlatformConfig()
        config.config["aws_account_id"] = identity['Account']
        config.save_config()

        return identity
    except NoCredentialsError:
        click.echo("❌ No AWS credentials found.")
        click.echo()
        click.echo("💡 Solutions:")
        click.echo("   1. Set AWS profile: export AWS_PROFILE=your-profile-name")
        click.echo("   2. Or run: aws sso login --profile your-profile-name")
        click.echo("   3. Check available profiles: aws configure list-profiles")
        click.echo()

        # Try to show available profiles
        try:
            result = subprocess.run(['aws', 'configure', 'list-profiles'],
                                  capture_output=True, text=True, check=True)
            if result.stdout.strip():
                click.echo("Available profiles:")
                for profile in result.stdout.strip().split('\n'):
                    click.echo(f"   - {profile}")
                click.echo()
                click.echo("Set one with: export AWS_PROFILE=profile-name")
        except:
            pass

        raise click.Abort()
    except Exception as e:
        click.echo(f"❌ AWS credential error: {e}")

        # Check if it's a profile issue
        aws_profile = os.environ.get('AWS_PROFILE')
        if aws_profile:
            click.echo(f"Current AWS_PROFILE: {aws_profile}")
            click.echo("Try running: aws sts get-caller-identity")
        else:
            click.echo("No AWS_PROFILE set. Try: export AWS_PROFILE=your-profile-name")

        raise click.Abort()


def check_setup_required():
    """Check if initial setup is required"""
    config = PlatformConfig()
    if not config.config.get("setup_complete", False):
        click.echo("🔧 Initial setup required. Run 'platform setup' first.")
        raise click.Abort()
    return config


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


def get_vpc_subnets(region):
    """Get available VPC subnets for selection"""
    try:
        ec2 = boto3.client('ec2', region_name=region)
        response = ec2.describe_subnets()

        subnets = []
        for subnet in response['Subnets']:
            # Get subnet name from tags
            name = subnet['SubnetId']
            for tag in subnet.get('Tags', []):
                if tag['Key'] == 'Name':
                    name = tag['Value']
                    break

            subnets.append({
                'id': subnet['SubnetId'],
                'name': name,
                'vpc_id': subnet['VpcId'],
                'cidr': subnet['CidrBlock'],
                'az': subnet['AvailabilityZone'],
                'type': 'private' if not subnet['MapPublicIpOnLaunch'] else 'public'
            })

        return subnets
    except Exception as e:
        click.echo(f"❌ Error fetching subnets: {e}")
        return []


def parse_expiration(expires_in):
    """Parse expiration string like '3d', '1w', '2h' into datetime"""
    units = {
        'h': 'hours',
        'd': 'days',
        'w': 'weeks'
    }

    if expires_in[-1] not in units:
        raise click.BadParameter("Expiration must end with 'h', 'd', or 'w' (e.g., '3d', '1w')")

    try:
        value = int(expires_in[:-1])
        unit = units[expires_in[-1]]

        kwargs = {unit: value}
        return datetime.now() + timedelta(**kwargs)
    except ValueError:
        raise click.BadParameter(f"Invalid expiration format: {expires_in}")


def generate_deployment_id(name, owner):
    """Generate unique deployment ID"""
    timestamp = datetime.now().strftime("%Y-%m-%d")
    owner_clean = owner.split('@')[0].replace('.', '-')
    return f"{owner_clean}-{name}-{timestamp}"


def create_deployment_metadata(deployment_id, name, owner, purpose, expires_at, resource_type, region):
    """Create deployment metadata"""
    return {
        "deployment_id": deployment_id,
        "name": name,
        "owner": owner,
        "purpose": purpose,
        "created_at": datetime.now().isoformat(),
        "expires_at": expires_at.isoformat(),
        "resource_type": resource_type,
        "region": region,
        "status": "creating",
        "tags": {
            "Owner": owner,
            "Purpose": purpose,
            "AutoDestroy": expires_at.isoformat(),
            "PlatformManaged": "true",
            "CreatedBy": "platform-cli"
        }
    }


def run_eksctl_command(command, deployment_dir, config_file=None):
    """Run eksctl commands"""
    os.chdir(deployment_dir)

    if command == "create":
        cmd = ["eksctl", "create", "cluster", "-f", config_file]
    elif command == "delete":
        cmd = ["eksctl", "delete", "cluster", "-f", config_file]
    elif command == "get":
        cmd = ["eksctl", "get", "cluster"]
    else:
        raise ValueError(f"Unknown eksctl command: {command}")

    try:
        click.echo(f"🔄 Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        click.echo(f"❌ eksctl {command} failed:")
        click.echo(e.stderr)
        raise click.Abort()


def generate_eksctl_config(deployment_id, owner, region, subnets, preset, expires_at, config):
    """Generate eksctl cluster configuration"""

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
        "managedNodeGroups": [
            {
                "name": f"{deployment_id}-base",
                "labels": {"apps": "base"},
                "tags": dict(cluster_tags),
                "availabilityZones": [list(vpc_subnets["private"].keys())[0]],
                "spot": True,
                "instanceTypes": preset_config["base_instances"],
                "desiredCapacity": preset_config["base_desired"],
                "minSize": 0,  # Allow scaling to 0
                "maxSize": 2,
                "privateNetworking": True,
                "ssh": {
                    "allow": True,
                    "publicKeyName": config.config.get("default_key_name", "en-field-key")
                },
                "iam": {
                    "withAddonPolicies": {
                        "autoScaler": True,
                        "externalDNS": True,
                        "certManager": True
                    },
                    "attachPolicyARNs": [
                        "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
                        "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
                        "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
                    ]
                }
            },
            {
                "name": f"{deployment_id}-coordinator",
                "labels": {"apps": "coordinator"},
                "tags": dict(cluster_tags),
                "availabilityZones": [list(vpc_subnets["private"].keys())[0]],
                "spot": True,
                "instanceTypes": preset_config["coordinator_instances"],
                "desiredCapacity": preset_config["coordinator_desired"],
                "minSize": 0,  # Allow scaling to 0
                "maxSize": 1,
                "privateNetworking": True,
                "ssh": {
                    "allow": True,
                    "publicKeyName": config.config.get("default_key_name", "en-field-key")
                },
                "iam": {
                    "withAddonPolicies": {
                        "autoScaler": True,
                        "externalDNS": True,
                        "certManager": True
                    },
                    "attachPolicyARNs": [
                        "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
                        "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
                        "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
                    ]
                }
            },
            {
                "name": f"{deployment_id}-workers",
                "labels": {"apps": "workers"},
                "tags": dict(cluster_tags),
                "availabilityZones": [list(vpc_subnets["private"].keys())[0]],
                "spot": True,
                "instanceTypes": preset_config["worker_instances"],
                "desiredCapacity": preset_config["worker_desired"],
                "minSize": 0,  # Allow scaling to 0
                "maxSize": preset_config["worker_max"],
                "privateNetworking": True,
                "ssh": {
                    "allow": True,
                    "publicKeyName": config.config.get("default_key_name", "en-field-key")
                },
                "iam": {
                    "withAddonPolicies": {
                        "autoScaler": True,
                        "externalDNS": True,
                        "certManager": True
                    },
                    "attachPolicyARNs": [
                        "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
                        "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
                        "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
                    ]
                }
            }
        ]
    }

    # Add custom IAM policy if account ID is available
    if config.config.get("aws_account_id"):
        custom_policy_arn = f"arn:aws:iam::{config.config['aws_account_id']}:policy/s3-eks-glue"
        for node_group in eksctl_config["managedNodeGroups"]:
            node_group["iam"]["attachPolicyARNs"].append(custom_policy_arn)

    return eksctl_config


@click.group()
def cli():
    """Platform CLI for AWS EKS/Starburst deployments"""
    pass


@cli.group()
def create():
    """Create new deployments"""
    pass


@cli.command("setup")
def setup():
    """Initial platform setup - configure your profile and tags"""

    # Validate AWS credentials first
    validate_aws_credentials()

    config = PlatformConfig()

    click.echo("🔧 Platform Tool Initial Setup")
    click.echo("This will configure your profile and tagging information.")
    click.echo()

    # User profile information
    click.echo("👤 User Profile:")
    name = click.prompt("Your name (for tagging)",
                       default=config.config.get("user_profile", {}).get("name", ""))
    email = click.prompt("Your email address",
                        default=config.config.get("user_profile", {}).get("email", ""))

    # Organizational information
    click.echo("\n🏢 Organization Information:")
    org = click.prompt("Organization/Department (e.g., 'cs', 'sales', 'engineering')",
                      default=config.config.get("user_profile", {}).get("org", "cs"))
    team = click.prompt("Team (e.g., 'tse', 'tam', 'cse', 'sa')",
                       default=config.config.get("user_profile", {}).get("team", "tse"))

    # Environment and cloud settings
    click.echo("\n☁️ Default Settings:")
    environment = click.prompt("Default environment",
                              default=config.config.get("default_tags", {}).get("environment", "demo"))
    region = click.prompt("Default AWS region",
                         default=config.config.get("default_region", "us-east-1"))
    key_name = click.prompt("Default SSH key name",
                           default=config.config.get("default_key_name", "en-field-key"))

    # Update configuration
    config.config.update({
        "default_region": region,
        "default_key_name": key_name,
        "user_profile": {
            "name": name,
            "email": email,
            "org": org,
            "team": team
        },
        "default_tags": {
            "cloud": "aws",
            "environment": environment,
            "org": org,
            "team": team
        },
        "setup_complete": True
    })

    config.save_config()

    click.echo("\n✅ Setup completed!")
    click.echo("\n📋 Your configuration:")
    click.echo(f"   Name: {name}")
    click.echo(f"   Email: {email}")
    click.echo(f"   Organization: {org}")
    click.echo(f"   Team: {team}")
    click.echo(f"   Environment: {environment}")
    click.echo(f"   Default Region: {region}")
    click.echo(f"   SSH Key: {key_name}")
    click.echo()
    click.echo("These tags will be automatically applied to all resources you create.")
    click.echo("You can modify them anytime with 'platform config --help'")


@create.command("eks-cluster")
@click.option("--name", required=True, help="Cluster name")
@click.option("--owner", help="Owner email address (defaults to your configured email)")
@click.option("--purpose", default="testing", help="Purpose of deployment")
@click.option("--expires-in", default="7d", help="Expiration time (e.g., '3d', '1w', '2h')")
@click.option("--region", help="AWS region (defaults to config)")
@click.option("--preset", default="development",
              type=click.Choice(['development', 'performance', 'demo']),
              help="Cluster preset configuration")
@click.option("--eksctl-config", help="Path to existing eksctl config file")
@click.option("--auto-select-subnets", is_flag=True, help="Automatically select first available private subnets")
def create_eks_cluster(name, owner, purpose, expires_in, region, preset, eksctl_config, auto_select_subnets):
    """Create a new EKS cluster using eksctl"""

    # Check if setup is complete
    config = check_setup_required()

    # Validate AWS credentials
    identity = validate_aws_credentials()

    # Use configured email if owner not provided
    if not owner:
        owner = config.config.get("user_profile", {}).get("email")
        if not owner:
            click.echo("❌ No owner email specified and none configured. Run 'platform setup' or provide --owner")
            raise click.Abort()

    # Parse expiration
    expires_at = parse_expiration(expires_in)

    # Use configured region if not provided
    if not region:
        region = config.config["default_region"]

    # Generate deployment ID
    deployment_id = generate_deployment_id(name, owner)
    deployment_dir = DEPLOYMENTS_DIR / deployment_id

    click.echo(f"🚀 Creating EKS cluster: {deployment_id}")
    click.echo(f"📅 Expires: {expires_at.strftime('%Y-%m-%d %H:%M:%S')}")
    click.echo(f"🌍 Region: {region}")
    click.echo(f"⚙️  Preset: {preset}")
    click.echo(f"👤 Owner: {owner}")

    # Create deployment directory
    deployment_dir.mkdir(exist_ok=True)

    # Handle eksctl configuration
    if eksctl_config:
        # Use provided eksctl config
        click.echo(f"📋 Using provided eksctl config: {eksctl_config}")
        import shutil
        shutil.copy(eksctl_config, deployment_dir / "cluster.yaml")
        eksctl_config_path = "cluster.yaml"
    else:
        # Generate eksctl config
        click.echo("🔍 Fetching available subnets...")
        subnets = get_vpc_subnets(region)

        if not subnets:
            click.echo("❌ No subnets found in region")
            raise click.Abort()

        # Filter private subnets
        private_subnets = [s for s in subnets if s['type'] == 'private']

        if not private_subnets:
            click.echo("❌ No private subnets found")
            raise click.Abort()

        if auto_select_subnets:
            # Auto-select private subnets from the same VPC with different AZs
            # Group subnets by VPC
            vpcs = {}
            for subnet in private_subnets:
                vpc_id = subnet['vpc_id']
                if vpc_id not in vpcs:
                    vpcs[vpc_id] = []
                vpcs[vpc_id].append(subnet)

            # Find the VPC with the most subnets
            best_vpc = max(vpcs.keys(), key=lambda vpc: len(vpcs[vpc]))
            vpc_subnets = vpcs[best_vpc]

            # Select subnets from different AZs within the same VPC
            selected_subnets = []
            used_azs = set()
            for subnet in vpc_subnets:
                if subnet['az'] not in used_azs and len(selected_subnets) < 3:
                    selected_subnets.append(subnet)
                    used_azs.add(subnet['az'])

            if len(selected_subnets) < 2:
                click.echo(f"❌ Need at least 2 subnets in different AZs. Found {len(selected_subnets)} in VPC {best_vpc}")
                raise click.Abort()

            click.echo(f"✅ Auto-selected {len(selected_subnets)} subnets from VPC {best_vpc}")
            for subnet in selected_subnets:
                click.echo(f"   - {subnet['name']} ({subnet['id']}) in {subnet['az']}")

        else:
            # Interactive subnet selection - group by VPC for better UX
            vpcs = {}
            for subnet in private_subnets:
                vpc_id = subnet['vpc_id']
                if vpc_id not in vpcs:
                    vpcs[vpc_id] = []
                vpcs[vpc_id].append(subnet)

            # Show subnets grouped by VPC
            click.echo("\n📋 Available private subnets grouped by VPC:")
            subnet_choices = []
            choice_index = 1

            for vpc_id, vpc_subnets in vpcs.items():
                click.echo(f"\n  VPC: {vpc_id}")
                for subnet in vpc_subnets:
                    click.echo(f"    {choice_index}. {subnet['name']} ({subnet['id']}) - {subnet['az']} - {subnet['cidr']}")
                    subnet_choices.append(subnet)
                    choice_index += 1

            click.echo("\n⚠️  Important: All selected subnets must be from the same VPC!")

            selected_indices = click.prompt(
                "Select subnets (comma-separated numbers, e.g., 1,2,3)",
                type=str
            )

            try:
                indices = [int(x.strip()) - 1 for x in selected_indices.split(',')]
                selected_subnets = [subnet_choices[i] for i in indices]

                # Validate all subnets are from the same VPC
                vpc_ids = set(subnet['vpc_id'] for subnet in selected_subnets)
                if len(vpc_ids) > 1:
                    click.echo(f"❌ Selected subnets are from different VPCs: {vpc_ids}")
                    click.echo("Please select subnets from the same VPC only.")
                    raise click.Abort()

                # Validate we have subnets in different AZs
                azs = set(subnet['az'] for subnet in selected_subnets)
                if len(azs) < 2:
                    click.echo("❌ Need subnets in at least 2 different availability zones")
                    raise click.Abort()

            except (ValueError, IndexError):
                click.echo("❌ Invalid subnet selection")
                raise click.Abort()

        click.echo(f"✅ Selected {len(selected_subnets)} subnets")

        # Generate eksctl config
        eksctl_config_data = generate_eksctl_config(
            deployment_id, owner, region, selected_subnets, preset, expires_at, config
        )

        # Save eksctl config
        eksctl_config_path = deployment_dir / "cluster.yaml"
        with open(eksctl_config_path, 'w') as f:
            yaml.dump(eksctl_config_data, f, default_flow_style=False)

        eksctl_config_path = "cluster.yaml"

        click.echo(f"📝 Generated eksctl config: {deployment_dir / 'cluster.yaml'}")

    # Create metadata
    metadata = create_deployment_metadata(
        deployment_id, name, owner, purpose, expires_at, "eks-cluster", region
    )
    metadata["eksctl_config"] = eksctl_config_path
    metadata["preset"] = preset
    metadata["is_running"] = False  # Track if cluster is running or stopped

    # Save metadata
    with open(deployment_dir / "metadata.json", 'w') as f:
        json.dump(metadata, f, indent=2)

    # Show config preview
    click.echo("\n📋 Cluster configuration preview:")
    with open(deployment_dir / eksctl_config_path, 'r') as f:
        config_preview = f.read()
        # Show first 20 lines
        lines = config_preview.split('\n')[:20]
        click.echo('\n'.join(lines))
        if len(config_preview.split('\n')) > 20:
            click.echo("...")

    if click.confirm("\nProceed with cluster creation?"):
        click.echo("🚀 Creating EKS cluster (this may take 10-15 minutes)...")

        try:
            output = run_eksctl_command("create", deployment_dir, eksctl_config_path)
            click.echo(output)

            # Update metadata
            metadata["status"] = "running"
            metadata["is_running"] = True
            metadata["created_date"] = datetime.now().isoformat()

            with open(deployment_dir / "metadata.json", 'w') as f:
                json.dump(metadata, f, indent=2)

            click.echo("✅ EKS cluster created successfully!")
            click.echo(f"📁 Deployment directory: {deployment_dir}")
            click.echo(f"🎯 Update kubeconfig: aws eks update-kubeconfig --region {region} --name {deployment_id}")
            click.echo(f"🔍 View in K9s: k9s --context {deployment_id}")
            click.echo()
            click.echo("💡 Tip: Use 'platform stop {deployment_id}' to scale down when not in use")

        except Exception as e:
            # Update metadata with error
            metadata["status"] = "failed"
            metadata["error"] = str(e)

            with open(deployment_dir / "metadata.json", 'w') as f:
                json.dump(metadata, f, indent=2)

            click.echo("❌ Cluster creation failed")
            raise
    else:
        click.echo("❌ Cluster creation cancelled")


@cli.command("start")
@click.argument("deployment_id")
@click.option("--force", is_flag=True, help="Skip confirmation")
def start_deployment(deployment_id, force):
    """Start/scale up a deployment"""

    deployment_dir = DEPLOYMENTS_DIR / deployment_id
    metadata_file = deployment_dir / "metadata.json"

    if not metadata_file.exists():
        click.echo(f"❌ Deployment not found: {deployment_id}")
        raise click.Abort()

    with open(metadata_file, 'r') as f:
        metadata = json.load(f)

    if metadata["status"] != "running":
        click.echo(f"❌ Cannot start deployment with status: {metadata['status']}")
        raise click.Abort()

    if metadata.get("is_running", True):
        click.echo(f"✅ Deployment {deployment_id} is already running")
        return

    click.echo(f"🚀 Starting deployment: {deployment_id}")
    click.echo(f"   Owner: {metadata['owner']}")
    click.echo(f"   Type: {metadata['resource_type']}")
    click.echo(f"   Region: {metadata['region']}")

    if not force and not click.confirm("Start this deployment?"):
        click.echo("❌ Start cancelled")
        return

    try:
        if metadata["resource_type"] == "eks-cluster":
            click.echo("🔄 Scaling up EKS node groups...")
            results = scale_eks_nodegroups(deployment_id, metadata["region"], scale_to=1)

            for result in results:
                click.echo(f"   {result}")

            # Update metadata
            metadata["is_running"] = True
            metadata["last_started"] = datetime.now().isoformat()

            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)

            click.echo("✅ Deployment started successfully!")
            click.echo("⏳ Node groups are scaling up (may take 2-3 minutes)")
            click.echo(f"🎯 Update kubeconfig: platform update-kubeconfig {deployment_id}")

        else:
            click.echo(f"❌ Start operation not supported for resource type: {metadata['resource_type']}")

    except Exception as e:
        click.echo(f"❌ Failed to start deployment: {e}")
        raise click.Abort()


@cli.command("stop")
@click.argument("deployment_id")
@click.option("--force", is_flag=True, help="Skip confirmation")
def stop_deployment(deployment_id, force):
    """Stop/scale down a deployment to save costs"""

    deployment_dir = DEPLOYMENTS_DIR / deployment_id
    metadata_file = deployment_dir / "metadata.json"

    if not metadata_file.exists():
        click.echo(f"❌ Deployment not found: {deployment_id}")
        raise click.Abort()

    with open(metadata_file, 'r') as f:
        metadata = json.load(f)

    if metadata["status"] != "running":
        click.echo(f"❌ Cannot stop deployment with status: {metadata['status']}")
        raise click.Abort()

    if not metadata.get("is_running", True):
        click.echo(f"✅ Deployment {deployment_id} is already stopped")
        return

    click.echo(f"⏸️  Stopping deployment: {deployment_id}")
    click.echo(f"   Owner: {metadata['owner']}")
    click.echo(f"   Type: {metadata['resource_type']}")
    click.echo(f"   Region: {metadata['region']}")
    click.echo()
    click.echo("This will scale node groups to 0 to save costs.")
    click.echo("The cluster control plane will remain active.")
    click.echo("Use 'platform start' to scale back up.")

    if not force and not click.confirm("Stop this deployment?"):
        click.echo("❌ Stop cancelled")
        return

    try:
        if metadata["resource_type"] == "eks-cluster":
            click.echo("🔄 Scaling down EKS node groups to 0...")
            results = scale_eks_nodegroups(deployment_id, metadata["region"], scale_to=0)

            for result in results:
                click.echo(f"   {result}")

            # Update metadata
            metadata["is_running"] = False
            metadata["last_stopped"] = datetime.now().isoformat()

            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)

            click.echo("✅ Deployment stopped successfully!")
            click.echo("💰 Node costs reduced to $0 while stopped")
            click.echo(f"🚀 Restart with: platform start {deployment_id}")

        else:
            click.echo(f"❌ Stop operation not supported for resource type: {metadata['resource_type']}")

    except Exception as e:
        click.echo(f"❌ Failed to stop deployment: {e}")
        raise click.Abort()


@cli.command("list")
@click.option("--owner", help="Filter by owner")
@click.option("--expiring-soon", is_flag=True, help="Show deployments expiring in 24 hours")
@click.option("--status", help="Filter by status (creating, running, failed)")
@click.option("--running", is_flag=True, help="Show only running (scaled up) deployments")
@click.option("--stopped", is_flag=True, help="Show only stopped (scaled down) deployments")
def list_deployments(owner, expiring_soon, status, running, stopped):
    """List active deployments"""

    deployments = []

    for deployment_dir in DEPLOYMENTS_DIR.iterdir():
        if deployment_dir.is_dir():
            metadata_file = deployment_dir / "metadata.json"
            if metadata_file.exists():
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)

                # Apply filters
                if owner and metadata["owner"] != owner:
                    continue

                if status and metadata["status"] != status:
                    continue

                if running and not metadata.get("is_running", True):
                    continue

                if stopped and metadata.get("is_running", True):
                    continue

                if expiring_soon:
                    expires_at = datetime.fromisoformat(metadata["expires_at"])
                    hours_until_expiry = (expires_at - datetime.now()).total_seconds() / 3600
                    if hours_until_expiry > 24:
                        continue

                deployments.append(metadata)

    if not deployments:
        click.echo("No deployments found")
        return

    click.echo("📋 Active Deployments:")
    for deployment in sorted(deployments, key=lambda x: x["created_at"]):
        expires_at = datetime.fromisoformat(deployment["expires_at"])
        time_left = expires_at - datetime.now()

        status_icons = {
            "creating": "🔄",
            "running": "✅",
            "failed": "❌",
            "destroyed": "🗑️"
        }
        status_icon = status_icons.get(deployment["status"], "❓")

        # Add running/stopped indicator
        is_running = deployment.get("is_running", True)
        running_status = "🟢 Running" if is_running else "⏸️  Stopped"

        click.echo(f"{status_icon} {deployment['deployment_id']} ({running_status})")
        click.echo(f"   Owner: {deployment['owner']}")
        click.echo(f"   Purpose: {deployment['purpose']}")
        click.echo(f"   Region: {deployment['region']}")
        click.echo(f"   Status: {deployment['status']}")
        if deployment.get("preset"):
            click.echo(f"   Preset: {deployment['preset']}")
        click.echo(f"   Expires in: {time_left}")

        # Show cost savings for stopped deployments
        if not is_running and deployment["status"] == "running":
            click.echo("   💰 Costs reduced while stopped")

        click.echo()


@cli.command("destroy")
@click.argument("deployment_id")
@click.option("--force", is_flag=True, help="Skip confirmation")
def destroy_deployment(deployment_id, force):
    """Destroy a deployment"""

    deployment_dir = DEPLOYMENTS_DIR / deployment_id

    if not deployment_dir.exists():
        click.echo(f"❌ Deployment not found: {deployment_id}")
        raise click.Abort()

    # Load metadata
    metadata_file = deployment_dir / "metadata.json"
    if not metadata_file.exists():
        click.echo(f"❌ Metadata not found for deployment: {deployment_id}")
        raise click.Abort()

    with open(metadata_file, 'r') as f:
        metadata = json.load(f)

    click.echo(f"🗑️  Destroying deployment: {deployment_id}")
    click.echo(f"   Owner: {metadata['owner']}")
    click.echo(f"   Created: {metadata['created_at']}")
    click.echo(f"   Type: {metadata['resource_type']}")

    if not force and not click.confirm("Are you sure you want to destroy this deployment?"):
        click.echo("❌ Destruction cancelled")
        return

    # Run eksctl delete
    eksctl_config = metadata.get("eksctl_config", "cluster.yaml")
    click.echo("🏗️  Destroying EKS cluster (this may take 10-15 minutes)...")

    try:
        run_eksctl_command("delete", deployment_dir, eksctl_config)

        # Update metadata
        metadata["status"] = "destroyed"
        metadata["destroyed_at"] = datetime.now().isoformat()

        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        click.echo(f"✅ Deployment {deployment_id} destroyed successfully")

    except Exception as e:
        click.echo(f"❌ Destruction failed: {e}")
        # Don't update metadata on failure so user can retry
        raise


@cli.command("extend")
@click.argument("deployment_id")
@click.option("--expires-in", required=True, help="New expiration time (e.g., '3d', '1w')")
def extend_deployment(deployment_id, expires_in):
    """Extend deployment expiration"""

    deployment_dir = DEPLOYMENTS_DIR / deployment_id
    metadata_file = deployment_dir / "metadata.json"

    if not metadata_file.exists():
        click.echo(f"❌ Deployment not found: {deployment_id}")
        raise click.Abort()

    # Parse new expiration
    new_expires_at = parse_expiration(expires_in)

    # Load and update metadata
    with open(metadata_file, 'r') as f:
        metadata = json.load(f)

    old_expires = metadata["expires_at"]
    metadata["expires_at"] = new_expires_at.isoformat()
    metadata["extended_at"] = datetime.now().isoformat()

    # Update tags
    metadata["tags"]["AutoDestroy"] = new_expires_at.isoformat()

    with open(metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2)

    click.echo(f"✅ Extended {deployment_id}")
    click.echo(f"   Old expiration: {old_expires}")
    click.echo(f"   New expiration: {new_expires_at.isoformat()}")


@cli.command("config")
@click.option("--set-region", help="Set default AWS region")
@click.option("--set-expiration", help="Set default expiration time")
@click.option("--set-key-name", help="Set default SSH key name")
@click.option("--set-name", help="Set your name")
@click.option("--set-email", help="Set your email")
@click.option("--set-org", help="Set your organization")
@click.option("--set-team", help="Set your team")
@click.option("--set-environment", help="Set default environment")
@click.option("--reset", is_flag=True, help="Reset configuration and run setup again")
def configure(set_region, set_expiration, set_key_name, set_name, set_email,
              set_org, set_team, set_environment, reset):
    """Configure platform settings"""

    config = PlatformConfig()

    if reset:
        if click.confirm("Are you sure you want to reset all configuration?"):
            config.config = {
                "default_region": "us-east-1",
                "default_expiration": "7d",
                "aws_account_id": config.config.get("aws_account_id"),  # Keep AWS account ID
                "default_key_name": "en-field-key",
                "user_profile": {
                    "name": None,
                    "email": None,
                    "org": None,
                    "team": None
                },
                "default_tags": {
                    "cloud": "aws",
                    "environment": "demo"
                },
                "setup_complete": False
            }
            config.save_config()
            click.echo("✅ Configuration reset. Run 'platform setup' to reconfigure.")
        return

    # Update individual settings
    if set_region:
        config.config["default_region"] = set_region
        click.echo(f"✅ Default region set to: {set_region}")

    if set_expiration:
        # Validate expiration format
        try:
            parse_expiration(set_expiration)
            config.config["default_expiration"] = set_expiration
            click.echo(f"✅ Default expiration set to: {set_expiration}")
        except click.BadParameter as e:
            click.echo(f"❌ {e}")
            raise click.Abort()

    if set_key_name:
        config.config["default_key_name"] = set_key_name
        click.echo(f"✅ Default SSH key name set to: {set_key_name}")

    if set_name:
        config.config.setdefault("user_profile", {})["name"] = set_name
        click.echo(f"✅ Name set to: {set_name}")

    if set_email:
        config.config.setdefault("user_profile", {})["email"] = set_email
        click.echo(f"✅ Email set to: {set_email}")

    if set_org:
        config.config.setdefault("user_profile", {})["org"] = set_org
        config.config.setdefault("default_tags", {})["org"] = set_org
        click.echo(f"✅ Organization set to: {set_org}")

    if set_team:
        config.config.setdefault("user_profile", {})["team"] = set_team
        config.config.setdefault("default_tags", {})["team"] = set_team
        click.echo(f"✅ Team set to: {set_team}")

    if set_environment:
        config.config.setdefault("default_tags", {})["environment"] = set_environment
        click.echo(f"✅ Environment set to: {set_environment}")

    # Save changes
    if any([set_region, set_expiration, set_key_name, set_name, set_email,
            set_org, set_team, set_environment]):
        config.save_config()
    else:
        # Show current config
        click.echo("📋 Current Configuration:")
        click.echo()

        # Setup status
        setup_complete = config.config.get("setup_complete", False)
        click.echo(f"Setup Complete: {'✅ Yes' if setup_complete else '❌ No (run platform setup)'}")
        click.echo()

        # User Profile
        user_profile = config.config.get("user_profile", {})
        click.echo("👤 User Profile:")
        click.echo(f"   Name: {user_profile.get('name', 'Not set')}")
        click.echo(f"   Email: {user_profile.get('email', 'Not set')}")
        click.echo(f"   Organization: {user_profile.get('org', 'Not set')}")
        click.echo(f"   Team: {user_profile.get('team', 'Not set')}")
        click.echo()

        # Default Settings
        click.echo("⚙️  Default Settings:")
        click.echo(f"   Region: {config.config.get('default_region', 'Not set')}")
        click.echo(f"   Expiration: {config.config.get('default_expiration', 'Not set')}")
        click.echo(f"   SSH Key: {config.config.get('default_key_name', 'Not set')}")
        click.echo()

        # Default Tags
        default_tags = config.config.get("default_tags", {})
        click.echo("🏷️  Default Tags:")
        for key, value in default_tags.items():
            click.echo(f"   {key}: {value}")
        click.echo()

        # AWS Info
        click.echo("☁️  AWS Info:")
        click.echo(f"   Account ID: {config.config.get('aws_account_id', 'Not detected')}")

        if not setup_complete:
            click.echo()
            click.echo("💡 Run 'platform setup' to complete initial configuration")


@cli.command("update-kubeconfig")
@click.argument("deployment_id")
def update_kubeconfig(deployment_id):
    """Update kubeconfig for a deployment"""

    deployment_dir = DEPLOYMENTS_DIR / deployment_id
    metadata_file = deployment_dir / "metadata.json"

    if not metadata_file.exists():
        click.echo(f"❌ Deployment not found: {deployment_id}")
        raise click.Abort()

    with open(metadata_file, 'r') as f:
        metadata = json.load(f)

    region = metadata["region"]

    try:
        cmd = [
            "aws", "eks", "update-kubeconfig",
            "--region", region,
            "--name", deployment_id
        ]

        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        click.echo(f"✅ Kubeconfig updated for {deployment_id}")
        click.echo(f"🎯 Access with K9s: k9s --context {deployment_id}")

    except subprocess.CalledProcessError as e:
        click.echo(f"❌ Failed to update kubeconfig: {e}")
        raise click.Abort()


def create_postgres_rds(name, vpc_id, subnets, region, user, password, db_name=None, instance_type='db.t3.micro', allocated_storage=20, backup_retention=7, deployment_id=None):
    """Create a PostgreSQL RDS database instance in the specified VPC"""
    try:
        click.echo(f"🔄 Creating PostgreSQL RDS instance: {name}...")

        # Create an RDS client
        rds = boto3.client('rds', region_name=region)

        # Create a security group for the RDS instance
        ec2 = boto3.client('ec2', region_name=region)

        # Create a security group for RDS
        sg_name = f"{name}-rds-sg"
        sg_desc = f"Security group for RDS database {name}"

        click.echo(f"📊 Creating security group: {sg_name}")
        sg_response = ec2.create_security_group(
            GroupName=sg_name,
            Description=sg_desc,
            VpcId=vpc_id
        )
        sg_id = sg_response['GroupId']

        # Tag the security group
        ec2.create_tags(
            Resources=[sg_id],
            Tags=[
                {'Key': 'Name', 'Value': sg_name},
                {'Key': 'PlatformManaged', 'Value': 'true'},
                {'Key': 'DeploymentId', 'Value': deployment_id or name}
            ]
        )

        # Allow PostgreSQL traffic from the VPC CIDR
        vpc_response = ec2.describe_vpcs(VpcIds=[vpc_id])
        vpc_cidr = vpc_response['Vpcs'][0]['CidrBlock']

        ec2.authorize_security_group_ingress(
            GroupId=sg_id,
            IpPermissions=[
                {
                    'IpProtocol': 'tcp',
                    'FromPort': 5432,
                    'ToPort': 5432,
                    'IpRanges': [{'CidrIp': vpc_cidr}]
                }
            ]
        )

        # Get subnet IDs
        subnet_ids = [subnet['id'] for subnet in subnets]

        # Create subnet group for RDS
        db_subnet_group_name = f"{name}-subnet-group"
        click.echo(f"📊 Creating DB subnet group: {db_subnet_group_name}")

        rds.create_db_subnet_group(
            DBSubnetGroupName=db_subnet_group_name,
            DBSubnetGroupDescription=f"Subnet group for {name}",
            SubnetIds=subnet_ids,
            Tags=[
                {'Key': 'Name', 'Value': db_subnet_group_name},
                {'Key': 'PlatformManaged', 'Value': 'true'},
                {'Key': 'DeploymentId', 'Value': deployment_id or name}
            ]
        )

        # Set default DB name if not specified
        if not db_name:
            db_name = "postgres"

        # Create the RDS instance
        click.echo(f"🚀 Launching RDS instance: {name} ({instance_type}, {allocated_storage}GB)")

        response = rds.create_db_instance(
            DBName=db_name,
            DBInstanceIdentifier=name,
            AllocatedStorage=allocated_storage,
            DBInstanceClass=instance_type,
            Engine='postgres',
            MasterUsername=user,
            MasterUserPassword=password,
            VpcSecurityGroupIds=[sg_id],
            DBSubnetGroupName=db_subnet_group_name,
            BackupRetentionPeriod=backup_retention,
            MultiAZ=False,
            AutoMinorVersionUpgrade=True,
            PubliclyAccessible=False,
            Tags=[
                {'Key': 'Name', 'Value': name},
                {'Key': 'PlatformManaged', 'Value': 'true'},
                {'Key': 'DeploymentId', 'Value': deployment_id or name}
            ]
        )

        click.echo(f"✅ RDS instance creation initiated. This may take 5-10 minutes to complete.")
        click.echo(f"📊 Database endpoint will be available when the instance is ready.")

        return {
            "db_instance_id": name,
            "security_group_id": sg_id,
            "subnet_group": db_subnet_group_name,
            "status": "creating",
            "db_name": db_name,
            "username": user,
            "engine": "postgres",
            "instance_type": instance_type,
            "allocated_storage": allocated_storage,
            "region": region
        }

    except Exception as e:
        click.echo(f"❌ Failed to create RDS instance: {str(e)}")
        raise


def get_rds_instance_status(instance_id, region):
    """Get the status and endpoint information for an RDS instance"""
    try:
        rds = boto3.client('rds', region_name=region)
        response = rds.describe_db_instances(DBInstanceIdentifier=instance_id)

        if not response['DBInstances']:
            return None

        instance = response['DBInstances'][0]
        return {
            "status": instance['DBInstanceStatus'],
            "endpoint": instance.get('Endpoint', {}).get('Address'),
            "port": instance.get('Endpoint', {}).get('Port', 5432),
            "engine": instance['Engine'],
            "engine_version": instance['EngineVersion'],
            "storage": instance['AllocatedStorage']
        }
    except Exception as e:
        click.echo(f"❌ Error getting RDS status: {str(e)}")
        return None


@create.command("postgres")
@click.option("--name", required=True, help="Database instance name")
@click.option("--deployment-id", required=True, help="EKS deployment ID to attach to")
@click.option("--username", required=True, help="Master username")
@click.option("--password", required=True, help="Master password")
@click.option("--db-name", default="postgres", help="Database name")
@click.option("--instance-type", default="db.t3.micro", help="RDS instance type")
@click.option("--storage", default=20, type=int, help="Allocated storage in GB")
@click.option("--backup-retention", default=7, type=int, help="Backup retention in days")
def create_postgres_db(name, deployment_id, username, password, db_name, instance_type, storage, backup_retention):
    """Create a PostgreSQL database for an EKS deployment"""

    # Check if setup is complete
    config = check_setup_required()

    # Validate AWS credentials
    validate_aws_credentials()

    # Check if the deployment exists
    deployment_dir = DEPLOYMENTS_DIR / deployment_id
    metadata_file = deployment_dir / "metadata.json"

    if not metadata_file.exists():
        click.echo(f"❌ Deployment not found: {deployment_id}")
        raise click.Abort()

    # Load deployment metadata
    with open(metadata_file, 'r') as f:
        metadata = json.load(f)

    # Ensure this is an EKS deployment
    if metadata["resource_type"] != "eks-cluster":
        click.echo("❌ This command only supports EKS cluster deployments")
        raise click.Abort()

    region = metadata["region"]

    # Get deployment VPC and subnet information
    click.echo(f"🔍 Getting VPC information for deployment: {deployment_id}")

    try:
        # Use eksctl to get cluster information
        cmd = ["eksctl", "get", "cluster", "-n", deployment_id, "-r", region, "-o", "json"]
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        cluster_info = json.loads(result.stdout)

        # Extract VPC ID
        if not cluster_info or len(cluster_info) == 0:
            click.echo("❌ Could not get cluster information")
            raise click.Abort()

        vpc_id = cluster_info[0]["VPC"]["ID"]
        click.echo(f"📋 Found VPC: {vpc_id}")

        # Get private subnets
        subnets = get_vpc_subnets(region)
        private_subnets = [s for s in subnets if s['type'] == 'private' and s['vpc_id'] == vpc_id]

        if not private_subnets or len(private_subnets) < 2:
            click.echo("❌ Need at least 2 private subnets for RDS")
            raise click.Abort()

        # Show selected subnets
        click.echo("📋 Selected subnets for RDS:")
        for subnet in private_subnets[:2]:
            click.echo(f"   - {subnet['name']} ({subnet['id']}) in {subnet['az']}")

        # Create the RDS instance
        db_name_sanitized = db_name.replace("-", "_")
        db_instance_name = f"{deployment_id}-{name}"

        # Check if database instance name exceeds 63 characters (RDS limit)
        if len(db_instance_name) > 63:
            db_instance_name = f"{deployment_id[:30]}-{name[:28]}"
            click.echo(f"⚠️  Database name truncated to: {db_instance_name}")

        # Confirm creation
        click.echo(f"\n🚀 Creating PostgreSQL database: {db_instance_name}")
        click.echo(f"   VPC: {vpc_id}")
        click.echo(f"   Type: {instance_type}")
        click.echo(f"   Storage: {storage} GB")
        click.echo(f"   Username: {username}")
        click.echo(f"   Database: {db_name_sanitized}")

        if not click.confirm("\nProceed with database creation?"):
            click.echo("❌ Database creation cancelled")
            return

        # Create the RDS instance
        db_info = create_postgres_rds(
            name=db_instance_name,
            vpc_id=vpc_id,
            subnets=private_subnets[:2],  # Use first 2 private subnets
            region=region,
            user=username,
            password=password,
            db_name=db_name_sanitized,
            instance_type=instance_type,
            allocated_storage=storage,
            backup_retention=backup_retention,
            deployment_id=deployment_id
        )

        # Save RDS metadata
        rds_metadata_path = deployment_dir / "rds_metadata.json"
        with open(rds_metadata_path, 'w') as f:
            # Don't store the password in the metadata
            db_info_safe = dict(db_info)
            db_info_safe["password"] = "******"  # Don't store actual password
            json.dump(db_info_safe, f, indent=2)

        # Update deployment metadata
        metadata["has_rds"] = True
        metadata["rds_instance_id"] = db_instance_name

        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        click.echo(f"\n✅ PostgreSQL database creation initiated: {db_instance_name}")
        click.echo("📊 Database creation will take 5-10 minutes.")
        click.echo("💡 You can check the status with: aws rds describe-db-instances " +
                 f"--db-instance-identifier {db_instance_name} --region {region}")

    except subprocess.CalledProcessError as e:
        click.echo(f"❌ Error getting cluster information: {e.stderr}")
        raise click.Abort()
    except Exception as e:
        click.echo(f"❌ Error creating database: {str(e)}")
        raise click.Abort()


if __name__ == "__main__":
    cli()