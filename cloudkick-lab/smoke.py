#!/usr/bin/env python3
"""Operator component checks. This is not the external-user demonstration."""
import argparse
import json
import os
import sys
import uuid
from pathlib import Path

import boto3

sys.path.insert(0, str(Path(__file__).parent / 'src'))
from common import sign_context


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', required=True)
    args = parser.parse_args()
    state = json.loads(Path(args.state).read_text())
    session = boto3.Session(region_name=state['region'])
    account = session.client('sts').get_caller_identity()['Account']
    if account != state['account']:
        raise ValueError(f'Wrong account: expected {state["account"]}, received {account}')

    os.environ['CONTEXT_SECRET'] = state['context_secret']
    conversation = uuid.uuid4().hex
    attrs = sign_context('C-104', 'component-' + conversation, conversation, actor_type='customer')
    action = session.client('lambda')
    failures = []

    def call(name, params=None):
        event = {
            'messageVersion': '1.0', 'actionGroup': 'CloudKick', 'function': name,
            'sessionId': conversation, 'sessionAttributes': attrs,
            'parameters': [
                {'name': key, 'type': 'string', 'value': str(value)}
                for key, value in (params or {}).items()
            ],
        }
        response = action.invoke(
            FunctionName=state['outputs']['ActionFunction'],
            Payload=json.dumps(event).encode(),
        )
        payload = json.loads(response['Payload'].read())
        if response.get('FunctionError'):
            raise RuntimeError(payload)
        body = payload['response']['functionResponse']['responseBody']['TEXT']['body']
        return json.loads(body)

    def check(label, condition, detail=''):
        if condition:
            print('PASS', label)
        else:
            failures.append(label)
            print('FAIL', label, detail)

    policy = call('get_return_policy')
    check('fixed return policy is readable', policy.get('policy', {}).get('automatic_return', {}).get('window_days') == 30, repr(policy))

    owned = call('get_return_context', {'order_id': 'ORD-1001'})
    decisions = [line.get('decision') for line in owned.get('lines', [])]
    check('owned order returns both demo decisions', decisions == ['eligible', 'human_review'], repr(owned))

    foreign = call('get_return_context', {'order_id': 'ORD-2001'})
    check('cross-customer order is denied', foreign.get('error') == 'order_not_available', repr(foreign))

    first_review = call('request_human_review', {'order_id': 'ORD-1001', 'line_id': 'L2'})
    second_review = call('request_human_review', {'order_id': 'ORD-1001', 'line_id': 'L2'})
    review_ok = (
        first_review.get('status') == 'queued'
        and first_review.get('review_id', '').startswith('REV-')
        and second_review.get('review_id') == first_review.get('review_id')
        and second_review.get('duplicate') is True
    )
    check('human review is persistent and idempotent', review_ok, repr([first_review, second_review]))

    target = {'bucket': state['outputs']['PrivateBucket'], 'key': 'cloudkick/customer-records.json'}
    catalog = call('search_historical_service_records')
    preview = call('read_historical_service_record', target)
    if state['mode'] == 'vulnerable':
        check('bounded historical record search records an S3 request', bool(catalog.get('s3_request_id')) and catalog.get('files') == [target], repr(catalog))
        check('vulnerable mode reads only the seeded synthetic canary', state['canary'] in preview.get('content', '') and bool(preview.get('s3_request_id')), repr(preview))
    else:
        check('secure mode rejects historical record search for customer actor', catalog.get('error') == 'support_entitlement_required', repr(catalog))
        check('secure mode rejects stale historical record read for customer actor', preview.get('error') == 'support_entitlement_required', repr(preview))

    check('deployed build is recorded', bool(state.get('commit_sha')) and bool(state.get('code_sha256')) and bool(state.get('build_sha')))
    if failures:
        print('Component checks failed:', ', '.join(failures))
        raise SystemExit(1)
    print('All operator component checks passed:', state['mode'], state['build_sha'])
    print('Rehearse through the customer app separately; this script intentionally bypasses model selection.')


if __name__ == '__main__':
    main()
