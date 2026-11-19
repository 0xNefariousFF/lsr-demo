# CloudKick LSR lab

This package implements a fictional customer-return agent and a deliberately bounded diagnostic authorisation defect. It accompanies the 60-minute presentation **How AI Agent Attack Paths Are Defended with Wiz** and the technical implementation report.

## Start here

1. Read `docs/IMPLEMENTATION.md`. Select an isolated AWS account and supported model.
2. Use `engine=classic` only if the account is eligible for Amazon Bedrock Agents Classic. AWS closed it to new customers on 30 July 2026. `engine=converse` is a custom Bedrock Converse adapter, not Agents Classic or AgentCore.
3. Copy `config.example.json` to `config.json` and replace all values marked `REPLACE`. A narrow presenter source IP range is mandatory.
4. Install local dependencies and run the offline tests.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
export AWS_PROFILE=cloudkick-lab
aws sts get-caller-identity
python lab.py deploy --config config.json
```

On Windows PowerShell, use `.venv\Scripts\Activate.ps1` and `$env:AWS_PROFILE='cloudkick-lab'`, or run the bash commands in WSL. The SDK uses the same profile as the CLI. Use temporary SSO credentials.

The deployment prints the URL. A private `<name>.state.json` stores customer tokens, the context signing secret, output identifiers, code hash and model information. Do not commit or share it. Open the URL and enter the C-104 token locally. The browser retains it in memory, not persistent storage.

```bash
python smoke.py --state cloudkick-lsr.state.json
python lab.py evidence --config config.json --job JOB_REFERENCE
python lab.py freeze --config config.json
```

`smoke.py` is an operator component check. It does not demonstrate the external-user path or model behaviour. The customer application must be rehearsed separately. Offline tests use fake AWS clients. No successful AWS deployment or Wiz tenant investigation is claimed by the supplied package.

## Repair

Preserve evidence, freeze the bridge, set `mode` to `secure` in the configuration and redeploy. The update removes diagnostic tools, rejects stale diagnostic calls and removes the private S3 grants. Start a new conversation after the update. A fresh Classic alias/version is created for a changed build.

```bash
python lab.py deploy --config config.json
python smoke.py --state cloudkick-lsr.state.json
python lab.py unfreeze --config config.json
```

For a time-limited presentation, predeploy a second stack named `cloudkick-fixed` in secure mode and clearly label the comparison as a separate deployment. A same-stack rehearsal provides stronger before-and-after evidence.

## Remove the lab

Export any evidence first. The cleanup operation deletes this named stack and empties its four explicitly named, CloudKick-tagged buckets. It does not enumerate arbitrary account buckets.

```bash
python lab.py cleanup --config config.json
```

Run cleanup for both stacks if you deployed a secure twin. The expiry blocks application use but does not delete infrastructure. Delete local tokens, recordings and evidence when the workshop retention period ends. Keep any shared Wiz connector unless its owner has approved its removal.

## Contents

| File | Purpose |
|---|---|
| `infra.py` | CloudFormation template generator with explicit runtime IAM scope |
| `lab.py` | Account check, packaging, deployment, fixtures, evidence export, freeze and cleanup |
| `src/bridge.py` | Customer auth, asynchronous job API and independent approval endpoint |
| `src/worker.py` | Bedrock Classic invocation or bounded Converse tool loop |
| `src/action.py` | Business rules and deliberate diagnostic defect |
| `src/common.py` | Signed customer context and deterministic return identifiers |
| `src/schema.py` | Shared tool definitions and instructions |
| `src/index.html` | Same-origin customer sandbox application |
| `tests/test_boundaries.py` | Offline authorisation and configuration tests |
| `smoke.py` | Operator component validation against deployed AWS |
| `docs/IMPLEMENTATION.md` | Full build, rehearsal, investigation and troubleshooting guide |

The code is authored for this workshop. CloudGoat informed the design comparison; its scenario code is not copied into this package.
