from datetime import date
from decimal import Decimal, InvalidOperation
from emi_calculator import calculate_emi
from flask import Flask, request, redirect, url_for, session, render_template_string 
from werkzeug.security import check_password_hash
from functools import wraps
from db import get_connection
from html import escape
from datetime import date
import os
from dotenv import load_dotenv
import calendar

load_dotenv()
app = Flask(__name__)
app.secret_key = os.environ["SECRET_KEY"]

SIDEBAR_HTML = """
<link rel="stylesheet" href="/static/style.css">

<div class="sidebar">
    <h2>🏦 Loan System</h2>

    <a href="/">🏠 Home</a>
    <a href="/dashboard">📊 Dashboard</a>
    <a href="/customers">👥 Customers</a>
    <a href="/loans">💰 Loans</a>
    <a href="/payment_history">💳 Payment History</a>
    <a href="/reports">📈 Reports</a>
    <a href="/overdue_reports">⚠️ Overdue EMIs</a>
    <a href="/closed_loans">✅ Closed Loans</a>

    <form method="post" action="/logout">
        <button type="submit">Logout</button>
    </form>
</div>
"""
def admin_layout(page_content):
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport"
              content="width=device-width, initial-scale=1">
        <title>Loan Management System</title>
    </head>
    <body>
        {SIDEBAR_HTML}

        <div class="main-content">
            {page_content}
        </div>
    </body>
    </html>
    """

from decimal import ROUND_HALF_UP

LATE_PENALTY_MONTHLY_RATE = Decimal("0.02")




def calculate_late_penalty(emi_amount, due_date, as_of_date=None):
    if as_of_date is None:
        as_of_date = date.today()

    overdue_days = max(0, (as_of_date - due_date).days)

    amount = Decimal(str(emi_amount))

    penalty = (
        amount
        * LATE_PENALTY_MONTHLY_RATE
        * Decimal(overdue_days)
        / Decimal(30)
    )

    penalty = penalty.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP
    )

    return overdue_days, penalty

def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "logged_in" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped_view


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        with open("user.txt", "r") as file:
            saved_username = file.readline().strip()
            saved_password_hash = file.readline().strip()

        if (
            username == saved_username
            and check_password_hash(saved_password_hash, password)
        ):
            session.clear()
            session["logged_in"] = True
            return redirect(url_for("home"))

        error = "Invalid username or password."

    return render_template_string("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Loan Management Login</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
        </head>
        <body>
            <h1>Loan Management Login</h1>
            {% if error %}
                <p style="color: red;">{{ error }}</p>
            {% endif %}
            <form method="post">
                <label>Username:</label>
                <input type="text" name="username" required>
                <br><br>
                <label>Password:</label>
                <input type="password" name="password" required>
                <br><br>
                <button type="submit">Log In</button>
            </form>
        </body>
        </html>
    """, error=error)

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))



@app.route("/")
@login_required
def home():
    return admin_layout("""
        <h1>Welcome to Loan Management System</h1>

        <p>
            Manage customers, loans, EMI payments,
            reports, and loan closures from one place.
        </p>

        <div class="dashboard-grid">

            <div class="dashboard-card">
                <h3>Customers</h3>
                <p>Manage customer records</p>
                <a href="/customers">View Customers</a>
            </div>

            <div class="dashboard-card">
                <h3>Loans</h3>
                <p>Manage loan applications</p>
                <a href="/loans">View Loans</a>
            </div>

            <div class="dashboard-card">
                <h3>Dashboard</h3>
                <p>View loan statistics</p>
                <a href="/dashboard">Open Dashboard</a>
            </div>

            <div class="dashboard-card">
                <h3>Reports</h3>
                <p>View financial reports</p>
                <a href="/reports">View Reports</a>
            </div>

        </div>
    """)

