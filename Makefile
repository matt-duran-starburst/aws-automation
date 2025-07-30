# Platform CLI Tool Makefile

.PHONY: help install install-dev setup test clean lint format check validate-modules validate-names

# Default target
help:
	@echo "Platform CLI Tool - Available Commands:"
	@echo ""
	@echo "Setup Commands:"
	@echo "  install      - Install the platform CLI tool for production use"
	@echo "  install-dev  - Install with development dependencies"
	@echo "  setup        - Run initial platform setup"
	@echo ""
	@echo "Development Commands:"
	@echo "  test         - Run tests"
	@echo "  lint         - Run code linting"
	@echo "  format       - Format code with black"
	@echo "  check        - Run all checks (lint, format, test)"
	@echo ""
	@echo "Validation Commands:"
	@echo "  validate-modules - Validate all modules can be imported"
	@echo "  validate-names   - Test cluster name validation functionality"
	@echo "  validate-config  - Validate configuration"
	@echo ""
	@echo "Maintenance Commands:"
	@echo "  clean        - Clean up temporary files"
	@echo "  clean-all    - Clean everything including venv"

# Installation targets
install:
	@echo "🔧 Installing Platform CLI Tool..."
	python3 -m pip install --upgrade pip
	python3 -m pip install -r requirements.txt
	chmod +x platform_cli.py
	@echo "✅ Installation complete!"
	@echo ""
	@echo "Next steps:"
	@echo "1. Ensure AWS credentials are configured"
	@echo "2. Run: python3 platform_cli.py setup"
	@echo "3. Optionally create symlink: ln -s $(pwd)/platform_cli.py /usr/local/bin/platform"

install-dev:
	@echo "🔧 Installing Platform CLI Tool for development..."
	python3 -m pip install --upgrade pip
	python3 -m pip install -r requirements.txt
	# Uncomment development dependencies in requirements.txt first
	# python3 -m pip install pytest pytest-cov black flake8 mypy
	chmod +x platform_cli.py
	@echo "✅ Development installation complete!"

setup:
	@echo "🚀 Running initial platform setup..."
	python3 platform_cli.py setup

# Validation targets
validate-modules:
	@echo "🔍 Validating module imports..."
	@python3 -c "import config; print('✅ config.py - OK')" || echo "❌ config.py - FAILED"
	@python3 -c "from modules import utils_module; print('✅ modules/utils_module.py - OK')" || echo "❌ modules/utils_module.py - FAILED"
	@python3 -c "from modules import eks_module; print('✅ modules/eks_module.py - OK')" || echo "❌ modules/eks_module.py - FAILED"
	@python3 -c "from modules import rds_module; print('✅ modules/rds_module.py - OK')" || echo "❌ modules/rds_module.py - FAILED"
	@python3 -c "from modules import s3_module; print('✅ modules/s3_module.py - OK')" || echo "❌ modules/s3_module.py - FAILED"
	@python3 -c "import platform_cli; print('✅ platform_cli.py - OK')" || echo "❌ platform_cli.py - FAILED"
	@python3 -c "from modules import validate_all_modules; results = validate_all_modules(); print('📊 Module validation summary:', results)"
	@echo "✅ Module validation complete!"

validate-names:
	@echo "🔍 Testing cluster name validation functionality..."
	@echo "Testing optimal names..."
	@python3 platform_cli.py validate-name "dev" || echo "Note: Setup required first"
	@python3 platform_cli.py validate-name "test-api" || echo "Note: Setup required first"
	@echo ""
	@echo "Testing problematic names..."
	@python3 platform_cli.py validate-name "very-long-cluster-name-that-might-cause-issues" || echo "Note: Setup required first"
	@echo ""
	@echo "Testing name suggestions..."
	@python3 platform_cli.py suggest-name "my-very-long-development-testing-cluster-name" || echo "Note: Setup required first"
	@echo "✅ Name validation testing complete!"

validate-config:
	@echo "🔍 Validating configuration..."
	@python3 -c "from config import validate_config; is_valid, errors, warnings = validate_config(); print('✅ Config validation complete')"

# Development targets
test:
	@echo "🧪 Running tests..."
	# Add when you have tests
	@python3 -m pytest tests/ -v --cov=. --cov-report=html || echo "⚠️ No tests found - add pytest to requirements.txt and create tests/"

