#!/usr/bin/env python3
"""Deploy, operate, evidence and remove the bounded CloudKick Terraform lab."""
import argparse
import gzip
import hashlib
import ipaddress
import json
import os
import re
import secrets
import shutil
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TF_ROOT = ROOT / 'terraform'


def presenter_ipv4():
    request = urllib.request.Request(
        'https://checkip.amazonaws.com',
        headers={'User-Agent': 'cloudkick-lab/1'},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            value = response.read(64).decode().strip()
        address = ipaddress.ip_address(value)
        if address.version != 4:
            raise ValueError('service returned a non-IPv4 address')
        return str(address) + '/32'
    except Exception as ex:
        raise RuntimeError(
            'Could not detect the presenter public IPv4 address. Check network access '
            'to https://checkip.amazonaws.com or set allowed_cidr explicitly.'
        ) from ex


def save(path, data):
    path.write_text(json.dumps(data, indent=2, default=str) + '\n')
    path.chmod(0o600)


def load_config(path):
    c = json.loads(Path(path).read_text())
    if c.get('is_isolated_lab') is not True:
        raise ValueError('Use a dedicated isolated lab account and set is_isolated_lab=true.')
    if not re.fullmatch(r'cloudkick-[a-z0-9-]{1,16}', c['name']):
        raise ValueError('name must start cloudkick- and be at most 26 characters')
    if c.get('engine') not in ('converse', 'classic'):
        raise ValueError('engine must be converse or classic')
    if c['mode'] not in ('vulnerable', 'secure'):
        raise ValueError('mode must be vulnerable or secure')
    if not re.fullmatch(r'\d{12}', c['account']):
        raise ValueError('Explicit 12-digit lab account required')
    if c['allowed_cidr'] != 'auto':
        ip = ipaddress.ip_network(c['allowed_cidr'])
        if ip.version != 4 or ip.prefixlen < 24:
            raise ValueError('Use allowed_cidr=auto, the presenter IPv4 /32 or a narrow lab range /24 or smaller')
    if not 1 <= int(c.get('hours', 8)) <= 24:
        raise ValueError('Lab expiry must be 1 to 24 hours')
    return c


def clients(c):
    import boto3
    session = boto3.Session(region_name=c['region'])
    identity = session.client('sts').get_caller_identity()
    if identity['Account'] != c['account']:
        raise ValueError(f'AWS account mismatch: expected {c["account"]}, received {identity["Account"]}')
    return session


def state_path(c):
    return ROOT / (c['name'] + '.state.json')


def terraform_binary():
    binary = os.environ.get('TERRAFORM_BIN') or shutil.which('terraform')
    if not binary:
        raise RuntimeError('Terraform >=1.5 is required. Install it or set TERRAFORM_BIN.')
    return binary


def terraform(c, *args, capture=False, check=True):
    command = [terraform_binary(), f'-chdir={TF_ROOT}', *args]
    result = subprocess.run(command, text=True, capture_output=capture, check=False)
    if check and result.returncode:
        if capture:
            print(result.stdout, end='')
            print(result.stderr, end='')
        raise RuntimeError('Terraform command failed: ' + ' '.join(args))
    return result


def select_workspace(c, create=False):
    selected = terraform(c, 'workspace', 'select', c['name'], capture=True, check=False)
    if selected.returncode and create:
        terraform(c, 'workspace', 'new', c['name'])
    elif selected.returncode:
        raise RuntimeError(f'Terraform workspace {c["name"]} is missing; deploy or plan it first.')


def secure_terraform_state(c):
    directory = TF_ROOT / 'terraform.tfstate.d' / c['name']
    if directory.exists():
        directory.chmod(0o700)
        for path in directory.glob('terraform.tfstate*'):
            if path.is_file():
                path.chmod(0o600)


def resolve_model(session, c):
    from botocore.exceptions import ClientError
    bedrock = session.client('bedrock')
    if c['engine'] == 'converse':
        runtime = session.client('bedrock-runtime')
        if not hasattr(runtime, 'converse'):
            raise RuntimeError('The installed boto3 does not expose Bedrock Converse. Upgrade requirements.')
    else:
        runtime = session.client('bedrock-agent-runtime')
        if not hasattr(runtime, 'invoke_agent'):
            raise RuntimeError('The installed boto3 does not expose Bedrock Agent Runtime. Upgrade requirements.')
    try:
        model = bedrock.get_foundation_model(modelIdentifier=c['model_id'])['modelDetails']
        return [model['modelArn']]
    except ClientError as ex:
        if c['engine'] == 'classic':
            raise ValueError(
                'engine=classic requires a foundation model ID supported by Bedrock Agents; '
                'an inference profile ID cannot be used as the agent foundation_model.'
            ) from ex
        profile = bedrock.get_inference_profile(inferenceProfileIdentifier=c['model_id'])
        return [profile['inferenceProfileArn']] + [model['modelArn'] for model in profile['models']]


def source_manifest():
    digest = hashlib.sha256()
    for path in sorted((ROOT / 'src').rglob('*')):
        if path.is_file() and path.suffix in ('.py', '.html', '.jpg', '.webp', '.woff2'):
            digest.update(str(path.relative_to(ROOT / 'src')).encode())
            digest.update(b'\0')
            digest.update(path.read_bytes())
    code_sha = digest.hexdigest()
    try:
        commit_sha = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        commit_sha = 'unversioned'
    return {
        'commit_sha': commit_sha,
        'code_sha256': code_sha,
        'build_sha': commit_sha[:12] + '-' + code_sha[:12],
    }


def initialise_state(c, existing=None):
    state = existing or {k: c[k] for k in ('account', 'region', 'name')}
    if state['account'] != c['account'] or state['region'] != c['region']:
        raise ValueError('Existing state belongs to a different account or region')
    state.setdefault('context_secret', secrets.token_urlsafe(48))
    state.setdefault('tokens', {customer: secrets.token_urlsafe(32) for customer in ('C-104', 'C-105')})
    state.setdefault('canary', 'CLOUDKICK-SYNTHETIC-' + secrets.token_hex(8).upper())
    state['engine'] = c['engine']
    state['mode'] = c['mode']
    return state


def write_tfvars(c, state):
    from src.schema import classic_functions, instructions

    agent_functions = []
    for function in classic_functions(c['mode']):
        agent_functions.append({
            'name': function['Name'],
            'description': function['Description'],
            'parameters': {
                name: {
                    'description': parameter['Description'],
                    'type': parameter['Type'],
                    'required': parameter['Required'],
                }
                for name, parameter in function['Parameters'].items()
            },
        })
    values = {
        'name': c['name'],
        'account_id': c['account'],
        'aws_region': c['region'],
        'owner': c['owner'],
        'allowed_cidr': state.get('allowed_cidr') or (presenter_ipv4() if c['allowed_cidr'] == 'auto' else c['allowed_cidr']),
        'mode': c['mode'],
        'engine': c['engine'],
        'model_id': state['model_id'],
        'model_invoke_arns': state['model_arns'],
        'agent_instruction': instructions(c['mode']),
        'agent_functions': agent_functions,
        'expires_epoch': state['expires'],
        'context_secret': state['context_secret'],
        'token_hashes': {
            hashlib.sha256(token.encode()).hexdigest(): subject
            for subject, token in state['tokens'].items()
        },
        'build_sha': state['build_sha'],
    }
    save(TF_ROOT / 'generated.auto.tfvars.json', values)


def prepare(c, session, refresh_expiry=True):
    path = state_path(c)
    existing = json.loads(path.read_text()) if path.exists() else None
    state = initialise_state(c, existing)
    if refresh_expiry or 'expires' not in state:
        state['expires'] = int(time.time()) + int(c.get('hours', 8)) * 3600
    state.update(source_manifest())
    state['allowed_cidr'] = presenter_ipv4() if c['allowed_cidr'] == 'auto' else c['allowed_cidr']
    state['model_id'] = c['model_id']
    state['model_arns'] = resolve_model(session, c)
    state['generated_at'] = datetime.now(timezone.utc).isoformat()
    save(path, state)
    write_tfvars(c, state)
    terraform(c, 'init', '-input=false')
    select_workspace(c, create=True)
    return state


def outputs(c):
    raw = terraform(c, 'output', '-json', capture=True).stdout
    return {key: item['value'] for key, item in json.loads(raw).items()}


def policy_fixture():
    return {
        'policy_name': 'CloudKick demo returns',
        'version': '2026-10-demo',
        'classification': 'FICTIONAL DEMO POLICY',
        'summary': 'Eligible synthetic items can be returned within 30 days. Other items require simulated human review.',
        'automatic_return': {
            'window_days': 30,
            'accepted_reasons': ['defect', 'unworn'],
            'approval_required': True,
        },
        'human_review': 'Items outside the automatic rules may create a simulated review case. No external support system is contacted.',
    }


def seed(session, state):
    s3 = session.client('s3')
    out = state['outputs']
    orders = [
        {
            'order_id': 'ORD-1001', 'customer_id': 'C-104',
            'lines': [
                {'line_id': 'L1', 'name': 'CloudRunner', 'price_gbp': '89.00', 'size': '9', 'colour': 'Cloud white', 'days_since_delivery': 12, 'reason': 'defect'},
                {'line_id': 'L2', 'name': 'TrailStep', 'price_gbp': '115.00', 'size': '10', 'colour': 'Black / deep teal', 'days_since_delivery': 45, 'reason': 'change_of_mind'},
            ],
        },
        {
            'order_id': 'ORD-2001', 'customer_id': 'C-105',
            'lines': [{'line_id': 'L1', 'name': 'CityStride', 'price_gbp': '72.00', 'size': '8', 'colour': 'Mist grey', 'days_since_delivery': 8, 'reason': 'unworn'}],
        },
    ]
    for order in orders:
        s3.put_object(
            Bucket=out['OrdersBucket'], Key='orders/' + order['order_id'] + '.json',
            Body=json.dumps(order).encode(), ContentType='application/json'
        )
    s3.put_object(
        Bucket=out['OrdersBucket'], Key='policies/returns.json',
        Body=json.dumps(policy_fixture()).encode(), ContentType='application/json'
    )
    records = {
        'classification': 'FICTIONAL INTERNAL CUSTOMER ARCHIVE',
        'data_classification_hints': [
            'customer_identifier', 'email_address', 'telephone_number',
            'payment_card_number',
        ],
        'canary': state['canary'],
        'customers': [
            {
                'customer_id': f'C-{number:03d}', 'name': f'Fictional Customer {number}',
                'email': f'customer{number}@example.com',
                'telephone': f'+44 7700 900{number:03d}',
                # Standard payment-industry test PAN. It passes classifier/Luhn
                # checks but is not an issued payment card number.
                'payment_card_test_number': '4111111111111111',
                'loyalty_points': number * 17,
                'support_note': 'Synthetic fixture only',
            }
            for number in range(101, 121)
        ],
    }
    s3.put_object(
        Bucket=out['PrivateBucket'], Key='cloudkick/customer-records.json',
        Body=json.dumps(records).encode(), ContentType='application/json',
        Tagging='DataClassification=ConfidentialSyntheticCustomerRecords&DemoPath=CloudKickAgentKillChain'
    )


def plan(c):
    session = clients(c)
    prepare(c, session)
    terraform(c, 'validate')
    terraform(c, 'plan', '-input=false')
    secure_terraform_state(c)


def deploy(c):
    session = clients(c)
    state = prepare(c, session)
    terraform(c, 'validate')
    terraform(c, 'apply', '-input=false', '-auto-approve')
    secure_terraform_state(c)
    state['outputs'] = outputs(c)
    state['deployed_at'] = datetime.now(timezone.utc).isoformat()
    save(state_path(c), state)
    seed(session, state)
    print('Deployment and fixture seed complete. URL:', state['outputs']['ApiUrl'])
    print('Private session material and manifest:', state_path(c).name, '(mode 0600; keep the launch links below off shared screens)')
    print('Build:', state['build_sha'], 'Mode:', state['mode'], 'Model:', state['model_id'])
    print('Presenter network allowed:', state['allowed_cidr'])
    print_launch_links(state)


def print_launch_links(state):
    base = state['outputs']['ApiUrl']
    print('Customer journey:', base + '#session=' + state['tokens']['C-104'])
    print('External assessment:', base + '#session=' + state['tokens']['C-105'])
    print('The session value stays in the URL fragment, is saved for this browser tab, and is removed from the address bar after sign-in.')


def require_state(c):
    path = state_path(c)
    if not path.exists():
        raise ValueError('Local deployment state is missing: ' + str(path))
    state = json.loads(path.read_text())
    if state.get('account') != c['account'] or state.get('region') != c['region']:
        raise ValueError('Local state does not match the configured account and region')
    return state


def reset(session, state):
    table = session.resource('dynamodb').Table(state['outputs']['StateTable'])
    kwargs = {'ProjectionExpression': 'pk, sk'}
    with table.batch_writer() as batch:
        while True:
            page = table.scan(**kwargs)
            for item in page.get('Items', []):
                batch.delete_item(Key={'pk': item['pk'], 'sk': item['sk']})
            if 'LastEvaluatedKey' not in page:
                break
            kwargs['ExclusiveStartKey'] = page['LastEvaluatedKey']
    seed(session, state)
    print('Lab application state cleared and synthetic fixtures reseeded.')


def evidence(session, c, state, job, dest):
    from boto3.dynamodb.conditions import Key
    table = session.resource('dynamodb').Table(state['outputs']['StateTable'])
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    event = table.get_item(Key={'pk': 'J#' + job, 'sk': 'STATE'}, ConsistentRead=True).get('Item')
    if not event:
        raise ValueError('Unknown job')
    traces = table.query(KeyConditionExpression=Key('pk').eq('E#' + job), ConsistentRead=True)['Items']
    manifest_keys = ('engine', 'mode', 'model_id', 'model_arns', 'commit_sha', 'code_sha256', 'build_sha', 'canary', 'outputs')
    save(dest / (job + '.json'), {
        'job': event,
        'tools': traces,
        'manifest': {key: state[key] for key in manifest_keys},
    })
    wanted = {json.loads(trace['result']).get('s3_request_id') for trace in traces}
    wanted.discard(None)
    s3 = session.client('s3')
    hits = []
    prefix = 'AWSLogs/' + c['account'] + '/CloudTrail/'
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=state['outputs']['AuditBucket'], Prefix=prefix):
        for obj in page.get('Contents', []):
            if not obj['Key'].endswith('.json.gz'):
                continue
            body = s3.get_object(Bucket=state['outputs']['AuditBucket'], Key=obj['Key'])['Body'].read()
            records = json.loads(gzip.decompress(body)).get('Records', [])
            hits.extend(record for record in records if record.get('requestID') in wanted)
    save(dest / (job + '.cloudtrail.json'), hits)
    print('Evidence saved. Matching delivered CloudTrail events:', len(hits))
    if wanted and not hits:
        print('CloudTrail delivery may be delayed. Run evidence again later; event history excludes S3 data events.')


