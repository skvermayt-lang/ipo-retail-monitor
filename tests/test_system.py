import copy
import json
import tempfile
import tomllib
import unittest
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import patch
from providers import IST,DataError,dated,number,parse_ig_gmp,parse_ig_subscription,parse_iw_index,parse_iw_detail,collect,IG_GMP,IG_SUB,IW_GMP
from strategy import evaluate,in_window,validate_config
from delivery import Conflict,DeliveryError,FileState,deliver_once,telegram_send,GitHubState,request_json

ROOT=Path(__file__).resolve().parents[1]
NOW=datetime(2026,10,28,15,2,tzinfo=IST)
CFG=tomllib.loads((ROOT/'config.toml').read_text(encoding='utf-8'))

def good():
    return dict(key='ig:123',name='Example Ltd',segment='mainboard',close_date='2026-10-28',
        price=100.,lot=150,gmp=20.,secondary_gmp=19.,previous_gmp=20.,qib=10.,nii=6.,retail=2.,total=5.,
        gmp_at=NOW-timedelta(minutes=10),secondary_at=NOW-timedelta(minutes=20),
        subscription_at=NOW-timedelta(minutes=5),previous_at=NOW-timedelta(days=1),
        subscription_close='2026-10-28',secondary_close='2026-10-28',subscription_price=100.,secondary_price=100.)

class StrategyTests(unittest.TestCase):
    def assess(self,**updates):
        i=good();i.update(updates)
        return evaluate(i,NOW,CFG['strategy'])
    def test_positive_case(self):
        self.assertEqual(self.assess()['verdict'],'APPLY')
        self.assertEqual(self.assess()['gmp_percent'],19)
    def test_weak_institutional_demand(self):
        self.assertEqual(self.assess(qib=0.9)['verdict'],'SKIP')
    def test_missing_is_not_zero(self):
        self.assertTrue(self.assess(qib=None)['quality'])
    def test_stale_subscription(self):
        self.assertTrue(self.assess(subscription_at=NOW-timedelta(hours=1))['quality'])
    def test_future_quote(self):
        self.assertTrue(self.assess(gmp_at=NOW+timedelta(hours=1))['quality'])
    def test_gmp_publisher_conflict(self):
        self.assertTrue(self.assess(secondary_gmp=35)['quality'])
    def test_gmp_falling(self):
        self.assertEqual(self.assess(previous_gmp=40)['verdict'],'SKIP')
    def test_missing_yesterday(self):
        self.assertTrue(self.assess(previous_at=NOW-timedelta(days=3))['quality'])
    def test_sme_excluded(self):
        self.assertEqual(self.assess(segment='sme')['verdict'],'SKIP')
    def test_not_closing_today(self):
        self.assertEqual(self.assess(close_date='2026-10-29')['verdict'],'SKIP')
    def test_retail_limit(self):
        self.assertEqual(self.assess(lot=2001)['verdict'],'SKIP')
    def test_date_conflict(self):
        self.assertTrue(self.assess(secondary_close='2026-10-29')['quality'])
    def test_price_conflict(self):
        self.assertTrue(self.assess(secondary_price=99)['quality'])
    def test_nonfinite_rejected(self):
        self.assertTrue(self.assess(gmp=float('nan'))['quality'])
    def test_negative_demand_rejected(self):
        self.assertTrue(self.assess(nii=-1)['quality'])
    def test_windows(self):
        self.assertTrue(in_window(NOW,CFG['schedule']))
        self.assertFalse(in_window(NOW.replace(hour=14),CFG['schedule']))
        self.assertFalse(in_window(NOW.replace(hour=15,minute=30),CFG['schedule']))
    def test_bad_deadline_config(self):
        bad=copy.deepcopy(CFG);bad['schedule']['broker_cutoff']='15:10'
        with self.assertRaises(ValueError):validate_config(bad)

