#!/usr/bin/env python3
"""
Platform CLI Tool for Local Development with Shared Cloud Data Sources
New architecture: Local Kind clusters + Shared cloud databases + Connectivity layer
"""

import click
from modules.local_cluster_module import create_kind_cluster, destroy_kind_cluster, list_local_clusters
from modules.connectivity_module import enable_data_source, disable_data_source, get_connection_info
from modules.starburst_module import deploy_starburst, undeploy_starburst
from modules.shared_data_module import list_available_sources, get_source_status
from modules.pulumi_module import provision_shared_infrastructure, destroy_shared_infrastructure

@click.group()
def cli():
    """Platform CLI for local development with shared cloud data sources"""
    pass

# ============================================================================
# LOCAL CLUSTER MANAGEMENT
# ============================================================================

@cli.group()
def local():
    """Manage local Kind clusters for development"""
    pass

@local.command("create")
@click.option("--name", required=True, help="Local cluster name")
@click.option("--preset", default="development",
              type=click.Choice(['development', 'performance', 'customer-reproduction']),
              help="Cluster preset configuration")
@click.option("--starburst", is_flag=True, help="Auto-deploy Starburst after cluster creation")
def create_local_cluster(name, preset, starburst):
    """Create a local Kind cluster optimized for Starburst"""
    click.echo(f"🚀 Creating local Kind cluster: {name}")

    # Create Kind cluster with preset configuration
    cluster_config = create_kind_cluster(name, preset)

    if starburst:
        click.echo("📊 Deploying Starburst Enterprise Platform...")
        deploy_starburst(name, preset)

    click.echo(f"✅ Local cluster '{name}' ready!")
    click.echo(f"💡 Enable data sources with: platform connect enable <source>")

@local.command("destroy")
@click.argument("cluster_name")
@click.option("--force", is_flag=True, help="Skip confirmation")
def destroy_local_cluster(cluster_name, force):
    """Destroy a local Kind cluster"""
    if not force:
        click.confirm(f"Destroy local cluster '{cluster_name}'?", abort=True)

    destroy_kind_cluster(cluster_name)
    click.echo(f"✅ Local cluster '{cluster_name}' destroyed")

@local.command("list")
def list_local_clusters_cmd():
    """List local Kind clusters"""
    clusters = list_local_clusters()

    if not clusters:
        click.echo("No local clusters found")
        return

    click.echo("📋 Local Clusters:")
    for cluster in clusters:
        status = "🟢 Running" if cluster['running'] else "🔴 Stopped"
        click.echo(f"  {status} {cluster['name']} ({cluster['preset']})")

# ============================================================================
# CONNECTIVITY MANAGEMENT
# ============================================================================

@cli.group()
def connect():
    """Manage connections to shared cloud data sources"""
    pass

@connect.command("enable")
@click.argument("data_source")
@click.option("--cluster", help="Target local cluster (defaults to current context)")
def enable_data_source_cmd(data_source, cluster):
    """Enable access to a shared data source"""
    click.echo(f"🔗 Enabling connection to {data_source}...")

    connection_info = enable_data_source(data_source, cluster)

    click.echo(f"✅ Connected to {data_source}")
    click.echo(f"📋 Connection details: platform connect info {data_source}")

@connect.command("disable")
@click.argument("data_source")
@click.option("--cluster", help="Target local cluster")
def disable_data_source_cmd(data_source, cluster):
    """Disable access to a shared data source"""
    click.echo(f"🔌 Disabling connection to {data_source}...")

    disable_data_source(data_source, cluster)

    click.echo(f"✅ Disconnected from {data_source}")

@connect.command("info")
@click.argument("data_source")
def get_connection_info_cmd(data_source):
    """Get connection information for a data source"""
    info = get_connection_info(data_source)

    click.echo(f"📋 Connection Info for {data_source}:")
    click.echo(f"   Status: {info['status']}")
    click.echo(f"   Endpoint: {info['endpoint']}")
    click.echo(f"   Port: {info['port']}")
    click.echo(f"   SSH Tunnel: {info['tunnel_status']}")

@connect.command("list")
def list_available_sources_cmd():
    """List available shared data sources"""
    sources = list_available_sources()

    click.echo("📊 Available Shared Data Sources:")
    for category, category_sources in sources.items():
        click.echo(f"\n  {category.upper()}:")
        for source in category_sources:
            status = "🟢 Connected" if source['connected'] else "⚪ Available"
            click.echo(f"    {status} {source['name']} - {source['description']}")

# ============================================================================
# STARBURST MANAGEMENT
# ============================================================================

@cli.group()
def starburst():
    """Manage Starburst Enterprise Platform deployments"""
    pass

@starburst.command("deploy")
@click.option("--cluster", required=True, help="Target local cluster")
@click.option("--config-from-case", help="Generate config from support case")
@click.option("--values-file", help="Custom Helm values file")
def deploy_starburst_cmd(cluster, config_from_case, values_file):
    """Deploy Starburst to a local cluster"""
    click.echo(f"📊 Deploying Starburst to cluster '{cluster}'...")

    if config_from_case:
        # Generate configuration based on customer case
        click.echo(f"🔍 Generating config from case: {config_from_case}")

    deploy_starburst(cluster, config_from_case, values_file)

    click.echo("✅ Starburst deployed successfully!")

@starburst.command("undeploy")
@click.argument("cluster")
def undeploy_starburst_cmd(cluster):
    """Remove Starburst from a local cluster"""
    undeploy_starburst(cluster)
    click.echo("✅ Starburst undeployed")

# ============================================================================
# SHARED INFRASTRUCTURE MANAGEMENT (Admin)
# ============================================================================

@cli.group()
def admin():
    """Administrative commands for shared infrastructure"""
    pass

@admin.command("provision")
@click.option("--component", help="Specific component to provision")
def provision_infrastructure(component):
    """Provision shared cloud infrastructure (Admin only)"""
    click.echo("🏗️ Provisioning shared infrastructure...")

    provision_shared_infrastructure(component)

    click.echo("✅ Shared infrastructure provisioned")

@admin.command("status")
def infrastructure_status():
    """Check status of shared infrastructure"""
    # Show status of shared databases, bastion hosts, etc.
    pass

if __name__ == "__main__":
    cli()