"""
Connectivity management module for secure access to shared cloud data sources.
Manages SSH tunnels, bastion hosts, and connection profiles for shared databases.
"""

import click
import json
import subprocess
import time
from pathlib import Path
from datetime import datetime
import paramiko
from sshtunnel import SSHTunnelForwarder
import threading

# Import from parent directory
import sys
sys.path.append(str(Path(__file__).parent.parent))
from config import PlatformConfig, PLATFORM_DIR

# Connectivity configuration directory
CONNECTIVITY_DIR = PLATFORM_DIR / "connectivity"
TUNNELS_DIR = CONNECTIVITY_DIR / "tunnels"
PROFILES_DIR = CONNECTIVITY_DIR / "profiles"

# Ensure directories exist
CONNECTIVITY_DIR.mkdir(exist_ok=True)
TUNNELS_DIR.mkdir(exist_ok=True)
PROFILES_DIR.mkdir(exist_ok=True)

# Shared data source definitions
SHARED_DATA_SOURCES = {
    "aws": {
        "aws-postgres": {
            "name": "AWS PostgreSQL (Shared)",
            "type": "postgresql",
            "description": "Shared PostgreSQL instance with sample datasets",
            "bastion_host": "bastion-aws.platform.internal",
            "target_host": "postgres-shared.platform.internal",
            "target_port": 5432,
            "local_port": 5432,
            "datasets": ["tpch", "tpcds", "customer_sample", "web_logs"]
        },
        "aws-mysql": {
            "name": "AWS MySQL (Shared)",
            "type": "mysql",
            "description": "Shared MySQL instance for compatibility testing",
            "bastion_host": "bastion-aws.platform.internal",
            "target_host": "mysql-shared.platform.internal",
            "target_port": 3306,
            "local_port": 3306,
            "datasets": ["sakila", "world", "customer_orders"]
        },
        "aws-s3": {
            "name": "AWS S3 (Shared Buckets)",
            "type": "s3",
            "description": "Shared S3 buckets with various data formats",
            "access_type": "iam_role",
            "buckets": ["platform-shared-parquet", "platform-shared-json", "platform-shared-csv"]
        }
    },
    "gcp": {
        "gcp-bigquery": {
            "name": "GCP BigQuery (Shared)",
            "type": "bigquery",
            "description": "Shared BigQuery datasets for analytics testing",
            "access_type": "service_account",
            "project_id": "platform-shared-data",
            "datasets": ["public_datasets", "sample_analytics", "customer_events"]
        },
        "gcp-postgres": {
            "name": "GCP Cloud SQL PostgreSQL",
            "type": "postgresql",
            "description": "Shared Cloud SQL PostgreSQL instance",
            "bastion_host": "bastion-gcp.platform.internal",
            "target_host": "postgres-gcp.platform.internal",
            "target_port": 5432,
            "local_port": 5433,
            "datasets": ["retail_data", "financial_sample"]
        }
    },
    "azure": {
        "azure-synapse": {
            "name": "Azure Synapse (Shared)",
            "type": "synapse",
            "description": "Shared Azure Synapse for data warehouse testing",
            "bastion_host": "bastion-azure.platform.internal",
            "target_host": "synapse-shared.platform.internal",
            "target_port": 1433,
            "local_port": 1433,
            "datasets": ["data_warehouse_sample", "time_series_data"]
        }
    }
}

# Active tunnel tracking
active_tunnels = {}
tunnel_lock = threading.Lock()


def get_ssh_key_path():
    """Get path to SSH private key for bastion hosts"""
    config = PlatformConfig()

    # Default SSH key location
    ssh_key_path = Path.home() / ".ssh" / "platform_bastion_key"

    # Check if key exists
    if not ssh_key_path.exists():
        click.echo(f"⚠️ SSH key not found at {ssh_key_path}")
        click.echo("💡 Request access to shared infrastructure:")
        click.echo("   1. Contact platform admin to provision bastion access")
        click.echo("   2. SSH key will be provided for secure connectivity")
        return None

    return str(ssh_key_path)


