# Cloud Credentials Setup

This guide covers how to configure credentials for Azure and GCP so that
the `devtodeploy` pipeline can provision staging and production environments.

---

## Azure

### Option A: Service Principal (recommended for CI/CD)

```bash
# 1. Log in
az login

# 2. Create a service principal with Contributor role
az ad sp create-for-rbac \
  --name devtodeploy-sp \
  --role Contributor \
  --scopes /subscriptions/<YOUR_SUBSCRIPTION_ID> \
  --sdk-auth
```

This outputs JSON. Set the following environment variables in your `.env`:

```
AZURE_SUBSCRIPTION_ID=<subscriptionId from output>
AZURE_RESOURCE_GROUP=devtodeploy-rg
AZURE_REGION=eastus
```

Then authenticate Terraform via environment variables:

```bash
export ARM_CLIENT_ID="<appId>"
export ARM_CLIENT_SECRET="<password>"
export ARM_TENANT_ID="<tenant>"
export ARM_SUBSCRIPTION_ID="<subscriptionId>"
```

Add these to your `.env` file (they are read by Terraform automatically).

### Option B: Azure CLI (interactive — for local testing only)

```bash
az login
az account set --subscription <YOUR_SUBSCRIPTION_ID>
```

Terraform will use your logged-in CLI credentials automatically.

### Create the Resource Group

```bash
az group create --name devtodeploy-rg --location eastus
```

---

## GCP

### Option A: Service Account Key (recommended for CI/CD)

```bash
# 1. Create a service account
gcloud iam service-accounts create devtodeploy-sa \
  --project=<YOUR_PROJECT_ID> \
  --display-name="devtodeploy Service Account"

# 2. Grant Editor role (or narrower roles for production)
gcloud projects add-iam-policy-binding <YOUR_PROJECT_ID> \
  --member="serviceAccount:devtodeploy-sa@<YOUR_PROJECT_ID>.iam.gserviceaccount.com" \
  --role="roles/editor"

# 3. Download the key
gcloud iam service-accounts keys create ~/devtodeploy-sa.json \
  --iam-account=devtodeploy-sa@<YOUR_PROJECT_ID>.iam.gserviceaccount.com
```

Set in your `.env`:

```
GCP_PROJECT_ID=<YOUR_PROJECT_ID>
GCP_REGION=us-central1
GCP_CREDENTIALS_FILE=/home/you/devtodeploy-sa.json
```

Export for Terraform:

```bash
export GOOGLE_APPLICATION_CREDENTIALS="$GCP_CREDENTIALS_FILE"
```

### Option B: Application Default Credentials (local testing only)

```bash
gcloud auth application-default login
```

Terraform will use ADC automatically — no key file needed.

### Enable Required APIs

```bash
gcloud services enable \
  run.googleapis.com \
  container.googleapis.com \
  iam.googleapis.com \
  --project=<YOUR_PROJECT_ID>
```

---

## Verifying Credentials

Run a dry-run Terraform plan before executing the full pipeline:

```bash
cd terraform/staging
terraform init
terraform plan \
  -var="app_name=test" \
  -var="cloud_provider=azure" \
  -var="subscription_id=$AZURE_SUBSCRIPTION_ID" \
  -var="resource_group=$AZURE_RESOURCE_GROUP"
```

If the plan succeeds (shows resources to create), your credentials are working.
