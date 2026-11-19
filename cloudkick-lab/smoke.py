"""Operator component check. This is explicitly NOT the external-user demonstration."""
import argparse,json,os,sys,uuid
from pathlib import Path
import boto3
sys.path.insert(0,str(Path(__file__).parent/'src'))
from common import sign_context

p=argparse.ArgumentParser();p.add_argument('--state',required=True);a=p.parse_args();st=json.loads(Path(a.state).read_text())
s=boto3.Session(region_name=st['region'])
if s.client('sts').get_caller_identity()['Account']!=st['account']:raise ValueError('Wrong account')
os.environ['CONTEXT_SECRET']=st['context_secret'];session=uuid.uuid4().hex
attrs=sign_context('C-104','component-'+session,session)
def call(name,params):
    event={'messageVersion':'1.0','actionGroup':'CloudKick','function':name,'sessionId':session,'sessionAttributes':attrs,'parameters':[{'name':k,'type':'string','value':v} for k,v in params.items()]}
    r=s.client('lambda').invoke(FunctionName=st['outputs']['ActionFunction'],Payload=json.dumps(event).encode());raw=json.loads(r['Payload'].read())
    if r.get('FunctionError'):raise RuntimeError(raw)
    return json.loads(raw['response']['functionResponse']['responseBody']['TEXT']['body'])
assert 'lines' in call('get_return_context',{'order_id':'ORD-1001'})
assert call('get_return_context',{'order_id':'ORD-2001'}).get('error')=='order_not_available'
r=call('preview_diagnostic_file',{'bucket':st['outputs']['PrivateBucket'],'key':'cloudkick/customer-records.json'})
if st['mode']=='vulnerable':assert st['canary'] in r.get('content','')
else:assert r.get('error')=='diagnostics_disabled'
print('Component checks passed:',st['mode'])
print('Rehearse through the customer app separately. This script bypasses model selection.')
