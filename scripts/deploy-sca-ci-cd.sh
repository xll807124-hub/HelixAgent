#!/bin/bash
# SCA CI/CD Integration Deployment Script
# Deploys SCA scanning to GitHub Actions, GitLab CI, or Jenkins

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(git rev-parse --show-toplevel)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Detect CI platform
detect_platform() {
    if [ -f "$PROJECT_ROOT/.github/workflows/sca-security-scan.yml" ]; then
        echo "github"
    elif [ -f "$PROJECT_ROOT/.gitlab-ci.yml" ]; then
        echo "gitlab"
    elif [ -f "$PROJECT_ROOT/Jenkinsfile" ]; then
        echo "jenkins"
    else
        echo "unknown"
    fi
}

# Deploy to GitHub Actions
deploy_github() {
    log_info "Deploying SCA scanning to GitHub Actions..."
    
    if [ ! -f "$PROJECT_ROOT/.github/workflows/sca-security-scan.yml" ]; then
        log_error "GitHub Actions workflow not found"
        return 1
    fi
    
    log_info "Verifying GitHub Actions workflow..."
    # Check if workflow file is valid
    if python -m json.tool < <(grep -o '".*"' "$PROJECT_ROOT/.github/workflows/sca-security-scan.yml" | head -1) 2>/dev/null; then
        log_warning "Workflow file is YAML, manual validation recommended"
    fi
    
    log_info "GitHub Actions files:"
    ls -la "$PROJECT_ROOT/.github/workflows/sca-security-scan.yml"
    
    log_info "Next steps:"
    echo "  1. Push to GitHub: git push origin main"
    echo "  2. Check Actions tab: https://github.com/<owner>/<repo>/actions"
    echo "  3. (Optional) Configure secrets in Settings → Secrets and variables"
    
    log_success "GitHub Actions deployment ready!"
}

# Deploy to GitLab CI
deploy_gitlab() {
    log_info "Deploying SCA scanning to GitLab CI..."
    
    if [ ! -f "$PROJECT_ROOT/.gitlab-ci.yml" ]; then
        log_error "GitLab CI config not found"
        return 1
    fi
    
    log_info "Verifying .gitlab-ci.yml syntax..."
    # Basic syntax check
    if grep -q "stages:" "$PROJECT_ROOT/.gitlab-ci.yml" && \
       grep -q "sca:scan" "$PROJECT_ROOT/.gitlab-ci.yml"; then
        log_success ".gitlab-ci.yml structure validated"
    else
        log_warning ".gitlab-ci.yml may have issues"
    fi
    
    log_info "GitLab CI files:"
    ls -la "$PROJECT_ROOT/.gitlab-ci.yml"
    
    log_info "Next steps:"
    echo "  1. Push to GitLab: git push origin main"
    echo "  2. Configure CI/CD variables in GitLab project"
    echo "  3. Check Pipelines tab: https://gitlab.com/<group>/<project>/-/pipelines"
    echo "  4. (Optional) Configure GitLab Runner if needed"
    
    log_success "GitLab CI deployment ready!"
}

# Deploy to Jenkins
deploy_jenkins() {
    log_info "Deploying SCA scanning to Jenkins..."
    
    if [ ! -f "$PROJECT_ROOT/Jenkinsfile" ]; then
        log_error "Jenkinsfile not found"
        return 1
    fi
    
    log_info "Verifying Jenkinsfile syntax..."
    # Check for required sections
    if grep -q "pipeline {" "$PROJECT_ROOT/Jenkinsfile" && \
       grep -q "stages {" "$PROJECT_ROOT/Jenkinsfile"; then
        log_success "Jenkinsfile structure validated"
    else
        log_warning "Jenkinsfile may have issues"
    fi
    
    log_info "Jenkins files:"
    ls -la "$PROJECT_ROOT/Jenkinsfile"
    
    log_info "Next steps:"
    echo "  1. Commit and push: git push origin main"
    echo "  2. In Jenkins UI, create new Pipeline job"
    echo "  3. Configure Pipeline script from SCM"
    echo "  4. Set repository URL and credentials"
    echo "  5. Set script path to 'Jenkinsfile'"
    echo "  6. Configure build triggers (Push, PR, Periodic)"
    
    log_success "Jenkins deployment ready!"
}

