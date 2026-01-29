from flask import Flask, request, render_template_string, send_file
from twilio.twiml.messaging_response import MessagingResponse
from datetime import datetime
import sqlite3
import csv
import io
import re
import os

app = Flask(__name__)
DATABASE = 'expenses.db'

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        amount REAL NOT NULL,
        category TEXT NOT NULL,
        description TEXT,
        partner_name TEXT,
        partner_phone TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS partners (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT UNIQUE NOT NULL
    )''')
    conn.commit()
    conn.close()

init_db()

CATEGORIES = {
    'rent': ['rent', 'rental', 'office rent', 'shop rent', 'lease'],
    'travel': ['travel', 'auto', 'cab', 'uber', 'ola', 'fuel', 'petrol', 'diesel', 'ticket', 'train', 'bus', 'flight', 'metro'],
    'food': ['food', 'lunch', 'dinner', 'breakfast', 'tea', 'coffee', 'snacks', 'meal', 'restaurant', 'hotel', 'eating', 'tiffin'],
    'partner_loan': ['loan', 'lent', 'lending', 'borrowed', 'gave to company', 'lent to company', 'partner loan', 'personal money'],
    'business_purchase': ['stock', 'inventory', 'purchase', 'bought', 'product', 'goods', 'material', 'supplies', 'wholesale'],
    'client_acquisition': ['client', 'customer', 'acquisition', 'gift', 'meeting', 'commission', 'marketing', 'promotion', 'business development']
}

def extract_amount(msg):
    patterns = [
        r'₹\s*([\d,]+(?:\.\d{2})?)',
        r'rs\.?\s*([\d,]+(?:\.\d{2})?)',
        r'inr\s*([\d,]+(?:\.\d{2})?)',
        r'([\d,]+(?:\.\d{2})?)\s*(?:rs|rupees|inr|₹)',
        r'\b([\d,]+)\b'
    ]
    for p in patterns:
        m = re.search(p, msg.lower())
        if m:
            try:
                return float(m.group(1).replace(',', ''))
            except:
                continue
    return None

def detect_category(msg):
    msg = msg.lower()
    for cat, keywords in CATEGORIES.items():
        for kw in keywords:
            if kw in msg:
                return cat
    return 'uncategorized'

def format_cat(cat):
    return cat.replace('_', ' ').title()

def get_partner(phone):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT name FROM partners WHERE phone=?', (phone,))
    r = c.fetchone()
    conn.close()
    return r['name'] if r else None

def register_partner(phone, name):
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute('INSERT OR REPLACE INTO partners (phone, name) VALUES (?, ?)', (phone, name))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

def save_expense(amount, category, description, partner_name, partner_phone):
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO expenses (amount, category, description, partner_name, partner_phone) VALUES (?, ?, ?, ?, ?)',
              (amount, category, description, partner_name, partner_phone))
    conn.commit()
    eid = c.lastrowid
    conn.close()
    return eid

@app.route('/webhook', methods=['POST'])
def webhook():
    msg = request.values.get('Body', '').strip()
    sender = request.values.get('From', '').replace('whatsapp:', '')
    
    resp = MessagingResponse()
    reply = resp.message()
    
    # Registration
    if msg.lower().startswith('register'):
        parts = msg.split(maxsplit=1)
        if len(parts) > 1:
            name = parts[1].strip()
            if register_partner(sender, name):
                reply.body(f"✅ Welcome {name}! You are registered.\n\nNow send expenses like:\n• Paid 5000 rent\n• Auto 200\n• Lunch 300\n• Lent 10000 to company\n• Bought stock 5000\n• Client gift 1000")
            else:
                reply.body("❌ Registration failed. Try again.")
        else:
            reply.body("Please send: register YourName")
        return str(resp)
    
    # Check if registered
    partner = get_partner(sender)
    if not partner:
        reply.body("👋 Welcome! Please register first:\n\nSend: register YourName\n\nExample: register Rahul")
        return str(resp)
    
    # Parse expense
    amount = extract_amount(msg)
    if not amount:
        reply.body("❌ Could not find amount.\n\nPlease include a number like:\n• Paid 500 rent\n• Travel 200")
        return str(resp)
    
    category = detect_category(msg)
    eid = save_expense(amount, category, msg, partner, sender)
    
    reply.body(f"✅ Recorded #{eid}\n₹{amount:,.0f} - {format_cat(category)}\nBy: {partner}")
    return str(resp)

DASHBOARD_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Expense Tracker</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f0f2f5; color: #333; }
        .container { max-width: 1000px; margin: 0 auto; padding: 20px; }
        header { background: linear-gradient(135deg, #25D366, #128C7E); color: white; padding: 25px; border-radius: 12px; margin-bottom: 25px; }
        header h1 { font-size: 26px; margin-bottom: 5px; }
        header p { opacity: 0.9; }
        .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin-bottom: 25px; }
        .card { background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
        .card h3 { font-size: 12px; color: #888; text-transform: uppercase; margin-bottom: 8px; }
        .card .val { font-size: 24px; font-weight: 700; color: #25D366; }
        .section { background: white; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); margin-bottom: 20px; overflow: hidden; }
        .section-head { padding: 18px 20px; border-bottom: 1px solid #eee; display: flex; justify-content: space-between; align-items: center; }
        .section-head h2 { font-size: 18px; }
        .btn { padding: 10px 18px; background: #25D366; color: white; text-decoration: none; border-radius: 6px; font-size: 14px; }
        .btn:hover { background: #1da851; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 14px 18px; text-align: left; border-bottom: 1px solid #f0f0f0; }
        th { background: #f9f9f9; font-size: 12px; text-transform: uppercase; color: #666; }
        .badge { display: inline-block; padding: 4px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; }
        .badge-rent { background: #e3f2fd; color: #1565c0; }
        .badge-travel { background: #f3e5f5; color: #7b1fa2; }
        .badge-food { background: #fff3e0; color: #ef6c00; }
        .badge-partner_loan { background: #e8f5e9; color: #2e7d32; }
        .badge-business_purchase { background: #fce4ec; color: #c2185b; }
        .badge-client_acquisition { background: #e0f7fa; color: #00838f; }
        .badge-uncategorized { background: #eee; color: #666; }
        .empty { padding: 50px; text-align: center; color: #999; }
        .amount { font-weight: 600; }
        @media (max-width: 600px) { th, td { padding: 10px 12px; font-size: 13px; } }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📊 Expense Tracker</h1>
            <p>WhatsApp-based bookkeeping for your partnership firm</p>
        </header>
        
        <div class="cards">
            <div class="card">
                <h3>Total Expenses</h3>
                <div class="val">₹{{ "{:,.0f}".format(total) }}</div>
            </div>
            {% for item in by_category %}
            <div class="card">
                <h3>{{ item.name }}</h3>
                <div class="val">₹{{ "{:,.0f}".format(item.total) }}</div>
            </div>
            {% endfor %}
        </div>
        
        <div class="section">
            <div class="section-head">
                <h2>Recent Expenses</h2>
                <a href="/export" class="btn">📥 Export CSV</a>
            </div>
            {% if expenses %}
            <table>
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Amount</th>
                        <th>Category</th>
                        <th>Description</th>
                        <th>Partner</th>
                    </tr>
                </thead>
                <tbody>
                    {% for e in expenses %}
                    <tr>
                        <td>{{ e.date }}</td>
                        <td class="amount">₹{{ "{:,.0f}".format(e.amount) }}</td>
                        <td><span class="badge badge-{{ e.category }}">{{ e.cat_name }}</span></td>
                        <td>{{ e.description }}</td>
                        <td>{{ e.partner }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <div class="empty">
                <p>No expenses recorded yet.</p>
                <p>Send a WhatsApp message to start tracking!</p>
            </div>
            {% endif %}
        </div>
    </div>
</body>
</html>
'''

