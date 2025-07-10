#!/usr/bin/env python3
"""
Comprehensive test runner for Discord Bot WebUI.

This script provides various testing options including:
- Unit tests
- Integration tests
- Coverage reporting
- Performance testing
- Security scanning
"""

import os
import sys
import subprocess
import argparse
from pathlib import Path


def run_command(cmd, description="", fail_on_error=True):
    """Run a command and handle output."""
    print(f"\n{'='*60}")
    print(f"Running: {description or cmd}")
    print(f"{'='*60}")
    
    result = subprocess.run(cmd, shell=True, capture_output=False)
    
    if result.returncode != 0 and fail_on_error:
        print(f"❌ Failed: {description or cmd}")
        sys.exit(1)
    elif result.returncode == 0:
        print(f"✅ Success: {description or cmd}")
    else:
        print(f"⚠️  Warning: {description or cmd}")
    
    return result.returncode == 0


def setup_environment():
    """Set up test environment variables."""
    os.environ.update({
        'TESTING': 'true',
        'DATABASE_URL': 'sqlite:///:memory:',
        'REDIS_URL': 'redis://localhost:6379/15',
        'SECRET_KEY': 'test-secret-key',
        'JWT_SECRET_KEY': 'test-jwt-secret',
        'CELERY_TASK_ALWAYS_EAGER': 'true',
        'CELERY_TASK_EAGER_PROPAGATES': 'true',
    })


def run_unit_tests(verbose=False, coverage=False):
    """Run unit tests."""
    cmd = "pytest tests/unit/"
    
    if verbose:
        cmd += " -v"
    
    if coverage:
        cmd += " --cov=app --cov-report=html --cov-report=term-missing"
    
    return run_command(cmd, "Unit Tests")


def run_integration_tests(verbose=False, coverage=False):
    """Run integration tests."""
    cmd = "pytest tests/integration/"
    
    if verbose:
        cmd += " -v"
    
    if coverage:
        cmd += " --cov=app --cov-append --cov-report=html --cov-report=term-missing"
    
    return run_command(cmd, "Integration Tests")


def run_all_tests(verbose=False, coverage=False):
    """Run all tests."""
    cmd = "pytest"
    
    if verbose:
        cmd += " -v"
    
    if coverage:
        cmd += " --cov=app --cov-report=html --cov-report=term-missing"
    
    return run_command(cmd, "All Tests")


def run_linting():
    """Run code linting."""
    commands = [
        ("black --check --diff app/ tests/", "Black formatting check"),
        ("isort --check-only --diff app/ tests/", "Import sorting check"),
        ("flake8 app/ tests/", "Flake8 linting"),
    ]
    
    success = True
    for cmd, desc in commands:
        if not run_command(cmd, desc, fail_on_error=False):
            success = False
    
    return success


def run_security_scan():
    """Run security scanning."""
    commands = [
        ("bandit -r app/ -f json -o bandit-report.json", "Bandit security scan"),
        ("safety check", "Safety dependency check"),
    ]
    
    success = True
    for cmd, desc in commands:
        if not run_command(cmd, desc, fail_on_error=False):
            success = False
    
    return success


def run_performance_tests():
    """Run performance tests."""
    cmd = "pytest tests/ -m slow -v"
    return run_command(cmd, "Performance Tests", fail_on_error=False)


def generate_coverage_report():
    """Generate detailed coverage report."""
    commands = [
        ("coverage html", "Generate HTML coverage report"),
        ("coverage report --fail-under=70", "Coverage threshold check"),
    ]
    
    for cmd, desc in commands:
        run_command(cmd, desc, fail_on_error=False)
    
    print("\n📊 Coverage report generated in htmlcov/index.html")


def run_docker_tests():
    """Run tests in Docker environment."""
    commands = [
        ("docker-compose -f docker-compose.test.yml build", "Build test containers"),
        ("docker-compose -f docker-compose.test.yml up --abort-on-container-exit", "Run tests in Docker"),
        ("docker-compose -f docker-compose.test.yml down", "Clean up containers"),
    ]
    
    success = True
    for cmd, desc in commands:
        if not run_command(cmd, desc, fail_on_error=False):
            success = False
    
    return success


def main():
    """Main test runner."""
    parser = argparse.ArgumentParser(description="Discord Bot WebUI Test Runner")
    parser.add_argument("--unit", action="store_true", help="Run unit tests only")
    parser.add_argument("--integration", action="store_true", help="Run integration tests only")
    parser.add_argument("--all", action="store_true", help="Run all tests (default)")
    parser.add_argument("--coverage", action="store_true", help="Generate coverage report")
    parser.add_argument("--lint", action="store_true", help="Run linting checks")
    parser.add_argument("--security", action="store_true", help="Run security scans")
    parser.add_argument("--performance", action="store_true", help="Run performance tests")
    parser.add_argument("--docker", action="store_true", help="Run tests in Docker")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--full", action="store_true", help="Run full test suite")
    
    args = parser.parse_args()
    
    # Set up environment
    setup_environment()
    
    # Default to all tests if no specific test type is selected
    if not any([args.unit, args.integration, args.lint, args.security, args.performance, args.docker]):
        args.all = True
    
    success = True
    
    print("🚀 Starting Discord Bot WebUI Test Suite")
    print(f"Working directory: {os.getcwd()}")
    
    # Run selected tests
    if args.unit:
        success &= run_unit_tests(args.verbose, args.coverage)
    
    if args.integration:
        success &= run_integration_tests(args.verbose, args.coverage)
    
    if args.all:
        success &= run_all_tests(args.verbose, args.coverage)
    
    if args.lint or args.full:
        success &= run_linting()
    
    if args.security or args.full:
        success &= run_security_scan()
    
    if args.performance or args.full:
        success &= run_performance_tests()
    
    if args.docker:
        success &= run_docker_tests()
    
    # Generate coverage report if requested
    if args.coverage:
        generate_coverage_report()
    
    # Final summary
    print("\n" + "="*60)
    if success:
        print("🎉 All tests completed successfully!")
        sys.exit(0)
    else:
        print("❌ Some tests failed. Please check the output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()