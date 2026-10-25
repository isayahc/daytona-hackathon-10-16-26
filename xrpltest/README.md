# XRPL Testnet event payments

All XRPL code, checkout assets, tests, dependencies, and documentation live in
this folder. It runs independently of the main event-planning application and
does not import or change `operator_app`. The folder is named `xrpltest` so it
does not shadow the installed SDK's `xrpl` package.

## Run the ticket checkout

Run these commands from the **repository root**, using Python 3.10 or newer:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r xrpltest/requirements.txt

# Replace the receiver with your dedicated organizer Testnet address.
.venv/bin/python -m xrpltest.event_tickets init \
  --event gallery-opening --title "Gallery Opening Night" --kind cultural \
  --receiver REPLACE_WITH_ORGANIZER_TESTNET_ADDRESS \
  --price-xrp 2 --capacity 100

.venv/bin/python -m xrpltest.server
```

Open **http://127.0.0.1:8081/tickets**. The main application can continue using
port 8080. Starting with no configured events shows an empty checkout page.

Attendees can **connect Xaman**, reserve a seat, and approve payment in their
wallet; the server verifies payment before issuing an admission code. Follow
[the Xaman setup guide](XAMAN.md) to add your developer app credentials. Manual
wallet-address entry and transaction-hash verification remain available.
The checkout never asks for wallet secrets. Read [the ticket guide](TICKETS.md)
for account setup, payment verification, admission, and the prototype's limits.

The earlier vendor payment CLI is also preserved here; see [the vendor guide](XRPL.md).
That optional CLI uses `XRPL_TESTNET_SEED`. The Xaman integration uses
`XAMAN_API_KEY` and `XAMAN_API_SECRET`; all may be configured in `xrpltest/.env`.

## Files

| Path | Purpose |
| --- | --- |
| `event_tickets.py` | Ticket events, reservations, payment verification, check-in CLI |
| `server.py` | Standalone loopback HTTP server and checkout API |
| `xaman.py` | Server-side Xaman sign-in, payment requests, and status verification |
| `static/` | Attendee checkout HTML, CSS, and JavaScript |
| `event_finance.py` | Optional vendor payment CLI and shared amount/address validation |
| `tests/` | Offline finance and ticket verification tests |
| `requirements.txt` | XRPL-specific dependencies |
| `.env.example` | Xaman developer credentials and optional vendor signer template |

## Data and existing orders

Defaults are `xrpltest/event-tickets.sqlite3` and
`xrpltest/event-finance.sqlite3`, regardless of the working directory. These
databases, local vendor files, and `.env` are ignored by Git. Existing event,
order, and payment tables remain compatible with the previous implementation;
Xaman adds its request-tracking table on first use.

If you already have a database outside this folder, explicitly point both the
CLI and server at it rather than creating replacement orders:

```bash
.venv/bin/python -m xrpltest.event_tickets --db /absolute/path/event-tickets.sqlite3 events
.venv/bin/python -m xrpltest.server --tickets-db /absolute/path/event-tickets.sqlite3
```

Existing data and secrets are not moved automatically. To carry this feature
onto another branch or checkout, bring the entire `xrpltest/` folder and install
its requirements. No main-app source changes are needed. Linking the checkout
or synchronizing ticket counts with the main app is a separate integration.

## Verify

```bash
.venv/bin/python -m unittest discover -s xrpltest/tests -v
node --check xrpltest/static/tickets.js
```

Tests mock ledger access and do not send payments. A funded Testnet payment has
not been demonstrated in this workspace. Unpaid reservations persist; this is
a local prototype, not a publicly hosted production checkout.
