"""Durable at-most-once send attempts. Reservations precede external delivery."""
import base64
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request,urlopen

class DeliveryError(Exception):
    pass
class Conflict(DeliveryError):
    pass

def request_json(url,method='GET',payload=None,headers=None):
    data=json.dumps(payload).encode() if payload is not None else None
    h={'Content-Type':'application/json',**(headers or {})}
    try:
        with urlopen(Request(url,data=data,method=method,headers=h),timeout=25) as r:
            return json.load(r)
    except HTTPError as e:
        if e.code in [409,422]:
            raise Conflict('State write conflict; delivery suppressed') from None
        raise DeliveryError(f'Remote request failed (HTTP {e.code}); inspect service configuration') from None
    except Exception:
        # Telegram URL includes the token: never log the exception URL.
        raise DeliveryError('Remote response uncertain; automatic resend disabled') from None

def validate_state(state):
    if not isinstance(state,dict) or state.get('version') != 1 or not isinstance(state.get('alerts'),dict):
        raise DeliveryError('Malformed state; refusing to reset deduplication history')
    return state

class FileState:
    """Single-process local mode; GitHub uses server-side SHA locking."""
    def __init__(self,path):
        self.path=Path(path)
    def read(self):
        if not self.path.exists():
            return {'version':1,'alerts':{}},None
        return validate_state(json.loads(self.path.read_text(encoding='utf-8'))),None
    def write(self,state,revision):
        temp=self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(state,indent=2),encoding='utf-8')
        os.replace(temp,self.path)

class GitHubState:
    def __init__(self,repo,token,branch):
        self.url=f'https://api.github.com/repos/{repo}/contents/data/state.json'
        self.branch=branch
        self.headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json',
                      'User-Agent':'ipo-retail-monitor','X-GitHub-Api-Version':'2022-11-28'}
    def read(self):
        obj=request_json(self.url+'?ref='+quote(self.branch,safe=''),headers=self.headers)
        return validate_state(json.loads(base64.b64decode(obj['content']))),obj['sha']
    def write(self,state,revision):
        payload={'message':'Record IPO notification state [skip ci]','branch':self.branch,'sha':revision,
                 'content':base64.b64encode(json.dumps(state,indent=2).encode()).decode()}
        request_json(self.url,'PUT',payload,self.headers)

def telegram_send(message,token,chat_id):
    obj=request_json(f'https://api.telegram.org/bot{token}/sendMessage','POST',{
        'chat_id':chat_id,'text':message,'link_preview_options':{'is_disabled':True},'allow_paid_broadcast':False})
    if not obj.get('ok'):
        raise DeliveryError('Telegram rejected message; automatic resend disabled')
    return obj['result']['message_id']

def deliver_once(store,key,record,send):
    state,revision=store.read()
    if key in state['alerts']:
        return 'suppressed'
    state['alerts'][key]={**record,'status':'reserved'}
    store.write(state,revision)
    try:
        message_id=send()
    except Exception:
        raise DeliveryError('Delivery failed or uncertain. Reservation retained; inspect Telegram before manual recovery.') from None
    state,revision=store.read()
    state['alerts'][key].update(status='sent',message_id=message_id)
    store.write(state,revision)
    return 'sent'
