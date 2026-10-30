# PY BANK — Streamlit + Neon PostgreSQL

## 🚀 Live Demo

**Try PY BANK online:** [Open PY BANK Banking App](https://banking-app-ug57zeutkwqrhra3yhudqv.streamlit.app/)

## Features

- Create an account with an account number, name, 4-digit PIN and opening balance
- Login and logout
- Check current balance
- Deposit and withdraw money
- View and download transaction history
- PINs are stored as salted PBKDF2-HMAC-SHA256 hashes, not plaintext
- Deposits/withdrawals update the balance and transaction ledger in one database transaction
- Account rows are locked during money movements to prevent concurrent balance updates from racing

## 1. Create a Neon database

1. Sign in at https://neon.tech and create a project.
2. Open the project's **Connect** panel.
3. Copy the PostgreSQL connection string. Use the pooled connection string if desired.
4. Keep the connection string private. It contains database credentials.

## 2. Set up the project locally

```bash
# Windows PowerShell
py -m venv .venv
.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

Create `.streamlit/secrets.toml` (the folder and file are not committed to Git):

```toml
DATABASE_URL = "postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require"
```

Use your actual Neon connection string. Do not add it to `app.py` or upload it to GitHub.

Alternatively, set the `DATABASE_URL` environment variable.

## 3. Run the app

```bash
streamlit run app.py
```

The app creates the `accounts` and `transactions` tables automatically on first run.

## 4. Deploy to Streamlit Community Cloud

1. Push this project to a private or public GitHub repository.
2. Create an app at https://share.streamlit.io.
3. Select the repository and `app.py`.
4. In **App settings → Secrets**, add:

```toml
DATABASE_URL = "postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require"
```

5. Deploy.

## Database design

### `accounts`
- `account_no` — primary key
- `name`
- `pin_salt`, `pin_hash`
- `balance`
- `created_at`

### `transactions`
- `transaction_id` — UUID primary key
- `account_no` — foreign key to accounts
- `transaction_type` — Opening, Deposit or Withdraw
- `amount`
- `previous_balance`
- `current_balance`
- `created_at`

## Important security note

This is an educational banking simulation, not production banking software. It has no verified identity/KYC process, password reset, rate limiting, MFA, fraud monitoring, administrative controls, or audit/compliance program. A four-digit PIN is weak for an internet-facing service. Do not use real customer information or real money. Before any real-world use, obtain a professional security review and implement stronger authentication, abuse protection, monitoring, backups, and operational controls.

The original Excel file stores PINs in plaintext. This new app does not import that file or reuse its plaintext PINs. If you need migration of existing test accounts, do it as a separate, carefully reviewed process.
