# XRPL event payments MVP

The existing Python operator dashboard now includes **Event payments**. Research,
event planning and USD sample budgets stay off-chain; ticket receipts and approved
vendor payments use **XRPL Testnet**. Test XRP has no monetary value. This is a
local demo, not a public payment processor or production custody service.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # only if you do not already have a .env
python -m operator_app.payments --setup
```

Set `XRPL_ENABLED=true` in `.env`, then:

```bash
python -m operator_app.server --port 8080
```

Open http://127.0.0.1:8080 and scroll to **Event payments**. Setup creates three
faucet-funded wallets: event treasury, demo attendee and approved vendor. Only
public addresses are printed. Seeds are stored in `.xrpl-wallets.json` with mode
0600 and excluded from Git. Never import a Mainnet seed. The endpoint is fixed to
`https://s.altnet.rippletest.net:51234`; there is no Mainnet switch.

Setup intentionally refuses to overwrite wallet files. If a faucet/setup request
fails, preserve the partial file and retry with a new file name using
`--wallet-file .xrpl-wallets-retry.json`; set `XRPL_WALLET_FILE` accordingly. A new
wallet requires a new `XRPL_DB_PATH`. Testnet resets also require a fresh demo
session; historical local receipts do not prove funds survived a network reset.

| Variable | Default | Purpose |
| --- | --- | --- |
| `XRPL_ENABLED` | `false` | Explicitly enable Testnet payments |
| `XRPL_WALLET_FILE` | `.xrpl-wallets.json` | Private test wallet seed file |
| `XRPL_DB_PATH` | `.xrpl-payments.sqlite3` | Persistent invoices and transaction intents |
| `XRPL_EVENT_BUDGET_XRP` | `100` | Maximum approved expenses per event, in test XRP |

Keep custom wallet and database paths out of Git and outside the static directory.
The default file names are ignored. Do not expose the development server publicly;
it has no user authentication. It binds to loopback, checks mutation Host/Origin,
and requires JSON plus a custom request header.

## Three-minute demonstration

1. Select an event in the payment panel. Create an **approved vendor expense**
   for **10 test XRP**, with a **20 test XRP** ticket-sales threshold. Check the
   approval box. The destination is the configured vendor wallet.
2. Click **Check policy & pay vendor**. The service holds the payment because
   verified ticket receipts have not met the threshold. Faucet funds do not count.
3. Create a **20 test XRP ticket** invoice. Click **Pay with demo attendee**.
   This signs a genuine Testnet transaction on the server using the disposable
   attendee wallet. It is a simulated purchase, not evidence of customer demand.
4. Open the receipt's Testnet explorer link. The invoice becomes paid only after
   the server fetches and verifies validated transaction evidence.
5. Click **Check policy & pay vendor** again. The receipt unlocks the approved
   payment. Open its transaction and inspect the updated event accounting.
6. Refresh/restart the app. Invoices and receipts persist. Repeated payment
   requests reconcile the same transaction rather than paying again.

External test wallets can also pay ticket invoices: send the exact XRP amount to
the displayed destination with the displayed 256-bit `InvoiceID`, then click
**Reconcile receipt** and paste the hash. One transaction settles one invoice;
partial payments, aggregate/overpayments and issued tokens are not supported.
No seed or signed blob is sent to the browser.

## Application and agent API

All mutation requests require `Content-Type: application/json` and
`X-Operator-Request: 1`. The local operator approves expense creation; an agent
can invoke the pay endpoint for already-approved invoices. Do not give an
untrusted model unrestricted access to the approval endpoint or wallet file.

| Method | Endpoint | Body / result |
| --- | --- | --- |
| GET | `/api/xrpl` | Network, enabled state, public addresses, invoices, per-event totals |
| POST | `/api/xrpl/invoices` | `event_id`, `kind` (`ticket` / `expense`), `label`, `amount_xrp` string, optional `min_sales_xrp` string; expenses require `approved: true` |
| POST | `/api/xrpl/pay` | `invoice_id`; submit once, or reconcile an existing pending transaction |
| POST | `/api/xrpl/reconcile` | `invoice_id`, `tx_hash`; fetch and validate Testnet evidence |