@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_connection()

    try:
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                COUNT(*) AS total_loans,

                COALESCE(SUM(loan_amount), 0)
                    AS total_loan_amount,

                SUM(CASE WHEN status = 'Active'
                    THEN 1 ELSE 0 END) AS active_loans,

                SUM(CASE WHEN status = 'Approved'
                    THEN 1 ELSE 0 END) AS approved_loans,

                SUM(CASE WHEN status = 'Paid'
                    THEN 1 ELSE 0 END) AS paid_loans,

                SUM(CASE WHEN status = 'Rejected'
                    THEN 1 ELSE 0 END) AS rejected_loans,

                COALESCE((
                    SELECT SUM(disbursement_amount)
                    FROM loan_disbursements
                ), 0) AS total_disbursed

            FROM loans
            """
        )

        loan_summary = cursor.fetchone()

        cursor.execute(
            """
            SELECT
                COUNT(*) AS total_emis,
                COALESCE(SUM(
                    CASE WHEN status = 'Paid'
                    THEN emi_amount ELSE 0 END
                ), 0) AS total_collected,
                COALESCE(SUM(
                    CASE WHEN status = 'Due'
                    THEN emi_amount ELSE 0 END
                ), 0) AS total_pending,
                SUM(CASE WHEN status = 'Paid' THEN 1 ELSE 0 END)
                    AS paid_emis,
                SUM(CASE WHEN status = 'Due' THEN 1 ELSE 0 END)
                    AS pending_emis
            FROM loan_emis
            """
        )

        emi_summary = cursor.fetchone()
        cursor.execute(
            """
            SELECT
                COUNT(*) AS overdue_count,
                COALESCE(SUM(emi_amount), 0)
                    AS overdue_principal_interest,
                COALESCE(SUM(
                    ROUND(
                        emi_amount * 0.02
                        * DATEDIFF(CURDATE(), emi_date) / 30,
                        2
                    )
                ), 0) AS overdue_penalties
            FROM loan_emis
            WHERE status = 'Due'
              AND emi_date < CURDATE()
            """
        )

        overdue_summary = cursor.fetchone()

        overdue_summary["total_overdue"] = (
            overdue_summary["overdue_principal_interest"]
            + overdue_summary["overdue_penalties"]
        )

    finally:
        cursor.close()
        conn.close()

    return render_template_string("""
        <h1>Loan Management Dashboard</h1>

        <h2>Loan Summary</h2>

        <p>Total Loans: {{ loan_summary.total_loans }}</p>

        <p>Total Loan Amount: ₹{{ loan_summary.total_loan_amount }}</p>

        <p>Active Loans: {{ loan_summary.active_loans or 0 }}</p>

        <p>Approved Loans: {{ loan_summary.approved_loans or 0 }}</p>

        <p>Paid Loans: {{ loan_summary.paid_loans or 0 }}</p>

        <p>Rejected Loans: {{ loan_summary.rejected_loans or 0 }}</p>

        <p>Total Disbursed: ₹{{ loan_summary.total_disbursed }}</p>

        <h2>EMI Summary</h2>
        <p>Total EMIs: {{ emi_summary.total_emis }}</p>
        <p>Paid EMIs: {{ emi_summary.paid_emis or 0 }}</p>
        <p>Pending EMIs: {{ emi_summary.pending_emis or 0 }}</p>
        <p>Total Collected: ₹{{ emi_summary.total_collected }}</p>
        <p>Total Pending: ₹{{ emi_summary.total_pending }}</p>
        <h2 style="color:#b91c1c;">Overdue EMI Summary</h2>

        <p>Overdue EMI Count: {{ overdue_summary.overdue_count }}</p>

        <p>
            Overdue EMI Amount:
            ₹{{ overdue_summary.overdue_principal_interest }}
        </p>

        <p>
            Outstanding Late Penalties:
            ₹{{ overdue_summary.overdue_penalties }}
        </p>

        <p>
            <strong>
                Total Overdue Including Penalties:
                ₹{{ overdue_summary.total_overdue }}
            </strong>
        </p>

        <p>
            <a href="/overdue_reports">View Overdue EMI Report</a>
        </p>
        <p><a href="/payment_history">EMI Payment History</a></p>
        

        <br>
        <a href="/customers">Customers</a> |
        <a href="/loans">Loans</a>
        <a href="/reports">Reports and Analytics</a>
        """,
            loan_summary=loan_summary,
            emi_summary=emi_summary,
            overdue_summary=overdue_summary
    )
    


@app.route("/reports")
@login_required
def reports():
    conn = get_connection()
    cursor = None

    try:
        cursor = conn.cursor(dictionary=True)

        # 1. Overall EMI payment summary
        cursor.execute(
            """
            SELECT
                COUNT(*) AS total_emis,

                COALESCE(SUM(
                    CASE WHEN status = 'Paid'
                    THEN 1 ELSE 0 END
                ), 0) AS paid_emis,

                COALESCE(SUM(
                    CASE WHEN status = 'Due'
                    THEN 1 ELSE 0 END
                ), 0) AS pending_emis,

                COALESCE(SUM(
                    CASE WHEN status = 'Paid'
                    THEN emi_amount ELSE 0 END
                ), 0) AS total_collected,

                COALESCE(SUM(
                    CASE WHEN status = 'Due'
                    THEN emi_amount ELSE 0 END
                ), 0) AS total_outstanding

            FROM loan_emis
            """
        )

        emi_summary = cursor.fetchone()

        # 2. Monthly EMI collections
        cursor.execute(
            """
            SELECT
                DATE_FORMAT(payment_date, '%Y-%m')
                    AS collection_month,
                SUM(emi_amount) AS monthly_collection
            FROM loan_emis
            WHERE status = 'Paid'
            AND payment_date IS NOT NULL
            GROUP BY DATE_FORMAT(payment_date, '%Y-%m')
            ORDER BY collection_month DESC
            """
        )

        monthly_collections = cursor.fetchall()

        # 3. Customer-wise outstanding amounts
        cursor.execute(
            """
            SELECT
                customers.customer_id,
                customers.name,
                COALESCE(SUM(loan_emis.emi_amount), 0)
                    AS outstanding_amount

            FROM customers

            JOIN loans
                ON customers.customer_id = loans.customer_id

            JOIN loan_emis
                ON loans.loan_id = loan_emis.loan_id

            WHERE loan_emis.status = 'Due'

            GROUP BY customers.customer_id, customers.name

            ORDER BY outstanding_amount DESC
            """
        )

        customer_outstanding = cursor.fetchall()

        # 4. Loan status breakdown
        cursor.execute(
            """
            SELECT
                status,
                COUNT(*) AS loan_count
            FROM loans
            GROUP BY status
            ORDER BY status
            """
        )

        loan_status_summary = cursor.fetchall()

    finally:
        if cursor is not None:
            cursor.close()
        conn.close()

    return render_template_string("""
        <h1>Reports and Analytics</h1>

        <h2>EMI Payment Summary</h2>

        <p>Total EMIs: {{ emi_summary.total_emis }}</p>

        <p>Paid EMIs: {{ emi_summary.paid_emis }}</p>

        <p>Pending EMIs: {{ emi_summary.pending_emis }}</p>

        <p>
            Total Collected:
            ₹{{ emi_summary.total_collected }}
        </p>

        <p>
            Total Outstanding:
            ₹{{ emi_summary.total_outstanding }}
        </p>

        <hr>

        <h2>Monthly EMI Collections</h2>

        {% if monthly_collections %}
        <table border="1" cellpadding="10">
            <tr>
                <th>Month</th>
                <th>Amount Collected</th>
            </tr>

            {% for item in monthly_collections %}
            <tr>
                <td>{{ item.collection_month }}</td>
                <td>₹{{ item.monthly_collection }}</td>
            </tr>
            {% endfor %}
        </table>
        {% else %}
            <p>No EMI collections recorded yet.</p>
        {% endif %}

        <hr>

        <h2>Customer-wise Outstanding Amount</h2>

        {% if customer_outstanding %}
        <table border="1" cellpadding="10">
            <tr>
                <th>Customer ID</th>
                <th>Customer Name</th>
                <th>Outstanding Amount</th>
            </tr>

            {% for customer in customer_outstanding %}
            <tr>
                <td>{{ customer.customer_id }}</td>
                <td>{{ customer.name }}</td>
                <td>₹{{ customer.outstanding_amount }}</td>
            </tr>
            {% endfor %}
        </table>
        {% else %}
            <p>No outstanding EMI amounts.</p>
        {% endif %}

        <hr>

        <h2>Loan Status Breakdown</h2>

        <table border="1" cellpadding="10">
            <tr>
                <th>Loan Status</th>
                <th>Number of Loans</th>
            </tr>

            {% for item in loan_status_summary %}
            <tr>
                <td>{{ item.status }}</td>
                <td>{{ item.loan_count }}</td>
            </tr>
            {% endfor %}
        </table>

        <br>

        <a href="/dashboard">Dashboard</a> |
        <a href="/customers">Customers</a> |
        <a href="/loans">Loans</a> |
        <a href="/overdue_reports">Overdue EMI Report</a> |
    """,
        emi_summary=emi_summary,
        monthly_collections=monthly_collections,
        customer_outstanding=customer_outstanding,
        loan_status_summary=loan_status_summary
    )



@app.route("/customers", methods=["GET", "POST"])
@login_required
def customers():

    # Add a new customer
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        address = request.form.get("address", "").strip()
        dob = request.form.get("date_of_birth", "").strip()

        if not name or not phone:
            return "Name and phone are required.", 400

        # Validate date of birth if provided
        if dob:
            try:
                dob = date.fromisoformat(dob)
                if dob >= date.today():
                    return "Date of birth must be in the past.", 400
            except ValueError:
                return "Invalid date of birth.", 400
        else:
            dob = None

        conn = get_connection()

        try:
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO customers
                    (name, phone, email, address, date_of_birth)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    name,
                    phone,
                    email or None,
                    address or None,
                    dob
                )
            )

            conn.commit()
            cursor.close()

        finally:
            conn.close()

        return redirect(url_for("customers"))

    # Retrieve customers from MySQL
    conn = get_connection()

    try:
        cursor = conn.cursor(dictionary=True)

        search_term = request.args.get("search", "").strip()
        search_pattern = f"%{search_term}%"

        cursor.execute(
            """
            SELECT customer_id, name, phone, email,
                address, date_of_birth
            FROM customers
            WHERE name LIKE %s OR phone LIKE %s
            ORDER BY customer_id DESC
            """,
            (search_pattern, search_pattern)
        )

        customer_list = cursor.fetchall()
        cursor.close()

    finally:
        conn.close()

    
    # Build the customer table
    rows = ""

    for customer in customer_list:
        rows += f"""
        <tr>
            <td>{customer['customer_id']}</td>
            <td>{escape(customer['name'])}</td>
            <td>{escape(customer['phone'])}</td>
            <td>{escape(customer['email'] or '')}</td>
            <td>{escape(customer['address'] or '')}</td>
            <td>{customer['date_of_birth'] or ''}</td>
           
            <td>
                <a href="/edit_customer/{customer['customer_id']}">Edit</a>

                <form method="post"
                    action="/delete_customer/{customer['customer_id']}"
                    onsubmit="return confirm('Are you sure you want to delete this customer?');"
                    style="display:inline;">
                    <button type="submit">Delete</button>
                </form>
            </td>
            <td>
                <a href="/customer_loans/{customer['customer_id']}">
                     View Loans
                </a>
            </td>

        </tr>
        """

    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Customer Management</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 30px;
                background: #f4f6f9;
                color: #222;
            }

            h1, h2 {
                color: #183153;
            }

            form, .table-container {
                background: white;
                padding: 20px;
                border-radius: 8px;
                margin-bottom: 25px;
            }

            label {
                display: block;
                margin-top: 12px;
                font-weight: bold;
            }

            input {
                box-sizing: border-box;
                width: 100%;
                max-width: 450px;
                padding: 10px;
                margin-top: 5px;
            }

            button {
                margin-top: 18px;
                padding: 10px 18px;
                background: #183153;
                color: white;
                border: none;
                border-radius: 5px;
                cursor: pointer;
            }

            table {
                border-collapse: collapse;
                width: 100%;
                background: white;
            }

            th, td {
                padding: 10px;
                border: 1px solid #ddd;
                text-align: left;
            }

            th {
                background: #183153;
                color: white;
            }

            .table-container {
                overflow-x: auto;
            }
        </style>
    </head>
    <body>
        <h1>Customer Management</h1>

        <form method="post">
            <h2>Add Customer</h2>

            <label for="name">Name *</label>
            <input id="name" name="name" maxlength="100" required>

            <label for="phone">Phone *</label>
            <input id="phone" name="phone" maxlength="20" required>

            <label for="email">Email</label>
            <input id="email" name="email" type="email" maxlength="100">

            <label for="date_of_birth">Date of Birth</label>
            <input id="date_of_birth" name="date_of_birth" type="date">

            <label for="address">Address</label>
            <input id="address" name="address" maxlength="255">

            <button type="submit">Add Customer</button>
        </form>

        <form method="get">
            <h2>Search Customers</h2>
            <input
                type="text"
                name="search"
                placeholder="Search by name or phone"
            >
            <button type="submit">Search</button>
            <a href="/customers">Clear</a>
        </form>

        <div class="table-container">
            <h2>Saved Customers</h2>

            <table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Name</th>
                        <th>Phone</th>
                        <th>Email</th>
                        <th>Address</th>
                        <th>Date of Birth</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
    """ + rows + """
                </tbody>
            </table>
        </div>

        <p><a href="/">Back to Home</a></p>
    </body>
    </html>
    """
