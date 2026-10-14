#!/usr/bin/env python3
"""Deploy, collect evidence and remove only this lab. Requires boto3 locally."""
import argparse, json, os, time, zipfile, io, hashlib, secrets, ipaddress, re, gzip
from pathlib import Path
from datetime import datetime,timezone
from infra import template

ROOT=Path(__file__).resolve().parent
def save(path,data):
    path.write_text(json.dumps(data,indent=2,default=str));path.chmod(0o600)

def load_config(path):
    c=json.loads(Path(path).read_text())
    if c.get('is_isolated_lab') is not True:raise ValueError('Use a dedicated isolated lab account and set is_isolated_lab=true.')
    if not re.fullmatch(r'cloudkick-[a-z0-9-]{1,16}',c['name']):raise ValueError('name must start cloudkick- and be at most 26 characters')
    if c['engine'] not in ('classic','converse') or c['mode'] not in ('vulnerable','secure'):raise ValueError('Invalid mode or engine')
    if not re.fullmatch(r'\d{12}',c['account']):raise ValueError('Explicit 12-digit lab account required')
    ip=ipaddress.ip_network(c['allowed_cidr'])
    if ip.version!=4 or ip.prefixlen<24:raise ValueError('Use the presenter IPv4 /32 or a narrow lab range /24 or smaller')
    if not 1<=int(c.get('hours',8))<=24:raise ValueError('Lab expiry must be 1 to 24 hours')
    return c

def clients(c):
    import boto3
    s=boto3.Session(region_name=c['region'])
    if s.client('sts').get_caller_identity()['Account']!=c['account']:raise ValueError('AWS account mismatch')
    return s

def state_path(c):return ROOT/(c['name']+'.state.json')

def resolve_model(s,c):
    bed=s.client('bedrock')
    try:
        m=bed.get_foundation_model(modelIdentifier=c['model_id'])['modelDetails']
        return [m['modelArn']]
    except Exception:
        # Both profile ARN and profile ID are accepted by this API.
        p=bed.get_inference_profile(inferenceProfileIdentifier=c['model_id'])
        return [p['inferenceProfileArn']]+[m['modelArn'] for m in p['models']]

def seed(s,c,state):
    s3=s.client('s3');out=state['outputs']
    orders=[{'order_id':'ORD-1001','customer_id':'C-104','lines':[{'line_id':'L1','name':'CloudRunner','price_gbp':'89.00','days_since_delivery':12,'reason':'defect'},{'line_id':'L2','name':'TrailStep','price_gbp':'115.00','days_since_delivery':45,'reason':'change_of_mind'}]}, {'order_id':'ORD-2001','customer_id':'C-105','lines':[{'line_id':'L1','name':'CityStride','price_gbp':'72.00','days_since_delivery':8,'reason':'unworn'}]}]
    for o in orders:s3.put_object(Bucket=out['OrdersBucket'],Key='orders/'+o['order_id']+'.json',Body=json.dumps(o).encode(),ContentType='application/json')
    records={'classification':'FICTIONAL INTERNAL CUSTOMER ARCHIVE','canary':state['canary'],'customers':[{'customer_id':f'C-{i:03d}','name':f'Fictional Customer {i}','email':f'customer{i}@example.test','loyalty_points':i*17,'support_note':'Synthetic fixture only'} for i in range(101,121)]}
    s3.put_object(Bucket=out['PrivateBucket'],Key='cloudkick/customer-records.json',Body=json.dumps(records).encode(),ContentType='application/json')

