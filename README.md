# Platform Tool MVP Setup Guide - EKS with eksctl

This guide will help you set up the MVP version of the Platform CLI tool for AWS EKS cluster deployments using eksctl.

## Repository Structure

Create your new repository with this simplified structure:

```
platform-tool/
├── platform_cli.py             # Main CLI tool
├── requirements.txt             # Python dependencies
├── README.md
├── .gitignore
└── .github/
    └── workflows/
        └── ci.yml
```

No Terraform modules needed! We're using eksctl directly for simplicity.

## Prerequisites

1. **AWS CLI with SSO configured**
   ```bash
   aws configure sso
   aws sso login --profile your-sandbox-profile
   ```

2. **eksctl installed**
   ```bash
   # macOS
   brew tap weaveworks/tap
   brew install weaveworks/tap/eksctl

   # Other platforms: https://eksctl.io/installation/
   ```

3. **Python 3.8+**
   ```bash
   python3 --version
   ```

4. **kubectl installed**
   ```bash
   # macOS
   brew install kubectl
   ```

5. **K9s (optional but recommended)**
   ```bash
   # macOS
   brew install k9s
   ```

## Installation Steps

### 1. Create Python Environment

```bash
# Clone your repository
git clone https://github.com/yourorg/platform-tool.git
cd platform-tool

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Create requirements.txt

```txt
click>=8.0.0
boto3>=1.26.0
botocore>=1.29.0
PyYAML>=6.0
```

### 3. Make CLI Tool Executable

```bash
chmod +x platform_cli.py

# Create symlink for easy access (optional)
ln -s $(pwd)/platform_cli.py /usr/local/bin/platform
```

## First Time Setup

### 1. Run Initial Setup

Before creating any deployments, you need to configure your profile and tagging information:

```bash
# Run the interactive setup
./platform_cli.py setup
```

This will prompt you for:
- **Your name** (for tagging)
- **Your email** (default owner for deployments)
- **Organization** (e.g., 'cs', 'sales', 'engineering')
- **Team** (e.g., 'tse', 'tam', 'cse', 'sa')
- **Default environment** (e.g., 'demo', 'sandbox')
- **Default AWS region** (e.g., 'us-east-1')
- **SSH key name** (e.g., 'your-key-name')

Example setup session:
```
🔧 Platform Tool Initial Setup
This will configure your profile and tagging information.

👤 User Profile:
Your name (for tagging): John Doe
Your email address: john.doe@company.com

🏢 Organization Information:
Organization/Department (e.g., 'cs', 'sales', 'engineering'): cs
Team (e.g., 'tse', 'tam', 'cse', 'sa'): tse

☁️ Default Settings:
Default environment: demo
Default AWS region: us-east-1
Default SSH key name: my-key

✅ Setup completed!
```

These tags will be automatically applied to all AWS resources you create:
```yaml
tags:
  cloud: aws
  environment: demo
  org: cs
  team: tse
  user: john-doe
  PlatformManaged: true
```

### 2. Verify Configuration

```bash
# View your current configuration
./platform_cli.py config
```

## First EKS Cluster Deployment

### 1. Create Your First EKS Cluster

```bash
# Ensure you've completed setup first
./platform_cli.py setup

# Create a development cluster (uses your configured email as owner)
./platform_cli.py create eks-cluster \
  --name "my-first-test" \
  --purpose "testing platform tool" \
  --expires-in 1d \
  --preset development
```

**What happens:**
1. Tool validates AWS credentials and checks setup completion
2. Uses your configured email as the default owner
3. Fetches available VPC subnets in your region
4. Prompts you to select private subnets (or use `--auto-select-subnets`)
5. Generates eksctl YAML configuration with your configured tags
6. Creates EKS cluster with 3 node groups: base, coordinator, workers
7. Takes ~10-15 minutes to complete

### 2. Alternative: Specify Different Owner

```bash
# Override the default owner email
./platform_cli.py create eks-cluster \
  --name "team-cluster" \
  --owner "different.person@company.com" \
  --preset performance \
  --expires-in 3d
