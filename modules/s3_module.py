"""
S3 bucket management module for the Platform CLI tool.
Handles S3 bucket creation, tagging, and lifecycle management.
"""

import click
import json
import boto3
from botocore.exceptions import ClientError
from datetime import datetime

# Import from parent directory
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))
from config import PlatformConfig


def locate_s3_bucket(name, region):
    """Locate an existing S3 bucket"""
    try:
        s3 = boto3.client('s3', region_name=region)

        # Check if bucket exists and is accessible
        try:
            s3.head_bucket(Bucket=name)
            # Get bucket location to verify it's in the expected region
            response = s3.get_bucket_location(Bucket=name)
            bucket_region = response.get('LocationConstraint')

            # us-east-1 returns None for LocationConstraint
            if bucket_region is None:
                bucket_region = 'us-east-1'

            if bucket_region == region:
                click.echo(f"✅ Found bucket '{name}' in region '{region}'")
                return name
            else:
                click.echo(f"⚠️ Bucket '{name}' exists but in different region: {bucket_region}")
                return None

        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            if error_code == '404':
                click.echo(f"📋 Bucket '{name}' not found in region '{region}'")
                return None
            elif error_code == '403':
                click.echo(f"❌ Access denied to bucket '{name}'")
                return None
            else:
                click.echo(f"❌ Error checking bucket '{name}': {e}")
                return None

    except Exception as e:
        click.echo(f"❌ Error locating bucket: {str(e)}")
        return None


def create_s3_bucket(name, region, config_instance, owner, preset, expires_at):
    """
    Creates an S3 bucket and tags it with dynamically generated tags.
    """
    # Sanitize region
    region = str(region).strip().lower()
    if not region:
        click.echo("❌ Error: Region is empty after sanitization")
        return False

    _config = config_instance.config

    click.echo(f"🔄 Creating S3 bucket '{name}' in region '{region}'")

    try:
        s3 = boto3.client('s3', region_name=region)

        # Create bucket with region-specific configuration
        if region == 'us-east-1':
            try:
                # us-east-1 doesn't need CreateBucketConfiguration
                s3.create_bucket(Bucket=name)
                click.echo(f"✅ Bucket created in us-east-1")
            except ClientError as ce:
                error_code = ce.response.get("Error", {}).get("Code")
                if error_code == 'BucketAlreadyExists':
                    click.echo(f"❌ Bucket name '{name}' already exists globally")
                    return False
                elif error_code == 'BucketAlreadyOwnedByYou':
                    click.echo(f"✅ Bucket '{name}' already exists and is owned by you")
                else:
                    raise ce
        else:
            # Other regions need CreateBucketConfiguration
            create_bucket_config = {'LocationConstraint': region}
            s3.create_bucket(
                Bucket=name,
                CreateBucketConfiguration=create_bucket_config
            )
            click.echo(f"✅ Bucket created in {region}")

        # Generate tags
        cluster_tags = dict(_config.get("default_tags", {}))
        cluster_tags.update({
            "user": _config.get("user_profile", {}).get("name", owner.split('@')[0]),
            "project": "platform-tool",
            "info": f"Platform tool S3 bucket - {preset}",
            "expires": expires_at.isoformat(),
            "PlatformManaged": "true",
            "Owner": owner,
            "Purpose": f"Platform tool bucket for {preset} environment"
        })

        # Add user profile tags if available
        user_profile = _config.get("user_profile", {})
        if user_profile.get("org"):
            cluster_tags["org"] = user_profile["org"]
        if user_profile.get("team"):
            cluster_tags["team"] = user_profile["team"]

        # Handle environment tag (avoid duplication)
        if 'environment' in cluster_tags and 'Environment' not in cluster_tags:
            cluster_tags['Environment'] = cluster_tags.pop('environment')

        click.echo(f"📋 Applying tags to bucket:")
        for key, value in cluster_tags.items():
            click.echo(f"   {key}: {value}")

        # Convert tags to S3 format
        s3_tags_list = [{'Key': k, 'Value': str(v)} for k, v in cluster_tags.items()]

        # Apply tags to bucket
        s3.put_bucket_tagging(
            Bucket=name,
            Tagging={'TagSet': s3_tags_list}
        )
        click.echo(f"✅ Bucket '{name}' tagged successfully")

        return True

    except ClientError as ce:
        error_code = ce.response.get("Error", {}).get("Code")
        error_message = ce.response.get("Error", {}).get("Message", "")

        if error_code == 'BucketAlreadyExists':
            click.echo(f"❌ Bucket name '{name}' is already taken globally")
        elif error_code == 'InvalidBucketName':
            click.echo(f"❌ Invalid bucket name '{name}': {error_message}")
        else:
            click.echo(f"❌ Failed to create bucket '{name}': {ce}")
        return False
    except Exception as e:
        click.echo(f"❌ Unexpected error creating bucket '{name}': {str(e)}")
        return False


