# XRPL vendor payment prototype

The primary integration is now **[attendee ticket payments](TICKETS.md)**.
This document describes the separate vendor-payment prototype.

**Hackathon track: Agentic Finance.** The product direction is an event planning
assistant that can research suppliers, prepare vendor payments, and reconcile
receipts against an event budget. Cultural producers can pay venues, artists,
and caterers; corporate teams can pay suppliers for launches, dinners, and offsites.

The first implementation is a **local, organizer-approved Testnet payment CLI**
in `event_finance.py`. It uses native XRP payments through `xrpl-py`. It is not
an autonomous treasury, lending product, escrow implementation, or production
payment service. Testnet XRP has no monetary value.

## Implemented flow

1. The organizer defines an event ID, cultural/corporate type, sender account,
   XRP budget, per-payment limit, and approved vendor addresses/tags.
2. A payment proposal identifies the event, vendor, invoice, and explicit XRP
   amount. Proposal creation does not load the signing seed or send anything.
3. The organizer reviews the sender, recipient, destination tag, amount in
   drops, and maximum fee, then types `PAY <payment-id>`.
4. The app reserves budget atomically, autofills an expiring transaction, checks
   the fee, signs locally, and saves the signed transaction and its hash before
   submitting to the fixed XRPL Testnet endpoint.
5. A ledger lookup must confirm the matching transaction, successful final
   result, and exact delivered amount before the app reports `paid`.

Research results are suggestions, not approved payment recipients or invoices.
The organizer must establish those details separately. The existing research
workers do not automatically call this CLI, and the workspace UI is still a
read-only sample. Linking the research results, payment proposals, and receipts
in the UI is the next integration step.

## Setup

Run all commands below from the repository root. The default database is now
`xrpltest/event-finance.sqlite3`; use `--db /absolute/path/to/existing.sqlite3`
before the subcommand to reuse an existing vendor payment database.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r xrpltest/requirements.txt
```

Get two dedicated, funded Testnet accounts using the official
[XRP Testnet faucet](https://xrpl.org/resources/dev-tools/xrp-faucets): one
organizer and one demonstration vendor. Keep the organizer's seed locally in
`xrpltest/.env` as `XRPL_TESTNET_SEED`. Do not put seeds in event briefs, vendor JSON,
agent prompts, or source control. The CLI only loads `xrpltest/.env` for `pay`.

Create `xrpltest/vendors.local.json`, replacing the placeholder with the vendor's
classic Testnet address:

```json
{
  "venue": {
    "address": "REPLACE_WITH_VENDOR_TESTNET_CLASSIC_ADDRESS"
  }
}
```

If the recipient requires a destination tag, add `"destination_tag": 42`
using its actual tag. Omit it for a dedicated account that does not require one.
The vendor file and default SQLite database are ignored by Git.

## Demo walkthrough

Replace the sender placeholder below with the organizer's classic address.
These amounts are demonstration XRP amounts, not USD conversions. Use the same
event ID as the application event when connecting the workflows.

```bash
.venv/bin/python -m xrpltest.event_finance init \
  --event launch-demo --kind corporate \
  --sender REPLACE_WITH_ORGANIZER_TESTNET_CLASSIC_ADDRESS \
  --budget-xrp 20 --payment-limit-xrp 5 \
  --vendors-file xrpltest/vendors.local.json

.venv/bin/python -m xrpltest.event_finance propose \
  --event launch-demo --vendor venue \
  --invoice venue-deposit-001 --amount-xrp 2
```

Copy the returned payment ID into the following commands:

```bash
.venv/bin/python -m xrpltest.event_finance show PAYMENT_ID
.venv/bin/python -m xrpltest.event_finance pay PAYMENT_ID
.venv/bin/python -m xrpltest.event_finance reconcile PAYMENT_ID
.venv/bin/python -m xrpltest.event_finance budget --event launch-demo
```

The `pay` command asks for interactive confirmation. A saved transaction hash
also produces a Testnet explorer link. An explorer link alone is not proof of
success: inspect `status`, `result_code`, and `ledger_index`.

For a cultural demo, use `--kind cultural` and an event such as an exhibition
opening, with approved vendors for the gallery and catering. The same budget
and approval workflow applies.

## Payment and budget semantics

- `1 XRP = 1,000,000 drops`. All stored monetary values (`amount`, `reserved`,
  `budget`, `payment_limit`) are integer drops. Budget output makes the units
  explicit with `budget_drops` and `available_drops`.
- The per-payment limit covers principal; the event budget covers principal
  and fees. Each attempted payment reserves its amount plus a fee allowance
  of 1,000 drops (0.001 XRP). A higher network fee prevents signing.
- Drafts do not reserve budget. Budget is checked again inside a database
  transaction immediately before signing.
- A validated successful payment consumes its amount plus the actual fee.
  A validated failed transaction consumes only its actual fee.
- A submission timeout remains `needs_review`; a nonfinal lookup stays pending.
  Its budget stays reserved. Run `reconcile` against the original hash. The app
  does not create a replacement payment or retry submission automatically.
- An invoice reference is unique within its event. Pending payments block
  additional submissions from that sender across events in the same database,
  avoiding concurrent sequence allocation inside this application.
- Not-found responses are inconclusive. This version does not automatically
  release funds for expired/unfound transactions, because that requires a
  complete ledger-history check. Interrupted preparation without a saved hash
  also requires operator inspection. Do not delete records to retry blindly.

The budget is a local spending policy, not an on-chain vault or segregated
balance. It does not account for other applications spending from the same
wallet, and a database budget does not guarantee sufficient spendable funds
after XRPL account reserves. Use one dedicated demo wallet and one database.

## Boundaries and next steps

The local CLI assumes one trusted operator. Its confirmation and SQLite policy
are application controls, not an authorization boundary against a process with
the same filesystem access. Before exposing payments to autonomous agents or
multiple users, move policy administration and signing behind authenticated,
separate services. Keep agent tools limited to proposing and reading payments.

The first workflow requires approval for every payment. A later Agentic Finance
demo can add policy-limited automatic execution for preapproved recipients and
amounts, after the separate signer and authorization boundary exist.

The existing event model has USD budget fields. Do not copy them into XRP
amounts or sum currencies without an explicit quote. This version keeps XRP
finance separate and links it by event ID. Stablecoin support, sponsorship
receipts, lending, and escrow are follow-on work. Attendee ticket payments are
provided separately by [the ticket checkout](TICKETS.md).

## Verification

```bash
.venv/bin/python -m unittest discover -s xrpltest/tests -p 'test_event_finance.py' -v
```

Tests use generated unfunded wallets and mocked network responses. They cover
exact amounts, approved vendors/tags, invoice duplication, budget limits,
confirmation cancellation, fee caps, signing, durable transaction hashes,
uncertain submission, ledger reconciliation, and duplicate-send prevention.
They do not establish that a funded Testnet payment has been demonstrated.

## Official references

- [Send XRP](https://xrpl.org/docs/tutorials/payments/send-xrp): native payment workflow.
- [Python SDK transaction methods](https://xrpl-py.readthedocs.io/en/stable/source/xrpl.transaction.html): local signing and submission interfaces.
- [Reliable transaction submission](https://xrpl.org/docs/concepts/transactions/reliable-transaction-submission): use final ledger evidence and retain transaction identity when outcomes are uncertain.
- [Escrow](https://xrpl.org/docs/concepts/payment-types/escrow): a possible later deposit feature; timing and cryptographic conditions do not independently verify real-world service delivery.
- [Known amendments](https://xrpl.org/resources/known-amendments): check network support before building around lending or vault features. They are not dependencies of this payment MVP.