```

### 3. Access Your Cluster

```bash
# Update kubeconfig (or use the built-in command)
./platform_cli.py update-kubeconfig my-deployment-id

# Access with K9s
k9s

# Or use kubectl
kubectl get nodes
kubectl get pods --all-namespaces
```

## Cost Management with Start/Stop

### Stop a Cluster (Scale to 0)

```bash
# Stop cluster to save costs when not in use
./platform_cli.py stop my-deployment-id

# This will:
# - Scale all node groups to 0 instances
# - Keep the cluster control plane running
# - Reduce costs to nearly $0 while stopped
```

### Start a Cluster (Scale Back Up)

```bash
# Start cluster when you need it again
./platform_cli.py start my-deployment-id

# This will:
# - Scale node groups back to their original sizes
# - Takes 2-3 minutes for nodes to be ready
# - Restore full functionality
```

### Check Status

```bash
# See which deployments are running vs stopped
./platform_cli.py list --running    # Only running deployments
./platform_cli.py list --stopped    # Only stopped deployments
./platform_cli.py list              # All deployments with status
```

## Common Commands

### Deployment Management
```bash
# List all deployments
./platform_cli.py list

# List your deployments only
./platform_cli.py list --owner your.email@company.com

# Show expiring deployments
./platform_cli.py list --expiring-soon

# Show only running clusters
./platform_cli.py list --status running

# Show only running (scaled up) vs stopped (scaled down)
./platform_cli.py list --running
./platform_cli.py list --stopped

# Extend a deployment
./platform_cli.py extend my-deployment-id --expires-in 3d

# Destroy a deployment
./platform_cli.py destroy my-deployment-id

# Force destroy without confirmation
./platform_cli.py destroy my-deployment-id --force
```

### Cost Management
```bash
# Stop cluster to save costs
./platform_cli.py stop my-deployment-id

# Start cluster when needed
./platform_cli.py start my-deployment-id

# Force start/stop without confirmation
./platform_cli.py stop my-deployment-id --force
./platform_cli.py start my-deployment-id --force
```

### Configuration
```bash
# View current configuration
./platform_cli.py config

# Update individual settings
./platform_cli.py config --set-region us-west-2
./platform_cli.py config --set-team tam
./platform_cli.py config --set-environment production

# Reset configuration and run setup again
./platform_cli.py config --reset

# Update kubeconfig for existing deployment
./platform_cli.py update-kubeconfig my-deployment-id
```

### Quick Examples
```bash
# Quick development cluster for testing
./platform_cli.py create eks-cluster --name "quick-test" --preset demo --expires-in 4h --auto-select-subnets

# Performance testing cluster
./platform_cli.py create eks-cluster --name "perf-test" --preset performance --expires-in 2d

# Stop all your clusters before weekend
./platform_cli.py list --owner me@company.com --running | grep "✅" | awk '{print $2}' | xargs -I {} ./platform_cli.py stop {} --force

# Start a specific cluster for Monday morning
./platform_cli.py start my-cluster-id
```

## Generated Files Structure

After first run:

```
~/.platform/
├── config.json                 # Platform configuration
└── deployments/
    └── your-first-test-2025-07-13/
        ├── cluster.yaml         # Generated eksctl config
        └── metadata.json        # Deployment metadata