def delete_s3_bucket(name, region, force=False):
    """Delete an S3 bucket (optionally force delete with contents)"""
    try:
        s3 = boto3.client('s3', region_name=region)

        if force:
            # Delete all objects first
            click.echo(f"🗑️ Deleting all objects in bucket '{name}'...")

            # List and delete all objects
            paginator = s3.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=name):
                if 'Contents' in page:
                    objects = [{'Key': obj['Key']} for obj in page['Contents']]
                    s3.delete_objects(
                        Bucket=name,
                        Delete={'Objects': objects}
                    )

            # Delete all object versions if versioning is enabled
            version_paginator = s3.get_paginator('list_object_versions')
            for page in version_paginator.paginate(Bucket=name):
                if 'Versions' in page:
                    versions = [{'Key': v['Key'], 'VersionId': v['VersionId']} for v in page['Versions']]
                    s3.delete_objects(
                        Bucket=name,
                        Delete={'Objects': versions}
                    )
                if 'DeleteMarkers' in page:
                    markers = [{'Key': m['Key'], 'VersionId': m['VersionId']} for m in page['DeleteMarkers']]
                    s3.delete_objects(
                        Bucket=name,
                        Delete={'Objects': markers}
                    )

        # Delete the bucket
        s3.delete_bucket(Bucket=name)
        click.echo(f"✅ Bucket '{name}' deleted successfully")
        return True

    except ClientError as ce:
        error_code = ce.response.get("Error", {}).get("Code")
        if error_code == 'BucketNotEmpty':
            click.echo(f"❌ Bucket '{name}' is not empty. Use --force to delete contents")
        elif error_code == 'NoSuchBucket':
            click.echo(f"⚠️ Bucket '{name}' does not exist")
        else:
            click.echo(f"❌ Failed to delete bucket '{name}': {ce}")
        return False
    except Exception as e:
        click.echo(f"❌ Unexpected error deleting bucket '{name}': {str(e)}")
        return False


def get_bucket_info(name, region):
    """Get information about an S3 bucket"""
    try:
        s3 = boto3.client('s3', region_name=region)

        # Get bucket location
        location_response = s3.get_bucket_location(Bucket=name)
        bucket_region = location_response.get('LocationConstraint') or 'us-east-1'

        # Get bucket tags
        try:
            tags_response = s3.get_bucket_tagging(Bucket=name)
            tags = {tag['Key']: tag['Value'] for tag in tags_response['TagSet']}
        except ClientError as e:
            if e.response.get('Error', {}).get('Code') == 'NoSuchTagSet':
                tags = {}
            else:
                raise e

        # Get bucket size (approximate)
        cloudwatch = boto3.client('cloudwatch', region_name=bucket_region)
        try:
            size_response = cloudwatch.get_metric_statistics(
                Namespace='AWS/S3',
                MetricName='BucketSizeBytes',
                Dimensions=[
                    {'Name': 'BucketName', 'Value': name},
                    {'Name': 'StorageType', 'Value': 'StandardStorage'}
                ],
                StartTime=datetime.now().replace(hour=0, minute=0, second=0, microsecond=0),
                EndTime=datetime.now(),
                Period=86400,
                Statistics=['Average']
            )
            size_bytes = size_response['Datapoints'][0]['Average'] if size_response['Datapoints'] else 0
        except:
            size_bytes = 0

        return {
            'name': name,
            'region': bucket_region,
            'tags': tags,
            'size_bytes': size_bytes,
            'size_gb': round(size_bytes / (1024**3), 2) if size_bytes > 0 else 0,
            'platform_managed': tags.get('PlatformManaged', 'false').lower() == 'true',
            'owner': tags.get('Owner', 'Unknown'),
            'expires': tags.get('expires', 'No expiration set')
        }

    except ClientError as e:
        if e.response.get('Error', {}).get('Code') == 'NoSuchBucket':
            return None
        else:
            raise e


def list_platform_buckets(region=None):
    """List all S3 buckets managed by the platform tool"""
    try:
        s3 = boto3.client('s3')

        # Get all buckets
        response = s3.list_buckets()
        platform_buckets = []

        for bucket in response['Buckets']:
            bucket_name = bucket['Name']

            try:
                # Get bucket region
                location_response = s3.get_bucket_location(Bucket=bucket_name)
                bucket_region = location_response.get('LocationConstraint') or 'us-east-1'

                # Skip if specific region requested and doesn't match
                if region and bucket_region != region:
                    continue

                # Check if bucket is platform managed
                try:
                    tags_response = s3.get_bucket_tagging(Bucket=bucket_name)
                    tags = {tag['Key']: tag['Value'] for tag in tags_response['TagSet']}

                    if tags.get('PlatformManaged', '').lower() == 'true':
                        bucket_info = get_bucket_info(bucket_name, bucket_region)
                        if bucket_info:
                            platform_buckets.append(bucket_info)

                except ClientError as e:
                    # Skip buckets without tags or access denied
                    continue

            except ClientError as e:
                # Skip buckets we can't access
                continue

        return platform_buckets

    except Exception as e:
        click.echo(f"❌ Error listing buckets: {str(e)}")
        return []


def validate_bucket_name(name):
    """Validate S3 bucket name according to AWS rules"""
    import re

    if not name:
        return False, "Bucket name cannot be empty"

    if len(name) < 3 or len(name) > 63:
        return False, "Bucket name must be between 3 and 63 characters"

    if not re.match(r'^[a-z0-9]', name):
        return False, "Bucket name must start with a lowercase letter or number"

    if not re.search(r'[a-z0-9]$', name):
        return False, "Bucket name must end with a lowercase letter or number"

    if not re.match(r'^[a-z0-9.-]+$', name):
        return False, "Bucket name can only contain lowercase letters, numbers, hyphens, and periods"

    if '..' in name:
        return False, "Bucket name cannot contain consecutive periods"

    if '.-' in name or '-.' in name:
        return False, "Bucket name cannot contain periods adjacent to hyphens"

    # Check for IP address format
    if re.match(r'^\d+\.\d+\.\d+\.\d+$', name):
        return False, "Bucket name cannot be formatted as an IP address"

    return True, "Valid bucket name"