def test_bastion_connectivity(bastion_host, ssh_key_path):
    """Test connectivity to bastion host"""
    try:
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        ssh_client.connect(
            hostname=bastion_host,
            username='platform-user',
            key_filename=ssh_key_path,
            timeout=10
        )

        ssh_client.close()
        return True

    except Exception as e:
        click.echo(f"❌ Cannot connect to bastion {bastion_host}: {e}")
        return False


def create_ssh_tunnel(data_source_id, source_config):
    """Create SSH tunnel to shared data source"""

    ssh_key_path = get_ssh_key_path()
    if not ssh_key_path:
        return None

    bastion_host = source_config["bastion_host"]
    target_host = source_config["target_host"]
    target_port = source_config["target_port"]
    local_port = source_config["local_port"]

    # Test bastion connectivity first
    if not test_bastion_connectivity(bastion_host, ssh_key_path):
        return None

    try:
        click.echo(f"🔗 Creating SSH tunnel: localhost:{local_port} -> {target_host}:{target_port}")

        # Create SSH tunnel
        tunnel = SSHTunnelForwarder(
            ssh_address_or_host=(bastion_host, 22),
            ssh_username='platform-user',
            ssh_pkey=ssh_key_path,
            remote_bind_address=(target_host, target_port),
            local_bind_address=('127.0.0.1', local_port),
            set_keepalive=30
        )

        tunnel.start()

        # Verify tunnel is working
        if tunnel.is_alive:
            click.echo(f"✅ SSH tunnel active: localhost:{local_port}")

            # Store tunnel info
            tunnel_info = {
                "data_source_id": data_source_id,
                "bastion_host": bastion_host,
                "target_host": target_host,
                "target_port": target_port,
                "local_port": local_port,
                "created_at": datetime.now().isoformat(),
                "status": "active"
            }

            # Save tunnel metadata
            tunnel_file = TUNNELS_DIR / f"{data_source_id}.json"
            with open(tunnel_file, 'w') as f:
                json.dump(tunnel_info, f, indent=2)

            # Track active tunnel
            with tunnel_lock:
                active_tunnels[data_source_id] = tunnel

            return tunnel_info
        else:
            click.echo("❌ Failed to establish SSH tunnel")
            tunnel.stop()
            return None

    except Exception as e:
        click.echo(f"❌ Error creating SSH tunnel: {e}")
        return None


def stop_ssh_tunnel(data_source_id):
    """Stop SSH tunnel for data source"""

    with tunnel_lock:
        if data_source_id in active_tunnels:
            tunnel = active_tunnels[data_source_id]
            tunnel.stop()
            del active_tunnels[data_source_id]
            click.echo(f"✅ SSH tunnel stopped for {data_source_id}")

    # Remove tunnel metadata
    tunnel_file = TUNNELS_DIR / f"{data_source_id}.json"
    if tunnel_file.exists():
        tunnel_file.unlink()


def enable_data_source(data_source_id, cluster_name=None):
    """Enable access to a shared data source"""

    # Find data source configuration
    source_config = None
    for cloud_provider, sources in SHARED_DATA_SOURCES.items():
        if data_source_id in sources:
            source_config = sources[data_source_id]
            break

    if not source_config:
        available_sources = []
        for cloud, sources in SHARED_DATA_SOURCES.items():
            available_sources.extend(sources.keys())
        click.echo(f"❌ Unknown data source: {data_source_id}")
        click.echo(f"💡 Available sources: {', '.join(available_sources)}")
        return None

    # Check if already connected
    if is_data_source_connected(data_source_id):
        click.echo(f"✅ Already connected to {data_source_id}")
        return get_connection_info(data_source_id)

    click.echo(f"🔗 Enabling connection to {source_config['name']}...")

    # Handle different connection types
    if source_config["type"] in ["postgresql", "mysql", "synapse"]:
        # Create SSH tunnel for database connections
        tunnel_info = create_ssh_tunnel(data_source_id, source_config)
        if not tunnel_info:
            return None

        # Create connection profile for Starburst
        connection_profile = create_starburst_connection_profile(data_source_id, source_config, tunnel_info)

        return {
            "data_source_id": data_source_id,
            "name": source_config["name"],
            "type": source_config["type"],
            "status": "connected",
            "tunnel_info": tunnel_info,
            "connection_profile": connection_profile
        }

    elif source_config["type"] in ["s3", "bigquery"]:
        # Handle cloud storage/analytics services
        connection_profile = create_cloud_service_profile(data_source_id, source_config)

        return {
            "data_source_id": data_source_id,
            "name": source_config["name"],
            "type": source_config["type"],
            "status": "connected",
            "connection_profile": connection_profile
        }

    else:
        click.echo(f"❌ Unsupported data source type: {source_config['type']}")
        return None


