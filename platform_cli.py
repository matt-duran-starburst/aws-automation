#!/usr/bin/env python3
"""
Platform CLI Tool for AWS EKS/Starburst Deployments
Refactored version with modular architecture

Renamed from platform.py to platform_cli.py to avoid stdlib conflict
"""

import click
import json
import os
import subprocess
import yaml
from datetime import datetime

# Import our modules
from config import PlatformConfig, PLATFORM_DIR, DEPLOYMENTS_DIR, CONFIG_FILE
from modules.utils_module import (
    validate_aws_credentials, check_setup_required, get_vpc_subnets,
    parse_expiration, generate_deployment_id, create_deployment_metadata,
    load_deployment_metadata, save_deployment_metadata, list_deployments,
    print_deployments_table, confirm_action, sanitize_name
)
from modules.eks_module import (
    scale_eks_nodegroups, run_eksctl_command, generate_eksctl_config,
    get_cluster_vpc_info, update_kubeconfig
)
from modules.rds_module import (
    create_rds_instance, get_rds_instance_status, delete_rds_instance,
    get_connection_string, validate_engine_requirements, DATABASE_ENGINES
)
from modules.s3_module import (
    locate_s3_bucket, create_s3_bucket, delete_s3_bucket, get_bucket_info,
    list_platform_buckets, validate_bucket_name
)


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
    save_deployment_metadata(deployment_id, metadata)

    # Show config preview
    click.echo("\n📋 Cluster configuration preview:")
    with open(deployment_dir / eksctl_config_path, 'r') as f:
        config_preview = f.read()
        # Show first 20 lines
        lines = config_preview.split('\n')[:20]
        click.echo('\n'.join(lines))
        if len(config_preview.split('\n')) > 20:
            click.echo("...")

    if confirm_action("\nProceed with cluster creation?"):
        click.echo("🚀 Creating EKS cluster (this may take 10-15 minutes)...")

        try:
            output = run_eksctl_command("create", deployment_dir, eksctl_config_path)
            click.echo(output)

            # Update metadata
            metadata["status"] = "running"
            metadata["is_running"] = True
            metadata["created_date"] = datetime.now().isoformat()

            save_deployment_metadata(deployment_id, metadata)

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

            save_deployment_metadata(deployment_id, metadata)

            click.echo("❌ Cluster creation failed")
            raise
    else:
        click.echo("❌ Cluster creation cancelled")


@create.command("database")
@click.option("--name", required=True, help="Database instance name")
@click.option("--deployment-id", required=True, help="EKS deployment ID to attach to")
@click.option("--engine", required=True,
              type=click.Choice(['postgres', 'mysql', 'oracle']),
              help="Database engine")
