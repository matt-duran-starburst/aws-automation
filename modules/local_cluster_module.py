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
            "database": True,
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
            "database": True,
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
            "database": True,
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


def check_existing_clusters_and_ports(cluster_name):
    """Check for existing clusters and port conflicts"""
    result = {
        "can_create": True,
        "reason": "",
        "suggestions": []
    }
    
    # Check if Kind cluster with same name already exists
    try:
        kind_result = subprocess.run(
            ['kind', 'get', 'clusters'],
            capture_output=True, text=True, check=True
        )
        existing_clusters = kind_result.stdout.strip().split('\n') if kind_result.stdout.strip() else []
        
        if cluster_name in existing_clusters:
            result["can_create"] = False
            result["reason"] = f"Kind cluster '{cluster_name}' already exists"
            result["suggestions"] = [
                f"Use a different name: python3 platform_cli.py local create --name {cluster_name}-2 --preset development",
                f"Destroy existing cluster: python3 platform_cli.py local destroy --name {cluster_name} --force",
                "List existing clusters: python3 platform_cli.py local list"
            ]
            return result
            
    except subprocess.CalledProcessError:
        pass  # Kind might not have any clusters
    
    # Check for port conflicts on common ports
    ports_to_check = [80, 443, 8080, 5432, 3306]
    busy_ports = []
    
    for port in ports_to_check:
        if is_port_in_use(port):
            busy_ports.append(port)
    
    if busy_ports:
        result["can_create"] = False
        result["reason"] = f"Required ports are already in use: {', '.join(map(str, busy_ports))}"
        result["suggestions"] = [
            "Check what's using the ports: docker ps",
            "Stop other Kind clusters: kind delete cluster --name <cluster-name>",
            "Check for other Docker containers using these ports",
            f"List existing clusters: python3 platform_cli.py local list"
        ]
        
        # Try to identify what's using the ports
        try:
            docker_result = subprocess.run(
                ['docker', 'ps', '--format', 'table {{.Names}}\\t{{.Ports}}'],
                capture_output=True, text=True
            )
            if docker_result.returncode == 0 and docker_result.stdout.strip():
                click.echo("\n📋 Current Docker containers using ports:")
                for line in docker_result.stdout.strip().split('\n'):
                    if any(f":{port}->" in line or f"0.0.0.0:{port}" in line for port in busy_ports):
                        click.echo(f"   {line}")
        except Exception:
            pass
    
    return result


def is_port_in_use(port):
    """Check if a port is currently in use"""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', port))
            return result == 0
    except Exception:
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
    
    # Check for existing clusters and port conflicts
    existing_check = check_existing_clusters_and_ports(cluster_name)
    if not existing_check["can_create"]:
        click.echo(f"❌ Cannot create cluster: {existing_check['reason']}")
        if existing_check.get("suggestions"):
            click.echo("💡 Suggestions:")
            for suggestion in existing_check["suggestions"]:
                click.echo(f"   • {suggestion}")
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

        # Switch to the new cluster context automatically
        switch_context_result = switch_kubectl_context(cluster_name)
        
        # Save cluster metadata
        metadata = {
            "name": cluster_name,
            "preset": preset,
            "created_at": datetime.now().isoformat(),
            "kind_config_file": str(config_file),
            "features": preset_config["features"],
            "status": "running",
            "context_switched": switch_context_result
        }

        metadata_file = cluster_dir / "metadata.json"
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)

        # Show connection info
        click.echo(f"\n📋 Cluster Info:")
        click.echo(f"   Name: {cluster_name}")
        click.echo(f"   Preset: {preset}")
        click.echo(f"   Kubeconfig context: kind-{cluster_name}")
        click.echo(f"\n🔧 kubectl Commands:")
        click.echo(f"   Switch context: kubectl config use-context kind-{cluster_name}")
        click.echo(f"   Check nodes:    kubectl get nodes")
        click.echo(f"   Check pods:     kubectl get pods -A")
        click.echo(f"   Check database: kubectl get pods -l app=postgres")
        click.echo(f"\n💡 Next Steps:")
        click.echo(f"   Prepare Starburst: python3 platform_cli.py starburst prepare --cluster {cluster_name}")
        click.echo(f"   Enable data sources: python3 platform_cli.py connect enable <source>")
        if preset_config["features"].get("database"):
            click.echo(f"   PostgreSQL ready: localhost:30432 (user: starburst, db: starburst)")

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
    
    # Set up local database if enabled
    if preset_config["features"].get("database"):
        setup_local_database(cluster_name)