@app.route("/customer_loans/<int:customer_id>")
@login_required
def customer_loans(customer_id):
    conn = get_connection()
    cursor = None

    try:
        cursor = conn.cursor(dictionary=True)

        # Get customer details
        cursor.execute(
            """
            SELECT *
            FROM customers
            WHERE customer_id = %s
            """,
            (customer_id,)
        )

        customer = cursor.fetchone()

        if customer is None:
            return "Customer not found.", 404

        # Get all loans belonging to this customer
        cursor.execute(
            """
            SELECT *
            FROM loans
            WHERE customer_id = %s
            ORDER BY loan_id DESC
            """,
            (customer_id,)
        )

        loan_list = cursor.fetchall()

        # Get EMI details for each loan
        for loan in loan_list:
            cursor.execute(
                """
                SELECT *
                FROM loan_emis
                WHERE loan_id = %s
                ORDER BY emi_number
                """,
                (loan["loan_id"],)
            )

            loan["emi_list"] = cursor.fetchall()

    finally:
        if cursor is not None:
            cursor.close()
        conn.close()

    return render_template_string("""
        <h1>Customer Loan Details</h1>

        <h2>Customer Information</h2>

        <p>Customer ID: {{ customer.customer_id }}</p>

        <h2>Loans</h2>

        {% if loan_list %}
            {% for loan in loan_list %}

                <hr>

                <h3>Loan ID: {{ loan.loan_id }}</h3>

                <p>Loan Amount: ₹{{ loan.loan_amount }}</p>

                <p>Interest Rate: {{ loan.annual_interest_rate }}%</p>

                <p>Duration: {{ loan.duration_months }} months</p>

                <p>Loan Status: {{ loan.status }}</p>

                <h4>EMI Payment Details</h4>

                {% if loan.emi_list %}
                    <table border="1" cellpadding="8">
                        <tr>
                            <th>EMI Number</th>
                            <th>Due Date</th>
                            <th>EMI Amount</th>
                            <th>Balance</th>
                            <th>Status</th>
                            <th>Payment Date</th>
                        </tr>

                        {% for emi in loan.emi_list %}
                        <tr>
                            <td>{{ emi.emi_number }}</td>
                            <td>{{ emi.emi_date }}</td>
                            <td>₹{{ emi.emi_amount }}</td>
                            <td>₹{{ emi.balance_amount }}</td>
                            <td>{{ emi.status }}</td>
                            <td>{{ emi.payment_date or "-" }}</td>
                        </tr>
                        {% endfor %}
                    </table>
                {% else %}
                    <p>No EMI schedule generated yet.</p>
                {% endif %}

            {% endfor %}
        {% else %}
            <p>This customer has no loans.</p>
        {% endif %}

        <br>
        <a href="/customers">Back to Customers</a>
    """, customer=customer, loan_list=loan_list)