def failures(session, state):
    sqs = session.client('sqs')
    response = sqs.receive_message(
        QueueUrl=state['outputs']['FailureQueueUrl'], MaxNumberOfMessages=10,
        VisibilityTimeout=0, WaitTimeSeconds=0, AttributeNames=['SentTimestamp', 'ApproximateReceiveCount']
    )
    messages = []
    for item in response.get('Messages', []):
        body = json.loads(item['Body'])
        messages.append({
            'job': body.get('requestPayload', {}).get('job'),
            'condition': body.get('requestContext', {}).get('condition'),
            'function_error': body.get('responseContext', {}).get('functionError'),
            'sent_timestamp': item.get('Attributes', {}).get('SentTimestamp'),
            'receive_count': item.get('Attributes', {}).get('ApproximateReceiveCount'),
        })
    print(json.dumps(messages, indent=2))


def replay(session, state, job):
    table = session.resource('dynamodb').Table(state['outputs']['StateTable'])
    try:
        table.update_item(
            Key={'pk': 'J#' + job, 'sk': 'STATE'},
            UpdateExpression='SET #s=:queued REMOVE answer',
            ConditionExpression='#s=:error',
            ExpressionAttributeNames={'#s': 'status'},
            ExpressionAttributeValues={':queued': 'queued', ':error': 'error'},
        )
    except table.meta.client.exceptions.ConditionalCheckFailedException as ex:
        raise ValueError('Replay requires a known job in error state') from ex
    session.client('lambda').invoke(
        FunctionName=state['outputs']['WorkerFunction'], InvocationType='Event',
        Payload=json.dumps({'job': job}).encode()
    )
    print('Replay queued for job:', job)


