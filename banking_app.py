import os
import hashlib
import hmac
import secrets
import uuid
from decimal import Decimal, InvalidOperation
from datetime import datetime

import psycopg
import pandas as pd
import streamlit as st


# ---------------------------------------------------------
# PAGE CONFIGURATION
# ---------------------------------------------------------
st.set_page_config(
    page_title="PY BANK",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------
# DATABASE CONFIGURATION
# ---------------------------------------------------------
def get_database_url():
    """Read the Neon connection string from Streamlit secrets or environment."""
    try:
        value = st.secrets.get("DATABASE_URL", "")
    except Exception:
        value = ""

    return value or os.getenv("DATABASE_URL", "")


DATABASE_URL = get_database_url()


def get_connection():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is missing. Add it to .streamlit/secrets.toml "
            "or set the DATABASE_URL environment variable."
        )
    return psycopg.connect(DATABASE_URL, connect_timeout=10)


def initialize_database():
    """Create the tables if they do not already exist."""
    schema = """
    CREATE TABLE IF NOT EXISTS accounts (
        account_no TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        pin_salt TEXT NOT NULL,
        pin_hash TEXT NOT NULL,
        balance NUMERIC(14, 2) NOT NULL DEFAULT 0 CHECK (balance >= 0),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS transactions (
        transaction_id UUID PRIMARY KEY,
        account_no TEXT NOT NULL REFERENCES accounts(account_no),
        transaction_type TEXT NOT NULL
            CHECK (transaction_type IN ('Opening', 'Deposit', 'Withdraw')),
        amount NUMERIC(14, 2) NOT NULL CHECK (amount >= 0),
        previous_balance NUMERIC(14, 2) NOT NULL,
        current_balance NUMERIC(14, 2) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_transactions_account_date
        ON transactions(account_no, created_at DESC);
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(schema)


# ---------------------------------------------------------
# SECURITY AND VALIDATION
# ---------------------------------------------------------
def hash_pin(pin: str, salt: bytes | None = None):
    salt = salt or secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256", pin.encode("utf-8"), salt, 300_000
    )
    return salt.hex(), derived.hex()


def verify_pin(pin: str, salt_hex: str, expected_hash: str) -> bool:
    _, actual_hash = hash_pin(pin, bytes.fromhex(salt_hex))
    return hmac.compare_digest(actual_hash, expected_hash)


def parse_amount(value) -> Decimal:
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ValueError("Enter a valid amount.")
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Amount must be greater than ₹0.")
    if amount > Decimal("999999999999.99"):
        raise ValueError("Amount is too large.")
    return amount


def money(value):
    return f"₹{Decimal(value):,.2f}"


# ---------------------------------------------------------
# BANKING OPERATIONS
# ---------------------------------------------------------
def create_account(name: str, account_no: str, pin: str, opening_balance: Decimal):
    salt, pin_digest = hash_pin(pin)
    transaction_id = uuid.uuid4()

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO accounts (account_no, name, pin_salt, pin_hash, balance)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (account_no, name.strip(), salt, pin_digest, opening_balance),
            )
            cur.execute(
                """
                INSERT INTO transactions
                    (transaction_id, account_no, transaction_type, amount,
                     previous_balance, current_balance)
                VALUES (%s, %s, 'Opening', %s, 0, %s)
                """,
                (transaction_id, account_no, opening_balance, opening_balance),
            )


def authenticate(account_no: str, pin: str):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT name, pin_salt, pin_hash
                FROM accounts
                WHERE account_no = %s
                """,
                (account_no,),
            )
            row = cur.fetchone()

    if row and verify_pin(pin, row[1], row[2]):
        return row[0]
    return None


def get_account(account_no: str):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT account_no, name, balance, created_at FROM accounts WHERE account_no = %s",
                (account_no,),
            )
            return cur.fetchone()


