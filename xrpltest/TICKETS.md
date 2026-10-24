# XRPL attendee ticket payments

**Product:** AI-assisted planning for cultural and corporate events, with XRP
ticket checkout and payment-verified admission. Ticket payments alone fit the
hackathon's **Why Not** lane most directly. An Agentic Finance entry should
demonstrate additional agent-driven financial behavior; ordinary checkout is
not autonomous finance.

## What works

- Organizers create an event with a title, cultural/corporate category, receiving
  wallet, price in native XRP, and capacity.
- Each checkout reserves **one seat** and creates an unsigned payment request
  with the attendee's wallet, organizer address, amount, and unique destination tag.
- Attendees send the payment using their own **Testnet** wallet, then paste the
  transaction hash into the checkout page.
- The app looks up that transaction on XRPL Testnet. It checks finality, success,
  sender, receiver, tag, actual delivered XRP, and that the payment occurred
  after checkout began. It rejects partial and cross-currency payments.
- A verified payment produces one persistent admission code and an explorer
  receipt. Repeating verification returns the same ticket. A payment hash cannot
  fund another order. Organizer check-in accepts the admission code only once.

Tickets are application admission records, not NFTs or XRPL sequence `Ticket`
objects. Payment settlement is on XRPL; orders and admission records are local.
The receiver and attendee keep control of their wallets. The ticket application
does not load a seed, sign, submit payments, or request wallet secrets.

## Setup

Run all commands below from the repository root. This feature uses the
independent `xrpltest` server, not the main application's server.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r xrpltest/requirements.txt
```

Use two dedicated, funded Testnet accounts from the official
[XRP faucet](https://xrpl.org/resources/dev-tools/xrp-faucets): an organizer
receiving account and an attendee account. Testnet funds have no monetary value.
Use an organizer account under your control, not a custodial exchange deposit
address: this application assigns destination tags to individual orders.
No seed belongs in the ticket server's environment or event configuration.

Create an event, replacing the receiver placeholder with its classic address:

```bash
.venv/bin/python -m xrpltest.event_tickets init \
  --event gallery-opening --title "Gallery Opening Night" --kind cultural \
  --receiver REPLACE_WITH_ORGANIZER_TESTNET_ADDRESS \
  --price-xrp 2 --capacity 100

.venv/bin/python -m xrpltest.server \
  --port 8081
```

Open **http://127.0.0.1:8081/tickets**. For a corporate event, use
`--kind corporate` and an appropriate title. To link to an existing application
event, use its ID when configuring ticket sales. The sample dashboard's
registration counts are not synchronized with ticket orders yet.

The server binds to loopback and is a local demo, not a publicly hosted checkout.
Both the browser and CLI default to `xrpltest/event-tickets.sqlite3`. To reuse
an existing database, pass its absolute path using the CLI's `--db` option
(before the subcommand) and the server's `--tickets-db` option. Do not recreate
orders that already have a pending or confirmed payment.

## Attendee flow

1. Select an event, enter the attendee's classic Testnet wallet address, and
   reserve a ticket. Checkout reads the latest validated ledger before it
   creates the order, so this step needs network access.
2. Save the resulting page URL. Its `#order=...` reference restores the order
   after a reload; treat it as private because it can reveal the admission code.
3. In a wallet/tool that supports Testnet, send the displayed XRP amount to the
   organizer **with the displayed destination tag**, from the specified attendee
   account. The request JSON can be copied for use with the XRPL SDK. There is
   no embedded wallet connection or automatic signing in this version.
4. Paste the transaction hash and select **Verify payment & get ticket**.
   If the ledger has not validated it yet, retry verification without paying again.
5. Save the admission code and present it at the event.

For SDK-based signing, use the official
[Send XRP tutorial](https://xrpl.org/docs/tutorials/payments/send-xrp) with the
checkout's exact `Account`, `Destination`, `DestinationTag`, and `Amount`.
The wallet must autofill the fee, sequence, and expiration before signing.
Network fees are separate from the ticket price and are paid by the attendee.

## CLI and admission

```bash
# Alternative to creating an order in the browser:
.venv/bin/python -m xrpltest.event_tickets checkout \
  --event gallery-opening --buyer REPLACE_WITH_ATTENDEE_TESTNET_ADDRESS

.venv/bin/python -m xrpltest.event_tickets show ORDER_ID
.venv/bin/python -m xrpltest.event_tickets verify ORDER_ID --tx-hash TRANSACTION_HASH
.venv/bin/python -m xrpltest.event_tickets events

# Organizer-only local action after checking the attendee's ticket:
.venv/bin/python -m xrpltest.event_tickets check-in TICKET_CODE
```

`events` shows seats reserved, tickets paid, and available capacity. Reservations
include paid tickets. For example, 3 awaiting payment and 2 paid tickets reserve
5 seats. A second check-in of the same ticket is rejected.

## API

The standalone server exposes these routes using its configured database:

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/tickets/events` | Configured ticket events and availability |
| POST | `/api/tickets/orders` | JSON `event_id`, `buyer`; reserve one ticket |
| GET | `/api/tickets/orders/ORDER_ID` | Restore order and receipt by private reference |
| POST | `/api/tickets/verify` | JSON `order_id`, `tx_hash`; verify incoming payment |

The browser has no event-configuration or check-in endpoint. Those remain local
organizer CLI commands. The server rejects foreign Host/Origin headers and
requires small JSON bodies for writes.

## Current demo limits

- **Reservations persist:** unpaid orders continue to hold seats. This avoids
  selling a seat twice while payment confirmation is pending. Timeouts,
  cancellation, late-payment handling, and refund workflows are not implemented.
  Do not delete/reinitialize the database to reclaim seats for the same wallet.
- Use one persistent database for each receiving account and do not share the
  account's tag allocation with another ticketing system. The database enforces
  uniqueness within this application, not across independent deployments.
- Verification is initiated by the attendee; no background ledger watcher runs.
  A successful network payment by itself does not update the local order until
  verification is requested.
- Wrong tags, unexpected amounts, and unsupported payment types require organizer
  review; the app does not automatically refund or combine payments.
- Amounts are XRP, not USD. Fiat quotes, stablecoins, taxes, fees charged by the
  organizer, and multiple tickets in one order are outside this version.
- This is a local prototype. Public launch requires authenticated organizer
  accounts, durable hosted storage, reservation abuse controls, recovery, and
  tested wallet integration. It has not been validated with a funded live
  Testnet payment in this workspace.

## Verification and references

```bash
.venv/bin/python -m unittest discover -s xrpltest/tests -p 'test_event_tickets.py' -v
node --check xrpltest/static/tickets.js
```

The tests use unfunded SDK-generated addresses and mocked ledger responses.
They exercise the checkout API, capacity, payment matching, exact delivery,
replay protection, receipt restoration, and one-time check-in.

XRPL's [payment monitoring guidance](https://xrpl.org/docs/concepts/payment-types/robustly-monitoring-for-payments)
requires final ledger results and checking the amount actually delivered.
[Destination tags](https://xrpl.org/docs/concepts/transactions/source-and-destination-tags)
let the receiving application associate incoming funds with a specific order.