@click.option("--username", required=True, help="Master username")
@click.option("--password", required=True, help="Master password")
@click.option("--db-name", help="Database name (defaults to engine default)")
@click.option("--instance-type", help="RDS instance type (defaults to engine default)")
@click.option("--storage", default=20, type=int, help="Allocated storage in GB")
@click.option("--backup-retention", default=7, type=int, help="Backup retention in days")
def create_database(name, deployment_id, engine, username, password, db_name,
                   instance_type, storage, backup_retention):
    """Create a database for an EKS deployment"""

    # Check if setup is complete
    config = check_setup_required()

    # Validate AWS credentials
    validate_aws_credentials()

    # Validate engine requirements
    if not instance_type:
        instance_type = DATABASE_ENGINES[engine]["default_instance"]

    validate_engine_requirements(engine, instance_type, storage)

    # Check if the deployment exists
    metadata = load_deployment_metadata(deployment_id)
    if not metadata:
        click.echo(f"❌ Deployment not found: {deployment_id}")
        raise click.Abort()

    # Ensure this is an EKS deployment
    if metadata["resource_type"] != "eks-cluster":
        click.echo("❌ This command only supports EKS cluster deployments")
        raise click.Abort()

    region = metadata["region"]

    # Get deployment VPC and subnet information
    click.echo(f"🔍 Getting VPC information for deployment: {deployment_id}")

    try:
        vpc_id = get_cluster_vpc_info(deployment_id, region)
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
        db_instance_name = f"{deployment_id}-{sanitize_name(name)}"

        # Check if database instance name exceeds 63 characters (RDS limit)
        if len(db_instance_name) > 63:
            db_instance_name = f"{deployment_id[:30]}-{sanitize_name(name, 28)}"
            click.echo(f"⚠️  Database name truncated to: {db_instance_name}")

        # Confirm creation
        click.echo(f"\n🚀 Creating {engine.upper()} database: {db_instance_name}")
        click.echo(f"   VPC: {vpc_id}")
        click.echo(f"   Type: {instance_type}")
        click.echo(f"   Storage: {storage} GB")
        click.echo(f"   Username: {username}")
        if db_name:
            click.echo(f"   Database: {db_name}")

        if not confirm_action("\nProceed with database creation?"):
            click.echo("❌ Database creation cancelled")
            return

        # Create the RDS instance
        db_info = create_rds_instance(
            name=db_instance_name,
            engine=engine,
            vpc_id=vpc_id,
            subnets=private_subnets[:2],  # Use first 2 private subnets
            region=region,
            username=username,
            password=password,
            db_name=db_name,
            instance_type=instance_type,
            allocated_storage=storage,
            backup_retention=backup_retention,
            deployment_id=deployment_id
        )

        # Save RDS metadata
        deployment_dir = DEPLOYMENTS_DIR / deployment_id
        rds_metadata_path = deployment_dir / "rds_metadata.json"
        with open(rds_metadata_path, 'w') as f:
            # Don't store the password in the metadata
            db_info_safe = dict(db_info)
            db_info_safe["password"] = "******"  # Don't store actual password
            json.dump(db_info_safe, f, indent=2)

        # Update deployment metadata
        metadata["has_rds"] = True
        metadata["rds_instance_id"] = db_instance_name
        metadata["rds_engine"] = engine

        save_deployment_metadata(deployment_id, metadata)

        click.echo(f"\n✅ {engine.upper()} database creation initiated: {db_instance_name}")
        click.echo("📊 Database creation will take 5-15 minutes.")
        click.echo("💡 Use 'platform status database' to check progress")

    except Exception as e:
        click.echo(f"❌ Error creating database: {str(e)}")
        raise click.Abort()


@create.command("s3-bucket")
@click.option('--name', required=True, help="The name of the S3 bucket to create")
@click.option('--region', help="The AWS region for the S3 bucket. Overrides config default")
@click.option('--owner-email', help="The owner's email for tags. Defaults to config user email")
@click.option('--preset', help="The deployment preset for the 'info' tag. Defaults to config environment")
@click.option('--expires-days', type=int, default=90, help="Number of days until bucket expiration tag")
def create_s3_bucket_command(name, region, owner_email, preset, expires_days):
    """Create or locate an S3 bucket with platform management tags"""

    # Check if setup is complete
    config = check_setup_required()

    # Validate AWS credentials
    validate_aws_credentials()

    # Validate bucket name
    is_valid, error_msg = validate_bucket_name(name)
    if not is_valid:
        click.echo(f"❌ Invalid bucket name: {error_msg}")
        raise click.Abort()

    # Determine region
    actual_region = region or config.config.get("default_region")
    if not actual_region:
        click.echo("❌ AWS region not provided via --region or found in config")
        raise click.Abort()

    # Determine owner_email
    actual_owner_email = owner_email or config.config.get("user_profile", {}).get("email")
    if not actual_owner_email:
        click.echo("❌ Owner email not provided via --owner-email or found in config")
        raise click.Abort()

    # Determine preset
    actual_preset = preset or config.config.get("default_tags", {}).get("environment", "development")

    click.echo(f"\n🪣 Managing S3 bucket '{name}' in region '{actual_region}'")

    # Construct expiration datetime
    expires_in_str = f"{expires_days}d"
    try:
        expires_at = parse_expiration(expires_in_str)
    except click.BadParameter as e:
        click.echo(f"❌ Invalid expires-days value: {e}")
        raise click.Abort()

    # Check if bucket exists
    located_bucket = locate_s3_bucket(name, actual_region)

    if located_bucket:
        click.echo(f"✅ Bucket '{name}' already exists")

        # Get bucket info
        bucket_info = get_bucket_info(name, actual_region)
        if bucket_info:
            click.echo(f"📊 Bucket info:")
            click.echo(f"   Region: {bucket_info['region']}")
            click.echo(f"   Size: {bucket_info['size_gb']} GB")
            click.echo(f"   Owner: {bucket_info['owner']}")
            click.echo(f"   Platform Managed: {bucket_info['platform_managed']}")
        return

    click.echo(f"📋 Bucket '{name}' not found. Creating it...")

    # Create the bucket
    if create_s3_bucket(name, actual_region, config, actual_owner_email, actual_preset, expires_at):
        click.echo(f"✅ Bucket '{name}' successfully created and tagged")
    else:
        click.echo(f"❌ Failed to create bucket '{name}'")
        raise click.Abort()


