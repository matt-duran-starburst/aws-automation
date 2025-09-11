"""
Shared utilities module for the Platform CLI tool.
Contains common functions used across different modules.
"""

import click
import json
import os
import subprocess
import uuid
from datetime import datetime, timedelta
from pathlib import Path
import boto3
from botocore.exceptions import NoCredentialsError

# Import from parent directory
import sys
sys.path.append(str(Path(__file__).parent.parent))
from config import PLATFORM_DIR, LOCAL_CLUSTERS_DIR


def validate_aws_credentials():
    """Ensure AWS credentials are available and get account info"""
    try:
        session = boto3.Session()
        sts = session.client('sts')
        identity = sts.get_caller_identity()
        click.echo(f"✅ AWS credentials valid: {identity['Arn']}")

        # Update config with account ID
        from config import PlatformConfig
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
    from config import PlatformConfig
    config = PlatformConfig()
    if not config.config.get("setup_complete", False):
        click.echo("🔧 Initial setup required. Run 'platform setup' first.")
        raise click.Abort()
    return config


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
    """Generate unique deployment ID with length validation"""
    timestamp = datetime.now().strftime("%m%d")  # Shorter timestamp: MMDD instead of YYYY-MM-DD
    owner_clean = owner.split('@')[0].replace('.', '-')

    # Truncate components to ensure reasonable total length
    owner_clean = truncate_string(owner_clean, 15)  # Max 15 chars for owner
    name_clean = sanitize_name(name, 20)  # Max 20 chars for name

    deployment_id = f"{owner_clean}-{name_clean}-{timestamp}"

    # Ensure total length doesn't exceed 40 characters (leaves room for eksctl prefixes)
    if len(deployment_id) > 40:
        # If still too long, truncate further
        available_length = 40 - len(timestamp) - 2  # 2 for hyphens
        owner_length = min(len(owner_clean), available_length // 2)
        name_length = available_length - owner_length

        deployment_id = f"{owner_clean[:owner_length]}-{name_clean[:name_length]}-{timestamp}"

    return deployment_id


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


def load_deployment_metadata(deployment_id):
    """Load cluster metadata from file (updated for local clusters)"""
    cluster_dir = LOCAL_CLUSTERS_DIR / deployment_id
    metadata_file = cluster_dir / "metadata.json"

    if not metadata_file.exists():
        return None

    with open(metadata_file, 'r') as f:
        return json.load(f)


def save_deployment_metadata(deployment_id, metadata):
    """Save cluster metadata to file (updated for local clusters)"""
    cluster_dir = LOCAL_CLUSTERS_DIR / deployment_id
    metadata_file = cluster_dir / "metadata.json"

    # Ensure cluster directory exists
    cluster_dir.mkdir(parents=True, exist_ok=True)

    with open(metadata_file, 'w') as f:
        json.dump(metadata, f, indent=2)


def list_deployments(owner=None, status=None, resource_type=None, expiring_soon=False,
                    running=None, stopped=None):
    """List local clusters with optional filters (updated for local clusters)"""
    deployments = []

    for cluster_dir in LOCAL_CLUSTERS_DIR.iterdir():
        if cluster_dir.is_dir():
            metadata_file = cluster_dir / "metadata.json"
            if metadata_file.exists():
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)

                # Apply filters
                if owner and metadata.get("owner") != owner:
                    continue

                if status and metadata.get("status") != status:
                    continue

                if resource_type and metadata.get("resource_type") != resource_type:
                    continue

                if running is not None:
                    is_running = metadata.get("is_running", True)
                    if running and not is_running:
                        continue
                    if not running and is_running:
                        continue

                if stopped is not None:
                    is_running = metadata.get("is_running", True)
                    if stopped and is_running:
                        continue
                    if not stopped and not is_running:
                        continue

                if expiring_soon:
                    expires_at = datetime.fromisoformat(metadata["expires_at"])
                    hours_until_expiry = (expires_at - datetime.now()).total_seconds() / 3600
                    if hours_until_expiry > 24:
                        continue

                deployments.append(metadata)

    return sorted(deployments, key=lambda x: x.get("created_at", ""))


def format_time_remaining(expires_at_str):
    """Format time remaining until expiration"""
    try:
        expires_at = datetime.fromisoformat(expires_at_str)
        time_left = expires_at - datetime.now()

        if time_left.total_seconds() < 0:
            return "⚠️ EXPIRED"

        days = time_left.days
        hours, remainder = divmod(time_left.seconds, 3600)
        minutes, _ = divmod(remainder, 60)

        if days > 0:
            return f"{days}d {hours}h"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"
    except:
        return "Unknown"