Example ticket invoice for an existing event:

```bash
curl http://127.0.0.1:8080/api/xrpl/invoices \
  -H 'Content-Type: application/json' -H 'X-Operator-Request: 1' \
  -d '{"event_id":"e1","kind":"ticket","label":"Demo ticket","amount_xrp":"20"}'
```

Use the returned `id` as `invoice_id` when calling `/api/xrpl/pay`.

## Verification and failure behavior

- Money is integer drops; decimal strings have at most six fractional digits.
- Only a validated `tesSUCCESS` Payment with matching invoice, destination and
  actual `delivered_amount` counts. Partial-payment flags and issued currencies
  are rejected. Event-wallet self-transfers cannot count as ticket receipts.
- Expenses require explicit approval, the configured per-event cap, enough
  verified receipts from that event, and the invoice's sales threshold. The MVP
  uses one predefined vendor wallet rather than arbitrary agent-selected payees.
- SQLite persists the signed transaction and hash **before** submission. A
  pending payment blocks new submissions, including from another server process
  sharing the database, until its outcome is reconciled. Repeated clicks cannot
  create a second signed payment for the invoice.
- On a timeout, refresh and reconcile the existing hash. A validated ledger
  failure is recorded as `failed`. A transaction that never lands remains
  `pending` for manual investigation; this MVP does not automatically replace
  expired transactions or clear uncertain payments. Do not delete the record
  and retry while the original outcome is unknown.
- Invoice totals exclude faucet funding and network fees. “Cash surplus” is
  collected receipts minus paid invoice amounts; it is not wallet balance or
  proven business profit. “After commitments” additionally includes unpaid
  approved expenses. The faucet bankroll covers fees and account reserves.

## Scope

Implemented: Testnet wallet setup, ticket and vendor invoices, local approval,
revenue-gated payments, external receipt reconciliation, persistent accounting,
explorer links, and integration with the existing dashboard/events.

Not implemented: event creation or a Luma integration, autonomous discovery and
booking of hosts, escrow, refunds, fiat/stablecoin settlement, public checkout,
production authentication/custody, or automated payment execution by the Daytona
agent runtime. The new API is the integration point for that runtime. Existing
research/communications behavior is unchanged.

## Tests and reference documentation

```bash
python -m unittest discover -s tests -v
node --check operator_app/static/payments.js
```

Payment tests cover policy holds, event separation, budget exhaustion, exact
amount validation, invalid receipts, external payment reconciliation, restart and
concurrent retry safety, HTTP origin rejection, and real SDK signing/serialization
without network. Existing SurrealDB integration tests require `SURREAL_TEST_BINARY`.

- [XRPL Python quickstart](https://xrpl.org/docs/tutorials/get-started/get-started-python)
- [Send XRP](https://xrpl.org/docs/tutorials/payments/send-xrp)
- [Payment / InvoiceID](https://xrpl.org/docs/references/protocol/transactions/types/payment)
- [Delivered amounts and partial payments](https://xrpl.org/docs/concepts/payment-types/partial-payments)

### Live Testnet validation (2026-10-24)

A live check held a 1 test-XRP expense until a 2 test-XRP ticket receipt validated,
then paid the vendor and verified repeat calls returned the same transaction.

- [2 test-XRP ticket receipt](https://testnet.xrpl.org/transactions/B333E4841F0DA2F2E40BF12EC49D2B384678D54209EAC3CF96A245AA2070706D)
- [1 test-XRP vendor payment](https://testnet.xrpl.org/transactions/495E9E590B18904A8A1062FEC958C9F1F9876EA7BD88FB24D670EF4BD9904D5C)

These are valueless test transactions, not real event revenue. Explorer records
may disappear on a Testnet reset. No wallet seeds or local database are committed.
