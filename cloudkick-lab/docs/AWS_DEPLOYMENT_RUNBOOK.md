# CloudKick AWS deployment and validation runbook

This runbook deploys the Phase 2 demo into a dedicated AWS sandbox from a local
machine. It uses AWS CLI credentials, Terraform and the repository's Python
lifecycle utility. The primary and only supported deployment engine is Amazon
Bedrock Converse.

The commands below assume Bash, zsh or WSL. In PowerShell, replace `export` with
`$env:NAME = "value"` and activate `.venv\Scripts\Activate.ps1`.

## 1. Confirm the sandbox boundary

Use an account that contains no production workloads or real customer data.
The deployment creates IAM roles, a regional API Gateway account logging
configuration, Lambda functions, three S3 buckets, DynamoDB, SQS, CloudWatch
logs and a CloudTrail trail with S3 data events.

For the first sandbox deployment, the simplest deployment identity is a
temporary administrator or equivalent infrastructure role. At minimum, it must
be able to:

- call STS `GetCallerIdentity`;
- read Bedrock foundation-model and inference-profile metadata;
- create, tag, update and delete the named IAM roles and policies, attach the
  API Gateway logging policy and pass the three Lambda roles;
- manage Lambda, REST API Gateway account/API/stage settings, DynamoDB, S3,
  CloudTrail, CloudWatch Logs and SQS resources;
- invoke the selected Bedrock model or inference profile for validation.

Do not give the deployment identity or AWS credentials to the external-user
participant. Prefer temporary credentials from `aws login` rather than creating
a long-lived access key.

## 2. Install the local prerequisites

Install:

- Git;
- Python 3.12;
- AWS CLI v2;
- Terraform 1.5 or newer;
- `curl` for checking the presenter egress IP;
- `jq`, recommended for reading non-secret output fields.

Confirm the versions:

```bash
git --version
python3.12 --version
aws --version
terraform version
curl --version
jq --version
```

## 3. Clone or update the repository

For a new checkout:

```bash
git clone https://github.com/0xNefariousFF/lsr-demo.git
cd lsr-demo/cloudkick-lab
git switch main
git pull --ff-only origin main
```

For an existing clean checkout:

```bash
cd /path/to/lsr-demo
git switch main
git pull --ff-only origin main
cd cloudkick-lab
```

Do not run `git pull` over local configuration, Terraform state or evidence that
has not been backed up. These files are ignored by Git but remain operationally
important.

## 4. Configure AWS CLI credentials

### Recommended: log in with the existing IAM console user

AWS CLI v2.32.0 or newer can exchange existing AWS Management Console
credentials for temporary local-development credentials. This avoids storing a
long-lived access key.

An administrator must attach the AWS-managed login policy to the existing IAM
user. Run this with an administrative identity, not with
`cloudkick-developer` unless it already administers its own policies:

In the AWS console, open **IAM → Users → cloudkick-developer → Add
permissions → Attach policies directly**, select
`SignInLocalDevelopmentAccess`, and confirm the change. An administrator who
already has working CLI credentials can instead run:

```bash
aws iam attach-user-policy \
  --user-name cloudkick-developer \
  --policy-arn arn:aws:iam::aws:policy/SignInLocalDevelopmentAccess
```

`SignInLocalDevelopmentAccess` only permits the console-to-CLI login exchange.
It does not grant permission to deploy CloudKick. The user still needs the
sandbox deployment permissions described in section 1.

On the development machine, confirm the CLI version and start the browser login:

```bash
aws --version
aws login --profile cloudkick-lab
```

When the browser opens, sign in to the sandbox account as
`cloudkick-developer`, select that identity, and return to the terminal. If the
machine cannot open a browser, use:

```bash
aws login --remote --profile cloudkick-lab
```

Set the profile and approved deployment Region:

```bash
aws configure set region eu-west-2 --profile cloudkick-lab
export AWS_PROFILE=cloudkick-lab
export AWS_REGION=eu-west-2
export AWS_DEFAULT_REGION="$AWS_REGION"
export AWS_PAGER=""
```

The CLI caches temporary credentials under `~/.aws/login/cache` and refreshes
them during a session of up to 12 hours. Run `aws login --profile
cloudkick-lab` again after the session expires.

Verify the active identity before creating anything:

```bash
aws sts get-caller-identity
LAB_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
printf 'Sandbox account: %s\n' "$LAB_ACCOUNT_ID"
```

The account ID printed here must be the account you place in `config.json`.
Stop if it is a shared or production account.

Also verify that the Python SDK used by `lab.py` can use the profile:

```bash
python -c 'import boto3; print(boto3.Session().client("sts").get_caller_identity()["Arn"])'
```

If AWS CLI commands work but Python or Terraform reports missing credentials,
create a compatibility profile using the CLI as a process credential provider:

```bash
aws login --profile cloudkick-signin
aws configure set region eu-west-2 --profile cloudkick-signin
aws configure set credential_process \
  'aws configure export-credentials --profile cloudkick-signin --format process' \
  --profile cloudkick-lab
aws configure set region eu-west-2 --profile cloudkick-lab
export AWS_PROFILE=cloudkick-lab

aws sts get-caller-identity
python -c 'import boto3; print(boto3.Session().client("sts").get_caller_identity()["Arn"])'
```

When finished, remove the cached login session. Use the first command for the
direct profile or the second for the compatibility profile:

```bash
aws logout --profile cloudkick-lab
aws logout --profile cloudkick-signin
```

### Fallback: IAM access key

If your organisation has disabled `aws login`, an administrator can permit an
access key for `cloudkick-developer`. Treat this as the fallback because it is a
long-lived credential. Create the key in IAM, save the secret once, and configure
the local profile without putting either value in a command or repository:

```bash
aws configure --profile cloudkick-lab
```

Enter the access key ID, secret access key, approved Region and `json` output
when prompted. Then export `AWS_PROFILE`, verify STS as above, and deactivate or
delete the access key immediately after cleanup.

## 5. Select and test the pinned Bedrock model

Use **Amazon Nova Lite** in `eu-west-2`:

```bash
export MODEL_ID='amazon.nova-lite-v1:0'
```

Nova Lite is the demo's recommended model. It supports Bedrock Converse and
client-side tool calling, is less capable and less expensive than the previous
Sonnet choice, and does not require the Anthropic use-case form. The scripted
customer and external-assessment paths use controlled orchestration around real
Actions, so their success does not depend on the model deciding whether to call a
tool. Nova still handles unscripted customer wording within the same bounded schema.