def disable_data_source(data_source_id, cluster_name=None):
    """Disable access to a shared data source"""

    if not is_data_source_connected(data_source_id):
        click.echo(f"⚠️ Data source {data_source_id} is not connected")
        return

    # Stop SSH tunnel if exists
    stop_ssh_tunnel(data_source_id)

    # Remove connection profile
    profile_file = PROFILES_DIR / f"{data_source_id}.yaml"
    if profile_file.exists():
        profile_file.unlink()

    click.echo(f"✅ Disconnected from {data_source_id}")


def is_data_source_connected(data_source_id):
    """Check if data source is currently connected"""

    # Check for active tunnel
    tunnel_file = TUNNELS_DIR / f"{data_source_id}.json"
    if tunnel_file.exists():
        # Verify tunnel is still active
        with tunnel_lock:
            if data_source_id in active_tunnels:
                tunnel = active_tunnels[data_source_id]
                return tunnel.is_alive

    # Check for connection profile (for cloud services)
    profile_file = PROFILES_DIR / f"{data_source_id}.yaml"
    return profile_file.exists()


def get_connection_info(data_source_id):
    """Get connection information for a data source"""

    # Find source configuration
    source_config = None
    for cloud_provider, sources in SHARED_DATA_SOURCES.items():
        if data_source_id in sources:
            source_config = sources[data_source_id]
            break

    if not source_config:
        return None

    connection_info = {
        "data_source_id": data_source_id,
        "name": source_config["name"],
        "type": source_config["type"],
        "description": source_config["description"],
        "status": "connected" if is_data_source_connected(data_source_id) else "disconnected"
    }

    # Add tunnel-specific info
    if source_config["type"] in ["postgresql", "mysql", "synapse"]:
        tunnel_file = TUNNELS_DIR / f"{data_source_id}.json"
        if tunnel_file.exists():
            with open(tunnel_file, 'r') as f:
                tunnel_info = json.load(f)

            connection_info.update({
                "endpoint": "localhost",
                "port": tunnel_info["local_port"],
                "tunnel_status": "active" if is_data_source_connected(data_source_id) else "inactive",
                "target_endpoint": f"{tunnel_info['target_host']}:{tunnel_info['target_port']}"
            })
        else:
            connection_info.update({
                "endpoint": "not connected",
                "port": source_config["local_port"],
                "tunnel_status": "inactive"
            })

    return connection_info


