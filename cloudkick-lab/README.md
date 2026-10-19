# CloudKick LSR lab

This package implements a fictional customer-return agent and a deliberately bounded diagnostic authorisation defect. It accompanies the 60-minute presentation **How AI Agent Attack Paths Are Defended with Wiz** and the technical implementation report.

## Start here

1. Read `docs/IMPLEMENTATION.md`. Select an isolated AWS account and supported model. Install Terraform 1.5 or newer and Python 3.12.
   Follow `docs/AWS_DEPLOYMENT_RUNBOOK.md` for the complete AWS CLI, deployment,
   validation and teardown sequence.
2. Choose the engine for the story you need. `engine=converse` is the repeatable
   customer-demo path and implements a custom agent with the Bedrock Converse API.
   `engine=classic` deploys a real Amazon Bedrock Agent, alias and function-schema
   action group for the strongest Wiz agent/tool graph, but only in an account and
   Region still eligible for Agents Classic. Neither profile is AgentCore.
3. Copy `config.example.json` to `config.json` and replace all values marked `REPLACE`.
   Keep `allowed_cidr` set to `auto` to detect the deployment machine's current
   public IPv4 address on every plan or deploy. A fixed `/24` through `/32` remains
   available for a known corporate egress range.
4. Install local dependencies and run the offline tests.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
terraform -chdir=terraform init -backend=false
terraform -chdir=terraform validate
export AWS_PROFILE=cloudkick-lab
aws sts get-caller-identity
python lab.py plan --config config.json
python lab.py deploy --config config.json
```

On Windows PowerShell, use `.venv\Scripts\Activate.ps1` and `$env:AWS_PROFILE='cloudkick-lab'`, or run the bash commands in WSL. The SDK uses the same profile as the CLI. AWS CLI v2.32.0 or newer can use the IAM console user through `aws login`; see the deployment runbook.

The deployment prints two launch links: a C-104 customer journey and a C-105 external-assessment journey. The bearer value is carried in the URL fragment, consumed by the page, stored only for the browser tab and removed from the address bar. It is never sent in the initial HTTP request. Reprint the links with `python lab.py links --config config.json`.

A private `<name>.state.json` stores the underlying customer tokens, context-signing secret, output identifiers and build manifest. Terraform also stores sensitive Lambda environment values in its local workspace state. Do not commit or share either file.

```bash
python smoke.py --state cloudkick-lsr.state.json
python rehearse.py --state cloudkick-lsr.state.json --perspective all
python lab.py evidence --config config.json --job JOB_REFERENCE
python lab.py freeze --config config.json
```

`smoke.py` checks the deployed portal, decoded visual assets, launch token and
Action component boundaries with explicit pass/fail exits. With `engine=converse`,
`rehearse.py` uses the public web API with controlled C-104 customer and six-stage
C-105 assessment paths. The native Agent profile uses the same application and tools,
but its orchestration is model-driven and must be rehearsed in the selected account.
Both profiles perform genuine bounded AWS actions.
Offline tests use fake AWS
clients. No successful AWS deployment
or Wiz tenant investigation is claimed by the supplied package.

## Repair

Preserve evidence, freeze the bridge, set `mode` to `secure` in the configuration and redeploy. The update removes diagnostic tools, rejects stale diagnostic calls and removes the private S3 grants. Start a new conversation after the update.

```bash
python lab.py deploy --config config.json
python smoke.py --state cloudkick-lsr.state.json
python lab.py unfreeze --config config.json
```

For a time-limited presentation, predeploy a second stack named `cloudkick-fixed` in secure mode and clearly label the comparison as a separate deployment. A same-stack rehearsal provides stronger before-and-after evidence.

## Remove the lab

Export any evidence first. The cleanup operation runs Terraform destroy in the named workspace, including the four explicitly named lab buckets. It does not enumerate arbitrary account buckets.

```bash
python lab.py cleanup --config config.json
```

Run cleanup for both stacks if you deployed a secure twin. The expiry blocks application use but does not delete infrastructure. Delete local tokens, recordings and evidence when the workshop retention period ends. Keep any shared Wiz connector unless its owner has approved its removal.

## Contents

| File | Purpose |
|---|---|
| `terraform/` | Authoritative AWS infrastructure, IAM boundaries, logs and outputs |
| `infra.py` | Legacy CloudFormation generator retained for compatibility tests only |
| `lab.py` | Terraform lifecycle, account/model checks, fixtures, evidence, reset, replay and cleanup |
| `src/bridge.py` | Customer auth, asynchronous job API, approval and human-review endpoints |
| `src/worker.py` | Bedrock Classic invocation or bounded Converse tool loop |
| `src/action.py` | Business rules and deliberate diagnostic defect |
| `src/common.py` | Signed customer context and deterministic return identifiers |
| `src/schema.py` | Shared tool definitions and instructions |
| `src/index.html` | Same-origin customer sandbox application |
| `tests/test_boundaries.py` | Offline authorisation and configuration tests |
| `smoke.py` | Operator component validation against deployed AWS |
| `rehearse.py` | Repeatable intended and offensive public-API rehearsal |
| `docs/IMPLEMENTATION.md` | Full build, rehearsal, investigation and troubleshooting guide |
| `docs/DEMO_RUNBOOK.md` | Presenter-ready customer, assessor and defender workflows |

The authoritative Phase 1 design is `docs/BASELINE.md`. AWS observations from a
local deployment should be recorded against the acceptance gates rather than
assumed from the implementation.

The code is authored for this workshop. CloudGoat informed the design comparison; its scenario code is not copied into this package.
