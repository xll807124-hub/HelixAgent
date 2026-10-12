#!/usr/bin/env groovy

pipeline {
    agent any
    
    options {
        timeout(time: 30, unit: 'MINUTES')
        timestamps()
        buildDiscarder(logRotator(numToKeepStr: '30'))
    }
    
    environment {
        PYTHON_VERSION = '3.13'
        NODE_VERSION = '20'
        REPORTS_DIR = 'security-reports'
    }
    
    stages {
        stage('Prepare') {
            steps {
                script {
                    echo '=== Preparing environment ==='
                    sh '''
                        mkdir -p $REPORTS_DIR
                        python --version
                        npm --version
                    '''
                }
            }
        }
        
        stage('Install Dependencies') {
            parallel {
                stage('Python Dependencies') {
                    steps {
                        script {
                            sh '''
                                python -m pip install --upgrade pip
                                python -m pip install pip-audit
                                if [ -f requirements.txt ]; then
                                    pip install -r requirements.txt
                                fi
                            '''
                        }
                    }
                }
                
                stage('Node Dependencies') {
                    steps {
                        script {
                            sh '''
                                if [ -f package.json ]; then
                                    npm ci --legacy-peer-deps
                                fi
                            '''
                        }
                    }
                }
            }
        }
        
        stage('SCA Scanning') {
            parallel {
                stage('NPM Audit') {
                    steps {
                        script {
                            echo '=== Running NPM Audit ==='
                            sh '''
                                npm audit --json > $REPORTS_DIR/npm-audit.json || true
                                cat $REPORTS_DIR/npm-audit.json | python -m json.tool > $REPORTS_DIR/npm-audit-formatted.json || true
                            '''
                        }
                    }
                }
                
                stage('pip-audit') {
                    steps {
                        script {
                            echo '=== Running pip-audit ==='
                            sh '''
                                python -m pip_audit --format json > $REPORTS_DIR/pip-audit.json || true
                                python -m pip_audit --format markdown > $REPORTS_DIR/pip-audit.md || true
                            '''
                        }
                    }
                }
            }
        }
        
        stage('SCA Orchestration') {
            steps {
                script {
                    echo '=== Running SCA Orchestrator ==='
                    sh '''
                        python << 'PYTHON_EOF'
import json
import subprocess
from pathlib import Path

print("[*] Running SCA Orchestrator...")

results = {
    'timestamp': str(Path.cwd()),
    'npm_audit': None,
    'pip_audit': None,
    'orchestrator_decision': 'unknown',
    'details': {}
}

# Parse npm audit
npm_report = Path('security-reports/npm-audit.json')
if npm_report.exists():
    with open(npm_report) as f:
        npm_data = json.load(f)
    results['npm_audit'] = {
        'total': npm_data.get('metadata', {}).get('vulnerabilities', {}).get('total', 0),
        'critical': npm_data.get('metadata', {}).get('vulnerabilities', {}).get('critical', 0),
        'high': npm_data.get('metadata', {}).get('vulnerabilities', {}).get('high', 0),
    }

# Parse pip-audit
pip_report = Path('security-reports/pip-audit.json')
if pip_report.exists():
    with open(pip_report) as f:
        pip_data = json.load(f)
    vulnerable_packages = [d for d in pip_data.get('dependencies', []) if d.get('vulns')]
    results['pip_audit'] = {
        'vulnerable_packages': len(vulnerable_packages),
        'total_vulnerabilities': sum(len(d.get('vulns', [])) for d in pip_data.get('dependencies', []))
    }

# Make decision
npm_critical = results.get('npm_audit', {}).get('critical', 0)
pip_total = results.get('pip_audit', {}).get('total_vulnerabilities', 0)

if npm_critical > 0:
    results['orchestrator_decision'] = 'BLOCK'
    results['reason'] = f'Critical vulnerabilities detected in npm packages: {npm_critical}'
elif pip_total > 10:
    results['orchestrator_decision'] = 'REVIEW'
    results['reason'] = f'High number of pip vulnerabilities: {pip_total}'
else:
    results['orchestrator_decision'] = 'ALLOW'
    results['reason'] = 'No critical vulnerabilities detected'

# Save results
with open('security-reports/orchestrator-decision.json', 'w') as f:
    json.dump(results, f, indent=2)

print(json.dumps(results, indent=2))
PYTHON_EOF
                    '''
                }
            }
        }
        
        stage('Generate Report') {
            steps {
                script {
                    sh '''
                        echo "=== SCA Security Report ===" > $REPORTS_DIR/summary.txt
                        echo "" >> $REPORTS_DIR/summary.txt
                        echo "Generated at: $(date)" >> $REPORTS_DIR/summary.txt
                        echo "" >> $REPORTS_DIR/summary.txt
                        echo "--- NPM Audit ---" >> $REPORTS_DIR/summary.txt
                        cat $REPORTS_DIR/npm-audit-formatted.json >> $REPORTS_DIR/summary.txt || echo "No npm audit results" >> $REPORTS_DIR/summary.txt
                        echo "" >> $REPORTS_DIR/summary.txt
                        echo "--- pip-audit ---" >> $REPORTS_DIR/summary.txt
                        cat $REPORTS_DIR/pip-audit.md >> $REPORTS_DIR/summary.txt || echo "No pip audit results" >> $REPORTS_DIR/summary.txt
                        echo "" >> $REPORTS_DIR/summary.txt
                        echo "--- Decision ---" >> $REPORTS_DIR/summary.txt
                        cat $REPORTS_DIR/orchestrator-decision.json >> $REPORTS_DIR/summary.txt || echo "No orchestrator decision" >> $REPORTS_DIR/summary.txt
                    '''
                }
            }
        }
        
        stage('Archive Results') {
            steps {
                script {
                    archiveArtifacts artifacts: 'security-reports/**', allowEmptyArchive: true
                }
            }
        }
    }
    
    post {
        always {
            script {
                // Parse orchestrator decision
                def decisionFile = readFile 'security-reports/orchestrator-decision.json'
                def decision = readJSON text: decisionFile
                
                if (decision.orchestrator_decision == 'BLOCK') {
                    currentBuild.result = 'FAILURE'
                    echo "❌ SCA Scan FAILED - Critical vulnerabilities detected"
                } else if (decision.orchestrator_decision == 'REVIEW') {
                    currentBuild.result = 'UNSTABLE'
                    echo "⚠️ SCA Scan completed with warnings"
                } else {
                    currentBuild.result = 'SUCCESS'
                    echo "✅ SCA Scan passed"
                }
            }
        }
        
        failure {
            echo '❌ SCA Scan detected critical vulnerabilities'
            // Send notification
            emailext(
                subject: "❌ SCA Scan Failed: ${env.JOB_NAME} #${env.BUILD_NUMBER}",
                body: '''
                    Security scan detected critical vulnerabilities.
                    
                    Check details: ${BUILD_URL}
                ''',
                to: '${DEFAULT_RECIPIENTS}',
                attachmentsPattern: 'security-reports/**'
            )
        }
        
        unstable {
            echo '⚠️ SCA Scan completed with warnings'
            emailext(
                subject: "⚠️ SCA Scan Warning: ${env.JOB_NAME} #${env.BUILD_NUMBER}",
                body: '''
                    Security scan detected vulnerabilities that need review.
                    
                    Check details: ${BUILD_URL}
                ''',
                to: '${DEFAULT_RECIPIENTS}',
                attachmentsPattern: 'security-reports/**'
            )
        }
        
        success {
            echo '✅ SCA Scan passed'
        }
        
        cleanup {
            cleanWs()
        }
    }
}