@app.route("/edit_customer/<int:customer_id>", methods=["GET", "POST"])
def edit_customer(customer_id):

    conn = get_connection()

    try:
        cursor = conn.cursor(dictionary=True)

        # Find the customer
        cursor.execute(
            """
            SELECT customer_id, name, phone, email,
                   address, date_of_birth
            FROM customers
            WHERE customer_id = %s
            """,
            (customer_id,)
        )

        customer = cursor.fetchone()

        if customer is None:
            return "Customer not found.", 404

        # Save changes when the form is submitted
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            phone = request.form.get("phone", "").strip()
            email = request.form.get("email", "").strip()
            address = request.form.get("address", "").strip()
            dob = request.form.get("date_of_birth", "").strip()

            if not name or not phone:
                return "Name and phone are required.", 400

            if dob:
                try:
                    dob = date.fromisoformat(dob)
                    if dob >= date.today():
                        return "Date of birth must be in the past.", 400
                except ValueError:
                    return "Invalid date of birth.", 400
            else:
                dob = None

            cursor.execute(
                """
                UPDATE customers
                SET name = %s,
                    phone = %s,
                    email = %s,
                    address = %s,
                    date_of_birth = %s
                WHERE customer_id = %s
                """,
                (
                    name,
                    phone,
                    email or None,
                    address or None,
                    dob,
                    customer_id
                )
            )

            conn.commit()
            return redirect(url_for("customers"))

        # Display the edit form
        dob_value = (
            customer["date_of_birth"].isoformat()
            if customer["date_of_birth"]
            else ""
        )

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Edit Customer</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
        </head>
        <body>
            <h1>Edit Customer</h1>

            <form method="post">
                <label>Name:</label>
                <input name="name" maxlength="100"
                       value="{escape(customer['name'])}" required>
                <br><br>

                <label>Phone:</label>
                <input name="phone" maxlength="20"
                       value="{escape(customer['phone'])}" required>
                <br><br>

                <label>Email:</label>
                <input name="email" type="email" maxlength="100"
                       value="{escape(customer['email'] or '')}">
                <br><br>

                <label>Date of Birth:</label>
                <input name="date_of_birth" type="date"
                       value="{dob_value}">
                <br><br>

                <label>Address:</label>
                <input name="address" maxlength="255"
                       value="{escape(customer['address'] or '')}">
                <br><br>

                <button type="submit">Save Changes</button>
            </form>

            <p><a href="/customers">Cancel</a></p>
        </body>
        </html>
        """

    finally:
        conn.close()

@app.route("/delete_customer/<int:customer_id>", methods=["POST"])
def delete_customer(customer_id):

    conn = get_connection()

    try:
        cursor = conn.cursor()

        cursor.execute(
            "DELETE FROM customers WHERE customer_id = %s",
            (customer_id,)
        )

        conn.commit()

        

    finally:
        cursor.close()
        conn.close()

    return redirect(url_for("customers"))

@app.route("/loans", methods=["GET", "POST"])
@login_required
def loans():

    conn = get_connection()

    try:
        cursor = conn.cursor(dictionary=True)

        # Load customers for the dropdown
        cursor.execute(
            "SELECT customer_id, name FROM customers ORDER BY name"
        )
        customer_list = cursor.fetchall()

        # Load loan types for the dropdown
        cursor.execute(
            "SELECT loan_type_id, type_name FROM loan_types ORDER BY type_name"
        )
        loan_type_list = cursor.fetchall()

        if request.method == "POST":
            customer_id = request.form.get("customer_id", "").strip()
            loan_type_id = request.form.get("loan_type_id", "").strip()
            amount_text = request.form.get("loan_amount", "").strip()
            rate_text = request.form.get("annual_interest_rate", "").strip()
            duration_text = request.form.get("duration_months", "").strip()
            loan_date = request.form.get("loan_date", "").strip()

            try:
                customer_id = int(customer_id)
                loan_type_id = int(loan_type_id)
                amount = float(amount_text)
                rate = float(rate_text)
                duration = int(duration_text)
                loan_date = date.fromisoformat(loan_date)

                if amount <= 0 or rate < 0 or duration <= 0:
                    return "Enter a positive amount and duration, and a non-negative interest rate.", 400

                if loan_date > date.today():
                    return "Loan date cannot be in the future.", 400

                cursor.execute(
                """
                INSERT INTO loans
                    (customer_id, loan_type_id, loan_amount,
                    annual_interest_rate, duration_months, loan_date)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    customer_id,
                    loan_type_id,
                    amount,
                    rate,
                    duration,
                    loan_date
                )
)

                conn.commit()
                return redirect(url_for("loans"))

            except (ValueError, TypeError):
                return "Please enter valid loan details.", 400

        # Build the customer dropdown
        customer_options = ""

        for customer in customer_list:
            customer_options += (
                f"<option value='{customer['customer_id']}'>"
                f"{escape(customer['name'])}</option>"
            )
        # Build the loan type dropdown
        loan_type_options = ""

        for loan_type in loan_type_list:
            loan_type_options += (
                f"<option value='{loan_type['loan_type_id']}'>"
                f"{escape(loan_type['type_name'])}</option>"
            )

        loan_status_filter = request.args.get("status", "").strip()

        allowed_statuses = [
            "Active",
            "Approved",
            "Paid",
            "Rejected"
        ]

        if loan_status_filter not in allowed_statuses:
            loan_status_filter = ""

        cursor.execute(
            """
            
            SELECT
                loans.loan_id,
                customers.name,
                loan_types.type_name,
                loans.loan_amount,
                loans.annual_interest_rate,
                loans.duration_months,
                loans.loan_date,
                loans.status,
                loan_disbursements.disbursement_id,
                loan_disbursements.disbursement_amount

            FROM loans

            JOIN customers
                ON loans.customer_id = customers.customer_id

            LEFT JOIN loan_types
                ON loans.loan_type_id = loan_types.loan_type_id

            LEFT JOIN loan_disbursements
                ON loans.loan_id = loan_disbursements.loan_id

            ORDER BY loans.loan_id DESC

            """
        )

        loan_list = cursor.fetchall()
        if loan_status_filter:
            loan_list = [
                loan for loan in loan_list
                if loan["status"] == loan_status_filter
            ]

        loan_rows = ""

       
        for loan in loan_list:
            emi = calculate_emi(
                float(loan['loan_amount']),
                float(loan['annual_interest_rate']),
                int(loan['duration_months'])
            )

            total_repayment = round(
                emi * int(loan['duration_months']), 2
            )

            total_interest = round(
                total_repayment - float(loan['loan_amount']), 2
            )

            status = loan["status"]

            
            if status == "Active":
                action_buttons = f"""
                    <form method="post"
                        action="/update_loan_status/{loan['loan_id']}">
                        <button type="submit" name="status" value="Approved">
                            Approve
                        </button>
                        <button type="submit" name="status" value="Rejected">
                            Reject
                        </button>
                    </form>
                    <a href="/emi_details/{loan['loan_id']}">
                        EMI Details
                    </a>
                """
            elif status == "Approved":
                action_buttons = f"""
                    <a href="/emi_details/{loan['loan_id']}">
                        EMI Details
                    </a>
                """
            elif status == "Paid":
                action_buttons = f"""
                    <a href="/emi_details/{loan['loan_id']}">
                        EMI Details
                    </a>

                    <br><br>

                    <a href="/close_loan/{loan['loan_id']}">
                        Loan Closure / Certificate
                    </a>
                """

            else:
                action_buttons = "<span>No actions available</span>"

            # Edit Loan action
            action_buttons += f"""
                <br><br>
                <a href="/edit_loan/{loan['loan_id']}">
                    Edit Loan
                </a>
            """

            # Disbursement actions
            if loan["disbursement_id"] is not None:
                action_buttons += f"""
                    <br><br>
                    <a href="/disbursement_details/{loan['loan_id']}">
                        View Disbursement
                    </a>

                    <p>
                        Disbursed: ₹{loan['disbursement_amount']}
                    </p>
                """

            elif status == "Approved":
                action_buttons += f"""
                    <br><br>
                    <a href="/disburse_loan/{loan['loan_id']}">
                        Disburse Loan
                    </a>
                """




            loan_rows += f"""
            <tr>
                <td>{loan['loan_id']}</td>
                <td>{escape(loan['name'])}</td>
                <td>{escape(loan['type_name'] or 'Not assigned')}</td>
                <td>₹{loan['loan_amount']}</td>
                <td>{loan['annual_interest_rate']}%</td>
                <td>{loan['duration_months']} months</td>
                <td>{loan['loan_date']}</td>
                
                <td>{escape(loan['status'])}</td>
                <td>{action_buttons}</td>
                

                <td>₹{emi:.2f}</td>
                <td>₹{total_repayment:.2f}</td>
                <td>₹{total_interest:.2f}</td>
            </tr>
            """


        return f"""

        <!DOCTYPE html>
        <html>
        
        <head>
            <title>Loan Management</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">

            <style>
                body {{
                    font-family: Arial, sans-serif;
                    background: #f4f7fb;
                    color: #243047;
                    margin: 0;
                    padding: 30px;
                }}

                h1 {{
                    color: #123b66;
                }}

                form, table {{
                    background: white;
                    padding: 20px;
                    border-radius: 10px;
                }}

                input, select {{
                    padding: 8px;
                    margin-top: 6px;
                    border: 1px solid #ccd5e0;
                    border-radius: 5px;
                }}

                button {{
                    background: #1769aa;
                    color: white;
                    padding: 10px 18px;
                    border: none;
                    border-radius: 5px;
                    cursor: pointer;
                }}

                button:hover {{
                    background: #104d80;
                }}

                table {{
                    width: 100%;
                    border-collapse: collapse;
                    padding: 0;
                }}

                th {{
                    background: #123b66;
                    color: white;
                }}

                th, td {{
                    padding: 10px;
                    border: 1px solid #dce3eb;
                    text-align: left;
                }}

                tr:nth-child(even) {{
                    background: #f0f5fa;
                }}
            </style>
        </head>

        <body>
            <h1>Loan Management</h1>

            <form method="post">
                <label>Customer:</label>
                <select name="customer_id" required>
                    {customer_options}
                </select>
                <br><br>
                <label>Loan Type:</label>
                <select name="loan_type_id" required>
                    {loan_type_options}
                </select>
                <br><br>

                <label>Loan Amount (₹):</label>
                <input type="number" id="loan_amount" name="loan_amount"
                       min="0.01" step="0.01" required>
                <br><br>

                <label>Annual Interest Rate (%):</label>
                <input type="number" id="annual_interest_rate"
                        name="annual_interest_rate"
                        min="0" step="0.01" required>
                <br><br>

                <label>Duration (months):</label>
                <input type="number" id="duration_months" name="duration_months"
                        min="1" step="1" required>
                <br><br>

                <label>Loan Date:</label>
                <input type="date" name="loan_date"
                       value="{date.today().isoformat()}" required>
                <br><br>

                <h3>Live EMI Calculator</h3>

                <p>Monthly EMI: ₹<span id="emi">0.00</span></p>
                <p>Total Repayment: ₹<span id="total_repayment">0.00</span></p>
                <p>Total Interest: ₹<span id="total_interest">0.00</span></p>

                <br>


                <button type="submit">Create Loan</button>
            </form>

            
<h2>Saved Loans</h2>

<form method="get">
    <label>Filter Loans by Status:</label>

    <select name="status">
        <option value="">All Loans</option>
        <option value="Active">Active</option>
        <option value="Approved">Approved</option>
        <option value="Paid">Paid</option>
        <option value="Rejected">Rejected</option>
    </select>

    <button type="submit">Filter</button>
    <a href="/loans">Clear Filter</a>
</form>

<table border="1" cellpadding="8" cellspacing="0">
    <thead>
        <tr>
            <th>Loan ID</th>
            <th>Customer</th>
            <th>Loan Type</th>
            <th>Amount</th>
            <th>Annual Interest</th>
            <th>Duration</th>
            <th>Loan Date</th>
            <th>Status</th>
            <th>Actions</th>
            <th>Monthly EMI</th>
            <th>Total Repayment</th>
            <th>Total Interest</th>
        </tr>
    </thead>
    <tbody>
        {loan_rows if loan_rows else '<tr><td colspan="11">No loans found.</td></tr>'}
    </tbody>
</table>


<script>
function calculateLiveEMI() {{
    const amount = parseFloat(
        document.getElementById("loan_amount").value
    );

    const annualRate = parseFloat(
        document.getElementById("annual_interest_rate").value
    );

    const months = parseInt(
        document.getElementById("duration_months").value
    );

    const emiDisplay = document.getElementById("emi");
    const repaymentDisplay = document.getElementById("total_repayment");
    const interestDisplay = document.getElementById("total_interest");

    if (
        !Number.isFinite(amount) || amount <= 0 ||
        !Number.isFinite(annualRate) || annualRate < 0 ||
        !Number.isInteger(months) || months <= 0
    ) {{
        emiDisplay.textContent = "0.00";
        repaymentDisplay.textContent = "0.00";
        interestDisplay.textContent = "0.00";
        return;
    }}

    const monthlyRate = annualRate / 12 / 100;
    let emi;

    if (monthlyRate === 0) {{
        emi = amount / months;
    }} else {{
        const factor = Math.pow(1 + monthlyRate, months);
        emi = amount * monthlyRate * factor / (factor - 1);
    }}

    emi = Math.round((emi + Number.EPSILON) * 100) / 100;

    const totalRepayment = Math.round(
        (emi * months + Number.EPSILON) * 100
    ) / 100;

    const totalInterest = Math.round(
        (totalRepayment - amount + Number.EPSILON) * 100
    ) / 100;

    emiDisplay.textContent = emi.toFixed(2);
    repaymentDisplay.textContent = totalRepayment.toFixed(2);
    interestDisplay.textContent = totalInterest.toFixed(2);
}}

document.getElementById("loan_amount")
    .addEventListener("input", calculateLiveEMI);

document.getElementById("annual_interest_rate")
    .addEventListener("input", calculateLiveEMI);

document.getElementById("duration_months")
    .addEventListener("input", calculateLiveEMI);
</script>


<p><a href="/">Back to Home</a></p>
<p><a href="/customers">Manage Customers</a></p>

        </body>
        </html>
        """



    finally:
        conn.close()
