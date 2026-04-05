# Jenkins Setup Guide

This guide walks you through configuring a Jenkins server to work with the
`devtodeploy` pipeline (Stage 6 — JenkinsAgent).

## Prerequisites

- Jenkins 2.440+ installed and accessible at a stable URL
- Jenkins plugins installed:
  - **Pipeline** (workflow-aggregator)
  - **Git** (git)
  - **JUnit** (junit)
  - **HTTP Request** (http_request) — optional, for webhook callbacks

## Step 1: Install Plugins

In Jenkins → Manage Jenkins → Plugin Manager → Available, search for and install:

```
workflow-aggregator
git
junit
```

Restart Jenkins after installation.

## Step 2: Create the Pipeline Job

1. Jenkins → New Item → Enter name: `devtodeploy-functional` → Select **Pipeline** → OK
2. Under **General**, check **This project is parameterized** and add:
   - **String Parameter**: Name = `GIT_REPO`, Default = `(empty)`
   - **String Parameter**: Name = `BRANCH`, Default = `main`
3. Under **Pipeline**, select **Pipeline script** and paste the Jenkinsfile below.
4. Click **Save**.

## Step 3: Jenkinsfile

Paste this into the Pipeline script field (or store as `Jenkinsfile` in the repo):

```groovy
pipeline {
    agent any

    parameters {
        string(name: 'GIT_REPO',  defaultValue: '', description: 'GitHub repository URL')
        string(name: 'BRANCH',    defaultValue: 'main', description: 'Branch to test')
    }

    environment {
        PYTHONPATH = "${WORKSPACE}"
    }

    stages {
        stage('Checkout') {
            steps {
                git url: params.GIT_REPO, branch: params.BRANCH
            }
        }

        stage('Install Dependencies') {
            steps {
                sh '''
                    python3 -m venv .venv
                    . .venv/bin/activate
                    if [ -f backend/requirements.txt ]; then
                        pip install -r backend/requirements.txt -q
                    elif [ -f requirements.txt ]; then
                        pip install -r requirements.txt -q
                    fi
                    pip install pytest pytest-cov httpx -q
                '''
            }
        }

        stage('Functional Tests') {
            steps {
                sh '''
                    . .venv/bin/activate
                    pytest tests/ \
                        --tb=short \
                        --junitxml=test-results.xml \
                        -v
                '''
            }
            post {
                always {
                    junit 'test-results.xml'
                }
            }
        }
    }

    post {
        always {
            cleanWs()
        }
    }
}
```

## Step 4: Create an API Token

1. Jenkins → top-right user menu → Configure
2. Under **API Token** → Add new Token → copy the value
3. Set in your `.env` file:

```
JENKINS_URL=http://your-jenkins:8080
JENKINS_USER=admin
JENKINS_API_TOKEN=<paste token here>
JENKINS_JOB_NAME=devtodeploy-functional
```

## Step 5: Verify

Run this command to verify the connection:

```bash
curl -u admin:<api_token> http://your-jenkins:8080/api/json
```

You should receive a JSON response. If you get a 403, check that:
- The user has the **Build** permission on the job
- CSRF protection is configured to allow API tokens (Manage Jenkins → Security)

## Skipping Jenkins

If `JENKINS_URL` contains `your-jenkins` or `JENKINS_API_TOKEN` is empty,
the pipeline **automatically skips** Stage 6 with a warning and continues.
No error is thrown. Once Jenkins is configured, re-run or resume the pipeline.
