"""
Local cluster management module using Kind for lightweight Kubernetes clusters.
Replaces the heavy EKS cluster creation with fast local development environments.
"""

import click
import json
import subprocess
import yaml
from datetime import datetime
from pathlib import Path
import tempfile

# Import from parent directory
import sys
sys.path.append(str(Path(__file__).parent.parent))
from config import PlatformConfig, PLATFORM_DIR

# Local cluster configuration directory
LOCAL_CLUSTERS_DIR = PLATFORM_DIR / "local_clusters"
LOCAL_CLUSTERS_DIR.mkdir(exist_ok=True)

# Kind cluster presets optimized for different use cases
CLUSTER_PRESETS = {
    "development": {
        "description": "Lightweight development cluster",
        "nodes": {
            "control_plane": 1,
            "workers": 1
        },
        "features": {
            "ingress": True,
            "registry": True,
            "port_forwards": [80, 443, 8080, 5432, 3306]
        },
        "resources": {
            "cpu": "2",
            "memory": "4Gi"
        }
    },
    "performance": {
        "description": "Higher resource cluster for performance testing",
        "nodes": {
            "control_plane": 1,
            "workers": 2
        },
        "features": {
            "ingress": True,
            "registry": True,
            "port_forwards": [80, 443, 8080, 5432, 3306, 1521]
        },
        "resources": {
            "cpu": "4",
            "memory": "8Gi"
        }
    },
    "customer-reproduction": {
        "description": "Multi-node cluster for customer issue reproduction",
        "nodes": {
            "control_plane": 1,
            "workers": 3
        },
        "features": {
            "ingress": True,
            "registry": True,
            "monitoring": True,
            "port_forwards": [80, 443, 8080, 5432, 3306, 1521, 9000]
        },
        "resources": {
            "cpu": "6",
            "memory": "12Gi"
        }
    }
}


def check_kind_available():
    """Check if Kind is installed and available"""
    try:
        result = subprocess.run(['kind', 'version'],
                              capture_output=True, text=True, check=True)
        click.echo(f"✅ Kind available: {result.stdout.strip()}")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        click.echo("❌ Kind not found. Install with:")
        click.echo("   # macOS: brew install kind")
        click.echo("   # Linux: curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.20.0/kind-linux-amd64")
        click.echo("   # See: https://kind.sigs.k8s.io/docs/user/quick-start/")
        return False