@cli.command("start")
@click.argument("deployment_id")
@click.option("--force", is_flag=True, help="Skip confirmation")
def start_deployment(deployment_id, force):
    """Start/scale up a deployment"""

    metadata = load_deployment_metadata(deployment_id)
    if not metadata:
        click.echo(f"❌ Deployment not found: {deployment_id}")
        raise click.Abort()

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

    if not confirm_action("Start this deployment?", force):
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

            save_deployment_metadata(deployment_id, metadata)

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

    metadata = load_deployment_metadata(deployment_id)
    if not metadata:
        click.echo(f"❌ Deployment not found: {deployment_id}")
        raise click.Abort()

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

    if not confirm_action("Stop this deployment?", force):
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

            save_deployment_metadata(deployment_id, metadata)

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
@click.option("--type", "resource_type", help="Filter by resource type (eks-cluster, s3-bucket)")
def list_deployments_command(owner, expiring_soon, status, running, stopped, resource_type):
    """List active deployments"""

    deployments = list_deployments(
        owner=owner,
        status=status,
        resource_type=resource_type,
        expiring_soon=expiring_soon,
        running=running,
        stopped=stopped
    )

    print_deployments_table(deployments)


@cli.command("destroy")
@click.argument("deployment_id")
@click.option("--force", is_flag=True, help="Skip confirmation")
def destroy_deployment(deployment_id, force):
    """Destroy a deployment"""

    metadata = load_deployment_metadata(deployment_id)
    if not metadata:
        click.echo(f"❌ Deployment not found: {deployment_id}")
        raise click.Abort()

    click.echo(f"🗑️  Destroying deployment: {deployment_id}")
    click.echo(f"   Owner: {metadata['owner']}")
    click.echo(f"   Created: {metadata['created_at']}")
    click.echo(f"   Type: {metadata['resource_type']}")

    if not confirm_action("Are you sure you want to destroy this deployment?", force):
        click.echo("❌ Destruction cancelled")
        return

    # Handle different resource types
    try:
        if metadata["resource_type"] == "eks-cluster":
            # Run eksctl delete
            deployment_dir = DEPLOYMENTS_DIR / deployment_id
            eksctl_config = metadata.get("eksctl_config", "cluster.yaml")
            click.echo("🏗️  Destroying EKS cluster (this may take 10-15 minutes)...")

            run_eksctl_command("delete", deployment_dir, eksctl_config)

            # Also delete RDS if it exists
            if metadata.get("has_rds"):
                rds_instance_id = metadata.get("rds_instance_id")
                if rds_instance_id:
                    click.echo(f"🗑️ Also destroying RDS instance: {rds_instance_id}")
                    delete_rds_instance(rds_instance_id, metadata["region"])

        # Update metadata
        metadata["status"] = "destroyed"
        metadata["destroyed_at"] = datetime.now().isoformat()

        save_deployment_metadata(deployment_id, metadata)

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

    metadata = load_deployment_metadata(deployment_id)
    if not metadata:
        click.echo(f"❌ Deployment not found: {deployment_id}")
        raise click.Abort()

    # Parse new expiration
    new_expires_at = parse_expiration(expires_in)

    old_expires = metadata["expires_at"]
    metadata["expires_at"] = new_expires_at.isoformat()
    metadata["extended_at"] = datetime.now().isoformat()

    # Update tags
    metadata["tags"]["AutoDestroy"] = new_expires_at.isoformat()

    save_deployment_metadata(deployment_id, metadata)

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
        if confirm_action("Are you sure you want to reset all configuration?"):
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
def update_kubeconfig_command(deployment_id):
    """Update kubeconfig for a deployment"""

    metadata = load_deployment_metadata(deployment_id)
    if not metadata:
        click.echo(f"❌ Deployment not found: {deployment_id}")
        raise click.Abort()

    region = metadata["region"]

    success, message = update_kubeconfig(deployment_id, region)
    if success:
        click.echo(f"✅ {message}")
        click.echo(f"🎯 Access with K9s: k9s --context {deployment_id}")
    else:
        click.echo(f"❌ {message}")
        raise click.Abort()


