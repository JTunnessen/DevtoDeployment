# DevtoDeployment

![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Claude](https://img.shields.io/badge/powered%20by-Claude%20Sonnet-blueviolet)

A multi-agent pipeline that takes a natural language description of an application and autonomously generates, tests, scans, documents, and deploys it to Azure or GCP — with a human QA gate before production.

---

## How It Works

Describe your app in plain English. Nine coordinated AI agents handle everything from code generation to cloud deployment.

```
devtodeploy run "A task management web app with Kanban boards and team assignment" --cloud azure
```

| # | Agent | What happens |
|---|-------|-------------|
| 1 | **InputAgent** | Parses your description into a structured app specification |
| 2 | **DevelopmentAgent** | Generates full-stack code (FastAPI backend + HTML/JS frontend), self-checks up to 10 iterations |
| — | **Local Preview Loop** | Launches the app locally, opens your browser, and lets you request changes — repeat until satisfied |
| 3 | **FunctionalTestAgent** | Writes and runs pytest tests |
| 4 | **GitHubScanAgent** | Creates a GitHub repo, pushes code, runs Bandit + Safety static analysis, auto-remediates HIGH findings, **builds and pushes the Docker image** (built once here, reused by Stages 8 and 9) |
| 5 | **ReadmeAgent** | Generates a `README.md` for the app and pushes it to GitHub |
| 6 | **JenkinsAgent** | Triggers a Jenkins functional test job and waits for results |
| 7 | **CybersecAgent** | Generates `SECURITY.md` (OWASP Top 10) and `NIST_800_53.md` (SP 800-53 Rev5 control assessment) |
| 8 | **StagingAgent** | Provisions a staging environment via Terraform, deploys the pre-built Docker image, runs a k6 load test |
| — | **Human QA Gate** | Pauses here — review the staging URL, then run `devtodeploy approve <state.json>` to continue |
| 9 | **ProductionAgent** | Provisions production infrastructure, deploys the same Docker image, smoke tests, creates a GitHub Release |

The pipeline checkpoints state to disk after every stage. If anything fails or you reject staging, you can resume exactly where you left off.

---

## Prerequisites

**Required**
- Python 3.11+
- `git`
- An [Anthropic API key](https://console.anthropic.com/)
- A GitHub personal access token (with `repo` scope)

**Required for cloud deployment (Stages 4, 8–9)**
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (must be running when the pipeline executes)
- [Terraform](https://developer.hashicorp.com/terraform/install) >= 1.7
- Azure CLI (`az`) **or** GCP CLI (`gcloud`) depending on your target cloud
- See [docs/cloud_credentials.md](docs/cloud_credentials.md) for credential setup

**GCP additional setup**
```bash
# Enable required APIs
gcloud services enable run.googleapis.com containerregistry.googleapis.com \
  artifactregistry.googleapis.com cloudresourcemanager.googleapis.com \
  iam.googleapis.com --project=<your-project-id>

# Authenticate Docker to push to GCR
gcloud auth configure-docker gcr.io
```

**Required for load testing (Stage 8)**
- [k6](https://k6.io/docs/get-started/installation/) — if not installed, the load test is skipped and the pipeline continues

**Optional**
- A Jenkins server for automated functional testing (Stage 6). If not configured, Stage 6 is skipped automatically. See [docs/jenkins_setup.md](docs/jenkins_setup.md).

---

## Installation

```bash
git clone https://github.com/JTunnessen/DevtoDeployment.git
cd DevtoDeployment

pip install -e .
```

---

## Configuration

Copy the environment variable template and fill in your values:

```bash
cp .env.example .env
```

Minimum required variables:

```bash
ANTHROPIC_API_KEY=sk-ant-...
GITHUB_TOKEN=ghp_...
GITHUB_ORG=your-github-username-or-org
```

For cloud deployment, add the relevant Azure or GCP credentials. See [docs/cloud_credentials.md](docs/cloud_credentials.md) for step-by-step instructions.

---

## Usage

### Run the full pipeline

```bash
# Deploy to Azure (default)
devtodeploy run "A recipe sharing platform where users can submit recipes, search by ingredient, and generate shopping lists" --cloud azure

# Deploy to GCP
devtodeploy run "A personal finance tracker with income/expense logging, category breakdowns, and CSV export" --cloud gcp
```

### Run specific stages only (useful for testing)

```bash
# Run only stages 1, 2, and 3 (no GitHub, no cloud required)
devtodeploy run "A simple to-do API" --stages 1,2,3 --cloud azure
```

### Approve staging for production

After Stage 8 deploys to staging, the pipeline pauses. Review the app at the staging URL, then run:

```bash
devtodeploy approve /tmp/devtodeploy/<pipeline-id>/state.json
```

This shows the staging URL and app name, prompts for confirmation, and records approval in the state file. Then resume to deploy to production:

```bash
devtodeploy resume /tmp/devtodeploy/<pipeline-id>/state.json
```

### Resume after a rejection or failure

When a stage fails, the pipeline saves its full state to disk:

```bash
devtodeploy resume /tmp/devtodeploy/<pipeline-id>/state.json
```

### Check pipeline status

```bash
devtodeploy status /tmp/devtodeploy/<pipeline-id>/state.json
```

---

## Local Preview Loop

After Stage 2 generates your application, `devtodeploy` automatically starts it locally (port 8765) and opens it in your browser. You can then request as many rounds of changes as you like before the pipeline continues:

```
╔══════════════════════════════════════════════════════╗
║              INTERACTIVE PREVIEW                     ║
║                                                      ║
║  Your generated application will launch in your      ║
║  browser. Review it, request changes if needed,      ║
║  and type 'no' when you're happy to continue.        ║
╚══════════════════════════════════════════════════════╝

  App running at http://127.0.0.1:8765

  Would you like to make any changes or enhancements? [y/n]: y

  Change 1: Make the sidebar collapsible
  Change 2: Add a dark mode toggle
  Change 3: done

  Applying your changes — please wait…
  [app restarts, browser refreshes]

  Would you like to make any changes or enhancements? [y/n]: n

  Great! Continuing to the next pipeline stage…
```

Each round of changes is sent to Claude with the full current source as context. The pipeline proceeds to Stage 3 only when you type **no**.

To skip the preview entirely (for automated/CI runs):

```bash
devtodeploy run "..." --no-preview --cloud azure
```

---

## Human QA Approval Gate

After Stage 8 deploys to staging and runs the load test, the pipeline pauses. Visit the staging URL, then run the approve command:

```bash
devtodeploy approve /tmp/devtodeploy/<pipeline-id>/state.json
```

```
Staging URL: https://personal-finance-tracker-staging-abc123-uc.a.run.app
App: FinanceTracker
GitHub: https://github.com/your-org/personal-finance-tracker

Approve this staging deployment for production? [y/N]: y
✓ Approved. Resume the pipeline to deploy to production.

  devtodeploy resume /tmp/devtodeploy/<pipeline-id>/state.json
```

- **`y`** → records approval, resume deploys to production using the same Docker image
- **`N`** → records rejection, pipeline halts with a resumable checkpoint

---

## Security Documentation

Every generated application receives two security documents, automatically committed to its GitHub repository:

- **`SECURITY.md`** — OWASP Top 10 alignment checklist, Bandit + Safety findings summary, controls implemented, and hardening recommendations
- **`NIST_800_53.md`** — NIST SP 800-53 Rev5 control assessment covering Access Control (AC), Audit & Accountability (AU), Configuration Management (CM), Identification & Authentication (IA), System & Communications Protection (SC), System & Information Integrity (SI), Incident Response (IR), System & Services Acquisition (SA), and Risk Assessment (RA)

---

## Cloud Infrastructure

Terraform modules are included for four deployment targets, selectable via `DEPLOYMENT_TARGET` in your `.env`:

| Cloud | Target | Variable value |
|-------|--------|---------------|
| Azure | App Service | `app_service` |
| Azure | AKS | `aks` |
| GCP | Cloud Run | `cloud_run` |
| GCP | GKE | `gke` |

Staging uses cost-optimised SKUs (Azure B1 / Cloud Run min-instances=0). Production uses auto-scaling SKUs (Azure P2v3 / Cloud Run with min 2 instances).

---

## Load Testing

The k6 load test script (`loadtests/k6_script.js`) ramps up to `MAX_LOAD_TEST_USERS` (configurable in `.env`, default: 100) virtual users:

```
0 → min(MAX_VUS, 10) over 20s   (warm-up)
→ MAX_VUS over 40s               (ramp to peak)
Hold at MAX_VUS for 30s
Ramp down to 0 over 10s
```

Pass criteria: p95 response time < 2,000ms and error rate < 5%.

If k6 is not installed the load test is skipped automatically and the pipeline continues to the QA gate.

---

## Project Structure

```
DevtoDeployment/
├── devtodeploy/
│   ├── agents/          # One module per pipeline stage
│   ├── integrations/    # GitHub, Jenkins, Bandit + Safety, Terraform, Docker, k6 wrappers
│   ├── prompts/         # Claude prompt templates
│   ├── utils/           # Logging, retry, workspace helpers
│   ├── cli.py           # Typer CLI entry point
│   ├── config.py        # pydantic-settings config (reads from .env)
│   ├── orchestrator.py  # Sequential state machine + human approval gate
│   └── state.py         # PipelineState model (serialized after every stage)
├── terraform/
│   ├── modules/         # azure_appservice, azure_aks, gcp_cloudrun, gcp_gke
│   ├── staging/         # Staging environment config
│   └── production/      # Production environment config
├── loadtests/
│   └── k6_script.js     # k6 ramp-up test script
├── docs/
│   ├── jenkins_setup.md      # Jenkins setup guide + Jenkinsfile
│   └── cloud_credentials.md  # Azure & GCP credential setup
└── tests/               # Unit tests for state and orchestrator logic
```

---

## Running the Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

---

## License

MIT — see [LICENSE](LICENSE).