def deploy(c):
    s=clients(c);cf=s.client('cloudformation');s3=s.client('s3');path=state_path(c)
    if path.exists():
        state=json.loads(path.read_text())
        if state['account']!=c['account'] or state['region']!=c['region']:raise ValueError('Existing state belongs to a different account or region')
        if state['engine']!=c['engine']:raise ValueError('Use a new name when changing engine')
    else:
        state={k:c[k] for k in ('account','region','name','engine')}
        state.update(context_secret=secrets.token_urlsafe(48),tokens={x:secrets.token_urlsafe(32) for x in ('C-104','C-105')},canary='CLOUDKICK-SYNTHETIC-'+secrets.token_hex(8).upper())
    c['expires']=int(time.time())+int(c.get('hours',8))*3600
    c['token_hashes']={hashlib.sha256(token.encode()).hexdigest():sub for sub,token in state['tokens'].items()}
    c['model_arns']=resolve_model(s,c)
    artifact=f'{c["name"]}-{c["account"]}-{c["region"]}-artifacts'
    if not state.get('artifact_bucket'):
        kwargs={'Bucket':artifact}
        if c['region']!='us-east-1':kwargs['CreateBucketConfiguration']={'LocationConstraint':c['region']}
        s3.create_bucket(**kwargs)
        s3.put_public_access_block(Bucket=artifact,PublicAccessBlockConfiguration={k:True for k in ('BlockPublicAcls','IgnorePublicAcls','BlockPublicPolicy','RestrictPublicBuckets')})
        s3.put_bucket_encryption(Bucket=artifact,ServerSideEncryptionConfiguration={'Rules':[{'ApplyServerSideEncryptionByDefault':{'SSEAlgorithm':'AES256'}}]})
        s3.put_bucket_tagging(Bucket=artifact,Tagging={'TagSet':[{'Key':'Project','Value':'CloudKick'},{'Key':'LabName','Value':c['name']}]})
        state['artifact_bucket']=artifact;save(path,state)
    memory=io.BytesIO()
    with zipfile.ZipFile(memory,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted((ROOT/'src').iterdir()):
            if p.is_file() and p.suffix in ('.py','.html'):
                info=zipfile.ZipInfo(p.name,(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;z.writestr(info,p.read_bytes())
    payload=memory.getvalue();digest=hashlib.sha256(payload).hexdigest();key='code/'+digest+'.zip'
    s3.put_object(Bucket=artifact,Key=key,Body=payload)
    t=template(c,artifact,key);body=json.dumps(t);save(ROOT/(c['name']+'.template.json'),t)
    cf.validate_template(TemplateBody=body)
    args=dict(StackName=c['name'],TemplateBody=body,Parameters=[{'ParameterKey':'ContextSecret','ParameterValue':state['context_secret']}],Capabilities=['CAPABILITY_NAMED_IAM'],Tags=[{'Key':'Project','Value':'CloudKick'}])
    try:
        cf.describe_stacks(StackName=c['name']);exists=True
    except cf.exceptions.ClientError as ex:
        if 'does not exist' not in str(ex):raise
        exists=False
    if exists:
        try:cf.update_stack(**args)
        except cf.exceptions.ClientError as ex:
            if 'No updates are to be performed' not in str(ex):raise
        else:cf.get_waiter('stack_update_complete').wait(StackName=c['name'])
    else:
        cf.create_stack(**args);cf.get_waiter('stack_create_complete').wait(StackName=c['name'])
    stack=cf.describe_stacks(StackName=c['name'])['Stacks'][0]
    state.update(outputs={x['OutputKey']:x['OutputValue'] for x in stack.get('Outputs',[])},mode=c['mode'],model_id=c['model_id'],model_arns=c['model_arns'],code_sha256=digest,expires=c['expires'])
    save(path,state);seed(s,c,state)
    print('Deployment complete. URL:',state['outputs']['ApiUrl'])
    print('Tokens and configuration:',path.name,'(keep private; tokens are not printed)')
    print('Record model ID, alias, code hash and mode before rehearsal.')

def evidence(s,c,state,job,dest):
    from boto3.dynamodb.conditions import Key
    table=s.resource('dynamodb').Table(state['outputs']['StateTable']);dest=Path(dest);dest.mkdir(parents=True,exist_ok=True)
    event=table.get_item(Key={'pk':'J#'+job,'sk':'STATE'},ConsistentRead=True).get('Item')
    if not event:raise ValueError('Unknown job')
    traces=table.query(KeyConditionExpression=Key('pk').eq('E#'+job),ConsistentRead=True)['Items']
    save(dest/(job+'.json'),{'job':event,'tools':traces,'manifest':{k:state[k] for k in ('engine','mode','model_id','model_arns','code_sha256','canary','outputs')}})
    wanted={json.loads(t['result']).get('s3_request_id') for t in traces};wanted.discard(None)
    s3=s.client('s3');hits=[]
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=state['outputs']['AuditBucket'],Prefix='AWSLogs/'+c['account']+'/CloudTrail/'):
        for obj in page.get('Contents',[]):
            if not obj['Key'].endswith('.json.gz'):continue
            records=json.loads(gzip.decompress(s3.get_object(Bucket=state['outputs']['AuditBucket'],Key=obj['Key'])['Body'].read())).get('Records',[])
            hits.extend(e for e in records if e.get('requestID') in wanted)
    save(dest/(job+'.cloudtrail.json'),hits)
    print('Evidence saved. Matching delivered CloudTrail events:',len(hits))
    if wanted and not hits:print('CloudTrail delivery may be delayed. Run evidence again later. Event history excludes S3 data events.')

def cleanup(s,c,state):
    cf=s.client('cloudformation');s3=s.client('s3')
    try:
        cf.describe_stacks(StackName=c['name']);cf.delete_stack(StackName=c['name']);cf.get_waiter('stack_delete_complete').wait(StackName=c['name'])
    except cf.exceptions.ClientError as ex:
        if 'does not exist' not in str(ex):raise
    # Data buckets are deliberately retained until stack/trail deletion finishes.
    buckets=[f'{c["name"]}-{c["account"]}-{c["region"]}-{x}' for x in ('orders','private','audit','artifacts')]
    for b in buckets:
        try:tags=s3.get_bucket_tagging(Bucket=b)['TagSet']
        except s3.exceptions.ClientError as ex:
            if ex.response['Error']['Code'] in ('NoSuchBucket','404'):continue
            raise
        if not any(t['Key']=='Project' and t['Value']=='CloudKick' for t in tags):raise ValueError('Refusing untagged bucket '+b)
        for page in s3.get_paginator('list_objects_v2').paginate(Bucket=b):
            objs=[{'Key':o['Key']} for o in page.get('Contents',[])]
            if objs:s3.delete_objects(Bucket=b,Delete={'Objects':objs})
        s3.delete_bucket(Bucket=b)
    state_path(c).unlink(missing_ok=True)
    print('Stack and four lab buckets removed. Remove local token/state backups separately.')

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['deploy','evidence','freeze','unfreeze','cleanup']);p.add_argument('--config',default='config.json');p.add_argument('--job');p.add_argument('--dest',default='evidence');a=p.parse_args();c=load_config(a.config)
    if a.command=='deploy':deploy(c);return
    s=clients(c);path=state_path(c);state=json.loads(path.read_text()) if path.exists() else {}
    if a.command=='cleanup':cleanup(s,c,state);return
    if a.command in ('freeze','unfreeze'):
        lam=s.client('lambda')
        if a.command=='freeze':lam.put_function_concurrency(FunctionName=c['name']+'-bridge',ReservedConcurrentExecutions=0)
        else:lam.delete_function_concurrency(FunctionName=c['name']+'-bridge')
        print(a.command,'complete');return
    if not a.job:raise ValueError('--job is required')
    evidence(s,c,state,a.job,a.dest)
if __name__=='__main__':main()
