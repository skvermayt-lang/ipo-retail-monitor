"""Transparent heuristics, not trained predictions or a guaranteed return."""
import math
from datetime import datetime, time, timedelta

def clock(value):
    return time.fromisoformat(value)

def validate_config(config):
    s = config['schedule']
    if not (clock(s['verdict_at']) <= clock(s['data_retry_until']) < clock(s['send_until']) < clock(s['broker_cutoff'])):
        raise ValueError('Require verdict_at <= data_retry_until < send_until < broker_cutoff')
    required = {'min_gmp_percent','min_qib','min_nii','min_retail','min_total', 'max_gmp_source_gap_pp',
                'max_gmp_drop_percent','max_subscription_age_minutes','max_gmp_age_hours','retail_limit_rupees'}
    for key in required:
        value = config['strategy'].get(key)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value < 0:
            raise ValueError('Invalid strategy setting: '+key)
    if config['strategy']['retail_limit_rupees'] > 200000:
        raise ValueError('Retail limit cannot exceed Rs 200000')

def in_window(now, schedule):
    return clock(schedule['verdict_at']) <= now.time().replace(tzinfo=None) < clock(schedule['send_until'])

def numeric(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)

def evaluate(issue, now, cfg):
    reasons, quality = [], []
    close = now.date().isoformat()
    if issue.get('segment') != 'mainboard' or issue.get('close_date') != close:
        return {'verdict':'SKIP','quality':['Not a mainboard closing today'],'reasons':[]}
    for field in ['price','lot','gmp','secondary_gmp','previous_gmp','qib','nii','retail','total']:
        if not numeric(issue.get(field)):
            quality.append('Missing/invalid '+field)
    for field in ['price','lot']:
        if numeric(issue.get(field)) and issue[field] <= 0:
            quality.append('Nonpositive '+field)
    for field in ['qib','nii','retail','total']:
        if numeric(issue.get(field)) and issue[field] < 0:
            quality.append('Negative '+field)
    for field,max_age in [('subscription_at',timedelta(minutes=cfg['max_subscription_age_minutes'])),
                          ('gmp_at',timedelta(hours=cfg['max_gmp_age_hours'])),
                          ('secondary_at',timedelta(hours=cfg['max_gmp_age_hours']))]:
        stamp = issue.get(field)
        if not isinstance(stamp,datetime) or stamp.tzinfo is None:
            quality.append('Missing publisher timestamp: '+field)
        elif stamp > now+timedelta(minutes=2) or now-stamp > max_age or stamp.date() != now.date():
            quality.append('Stale/future publisher timestamp: '+field)
    for field in ['subscription_close','secondary_close']:
        if issue.get(field) != close:
            quality.append('Closing-date mismatch/missing: '+field)
    price = issue.get('price')
    for field in ['subscription_price','secondary_price']:
        other = issue.get(field)
        if not numeric(other) or not numeric(price) or abs(other-price) > 0.01:
            quality.append('Issue-price mismatch/missing: '+field)
    prev_at = issue.get('previous_at')
    if not isinstance(prev_at,datetime) or prev_at.date() != now.date()-timedelta(days=1):
        quality.append('Previous-calendar-day GMP history missing')
    if quality:
        return dict(verdict='SKIP',quality=quality,reasons=[],gmp_percent=None)
    conservative_gmp = min(issue['gmp'],issue['secondary_gmp'])
    gmp_pct = conservative_gmp / price * 100
    gap = abs(issue['gmp']-issue['secondary_gmp']) / price * 100
    if gap > cfg['max_gmp_source_gap_pp']:
        quality.append(f'GMP publishers disagree by {gap:.2f} percentage points')
    cost = price * issue['lot']
    if cost > cfg['retail_limit_rupees']:
        reasons.append('One lot exceeds the retail application limit')
    if gmp_pct < cfg['min_gmp_percent']:
        reasons.append(f"Conservative GMP {gmp_pct:.2f}% < {cfg['min_gmp_percent']:g}%")
    for field in ['qib','nii','retail','total']:
        minimum = cfg['min_'+field]
        if issue[field] < minimum:
            reasons.append(f'{field.upper()} demand {issue[field]:g}x < {minimum:g}x')
    previous = issue['previous_gmp']
    drop = (previous-conservative_gmp) / previous * 100 if previous > 0 else 0
    if drop > cfg['max_gmp_drop_percent']:
        reasons.append(f'GMP fell {drop:.1f}% versus yesterday')
    return dict(verdict='APPLY' if not reasons and not quality else 'SKIP',quality=quality,
                reasons=reasons or (['All configured demand and GMP rules passed'] if not quality else []),
                gmp_percent=round(gmp_pct,2),lot_cost=round(cost,2),source_gap_pp=round(gap,2))

def format_message(issue,decision,now,schedule):
    def value(key,suffix=''):
        v=issue.get(key)
        return f'{v:g}{suffix}' if numeric(v) else 'unavailable'
    lines=[f"{decision['verdict']} | {issue['name']}", 'Mainboard retail | listing-day gains screen',
           f"Closing: {issue['close_date']} | Assessed: {now:%d %b %H:%M} IST",
           f"QIB {value('qib','x')} | NII {value('nii','x')} | Retail {value('retail','x')} | Total {value('total','x')}",
           f"Issue price Rs {value('price')} | Lot {value('lot')}",
           f"GMP: InvestorGain Rs {value('gmp')} / IPO Watch Rs {value('secondary_gmp')}"]
    if decision.get('gmp_percent') is not None:
        lines.append(f"Lower GMP / issue price: {decision['gmp_percent']:.2f}% (indicative)")
    if decision.get('lot_cost'):
        lines.append(f"One lot at upper price: Rs {decision['lot_cost']:,.2f}")
    for key,label in [('subscription_at','Demand updated'),('gmp_at','InvestorGain GMP'),('secondary_at','IPO Watch GMP')]:
        if isinstance(issue.get(key),datetime):
            lines.append(f'{label}: {issue[key]:%d %b %H:%M} IST')
    lines += ['Reason: '+'; '.join(decision['quality']+decision['reasons']),
              f"Configured broker cutoff: {schedule['broker_cutoff']} IST; confirm in your broker app.",
              'Pre-close snapshot; final demand can change. GMP is unofficial; gains and allotment are not assured. Rules are unbacktested.']
    lines.extend(issue[k] for k in ['subscription_url','gmp_url','secondary_url'] if issue.get(k))
    return '\n'.join(lines)[:4000]