def check_docker_available():
    """Check if Docker is running"""
    try:
        subprocess.run(['docker', 'ps'],
                      capture_output=True, text=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        click.echo("❌ Docker not running. Start Docker Desktop or docker daemon.")
        return False


def generate_kind_config(cluster_name, preset):
    """Generate Kind cluster configuration based on preset"""
    if preset not in CLUSTER_PRESETS:
        raise ValueError(f"Unknown preset: {preset}")

    preset_config = CLUSTER_PRESETS[preset]

    # Base Kind configuration
    kind_config = {
        "kind": "Cluster",
        "apiVersion": "kind.x-k8s.io/v1alpha4",
        "name": cluster_name,
        "nodes": []
    }

    # Add control plane node
    control_plane_node = {
        "role": "control-plane",
        "kubeadmConfigPatches": [
            """
kind: InitConfiguration
nodeRegistration:
  kubeletExtraArgs:
    node-labels: "ingress-ready=true"
"""
        ]
    }

    # Add port mappings for connectivity to external services
    if preset_config["features"].get("port_forwards"):
        control_plane_node["extraPortMappings"] = []
        for port in preset_config["features"]["port_forwards"]:
            control_plane_node["extraPortMappings"].append({
                "containerPort": port,
                "hostPort": port,
                "protocol": "TCP"
            })

    kind_config["nodes"].append(control_plane_node)

    # Add worker nodes
    for i in range(preset_config["nodes"]["workers"]):
        worker_node = {
            "role": "worker"
        }
        kind_config["nodes"].append(worker_node)

    return kind_config


def create_kind_cluster(cluster_name, preset="development"):
    """Create a Kind cluster with specified preset"""

    # Validate prerequisites
    if not check_docker_available():
        raise click.Abort()

    if not check_kind_available():
        raise click.Abort()

    if preset not in CLUSTER_PRESETS:
        raise ValueError(f"Unknown preset: {preset}. Available: {list(CLUSTER_PRESETS.keys())}")

    preset_config = CLUSTER_PRESETS[preset]

    click.echo(f"🚀 Creating Kind cluster '{cluster_name}' with preset '{preset}'")
    click.echo(f"📋 Configuration: {preset_config['description']}")
    click.echo(f"   Control plane: {preset_config['nodes']['control_plane']}")
    click.echo(f"   Workers: {preset_config['nodes']['workers']}")

    # Generate Kind configuration
    kind_config = generate_kind_config(cluster_name, preset)

    # Save Kind configuration
    cluster_dir = LOCAL_CLUSTERS_DIR / cluster_name
    cluster_dir.mkdir(exist_ok=True)

    config_file = cluster_dir / "kind-config.yaml"
    with open(config_file, 'w') as f:
        yaml.dump(kind_config, f, default_flow_style=False)

    try:
        # Create the cluster
        cmd = ['kind', 'create', 'cluster', '--name', cluster_name, '--config', str(config_file)]
        click.echo(f"🔄 Running: {' '.join(cmd)}")

        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        click.echo("✅ Kind cluster created successfully!")

        # Set up additional features
        setup_cluster_features(cluster_name, preset_config)

        # Save cluster metadata
        metadata = {
            "name": cluster_name,
            "preset": preset,
            "created_at": datetime.now().isoformat(),
            "kind_config_file": str(config_file),
            "features": preset_config["features"],
            "status": "running"
        }

        metadata_file = cluster_dir / "metadata.json"
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        # Show connection info
        click.echo(f"\n📋 Cluster Info:")
        click.echo(f"   Name: {cluster_name}")
        click.echo(f"   Preset: {preset}")
        click.echo(f"   Kubeconfig context: kind-{cluster_name}")
        click.echo(f"   Access: kubectl --context kind-{cluster_name} get nodes")

        return metadata

    except subprocess.CalledProcessError as e:
        click.echo(f"❌ Failed to create Kind cluster: {e}")
        click.echo(f"stderr: {e.stderr}")
        raise click.Abort()


def setup_cluster_features(cluster_name, preset_config):
    """Set up additional features like ingress controller"""

    context = f"kind-{cluster_name}"

    # Install ingress controller if enabled
    if preset_config["features"].get("ingress"):
        click.echo("🔗 Installing NGINX Ingress Controller...")

        ingress_cmd = [
            'kubectl', 'apply', '--context', context, '-f',
            'https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml'
        ]

        try:
            subprocess.run(ingress_cmd, check=True, capture_output=True)

            # Wait for ingress controller to be ready
            wait_cmd = [
                'kubectl', 'wait', '--context', context,
                '--namespace', 'ingress-nginx',
                '--for=condition=ready', 'pod',
                '--selector=app.kubernetes.io/component=controller',
                '--timeout=90s'
            ]
            subprocess.run(wait_cmd, check=True, capture_output=True)

            click.echo("✅ Ingress controller ready")

        except subprocess.CalledProcessError as e:
            click.echo(f"⚠️ Warning: Failed to set up ingress controller: {e}")

    # Set up local registry if enabled
    if preset_config["features"].get("registry"):
        setup_local_registry(cluster_name)


def setup_local_registry(cluster_name):
    """Set up a local Docker registry connected to the Kind cluster"""
    registry_name = f"{cluster_name}-registry"
    registry_port = "5001"  # Use different port to avoid conflicts

    try:
        # Check if registry already exists
        result = subprocess.run(['docker', 'ps', '-f', f'name={registry_name}'],
                              capture_output=True, text=True)

        if registry_name in result.stdout:
            click.echo(f"✅ Local registry already running: {registry_name}")
            return

        # Create local registry
        click.echo(f"📦 Creating local registry: {registry_name}")

        registry_cmd = [
            'docker', 'run', '-d', '--restart=always',
            '-p', f'{registry_port}:5000',
            '--name', registry_name,
            'registry:2'
        ]

        subprocess.run(registry_cmd, check=True, capture_output=True)

        # Connect registry to Kind network
        network_cmd = ['docker', 'network', 'connect', 'kind', registry_name]
        subprocess.run(network_cmd, check=True, capture_output=True)

        click.echo(f"✅ Local registry ready at localhost:{registry_port}")

    except subprocess.CalledProcessError as e:
        click.echo(f"⚠️ Warning: Failed to set up local registry: {e}")


def destroy_kind_cluster(cluster_name):
    """Destroy a Kind cluster and clean up resources"""

    click.echo(f"🗑️ Destroying Kind cluster: {cluster_name}")

    try:
        # Delete Kind cluster
        cmd = ['kind', 'delete', 'cluster', '--name', cluster_name]
        subprocess.run(cmd, check=True, capture_output=True)

        # Clean up local registry
        registry_name = f"{cluster_name}-registry"
        try:
            subprocess.run(['docker', 'rm', '-f', registry_name],
                          capture_output=True, check=False)
        except:
            pass  # Registry might not exist

        # Clean up local metadata
        cluster_dir = LOCAL_CLUSTERS_DIR / cluster_name
        if cluster_dir.exists():
            import shutil
            shutil.rmtree(cluster_dir)

        click.echo(f"✅ Cluster '{cluster_name}' destroyed")

    except subprocess.CalledProcessError as e:
        click.echo(f"❌ Failed to destroy cluster: {e}")
        raise click.Abort()


def list_local_clusters():
    """List all local Kind clusters managed by the platform"""

    clusters = []

    # Get Kind clusters
    try:
        result = subprocess.run(['kind', 'get', 'clusters'],
                              capture_output=True, text=True, check=True)
        kind_clusters = result.stdout.strip().split('\n') if result.stdout.strip() else []
    except subprocess.CalledProcessError:
        kind_clusters = []

    # Match with our metadata
    for cluster_name in kind_clusters:
        cluster_dir = LOCAL_CLUSTERS_DIR / cluster_name
        metadata_file = cluster_dir / "metadata.json"

        if metadata_file.exists():
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)

            # Check if cluster is actually running
            try:
                subprocess.run(['kubectl', 'cluster-info', '--context', f'kind-{cluster_name}'],
                             capture_output=True, check=True)
                metadata['running'] = True
            except subprocess.CalledProcessError:
                metadata['running'] = False

            clusters.append(metadata)
        else:
            # Kind cluster exists but no metadata - might be external
            clusters.append({
                'name': cluster_name,
                'preset': 'unknown',
                'running': True,
                'created_at': 'unknown'
            })

    return clusters


def get_cluster_info(cluster_name):
    """Get detailed information about a specific cluster"""

    cluster_dir = LOCAL_CLUSTERS_DIR / cluster_name
    metadata_file = cluster_dir / "metadata.json"

    if not metadata_file.exists():
        return None

    with open(metadata_file, 'r') as f:
        metadata = json.load(f)

    # Add runtime information
    context = f"kind-{cluster_name}"

    try:
        # Get node information
        nodes_result = subprocess.run([
            'kubectl', 'get', 'nodes', '--context', context, '-o', 'json'
        ], capture_output=True, text=True, check=True)

        nodes_data = json.loads(nodes_result.stdout)
        metadata['nodes'] = len(nodes_data['items'])
        metadata['node_details'] = [
            {
                'name': node['metadata']['name'],
                'status': node['status']['conditions'][-1]['type'],
                'version': node['status']['nodeInfo']['kubeletVersion']
            }
            for node in nodes_data['items']
        ]

    except subprocess.CalledProcessError:
        metadata['nodes'] = 'unknown'
        metadata['node_details'] = []

    return metadata