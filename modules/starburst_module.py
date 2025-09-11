"""
Starburst Enterprise Platform preparation module for local Kind clusters.
Handles cluster preparation, namespace setup, and catalog configuration templates.
Users deploy Starburst with their own Helm workflows and credentials.
"""

import click
import json
import subprocess
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

# Import from parent directory
import sys
sys.path.append(str(Path(__file__).parent.parent))
from config import PLATFORM_DIR

# Starburst and Helm configuration
HELM_DIR = PLATFORM_DIR / "helm"
VALUES_DIR = HELM_DIR / "values-templates"
STARBURST_NAMESPACE = "starburst"

# Ensure directories exist
HELM_DIR.mkdir(exist_ok=True)
VALUES_DIR.mkdir(exist_ok=True)

# Starburst deployment presets
STARBURST_PRESETS = {
    "development": {
        "name": "development",
        "description": "Lightweight development setup",
        "coordinator": {
            "resources": {
                "requests": {"memory": "1Gi", "cpu": "0.5"},
                "limits": {"memory": "2Gi", "cpu": "1"}
            }
        },
        "worker": {
            "replicas": 1,
            "resources": {
                "requests": {"memory": "2Gi", "cpu": "1"},
                "limits": {"memory": "4Gi", "cpu": "2"}
            }
        },
        "catalogs": ["memory", "jmx"]
    },
    "performance": {
        "name": "performance",
        "description": "Performance testing setup",
        "coordinator": {
            "resources": {
                "requests": {"memory": "2Gi", "cpu": "1"},
                "limits": {"memory": "4Gi", "cpu": "2"}
            }
        },
        "worker": {
            "replicas": 2,
            "resources": {
                "requests": {"memory": "4Gi", "cpu": "2"},
                "limits": {"memory": "8Gi", "cpu": "4"}
            }
        },
        "catalogs": ["memory", "jmx", "tpch"]
    },
    "customer-reproduction": {
        "name": "customer-reproduction",
        "description": "Customer environment reproduction",
        "coordinator": {
            "resources": {
                "requests": {"memory": "4Gi", "cpu": "2"},
                "limits": {"memory": "8Gi", "cpu": "4"}
            }
        },
        "worker": {
            "replicas": 3,
            "resources": {
                "requests": {"memory": "8Gi", "cpu": "4"},
                "limits": {"memory": "16Gi", "cpu": "8"}
            }
        },
        "catalogs": ["memory", "jmx", "tpch", "tpcds"]
    }
}

def check_kubectl_available() -> bool:
    """Check if kubectl is available and can connect to cluster"""
    try:
        result = subprocess.run(
            ["kubectl", "cluster-info"],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False

def run_kubectl_command(command: List[str], namespace: str = None, timeout: int = 60) -> Dict[str, Any]:
    """Execute kubectl commands with proper error handling"""
    if not check_kubectl_available():
        return {
            "success": False,
            "error": "kubectl not available or cannot connect to cluster",
            "stdout": "",
            "stderr": ""
        }
    
    full_command = ["kubectl"] + command
    if namespace and "--namespace" not in command and "-n" not in command:
        full_command.extend(["--namespace", namespace])
    
    try:
        result = subprocess.run(
            full_command,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": ' '.join(full_command)
        }
        
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"Command timed out after {timeout} seconds",
            "stdout": "",
            "stderr": ""
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to execute command: {str(e)}",
            "stdout": "",
            "stderr": ""
        }

