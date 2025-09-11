# Platform CLI Tool - Local Development with Shared Cloud Data Sources

This Platform CLI tool enables support engineers and internal teams to create fast, local Kubernetes clusters for Starburst development with access to shared cloud data sources. The tool has been transformed from individual EKS cluster provisioning to a lightweight local-first architecture.

## Project Scope

**Platform CLI** provides local development environments with secure access to shared cloud data sources. The tool creates local Kind clusters with Starburst Enterprise Platform and connects to shared databases across AWS, GCP, and Azure through SSH tunnels and bastion hosts.

### Key Features
- **Local Kind Clusters**: Fast, lightweight Kubernetes environments (2-5 minutes vs 20-40 minutes)
- **Shared Infrastructure**: Cost-effective shared databases instead of individual resources per user
- **Multi-Cloud Support**: Connect to AWS, GCP, and Azure data sources
- **Starburst Ready**: Automated namespace and configuration generation for Starburst deployment
- **PostgreSQL Integration**: Built-in PostgreSQL database for Starburst metadata

## Repository Structure

```
platform-tool/
├── platform_cli.py                 # Main CLI entry point
├── config.py                       # User configuration and platform settings
├── requirements.txt                 # Python dependencies
├── README.md
├──
├── modules/                         # Core functionality modules
│   ├── __init__.py                 # Module exports and validation
│   ├── utils_module.py             # Shared utilities and AWS validation
│   ├── local_cluster_module.py     # Kind cluster management
│   ├── connectivity_module.py      # SSH tunnels and data sources
│   ├── starburst_module.py         # Starburst deployment preparation
│   ├── shared_data_module.py       # Shared data source management
│   └── pulumi_module.py            # Shared infrastructure management
│
├── helm/                           # Kubernetes deployment configs
│   └── values-templates/           # Generated Starburst values files
│
└── connectivity/                   # Connection management
    ├── ssh_configs/               # SSH tunnel configurations
    └── connection_profiles/       # Data source connection profiles
```

## Prerequisites

1. **Docker Desktop** with 4GB+ memory allocated
   ```bash
   # Check Docker status
   docker info
   ```

2. **Kind** (Kubernetes in Docker)
   ```bash
   # macOS
   brew install kind

   # Linux
   curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.20.0/kind-linux-amd64
   chmod +x ./kind && sudo mv ./kind /usr/local/bin/kind
   ```

3. **kubectl** (Kubernetes CLI)
   ```bash
   # macOS
   brew install kubectl

   # Linux
   curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
   ```

4. **Helm** (for Starburst deployment)
   ```bash
   # macOS
   brew install helm

   # Linux
   curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
   ```

5. **Python 3.8+**
   ```bash
   python3 --version
   ```

## Installation

### 1. Set Up Python Environment

```bash
# Clone the repository
git clone <repository-url>
cd platform-tool

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Make CLI Executable

```bash
chmod +x platform_cli.py

# Optional: Create symlink for easier access
ln -s $(pwd)/platform_cli.py /usr/local/bin/platform
```

## First Time Setup

### 1. Run Initial Configuration

```bash
# Configure your user profile and settings
python3 platform_cli.py setup
```

This will prompt you for:
- **Your name** (for user attribution)
- **Your email** (for usage tracking)
- **Organization** (e.g., 'starburst', 'customer-success')
- **Team** (e.g., 'support', 'engineering', 'sales')

Example setup session:
```
🔧 Platform Tool Initial Setup
This will configure your profile for local development.

👤 User Profile:
Your name: Matthew Duran
Your email: matthew.duran@starburstdata.com
Organization: starburst
Team: support

✅ Setup completed!
Configuration saved to ~/.platform/config.json
```

### 2. Verify Configuration

```bash
# View current configuration
python3 platform_cli.py config
```

## Quick Start

### 1. Create Your First Local Cluster

```bash
# Create a development cluster with PostgreSQL database
python3 platform_cli.py local create \
  --name devtest \
  --preset development
```

**What happens:**
1. Creates Kind cluster with control plane and worker nodes (2-5 minutes)
2. Installs NGINX ingress controller
3. Sets up local Docker registry
4. Deploys PostgreSQL database for Starburst
5. Configures kubectl context automatically

### 2. Prepare Cluster for Starburst

```bash
# Generate namespace and values file for Starburst deployment
python3 platform_cli.py starburst prepare \
  --cluster devtest \
  --preset development
```

This creates:
- Starburst namespace
- Helm values file with minimal resource requirements
- Connection configuration for local PostgreSQL

### 3. Deploy Starburst (Manual)

```bash
# Login to Starburst Harbor registry with your credentials
helm registry login harbor.starburstdata.net -u <username> -p <password>

# Deploy using the generated values file
helm upgrade --install starburst-devtest \
  oci://harbor.starburstdata.net/starburst-enterprise/starburst-enterprise \
  --namespace starburst \
  --values ~/.platform/helm/values-templates/starburst-devtest-development.yaml \
  --values your-registry-values.yaml
