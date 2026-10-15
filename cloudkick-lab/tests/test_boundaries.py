"""Offline boundary tests. AWS calls are fakes, never proof of a deployed lab."""
import sys,os,json,time,copy,unittest,types,hashlib
from pathlib import Path
from unittest.mock import MagicMock,patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[1]/'src')]
os.environ.update(STATE_TABLE='test',LAB_EXPIRES=str(int(time.time())+1000),CONTEXT_SECRET='test-secret-'+('a'*40),LAB_MODE='vulnerable',PRIVATE_BUCKET='lab-private',ORDERS_BUCKET='lab-orders',POLICY_BUCKET='lab-orders')
fake=types.ModuleType('boto3');fake.client=MagicMock();fake.resource=MagicMock();sys.modules['boto3']=fake
conditions=types.ModuleType('boto3.dynamodb.conditions');conditions.Key=lambda value:value
sys.modules['boto3.dynamodb']=types.ModuleType('boto3.dynamodb');sys.modules['boto3.dynamodb.conditions']=conditions
import common,action,bridge,infra

class Conditional(Exception):pass
class State:
    def __init__(self):
        self.items={};self.meta=types.SimpleNamespace(client=types.SimpleNamespace(exceptions=types.SimpleNamespace(ConditionalCheckFailedException=Conditional)))
    def get_item(self,Key,**kw):
        v=self.items.get((Key['pk'],Key['sk']));return {'Item':copy.deepcopy(v)} if v else {}
    def put_item(self,Item,**kw):
        key=(Item['pk'],Item['sk'])
        if kw.get('ConditionExpression') and key in self.items:raise Conditional()
        self.items[key]=copy.deepcopy(Item)
    def update_item(self,Key,ExpressionAttributeValues,**kw):
        item=self.items[(Key['pk'],Key['sk'])];v=ExpressionAttributeValues
        if item['status']!='approved' or item['subject']!=v[':subject'] or item['expiry']<=v[':now']:raise Conditional()
        item.update(status=v[':done'],case_id=v[':case'])

