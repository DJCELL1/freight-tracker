# Freight Tracker

Drop in a despatch manifest PDF and see what has left Vic, and when it lands.

Every order on the manifest gets an ETA of **despatch date + 5 days**, and the
dashboard counts down to it: on the road, due today, overdue, delivered.

## Running it

```bash
pip install -r requirements.txt
streamlit run app.py
```

Scanned manifests need two system packages as well, for rasterising and reading
the pages:

```bash
sudo apt-get install -y poppler-utils tesseract-ocr   # Debian/Ubuntu
brew install poppler tesseract                        # macOS
```

Without them the app still runs and still reads manifests that have a text
layer; a scan will report that OCR is unavailable rather than failing quietly.

## Using it

**Add manifest** — drop in the pack: the manifest page plus its delivery
dockets. The parse is shown for review before anything is saved, because a
scanned pack is read by OCR and OCR is not perfect. Correct anything that looks
wrong in the form and the table, then save. Re-uploading the same manifest
refreshes what the PDF says and leaves your delivery marks and notes alone.

**Dashboard** — every order, newest despatch first, with its ETA and a
countdown. Expand an order for the item lines off its docket, to mark it
delivered when it lands, or to leave a note.

**Settings** — the transit allowance (5 days by default; switch to working days
if that suits the lane better), and the origin used when a scan is too degraded
to read the sender's address.

Everything is stored in a SQLite file, `freight_tracker.db`, created next to
the app on first run. It is gitignored — it holds your consignments, not code.
Set `FREIGHT_DB_PATH` to put it somewhere else, which is what the deployment
below does.

## Deploying it on Railway

The repo carries a `Dockerfile` and a `railway.toml`, so Railway builds it
without further configuration — but **add the volume before you rely on it**.

1. **New Project → Deploy from GitHub repo**, and pick this repository. Railway
   reads `railway.toml`, builds the Dockerfile, and starts the app on its own
   `$PORT`.
2. **Add a volume.** In the service, **Settings → Volumes → Add volume**, mount
   path `/data`. This is the step that matters: without it the container's
   filesystem is rebuilt on every deploy and every shipment you have logged
   disappears the next time you push a change. The image already points
   `FREIGHT_DB_PATH` at `/data/freight_tracker.db`.
3. **Generate a domain** under **Settings → Networking** to get a URL.

The service is pinned to one instance on purpose. The database is a single
SQLite file on one volume, and a second replica writing to it concurrently
would corrupt it. Scaling past one instance means moving to Postgres first.

Anyone with the URL can reach the app — Streamlit has no login of its own. Put
it behind Railway's private networking, or in front of an authenticating proxy,
if that matters for your freight data.

## How a manifest is read

A pack holds one manifest page and a delivery docket per order:

- the **manifest** says when the load left and which orders were on it,
- each **docket** says what was in that order, and carries its SO and PO.

The despatch date on the manifest is what the ETA counts from.

Scans are the normal case here, so the parsing is built to survive them:

- **Text layer first, OCR second.** A born-digital PDF is read exactly; only a
  page with no text is rasterised and OCR'd, at 400 DPI with the contrast
  stretched — below that the grey-on-grey manifest number is unreadable.
- **The dockets spell-check the manifest.** Every order number appears twice: in
  the manifest's cramped table and again on its own docket in large clean type.
  A manifest number that is a character or two off a docket number is corrected
  to it. Where it is equally close to two, it is left alone for a human to look
  at rather than guessed at.
- **Rows are found by content, not by row number.** That number is a single
  grey character and scans as `{` or `|` about as often as a digit.
- **Fields are left empty rather than filled in wrong.** An unreadable sender
  footer produces no origin, and the upload screen falls back to the configured
  default. The review step is where anything doubtful gets fixed.

## Layout

| File | What it does |
|---|---|
| `app.py` | Streamlit entry point and navigation |
| `ocr.py` | PDF to page text — text layer, else OCR |
| `normalise.py` | Repairs OCR damage in reference numbers and dates |
| `parser.py` | Manifest and docket pages to shipment records |
| `eta.py` | Despatch date plus the transit allowance, and status |
| `store.py` | SQLite persistence |
| `views/` | Dashboard, Add manifest, Settings |

## Tests

```bash
python -m pytest tests
```

The parser tests run against text carrying the damage real scans produce —
`SO-` reading as `S$0-`, `11:59` as `41:59`, a quantity of `5` as `S` — so the
repairs stay honest. They use invented order numbers and company names, not
customer paperwork.