```

### 4. Access Your Cluster

```bash
# Check cluster status
kubectl get nodes
kubectl get pods -A

# Check PostgreSQL database
kubectl get pods -l app=postgres

# Access Starburst (after deployment)
kubectl port-forward service/starburst 8080:8080 -n starburst
# Then visit: http://localhost:8080
```

## Core Commands

### Local Cluster Management

```bash
# Create clusters
python3 platform_cli.py local create --name mytest --preset development
python3 platform_cli.py local create --name perftest --preset performance

# List clusters
python3 platform_cli.py local list

# Destroy clusters
python3 platform_cli.py local destroy --name mytest --force

# Get cluster information
kubectl config get-contexts
```

### Starburst Management

```bash
# Prepare cluster for Starburst
python3 platform_cli.py starburst prepare --cluster mytest --preset development

# Check deployment status
python3 platform_cli.py starburst status --cluster mytest

# Clean up preparation artifacts
python3 platform_cli.py starburst cleanup --cluster mytest
```

### Data Source Management

```bash
# List available shared data sources
python3 platform_cli.py connect list

# Enable connection to a data source
python3 platform_cli.py connect enable aws-postgres

# Check connection status
python3 platform_cli.py connect info aws-postgres

# Disable connection
python3 platform_cli.py connect disable aws-postgres
```

### Shared Infrastructure (Admin Only)

```bash
# Provision shared infrastructure (requires admin access)
python3 platform_cli.py admin provision --stacks shared-databases

# Check infrastructure status
python3 platform_cli.py admin status

# Destroy shared infrastructure
python3 platform_cli.py admin destroy --stacks shared-databases
```

## Cluster Presets

### Development (Default)
- **Resources**: Coordinator 1Gi, Worker 1.5Gi (~2.5GB total)
- **Use Case**: Basic development, testing features
- **Docker Memory**: 4GB+ recommended

### Performance
- **Resources**: Coordinator 2Gi, Worker 3Gi (~5GB total)
- **Use Case**: Query testing, moderate datasets
- **Docker Memory**: 6GB+ recommended

### Customer Reproduction
- **Resources**: Coordinator 4Gi, Workers 2x4Gi (~12GB total)
- **Use Case**: Reproducing customer issues
- **Docker Memory**: 8GB+ recommended

## Configuration Files

After setup, the tool creates:

```
~/.platform/
├── config.json                     # User configuration
├── local_clusters/                 # Cluster metadata
│   └── devtest/
│       ├── kind-config.yaml        # Kind cluster configuration
│       ├── metadata.json           # Cluster metadata
│       └── postgres_port_forward.pid # Port forwarding process
├── helm/                           # Helm configurations
│   └── values-templates/           # Generated Starburst values
├── connectivity/                   # Connection profiles
│   └── connection_profiles/        # Data source connections
└── usage/                         # Usage tracking logs
    └── usage_20250115.jsonl       # Daily usage logs
```

## Troubleshooting

### Common Issues

1. **"Port already allocated" during cluster creation**
   ```bash
   # Check what's using the ports
   docker ps

   # Clean up existing clusters
   python3 platform_cli.py local list
   python3 platform_cli.py local destroy --name <cluster> --force
   ```

2. **PostgreSQL connection issues**
   ```bash
   # Check PostgreSQL pod status
   kubectl get pods -l app=postgres

   # Check port forwarding
   ps aux | grep "kubectl.*port-forward"

   # Test connection
   psql -h localhost -p 5432 -U starburst -d starburst
   ```

3. **Insufficient Docker memory**
   ```bash
   # Check Docker settings
   # Docker Desktop > Settings > Resources > Memory
   # Increase to 4GB+ for development, 8GB+ for performance
   ```

4. **Starburst coordinator not starting**
   ```bash
   # Check coordinator logs
   kubectl logs deployment/coordinator -n starburst

   # Verify discovery URI configuration
   kubectl exec deployment/coordinator -n starburst -- cat /etc/starburst/config.properties
   ```

### Logs and Debugging

```bash
# Check cluster status
kubectl cluster-info --context kind-devtest

# View all pods across namespaces
kubectl get pods -A

# Check Starburst deployment
kubectl get pods -n starburst
kubectl logs -n starburst deployment/coordinator
kubectl logs -n starburst deployment/worker

# Check port forwarding processes
ps aux | grep port-forward

# View generated Starburst values
cat ~/.platform/helm/values-templates/starburst-devtest-development.yaml
```

## Docker Memory Configuration

For optimal performance, configure Docker Desktop memory:

- **Minimum**: 4GB (development preset)
- **Recommended**: 6GB (performance preset)
- **Ideal**: 8GB+ (customer-reproduction preset)

**To configure:**
1. Docker Desktop → Settings → Resources → Memory
2. Increase memory allocation
3. Apply & Restart Docker

## Next Steps

1. **Connect to shared data sources** using the connectivity module
2. **Deploy your own Starburst configurations** with custom catalogs
3. **Set up shared infrastructure** for team-wide data access
4. **Integrate with CI/CD pipelines** for automated testing
