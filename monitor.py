import argparse
import json
import os
import sys
import time
import tomllib
from datetime import datetime
from pathlib import Path
from delivery import DeliveryError,FileState,GitHubState,deliver_once,telegram_send
from providers import DataError,IST,collect
from strategy import clock,evaluate,format_message,in_window,validate_config

def main():
    parser=argparse.ArgumentParser(description='Final-day mainboard retail IPO screen')
    parser.add_argument('--send',action='store_true',help='Deliver to Telegram; default is read-only preview')
    parser.add_argument('--state',default='local-state.json')
    parser.add_argument('--config',default='config.toml')
    parser.add_argument('--report',default='report.json')
    args=parser.parse_args()
    config=tomllib.loads(Path(args.config).read_text(encoding='utf-8'))
    validate_config(config)
    now=datetime.now(IST)
    schedule=config['schedule']
    if args.send and not in_window(now,schedule):
        print('Outside delivery window; no notifications.')
        return
    token,chat=os.environ.get('TELEGRAM_BOT_TOKEN'),os.environ.get('TELEGRAM_CHAT_ID')
    if args.send and (not token or not chat):
        raise DeliveryError('Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID as GitHub Secrets')
    github=os.environ.get('GITHUB_ACTIONS') == 'true'
    store=None
    if args.send:
        if github:
            store=GitHubState(os.environ['GITHUB_REPOSITORY'],os.environ['GITHUB_TOKEN'],os.environ['STATE_BRANCH'])
        else:
            store=FileState(args.state)
    issues,errors=collect(now,config.get('aliases',{}))
    now=datetime.now(IST)
    report={'assessed_at':now.isoformat(),'mode':'send' if args.send else 'preview','errors':errors,'issues':[]}
    failed=False
    for issue in issues:
        now=datetime.now(IST)
        decision=evaluate(issue,now,config['strategy'])
        message=format_message(issue,decision,now,schedule)
        status='preview'
        if args.send:
            send_time=datetime.now(IST)
            if not in_window(send_time,schedule) or send_time.date()!=now.date():
                status='expired'
            elif decision['quality'] and send_time.time()<clock(schedule['data_retry_until']):
                status='waiting_for_data'
            else:
                try:
                    def safe_send():
                        moment=datetime.now(IST)
                        if not in_window(moment,schedule) or moment.date()!=now.date():
                            raise DeliveryError('Delivery window expired after state reservation')
                        latest=evaluate(issue,moment,config['strategy'])
                        if latest != decision:
                            raise DeliveryError('Data became stale after state reservation')
                        return telegram_send(message,token,chat)
                    status=deliver_once(store,issue['key'],{
                        'name':issue['name'],'verdict':decision['verdict'],'at':send_time.isoformat(),
                        'close_date':issue['close_date'],'decision':decision},safe_send)
                    if status=='sent':
                        time.sleep(1.1)
                except DeliveryError as e:
                    failed=True
                    status='delivery_attention_required'
                    print(str(e),file=sys.stderr)
        print(message+'\nDelivery: '+status+'\n')
        report['issues'].append({'issue':issue,'decision':decision,'delivery':status,'message':message})
    Path(args.report).write_text(json.dumps(report,indent=2,default=str),encoding='utf-8')
    if not issues:
        print('No mainboard IPOs closing today in the publisher report.')
    if failed or errors:
        raise DeliveryError('Run needs attention; inspect report.json and GitHub Actions log')

if __name__=='__main__':
    try:
        main()
    except (DataError,DeliveryError,ValueError,KeyError,OSError) as e:
        print(f'Monitor stopped: {e}',file=sys.stderr)
        sys.exit(1)
