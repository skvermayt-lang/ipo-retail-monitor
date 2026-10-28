# Retail IPO Verdict Monitor

A free-to-run Python monitor for **Indian mainboard retail IPOs and listing-day gains**. It discovers issues closing today, checks final-day subscription demand against two GMP publishers, and attempts one Telegram verdict per issue.

**Status:** published to [skvermayt-lang/ipo-retail-monitor](https://github.com/skvermayt-lang/ipo-retail-monitor). All 38 tests passed locally and on GitHub Actions. Telegram activation still requires your bot secrets. No trade is placed. This is an unbacktested rules-based screen, not an investment advisory service or a guarantee of profit.

## What a verdict means

`APPLY` means every configured screening condition passed. `SKIP` means a condition failed or reliable data was unavailable by the final retry. A positive result is not a prediction of listing returns. No valuation, financial-statement, governance or broader-market analysis is performed.

The default conditions are:

| Check | Requirement |
| --- | --- |
| Scope | Mainboard IPO closing today; SME excluded |
| QIB subscription | At least 5x |
| NII subscription | At least 3x |
| Retail subscription | At least 1x |
| Total subscription | At least 3x |
| Conservative GMP / upper issue price | At least 15% using the lower of two quotes |
| GMP disagreement | At most 5 percentage points of issue price |
| GMP decline | At most 20% versus previous calendar day's IPO Watch GMP |
| Subscription timestamp | Today, no older than 30 minutes |
| GMP timestamps | Today, no older than 24 hours |
| One-lot application | At most Rs 200,000 at the upper price |
| Identity checks | Stable InvestorGain issuer ID; exact reviewed secondary name; agreeing issue prices and closing dates |

These thresholds are initial heuristics, not statistically validated cutoffs. Edit `config.toml` to change them. Do not lower data-quality protections just to produce more APPLY alerts. Zero is a valid observation; an absent value is never treated as zero.

## Final day timing

All application logic uses IST (UTC+05:30), independent of the runner timezone. Default scheduled attempts: **15:02, 15:12 and 15:22 IST, Monday-Friday**. A healthy-data verdict is sent on the first eligible run. Later runs suppress the same issue, even if the verdict changes.

- Evaluation window starts 15:00.
- Incomplete/stale/conflicting data waits until 15:20, then produces a single SKIP explaining the data problem.
- No messages are initiated at or after 15:30.
- Configured broker cutoff is 16:00. **Confirm your actual broker cutoff before enabling delivery.** This is a conservative configuration assumption, not an exchange deadline.
- If you change the evaluation window, change the workflow cron too. Cron is in UTC: subtract 5 hours 30 minutes from IST.
- The bot checks the delivery window and freshness again after reserving an alert, immediately before sending.

Fully final subscription figures arrive after bidding has closed. The actionable verdict necessarily uses a provisional final-day snapshot before your broker cutoff. Later revisions will not trigger a second message.

GitHub schedules are best effort: jobs may be delayed or dropped. A delayed run expires rather than sending a late APPLY. Use the manual workflow in the permitted window if a scheduled run is delayed. There is no guaranteed delivery time on this free setup.

## Deploy to GitHub without paid hosting

1. Create a **new public repository** named `ipo-retail-monitor`. Standard Linux GitHub Actions runners on public repositories currently have no runner charges. Do not select larger paid runners, add paid APIs, or enable paid Telegram broadcasts.
2. Upload this entire folder, **including `.github/workflows` and `data/state.json`**, to the repository root. Keep a copy of the initial state; never reset an active state file.
3. In repository **Settings -> Secrets and variables -> Actions**, add:
   - `TELEGRAM_BOT_TOKEN`: your own BotFather token.
   - `TELEGRAM_CHAT_ID`: the destination chat ID.
4. Keep credentials out of source files, issues, screenshots and chat. `GITHUB_TOKEN` is supplied automatically by Actions; a personal access token is not required.
5. In **Settings -> Actions -> General**, permit the repository workflow to write contents. The workflow requests `contents: write` to commit deduplication reservations. Organization or branch-protection policies may still block it; check logs. Never bypass a policy silently.
6. Review `config.toml`, especially your broker cutoff, before allowing scheduled delivery.
7. Under **Actions -> IPO verdict monitor -> Run workflow**, choose `preview`. Check the summary for data-source errors and identities. Preview sends nothing and changes no notification state.
8. Run **Telegram connection check** to verify the bot can access the destination. This checks access without sending a message.
9. During the configured window, choose `send` to run a real verdict. Scheduled runs use send automatically after secrets are configured.

The code writes only public issuer names, rule outcomes, timestamps and Telegram message IDs into `data/state.json`. No bot token or chat ID is committed. On a public repository this state and workflow logs are public. Keep the repository dedicated to this monitor; do not upload private investment records.

If using Git locally, create the empty repository first and run from this folder:

```powershell
git init -b main
git add .
git commit -m "Build retail IPO verdict monitor"
git remote add origin https://github.com/YOUR_USERNAME/ipo-retail-monitor.git
git push -u origin main
```

If the remote already contains an initial README, clone it and copy this folder's contents into the clone before committing; do not force-push over existing work.

## Telegram setup

Create a bot using [@BotFather](https://t.me/BotFather), open your bot, and send `/start`. For a channel, add the bot with posting rights. For a group, add the bot and send a command that it can receive.

Install Python 3.11 or newer, then run:

```powershell
python -m pip install -r requirements.txt
python bot_setup.py
```

The helper asks for the token with hidden input and prints chat IDs found in recent bot updates. It does not save the token or send a message. An existing webhook prevents `getUpdates`; do not reuse a bot controlled by another application unless you deliberately change that integration.

Add the chosen ID and token in GitHub Secrets. Do not put a token into a browser URL or command line. If a token is exposed, revoke it through BotFather and replace the secret.

## Duplicate prevention and delivery tradeoff

The deployed bot uses `data/state.json` on the default branch as its durable ledger. It reads the latest file through the GitHub API, reserves the stable issuer ID using a compare-and-swap SHA write, **then** calls Telegram once. Overlapping workflow runs are serialized. State write failures and SHA conflicts stop delivery. Closing-date extensions and name changes do not reset an issuer's key.

A successful Telegram response changes `reserved` to `sent`. Both statuses suppress future attempts. No expiration or automatic reset is applied.

Telegram `sendMessage` has no client idempotency key. Exactly-once delivery cannot be guaranteed across a network timeout. This design prioritizes **at-most-once send attempts**: a crash after reservation or an uncertain response can mean a missed message. It never automatically retries that reservation. Check your Telegram chat and Actions logs before manually removing a reservation for a recovery attempt. Manual resets, a second repository or a different state file can create duplicates. Use only one active deployment. Local FileState is single-process only and does not share the deployed ledger.

The private bot token/chat ID are not included in public state. Avoid deleting, reverting, or force-pushing the ledger. A malformed or missing deployed ledger fails closed.

## Run locally

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python monitor.py
```

Source-code pushes also run a live-data preview automatically, without sending Telegram messages. Preview is the default. It writes `report.json` locally, with source links, publisher timestamps, calculations and reasons; it never sends. An early preview is not the final-day verdict.

`python monitor.py --send` delivers only in the window and requires `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in the process environment. Local mode uses `local-state.json`; do not use it in parallel with GitHub. Keep this local state file to retain duplicate protection.

## Data and operation limits

- InvestorGain: IPO discovery, lot size, upper issue price, timestamped GMP, and subscription categories. Subscription is republished data, not a direct verified exchange feed.
- IPO Watch: exact-name GMP cross-check, dated GMP history, issue price and closing date. Two publishers do not necessarily mean independent underlying grey-market sources.
- Mainboard-only badge and table checks prevent treating SME categories as retail. There is no fuzzy-name matching. Add reviewed name aliases in `config.toml`; missing matches block APPLY.
- Public HTML is a best-effort source, not a contracted free API. Layouts, blocking, availability and terms can change. There is no CAPTCHA bypass, proxy service or paid data dependency. Maintain adapters or switch to a legitimately available feed if a publisher blocks requests.
- Discovery depends on InvestorGain's current report. An issue omitted from it cannot be assessed. A complete discovery outage fails the workflow; it cannot invent issuer-specific SKIP messages for unknown issues.
- Turn on GitHub's normal failed-workflow notifications and inspect failed runs. There are no extra Telegram health messages, so repeated operational errors do not spam the channel.
- Public scheduled workflows can be disabled after 60 days without repository activity. Check workflow status monthly, especially over long gaps without IPO verdict commits. Re-enable it manually when necessary.
- This system needs no AI API, subscription, server, domain, database service or payment card. Public standard Actions and normal low-volume Telegram bot messages are free under current provider policies. Future provider changes cannot be guaranteed free forever. Private repositories have usage allowances; this design targets a public repository.

## Verified references

- [GitHub Actions free public standard runners](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
- [GitHub scheduled runs, delays and inactivity](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [GitHub Contents API, revision SHA writes](https://docs.github.com/en/rest/repos/contents#create-or-update-file-contents)
- [Telegram Bot API](https://core.telegram.org/bots/api#sendmessage)
- [Telegram low-volume messaging costs and limits](https://core.telegram.org/bots/faq#my-bot-is-hitting-limits-how-do-i-avoid-this)
- [NSE e-IPO FAQs including SME category changes](https://www.nseindia.com/static/trade/e-ipo-faqs)
- [InvestorGain public GMP report](https://www.investorgain.com/report/ipo-gmp-live/331/)
- [InvestorGain public subscription report](https://www.investorgain.com/report/ipo-subscription-live/333/)
- [IPO Watch public GMP report](https://ipowatch.in/ipo-grey-market-premium-latest-ipo-gmp/)