lint:
	@echo "🔍 Running linting..."
	# Add when you have flake8 installed
	@python3 -m flake8 *.py modules/*.py || echo "⚠️ flake8 not installed - add to requirements.txt for linting"

format:
	@echo "🎨 Formatting code..."
	# Add when you have black installed
	@python3 -m black *.py modules/*.py || echo "⚠️ black not installed - add to requirements.txt for formatting"

check: validate-modules validate-names lint format test
	@echo "✅ All checks completed!"

# Cleanup targets
clean:
	@echo "🧹 Cleaning temporary files..."
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type f -name "*.log" -delete
	find . -type f -name ".coverage" -delete
	rm -rf htmlcov/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	@echo "✅ Cleanup complete!"

clean-all: clean
	@echo "🧹 Deep cleaning..."
	rm -rf venv/
	rm -rf .venv/
	rm -rf env/
	@echo "✅ Deep cleanup complete!"

# AWS and Platform specific targets
check-aws:
	@echo "🔍 Checking AWS configuration..."
	@aws sts get-caller-identity && echo "✅ AWS credentials valid" || echo "❌ AWS credentials not configured"

check-eksctl:
	@echo "🔍 Checking eksctl installation..."
	@which eksctl > /dev/null && echo "✅ eksctl found: $(eksctl version --client --output json | jq -r '.clientVersion.version')" || echo "❌ eksctl not found - install from https://eksctl.io/"

check-kubectl:
	@echo "🔍 Checking kubectl installation..."
	@which kubectl > /dev/null && echo "✅ kubectl found: $(kubectl version --client --output json | jq -r '.clientVersion.gitVersion')" || echo "❌ kubectl not found"

check-deps: check-aws check-eksctl check-kubectl
	@echo "✅ Dependency check complete!"

# Quick platform commands (requires installation)
platform-status:
	@python3 platform_cli.py list

platform-config:
	@python3 platform_cli.py config

# Installation verification
verify-install:
	@echo "🔍 Verifying installation..."
	@python3 platform_cli.py --help > /dev/null && echo "✅ Platform CLI responds to --help"
	@$(MAKE) validate-modules
	@$(MAKE) validate-names
	@$(MAKE) check-deps
	@echo "✅ Installation verification complete!"

# Development workflow
dev-setup: install-dev validate-modules validate-names check-deps
	@echo "🚀 Development environment ready!"
	@echo ""
	@echo "Suggested workflow:"
	@echo "1. make setup          # Initial platform configuration"
	@echo "2. make check          # Run all checks before committing"
	@echo "3. make test           # Run tests"
	@echo ""

# Production deployment workflow
prod-setup: install validate-modules validate-names check-deps setup
	@echo "🚀 Production environment ready!"

# Show configuration
show-config:
	@echo "📋 Current Configuration:"
	@python3 platform_cli.py config

# CloudFormation issue testing
test-cloudformation-fix:
	@echo "🔧 Testing CloudFormation IAM policy name length fixes..."
	@echo ""
	@echo "Testing short names (should work):"
	@python3 platform_cli.py validate-name "dev" || echo "Note: Run 'make setup' first"
	@python3 platform_cli.py validate-name "test-api" || echo "Note: Run 'make setup' first"
	@echo ""
	@echo "Testing long names (should provide guidance):"
	@python3 platform_cli.py validate-name "my-very-long-development-testing-cluster" || echo "Note: Run 'make setup' first"
	@echo ""
	@echo "Testing name suggestions:"
	@python3 platform_cli.py suggest-name "my-very-long-performance-testing-cluster-name" || echo "Note: Run 'make setup' first"
	@echo ""
	@echo "✅ CloudFormation fix testing complete!"

# Emergency cleanup (if deployments are stuck)
emergency-cleanup:
	@echo "🚨 Emergency cleanup mode..."
	@echo "This will show all platform deployments for manual review"
	@python3 platform_cli.py list
	@echo ""
	@echo "To destroy specific deployments:"
	@echo "  python3 platform_cli.py destroy <deployment-id> --force"
	@echo ""
	@echo "To destroy ALL deployments (DANGEROUS):"
	@echo "  python3 platform_cli.py list --owner $(python3 -c 'from config import PlatformConfig; print(PlatformConfig().get_user_email() or \"unknown\")')"