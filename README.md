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
| 4 | **GitHubScanAgent** | Creates a GitHub repo, pushes code, runs Semgrep static analysis, auto-remediates HIGH findings |
| 5 | **ReadmeAgent** | Generates a `README.md` for the app and pushes it to GitHub |
| 6 | **JenkinsAgent** | Triggers a Jenkins functional test job and waits for results |
| 7 | **CybersecAgent** | Generates `SECURITY.md` (OWASP Top 10) and `NIST_800_53.md` (SP 800-53 Rev5 control assessment) |
| 8 | **StagingAgent** | Provisions a staging environment via Terraform, deploys the app, runs a k6 load test up to 10,000 concurrent users |
| — | **Human QA Gate** | Pauses here — presents the staging URL and metrics for your review |
| 9 | **ProductionAgent** | Provisions production infrastructure, deploys, smoke tests, and creates a GitHub Release |

The pipeline checkpoints state to disk after every stage. If anything fails or you reject staging, you can resume exactly where you left off.

---

## Prerequisites

**Required**
- Python 3.11+
- `git`
- An [Anthropic API key](https://console.anthropic.com/)
- A GitHub personal access token (with `repo` scope)

**Required for cloud deployment (Stages 8–9)**
- [Terraform](https://developer.hashicorp.com/terraform/install) >= 1.7
- Azure CLI (`az`) **or** GCP CLI (`gcloud`) depending on your target cloud
- See [docs/cloud_credentials.md](docs/cloud_credentials.md) for credential setup

**Required for load testing (Stage 8)**
- [k6](https://k6.io/docs/get-started/installation/)

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

### Resume after a rejection or failure

When you reject staging or a stage fails, the pipeline saves its full state to disk:

```bash
devtodeploy resume /tmp/devtodeploy/<pipeline-id>/state.json
```

Resuming after a staging rejection re-provisions staging, re-runs the load test, and re-prompts the QA gate.

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

After staging is deployed and load-tested, the pipeline pauses and displays a summary:

```
╔══════════════════════════════════════════════════════════════╗
║          STAGING QA APPROVAL REQUIRED                        ║
╠══════════════════════════════════════════════════════════════╣
║ App:          RecipeShare                                     ║
║ Staging URL:  https://recipeshare-staging.azurewebsites.net   ║
║ Load Test:    ✓ PASSED  (p95=312ms, error rate=0.2%)          ║
║ Static Scan:  ✓ PASSED  (0 HIGH, 1 MEDIUM, 4 LOW)             ║
║ Jenkins:      ✓ SUCCESS (34/34 tests passed)                  ║
╠══════════════════════════════════════════════════════════════╣
║  Please test the application at the URL above.               ║
║  Type 'approve' to deploy to production.                     ║
║  Type 'reject'  to shut down staging and stop the pipeline.  ║
╚══════════════════════════════════════════════════════════════╝
```

- **`approve`** → deploys to production
- **`reject`** → tears down the staging environment (to avoid cloud costs) and saves a resumable checkpoint

---

## Security Documentation

Every generated application receives two security documents, automatically committed to its GitHub repository:

- **`SECURITY.md`** — OWASP Top 10 alignment checklist, Semgrep findings summary, controls implemented, and hardening recommendations
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

The k6 load test script (`loadtests/k6_script.js`) ramps up to `MAX_LOAD_TEST_USERS` (default: 10,000) virtual users using this profile:

```
0 → 100 VUs over 30s   (warm-up)
100 → 10,000 VUs over 60s  (ramp to peak)
Hold at 10,000 VUs for 60s
Ramp down to 0 over 30s
```

Pass criteria: p95 response time < 2,000ms and error rate < 5%.

---

## Project Structure

```
DevtoDeployment/
├── devtodeploy/
│   ├── agents/          # One module per pipeline stage
│   ├── integrations/    # GitHub, Jenkins, Semgrep, Terraform, k6 wrappers
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