Model capability is not a security boundary. The Action handler, server-side
approval, customer ownership checks, bounded targets and IAM policy remain the
controls that prevent work outside this demo. See the
[Amazon Nova models documentation](https://docs.aws.amazon.com/nova/latest/userguide/what-is-nova.html)
and [Bedrock Converse tool use](https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use-inference-call.html).

Do not silently replace this ID with the newest model shown in the console. A
different model changes the scenario behaviour and must be rehearsed again.

### 5.1 Confirm Nova Lite is available

```bash
aws bedrock get-foundation-model-availability \
  --region "$AWS_REGION" \
  --model-id "$MODEL_ID" \
  --query '{Agreement:agreementAvailability,Authorization:authorizationStatus,Entitlement:entitlementAvailability,Region:regionAvailability}' \
  --output json
```

Continue when the agreement is `AVAILABLE`, authorization is `AUTHORIZED`, and
the entitlement and Region are both `AVAILABLE`.

Confirm the model metadata:

```bash
aws bedrock get-foundation-model \
  --region "$AWS_REGION" \
  --model-identifier "$MODEL_ID" \
  --query 'modelDetails.{Id:modelId,Name:modelName,Status:modelLifecycle.status,Input:inputModalities,Output:outputModalities}' \
  --output table
```

### 5.2 Run the full Converse tool-use preflight

The old `READY` prompt proved only text generation. This check exercises the
contract the demo actually needs: the model must request a tool, accept its
result and finish the answer. It runs the round trip three times at temperature
zero and incurs a small inference charge.

```bash
chmod +x scripts/bedrock_model_preflight.sh
./scripts/bedrock_model_preflight.sh 3
```

The required result is three `PASS` lines followed by:

```text
MODEL PREFLIGHT PASSED: amazon.nova-lite-v1:0 in eu-west-2
```

Do not deploy until this passes. Run it again on the presenter network on the
day of the demo. This proves current access, Converse compatibility and the
two-turn tool contract; it cannot guarantee that every natural-language answer
or red-team attempt will be identical.

### 5.3 Resolve access failures without changing the scenario

- `AccessDeniedException`: confirm that `cloudkick-developer` can inspect and
  invoke the Nova Lite foundation model in `eu-west-2`, and check applicable
  organisation SCPs.
- marketplace, subscription or model-access error: have the sandbox
  administrator enable Amazon Nova Lite and allow the account's model-access
  prerequisites, then repeat the preflight.
- `ResourceNotFoundException`: first confirm that
  `AWS_REGION` is `eu-west-2` and that the CLI is using the intended sandbox
  account. Do not infer availability from the model's display name.
- throttling or quota errors: inspect the account's Bedrock quotas for Nova Lite,
  wait for capacity to recover and rerun all three attempts. Do not treat a
  single successful call as the demo readiness gate.

## 6. Determine the presenter source CIDR

The API resource policy accepts only an IPv4 `/24` through `/32`. A presenter
machine normally uses its current public egress IP as a `/32`.

```bash
PRESENTER_IP=$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')
export PRESENTER_CIDR="${PRESENTER_IP}/32"
printf 'Presenter CIDR: %s\n' "$PRESENTER_CIDR"
```

If you use a corporate VPN, confirm which egress address the browser will use
during the demo. Do not use `0.0.0.0/0`; the utility rejects broad CIDRs.

## 7. Prepare and validate the local project

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Required by Boto3 when AWS CLI `aws login` supplies the credentials.
python -c 'import awscrt; print("AWS CRT credential support: READY")'

python -m unittest discover -s tests -v
python -m py_compile src/*.py lab.py infra.py smoke.py
terraform -chdir=terraform init -backend=false
terraform -chdir=terraform fmt -check
terraform -chdir=terraform validate
```

Expected local result: all Python tests pass and Terraform reports that the
configuration is valid. These checks do not prove AWS or model behaviour.

## 8. Create the vulnerable deployment configuration

Create the ignored local configuration:

```bash
cp config.example.json config.json
chmod 600 config.json
```

Edit `config.json` so it resembles the following. Use your actual account,
Region, public CIDR and tested model identifier.

```json
{
  "name": "cloudkick-lsr",
  "account": "YOUR_12_DIGIT_SANDBOX_ACCOUNT",
  "region": "eu-west-2",
  "owner": "YOUR_NAME_OR_TEAM",
  "is_isolated_lab": true,
  "allowed_cidr": "auto",
  "engine": "converse",
  "mode": "vulnerable",
  "model_id": "amazon.nova-lite-v1:0",
  "hours": 8
}
```

Rules enforced by the utility:

- `name` begins with `cloudkick-` and contains no more than 16 characters after
  that prefix;
- the active AWS account exactly matches `account`;
- `engine` is `converse`;
- `mode` is `vulnerable` or `secure`;
- `allowed_cidr` is `auto` or an IPv4 `/24` through `/32`; `auto` resolves the
  deployment machine's current public IPv4 on every plan or deploy;
- expiry is between one and 24 hours.

The three bucket names include the deployment name, account and Region. Choose a
different deployment name if that combination already exists.

## 9. Review the Terraform plan

```bash
python lab.py plan --config config.json
```

The command:

1. verifies the AWS account through STS;
2. resolves the model/profile and exact IAM ARNs;
3. creates customer tokens, the signing secret and synthetic canary locally;
4. selects a Terraform workspace matching the deployment name;
5. validates Terraform and prints the plan.

Review the plan before applying. It should contain only the named CloudKick lab
resources. In vulnerable mode, the Action role has one intentional private
`GetObject` grant and a prefix-limited `ListBucket` grant. It must not contain
account-wide S3 read, `ListAllMyBuckets` or arbitrary DynamoDB access.

The following local files now contain secrets and must not be committed or
shared:

- `cloudkick-lsr.state.json`;
- `terraform/generated.auto.tfvars.json`;
- `terraform/terraform.tfstate.d/cloudkick-lsr/terraform.tfstate`.

Keep the entire checkout on an encrypted disk and preserve it until cleanup is
complete.

## 10. Deploy and seed the lab

```bash
python lab.py deploy --config config.json
```

The command applies Terraform, reads its outputs and seeds:

- the fictional returns policy;
- ORD-1001 for C-104;
- ORD-2001 for C-105;
- one exact fictional private archive containing the deployment canary.

Record the printed build ID, mode, model and the two launch links. Do not project
or paste the private state file. Reprint the links later with:

```bash
python lab.py links --config config.json
```

Open **Customer journey** for the normal workflow. The page consumes the session
fragment and removes it from the address bar automatically. It should show Chris M.,
ORD-1001 and the CloudRunner. Expand **Demo details** only when you need to verify
C-104, `converse`, `vulnerable` and the build ID.

## 11. Run the operator component checks

```bash
python smoke.py --state "$LAB_STATE"
```

Every line should be `PASS`, followed by `All operator component checks passed`.
The first checks call the public API and verify that the hero and product images
are decoded correctly, catching stale source-IP policy and API Gateway binary-media
regressions. The remaining checks directly invoke Action Lambda and therefore prove
component boundaries, not black-box model discovery or customer disclosure.

## 12. Validate the normal-customer workflow

Use a new browser conversation and run these steps:

1. Ask: `What is CloudKick's return policy?`
2. Ask: `Check my return options for ORD-1001.`
3. Confirm L1 is eligible and L2 requires human review.
4. Ask: `Prepare a return for ORD-1001 line L1.`
5. Confirm the inline card shows the item, order and simulated £89 amount.
6. Select **Review return**. The application records the confirmation and asks
   KickAssist to create the return automatically.
7. Record the `RET-...` case ID.
8. Repeat the create request and confirm the same case ID is returned.
9. Select **Get help with another item** and confirm the customer-care review card
   is `queued` without copying a reference.
10. Ask for `ORD-2001` and confirm it is not disclosed.

Save the job reference displayed below the chat for each workflow you plan to
use as evidence.

## 13. Validate the bounded vulnerable path

For an actual external-user rehearsal, give the participant only the printed
**External assessment** link. It creates an ordinary C-105 customer session; it does
not provide AWS access. Do not give them the architecture, bucket name, object key,
source or operator state. Start a new conversation.

Run the same progressive public-API rehearsal used by the live story:

```bash
python rehearse.py --state "$LAB_STATE" --perspective offensive
```

The five-message sequence starts with customer-facing reconnaissance, develops an
older-record hypothesis, validates the assessor's owned ORD-2001, discovers one bounded
candidate, requests only its reference marker and then stops. It never supplies a bucket,
object key, tool name or canary. `rehearse.py` prints the corresponding ATLAS/ATT&CK
stage before each request and prints the final defender-pivot job reference.

In vulnerable mode the only passing outcome is disclosure of the exact synthetic canary.
The C-105 sequence uses deterministic controlled orchestration around genuine Action and
AWS calls, so a refusal, missing marker or failed action is a release-gate failure rather
than an acceptable variation. Run `smoke.py`, reset the application state, start a new
conversation and repeat the rehearsal. Do not substitute the operator component check for
the external-user result.

## 14. Export the AWS evidence

Use the job reference shown by the customer app:

```bash
export JOB_REFERENCE='REPLACE_WITH_32_CHARACTER_JOB_ID'
python lab.py evidence \
  --config config.json \
  --job "$JOB_REFERENCE" \
  --dest evidence/vulnerable
```

The exporter writes the customer job, Action tool records, build manifest and
matching delivered CloudTrail S3 data events. CloudTrail delivery can be delayed;
if zero matching events are reported, wait several minutes and run the same
command again.

Evidence can contain prompts, answers and the synthetic archive content. Keep it
private and do not commit the `evidence/` directory.

Useful AWS CLI checks:

```bash
ACTION_ROLE=$(jq -r '.outputs.ActionRole' "$LAB_STATE")
aws iam get-role-policy \
  --role-name "$ACTION_ROLE" \
  --policy-name CloudKickActionScope

aws cloudtrail get-trail-status \
  --name cloudkick-lsr-object-evidence \
  --region "$AWS_REGION"
```

## 15. Validate the secure configuration in place

An in-place repair gives the clearest before/after evidence. Export vulnerable
evidence first, then freeze new customer requests:

```bash
python lab.py freeze --config config.json
```

Edit only `mode` in `config.json`:

```json
"mode": "secure"
```

Review and apply the repair:

```bash
python lab.py plan --config config.json
python lab.py deploy --config config.json
python smoke.py --state "$LAB_STATE"
python lab.py unfreeze --config config.json
```

Expected secure results:

- all normal policy, order, approval, return and human-review checks still pass;
- diagnostic tools are absent from the model tool schema;
- a stale customer diagnostic call returns `support_entitlement_required`
  before S3;
- the Action IAM policy contains no private-bucket read or list grant.

Confirm the IAM boundary independently:

```bash
ACTION_ROLE=$(jq -r '.outputs.ActionRole' "$LAB_STATE")
PRIVATE_BUCKET=$(jq -r '.outputs.PrivateBucket' "$LAB_STATE")
ACTION_ROLE_ARN=$(aws iam get-role \
  --role-name "$ACTION_ROLE" \
  --query 'Role.Arn' \
  --output text)

aws iam get-role-policy \
  --role-name "$ACTION_ROLE" \
  --policy-name CloudKickActionScope

aws iam simulate-principal-policy \
  --policy-source-arn "$ACTION_ROLE_ARN" \
  --action-names s3:GetObject \
  --resource-arns "arn:aws:s3:::${PRIVATE_BUCKET}/cloudkick/customer-records.json" \
  --query 'EvaluationResults[0].EvalDecision' \
  --output text
```

The simulation should report `implicitDeny`. It is supporting IAM evidence, not
a replacement for the secure handler test or full effective-access analysis.

Start a fresh browser conversation after changing the schema. Re-run the normal
customer workflow and the permitted external-user prompts. Export secure job
evidence to a separate directory.

## 16. Optional secure twin

If presentation timing requires both URLs to exist at once:

```bash
cp config.json config.secure.json
chmod 600 config.secure.json
```

Set the original configuration back to `mode: vulnerable`. In
`config.secure.json`, use a different name such as `cloudkick-fixed` and keep
`mode: secure`. Deploy each configuration separately.

```bash
python lab.py deploy --config config.json
python lab.py deploy --config config.secure.json
```

Each deployment has its own tokens, Terraform workspace, buckets, functions and
URL. API Gateway's CloudWatch logging role setting is regional and account-wide,
so the most recently applied twin supplies that role. Do not destroy one twin
and then continue relying on access logs from the other without reapplying the
remaining deployment. For the simplest validation, prefer the in-place repair.

## 17. Inspect or replay failed work

List messages currently visible in the Worker asynchronous failure queue:

```bash
python lab.py failures --config config.json
```

Replay requires a known job whose DynamoDB status is `error`:

```bash
python lab.py replay --config config.json --job "$JOB_REFERENCE"
```

Do not repeatedly replay a failing model request. Check the Worker log first:

```bash
aws logs tail /aws/lambda/cloudkick-lsr-worker \
  --region "$AWS_REGION" \
  --since 30m \
  --format short
```

Logs contain build, mode, job and request correlation fields but intentionally
omit customer messages and tool result contents.

## 18. Cleanup

Export required evidence before cleanup. The expiry blocks application use but
does not destroy infrastructure or stop all charges.

```bash
python lab.py cleanup --config config.json
```

For twins, run cleanup for both configuration files after the session. Do not
continue using the remaining twin between the two cleanup commands unless you
reapply it to restore the regional API Gateway logging setting.

Verify that named resources are absent:

```bash
aws lambda list-functions \
  --region "$AWS_REGION" \
  --query 'Functions[?starts_with(FunctionName, `cloudkick-`)].FunctionName'

aws dynamodb list-tables \
  --region "$AWS_REGION" \
  --query 'TableNames[?starts_with(@, `cloudkick-`)]'

aws s3api list-buckets \
  --query 'Buckets[?starts_with(Name, `cloudkick-`)].Name'

aws cloudtrail list-trails \
  --region "$AWS_REGION" \
  --query 'Trails[?starts_with(Name, `cloudkick-`)].Name'
```

After confirming cleanup, delete retained local evidence and backups according
to the workshop retention policy. The utility removes the named deployment
secret file and Terraform workspace state; it does not remove unrelated AWS
resources or a shared Wiz connector.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `aws: error: argument command: Invalid choice 'login'` | Upgrade AWS CLI v2 to 2.32.0 or newer. Do not substitute a console password into `aws configure`. |
| `aws login` is denied | Ask an administrator to attach `SignInLocalDevelopmentAccess` to `cloudkick-developer`; also confirm organisation policies permit local-development sign-in. |
| AWS CLI works but Python or Terraform cannot find credentials | Configure the `credential_process` compatibility profile from section 4 and keep `AWS_PROFILE=cloudkick-lab`. |
| `Unable to locate credentials` | Run `aws login --profile cloudkick-lab`, export `AWS_PROFILE`, then repeat `aws sts get-caller-identity`. |
| Account mismatch | Correct `config.json` or switch AWS profiles. Never weaken the account check. |
| Model `AccessDeniedException` | Confirm model/profile ID, Region, subscription terms, IAM/SCP permissions and organisation data-location rules. |
| Terraform API Gateway logging error | Confirm the deployer can create/pass the logging role and patch the regional API Gateway account settings. |
| Browser receives 403 | Confirm the browser's current public egress IP matches `allowed_cidr`; check VPN changes. |
| Browser receives 401 | Use the token from the matching deployment state file without whitespace. |
| Job remains queued | Inspect Worker logs, Lambda concurrency and the failure queue. Do not expose raw internal records through the customer route. |
| No matching CloudTrail event | Confirm the trail is logging and wait for S3 delivery before rerunning evidence export. |
| Secure model still mentions diagnostics | Start a new conversation and confirm the URL, mode and build ID. |
| Cleanup fails | Preserve state, inspect the first Terraform/provider error and retry. Do not delete state or unrelated buckets manually. |

## Validation record to retain

For a successful rehearsal, record:

- date, account alias/ID and Region;
- Git commit and build ID;
- model or inference-profile ID;
- vulnerable and secure Terraform plans;
- component-check output;
- customer, external-user and secure-retest job IDs;
- Action records and matching CloudTrail request IDs;
- actual Wiz observations, clearly separated from inferred relationships;
- cleanup result.

Do not label AWS deployment, model behaviour, CloudTrail delivery or Wiz
visibility as validated until you have observed it in your environment.