@app.route("/edit_loan/<int:loan_id>", methods=["GET", "POST"])
@login_required
def edit_loan(loan_id):
    conn = get_connection()
    cursor = None

    try:
        cursor = conn.cursor(dictionary=True)

        # Get the selected loan
        cursor.execute(
            """
            SELECT
                loan_id,
                loan_type_id,
                loan_amount,
                annual_interest_rate,
                duration_months,
                loan_date
            FROM loans
            WHERE loan_id = %s
            """,
            (loan_id,)
        )

        loan = cursor.fetchone()

        if loan is None:
            return "Loan not found.", 404

        # Check whether an EMI schedule already exists
        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM loan_emis
            WHERE loan_id = %s
            """,
            (loan_id,)
        )

        emi_result = cursor.fetchone()
        has_emis = emi_result["total"] > 0

        # Get all available loan types
        cursor.execute(
            """
            SELECT loan_type_id, type_name
            FROM loan_types
            ORDER BY type_name
            """
        )

        loan_type_list = cursor.fetchall()

        if request.method == "POST":
            loan_type_id = request.form.get(
                "loan_type_id", ""
            ).strip()

            try:
                if not loan_type_id:
                    return "Please select a loan type.", 400

                loan_type_id = int(loan_type_id)

                # Verify that the selected loan type exists
                cursor.execute(
                    """
                    SELECT loan_type_id
                    FROM loan_types
                    WHERE loan_type_id = %s
                    """,
                    (loan_type_id,)
                )

                if cursor.fetchone() is None:
                    return "Invalid loan type selected.", 400

                # If EMIs exist, update only the loan type
                if has_emis:
                    cursor.execute(
                        """
                        UPDATE loans
                        SET loan_type_id = %s
                        WHERE loan_id = %s
                        """,
                        (loan_type_id, loan_id)
                    )

                else:
                    amount = float(
                        request.form.get("loan_amount", "")
                    )

                    rate = float(
                        request.form.get("annual_interest_rate", "")
                    )

                    duration = int(
                        request.form.get("duration_months", "")
                    )

                    loan_date = date.fromisoformat(
                        request.form.get("loan_date", "")
                    )

                    if amount <= 0 or rate < 0 or duration <= 0:
                        return "Enter valid loan amount, interest rate and duration.", 400

                    if loan_date > date.today():
                        return "Loan date cannot be in the future.", 400

                    cursor.execute(
                        """
                        UPDATE loans
                        SET loan_type_id = %s,
                            loan_amount = %s,
                            annual_interest_rate = %s,
                            duration_months = %s,
                            loan_date = %s
                        WHERE loan_id = %s
                        """,
                        (
                            loan_type_id,
                            amount,
                            rate,
                            duration,
                            loan_date,
                            loan_id
                        )
                    )

                conn.commit()
                return redirect(url_for("loans"))

            except (ValueError, TypeError):
                return "Please enter valid loan details.", 400

        # Prepare loan type dropdown
        loan_type_options = ""

        for item in loan_type_list:
            selected = (
                "selected"
                if item["loan_type_id"] == loan["loan_type_id"]
                else ""
            )

            loan_type_options += (
                f"<option value='{item['loan_type_id']}' {selected}>"
                f"{escape(item['type_name'])}</option>"
            )

        loan_date_value = loan["loan_date"].isoformat()

        # Lock financial terms if an EMI schedule exists
        readonly = "readonly" if has_emis else ""

        if has_emis:
            notice = """
                <p style="color: #b45309;">
                    This loan already has an EMI schedule.
                    You can change its Loan Type, but its financial
                    terms are locked to protect the EMI records.
                </p>
            """
        else:
            notice = """
                <p>
                    You can update the loan type and financial details.
                </p>
            """

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Edit Loan</title>
            <meta name="viewport" content="width=device-width, initial-scale=1">
        </head>

        <body>
            <h1>Edit Loan #{loan_id}</h1>

            {notice}

            <form method="post">

                <label>Loan Type:</label>
                <select name="loan_type_id" required>
                    {loan_type_options}
                </select>
                <br><br>

                <label>Loan Amount (₹):</label>
                <input
                    type="number"
                    name="loan_amount"
                    min="0.01"
                    step="0.01"
                    value="{loan['loan_amount']}"
                    {readonly}
                    required
                >
                <br><br>

                <label>Annual Interest Rate (%):</label>
                <input
                    type="number"
                    name="annual_interest_rate"
                    min="0"
                    step="0.01"
                    value="{loan['annual_interest_rate']}"
                    {readonly}
                    required
                >
                <br><br>

                <label>Duration (months):</label>
                <input
                    type="number"
                    name="duration_months"
                    min="1"
                    step="1"
                    value="{loan['duration_months']}"
                    {readonly}
                    required
                >
                <br><br>

                <label>Loan Date:</label>
                <input
                    type="date"
                    name="loan_date"
                    value="{loan_date_value}"
                    {readonly}
                    required
                >
                <br><br>

                <button type="submit">Save Changes</button>
            </form>

            <p><a href="/loans">Back to Loans</a></p>
        </body>
        </html>
        """

    finally:
        if cursor is not None:
            cursor.close()
        conn.close()