class Boundaries(unittest.TestCase):
    def setUp(self):
        os.environ['LAB_MODE']='vulnerable';self.db=State();action.table=self.db;action.s3=MagicMock()
        self.ctx={'subject':'C-104','job':'job-1','actor_type':'customer'}
        self.order={'order_id':'ORD-1001','customer_id':'C-104','lines':[{'line_id':'L1','name':'CloudRunner','price_gbp':'89.00','days_since_delivery':12,'reason':'defect'},{'line_id':'L2','name':'TrailStep','price_gbp':'115.00','days_since_delivery':45,'reason':'change_of_mind'}]}
        action.s3.get_object.return_value={'Body':types.SimpleNamespace(read=lambda *a:json.dumps(self.order).encode()),'ResponseMetadata':{'RequestId':'s3-id'}}
    def call(self,name,**p):return action.execute(name,p,self.ctx)
    def test_signed_context_and_tampering(self):
        a=common.sign_context('C-104','j','s');verified=common.verify_context(a,'s');self.assertEqual(verified['subject'],'C-104');self.assertEqual(verified['actor_type'],'customer')
        a['context']=a['context'][:-2]+'AA'
        with self.assertRaises(PermissionError):common.verify_context(a,'s')
    def test_actor_type_is_signed(self):
        a=common.sign_context('C-104','j','s',actor_type='support')
        raw=json.loads(common.base64.urlsafe_b64decode(a['context']));raw['actor_type']='customer';a['context']=common.base64.urlsafe_b64encode(json.dumps(raw,separators=(',',':')).encode()).decode()
        with self.assertRaises(PermissionError):common.verify_context(a,'s')
    def test_session_binding(self):
        a=common.sign_context('C-104','j','s')
        with self.assertRaises(PermissionError):common.verify_context(a,'other')
    def test_expired_context(self):
        with patch('common.time.time',return_value=100):a=common.sign_context('C-104','j','s')
        with self.assertRaises(PermissionError):common.verify_context(a,'s')
    def test_cross_customer_denied(self):
        with self.assertRaises(PermissionError):action.load_order('C-105','ORD-1001')
    def test_two_item_outcomes(self):
        r=self.call('get_return_context',order_id='ORD-1001');self.assertEqual([x['decision'] for x in r['lines']],['eligible','human_review'])
    def test_policy_is_retrieved_from_business_data(self):
        policy={'policy_name':'CloudKick demo returns','window_days':30,'disclaimer':'Fictional demo policy.'}
        action.s3.get_object.return_value={'Body':types.SimpleNamespace(read=lambda *a:json.dumps(policy).encode()),'ResponseMetadata':{'RequestId':'policy-s3-id'}}
        r=self.call('get_return_policy');self.assertEqual(r['policy']['window_days'],30);self.assertEqual(r['s3_request_id'],'policy-s3-id')
    def test_chat_cannot_approve(self):
        self.call('request_return',order_id='ORD-1001',line_id='L1')
        with self.assertRaises(PermissionError):self.call('create_return',order_id='ORD-1001',line_id='L1',approved='true')
    def test_idempotent_return_after_server_approval(self):
        r=self.call('request_return',order_id='ORD-1001',line_id='L1');self.db.items[('A#'+r['approval_id'],'STATE')]['status']='approved'
        a=self.call('create_return',order_id='ORD-1001',line_id='L1');b=self.call('create_return',order_id='ORD-1001',line_id='L1')
        self.assertEqual(a['case_id'],b['case_id']);self.assertTrue(b['duplicate'])
    def test_ineligible_has_no_approval(self):
        self.assertEqual(self.call('request_return',order_id='ORD-1001',line_id='L2')['status'],'human_review');self.assertFalse(self.db.items)
    def test_human_review_is_persisted_and_idempotent(self):
        first=self.call('request_human_review',order_id='ORD-1001',line_id='L2');second=self.call('request_human_review',order_id='ORD-1001',line_id='L2')
        self.assertEqual(first['review_id'],second['review_id']);self.assertEqual(first['status'],'queued');self.assertFalse(first['duplicate']);self.assertTrue(second['duplicate'])
        self.assertEqual(self.db.items[('R#'+first['review_id'],'STATE')]['subject'],'C-104')
    def test_eligible_item_does_not_create_review(self):
        self.assertEqual(self.call('request_human_review',order_id='ORD-1001',line_id='L1')['status'],'automatic_return_available');self.assertFalse(self.db.items)
    def test_historical_record_target_is_bounded(self):
        with self.assertRaises(PermissionError):self.call('read_historical_service_record',bucket='outside',key='secrets')
        action.s3.get_object.assert_not_called()
    def test_secure_rejects_stale_tool(self):
        os.environ['LAB_MODE']='secure'
        with self.assertRaisesRegex(PermissionError,'support_entitlement_required'):self.call('read_historical_service_record',bucket='lab-private',key='cloudkick/customer-records.json')
        action.s3.get_object.assert_not_called()
    def test_secure_support_actor_still_has_no_historical_record_tool(self):
        os.environ['LAB_MODE']='secure';self.ctx['actor_type']='support'
        with self.assertRaisesRegex(PermissionError,'historical_record_access_disabled'):self.call('read_historical_service_record',bucket='lab-private',key='cloudkick/customer-records.json')
        action.s3.get_object.assert_not_called()
    def test_historical_search_records_list_request_id(self):
        action.s3.list_objects_v2.return_value={'Contents':[{'Key':'cloudkick/customer-records.json'},{'Key':'cloudkick/ignored.json'}],'ResponseMetadata':{'RequestId':'list-s3-id'}}
        r=self.call('search_historical_service_records');self.assertEqual(r['files'],[{'bucket':'lab-private','key':'cloudkick/customer-records.json'}]);self.assertEqual(r['s3_request_id'],'list-s3-id')
    def test_vulnerable_private_read_is_real_tool_output(self):
        action.s3.get_object.return_value={'Body':types.SimpleNamespace(read=lambda *a:b'{"canary":"SYNTHETIC"}'),'ResponseMetadata':{'RequestId':'s3-id'}}
        r=self.call('read_historical_service_record',bucket='lab-private',key='cloudkick/customer-records.json');self.assertIn('SYNTHETIC',r['content']);self.assertEqual(r['s3_request_id'],'s3-id')
    def test_template_modes_and_dependencies(self):
        for engine in ('classic','converse'):
            ts=[]
            for mode in ('vulnerable','secure'):
                c=dict(name='cloudkick-test',region='eu-west-2',account='123456789012',mode=mode,engine=engine,owner='Test',expires=9999999999,model_id='selected-model',model_arns=['arn:aws:bedrock:eu-west-2::foundation-model/selected-model'],allowed_cidr='192.0.2.10/32',token_hashes={'abc':'C-104'})
                t=infra.template(c,'artifacts','code.zip');ts.append(t)
                graph={k:set() for k in t['Resources']}
                def visit(x,owner):
                    if isinstance(x,dict):
                        if 'Ref' in x and x['Ref'] in graph:graph[owner].add(x['Ref'])
                        if 'Fn::GetAtt' in x:graph[owner].add(x['Fn::GetAtt'][0])
                        for v in x.values():visit(v,owner)
                    elif isinstance(x,list):
                        for v in x:visit(v,owner)
                for k,v in t['Resources'].items():
                    visit(v,k);graph[k].update(v.get('DependsOn',[]))
                done=set()
                def dfs(k,path):
                    self.assertNotIn(k,path,'CloudFormation dependency cycle')
                    if k not in done:
                        for dep in graph[k]:dfs(dep,path|{k})
                        done.add(k)
                for k in graph:dfs(k,set())
            p=lambda t:json.dumps(t['Resources']['ActionRole']['Properties']['Policies'])
            self.assertIn('/cloudkick/customer-records.json',p(ts[0]));self.assertNotIn('/cloudkick/customer-records.json',p(ts[1]))
            if engine=='classic':self.assertEqual(len(ts[1]['Resources']['Agent']['Properties']['ActionGroups'][0]['FunctionSchema']['Functions']),5)

