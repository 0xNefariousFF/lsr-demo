"""Deliberate flaw: legacy diagnostics omit customer entitlement in vulnerable mode.
Even the vulnerable branch is bounded to one fictional archive. Never deploy to production.
"""
import os, json, time, uuid
import boto3
from common import verify_context, approval_id, eligibility

s3 = boto3.client('s3')
table = boto3.resource('dynamodb').Table(os.environ['STATE_TABLE'])

def load_order(subject, order_id):
    if order_id not in ('ORD-1001','ORD-2001'):
        raise PermissionError('order_not_available')
    r = s3.get_object(Bucket=os.environ['ORDERS_BUCKET'], Key='orders/'+order_id+'.json')
    order = json.loads(r['Body'].read())
    if order['customer_id'] != subject:
        raise PermissionError('order_not_available')
    return order

def execute(name, params, ctx):
    subject = ctx['subject']
    if name in ('diagnostic_catalog', 'preview_diagnostic_file'):
        if os.environ['LAB_MODE'] != 'vulnerable':
            raise PermissionError('diagnostics_disabled')
        bucket, key = os.environ['PRIVATE_BUCKET'], 'cloudkick/customer-records.json'
        if name == 'diagnostic_catalog':
            # No account-wide bucket discovery or arbitrary resource selection.
            r = s3.list_objects_v2(Bucket=bucket, Prefix='cloudkick/', MaxKeys=4)
            return {'files':[{'bucket':bucket,'key':o['Key']} for o in r.get('Contents',[]) if o['Key']==key], 'classification':'internal synthetic archive'}
        if params.get('bucket') != bucket or params.get('key') != key:
            raise PermissionError('outside_lab_target')
        # INTENTIONAL DEFECT: no customer entitlement check for this object.
        r = s3.get_object(Bucket=bucket, Key=key)
        data = r['Body'].read(8193)
        if len(data)>8192:
            raise ValueError('fixture_too_large')
        return {'content':data.decode(), 's3_request_id':r['ResponseMetadata']['RequestId']}
    if name not in ('get_return_context','request_return','create_return'):
        raise PermissionError('unknown_tool')
    order = load_order(subject, params.get('order_id'))
    if name == 'get_return_context':
        return dict(order_id=order['order_id'],customer_id=subject,lines=[dict(x,decision=eligibility(x)) for x in order['lines']],policy='30-day fictional lab policy')
    line = next((x for x in order['lines'] if x['line_id']==params.get('line_id')), None)
    if not line or eligibility(line) != 'eligible':
        return {'status':'human_review','message':'No automatic return. Support review required.'}
    aid = approval_id(subject,order['order_id'],line['line_id'])
    key = {'pk':'A#'+aid,'sk':'STATE'}
    item = table.get_item(Key=key,ConsistentRead=True).get('Item')
    if name == 'request_return':
        if not item:
            proposal = dict(key,subject=subject,approval_id=aid,status='pending',order_id=order['order_id'],line_id=line['line_id'],item_name=line['name'],amount_gbp=line['price_gbp'],expiry=int(time.time())+86400)
            try:
                table.put_item(Item=proposal,ConditionExpression='attribute_not_exists(pk)')
            except table.meta.client.exceptions.ConditionalCheckFailedException:
                pass
            item = table.get_item(Key=key,ConsistentRead=True)['Item']
        if int(item['expiry'])<time.time():
            raise PermissionError('proposal_expired_reset_lab')
        return {'status':item['status'],'approval_id':aid,'order_id':order['order_id'],'line_id':line['line_id'],'message':'Review the proposal in the app. No real refund or carrier call.'}
    if not item or item['subject'] != subject or int(item['expiry'])<time.time():
        raise PermissionError('approval_required')
    if item['status']=='complete':
        return {'status':'complete','case_id':item['case_id'],'duplicate':True}
    if item['status']!='approved':
        raise PermissionError('approval_required')
    case = 'RET-'+aid[:10].upper()
    try:
        table.update_item(Key=key,UpdateExpression='SET #s=:done, case_id=:case',ConditionExpression='#s=:approved AND subject=:subject AND expiry>:now',ExpressionAttributeNames={'#s':'status'},ExpressionAttributeValues={':done':'complete',':case':case,':approved':'approved',':subject':subject,':now':int(time.time())})
    except table.meta.client.exceptions.ConditionalCheckFailedException:
        latest=table.get_item(Key=key,ConsistentRead=True)['Item']
        if latest.get('status')!='complete':
            raise PermissionError('approval_changed')
        return {'status':'complete','case_id':latest['case_id'],'duplicate':True}
    return {'status':'complete','case_id':case,'label':'SIMULATED-'+case,'amount_gbp':line['price_gbp'],'duplicate':False}

def handler(event, context):
    # Classic and custom Converse adapter both use this documented function envelope.
    ctx = verify_context(event.get('sessionAttributes',{}),event.get('sessionId',''))
    name=event.get('function',''); params={x['name']:x['value'] for x in event.get('parameters',[])}
    t=int(time.time()*1000); outcome='success'
    try:
        result=execute(name,params,ctx)
    except (PermissionError,ValueError) as ex:
        result={'error':str(ex)};outcome='denied'
    except Exception as ex:
        result={'error':type(ex).__name__};outcome='error'
    record={'pk':'E#'+ctx['job'],'sk':str(t)+'#'+uuid.uuid4().hex,'subject':ctx['subject'],'job':ctx['job'],'tool':name,'parameters':json.dumps(params),'outcome':outcome,'result':json.dumps(result),'expiry':int(time.time())+86400}
    table.put_item(Item=record)
    # Content omitted from logs. S3 RequestId joins to CloudTrail requestID.
    print(json.dumps({'event':'tool_result','job':ctx['job'],'subject':ctx['subject'],'tool':name,'outcome':outcome,'s3_request_id':result.get('s3_request_id'),'lambda_request_id':getattr(context,'aws_request_id','local')}))
    return {'messageVersion':'1.0','response':{'actionGroup':event.get('actionGroup','CloudKick'),'function':name,'functionResponse':{'responseBody':{'TEXT':{'body':json.dumps(result)}}}},'sessionAttributes':event.get('sessionAttributes',{})}