def create_namespace() -> Dict[str, Any]:
    """Create Starburst namespace if it doesn't exist"""
    result = run_kubectl_command([
        "create", "namespace", STARBURST_NAMESPACE, "--dry-run=client", "-o", "yaml"
    ])
    
    if result["success"]:
        # Apply the namespace
        try:
            process = subprocess.Popen(
                ["kubectl", "apply", "-f", "-"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            stdout, stderr = process.communicate(input=result["stdout"])
            
            return {
                "success": process.returncode == 0,
                "stdout": stdout,
                "stderr": stderr
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to create namespace: {str(e)}"}
    
    return result

def generate_values_file(preset: str, connected_sources: List[str] = None, cluster_name: str = "default") -> Dict[str, Any]:
    """Generate Helm values file for Starburst deployment"""
    if preset not in STARBURST_PRESETS:
        return {
            "success": False,
            "error": f"Unknown preset: {preset}. Available: {list(STARBURST_PRESETS.keys())}"
        }
    
    if connected_sources is None:
        connected_sources = []
    
    preset_config = STARBURST_PRESETS[preset]
    
    # Base values template
    values_template = {
        "nameOverride": f"starburst-{cluster_name}",
        "coordinator": preset_config["coordinator"],
        "worker": preset_config["worker"],
        "catalogs": {},
        "ingress": {
            "enabled": True,
            "className": "nginx",
            "hosts": [
                {
                    "host": f"starburst-{cluster_name}.local",
                    "paths": [{"path": "/", "pathType": "Prefix"}]
                }
            ]
        },
        "service": {
            "type": "NodePort",
            "ports": {
                "http": {"port": 8080, "nodePort": 30080}
            }
        },
        # External PostgreSQL database for Starburst metadata
        "backend": {
            "type": "POSTGRESQL",
            "config": {
                "databaseUrl": "jdbc:postgresql://postgres:5432/starburst",
                "username": "starburst",
                "password": "starburst123"
            }
        }
    }
    
    # Add built-in catalogs
    for catalog in preset_config["catalogs"]:
        if catalog == "memory":
            values_template["catalogs"]["memory"] = {
                "connector": "memory"
            }
        elif catalog == "jmx":
            values_template["catalogs"]["jmx"] = {
                "connector": "jmx"
            }
        elif catalog == "tpch":
            values_template["catalogs"]["tpch"] = {
                "connector": "tpch"
            }
        elif catalog == "tpcds":
            values_template["catalogs"]["tpcds"] = {
                "connector": "tpcds"
            }
    
    # Add connected data sources as catalogs
    for source in connected_sources:
        if source.startswith("aws-postgres"):
            values_template["catalogs"]["postgres_shared"] = {
                "connector": "postgresql",
                "properties": {
                    "connection-url": "jdbc:postgresql://localhost:5433/shared_db",
                    "connection-user": "starburst",
                    "connection-password": "shared_password"
                }
            }
        elif source.startswith("aws-mysql"):
            values_template["catalogs"]["mysql_shared"] = {
                "connector": "mysql",
                "properties": {
                    "connection-url": "jdbc:mysql://localhost:3306/shared_db",
                    "connection-user": "starburst", 
                    "connection-password": "shared_password"
                }
            }
        elif source.startswith("gcp-bigquery"):
            values_template["catalogs"]["bigquery_shared"] = {
                "connector": "bigquery",
                "properties": {
                    "project-id": "starburst-shared-dev",
                    "parent-project-id": "starburst-shared-dev"
                }
            }
    
    # Save values file
    values_file = VALUES_DIR / f"starburst-{cluster_name}-{preset}.yaml"
    
    try:
        with open(values_file, 'w') as f:
            yaml.dump(values_template, f, default_flow_style=False)
        
        return {
            "success": True,
            "values_file": str(values_file),
            "preset": preset,
            "connected_sources": connected_sources,
            "catalogs": list(values_template["catalogs"].keys())
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to save values file: {str(e)}"
        }

def prepare_starburst_deployment(cluster_name: str, preset: str = "development", connected_sources: List[str] = None) -> Dict[str, Any]:
    """Prepare cluster for Starburst deployment (namespace, values file)"""
    if not check_kubectl_available():
        return {"success": False, "error": "kubectl not available or cannot connect to cluster"}
    
    if connected_sources is None:
        connected_sources = []
    
    click.echo(f"🚀 Preparing cluster for Starburst deployment...")
    click.echo(f"   Cluster: {cluster_name}")
    click.echo(f"   Preset: {preset}")
    click.echo(f"   Connected sources: {len(connected_sources)}")
    
    # Create namespace
    namespace_result = create_namespace()
    if not namespace_result["success"]:
        click.echo(f"⚠️  Warning: Could not create namespace: {namespace_result.get('error', 'Unknown error')}")
    
    # Generate values file
    values_result = generate_values_file(preset, connected_sources, cluster_name)
    if not values_result["success"]:
        return values_result
    
    click.echo(f"✅ Cluster prepared for Starburst deployment")
    click.echo(f"\n📋 Next Steps:")
    click.echo(f"   1. Login to Starburst Harbor registry:")
    click.echo(f"      helm registry login harbor.starburstdata.net -u <username> -p <password>")
    click.echo(f"   2. Deploy Starburst with your values file:")
    click.echo(f"      helm upgrade --install starburst-{cluster_name} oci://harbor.starburstdata.net/starburst-enterprise/starburst-enterprise \\")
    click.echo(f"        --namespace {STARBURST_NAMESPACE} \\")
    click.echo(f"        --values {values_result['values_file']} \\")
    click.echo(f"        --values your-registry-values.yaml")
    click.echo(f"   3. Check deployment status:")
    click.echo(f"      kubectl get pods -n {STARBURST_NAMESPACE}")
    
    return {
        "success": True,
        "cluster_name": cluster_name,
        "preset": preset,
        "namespace": STARBURST_NAMESPACE,
        "values_file": values_result["values_file"],
        "catalogs": values_result["catalogs"],
        "helm_commands": {
            "login": "helm registry login harbor.starburstdata.net -u <username> -p <password>",
            "deploy": f"helm upgrade --install starburst-{cluster_name} oci://harbor.starburstdata.net/starburst-enterprise/starburst-enterprise --namespace {STARBURST_NAMESPACE} --values {values_result['values_file']} --values your-registry-values.yaml",
            "status": f"kubectl get pods -n {STARBURST_NAMESPACE}"
        }
    }

def cleanup_starburst_preparation(cluster_name: str) -> Dict[str, Any]:
    """Clean up Starburst preparation artifacts (namespace, values files)"""
    if not check_kubectl_available():
        return {"success": False, "error": "kubectl not available or cannot connect to cluster"}
    
    click.echo(f"🗑️  Cleaning up Starburst preparation...")
    click.echo(f"   Cluster: {cluster_name}")
    
    # Clean up values files
    cleaned_files = []
    for file_path in VALUES_DIR.glob(f"starburst-{cluster_name}-*.yaml"):
        try:
            file_path.unlink()
            cleaned_files.append(str(file_path))
        except Exception as e:
            click.echo(f"⚠️  Could not remove values file {file_path}: {e}")
    
    # Optionally clean up namespace (but warn user first)
    click.echo(f"\n💡 To remove Starburst deployment and namespace:")
    click.echo(f"   helm uninstall starburst-{cluster_name} -n {STARBURST_NAMESPACE}")
    click.echo(f"   kubectl delete namespace {STARBURST_NAMESPACE}")
    
    return {
        "success": True,
        "cluster_name": cluster_name,
        "cleaned_files": cleaned_files,
        "manual_cleanup_commands": {
            "uninstall_helm": f"helm uninstall starburst-{cluster_name} -n {STARBURST_NAMESPACE}",
            "delete_namespace": f"kubectl delete namespace {STARBURST_NAMESPACE}"
        }
    }

def get_deployment_status(cluster_name: str) -> Dict[str, Any]:
    """Check status of Starburst deployment"""
    release_name = f"starburst-{cluster_name}"
    
    status_info = {
        "cluster_name": cluster_name,
        "release_name": release_name,
        "deployed": False,
        "pods": {},
        "services": {}
    }
    
    # Get pod status
    pods_result = run_kubectl_command([
        "get", "pods", "-o", "json", "-l", f"app.kubernetes.io/instance={release_name}"
    ], STARBURST_NAMESPACE)
    
    if pods_result["success"]:
        try:
            pods_data = json.loads(pods_result["stdout"])
            if pods_data.get("items"):
                status_info["deployed"] = True
                for pod in pods_data.get("items", []):
                    pod_name = pod["metadata"]["name"]
                    status_info["pods"][pod_name] = {
                        "status": pod["status"]["phase"],
                        "ready": all(
                            condition["status"] == "True" 
                            for condition in pod["status"].get("conditions", [])
                            if condition["type"] == "Ready"
                        ),
                        "restarts": sum(
                            container.get("restartCount", 0) 
                            for container in pod["status"].get("containerStatuses", [])
                        )
                    }
        except json.JSONDecodeError:
            status_info["pods"]["error"] = "Could not parse pod status"
    
    # Get service status
    services_result = run_kubectl_command([
        "get", "services", "-o", "json", "-l", f"app.kubernetes.io/instance={release_name}"
    ], STARBURST_NAMESPACE)
    
    if services_result["success"]:
        try:
            services_data = json.loads(services_result["stdout"])
            for service in services_data.get("items", []):
                service_name = service["metadata"]["name"]
                service_spec = service["spec"]
                status_info["services"][service_name] = {
                    "type": service_spec.get("type"),
                    "ports": [
                        {
                            "port": port.get("port"),
                            "target_port": port.get("targetPort"),
                            "node_port": port.get("nodePort")
                        }
                        for port in service_spec.get("ports", [])
                    ]
                }
        except json.JSONDecodeError:
            status_info["services"]["error"] = "Could not parse service status"
    
    return status_info

def list_starburst_preparations() -> Dict[str, Any]:
    """List all Starburst preparation artifacts"""
    preparations = {}
    
    for values_file in VALUES_DIR.glob("starburst-*.yaml"):
        try:
            # Parse filename: starburst-{cluster_name}-{preset}.yaml
            parts = values_file.stem.split("-")
            if len(parts) >= 3 and parts[0] == "starburst":
                cluster_name = parts[1]
                preset = parts[2]
                
                with open(values_file, 'r') as f:
                    values_data = yaml.safe_load(f)
                
                preparations[cluster_name] = {
                    "cluster_name": cluster_name,
                    "preset": preset,
                    "values_file": str(values_file),
                    "created": datetime.fromtimestamp(values_file.stat().st_mtime).isoformat(),
                    "catalogs": list(values_data.get("catalogs", {}).keys())
                }
        except Exception as e:
            click.echo(f"⚠️  Could not parse values file {values_file}: {e}")
    
    return {
        "success": True,
        "preparations": preparations,
        "count": len(preparations)
    }

# Maintain backward compatibility by aliasing the old function names
deploy_starburst = prepare_starburst_deployment
undeploy_starburst = cleanup_starburst_preparation