# Validate environment
validate_environment() {
    log_info "Validating environment..."
    
    # Check for required tools
    local tools_ok=true
    
    if ! command -v git &> /dev/null; then
        log_error "git not found"
        tools_ok=false
    fi
    
    if ! command -v python &> /dev/null; then
        log_error "python not found"
        tools_ok=false
    fi
    
    if ! command -v npm &> /dev/null; then
        log_warning "npm not found (required for npm audit)"
    fi
    
    if ! python -m pip show pip-audit &> /dev/null; then
        log_warning "pip-audit not installed"
        echo "  Install with: python -m pip install pip-audit"
    fi
    
    if [ "$tools_ok" = false ]; then
        log_error "Missing required tools"
        return 1
    fi
    
    log_success "Environment validation passed"
}

# Create policy file if it doesn't exist
create_policy() {
    local policy_dir="$PROJECT_ROOT/security/policies"
    local policy_file="$policy_dir/sca-policy.json"
    
    if [ ! -f "$policy_file" ]; then
        log_info "Creating default SCA policy..."
        mkdir -p "$policy_dir"
        cat > "$policy_file" << 'EOF'
{
  "version": "1.0",
  "vulnerability_thresholds": {
    "npm": {
      "critical": { "threshold": 0, "action": "block" },
      "high": { "threshold": 3, "action": "review" }
    },
    "pip": {
      "critical": { "threshold": 0, "action": "block" },
      "high": { "threshold": 5, "action": "review" }
    }
  }
}
EOF
        log_success "Policy file created: $policy_file"
    else
        log_info "Policy file already exists: $policy_file"
    fi
}

# Main menu
show_menu() {
    echo ""
    echo "SCA CI/CD Integration Deployment"
    echo "=================================="
    echo "1) Auto-detect and deploy"
    echo "2) Deploy to GitHub Actions"
    echo "3) Deploy to GitLab CI"
    echo "4) Deploy to Jenkins"
    echo "5) Validate all configurations"
    echo "6) Create/update policy file"
    echo "7) Exit"
    echo ""
    read -p "Select option: " choice
}

# Main script
main() {
    log_info "SCA CI/CD Integration Deployment Tool"
    log_info "Project root: $PROJECT_ROOT"
    
    validate_environment || exit 1
    
    while true; do
        show_menu
        case $choice in
            1)
                create_policy
                platform=$(detect_platform)
                case $platform in
                    github)
                        deploy_github
                        ;;
                    gitlab)
                        deploy_gitlab
                        ;;
                    jenkins)
                        deploy_jenkins
                        ;;
                    *)
                        log_warning "Could not detect platform. All configuration files available."
                        log_info "Files found:"
                        [ -f "$PROJECT_ROOT/.github/workflows/sca-security-scan.yml" ] && echo "  ✓ .github/workflows/sca-security-scan.yml"
                        [ -f "$PROJECT_ROOT/.gitlab-ci.yml" ] && echo "  ✓ .gitlab-ci.yml"
                        [ -f "$PROJECT_ROOT/Jenkinsfile" ] && echo "  ✓ Jenkinsfile"
                        ;;
                esac
                ;;
            2)
                create_policy
                deploy_github
                ;;
            3)
                create_policy
                deploy_gitlab
                ;;
            4)
                create_policy
                deploy_jenkins
                ;;
            5)
                log_info "Validating configurations..."
                [ -f "$PROJECT_ROOT/.github/workflows/sca-security-scan.yml" ] && log_success "GitHub Actions workflow found"
                [ -f "$PROJECT_ROOT/.gitlab-ci.yml" ] && log_success "GitLab CI config found"
                [ -f "$PROJECT_ROOT/Jenkinsfile" ] && log_success "Jenkinsfile found"
                [ -f "$PROJECT_ROOT/security/policies/sca-policy.json" ] && log_success "SCA policy found"
                ;;
            6)
                create_policy
                ;;
            7)
                log_info "Exiting..."
                exit 0
                ;;
            *)
                log_error "Invalid option"
                ;;
        esac
    done
}

# Run main if script is executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
