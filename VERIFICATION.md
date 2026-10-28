# Verification and activation status

Verified locally on 28 October 2026:

- 38 tests passed, covering strategy conditions, missing/stale/future data, price/date conflicts, year rollover, mainboard filtering, actual publisher table shapes, read-only preview, retry timing, durable reservations, send timeouts, status-write failure, SHA conflicts, restarts, and deadline expiry after reservation.
- All Python sources parsed successfully.
- GitHub accepted the workflow files; the Tests job passed all 38 tests on a standard Ubuntu runner. [Run](https://github.com/skvermayt-lang/ipo-retail-monitor/actions/runs/40650601420)
- Live HTTP fetches succeeded for InvestorGain subscription/GMP and IPO Watch index/issuer GMP history. No authentication cookies, proxies or paid API were used.
- A live read-only preview discovered the mainboard closing today and combined subscription categories with both GMP publishers. The preview was before the final delivery window and is not the day's final verdict.
- No Telegram message was sent. No credentials are included in the package.

Pending external setup:

- Code/workflows published to the public skvermayt-lang/ipo-retail-monitor repository; automatic live-data preview pending.
- Confirm broker cutoff in config.toml.
- Add Telegram bot token and chat ID as GitHub Actions secrets.
- Run the Telegram connection check, preview and a real in-window workflow.

GitHub unit-test runner execution is verified. Live-data preview on the hosted runner and real Telegram delivery are not yet verified. Free public pages can change or block hosted runners even when local fetches work. The rules have not been backtested and provide no guaranteed investment outcome.