@app.route("/disburse_loan/<int:loan_id>", methods=["GET", "POST"])
@login_required
def disburse_loan(loan_id):
    conn = get_connection()
    cursor = None

    try:
        cursor = conn.cursor(dictionary=True)

        # Get loan details
        cursor.execute(
            """
            SELECT loan_id, loan_amount, status
            FROM loans
            WHERE loan_id = %s
            """,
            (loan_id,)
        )

        loan = cursor.fetchone()

        if loan is None:
            return "Loan not found.", 404

        # Only approved loans can be disbursed
        if loan["status"] != "Approved":
            return "Only approved loans can be disbursed.", 400

        # Check whether this loan was already disbursed
        cursor.execute(
            """
            SELECT disbursement_id
            FROM loan_disbursements
            WHERE loan_id = %s
            """,
            (loan_id,)
        )

        existing_disbursement = cursor.fetchone()

        if existing_disbursement:
            return redirect(
                url_for("disbursement_details", loan_id=loan_id)
            )

        if request.method == "POST":

            amount_text = request.form.get(
                "disbursement_amount", ""
            ).strip()

            disbursement_date_text = request.form.get(
                "disbursement_date", ""
            ).strip()

            payment_method = request.form.get(
                "payment_method", ""
            ).strip()

            reference_number = request.form.get(
                "reference_number", ""
            ).strip()

            notes = request.form.get("notes", "").strip()

            allowed_methods = [
                "Bank Transfer",
                "Cheque",
                "Cash",
                "UPI",
                "Other"
            ]

            try:
                amount = Decimal(amount_text)

                if not amount.is_finite() or amount <= 0:
                    return "Enter a valid disbursement amount.", 400

                approved_amount = Decimal(str(loan["loan_amount"]))

                if amount > approved_amount:
                    return (
                        "Disbursement amount cannot exceed "
                        "the approved loan amount.",
                        400
                    )

                if amount != amount.quantize(Decimal("0.01")):
                    return "Amount can have a maximum of two decimal places.", 400

                if amount > Decimal("9999999999.99"):
                    return "Disbursement amount is too large.", 400

                disbursement_date = date.fromisoformat(
                    disbursement_date_text
                )

                if disbursement_date > date.today():
                    return "Disbursement date cannot be in the future.", 400

                if payment_method not in allowed_methods:
                    return "Select a valid payment method.", 400

                if len(reference_number) > 100 or len(notes) > 255:
                    return "Reference or notes are too long.", 400

            except (InvalidOperation, ValueError, TypeError):
                return "Please enter valid disbursement details.", 400

            # Insert the disbursement record
            cursor.execute(
                """
                INSERT INTO loan_disbursements (
                    loan_id,
                    disbursement_amount,
                    disbursement_date,
                    payment_method,
                    reference_number,
                    notes
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    loan_id,
                    amount,
                    disbursement_date,
                    payment_method,
                    reference_number or None,
                    notes or None
                )
            )

            conn.commit()

            return redirect(
                url_for("disbursement_details", loan_id=loan_id)
            )

        # Display the disbursement form
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Loan Disbursement</title>
            <meta name="viewport"
                  content="width=device-width, initial-scale=1">
        </head>

        <body>
            <h1>Disburse Loan #{loan_id}</h1>

            <p>
                Approved Loan Amount:
                ₹{loan['loan_amount']}
            </p>

            <form method="post">

                <label>Disbursement Amount (₹):</label>
                <input
                    type="number"
                    name="disbursement_amount"
                    min="0.01"
                    max="{loan['loan_amount']}"
                    step="0.01"
                    required
                >
                <br><br>

                <label>Disbursement Date:</label>
                <input
                    type="date"
                    name="disbursement_date"
                    value="{date.today().isoformat()}"
                    max="{date.today().isoformat()}"
                    required
                >
                <br><br>

                <label>Payment Method:</label>
                <select name="payment_method" required>
                    <option value="">Select Method</option>
                    <option value="Bank Transfer">Bank Transfer</option>
                    <option value="Cheque">Cheque</option>
                    <option value="Cash">Cash</option>
                    <option value="UPI">UPI</option>
                    <option value="Other">Other</option>
                </select>
                <br><br>

                <label>Reference Number:</label>
                <input
                    type="text"
                    name="reference_number"
                    maxlength="100"
                >
                <br><br>

                <label>Notes:</label>
                <textarea
                    name="notes"
                    maxlength="255"
                ></textarea>
                <br><br>

                <button type="submit">
                    Save Disbursement
                </button>

            </form>

            <p>
                <a href="/loans">Back to Loans</a>
            </p>
        </body>
        </html>
        """

    except Exception:
        conn.rollback()
        raise

    finally:
        if cursor is not None:
            cursor.close()
        conn.close()


@app.route("/disbursement_details/<int:loan_id>")
@login_required
def disbursement_details(loan_id):
    conn = get_connection()
    cursor = None

    try:
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                loans.loan_id,
                loans.loan_amount,
                loans.status,
                customers.name AS customer_name,
                loan_disbursements.disbursement_id,
                loan_disbursements.disbursement_amount,
                loan_disbursements.disbursement_date,
                loan_disbursements.payment_method,
                loan_disbursements.reference_number,
                loan_disbursements.notes,
                loan_disbursements.created_at

            FROM loans

            JOIN customers
                ON loans.customer_id = customers.customer_id

            LEFT JOIN loan_disbursements
                ON loans.loan_id = loan_disbursements.loan_id

            WHERE loans.loan_id = %s
            """,
            (loan_id,)
        )

        details = cursor.fetchone()

        if details is None:
            return "Loan not found.", 404

    finally:
        if cursor is not None:
            cursor.close()
        conn.close()

    if details["disbursement_id"] is None:
        return "No disbursement has been recorded for this loan."

    return render_template_string("""
        <h1>Loan Disbursement Details</h1>

        <p>Loan ID: {{ details.loan_id }}</p>

        <p>Customer: {{ details.customer_name }}</p>

        <p>Loan Status: {{ details.status }}</p>

        <p>
            Approved Loan Amount:
            ₹{{ details.loan_amount }}
        </p>

        <hr>

        <h2>Disbursement Information</h2>

        <p>
            Disbursement ID:
            {{ details.disbursement_id }}
        </p>

        <p>
            Disbursed Amount:
            ₹{{ details.disbursement_amount }}
        </p>

        <p>
            Disbursement Date:
            {{ details.disbursement_date }}
        </p>

        <p>
            Payment Method:
            {{ details.payment_method }}
        </p>

        <p>
            Reference Number:
            {{ details.reference_number or "-" }}
        </p>

        <p>
            Notes:
            {{ details.notes or "-" }}
        </p>

        <br>

        <a href="/loans">Back to Loans</a>
    """, details=details)

@app.route("/emi_details/<int:loan_id>")
@login_required
def emi_details(loan_id):
    conn = get_connection()
    cursor = None

    try:
        cursor = conn.cursor(dictionary=True)

        emi_status_filter = request.args.get(
            "status", ""
        ).strip()

        if emi_status_filter not in [
            "", "Due", "Paid", "Overdue"
        ]:
            emi_status_filter = ""

        cursor.execute(
            """
            SELECT *
            FROM loan_emis
            WHERE loan_id = %s
            ORDER BY emi_number
            """,
            (loan_id,)
        )

        emi_list = cursor.fetchall()

        today = date.today()

        for emi in emi_list:
            if emi["status"] == "Due":
                days, penalty = calculate_late_penalty(
                    emi["emi_amount"],
                    emi["emi_date"],
                    today
                )

                emi["overdue_days"] = days
                emi["display_status"] = (
                    "Overdue" if days > 0 else "Due"
                )
                emi["display_penalty"] = penalty

            else:
                emi["overdue_days"] = 0
                emi["display_status"] = "Paid"
                emi["display_penalty"] = emi["late_penalty"]

            emi["total_amount"] = (
                Decimal(str(emi["emi_amount"]))
                + Decimal(str(emi["display_penalty"]))
            )

        if emi_status_filter:
            emi_list = [
                emi for emi in emi_list
                if (
                    emi["display_status"] == emi_status_filter
                    or (
                        emi_status_filter == "Due"
                        and emi["status"] == "Due"
                    )
                )
            ]

    finally:
        if cursor is not None:
            cursor.close()
        conn.close()

    return render_template_string("""
        <h1>EMI Details</h1>

        <form method="get">
            <label>Filter by Status:</label>
            <select name="status">
                <option value="">All EMIs</option>
                <option value="Due">All Unpaid</option>
                <option value="Overdue">Overdue</option>
                <option value="Paid">Paid</option>
            </select>
            <button type="submit">Filter</button>
            <a href="{{ url_for('emi_details', loan_id=loan_id) }}">
                Clear Filter
            </a>
        </form>

        <br>

        <table border="1" cellpadding="10">
            <tr>
                <th>EMI No.</th>
                <th>Due Date</th>
                <th>Principal</th>
                <th>Interest</th>
                <th>EMI Amount</th>
                <th>Balance</th>
                <th>Status</th>
                <th>Overdue Days</th>
                <th>Penalty</th>
                <th>Total Amount</th>
                <th>Payment Date</th>
                <th>Action</th>
            </tr>

            {% for emi in emi_list %}
            <tr {% if emi.display_status == "Overdue" %}
                style="background-color:#ffe4e6;"
                {% endif %}>

                <td>{{ emi.emi_number }}</td>
                <td>{{ emi.emi_date }}</td>
                <td>₹{{ emi.principal_due }}</td>
                <td>₹{{ emi.interest_due }}</td>
                <td>₹{{ emi.emi_amount }}</td>
                <td>₹{{ emi.balance_amount }}</td>

                <td>
                    {% if emi.display_status == "Overdue" %}
                        <strong style="color:red;">Overdue</strong>
                    {% else %}
                        {{ emi.display_status }}
                    {% endif %}
                </td>

                <td>{{ emi.overdue_days }}</td>
                <td>₹{{ emi.display_penalty }}</td>
                <td>₹{{ emi.total_amount }}</td>
                <td>{{ emi.payment_date or "-" }}</td>

                <td>
                    {% if emi.status == "Due" %}
                        <form method="post"
                              action="{{ url_for('pay_emi', emi_id=emi.emi_id) }}"
                              onsubmit="return confirm('Record this EMI and its applicable penalty as paid?');">
                            <button type="submit">Pay EMI</button>
                        </form>
                    {% else %}
                        <a href="{{ url_for('emi_receipt', emi_id=emi.emi_id) }}">
                            View Receipt
                        </a>
                    {% endif %}
                </td>
            </tr>
            {% else %}
            <tr>
                <td colspan="12">No matching EMIs found.</td>
            </tr>
            {% endfor %}
        </table>

        <p><a href="/loans">Back to Loans</a></p>
    """, emi_list=emi_list, loan_id=loan_id)


@app.route("/pay_emi/<int:emi_id>", methods=["POST"])
@login_required
def pay_emi(emi_id):
    conn = get_connection()
    cursor = None

    try:
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT emi_id, loan_id, status,
                   emi_amount, emi_date
            FROM loan_emis
            WHERE emi_id = %s
            FOR UPDATE
            """,
            (emi_id,)
        )

        emi = cursor.fetchone()

        if emi is None:
            return "EMI not found.", 404

        if emi["status"] != "Due":
            return "This EMI is already paid.", 400

        loan_id = emi["loan_id"]

        overdue_days, penalty = calculate_late_penalty(
            emi["emi_amount"],
            emi["emi_date"]
        )

        cursor.execute(
            """
            UPDATE loan_emis
            SET status = 'Paid',
                payment_date = CURDATE(),
                late_penalty = %s
            WHERE emi_id = %s
            """,
            (penalty, emi_id)
        )

        cursor.execute(
            """
            SELECT COUNT(*) AS unpaid_count
            FROM loan_emis
            WHERE loan_id = %s
              AND status != 'Paid'
            """,
            (loan_id,)
        )

        result = cursor.fetchone()

        if result["unpaid_count"] == 0:
            cursor.execute(
                """
                UPDATE loans
                SET status = 'Paid'
                WHERE loan_id = %s
                """,
                (loan_id,)
            )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        if cursor is not None:
            cursor.close()
        conn.close()

    return redirect(
        url_for("emi_details", loan_id=loan_id)
    )