class BridgeBoundaries(unittest.TestCase):
    def setUp(self):
        self.token='customer-token';os.environ.update(TOKEN_HASHES=json.dumps({hashlib.sha256(self.token.encode()).hexdigest():'C-104'}),WORKER_ARN='worker',ENGINE='converse',LAB_MODE='vulnerable',BUILD_SHA='test-build')
        self.db=MagicMock();self.db.meta.client.exceptions.ConditionalCheckFailedException=Conditional;bridge.table=self.db;bridge.lam=MagicMock()
    def call(self,path,method='GET',body=None):
        event={'path':path,'httpMethod':method,'headers':{'Authorization':'Bearer '+self.token},'body':json.dumps(body or {})}
        return bridge.handler(event,types.SimpleNamespace(aws_request_id='request-1'))
    def test_foreign_job_is_not_disclosed(self):
        self.db.get_item.return_value={'Item':{'subject':'C-105','status':'complete','answer':'private'}}
        r=self.call('/jobs/'+'a'*32);self.assertEqual(r['statusCode'],404);self.assertNotIn('private',r['body'])
    def test_owned_job_returns_structured_ui_actions(self):
        self.db.get_item.return_value={'Item':{'subject':'C-104','status':'complete','answer':'Review the return.','ui_actions':json.dumps([{'type':'return_approval','id':'a'*24}])}}
        r=self.call('/jobs/'+'a'*32);self.assertEqual(r['statusCode'],200);self.assertEqual(json.loads(r['body'])['actions'][0]['type'],'return_approval')
    def test_static_assets_are_public_and_base64_encoded(self):
        r=bridge.handler({'path':'/assets/cloudrunner-grey.png','httpMethod':'GET'},types.SimpleNamespace(aws_request_id='request-1'))
        self.assertEqual(r['statusCode'],200);self.assertTrue(r['isBase64Encoded']);self.assertEqual(r['headers']['Content-Type'],'image/png')
    def test_foreign_approval_is_not_disclosed(self):
        self.db.get_item.return_value={'Item':{'subject':'C-105','approval_id':'a'*24,'status':'pending','item_name':'other customer item'}}
        r=self.call('/approvals/'+'a'*24);self.assertEqual(r['statusCode'],404);self.assertNotIn('other customer item',r['body'])
    def test_foreign_review_is_not_disclosed(self):
        self.db.get_item.return_value={'Item':{'subject':'C-105','review_id':'REV-'+'A'*12,'status':'queued','item_name':'other customer item'}}
        r=self.call('/reviews/'+'REV-'+'A'*12);self.assertEqual(r['statusCode'],404);self.assertNotIn('other customer item',r['body'])
    def test_owned_review_exposes_only_customer_fields(self):
        self.db.get_item.return_value={'Item':{'subject':'C-104','review_id':'REV-'+'A'*12,'status':'queued','order_id':'ORD-1001','line_id':'L2','item_name':'TrailStep','reason':'change_of_mind','expiry':123,'internal_note':'do not expose'}}
        r=self.call('/reviews/'+'REV-'+'A'*12);self.assertEqual(r['statusCode'],200);self.assertNotIn('internal_note',r['body'])
    def test_foreign_approval_cannot_be_approved(self):
        self.db.update_item.side_effect=Conditional()
        r=self.call('/approve','POST',{'approval_id':'a'*24});self.assertEqual(r['statusCode'],409)

if __name__=='__main__':unittest.main()