def switch_kubectl_context(cluster_name):
    """Switch kubectl context to the new Kind cluster"""
    context_name = f"kind-{cluster_name}"
    
    try:
        cmd = ['kubectl', 'config', 'use-context', context_name]
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        click.echo(f"✅ Switched kubectl context to: {context_name}")
        return True
    except subprocess.CalledProcessError as e:
        click.echo(f"⚠️ Warning: Failed to switch kubectl context: {e}")
        return False


def setup_local_database(cluster_name):
    """Set up a local PostgreSQL database for Starburst"""
    context = f"kind-{cluster_name}"
    
    try:
        click.echo(f"🗄️  Setting up PostgreSQL database for Starburst...")
        
        # Create PostgreSQL deployment
        postgres_yaml = f"""
apiVersion: apps/v1
kind: Deployment
metadata:
  name: postgres
  namespace: default
  labels:
    app: postgres
spec:
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
      - name: postgres
        image: postgres:15-alpine
        env:
        - name: POSTGRES_DB
          value: starburst
        - name: POSTGRES_USER
          value: starburst
        - name: POSTGRES_PASSWORD
          value: starburst123
        - name: PGDATA
          value: /var/lib/postgresql/data/pgdata
        ports:
        - containerPort: 5432
        volumeMounts:
        - name: postgres-storage
          mountPath: /var/lib/postgresql/data
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
      volumes:
      - name: postgres-storage
        emptyDir: {{}}
---
apiVersion: v1
kind: Service
metadata:
  name: postgres
  namespace: default
  labels:
    app: postgres
spec:
  type: NodePort
  ports:
  - port: 5432
    targetPort: 5432
    nodePort: 30432
  selector:
    app: postgres
"""
        
        # Apply PostgreSQL deployment
        postgres_process = subprocess.Popen(
            ['kubectl', 'apply', '--context', context, '-f', '-'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        stdout, stderr = postgres_process.communicate(input=postgres_yaml)
        
        if postgres_process.returncode == 0:
            click.echo("✅ PostgreSQL database deployed")
            
            # Wait for PostgreSQL to be ready
            click.echo("⏳ Waiting for PostgreSQL to be ready...")
            wait_cmd = [
                'kubectl', 'wait', '--context', context,
                '--for=condition=ready', 'pod',
                '--selector=app=postgres',
                '--timeout=120s'
            ]
            
            wait_result = subprocess.run(wait_cmd, capture_output=True, text=True, timeout=130)
            
            if wait_result.returncode == 0:
                click.echo("✅ PostgreSQL is ready")
                click.echo(f"   Connection: localhost:30432")
                click.echo(f"   Database: starburst")
                click.echo(f"   Username: starburst") 
                click.echo(f"   Password: starburst123")
            else:
                click.echo(f"⚠️  PostgreSQL deployment may still be starting: {wait_result.stderr}")
        else:
            click.echo(f"⚠️  Warning: Failed to deploy PostgreSQL: {stderr}")
            
    except Exception as e:
        click.echo(f"⚠️  Warning: Failed to set up PostgreSQL database: {e}")


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
    """Destroy a Kind cluster and clean up all associated resources"""
    
    click.echo(f"🗑️  Destroying Kind cluster: {cluster_name}")
    
    # Check if cluster exists first
    cluster_exists = check_cluster_exists(cluster_name)
    if not cluster_exists:
        click.echo(f"⚠️  Kind cluster '{cluster_name}' does not exist")
        click.echo("💡 Available clusters:")
        try:
            result = subprocess.run(['kind', 'get', 'clusters'], capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                for cluster in result.stdout.strip().split('\n'):
                    click.echo(f"   • {cluster}")
            else:
                click.echo("   • No Kind clusters found")
        except:
            click.echo("   • Unable to list clusters")
        return
    
    destruction_steps = []
    
    try:
        # Step 1: Delete Kind cluster
        click.echo("🔄 Deleting Kind cluster...")
        cmd = ['kind', 'delete', 'cluster', '--name', cluster_name]
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        destruction_steps.append("✅ Kind cluster deleted")
        
    except subprocess.CalledProcessError as e:
        click.echo(f"❌ Failed to delete Kind cluster: {e}")
        click.echo("💡 Manual cleanup commands:")
        click.echo(f"   kind delete cluster --name {cluster_name}")
        click.echo("   docker ps  # Check for remaining containers")
        raise click.Abort()
    
    # Step 2: Clean up local registry
    registry_name = f"{cluster_name}-registry"
    try:
        click.echo("🔄 Removing local registry...")
        registry_result = subprocess.run(
            ['docker', 'rm', '-f', registry_name],
            capture_output=True, text=True
        )
        if registry_result.returncode == 0:
            destruction_steps.append("✅ Local registry removed")
        else:
            destruction_steps.append("⚠️  No local registry found")
    except Exception as e:
        destruction_steps.append(f"⚠️  Registry cleanup warning: {e}")
    
    # Step 3: Clean up local metadata and files
    try:
        click.echo("🔄 Cleaning up local files...")
        cluster_dir = LOCAL_CLUSTERS_DIR / cluster_name
        if cluster_dir.exists():
            import shutil
            shutil.rmtree(cluster_dir)
            destruction_steps.append("✅ Local metadata cleaned")
        else:
            destruction_steps.append("⚠️  No local metadata found")
    except Exception as e:
        destruction_steps.append(f"⚠️  Metadata cleanup warning: {e}")
    
    # Step 4: Clean up any remaining Docker containers
    try:
        click.echo("🔄 Checking for orphaned containers...")
        container_check = subprocess.run([
            'docker', 'ps', '-a', '--filter', f'label=io.x-k8s.kind.cluster={cluster_name}', 
            '--format', '{{.Names}}'
        ], capture_output=True, text=True)
        
        if container_check.returncode == 0 and container_check.stdout.strip():
            orphaned_containers = container_check.stdout.strip().split('\n')
            click.echo(f"🧹 Removing {len(orphaned_containers)} orphaned containers...")
            for container in orphaned_containers:
                subprocess.run(['docker', 'rm', '-f', container], capture_output=True)
            destruction_steps.append(f"✅ {len(orphaned_containers)} orphaned containers removed")
        else:
            destruction_steps.append("✅ No orphaned containers found")
    except Exception as e:
        destruction_steps.append(f"⚠️  Container cleanup warning: {e}")
    
    # Step 5: Clean up any Helm releases (in case they exist)
    try:
        click.echo("🔄 Checking for Starburst installations...")
        helm_check = subprocess.run([
            'helm', 'list', '--all-namespaces', '--filter', f'starburst-{cluster_name}'
        ], capture_output=True, text=True)
        
        if helm_check.returncode == 0 and "starburst" in helm_check.stdout:
            click.echo("🧹 Found Starburst installation, cleaning up...")
            subprocess.run([
                'helm', 'uninstall', f'starburst-{cluster_name}', '-n', 'starburst'
            ], capture_output=True)
            destruction_steps.append("✅ Starburst installation removed")
        else:
            destruction_steps.append("✅ No Starburst installation found")
    except Exception:
        destruction_steps.append("⚠️  Helm cleanup skipped (helm not available)")
    
    # Summary
    click.echo(f"\n📋 Destruction Summary:")
    for step in destruction_steps:
        click.echo(f"   {step}")
    
    click.echo(f"\n✅ Cluster '{cluster_name}' completely destroyed")
    click.echo("💡 All ports should now be available for new clusters")


def check_cluster_exists(cluster_name):
    """Check if a Kind cluster exists"""
    try:
        result = subprocess.run(
            ['kind', 'get', 'clusters'],
            capture_output=True, text=True, check=True
        )
        existing_clusters = result.stdout.strip().split('\n') if result.stdout.strip() else []
        return cluster_name in existing_clusters
    except subprocess.CalledProcessError:
        return False


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