"""
WhatsApp Expense Tracker for Partnership Firms
A simple bookkeeping assistant that receives expenses via WhatsApp
and categorizes them for easy auditing.
"""

from flask import Flask, request, render_template, send_file, jsonify
from twilio.twiml.messaging_response import MessagingResponse
from datetime import datetime
import sqlite3
import csv
import io
import re
import os

app = Flask(__name__)

# Database setup
DATABASE = 'expenses.db'

def get_db():
    """Get database connection."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize the database with required tables."""
    conn = get_db()
    cursor = conn.cursor()
    
    # Create expenses table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            description TEXT,
            partner_name TEXT,
            partner_phone TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            raw_message TEXT
        )
    ''')
    
    # Create partners table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS partners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

# Initialize database on startup
init_db()

# Category keywords mapping
CATEGORY_KEYWORDS = {
    'rent': ['rent', 'rental', 'office rent', 'shop rent', 'lease'],
    'travel': ['travel', 'auto', 'cab', 'uber', 'ola', 'fuel', 'petrol', 'diesel', 'ticket', 'train', 'bus', 'flight', 'metro'],
    'food': ['food', 'lunch', 'dinner', 'breakfast', 'tea', 'coffee', 'snacks', 'meal', 'restaurant', 'hotel', 'eating'],
    'partner_loan': ['loan', 'lent', 'lending', 'borrowed', 'gave to company', 'lent to company', 'partner loan', 'personal money'],
    'business_purchase': ['stock', 'inventory', 'purchase', 'bought', 'product', 'goods', 'material', 'supplies', 'wholesale'],
    'client_acquisition': ['client', 'customer', 'acquisition', 'gift', 'meeting', 'commission', 'marketing', 'promotion', 'business development']
}

def extract_amount(message):
    """Extract amount from message."""
    # Look for patterns like: 5000, 5,000, Rs.5000, ₹5000, INR 5000
    patterns = [
        r'₹\s*([\d,]+(?:\.\d{2})?)',
        r'rs\.?\s*([\d,]+(?:\.\d{2})?)',
        r'inr\s*([\d,]+(?:\.\d{2})?)',
        r'([\d,]+(?:\.\d{2})?)\s*(?:rs|rupees|inr|₹)',
        r'\b([\d,]+(?:\.\d{2})?)\b'
    ]
    
    message_lower = message.lower()
    
    for pattern in patterns:
        match = re.search(pattern, message_lower)
        if match:
            amount_str = match.group(1).replace(',', '')
            try:
                return float(amount_str)
            except ValueError:
                continue
    
    return None

def detect_category(message):
    """Detect category from message keywords."""
    message_lower = message.lower()
    
    # Check each category's keywords
    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in message_lower:
                return category
    
    return 'uncategorized'

def format_category(category):
    """Format category name for display."""
    return category.replace('_', ' ').title()

def get_partner_name(phone):
    """Get partner name from phone number."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT name FROM partners WHERE phone = ?', (phone,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return result['name']
    return None

def register_partner(phone, name):
    """Register a new partner."""
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT OR REPLACE INTO partners (phone, name) VALUES (?, ?)', (phone, name))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error registering partner: {e}")
        return False
    finally:
        conn.close()

def save_expense(amount, category, description, partner_name, partner_phone, raw_message):
    """Save expense to database."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO expenses (amount, category, description, partner_name, partner_phone, raw_message)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (amount, category, description, partner_name, partner_phone, raw_message))
    conn.commit()
    expense_id = cursor.lastrowid
    conn.close()
    return expense_id

def parse_expense_message(message, phone):
    """Parse incoming message and extract expense details."""
    message = message.strip()
    
    # Check if it's a registration message
    if message.lower().startswith('register'):
        # Format: register John
        parts = message.split(maxsplit=1)
        if len(parts) > 1:
            name = parts[1].strip()
            if register_partner(phone, name):
                return {
                    'type': 'registration',
                    'success': True,
                    'name': name
                }
        return {
            'type': 'registration',
            'success': False
        }
    
    # Check if partner is registered
    partner_name = get_partner_name(phone)
    if not partner_name:
        return {
            'type': 'unregistered'
        }
    
    # Parse expense
    amount = extract_amount(message)
    if amount is None:
        return {
            'type': 'error',
            'message': 'Could not find amount in your message.'
        }
    
    category = detect_category(message)
    
    return {
        'type': 'expense',
        'amount': amount,
        'category': category,
        'description': message,
        'partner_name': partner_name
    }

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming WhatsApp messages."""
    incoming_msg = request.values.get('Body', '').strip()
    sender = request.values.get('From', '')
    
    # Clean phone number
    phone = sender.replace('whatsapp:', '')
    
    resp = MessagingResponse()
    msg = resp.message()
    
    # Parse the message
    result = parse_expense_message(incoming_msg, phone)
    
    if result['type'] == 'registration':
        if result['success']:
            msg.body(f"✓ Welcome {result['name']}! You're now registered.\n\nYou can start logging expenses by sending messages like:\n• Paid 5000 rent\n• Travel 300 auto\n• Bought stock 15000\n• Lent 20000 to company\n• Client gift 1000")
        else:
            msg.body("Please register with your name.\nFormat: register YourName")
    
    elif result['type'] == 'unregistered':
        msg.body("👋 Welcome to Expense Tracker!\n\nPlease register first by sending:\nregister YourName\n\nExample: register Rahul")
    
    elif result['type'] == 'error':
        msg.body(f"❌ {result['message']}\n\nPlease include an amount in your message.\nExample: Paid 5000 for rent")
    
    elif result['type'] == 'expense':
        # Save the expense
        expense_id = save_expense(
            amount=result['amount'],
            category=result['category'],
            description=result['description'],
            partner_name=result['partner_name'],
            partner_phone=phone,
            raw_message=incoming_msg
        )
        
        category_display = format_category(result['category'])
        msg.body(f"✓ Recorded #{expense_id}\n₹{result['amount']:,.2f} - {category_display}\nBy: {result['partner_name']}")
    
    return str(resp)

@app.route('/')
def dashboard():
    """Display expense dashboard."""
    conn = get_db()
    cursor = conn.cursor()
    
    # Get all expenses
    cursor.execute('''
        SELECT * FROM expenses 
        ORDER BY created_at DESC 
        LIMIT 100
    ''')
    expenses = cursor.fetchall()
    
    # Get category totals
    cursor.execute('''
        SELECT category, SUM(amount) as total 
        FROM expenses 
        GROUP BY category
    ''')
    category_totals = cursor.fetchall()
    
    # Get total
    cursor.execute('SELECT SUM(amount) as total FROM expenses')
    total = cursor.fetchone()['total'] or 0
    
    # Get partner totals
    cursor.execute('''
        SELECT partner_name, SUM(amount) as total 
        FROM expenses 
        GROUP BY partner_name
    ''')
    partner_totals = cursor.fetchall()
    
    conn.close()
    
    return render_template('dashboard.html', 
                         expenses=expenses, 
                         category_totals=category_totals,
                         partner_totals=partner_totals,
                         total=total,
                         format_category=format_category)

@app.route('/export')
def export_csv():
    """Export expenses to CSV."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM expenses ORDER BY created_at DESC')
    expenses = cursor.fetchall()
    conn.close()
    
    # Create CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow(['ID', 'Date', 'Amount', 'Category', 'Description', 'Partner', 'Phone'])
    
    # Data
    for expense in expenses:
        writer.writerow([
            expense['id'],
            expense['created_at'],
            expense['amount'],
            format_category(expense['category']),
            expense['description'],
            expense['partner_name'],
            expense['partner_phone']
        ])
    
    # Prepare response
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'expenses_{datetime.now().strftime("%Y%m%d")}.csv'
    )

@app.route('/api/expenses')
def api_expenses():
    """API endpoint to get expenses."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM expenses ORDER BY created_at DESC')
    expenses = cursor.fetchall()
    conn.close()
    
    return jsonify([dict(expense) for expense in expenses])

@app.route('/api/summary')
def api_summary():
    """API endpoint to get expense summary."""
    conn = get_db()
    cursor = conn.cursor()
    
    # Get category totals
    cursor.execute('''
        SELECT category, SUM(amount) as total, COUNT(*) as count
        FROM expenses 
        GROUP BY category
    ''')
    categories = cursor.fetchall()
    
    # Get total
    cursor.execute('SELECT SUM(amount) as total, COUNT(*) as count FROM expenses')
    overall = cursor.fetchone()
    
    conn.close()
    
    return jsonify({
        'total_amount': overall['total'] or 0,
        'total_count': overall['count'] or 0,
        'by_category': [dict(cat) for cat in categories]
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
