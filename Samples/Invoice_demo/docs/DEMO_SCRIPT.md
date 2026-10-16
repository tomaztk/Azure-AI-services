# Stage script (about 20 minutes)

**Screens:** laptop with the presenter screen (`/presenter?key=…`) on the projector, VS Code on a second
virtual desktop, the Foundry portal in a browser tab. Phone mirrored if you can.

**Handouts:** a printed stack of `samples/all_invoices_handout.pdf` (mostly pages 1 and 5, the clean ones,
plus a few of pages 2–4). Put the QR code (`samples/audience_qr.png`) on your slide.

## Checklist

| When | Do |
|---|---|
| Day before | `python scripts/setup_database.py --reseed` · `python scripts/generate_sample_invoices.py` · print handouts · load test: `python scripts/send_invoice.py samples/01_clean_brennerwerk.jpg --source audience --repeat 60 --concurrency 20` |
| Event morning | Scale App Service to P1v3 (`azd env set APP_SERVICE_SKU P1v3 && azd provision`) |
| 30 min before | `python scripts/cleanup.py --live --yes` · open all tabs · ask the agent one warm-up question (also wakes the serverless database) · hotspot ready |
| Backup | A screen recording of the full flow |

## Flow

### 1. Opening (2 min)
QR code on the slide. "Open this page and take one invoice from the stack."
Problem: invoices are typed in by hand, checked against orders by hand, and the numbers behind them
reach management weeks later.

### 2. Invoices on stage (5 min)
Drop `01_clean_brennerwerk.pdf` onto the presenter screen (*Drop a stage invoice here*): auto-approved in ~15 s.

Drop `02_price_above_contract_voltaris.pdf`: sent to a person, "Price above contract: 349.44 vs 312.00 (+12%)".
Approve it on stage.

Drop `04_more_than_received_tauern.pdf`: a crooked scan, still read correctly, and sent to a person because
6 motors are billed but only 4 were received.

### 3. Audience scans while you show the code (6 min)
"Now you." Counters start moving. Walk through three places in VS Code:

1. [`src/app/pipeline.py`](../src/app/pipeline.py) → `process()`: the whole intake in ~30 lines.
2. [`src/app/content_understanding.py`](../src/app/content_understanding.py) → `analyze()`: one REST call, keyless, `prebuilt-invoice`.
3. [`src/app/rules.py`](../src/app/rules.py) → `decide()`: every failed check goes to a person, with the reason.

Approve one or two audience invoices from the review queue (**View** shows the photo).

### 4. Ask the data (5 min)
On the phone (or the Foundry playground), ask the agent:

1. *How many invoices did the audience scan, and how many needed a person?*
2. *Why were invoices sent to a person?*
3. *Which suppliers invoice above contract price, and how much did we overpay?*
4. *Why did gross margin on the 500Wh battery pack drop?* → purchase cost per unit rose; Voltaris has
   invoiced 6–14 % above contract for three months, and nobody caught it in the old manual process.

Show [`src/app/data_tools.py`](../src/app/data_tools.py): the agent chooses a tool, the app runs fixed SQL.
Read two audience questions from the presenter screen.

### 5. Close (2 min)
Paper → Content Understanding → rules → Azure SQL → an agent that answers from the same data, minutes later.
Second QR code: your GitHub repo, `azd up` to try it.

## If something breaks

| Problem | Fallback |
|---|---|
| Venue Wi-Fi blocks the site | Hotspot; or `send_invoice.py` from the laptop and show the presenter screen |
| Content Understanding slow | Keep talking; the phone shows each stage. Worst case, play the recording |
| Agent slow on the first question | The database was paused; it's back within a minute |
