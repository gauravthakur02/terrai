# 🌍 TerraAI

> AI-powered Terraform assistant — manage cloud & on-prem infrastructure with natural language.

TerraAI is a feature-rich interactive CLI that lets you describe infrastructure in plain English and turns it into production-ready Terraform HCL. It auto-version-controls every change, maintains a human-readable infrastructure changelog, and lets you store state in any backend — local, cloud, or self-hosted.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Where Files Are Created](#where-files-are-created)
- [Where State Files Live](#where-state-files-live)
- [State Backend Options](#state-backend-options)
- [AI Model Support](#ai-model-support)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Commands Reference](#commands-reference)
- [TerraAI Chronicle](#terraai-chronicle-version-control)
- [Supported Providers](#supported-providers)
- [Project Structure](#project-structure)

---

## How It Works

```
You type:   "create an Azure VNet with 2 subnets in East US"
                        ↓
           TerraAI reads your workspace context
           (existing .tf files + current tfstate)
                        ↓
           LiteLLM sends prompt to your chosen AI model
           (GPT-4o / Claude / Gemini / Groq / Ollama …)
                        ↓
           AI returns structured JSON:
           { intent, hcl, resources, warnings, next_steps }
                        ↓
           TerraAI shows HCL with syntax highlighting
           You approve → saved to networking.tf
                        ↓
           Auto git commit  +  INFRASTRUCTURE.md updated
           + state snapshot taken  (TerraAI Chronicle)
                        ↓
           You run /plan → /apply
           Real Azure resources are created
```

---

## Where Files Are Created

All files are written to your **workspace directory**.

| Default | `./` — the current working directory when you launch `terraai` |
|---|---|
| Override at launch | `terraai --workspace /path/to/infra/project` |
| Override in session | `/workspace /path/to/infra/project` |
| Saved to config | `terraai configure --workspace /path/to/infra` |

### File layout inside a workspace

```
your-workspace/
│
├── main.tf                  ← provider block, variables (AI-generated)
├── networking.tf            ← VNets, subnets, NSGs (AI-generated)
├── compute.tf               ← VMs, scale sets (AI-generated)
├── storage.tf               ← storage accounts, blobs (AI-generated)
├── database.tf              ← SQL, Cosmos, Redis (AI-generated)
├── kubernetes.tf            ← AKS, Helm releases (AI-generated)
├── keyvault.tf              ← Key Vault, secrets (AI-generated)
├── appservice.tf            ← App Services, Functions (AI-generated)
├── backend.tf               ← state backend config (written by /backend set)
│
├── INFRASTRUCTURE.md        ← AI-authored changelog (auto-updated)
├── .gitignore               ← auto-created: excludes .terraform/, *.tfvars
│
├── .git/                    ← git repo (auto-initialized on first run)
│   └── …
│
└── .terraai/                ← TerraAI metadata (gitignored)
    ├── chronicle.json       ← machine-readable change history
    ├── state_config.json    ← backend configuration per environment
    ├── history              ← prompt_toolkit input history
    └── snapshots/
        ├── a1b2c3d4.json    ← tfstate snapshot after commit a1b2c3d4
        ├── e5f6a7b8.json    ← tfstate snapshot after commit e5f6a7b8
        └── …
```

### Which files get tracked in git?

| Tracked ✅ | `*.tf`, `backend.tf`, `INFRASTRUCTURE.md` |
|---|---|
| **Gitignored ❌** | `.terraform/`, `*.tfvars`, `tfplan`, `.terraai/`, `*.enc` |

> **Why exclude `.tfvars`?** Variable files often contain environment-specific values or secrets. Store them in a secrets manager (Azure Key Vault, AWS Secrets Manager) or pass via environment variables in CI.

---

## Where State Files Live

Terraform state (`terraform.tfstate`) records what infrastructure actually exists. TerraAI gives you **8 backend options** and supports **per-environment routing** — `dev`, `staging`, and `prod` can each point to a different backend.

### Configuring a backend

```bash
# In the interactive session:
/backend set azurerm     # launches interactive wizard
/backend set s3
/backend set pg          # self-hosted PostgreSQL
/backend set local       # local file (default)

# Switch environment:
/backend env prod        # switch to prod's backend
/backend list            # show all environments → backends

# After configuring, migrate existing state:
/backend migrate         # runs terraform init -migrate-state
```

### What the wizard does

1. Asks for provider-specific parameters (storage account name, bucket, connection string, etc.)
2. Writes `backend.tf` in your workspace with a valid Terraform backend block
3. Auto-commits `backend.tf` to git
4. Saves config to `.terraai/state_config.json` for session persistence

---

## State Backend Options

All backends are **open-source Terraform backends** — no Terraform Cloud, no proprietary lock-in.

| Icon | Backend | State file location | Locking | Best for |
|---|---|---|---|---|
| 🗂️ | `local` | `./terraform.tfstate` (workspace dir) | ❌ | Single dev, local testing |
| ☁️ | `azurerm` | Azure Blob Storage container | ✅ | Azure teams, MSI/SPN auth |
| 🟠 | `s3` | AWS S3 bucket + DynamoDB table | ✅ | AWS teams, IAM auth |
| 🔵 | `gcs` | Google Cloud Storage bucket | ✅ | GCP teams, SA auth |
| 🐘 | `pg` | PostgreSQL table (self-hosted) | ✅ | On-prem, no cloud required |
| 🔶 | `consul` | HashiCorp Consul KV store | ✅ | Service-mesh environments |
| ⎈ | `kubernetes` | Kubernetes Secret | ✅ | K8s-native workflows |
| 🌐 | `http` | Any REST endpoint | optional | Custom / BYO state server |

### Multi-environment State Federation

One workspace can have different backends per environment:

```
dev     →  🗂️  local       (./terraform.tfstate)
staging →  🐘  pg          (self-hosted PostgreSQL)
prod    →  ☁️  azurerm     (Azure Blob Storage, locked)
```

```bash
/backend env dev      # point state ops to local
/backend env prod     # point state ops to Azure Blob
/backend list         # show the full federation map
```

### Azure Blob Storage — example `backend.tf`

```hcl
terraform {
  backend "azurerm" {
    resource_group_name  = "rg-tfstate"
    storage_account_name = "stterraaidev"
    container_name       = "tfstate"
    key                  = "prod/terraform.tfstate"
  }
}
```

Auth is handled by environment variables — TerraAI never stores credentials:

```bash
export ARM_SUBSCRIPTION_ID="..."
export ARM_TENANT_ID="..."
export ARM_CLIENT_ID="..."
export ARM_CLIENT_SECRET="..."
# or use Managed Identity: ARM_USE_MSI=true
```

### PostgreSQL backend — fully on-prem

```hcl
terraform {
  backend "pg" {
    conn_str    = "postgres://user:pass@localhost/tfstate"
    schema_name = "terraform_state"
  }
}
```

```bash
export PG_CONN_STR="postgres://user:pass@localhost/tfstate"
```

---

## AI Model Support

TerraAI uses **LiteLLM** as the AI abstraction layer, giving you 100+ models with a single interface. No vendor lock-in.

### Free models (no cost)

| Model | Provider | Notes |
|---|---|---|
| `groq/llama3-70b-8192` | Groq | Fast, generous free tier |
| `groq/mixtral-8x7b-32768` | Groq | Fast, generous free tier |
| `gemini/gemini-1.5-flash` | Google | Free tier |
| `gemini/gemini-1.5-pro` | Google | Free tier |
| `ollama/llama3` | Ollama (local) | 100% free, runs on your machine |
| `ollama/codellama` | Ollama (local) | Code-optimized, offline |
| `ollama/mistral` | Ollama (local) | Fast local inference |

### Paid models

| Model | Provider |
|---|---|
| `gpt-4o` | OpenAI |
| `gpt-4o-mini` | OpenAI |
| `claude-sonnet-4-6` | Anthropic |
| `claude-haiku-4-5-20251001` | Anthropic |
| `azure/gpt-4o` | Azure OpenAI |

### Switching models

```bash
# At launch:
terraai --model groq/llama3-70b-8192

# In session:
/model ollama/codellama
/model gpt-4o

# Save as default:
terraai configure --model gpt-4o-mini
```

### API key setup

```bash
# OpenAI
export OPENAI_API_KEY="sk-..."

# Anthropic
export ANTHROPIC_API_KEY="sk-ant-..."

# Groq (free tier available at console.groq.com)
export GROQ_API_KEY="gsk_..."

# Google Gemini
export GOOGLE_API_KEY="AIza..."

# Ollama (no key needed — runs locally)
ollama pull codellama
terraai --model ollama/codellama --api-base http://localhost:11434
```

---

## Installation

### Requirements

- Python 3.10+
- Terraform CLI (`brew install terraform` / [download](https://developer.hashicorp.com/terraform/install))
- Git

### Install

```bash
git clone https://github.com/yourorg/terraai
cd terraai
./install.sh
```

The install script creates a `.venv`, installs dependencies, and creates a `./terraai` wrapper script.

### Optional: add to PATH

```bash
ln -s "$(pwd)/terraai" /usr/local/bin/terraai
```

---

## Quick Start

### With Groq (free, fast)

```bash
export GROQ_API_KEY=your_key_from_console_groq_com
./terraai --model groq/llama3-70b-8192 --provider azure
```

### With local Ollama (completely free, offline)

```bash
ollama pull codellama
./terraai --model ollama/codellama --api-base http://localhost:11434
```

### With OpenAI

```bash
export OPENAI_API_KEY=sk-...
./terraai --model gpt-4o --provider azure
```

### Example session

```
☁️ azure [my-infra] ❯ create an Azure resource group named rg-prod in East US

🤖 Thinking...

──────────────── ☁️ CREATE — Create Azure resource group 'rg-prod' in East US ──────────────────

Create Azure resource group 'rg-prod' in East US

┌─────────────────────────────────────────────────────────────┐
│ Resource                  │ Type                  │ Action  │
│ rg_prod                   │ azurerm_resource_group│ create  │
└─────────────────────────────────────────────────────────────┘

📄 Generated Terraform HCL
 1 │ resource "azurerm_resource_group" "rg_prod" {
 2 │   name     = "rg-prod"
 3 │   location = var.location
 4 │   tags     = var.tags
 5 │ }

Suggested file: resource_group.tf
💾 Save to resource_group.tf? (y=yes, r=rename, n=skip, p=plan after save): y

✅ Saved → /my-infra/resource_group.tf
📝 Auto-committed [a1b2c3d4] — /history to view

☁️ azure [my-infra] ❯ /plan
☁️ azure [my-infra] ❯ /apply
☁️ azure [my-infra] ❯ /history
☁️ azure [my-infra] ❯ /chronicle
```

---

## Commands Reference

### Infrastructure

| Command | Description |
|---|---|
| `/init` | Run `terraform init` — downloads providers |
| `/plan` | Run `terraform plan` — shows what will change |
| `/apply` | Apply changes (requires confirmation) |
| `/destroy` | Destroy all resources (requires typing `destroy`) |
| `/state` | Show current Terraform state |
| `/resources` | List all resources in state |
| `/outputs` | Show Terraform output values |
| `/files` | List `.tf` files in workspace |

### Version Control (Chronicle)

| Command | Description |
|---|---|
| `/history` | Git commit log for this workspace |
| `/chronicle` | AI-authored human-readable changelog |
| `/diff [sha1] [sha2]` | Show HCL diff between commits |
| `/rollback <sha>` | Restore `.tf` files from any past commit |
| `/tag <name> [msg]` | Tag a milestone (e.g. `v1.0-prod`) |
| `/tags` | List all tags |
| `/branch <name>` | Create and switch to a new git branch |
| `/branches` | List all branches |
| `/drift` | Detect out-of-band infrastructure changes |

### State Backend

| Command | Description |
|---|---|
| `/backend` | Show current backend config |
| `/backend set <type>` | Interactive wizard to configure a backend |
| `/backend env <name>` | Switch to a different environment's backend |
| `/backend list` | Show all environments → backend mappings |
| `/backend migrate` | Migrate state to newly configured backend |

### Configuration

| Command | Description |
|---|---|
| `/model <name>` | Switch AI model mid-session |
| `/workspace <path>` | Switch workspace directory |
| `/config` | Show current configuration |
| `/providers` | List supported Terraform providers |
| `/models` | List all supported AI models |
| `/clear` | Clear conversation history |
| `/help` | Show command reference |
| `/exit` | Exit TerraAI |

---

## TerraAI Chronicle (Version Control)

Every time you save AI-generated HCL, TerraAI automatically:

1. **Commits to git** with a semantic commit message written by the AI
   ```
   feat(azure): add VNet with 2 subnets for prod environment
   
     create: azurerm_virtual_network, azurerm_subnet
   
   Generated-By: TerraAI
   Timestamp: 2025-06-15T10:23:41Z
   ```

2. **Updates `INFRASTRUCTURE.md`** — a human-readable changelog that records:
   - What changed and why (your original request)
   - Which resources were affected
   - Warnings you should be aware of

3. **Snapshots state** to `.terraai/snapshots/<sha>.json` so drift detection can compare live infrastructure against a specific point in git history

This makes TerraAI's version control unique: git history + AI-authored explanations + state snapshots are all synchronized to the same commit SHA.

### Drift Detection

```bash
/drift
```

Compares your live `terraform.tfstate` against the last known snapshot. Reports:

- **Modified** — resources changed outside Terraform (manual portal edits, scripts)
- **Missing** — resources deleted outside Terraform
- **Extra** — resources created outside Terraform

---

## Supported Providers

| Provider | Example resources |
|---|---|
| `azure` | `azurerm_resource_group`, `azurerm_virtual_network`, `azurerm_storage_account`, `azurerm_kubernetes_cluster` |
| `aws` | `aws_vpc`, `aws_s3_bucket`, `aws_instance`, `aws_rds_cluster` |
| `gcp` | `google_compute_instance`, `google_storage_bucket`, `google_container_cluster` |
| `kubernetes` | `kubernetes_deployment`, `kubernetes_service`, `kubernetes_namespace` |
| `helm` | `helm_release` |
| `vmware` | `vsphere_virtual_machine`, `vsphere_folder` |

---

## Project Structure

```
terraai/
├── main.py                  # CLI entry point (Typer)
├── session.py               # Interactive REPL — command routing and AI flow
├── requirements.txt
├── install.sh
│
├── ai/
│   ├── client.py            # LiteLLM wrapper — multi-model AI client
│   └── prompts.py           # System prompt (Terraform expert persona)
│
├── config/
│   └── settings.py          # TerraAIConfig (Pydantic) — ~/.terraai/config.yaml
│
├── terraform/
│   ├── executor.py          # Terraform CLI bridge (init/plan/apply/destroy)
│   └── workspace.py         # .tf file management, context builder
│
├── vcs/                     # TerraAI Chronicle
│   ├── git_manager.py       # Git lifecycle: init, commit, log, diff, tags, branches
│   ├── changelog.py         # INFRASTRUCTURE.md + chronicle.json maintenance
│   └── drift_detector.py    # State snapshot + drift comparison
│
├── state/                   # State Backend Federation
│   ├── backends.py          # 8 backend types as typed dataclasses → HCL generators
│   └── manager.py           # Multi-env routing, BackendWizard, migration
│
├── ui/
│   ├── console.py           # Rich themed console + colour theme
│   └── panels.py            # HCL panels, plan tables, resource tables, badges
│
└── providers/
    └── __init__.py          # Provider HCL templates (Azure / AWS / GCP boilerplate)
```

---

## Configuration File

Saved to `~/.terraai/config.yaml`:

```yaml
model: gpt-4o-mini
default_provider: azure
workspace_dir: /path/to/your/infra
auto_approve: false
show_raw_hcl: true
terraform_bin: terraform
temperature: 0.1
```

Set with: `terraai configure --model gpt-4o --provider azure`

---

## License

MIT — open-source, no lock-in, no Terraform Cloud required.