def move_money(account_no: str, amount: Decimal, transaction_type: str):
    """Lock the account row and update balance + ledger atomically."""
    if transaction_type not in ("Deposit", "Withdraw"):
        raise ValueError("Invalid transaction type.")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT balance FROM accounts WHERE account_no = %s FOR UPDATE",
                (account_no,),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError("Account was not found.")

            previous_balance = Decimal(row[0])
            if transaction_type == "Withdraw" and amount > previous_balance:
                raise ValueError("Insufficient balance.")

            if transaction_type == "Deposit":
                current_balance = previous_balance + amount
            else:
                current_balance = previous_balance - amount

            cur.execute(
                "UPDATE accounts SET balance = %s WHERE account_no = %s",
                (current_balance, account_no),
            )
            cur.execute(
                """
                INSERT INTO transactions
                    (transaction_id, account_no, transaction_type, amount,
                     previous_balance, current_balance)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    uuid.uuid4(),
                    account_no,
                    transaction_type,
                    amount,
                    previous_balance,
                    current_balance,
                ),
            )
    return current_balance


def get_transactions(account_no: str):
    with get_connection() as conn:
        return pd.read_sql_query(
            """
            SELECT
                transaction_id::text AS "Transaction ID",
                transaction_type AS "Type",
                amount AS "Amount",
                previous_balance AS "Previous Balance",
                current_balance AS "Current Balance",
                created_at AS "Date & Time"
            FROM transactions
            WHERE account_no = %s
            ORDER BY created_at DESC
            """,
            conn,
            params=(account_no,),
        )


# ---------------------------------------------------------
# SESSION STATE
# ---------------------------------------------------------
if "account_no" not in st.session_state:
    st.session_state.account_no = None
if "user_name" not in st.session_state:
    st.session_state.user_name = None


# ---------------------------------------------------------
# UI
# ---------------------------------------------------------
st.markdown(
    """
    <style>
    .main-title {font-size: 2.35rem; font-weight: 800; letter-spacing: -1px;}
    .subtle {color: #8b93a7;}
    div[data-testid="stMetric"] {
        background: linear-gradient(135deg, rgba(42, 55, 90, .28), rgba(20, 130, 110, .12));
        border: 1px solid rgba(130, 150, 190, .22);
        padding: 18px; border-radius: 14px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="main-title">🏦 PY BANK</div>', unsafe_allow_html=True)
st.caption("A simple digital banking demo Created by Harshad & Dnyanesh using Streamlit and Neon PostgreSQL.")

if not DATABASE_URL:
    st.error("Neon database is not configured yet.")
    st.info(
        "Create a Neon project, copy its PostgreSQL connection string, "
        "then add DATABASE_URL to .streamlit/secrets.toml. See README.md."
    )
    st.stop()

try:
    initialize_database()
except Exception as exc:
    st.error(f"Could not connect to or initialize the database: {exc}")
    st.stop()


# ---------------------------------------------------------
# LOGGED-IN EXPERIENCE
# ---------------------------------------------------------
if st.session_state.account_no:
    account_no = st.session_state.account_no
    account = get_account(account_no)

    if not account:
        st.session_state.account_no = None
        st.session_state.user_name = None
        st.error("This account could not be found. Please log in again.")
        st.rerun()

    _, name, balance, created_at = account

    with st.sidebar:
        st.success(f"Logged in as {name}")
        st.write(f"Account: `{account_no}`")
        if st.button("Log out", use_container_width=True):
            st.session_state.account_no = None
            st.session_state.user_name = None
            st.rerun()

    st.subheader(f"Welcome back, {name}!")
    st.caption(f"Account created: {created_at:%d %b %Y}")

    col1, col2 = st.columns(2)
    col1.metric("Available balance", money(balance))
    history = get_transactions(account_no)
    col2.metric("Total transactions", len(history))

    deposit_tab, withdraw_tab, history_tab = st.tabs(
        ["➕ Deposit", "➖ Withdraw", "📄 Transaction history"]
    )

    with deposit_tab:
        st.subheader("Deposit money")
        with st.form("deposit_form"):
            deposit_value = st.number_input(
                "Amount (₹)", min_value=0.01, step=100.0, format="%.2f"
            )
            deposit_submit = st.form_submit_button(
                "Deposit money", type="primary", use_container_width=True
            )
        if deposit_submit:
            try:
                new_balance = move_money(
                    account_no, parse_amount(deposit_value), "Deposit"
                )
                st.success(f"Deposit successful. New balance: {money(new_balance)}")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    with withdraw_tab:
        st.subheader("Withdraw money")
        with st.form("withdraw_form"):
            withdraw_value = st.number_input(
                "Amount (₹)", min_value=0.01, step=100.0, format="%.2f",
                key="withdraw_amount"
            )
            withdraw_submit = st.form_submit_button(
                "Withdraw money", type="primary", use_container_width=True
            )
        if withdraw_submit:
            try:
                new_balance = move_money(
                    account_no, parse_amount(withdraw_value), "Withdraw"
                )
                st.success(f"Withdrawal successful. Remaining balance: {money(new_balance)}")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    with history_tab:
        st.subheader("Your transactions")
        if history.empty:
            st.info("No transactions found.")
        else:
            st.dataframe(history, use_container_width=True, hide_index=True)
            csv = history.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download transaction history (CSV)",
                data=csv,
                file_name=f"transactions_{account_no}.csv",
                mime="text/csv",
            )

# ---------------------------------------------------------
# AUTHENTICATION / REGISTRATION
# ---------------------------------------------------------
else:
    login_tab, register_tab = st.tabs(["🔐 Login", "📝 Create account"])

    with login_tab:
        st.subheader("Login to your account")
        with st.form("login_form"):
            login_account = st.text_input("Account number")
            login_pin = st.text_input("4-digit PIN", type="password", max_chars=4)
            login_submit = st.form_submit_button(
                "Login", type="primary", use_container_width=True
            )
        if login_submit:
            if not login_account.strip() or len(login_pin) != 4 or not login_pin.isdigit():
                st.error("Enter a valid account number and 4-digit PIN.")
            else:
                try:
                    user_name = authenticate(login_account.strip(), login_pin)
                    if user_name:
                        st.session_state.account_no = login_account.strip()
                        st.session_state.user_name = user_name
                        st.rerun()
                    else:
                        st.error("Invalid account number or PIN.")
                except Exception as exc:
                    st.error(f"Login failed: {exc}")

    with register_tab:
        st.subheader("Open a new account")
        with st.form("register_form"):
            new_name = st.text_input("Full name")
            new_account = st.text_input("Choose an account number")
            new_pin = st.text_input("Choose a 4-digit PIN", type="password", max_chars=4)
            confirm_pin = st.text_input("Confirm PIN", type="password", max_chars=4)
            opening_value = st.number_input(
                "Opening balance (₹)", min_value=0.0, step=100.0, format="%.2f"
            )
            register_submit = st.form_submit_button(
                "Create account", type="primary", use_container_width=True
            )
        if register_submit:
            if not new_name.strip():
                st.error("Please enter your name.")
            elif not new_account.strip().isdigit():
                st.error("Account number must contain only digits.")
            elif len(new_pin) != 4 or not new_pin.isdigit():
                st.error("PIN must be exactly 4 digits.")
            elif new_pin != confirm_pin:
                st.error("PINs do not match.")
            else:
                try:
                    opening_balance = Decimal(str(opening_value)).quantize(Decimal("0.01"))
                    if opening_balance < 0:
                        st.error("Opening balance cannot be negative.")
                    else:
                        create_account(
                            new_name, new_account.strip(), new_pin, opening_balance
                        )
                        st.success("Account created successfully. You can now log in.")
                except psycopg.errors.UniqueViolation:
                    st.error("That account number is already registered.")
                except Exception as exc:
                    st.error(f"Could not create account: {exc}")

st.divider()
st.caption("PY BANK · Educational project. Not intended for real banking or storing real funds.")
