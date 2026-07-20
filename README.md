# 🌍 TerraAI

> AI-powered Terraform assistant — manage cloud & on-prem infrastructure with natural language.

TerraAI is a feature-rich interactive CLI that lets you describe infrastructure in plain English and turns it into production-ready Terraform HCL. It auto-version-controls every change with AI-written semantic commits, maintains a human-readable infrastructure changelog (the Chronicle), stores credentials securely in your OS keyring, and supports 8 state backends — local, cloud, or fully on-prem.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [First-Run Setup Wizard](#first-run-setup-wizard)
- [Credential Storage](#credential-storage)
- [Azure Authentication](#azure-authentication)
- [Architecture Diagram](#architecture-diagram)
- [TerraAI Chronicle](#terraai-chronicle-version-control)
- [State Backend Options](#state-backend-options)
- [AI Model Support](#ai-model-support)
- [Commands Reference](#commands-reference)
- [Workspace File Layout](#workspace-file-layout)
- [Supported Providers](#supported-providers)
- [Project Structure](#project-structure)
- [Building Executables](#building-executables)
- [Configuration File](#configuration-file)

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
                        ↓
           /diagram → interactive architecture diagram
           shows resources and their relationships
```

---

## Installation

### Requirements

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.10+ | `brew install python@3.12` or [python.org](https://python.org) |
| Terraform CLI | 1.3+ | `brew install terraform` or [hashicorp.com](https://developer.hashicorp.com/terraform/install) |
| Git | 2.x | `brew install git` |

### Option A — Install from source

```bash
git clone https://github.com/yourorg/terraai
cd terraai
./install.sh
```

`install.sh` creates a `.venv`, installs all Python dependencies, and generates a `./terraai` launcher script. The launcher computes its own path at runtime so it works regardless of where you cloned the repo.

### Option B — Download a pre-built binary

No Python or virtual environment needed.

| Platform | Binary |
|----------|--------|
| macOS (Apple Silicon M1/M2/M3) | `terraai-macos-arm64` |
| macOS (Intel) | `terraai-macos-x64` |
| Linux x86_64 | `terraai-linux-x64` |
| Windows x64 | `terraai-windows-x64.exe` |

Download from [GitHub Releases](https://github.com/yourorg/terraai/releases), then:

```bash
# macOS / Linux
chmod +x terraai-macos-arm64
./terraai-macos-arm64

# Windows (PowerShell)
.\terraai-windows-x64.exe
```

### Optional: add to PATH

```bash
ln -s "$(pwd)/terraai" /usr/local/bin/terraai
# then from anywhere:
terraai --help
```

---

## Quick Start

On the **first launch**, TerraAI runs an interactive setup wizard (see [First-Run Setup Wizard](#first-run-setup-wizard)). After that, just run:

```bash
# With Groq (free tier — get key at console.groq.com)
export GROQ_API_KEY=gsk_...
./terraai --model groq/llama3-70b-8192 --provider azure

# With local Ollama (completely free, no API key)
ollama pull codellama
./terraai --model ollama/codellama

# With OpenAI
export OPENAI_API_KEY=sk-...
./terraai --model gpt-4o --provider azure
```

### Example session

```
☁️ azure[my-infra] ❯ create an Azure resource group named rg-prod in East US

⠸ 🤖 Thinking...

──────────────── ☁️ CREATE — Create Azure resource group 'rg-prod' ──────────────

┌─────────────────────────────────────────────────────────┐
│ Resource    │ Type                   │ Action            │
│ rg_prod     │ azurerm_resource_group │ create            │
└─────────────────────────────────────────────────────────┘

resource "azurerm_resource_group" "rg_prod" {
  name     = "rg-prod"
  location = var.location
  tags     = var.tags
}

💾 Save to resource_group.tf? (y=yes, r=rename, n=skip, p=plan after save): y
✅ Saved → ~/my-infra/resource_group.tf
📝 Auto-committed [a1b2c3d4] — /history to view

💡 Next steps:
  ▸ Run /init to download the azurerm provider
  ▸ Set ARM_SUBSCRIPTION_ID before /apply

☁️ azure[my-infra] ❯ /init
☁️ azure[my-infra] ❯ /plan
☁️ azure[my-infra] ❯ /apply
☁️ azure[my-infra] ❯ /diagram
```

---

## First-Run Setup Wizard

On the first launch, TerraAI automatically runs a 5-step setup wizard. Every subsequent launch skips it. Re-run it at any time with:

```bash
./terraai setup
```

### Step 1 — Workspace

Choose where your Terraform files will be written. This must be a directory separate from the TerraAI install itself.

```
  n  Create a new directory automatically (under ~/terraai-workspaces/)
  p  Enter a custom absolute path
```

### Step 2 — Git repository

```
  1  Initialise a new git repo in the workspace
  2  Clone an existing remote repo (GitHub, GitLab, Azure DevOps, etc.)
  s  Skip
```

If you clone, TerraAI pulls the repo into your workspace directory. It also prompts to add a remote push URL if none is configured.

### Step 3 — AI model & API key

Presents a numbered list of free and paid models. After you choose, it checks if the required API key is already set (env var or keyring). If not, it offers to store it securely (see [Credential Storage](#credential-storage)).

### Step 4 — Cloud provider credentials

```
  1  Azure
  2  AWS
  3  GCP
  4  Kubernetes
  s  Skip (configure manually later)
```

For Azure specifically, the wizard detects an active `az login` session and offers it as an option — no client secret required. See [Azure Authentication](#azure-authentication).

### Step 5 — State backend

```
  1  Local   — state on disk (fine for solo dev)
  2  Azure Blob Storage
  3  S3
  4  GCS
  5  PostgreSQL (on-prem)
  s  Skip
```

If you pick a remote backend, TerraAI records your choice and prompts you to fill in the connection details when the next session starts — so you don't need to remember `/backend set` syntax.

---

## Credential Storage

TerraAI stores secrets in your OS keyring — not in plain text on disk.

| Platform | Storage |
|----------|---------|
| macOS | Keychain Access |
| Windows | Credential Manager |
| Linux | GNOME Keyring / KDE Wallet |
| Fallback (no keyring) | `~/.terraai/config.yaml` with `chmod 600` |

### What gets stored

| Secret | Key name |
|--------|----------|
| AI API key (per provider) | `api_key_<provider>` |
| Azure Client Secret | `azure_client_secret` |
| AWS Secret Access Key | `aws_secret` |

You never need to manually interact with your keyring — TerraAI handles reads and writes. To set a key via environment variable instead:

```bash
export GROQ_API_KEY=gsk_...
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
export GEMINI_API_KEY=AIza...
```

---

## Azure Authentication

TerraAI supports three Azure authentication methods. Credentials are applied to the process environment before Terraform runs — they are never written into `.tf` files.

### Method 1 — Azure CLI (easiest for local dev)

No client secret needed. Run `az login` once and TerraAI detects the session automatically.

```bash
az login
export ARM_SUBSCRIPTION_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
./terraai --provider azure
```

In the setup wizard, choose **Auth method 1** and the wizard will set `ARM_USE_CLI=true` automatically.

### Method 2 — Service Principal (CI/CD)

```bash
# Create a service principal (one-time)
az ad sp create-for-rbac \
  --name "terraai-sp" \
  --role Contributor \
  --scopes /subscriptions/<subscription-id>

# Set credentials (client secret goes to keyring, never disk)
export ARM_SUBSCRIPTION_ID=...
export ARM_TENANT_ID=...
export ARM_CLIENT_ID=...
export ARM_CLIENT_SECRET=...   # or enter in wizard → stored in keyring
```

### Method 3 — Managed Identity (Azure VMs / AKS)

```bash
export ARM_USE_MSI=true
export ARM_SUBSCRIPTION_ID=...
```

No client ID or secret required — Azure assigns the identity automatically.

### Saving Azure credentials via the wizard

When you run the setup wizard and choose Service Principal, the client secret is stored in your OS keyring, not in `~/.terraai/config.yaml`. All other fields (subscription ID, tenant ID, client ID, auth method) are saved to the config file.

```bash
# To re-run just the credentials step:
./terraai setup
# → navigate to Step 4
```

---

## Architecture Diagram

After applying infrastructure, run `/diagram` to generate an interactive HTML diagram showing all your resources and their dependencies.

```
☁️ azure[my-infra] ❯ /diagram

Resources:
  📦  azurerm_resource_group.rg_prod          [Resource Group]
  💾  azurerm_storage_account.st_prod         [Storage]
  🌐  azurerm_virtual_network.vnet_prod       [Networking]
  ⎈   azurerm_kubernetes_cluster.aks_prod     [Kubernetes]

Relationships:
  azurerm_storage_account.st_prod   →  azurerm_resource_group.rg_prod
  azurerm_virtual_network.vnet_prod →  azurerm_resource_group.rg_prod
  azurerm_kubernetes_cluster.aks    →  azurerm_resource_group.rg_prod

✅ Diagram saved → ~/my-infra/architecture.html
```

The diagram opens automatically in your browser. It's a self-contained HTML file — no internet connection required.

**Features:**
- Force-directed layout — resources cluster by dependency
- Drag nodes to rearrange
- Scroll to zoom
- Hover a node to see resource type and cloud category
- **⊞ Fit** to centre all resources
- **↓ SVG** to export a static image for documentation

TerraAI parses both `terraform.tfstate` (deployed resources) and all `*.tf` files (planned resources) and detects dependencies by scanning for cross-resource references in HCL.

```bash
/diagram                    # saves architecture.html, opens in browser
/diagram prod-diagram.html  # custom filename
```

---

## TerraAI Chronicle (Version Control)

Every time you save AI-generated HCL, TerraAI automatically:

1. **Commits to git** with a semantic commit message written by the AI:

   ```
   feat(azure): add VNet with 2 subnets for prod environment

     create: azurerm_virtual_network, azurerm_subnet

   Generated-By: TerraAI
   Timestamp: 2025-06-15T10:23:41Z
   ```

2. **Updates `INFRASTRUCTURE.md`** — a human-readable changelog recording what changed, your original request, affected resources, and any warnings.

3. **Snapshots state** to `.terraai/snapshots/<sha>.json` so drift detection can compare live infrastructure against a specific commit.

Git history, AI-authored explanations, and state snapshots are all synchronised to the same commit SHA.

### Drift detection

```bash
/drift
```

Compares live `terraform.tfstate` against the last known snapshot. Reports:

- **Modified** — resources changed outside Terraform (manual portal edits, scripts)
- **Missing** — resources deleted outside Terraform
- **Extra** — resources created outside Terraform

### Version control commands

```bash
/history              # git log for this workspace
/chronicle            # AI-authored changelog
/diff a1b2 e5f6       # HCL diff between two commits
/rollback a1b2c3d4    # restore .tf files from a past commit
/tag v1.0-prod        # tag current state
/branch feature/aks   # create and switch branch
/drift                # detect out-of-band changes
```

---

## State Backend Options

All backends are standard open-source Terraform backends — no Terraform Cloud, no proprietary lock-in.

| Backend | State location | Locking | Best for |
|---------|---------------|---------|----------|
| `local` | `./terraform.tfstate` | ❌ | Single dev, local testing |
| `azurerm` | Azure Blob Storage | ✅ | Azure teams |
| `s3` | AWS S3 + DynamoDB | ✅ | AWS teams |
| `gcs` | Google Cloud Storage | ✅ | GCP teams |
| `pg` | PostgreSQL (self-hosted) | ✅ | On-prem, no cloud |
| `consul` | HashiCorp Consul KV | ✅ | Service-mesh environments |
| `kubernetes` | Kubernetes Secret | ✅ | K8s-native workflows |
| `http` | Any REST endpoint | Optional | Custom / BYO state server |

### Configuring a backend

```bash
/backend set azurerm    # interactive wizard — prompts for storage account, container, key
/backend set s3
/backend set pg         # self-hosted PostgreSQL, connection string stored in keyring
/backend set local

/backend env prod       # switch to prod's backend
/backend list           # show all environments → backends
/backend migrate        # runs terraform init -migrate-state
```

### Multi-environment state federation

One workspace, different backends per environment:

```
dev     →  local       ./terraform.tfstate
staging →  pg          self-hosted PostgreSQL
prod    →  azurerm     Azure Blob Storage (locked)
```

---

## AI Model Support

TerraAI uses [LiteLLM](https://github.com/BerriAI/litellm) as the AI abstraction layer, giving access to 100+ models with a single interface. No vendor lock-in.

### Free models

| Model | Provider | How to get access |
|-------|----------|-------------------|
| `groq/llama3-70b-8192` | Groq | Free tier at [console.groq.com](https://console.groq.com) |
| `groq/mixtral-8x7b-32768` | Groq | Free tier at [console.groq.com](https://console.groq.com) |
| `gemini/gemini-1.5-flash` | Google | Free tier at [aistudio.google.com](https://aistudio.google.com) |
| `gemini/gemini-1.5-pro` | Google | Free tier at [aistudio.google.com](https://aistudio.google.com) |
| `ollama/llama3` | Ollama | Local — `ollama pull llama3` |
| `ollama/codellama` | Ollama | Local — `ollama pull codellama` |
| `ollama/mistral` | Ollama | Local — `ollama pull mistral` |

### Paid models

| Model | Provider | Env var |
|-------|----------|---------|
| `gpt-4o` | OpenAI | `OPENAI_API_KEY` |
| `gpt-4o-mini` | OpenAI | `OPENAI_API_KEY` |
| `claude-sonnet-4-6` | Anthropic | `ANTHROPIC_API_KEY` |
| `claude-haiku-4-5-20251001` | Anthropic | `ANTHROPIC_API_KEY` |
| `azure/gpt-4o` | Azure OpenAI | `AZURE_OPENAI_API_KEY` |

### Switching models

```bash
# At launch
./terraai --model groq/llama3-70b-8192

# In session — prompts for key if not set
/model gpt-4o
/model ollama/codellama

# Save as default
./terraai configure --model gpt-4o-mini
```

### Ollama (local, free, offline)

```bash
# Install: https://ollama.com
ollama serve                   # start the Ollama server
ollama pull codellama          # download the model (~4 GB)
./terraai --model ollama/codellama
```

---

## Commands Reference

### Infrastructure

| Command | Description |
|---------|-------------|
| `/init` | Run `terraform init` — downloads providers |
| `/plan` | Show what will change without touching real infra |
| `/apply` | Apply changes (requires typing `yes`) |
| `/destroy` | Destroy all resources (requires typing `destroy`) |
| `/state` | Show current Terraform state |
| `/resources` | List all resources in state |
| `/outputs` | Show Terraform output values |
| `/files` | List `.tf` files in workspace |
| `/diagram [file]` | Generate interactive architecture diagram |

### Version Control

| Command | Description |
|---------|-------------|
| `/history` | Git commit log for this workspace |
| `/chronicle` | AI-authored human-readable changelog |
| `/diff [sha1] [sha2]` | HCL diff between commits |
| `/rollback <sha>` | Restore `.tf` files from any past commit |
| `/tag <name> [msg]` | Tag a milestone (e.g. `v1.0-prod`) |
| `/tags` | List all tags |
| `/branch <name>` | Create and switch to a new git branch |
| `/branches` | List all branches |
| `/drift` | Detect out-of-band infrastructure changes |

### State Backend

| Command | Description |
|---------|-------------|
| `/backend` | Show current backend config |
| `/backend set <type>` | Interactive wizard to configure a backend |
| `/backend env <name>` | Switch active environment (dev/staging/prod) |
| `/backend list` | Show all environment → backend mappings |
| `/backend migrate` | Migrate state to newly configured backend |

### Configuration

| Command | Description |
|---------|-------------|
| `/model <name>` | Switch AI model mid-session |
| `/workspace` | Interactive picker — switch to a recent workspace, create a new one, or enter a path |
| `/workspace <path>` | Switch straight to a workspace directory (created if it doesn't exist) |
| `/workspace new <name>` | Create a new workspace under `~/terraai-workspaces/` and switch to it |
| `/workspaces` | List recent workspaces |
| `/config` | Show current configuration |
| `/providers` | List supported Terraform providers |
| `/models` | List all supported AI models |
| `/clear` | Clear conversation history |
| `/help` | Show command reference |
| `/exit` | Exit TerraAI |

### CLI subcommands (outside session)

```bash
./terraai                              # start session (wizard on first run)
./terraai setup                        # re-run the 5-step setup wizard
./terraai configure --model gpt-4o     # save default model
./terraai configure --api-key sk-...   # save API key (also stored in keyring)
./terraai configure --workspace ~/infra
./terraai models                       # list all AI models + env vars
./terraai providers                    # list supported Terraform providers
```

---

## Workspace File Layout

All Terraform files are written to your **workspace directory** — never into the TerraAI install directory.

```
~/your-workspace/
│
├── main.tf                  ← provider + variables (AI-generated)
├── networking.tf            ← VNets, subnets, NSGs
├── compute.tf               ← VMs, scale sets
├── storage.tf               ← storage accounts, blobs
├── kubernetes.tf            ← AKS, Helm releases
├── backend.tf               ← state backend config (from /backend set)
│
├── INFRASTRUCTURE.md        ← AI-authored changelog (auto-updated)
���── architecture.html        ← interactive diagram (from /diagram)
├── .gitignore               ← auto-created on first run
│
├── .git/                    ← git repo (auto-initialised)
│
└── .terraai/                ← TerraAI metadata (gitignored)
    ├── chronicle.json       ← machine-readable change history
    ├── state_config.json    ← backend config per environment
    └── snapshots/
        ├── a1b2c3d4.json    ← tfstate snapshot after commit a1b2c3d4
        └── …
```

### What is and isn't tracked in git

| Tracked ✅ | `*.tf`, `backend.tf`, `INFRASTRUCTURE.md`, `architecture.html` |
|---|---|
| **Gitignored ❌** | `.terraform/`, `*.tfvars`, `terraform.tfstate`, `terraform.tfstate.backup`, `.terraai/` |

> **Why ignore `terraform.tfstate`?** State files can contain sensitive resource IDs and outputs. Store state in a remote backend instead — TerraAI makes this easy with `/backend set`.

> **Why ignore `*.tfvars`?** Variable files often contain environment-specific values or secrets. Use environment variables or a secrets manager instead.

---

## Supported Providers

| Provider | Terraform source | Example resources |
|----------|-----------------|-------------------|
| `azure` | `hashicorp/azurerm` | `azurerm_resource_group`, `azurerm_virtual_network`, `azurerm_kubernetes_cluster`, `azurerm_key_vault` |
| `aws` | `hashicorp/aws` | `aws_vpc`, `aws_s3_bucket`, `aws_instance`, `aws_eks_cluster` |
| `gcp` | `hashicorp/google` | `google_compute_instance`, `google_storage_bucket`, `google_container_cluster` |
| `kubernetes` | `hashicorp/kubernetes` | `kubernetes_deployment`, `kubernetes_service`, `kubernetes_namespace` |
| `helm` | `hashicorp/helm` | `helm_release` |
| `vmware` | `hashicorp/vsphere` | `vsphere_virtual_machine`, `vsphere_folder` |

---

## Project Structure

```
terraai/
├── main.py                  # CLI entry point (Typer) — root flags, subcommands
├── session.py               # Interactive REPL — command routing, AI flow
├── demo.py                  # Standalone demo (no API key needed)
├���─ install.sh               # Installer — creates .venv and launcher script
├── build.sh                 # macOS / Linux PyInstaller build
├── build.bat                # Windows PyInstaller build
├── terraai.spec             # PyInstaller spec (cross-platform config)
├── requirements.txt
│
├── .github/
│   ��── workflows/
│       └── build-release.yml  # CI: builds all 4 platform binaries on git tag push
│
├── ai/
│   ├── client.py            # LiteLLM wrapper — multi-model AI client
│   └── prompts.py           # System prompt (Terraform expert persona)
│
├── config/
│   └── settings.py          # TerraAIConfig (Pydantic v2) + keyring helpers
│
├── setup/
│   └── wizard.py            # First-run setup wizard (5 steps)
│
├── terraform/
│   ├── executor.py          # Terraform CLI bridge (init/plan/apply/destroy)
│   └── workspace.py         # .tf file management, context builder
│
├── vcs/
│   ├── git_manager.py       # Git lifecycle: init, commit, log, diff, tags, branches
│   ├── changelog.py         # INFRASTRUCTURE.md + chronicle.json
│   ├── drift_detector.py    # State snapshot + drift comparison
│   └── diagram.py           # Architecture diagram generator (HTML + SVG)
│
├── state/
│   ├── backends.py          # 8 backend types → HCL generators
│   └── manager.py           # Multi-env routing, BackendWizard, migration
│
├── ui/
│   ├── console.py           # Rich themed console
│   └── panels.py            # HCL panels, plan tables, resource tables
│
└── providers/
    └── __init__.py          # Provider HCL boilerplate
```

---

## Building Executables

Produce a single self-contained binary — no Python install needed on the target machine.

### macOS / Linux

```bash
./build.sh           # builds dist/terraai
./build.sh --clean   # clean dist/ and build/ first
```

### Windows

```bat
build.bat
build.bat --clean
```

### GitHub Actions (automatic)

Push a version tag to trigger a multi-platform release:

```bash
git tag v0.2.0
git push origin v0.2.0
# GitHub Actions builds macos-arm64, macos-x64, linux-x64, windows-x64
# All 4 binaries are attached to the GitHub Release automatically
```

See [`.github/workflows/build-release.yml`](.github/workflows/build-release.yml).

---

## Configuration File

Saved to `~/.terraai/config.yaml` (permissions: `chmod 600`). Sensitive values (API keys, Azure client secret) are stored in the OS keyring — not here.

```yaml
model: gpt-4o-mini
default_provider: azure
workspace_dir: ~/my-azure-infra
auto_approve: false
show_raw_hcl: true
terraform_bin: terraform
temperature: 0.1
setup_complete: true

# Azure (non-secret fields only)
azure_subscription_id: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
azure_tenant_id: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
azure_client_id: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
azure_use_cli_auth: false
azure_use_msi: false
```

Set individual fields:

```bash
./terraai configure --model gpt-4o
./terraai configure --provider azure
./terraai configure --workspace ~/my-infra
./terraai configure --api-key sk-...    # also stored in keyring
```

---

## License

MIT — open-source, no lock-in, no Terraform Cloud required.