class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=FileState(Path(self.temp.name)/'state.json')
        self.calls=[]
    def send(self):
        self.calls.append('send');return 42
    def test_restarts_do_not_duplicate(self):
        self.assertEqual(deliver_once(self.store,'ig:123',{},self.send),'sent')
        other=FileState(self.store.path)
        self.assertEqual(deliver_once(other,'ig:123',{},self.send),'suppressed')
        self.assertEqual(len(self.calls),1)
    def test_timeout_does_not_retry(self):
        def uncertain():
            self.calls.append('uncertain');raise TimeoutError()
        with self.assertRaises(DeliveryError):deliver_once(self.store,'ig:123',{},uncertain)
        self.assertEqual(deliver_once(self.store,'ig:123',{},self.send),'suppressed')
        self.assertEqual(self.calls,['uncertain'])
    def test_state_failure_prevents_send(self):
        with patch.object(self.store,'write',side_effect=DeliveryError('unavailable')):
            with self.assertRaises(DeliveryError):deliver_once(self.store,'ig:123',{},self.send)
        self.assertFalse(self.calls)
    def test_sha_conflict_prevents_send(self):
        with patch.object(self.store,'write',side_effect=Conflict('race')):
            with self.assertRaises(Conflict):deliver_once(self.store,'ig:123',{},self.send)
        self.assertFalse(self.calls)
    def test_status_write_failure_still_suppresses(self):
        write=self.store.write
        def fail_second(state,revision):
            if state['alerts']['ig:123']['status']=='sent':raise DeliveryError('offline')
            write(state,revision)
        with patch.object(self.store,'write',side_effect=fail_second):
            with self.assertRaises(DeliveryError):deliver_once(self.store,'ig:123',{},self.send)
        self.assertEqual(deliver_once(self.store,'ig:123',{},self.send),'suppressed')
        self.assertEqual(len(self.calls),1)
    def test_corrupt_state_does_not_reset(self):
        self.store.path.write_text('{"version":2}',encoding='utf-8')
        with self.assertRaises(DeliveryError):deliver_once(self.store,'ig:123',{},self.send)
        self.assertFalse(self.calls)
    def test_extended_close_does_not_duplicate(self):
        deliver_once(self.store,'ig:123',{'close_date':'2026-10-28'},self.send)
        deliver_once(self.store,'ig:123',{'close_date':'2026-10-30'},self.send)
        self.assertEqual(len(self.calls),1)
    def test_two_different_ipos(self):
        deliver_once(self.store,'ig:123',{},self.send)
        deliver_once(self.store,'ig:124',{},self.send)
        self.assertEqual(len(self.calls),2)
    def test_token_not_exposed(self):
        with patch('delivery.urlopen',side_effect=OSError('https://api.telegram.org/botSECRET/sendMessage')):
            with self.assertRaises(DeliveryError) as ctx:telegram_send('hi','SECRET','123')
        self.assertNotIn('SECRET',str(ctx.exception))
    def test_github_state_cas(self):
        store=GitHubState('owner/repo','TOKEN','main')
        with patch('delivery.request_json',return_value={}) as request:
            store.write({'version':1,'alerts':{}},'CURRENT_SHA')
        self.assertEqual(request.call_args.args[2]['sha'],'CURRENT_SHA')

