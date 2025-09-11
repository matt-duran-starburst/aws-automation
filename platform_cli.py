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
        click.echo("📊 Preparing cluster for Starburst deployment...")
        result = deploy_starburst(name, preset)
        if not result["success"]:
            click.echo(f"⚠️  Starburst preparation failed: {result['error']}")

    click.echo(f"✅ Local cluster '{name}' ready!")
    click.echo(f"💡 Next steps:")
    click.echo(f"   • Enable data sources: python3 platform_cli.py connect enable <source>")
    if starburst:
        click.echo(f"   • Starburst namespace and values file prepared")
        click.echo(f"   • Deploy with your Harbor credentials using the provided Helm commands")
    else:
        click.echo(f"   • Prepare for Starburst: python3 platform_cli.py starburst prepare --cluster {name}")

@local.command("destroy")
@click.option("--name", required=True, help="Local cluster name to destroy")
@click.option("--force", is_flag=True, help="Skip confirmation")
def destroy_local_cluster(name, force):
    """Destroy a local Kind cluster"""
    if not force:
        click.confirm(f"Destroy local cluster '{name}'?", abort=True)

    destroy_kind_cluster(name)
    click.echo(f"✅ Local cluster '{name}' destroyed")

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

@starburst.command("prepare")
@click.option("--cluster", required=True, help="Target local cluster")
@click.option("--preset", default="development", 
              type=click.Choice(['development', 'performance', 'customer-reproduction']),
              help="Starburst deployment preset")
def prepare_starburst_cmd(cluster, preset):
    """Prepare cluster for Starburst deployment (namespace, values file)"""
    result = deploy_starburst(cluster, preset)
    if not result["success"]:
        click.echo(f"❌ Failed to prepare cluster: {result['error']}")
        raise click.Abort()

@starburst.command("cleanup")
@click.option("--cluster", required=True, help="Target local cluster")
def cleanup_starburst_cmd(cluster):
    """Clean up Starburst preparation artifacts"""
    result = undeploy_starburst(cluster)
    if not result["success"]:
        click.echo(f"❌ Failed to cleanup: {result['error']}")
        raise click.Abort()

@starburst.command("status")
@click.option("--cluster", required=True, help="Target local cluster")
def starburst_status_cmd(cluster):
    """Check Starburst deployment status"""
    from modules.starburst_module import get_deployment_status
    status = get_deployment_status(cluster)
    
    click.echo(f"📊 Starburst Status for cluster '{cluster}':")
    click.echo(f"   Deployed: {'✅ Yes' if status['deployed'] else '❌ No'}")
    
    if status["deployed"]:
        click.echo(f"   Pods: {len(status['pods'])}")
        for pod_name, pod_info in status["pods"].items():
            status_icon = "✅" if pod_info["ready"] else "❌"
            click.echo(f"     {status_icon} {pod_name}: {pod_info['status']}")
        
        click.echo(f"   Services: {len(status['services'])}")
        for svc_name, svc_info in status["services"].items():
            click.echo(f"     🔗 {svc_name}: {svc_info['type']}")
    
    click.echo(f"\n💡 To deploy Starburst manually:")
    click.echo(f"   helm registry login harbor.starburstdata.net -u <username> -p <password>")
    click.echo(f"   helm upgrade --install starburst-{cluster} oci://harbor.starburstdata.net/starburst-enterprise/starburst-enterprise --namespace starburst")

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