def create_starburst_connection_profile(data_source_id, source_config, tunnel_info):
    """Create Starburst catalog configuration for connected data source"""

    # Generate Starburst catalog YAML based on data source type
    if source_config["type"] == "postgresql":
        catalog_config = {
            "connector.name": "postgresql",
            "connection-url": f"jdbc:postgresql://localhost:{tunnel_info['local_port']}/postgres",
            "connection-user": "starburst_user",
            "connection-password": "${ENV:POSTGRES_PASSWORD}",
            "case-insensitive-name-matching": "true"
        }

    elif source_config["type"] == "mysql":
        catalog_config = {
            "connector.name": "mysql",
            "connection-url": f"jdbc:mysql://localhost:{tunnel_info['local_port']}/mysql",
            "connection-user": "starburst_user",
            "connection-password": "${ENV:MYSQL_PASSWORD}",
            "case-insensitive-name-matching": "true"
        }

    elif source_config["type"] == "synapse":
        catalog_config = {
            "connector.name": "sqlserver",
            "connection-url": f"jdbc:sqlserver://localhost:{tunnel_info['local_port']};database=master",
            "connection-user": "starburst_user",
            "connection-password": "${ENV:SYNAPSE_PASSWORD}",
            "case-insensitive-name-matching": "true"
        }

    # Save as YAML file for Helm values integration
    profile_file = PROFILES_DIR / f"{data_source_id}.yaml"
    import yaml
    with open(profile_file, 'w') as f:
        yaml.dump({f"catalog_{data_source_id.replace('-', '_')}": catalog_config}, f)

    click.echo(f"📋 Created Starburst catalog profile: {profile_file}")

    return {
        "profile_file": str(profile_file),
        "catalog_name": data_source_id.replace('-', '_'),
        "connector_type": source_config["type"]
    }


def create_cloud_service_profile(data_source_id, source_config):
    """Create connection profile for cloud services (S3, BigQuery, etc.)"""

    if source_config["type"] == "s3":
        # S3 uses IAM roles - create catalog configuration
        catalog_config = {
            "connector.name": "hive",
            "hive.s3.aws-access-key": "${ENV:AWS_ACCESS_KEY_ID}",
            "hive.s3.aws-secret-key": "${ENV:AWS_SECRET_ACCESS_KEY}",
            "hive.s3.region": "us-east-1",
            "hive.metastore.uri": "thrift://localhost:9083"
        }

    elif source_config["type"] == "bigquery":
        catalog_config = {
            "connector.name": "bigquery",
            "bigquery.project-id": source_config["project_id"],
            "bigquery.credentials-key": "${ENV:GOOGLE_APPLICATION_CREDENTIALS}",
            "case-insensitive-name-matching": "true"
        }

    # Save profile
    profile_file = PROFILES_DIR / f"{data_source_id}.yaml"
    import yaml
    with open(profile_file, 'w') as f:
        yaml.dump({f"catalog_{data_source_id.replace('-', '_')}": catalog_config}, f)

    return {
        "profile_file": str(profile_file),
        "catalog_name": data_source_id.replace('-', '_'),
        "connector_type": source_config["type"]
    }


def list_available_sources():
    """List all available shared data sources"""

    available_sources = {}

    for cloud_provider, sources in SHARED_DATA_SOURCES.items():
        available_sources[cloud_provider] = []

        for source_id, source_config in sources.items():
            source_info = {
                "id": source_id,
                "name": source_config["name"],
                "type": source_config["type"],
                "description": source_config["description"],
                "connected": is_data_source_connected(source_id)
            }

            if "datasets" in source_config:
                source_info["datasets"] = source_config["datasets"]

            available_sources[cloud_provider].append(source_info)

    return available_sources


def cleanup_inactive_tunnels():
    """Clean up inactive SSH tunnels"""

    with tunnel_lock:
        inactive_tunnels = []

        for data_source_id, tunnel in active_tunnels.items():
            if not tunnel.is_alive:
                inactive_tunnels.append(data_source_id)

        for data_source_id in inactive_tunnels:
            click.echo(f"🧹 Cleaning up inactive tunnel: {data_source_id}")
            del active_tunnels[data_source_id]

            # Remove tunnel metadata
            tunnel_file = TUNNELS_DIR / f"{data_source_id}.json"
            if tunnel_file.exists():
                tunnel_file.unlink()


def monitor_tunnel_health():
    """Background thread to monitor tunnel health"""

    while True:
        try:
            cleanup_inactive_tunnels()
            time.sleep(60)  # Check every minute
        except Exception as e:
            click.echo(f"⚠️ Tunnel monitoring error: {e}")
            time.sleep(60)


# Start tunnel monitoring in background
tunnel_monitor_thread = threading.Thread(target=monitor_tunnel_health, daemon=True)
tunnel_monitor_thread.start()