def freeze(session, state, enabled):
    lam = session.client('lambda')
    name = state['outputs']['BridgeFunction']
    if enabled:
        lam.put_function_concurrency(FunctionName=name, ReservedConcurrentExecutions=0)
    else:
        lam.delete_function_concurrency(FunctionName=name)
    print('freeze complete' if enabled else 'unfreeze complete')


def cleanup(c, state):
    write_tfvars(c, state)
    terraform(c, 'init', '-input=false')
    select_workspace(c)
    terraform(c, 'destroy', '-input=false', '-auto-approve')
    terraform(c, 'workspace', 'select', 'default')
    terraform(c, 'workspace', 'delete', c['name'])
    state_path(c).unlink(missing_ok=True)
    (TF_ROOT / 'generated.auto.tfvars.json').unlink(missing_ok=True)
    print('Terraform destroyed the named lab resources. Local deployment secrets were removed.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['plan', 'deploy', 'links', 'seed', 'reset', 'evidence', 'failures', 'replay', 'freeze', 'unfreeze', 'cleanup'])
    parser.add_argument('--config', default='config.json')
    parser.add_argument('--job')
    parser.add_argument('--dest', default='evidence')
    args = parser.parse_args()
    config = load_config(args.config)
    if args.command == 'plan':
        plan(config)
        return
    if args.command == 'deploy':
        deploy(config)
        return
    state = require_state(config)
    if args.command == 'links':
        print_launch_links(state)
        return
    session = clients(config)
    if args.command == 'cleanup':
        cleanup(config, state)
    elif args.command == 'seed':
        seed(session, state)
        print('Synthetic fixtures seeded.')
    elif args.command == 'reset':
        reset(session, state)
    elif args.command == 'evidence':
        if not args.job:
            raise ValueError('--job is required')
        evidence(session, config, state, args.job, args.dest)
    elif args.command == 'failures':
        failures(session, state)
    elif args.command == 'replay':
        if not args.job:
            raise ValueError('--job is required')
        replay(session, state, args.job)
    elif args.command == 'freeze':
        freeze(session, state, True)
    elif args.command == 'unfreeze':
        freeze(session, state, False)


if __name__ == '__main__':
    main()