@app.route("/update_loan_status/<int:loan_id>", methods=["POST"])
@login_required
def update_loan_status(loan_id):
    new_status = request.form.get("status")

    conn = get_connection()
    cursor = None

    try:
        cursor = conn.cursor(dictionary=True)

        # Find the current status of this loan
        cursor.execute(
            "SELECT status FROM loans WHERE loan_id = %s",
            (loan_id,)
        )
        loan = cursor.fetchone()

        if loan is None:
            return "Loan not found.", 404

        current_status = loan["status"]

        # Define the allowed status changes
        allowed_transitions = {
            "Active": ["Approved", "Rejected"],
            "Approved": [],
            "Rejected": [],
            "Paid": []
        }

        if new_status not in allowed_transitions.get(current_status, []):
            return (
                f"Cannot change loan status from "
                f"{current_status} to {new_status}.",
                400
            )

        # Update the status only when the transition is allowed
        cursor.execute(
            "UPDATE loans SET status = %s WHERE loan_id = %s",
            (new_status, loan_id)
        )
        if new_status == "Approved":
            cursor.execute(
                """
                SELECT loan_amount, annual_interest_rate,
                    duration_months, loan_date
                FROM loans
                WHERE loan_id = %s
                """,
                (loan_id,)
            )

            loan_details = cursor.fetchone()

            if loan_details:
                cursor.execute(
                    "SELECT COUNT(*) AS total FROM loan_emis WHERE loan_id = %s",
                    (loan_id,)
                )
                existing_emis = cursor.fetchone()

                if existing_emis["total"] > 0:
                   return "EMI schedule already exists for this loan.", 400
                schedule = generate_emi_schedule(
                    float(loan_details["loan_amount"]),
                    float(loan_details["annual_interest_rate"]),
                    loan_details["duration_months"],
                    loan_details["loan_date"]
                )

                print("Generated EMI schedule:", schedule)
                
                for emi in schedule:
                    cursor.execute(
                        """
                        INSERT INTO loan_emis (
                            loan_id,
                            emi_number,
                            emi_date,
                            principal_due,
                            interest_due,
                            emi_amount,
                            balance_amount
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            loan_id,
                            emi["emi_number"],
                            emi["emi_date"],
                            emi["principal_due"],
                            emi["interest_due"],
                            emi["emi_amount"],
                            emi["balance_amount"]
                        )
                    )


        conn.commit()
    
    except Exception:
        conn.rollback()
        raise

    
    finally:
        if cursor is not None:
           cursor.close()
        conn.close()

    return redirect(url_for("loans"))


def add_months(original_date, months):
    month_index = original_date.month - 1 + months

    year = original_date.year + month_index // 12
    month = month_index % 12 + 1

    day = min(
        original_date.day,
        calendar.monthrange(year, month)[1]
    )

    return original_date.replace(
        year=year,
        month=month,
        day=day
    )



def generate_emi_schedule(loan_amount, annual_rate, months, loan_date):
    monthly_rate = annual_rate / 12 / 100
    emi = calculate_emi(loan_amount, annual_rate, months)

    balance = round(loan_amount, 2)
    schedule = []

    first_emi_date = add_months(loan_date, 1)
    
   

    for month in range(1, months + 1):
        interest = round(balance * monthly_rate, 2)
        principal = round(emi - interest, 2)

        # Adjust the final installment for rounding
        if month == months:
            principal = balance
            emi_amount = round(principal + interest, 2)
        else:
            emi_amount = emi

        balance = round(max(0, balance - principal), 2)

        schedule.append({
            "emi_number": month,
            "emi_date": add_months(loan_date, month),
            "principal_due": principal,
            "interest_due": interest,
            "emi_amount": emi_amount,
            "balance_amount": balance
        })

    return schedule

@app.route("/overdue_reports")
@login_required
def overdue_reports():
    conn = get_connection()
    cursor = None

    try:
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                customers.customer_id,
                customers.name AS customer_name,
                customers.phone,
                loans.loan_id,
                loan_emis.emi_id,
                loan_emis.emi_number,
                loan_emis.emi_date,
                loan_emis.emi_amount,
                DATEDIFF(
                    CURDATE(), loan_emis.emi_date
                ) AS overdue_days

            FROM loan_emis

            JOIN loans
                ON loan_emis.loan_id = loans.loan_id

            JOIN customers
                ON loans.customer_id = customers.customer_id

            WHERE loan_emis.status = 'Due'
              AND loan_emis.emi_date < CURDATE()

            ORDER BY loan_emis.emi_date ASC
            """
        )

        overdue_list = cursor.fetchall()

        total_emi_amount = Decimal("0.00")
        total_penalties = Decimal("0.00")

        for emi in overdue_list:
            days, penalty = calculate_late_penalty(
                emi["emi_amount"],
                emi["emi_date"]
            )

            emi["overdue_days"] = days
            emi["penalty"] = penalty

            emi["total_due"] = (
                Decimal(str(emi["emi_amount"]))
                + penalty
            )

            total_emi_amount += Decimal(
                str(emi["emi_amount"])
            )

            total_penalties += penalty

        grand_total = total_emi_amount + total_penalties

    finally:
        if cursor is not None:
            cursor.close()
        conn.close()

    return render_template_string("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Overdue EMI Report</title>

            <style>
                body {
                    font-family: Arial, sans-serif;
                    margin: 30px;
                }

                h1 {
                    color: #b91c1c;
                }

                table {
                    width: 100%;
                    border-collapse: collapse;
                }

                th, td {
                    padding: 10px;
                    border: 1px solid #ddd;
                    text-align: left;
                }

                th {
                    background: #183153;
                    color: white;
                }

                .overdue {
                    background: #ffe4e6;
                }
            </style>
        </head>

        <body>
            <h1>Overdue EMI Report</h1>

            <h2>Summary</h2>

            <p>Total Overdue EMIs: {{ overdue_list|length }}</p>

            <p>Outstanding EMI Amount: ₹{{ total_emi_amount }}</p>

            <p>Outstanding Penalties: ₹{{ total_penalties }}</p>

            <p>
                <strong>
                    Total Amount Due: ₹{{ grand_total }}
                </strong>
            </p>

            <hr>

            <h2>Overdue EMI Details</h2>

            <table>
                <tr>
                    <th>Customer ID</th>
                    <th>Customer</th>
                    <th>Phone</th>
                    <th>Loan ID</th>
                    <th>EMI No.</th>
                    <th>Due Date</th>
                    <th>Overdue Days</th>
                    <th>EMI Amount</th>
                    <th>Penalty</th>
                    <th>Total Due</th>
                    <th>Action</th>
                </tr>

                {% for emi in overdue_list %}
                <tr class="overdue">
                    <td>{{ emi.customer_id }}</td>
                    <td>{{ emi.customer_name }}</td>
                    <td>{{ emi.phone }}</td>
                    <td>{{ emi.loan_id }}</td>
                    <td>{{ emi.emi_number }}</td>
                    <td>{{ emi.emi_date }}</td>
                    <td>{{ emi.overdue_days }}</td>
                    <td>₹{{ emi.emi_amount }}</td>
                    <td>₹{{ emi.penalty }}</td>
                    <td>₹{{ emi.total_due }}</td>

                    <td>
                        <a href="{{ url_for('emi_details', loan_id=emi.loan_id) }}">
                            View EMI
                        </a>
                    </td>
                </tr>
                {% else %}
                <tr>
                    <td colspan="11">
                        No overdue EMIs found.
                    </td>
                </tr>
                {% endfor %}
            </table>

            <br>

            <a href="/dashboard">Dashboard</a> |
            <a href="/reports">Reports</a> |
            <a href="/">Home</a>

        </body>
        </html>
    """,
        overdue_list=overdue_list,
        total_emi_amount=total_emi_amount,
        total_penalties=total_penalties,
        grand_total=grand_total
    )

@app.route("/payment_history")
@login_required
def payment_history():
    conn = get_connection()
    cursor = None

    try:
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                e.emi_id,
                e.loan_id,
                e.emi_number,
                e.emi_date,
                e.emi_amount,
                e.late_penalty,
                e.payment_date,
                c.customer_id,
                c.name AS customer_name,
                c.phone
            FROM loan_emis e
            JOIN loans l ON e.loan_id = l.loan_id
            JOIN customers c ON l.customer_id = c.customer_id
            WHERE e.status = 'Paid'
            ORDER BY e.payment_date DESC, e.emi_id DESC
        """)

        payments = cursor.fetchall()

        for payment in payments:
            payment["total_paid"] = (
                Decimal(str(payment["emi_amount"]))
                + Decimal(str(payment["late_penalty"]))
            )

    finally:
        if cursor is not None:
            cursor.close()
        conn.close()

    return render_template_string("""
        <h1>EMI Payment History</h1>

        <table border="1" cellpadding="10">
            <tr>
                <th>Receipt No.</th>
                <th>Customer</th>
                <th>Loan ID</th>
                <th>EMI No.</th>
                <th>Payment Date</th>
                <th>EMI Amount</th>
                <th>Late Penalty</th>
                <th>Total Recorded</th>
                <th>Receipt</th>
            </tr>

            {% for p in payments %}
            <tr>
                <td>EMI-{{ p.emi_id }}</td>
                <td>{{ p.customer_name }}</td>
                <td>{{ p.loan_id }}</td>
                <td>{{ p.emi_number }}</td>
                <td>{{ p.payment_date }}</td>
                <td>₹{{ p.emi_amount }}</td>
                <td>₹{{ p.late_penalty }}</td>
                <td>₹{{ p.total_paid }}</td>
                <td>
                    <a href="{{ url_for('emi_receipt', emi_id=p.emi_id) }}">
                        View Receipt
                    </a>
                </td>
            </tr>
            {% else %}
            <tr>
                <td colspan="9">No EMI payments recorded yet.</td>
            </tr>
            {% endfor %}
        </table>

        <p><a href="/">Back to Home</a></p>
    """, payments=payments)