```

## Configuration Presets

The tool includes three built-in presets:

### Development (default)
- Base: 1x m6g.xlarge (spot)
- Coordinator: 1x m6g.xlarge (spot)
- Workers: 1x m6g.xlarge, max 2 (spot)

### Performance
- Base: 1x m6g.xlarge (spot)
- Coordinator: 1x m6g.2xlarge (spot)
- Workers: 2x m6g.2xlarge, max 4 (spot)

### Demo
- Base: 1x t3.medium (spot)
- Coordinator: 1x t3.large (spot)
- Workers: 1x t3.large, max 2 (spot)

## Subnet Selection

The tool will:
1. Fetch all subnets in your specified region
2. Filter for private subnets (recommended for EKS)
3. Show you a list to choose from
4. Or use `--auto-select-subnets` to pick automatically

Example subnet selection:
```
📋 Available private subnets:
  1. Private Subnet 1 (subnet-abc123) - us-east-1a - 10.0.1.0/24
  2. Private Subnet 2 (subnet-def456) - us-east-1b - 10.0.2.0/24
  3. Private Subnet 3 (subnet-ghi789) - us-east-1c - 10.0.3.0/24

Select subnets (comma-separated numbers, e.g., 1,2,3): 1,2
```

## Troubleshooting

### Common Issues

1. **"No AWS credentials found"**
   ```bash
   aws sso login --profile your-sandbox-profile
   export AWS_PROFILE=your-sandbox-profile
   ```

2. **"eksctl command not found"**
   ```bash
   # Install eksctl first
   brew install eksctl  # macOS
   # or follow: https://eksctl.io/installation/
   ```

3. **"No private subnets found"**
   ```bash
   # Check your VPC has private subnets in the region
   aws ec2 describe-subnets --region us-east-1
   ```

4. **SSH key not found**
   ```bash
   # Update your default key name or create the key
   ./platform.py config --set-key-name your-existing-key-name
   ```

### Logs and Debugging

```bash
# Check deployment directory for details
ls ~/.platform/deployments/

# View generated eksctl config
cat ~/.platform/deployments/your-deployment-id/cluster.yaml

# Check AWS resources
aws eks describe-cluster --name your-deployment-id --region us-east-1

# eksctl logs
eksctl utils describe-stacks --region us-east-1 --cluster your-deployment-id
```

## Next Steps for Full Platform

Once the EKS MVP is working:

1. **Add Starburst deployment**
   ```bash
   # Future command structure
   ./platform.py deploy starburst --to-cluster my-cluster --values-file ./starburst-values.yaml
   ```

2. **Add Hive Metastore deployment**
   ```bash
   # Future command structure
   ./platform.py deploy hive-metastore --to-cluster my-cluster --config ./hive-config.yaml
   ```

3. **Add customer reproduction workflow**
   ```bash
   # Future command structure
   ./platform.py reproduce-customer-issue --starburst-values ./customer-values.yaml
   ```

4. **Add auto-cleanup automation**
5. **Create web interface**

## GitHub Actions (Optional)

Create `.github/workflows/ci.yml`:

```yaml
name: Platform Tool CI

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v3

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.9'

    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt

    - name: Run syntax checks
      run: |
        python -m py_compile platform_cli.py

    - name: Install eksctl
      run: |
        curl --silent --location "https://github.com/weaveworks/eksctl/releases/latest/download/eksctl_$(uname -s)_amd64.tar.gz" | tar xz -C /tmp
        sudo mv /tmp/eksctl /usr/local/bin

    - name: Validate tool help
      run: |
        python platform_cli.py --help
        python platform_cli.py create --help
```

## Example Usage Patterns

```bash
# Quick development cluster for testing
./platform.py create eks-cluster --name "quick-test" --owner "me@company.com" --preset demo --expires-in 4h --auto-select-subnets

# Performance testing cluster
./platform.py create eks-cluster --name "perf-test" --owner "me@company.com" --preset performance --expires-in 2d

# Using your own eksctl config
./platform.py create eks-cluster --name "custom" --owner "me@company.com" --eksctl-config ./my-cluster.yaml

# Check what's expiring soon
./platform.py list --expiring-soon

# Clean up everything for a user
./platform.py list --owner me@company.com | grep "my-deployment" | xargs -I {} ./platform.py destroy {} --force
```