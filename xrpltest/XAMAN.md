# Connect Xaman and pay on Testnet

The checkout now supports **Connect Xaman** and **Pay with Xaman**. Approvals
happen in your Xaman app; the website receives the account and payment hash
without asking for your wallet seed. You can keep the manual checkout flow too.

## 1. Prepare Xaman

In Xaman, enable **Developer mode** under **Settings → Advanced**, then select
**Testnet**. Import a dedicated funded Testnet account from the
[official XRPL faucet](https://xrpl.org/resources/dev-tools/xrp-faucets) if you
do not already have one. Keep the attendee account different from the organizer's
receiving account. Use only Testnet accounts for this demo.

See the [XRPL Commons Xaman setup guide](https://docs.xrpl-commons.org/tools/xaman-setup)
for developer-mode and Testnet account instructions.

## 2. Register the developer app

Open the [Xaman Developer Console](https://apps.xumm.dev), sign in, and register
an application for your checkout. Obtain its **API key** and **API secret**.
These identify the application; they are not wallet seeds.

Create or edit **`xrpltest/.env`** locally:

```dotenv
XAMAN_API_KEY=your-developer-app-api-key
XAMAN_API_SECRET=your-developer-app-api-secret
```

Do not replace an existing `.env` file if it contains other settings. Do not
commit the credentials or paste them into chat. The folder's `.gitignore`
already excludes this file. Environment variables override the local file.

This implementation uses server-side payload requests and browser WebSocket
notifications. It needs no public webhook, OAuth redirect, or tunnel. Your
computer needs outgoing HTTPS access to Xaman and XRPL Testnet, and your browser
needs access to the Xaman WebSocket and QR image endpoints.

## 3. Start the checkout

From the repository root:

```bash
.venv/bin/python -m pip install -r xrpltest/requirements.txt
.venv/bin/python -m xrpltest.server
```

If you have not configured an event and organizer receiving address yet, follow
[the ticket setup guide](TICKETS.md). Open **http://127.0.0.1:8081/tickets** on
your computer. The phone does not need to open your computer's localhost URL:
it scans Xaman's signing request while the checkout remains open on your computer.

## 4. Test with your phone

1. Click **Connect Xaman** on the website.
2. Scan the QR code using Xaman and approve the sign-in. It is an off-ledger
   identity request, not a payment. The attendee address fills automatically.
3. Choose the event and select **Reserve one ticket**.
4. Click **Pay with Xaman · Testnet**. Scan the payment QR in Xaman. Confirm the
   network, organizer address, exact price, and destination tag before approving.
5. Keep the browser tab open. It waits for wallet approval, then verifies the
   actual transaction on XRPL Testnet. **Payment confirmed** and the admission
   code appear after verification succeeds.

An **Open in Xaman** link is also provided. On your desktop, scanning the QR on
your phone is the simplest local setup. Mobile-only use requires the checkout
itself to be reachable on the phone; this server continues to bind to loopback.

If live updates disconnect, select **Check wallet response** after approving.
The transaction hash can still be verified manually using the existing form.
No signing keys are needed in the ticket server's environment.

## Behavior and recovery

- Failed sign-in creation shows a specific error and unlocks **Connect Xaman**
  for retry. Reloading a previously stuck sign-in also clears its browser lock.
  The server verifies HTTPS with certifi's CA bundle and identifies its client
  to Xaman's API. If dependencies changed, rerun
  `uv pip install -r xrpltest/requirements.txt` and restart the server.

- Both sign-in and payment requests specify `force_network: TESTNET`. A payment
  response from any other network is rejected. Final verification always uses
  the configured XRPL Testnet endpoint.
- Payment details come from the saved order, not browser-provided amounts.
  The connected account must match the order's attendee account.
- A wallet approval is not a paid ticket. The server fetches the payload using
  its credentials, checks the app and request identity, and then runs the
  existing exact-delivery and duplicate-payment checks against the ledger.
- Active requests are stored in the ticket database. Repeated clicks on Pay
  reuse the existing request. The browser remembers request references within
  the tab's session storage, and the order URL restores the reservation.
- Verified wallet connections are valid for creating payments for one hour.
  If prompted, connect again. Connection does not authorize automatic spending.
- A rejected request can be replaced. An expired payment request is not
  automatically replaced: Xaman can still allow signing if it was opened before
  expiration. Check its result before attempting another payment.
- If creation times out, the request remains uncertain and is not automatically
  recreated. Review Xaman before sending manually. If the provider never returned
  a payload ID, this prototype requires operator investigation.
- After approval, the browser retries ledger verification up to 20 times at
  five-second intervals. These checks use the saved hash without repeatedly
  polling Xaman. **Check wallet response** remains available afterward.

Unpaid reservations still persist. Refunds, public hosting, and production
authentication remain outside this local prototype. Tests mock Xaman and the
ledger; an actual phone-approved Testnet payment still needs your credentials
and a funded account.

## Developer references

- [Xaman payload creation](https://xumm.readme.io/reference/post-payload)
- [Payload status and late expiration](https://xumm.readme.io/reference/get-payload)
- [Off-ledger SignIn](https://docs.xaman.dev/concepts/special-transaction-types/signin)
- [WebSocket notifications](https://docs.xaman.dev/concepts/payloads-sign-requests/status-updates/websocket)
- [Network selection](https://docs.xaman.dev/concepts/payloads-sign-requests/networks)
