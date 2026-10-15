# CloudKick Terraform deployment

This directory is the authoritative infrastructure definition for the Phase 2
lab. `lab.py` generates the sensitive variables, selects one Terraform workspace
per deployment name and runs the lifecycle commands. Do not hand-edit or commit
`generated.auto.tfvars.json`, the generated Lambda archive or Terraform state.

## Local validation

```bash
terraform -chdir=terraform init -backend=false
terraform -chdir=terraform fmt -check
terraform -chdir=terraform validate
python -m unittest discover -s tests -v
```

Validation proves the local configuration is internally valid. It does not prove
AWS quotas, model access, successful deployment or Wiz visibility.

## Plan and deploy

Copy `config.example.json` to a gitignored configuration file, use an isolated
AWS account, keep `engine` set to `converse`, and choose `vulnerable` or `secure`.

```bash
python lab.py plan --config config.json
python lab.py deploy --config config.json
python smoke.py --state cloudkick-lsr.state.json
```

The utility checks the active account, validates a narrow IPv4 CIDR, resolves the
selected Bedrock model or inference profile, creates a private build manifest and
seeds the synthetic policy, orders and one exact private archive. The `plan`
command creates the private local variables/state needed by Terraform but does
not apply infrastructure.

The generated Lambda archive is staged under `artifacts/` in the private orders
bucket and deployed to Lambda by S3 reference. This avoids embedding binary ZIP
content in the provider's `UpdateFunctionCode` request.

To keep a secure twin ready, use a second configuration with a different `name`
and `mode: secure`. API Gateway's CloudWatch role setting is regional and
account-wide; the most recently applied CloudKick stack supplies that role. Keep
that stack deployed until the other twin is no longer needed, and clean up the
older twin first.

## Operate and remove

```bash
python lab.py reset --config config.json
python lab.py failures --config config.json
python lab.py replay --config config.json --job JOB_REFERENCE
python lab.py evidence --config config.json --job JOB_REFERENCE
python lab.py freeze --config config.json
python lab.py unfreeze --config config.json
python lab.py cleanup --config config.json
```

Export evidence before cleanup. Destroy uses the exact named workspace and then
removes the private local deployment state. The application expiry stops new use;
it does not destroy chargeable infrastructure.