@app.route("/emi_receipt/<int:emi_id>")
@login_required
def emi_receipt(emi_id):
    conn = get_connection()
    cursor = None

    try:
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                e.emi_id,
                e.loan_id,
                e.emi_number,
                e.emi_date,
                e.emi_amount,
                e.late_penalty,
                e.payment_date,
                e.status,
                c.customer_id,
                c.name AS customer_name,
                c.phone,
                l.loan_amount
            FROM loan_emis e
            JOIN loans l ON e.loan_id = l.loan_id
            JOIN customers c ON l.customer_id = c.customer_id
            WHERE e.emi_id = %s
        """, (emi_id,))

        payment = cursor.fetchone()

        if payment is None:
            return "EMI not found.", 404

        if payment["status"] != "Paid":
            return "Receipt is available only for paid EMIs.", 400

        payment["total_paid"] = (
            Decimal(str(payment["emi_amount"]))
            + Decimal(str(payment["late_penalty"]))
        )

    finally:
        if cursor is not None:
            cursor.close()
        conn.close()

    return render_template_string("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>EMI Receipt {{ payment.emi_id }}</title>

            <style>
                body {
                    font-family: Arial, sans-serif;
                    margin: 40px;
                    color: #243047;
                }

                .receipt {
                    max-width: 650px;
                    margin: auto;
                    border: 1px solid #ddd;
                    padding: 30px;
                    border-radius: 10px;
                }

                h1 {
                    text-align: center;
                    color: #183153;
                }

                .total {
                    font-size: 20px;
                    font-weight: bold;
                    border-top: 2px solid #183153;
                    padding-top: 15px;
                }

                .actions {
                    text-align: center;
                    margin-top: 25px;
                }

                @media print {
                    .actions {
                        display: none;
                    }

                    .receipt {
                        border: none;
                    }
                }
            </style>
        </head>

        <body>
            <div class="receipt">
                <h1>EMI Payment Receipt</h1>

                <p><strong>Receipt No:</strong> EMI-{{ payment.emi_id }}</p>
                <p><strong>Payment Date:</strong> {{ payment.payment_date }}</p>

                <hr>

                <h3>Customer Details</h3>

                <p><strong>Customer:</strong> {{ payment.customer_name }}</p>
                <p><strong>Customer ID:</strong> {{ payment.customer_id }}</p>
                <p><strong>Phone:</strong> {{ payment.phone }}</p>

                <hr>

                <h3>Loan & EMI Details</h3>

                <p><strong>Loan ID:</strong> {{ payment.loan_id }}</p>
                <p><strong>Loan Amount:</strong> ₹{{ payment.loan_amount }}</p>
                <p><strong>EMI Number:</strong> {{ payment.emi_number }}</p>
                <p><strong>EMI Due Date:</strong> {{ payment.emi_date }}</p>

                <hr>

                <h3>Payment Breakdown</h3>

                <p>EMI Amount: ₹{{ payment.emi_amount }}</p>
                <p>Late Penalty: ₹{{ payment.late_penalty }}</p>

                <p class="total">
                    Total Recorded Payment: ₹{{ payment.total_paid }}
                </p>

                <p><strong>Status:</strong> Paid</p>

                <div class="actions">
                    <button onclick="window.print()">
                        Print / Save as PDF
                    </button>

                    <p>
                        <a href="/payment_history">
                            Back to Payment History
                        </a>
                    </p>
                </div>
            </div>
        </body>
        </html>
    """, payment=payment)

@app.route("/close_loan/<int:loan_id>", methods=["GET", "POST"])
@login_required
def close_loan(loan_id):
    conn = get_connection()
    cursor = None

    try:
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                l.loan_id,
                l.status,
                l.loan_amount,
                c.name AS customer_name,
                c.customer_id
            FROM loans l
            JOIN customers c
                ON l.customer_id = c.customer_id
            WHERE l.loan_id = %s
        """, (loan_id,))

        loan = cursor.fetchone()

        if loan is None:
            return "Loan not found.", 404

        cursor.execute("""
            SELECT
                COUNT(*) AS total_emis,
                COALESCE(SUM(
                    CASE WHEN status != 'Paid'
                    THEN 1 ELSE 0 END
                ), 0) AS unpaid_emis
            FROM loan_emis
            WHERE loan_id = %s
        """, (loan_id,))

        summary = cursor.fetchone()

        if (
            loan["status"] != "Paid"
            or summary["total_emis"] == 0
            or summary["unpaid_emis"] > 0
        ):
            return "Loan cannot be closed until all EMIs are paid.", 400

        cursor.execute("""
            SELECT closure_id, closure_date
            FROM loan_closures
            WHERE loan_id = %s
        """, (loan_id,))

        closure = cursor.fetchone()

        if request.method == "POST":
            if closure is None:
                cursor.execute("""
                    INSERT INTO loan_closures
                        (loan_id, closure_date)
                    VALUES (%s, CURDATE())
                """, (loan_id,))

                conn.commit()

            return redirect(
                url_for("no_dues_certificate", loan_id=loan_id)
            )

    finally:
        if cursor is not None:
            cursor.close()
        conn.close()

    return render_template_string("""
        <h1>Loan Closure</h1>

        <p><strong>Loan ID:</strong> {{ loan.loan_id }}</p>
        <p><strong>Customer:</strong> {{ loan.customer_name }}</p>
        <p><strong>Loan Amount:</strong> ₹{{ loan.loan_amount }}</p>
        <p><strong>Loan Status:</strong> {{ loan.status }}</p>

        {% if closure %}
            <p style="color:green;">
                This loan was formally closed on
                {{ closure.closure_date }}.
            </p>

            <a href="{{ url_for('no_dues_certificate', loan_id=loan.loan_id) }}">
                View No-Dues Certificate
            </a>
        {% else %}
            <p>All scheduled EMIs have been marked as paid.</p>

            <form method="post">
                <button type="submit">
                    Confirm Loan Closure
                </button>
            </form>
        {% endif %}

        <p><a href="/loans">Back to Loans</a></p>
    """, loan=loan, closure=closure)

@app.route("/no_dues_certificate/<int:loan_id>")
@login_required
def no_dues_certificate(loan_id):
    conn = get_connection()
    cursor = None

    try:
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                lc.closure_id,
                lc.closure_date,
                l.loan_id,
                l.loan_amount,
                l.loan_date,
                l.status,
                c.customer_id,
                c.name AS customer_name
            FROM loan_closures lc
            JOIN loans l ON lc.loan_id = l.loan_id
            JOIN customers c ON l.customer_id = c.customer_id
            WHERE lc.loan_id = %s
              AND l.status = 'Paid'
              AND NOT EXISTS (
                  SELECT 1
                  FROM loan_emis e
                  WHERE e.loan_id = l.loan_id
                    AND e.status != 'Paid'
              )
        """, (loan_id,))

        details = cursor.fetchone()

        if details is None:
            return "No closed loan certificate found.", 404

    finally:
        if cursor is not None:
            cursor.close()
        conn.close()

    return render_template_string("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>No-Dues Certificate</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    margin: 40px;
                    color: #243047;
                }

                .certificate {
                    max-width: 750px;
                    margin: auto;
                    padding: 45px;
                    border: 2px solid #183153;
                    line-height: 1.8;
                }

                h1 {
                    text-align: center;
                    color: #183153;
                }

                .signature {
                    margin-top: 70px;
                }

                .actions {
                    text-align: center;
                    margin-top: 25px;
                }

                @media print {
                    .actions {
                        display: none;
                    }

                    .certificate {
                        border: 2px solid #183153;
                    }
                }
            </style>
        </head>

        <body>
            <div class="certificate">

                <h1>NO-DUES CERTIFICATE</h1>

                <p><strong>Certificate No:</strong>
                    NDC-{{ details.closure_id }}
                </p>

                <p><strong>Closure Date:</strong>
                    {{ details.closure_date }}
                </p>

                <hr>

                <p>To Whom It May Concern,</p>

                <p>
                    This is to certify that
                    <strong>{{ details.customer_name }}</strong>,
                    Customer ID {{ details.customer_id }},
                    has completed all scheduled EMI payments
                    associated with Loan ID
                    <strong>{{ details.loan_id }}</strong>.
                </p>

                <p>
                    The original loan amount was
                    <strong>₹{{ details.loan_amount }}</strong>,
                    with a loan date of
                    {{ details.loan_date }}.
                </p>

                <p>
                    According to the payment records maintained
                    in this Loan Management System, all scheduled
                    EMIs have been marked as paid and the loan
                    has been formally closed.
                </p>

                <p>
                    This certificate is issued on the basis of
                    the records available in the system.
                </p>

                <div class="signature">
                    <p>________________________</p>
                    <p>Authorized Signatory</p>
                </div>

            </div>

            <div class="actions">
                <button onclick="window.print()">
                    Print / Save as PDF
                </button>

                <p>
                    <a href="/closed_loans">
                        Back to Closed Loans
                    </a>
                </p>
            </div>
        </body>
        </html>
    """, details=details)
@app.route("/closed_loans")
@login_required
def closed_loans():
    conn = get_connection()
    cursor = None

    try:
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                lc.closure_id,
                lc.closure_date,
                l.loan_id,
                l.loan_amount,
                c.name AS customer_name
            FROM loan_closures lc
            JOIN loans l ON lc.loan_id = l.loan_id
            JOIN customers c ON l.customer_id = c.customer_id
            ORDER BY lc.closure_date DESC, lc.closure_id DESC
        """)

        closed_loan_list = cursor.fetchall()

    finally:
        if cursor is not None:
            cursor.close()
        conn.close()

    return render_template_string("""
        <h1>Closed Loans History</h1>

        <table border="1" cellpadding="10">
            <tr>
                <th>Closure ID</th>
                <th>Loan ID</th>
                <th>Customer</th>
                <th>Loan Amount</th>
                <th>Closure Date</th>
                <th>Certificate</th>
            </tr>

            {% for loan in closed_loan_list %}
            <tr>
                <td>{{ loan.closure_id }}</td>
                <td>{{ loan.loan_id }}</td>
                <td>{{ loan.customer_name }}</td>
                <td>₹{{ loan.loan_amount }}</td>
                <td>{{ loan.closure_date }}</td>
                <td>
                    <a href="{{ url_for('no_dues_certificate', loan_id=loan.loan_id) }}">
                        View Certificate
                    </a>
                </td>
            </tr>
            {% else %}
            <tr>
                <td colspan="6">No loans have been closed yet.</td>
            </tr>
            {% endfor %}
        </table>

        <p><a href="/">Back to Home</a></p>
    """, closed_loan_list=closed_loan_list)




if __name__ == "__main__":
    app.run(debug=True, port=5001)