@cli.group()
def status():
    """Check status of deployments and resources"""
    pass


@status.command("database")
@click.argument("deployment_id")
def database_status(deployment_id):
    """Check database status for a deployment"""

    metadata = load_deployment_metadata(deployment_id)
    if not metadata:
        click.echo(f"❌ Deployment not found: {deployment_id}")
        raise click.Abort()

    if not metadata.get("has_rds"):
        click.echo(f"❌ No database found for deployment: {deployment_id}")
        return

    rds_instance_id = metadata.get("rds_instance_id")
    region = metadata["region"]

    click.echo(f"📊 Database status for {deployment_id}:")

    # Get RDS status
    db_status = get_rds_instance_status(rds_instance_id, region)
    if db_status:
        click.echo(f"   Instance ID: {rds_instance_id}")
        click.echo(f"   Status: {db_status['status']}")
        click.echo(f"   Engine: {db_status['engine']} {db_status['engine_version']}")
        click.echo(f"   Instance Type: {db_status['instance_class']}")
        click.echo(f"   Storage: {db_status['storage']} GB")

        if db_status['endpoint']:
            click.echo(f"   Endpoint: {db_status['endpoint']}:{db_status['port']}")

            # Load RDS metadata for connection info
            deployment_dir = DEPLOYMENTS_DIR / deployment_id
            rds_metadata_path = deployment_dir / "rds_metadata.json"
            if rds_metadata_path.exists():
                with open(rds_metadata_path, 'r') as f:
                    rds_metadata = json.load(f)

                click.echo("\n🔗 Connection Information:")
                connection_strings = get_connection_string(rds_metadata, "YOUR_PASSWORD")
                if isinstance(connection_strings, dict):
                    for conn_type, conn_string in connection_strings.items():
                        click.echo(f"   {conn_type.upper()}: {conn_string}")
                else:
                    click.echo(f"   {connection_strings}")
        else:
            click.echo("   Endpoint: Not yet available (database still initializing)")
    else:
        click.echo("   ❌ Could not retrieve database status")


@cli.group()
def s3():
    """S3 bucket management commands"""
    pass


@s3.command("list")
@click.option("--region", help="Filter by region")
def list_s3_buckets(region):
    """List platform-managed S3 buckets"""

    check_setup_required()
    validate_aws_credentials()

    buckets = list_platform_buckets(region)

    if not buckets:
        click.echo("No platform-managed S3 buckets found")
        return

    click.echo("📋 Platform-managed S3 buckets:")
    click.echo()

    for bucket in buckets:
        click.echo(f"🪣 {bucket['name']}")
        click.echo(f"   Region: {bucket['region']}")
        click.echo(f"   Size: {bucket['size_gb']} GB")
        click.echo(f"   Owner: {bucket['owner']}")
        click.echo(f"   Expires: {bucket['expires']}")
        click.echo()


@s3.command("delete")
@click.argument("bucket_name")
@click.option("--region", help="Bucket region")
@click.option("--force", is_flag=True, help="Force delete (remove all contents)")
def delete_s3_bucket_command(bucket_name, region, force):
    """Delete a platform-managed S3 bucket"""

    config = check_setup_required()
    validate_aws_credentials()

    if not region:
        region = config.config.get("default_region")

    if not region:
        click.echo("❌ Region required. Specify --region or set default in config")
        raise click.Abort()

    # Verify bucket exists and is platform managed
    bucket_info = get_bucket_info(bucket_name, region)
    if not bucket_info:
        click.echo(f"❌ Bucket '{bucket_name}' not found in region '{region}'")
        raise click.Abort()

    if not bucket_info['platform_managed']:
        click.echo(f"❌ Bucket '{bucket_name}' is not platform-managed")
        click.echo("Only platform-managed buckets can be deleted with this command")
        raise click.Abort()

    click.echo(f"🗑️ Deleting S3 bucket: {bucket_name}")
    click.echo(f"   Region: {region}")
    click.echo(f"   Size: {bucket_info['size_gb']} GB")
    click.echo(f"   Owner: {bucket_info['owner']}")

    if force:
        click.echo("\n⚠️ Force delete enabled - all contents will be permanently deleted!")

    if not confirm_action(f"Delete bucket '{bucket_name}'?", force=False):
        click.echo("❌ Deletion cancelled")
        return

    success = delete_s3_bucket(bucket_name, region, force=force)
    if not success:
        raise click.Abort()


if __name__ == "__main__":
    cli()