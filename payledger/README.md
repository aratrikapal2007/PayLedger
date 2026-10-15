# PayLedger

A mock peer-to-peer payment and expense-splitting app (Flask + SQLite + plain HTML/JS).
All users and money are fake.

> Local demo only. It deliberately contains security weaknesses for testing repair tools. Never deploy or expose it.

## Run (VS Code terminal)

```bash
pip install -r requirements.txt
python app.py            # open http://127.0.0.1:5000
python -m pytest -q      # functional tests, all should pass
```

Demo logins: `alice/alice123`, `bob/bob123`, `carol/carol123`, `dave/dave123`
(on the sign-in page you can also tap a name to fill them in).

Delete `payledger.db` to reset the data.