class ParserTests(unittest.TestCase):
    def test_missing_premium_not_zero(self):
        self.assertIsNone(number('₹-- (0.00%)'))
        self.assertEqual(number('₹0 (0%)'),0)
        self.assertEqual(number('1,234.50x'),1234.5)
    def test_year_rollover(self):
        now=datetime(2027,1,1,15,tzinfo=IST)
        self.assertEqual(dated('31-Dec 15:00',now,['%d-%b %H:%M']).year,2026)
    def test_live_shape_fixtures(self):
        folder=ROOT/'tests'/'fixtures'
        gmp=parse_ig_gmp((folder/'gmp.html').read_text(encoding='utf-8'),NOW)
        sub=parse_ig_subscription((folder/'ig.html').read_text(encoding='utf-8'),NOW)
        iw=parse_iw_index((folder/'ipowatch.html').read_text(encoding='utf-8'))
        detail=parse_iw_detail((folder/'detail.html').read_text(encoding='utf-8'),NOW)
        self.assertTrue(gmp);self.assertIn('ig:1635',sub)
        self.assertIn('eaaaindiaalternatives',iw)
        self.assertEqual(detail['secondary_close'],'2026-10-28')
        self.assertIsNotNone(detail['secondary_at'])
        self.assertTrue(all(i['segment']=='mainboard' for i in gmp))
    def test_html_breakage_fails_closed(self):
        with self.assertRaises(DataError):parse_ig_gmp('<html>Blocked</html>',NOW)
        with self.assertRaises(DataError):parse_iw_index('<html>New layout</html>')
    def test_collection_integrates_by_id(self):
        folder=ROOT/'tests'/'fixtures'
        pages={IG_GMP:'gmp.html',IG_SUB:'ig.html',IW_GMP:'ipowatch.html'}
        def get(url):
            return (folder/pages.get(url,'detail.html')).read_text(encoding='utf-8')
        issues,errors=collect(NOW,{},get)
        self.assertFalse(errors)
        eaaa=next(i for i in issues if i['key']=='ig:1635')
        self.assertEqual(eaaa['subscription_close'],eaaa['close_date'])
        self.assertEqual(eaaa['secondary_close'],eaaa['close_date'])


class OrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.report=Path(self.temp.name)/'report.json'
        self.state=Path(self.temp.name)/'state.json'
    def run_monitor(self,issue,when=NOW,send=True,expire_after_reservation=False):
        import monitor
        args=['monitor.py','--config',str(ROOT/'config.toml'),'--report',str(self.report),'--state',str(self.state)]
        if send:args+=['--send']
        calls=[when]*4+[when.replace(minute=31)] if expire_after_reservation else None
        with patch('sys.argv',args),patch('monitor.datetime') as dt,patch('monitor.collect',return_value=([issue],[])), \
             patch.dict('os.environ',{'GITHUB_ACTIONS':'false','TELEGRAM_BOT_TOKEN':'TOKEN','TELEGRAM_CHAT_ID':'123'}), \
             patch('monitor.telegram_send',return_value=123) as sender,patch('monitor.time.sleep'),patch('builtins.print'):
            dt.now.side_effect=calls
            dt.now.return_value=when
            if expire_after_reservation:
                with self.assertRaises(DeliveryError):monitor.main()
            else:monitor.main()
        return sender.call_count,json.loads(self.report.read_text(encoding='utf-8')) if self.report.exists() else None
    def test_preview_does_not_send_or_reserve(self):
        count,r=self.run_monitor(good(),send=False)
        self.assertEqual(count,0);self.assertFalse(self.state.exists())
        self.assertEqual(r['issues'][0]['delivery'],'preview')
    def test_bad_data_waits_before_final_retry(self):
        i=good();i['qib']=None
        count,r=self.run_monitor(i)
        self.assertEqual(count,0);self.assertEqual(r['issues'][0]['delivery'],'waiting_for_data')
    def test_bad_data_final_retry_sends_one_skip(self):
        i=good();i['qib']=None
        when=NOW.replace(minute=22)
        count,r=self.run_monitor(i,when)
        self.assertEqual(count,1);self.assertEqual(r['issues'][0]['decision']['verdict'],'SKIP')
        count,r=self.run_monitor(i,when)
        self.assertEqual(count,0);self.assertEqual(r['issues'][0]['delivery'],'suppressed')
    def test_after_window_no_send(self):
        count,r=self.run_monitor(good(),NOW.replace(minute=40))
        self.assertEqual(count,0);self.assertFalse(self.state.exists())
    def test_healthy_verdict_and_restart(self):
        count,r=self.run_monitor(good())
        self.assertEqual(count,1);self.assertEqual(r['issues'][0]['decision']['verdict'],'APPLY')
        count,r=self.run_monitor(good())
        self.assertEqual(count,0);self.assertEqual(r['issues'][0]['delivery'],'suppressed')
    def test_late_reservation_cannot_send(self):
        count,r=self.run_monitor(good(),expire_after_reservation=True)
        self.assertEqual(count,0)
        self.assertEqual(json.loads(self.state.read_text())['alerts']['ig:123']['status'],'reserved')

if __name__=='__main__':unittest.main()