@app.route('/')
def dashboard():
    conn = get_db()
    c = conn.cursor()
    
    # Get expenses
    c.execute('SELECT * FROM expenses ORDER BY created_at DESC LIMIT 100')
    rows = c.fetchall()
    expenses = []
    for r in rows:
        expenses.append({
            'date': r['created_at'][:16] if r['created_at'] else '',
            'amount': r['amount'],
            'category': r['category'],
            'cat_name': format_cat(r['category']),
            'description': r['description'] or '',
            'partner': r['partner_name'] or 'Unknown'
        })
    
    # Get totals by category
    c.execute('SELECT category, SUM(amount) as total FROM expenses GROUP BY category')
    cat_rows = c.fetchall()
    by_category = [{'name': format_cat(r['category']), 'total': r['total']} for r in cat_rows]
    
    # Get total
    c.execute('SELECT SUM(amount) as total FROM expenses')
    total_row = c.fetchone()
    total = total_row['total'] if total_row['total'] else 0
    
    conn.close()
    
    return render_template_string(DASHBOARD_HTML, expenses=expenses, by_category=by_category, total=total)

@app.route('/export')
def export():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM expenses ORDER BY created_at DESC')
    rows = c.fetchall()
    conn.close()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Date', 'Amount', 'Category', 'Description', 'Partner', 'Phone'])
    for r in rows:
        writer.writerow([r['id'], r['created_at'], r['amount'], format_cat(r['category']), r['description'], r['partner_name'], r['partner_phone']])
    
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'expenses_{datetime.now().strftime("%Y%m%d")}.csv'
    )

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