def print_deployments_table(deployments):
    """Print deployments in a formatted table"""
    if not deployments:
        click.echo("No deployments found")
        return

    status_icons = {
        "creating": "🔄",
        "running": "✅",
        "failed": "❌",
        "destroyed": "🗑️"
    }

    click.echo("📋 Deployments:")
    click.echo()

    for deployment in deployments:
        status_icon = status_icons.get(deployment.get("status"), "❓")
        is_running = deployment.get("is_running", True)
        running_status = "🟢 Running" if is_running else "⏸️  Stopped"

        time_remaining = format_time_remaining(deployment.get("expires_at", ""))

        click.echo(f"{status_icon} {deployment['deployment_id']} ({running_status})")
        click.echo(f"   Type: {deployment.get('resource_type', 'unknown')}")
        click.echo(f"   Owner: {deployment.get('owner', 'unknown')}")
        click.echo(f"   Purpose: {deployment.get('purpose', 'no purpose')}")
        click.echo(f"   Region: {deployment.get('region', 'unknown')}")
        click.echo(f"   Status: {deployment.get('status', 'unknown')}")

        if deployment.get("preset"):
            click.echo(f"   Preset: {deployment['preset']}")

        click.echo(f"   Expires: {time_remaining}")

        # Show cost savings for stopped deployments
        if not is_running and deployment.get("status") == "running":
            click.echo("   💰 Costs reduced while stopped")

        click.echo()


def confirm_action(message, force=False):
    """Confirm an action with the user"""
    if force:
        return True
    return click.confirm(message)


def truncate_string(s, max_length):
    """Truncate a string to max length"""
    if len(s) <= max_length:
        return s
    return s[:max_length-3] + "..."


def validate_cluster_name(name, owner):
    """Validate cluster name will work with AWS CloudFormation limits"""
    # Generate the deployment ID to check total length
    test_deployment_id = generate_deployment_id(name, owner)

    errors = []
    warnings = []

    # Check total deployment ID length
    if len(test_deployment_id) > 40:
        errors.append(f"Generated cluster name too long: '{test_deployment_id}' ({len(test_deployment_id)} chars)")
        errors.append("This will cause CloudFormation IAM policy name limit errors")
        errors.append("Try a shorter cluster name (--name)")
    elif len(test_deployment_id) > 30:
        warnings.append(f"Cluster name is long: '{test_deployment_id}' ({len(test_deployment_id)} chars)")
        warnings.append("Some advanced features (externalDNS, certManager) will be disabled")

    # Check individual name component
    if len(name) > 20:
        warnings.append(f"Cluster name '{name}' is long ({len(name)} chars). Consider shortening for better compatibility")

    # Check for invalid characters
    import re
    if not re.match(r'^[a-zA-Z0-9-]+', name):
        errors.append("Cluster name can only contain letters, numbers, and hyphens")

    if name.startswith('-') or name.endswith('-'):
        errors.append("Cluster name cannot start or end with hyphen")

    return errors, warnings, test_deployment_id


def suggest_shorter_name(name, max_length=15):
    """Suggest a shorter version of the cluster name"""
    if len(name) <= max_length:
        return name

    # Try to create a meaningful abbreviation
    words = name.replace('-', ' ').replace('_', ' ').split()

    if len(words) > 1:
        # Use first letter of each word + number suffix
        abbreviated = ''.join(word[0] for word in words[:4])  # Max 4 words
        if len(name) > max_length:
            # Add some characters from the original name
            remaining_length = max_length - len(abbreviated) - 1
            if remaining_length > 0:
                abbreviated += '-' + name[:remaining_length]
        return abbreviated[:max_length]
    else:
        # Single word - truncate and maybe add vowel removal
        truncated = name[:max_length]
        if len(truncated) < len(name):
            # Try removing vowels to fit more meaningful content
            consonants = ''.join(c for c in name if c.lower() not in 'aeiou' or c == name[0])
            if len(consonants) <= max_length and len(consonants) >= 3:
                return consonants[:max_length]
        return truncated


def print_cluster_name_guidance():
    """Print helpful guidance about cluster naming"""
    click.echo("\n💡 Cluster Naming Best Practices:")
    click.echo("   • Keep cluster names short (15 chars or less)")
    click.echo("   • Use descriptive but concise names: 'dev-api', 'test-ml', 'demo-web'")
    click.echo("   • Avoid long email prefixes in deployment IDs")
    click.echo("   • Use abbreviations: 'development' → 'dev', 'testing' → 'test'")
    click.echo("   • Remember: shorter names = more AWS features enabled")
    click.echo()


def sanitize_name(name, max_length=None):
    """Sanitize a name for AWS resource naming with enhanced validation"""
    import re

    # Convert to lowercase for consistency
    sanitized = name.lower()

    # Replace invalid characters with hyphens
    sanitized = re.sub(r'[^a-z0-9-]', '-', sanitized)

    # Remove multiple consecutive hyphens
    sanitized = re.sub(r'-+', '-', sanitized)

    # Remove leading/trailing hyphens
    sanitized = sanitized.strip('-')

    # Ensure we have something left
    if not sanitized:
        sanitized = "cluster"

    # Truncate if needed
    if max_length and len(sanitized) > max_length:
        sanitized = sanitized[:max_length].rstrip('-')

    return sanitized