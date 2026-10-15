"""Shared identity context. No customer-controlled identity reaches the tools."""
import os, json, time, hashlib, hmac, base64

def packed(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))

def sign_context(subject, job, session, actor_type='customer'):
    if actor_type not in ('customer', 'support'):
        raise ValueError('invalid_actor_type')
    body = packed(dict(subject=subject, job=job, session=session,
                       actor_type=actor_type, exp=int(time.time())+300))
    raw = base64.urlsafe_b64encode(body.encode()).decode()
    sig = hmac.new(os.environ['CONTEXT_SECRET'].encode(), raw.encode(), hashlib.sha256).hexdigest()
    return {'context': raw, 'signature': sig}

def verify_context(attrs, session):
    raw = attrs.get('context', '')
    expected = hmac.new(os.environ['CONTEXT_SECRET'].encode(), raw.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, attrs.get('signature', '')):
        raise PermissionError('invalid_context')
    ctx = json.loads(base64.urlsafe_b64decode(raw))
    if ctx['exp'] < time.time() or ctx['session'] != session:
        raise PermissionError('expired_or_wrong_session')
    if int(os.environ['LAB_EXPIRES']) < time.time():
        raise PermissionError('lab_expired')
    if ctx['subject'] not in ('C-104', 'C-105'):
        raise PermissionError('unknown_subject')
    if ctx.get('actor_type') not in ('customer', 'support'):
        raise PermissionError('unknown_actor_type')
    return ctx

def approval_id(subject, order, line):
    return hashlib.sha256(f'{subject}:{order}:{line}'.encode()).hexdigest()[:24]

def review_id(subject, order, line):
    return 'REV-' + hashlib.sha256(f'review:{subject}:{order}:{line}'.encode()).hexdigest()[:12].upper()

def eligibility(line):
    # Explicit fictional retailer policy, not legal consumer-rights advice.
    if line['days_since_delivery'] <= 30 and line['reason'] in ('defect', 'unworn'):
        return 'eligible'
    return 'human_review'
