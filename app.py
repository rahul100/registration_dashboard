"""
Vahan EV Data Visualization Web App
Select maker and column to view daily registration trends.
Uses SQLite database with calculated daily values.
"""

import os
import sqlite3
import secrets
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, jsonify, request, session, redirect, url_for

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'))
app.secret_key = secrets.token_hex(32)

DB_PATH = os.path.join(BASE_DIR, "vahan_data.db")

# Admin credentials (in production, use hashed passwords and env variables)
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

# Active sessions tracker: {session_id: {user_type, ip, user_agent, started, last_activity, pages_viewed}}
active_sessions = {}


def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def track_session():
    """Track user session activity"""
    if 'session_id' not in session:
        session['session_id'] = secrets.token_hex(16)
        session['user_type'] = 'user'
        session['started'] = datetime.now().isoformat()

    sid = session['session_id']
    now = datetime.now().isoformat()

    if sid not in active_sessions:
        active_sessions[sid] = {
            'user_type': session.get('user_type', 'user'),
            'ip': request.remote_addr,
            'user_agent': request.headers.get('User-Agent', '')[:100],
            'started': session.get('started', now),
            'last_activity': now,
            'pages_viewed': 0
        }

    active_sessions[sid]['last_activity'] = now
    active_sessions[sid]['pages_viewed'] += 1
    active_sessions[sid]['user_type'] = session.get('user_type', 'user')


def cleanup_stale_sessions(timeout_minutes=30):
    """Remove sessions inactive for more than timeout_minutes"""
    now = datetime.now()
    stale = []
    for sid, data in active_sessions.items():
        last = datetime.fromisoformat(data['last_activity'])
        if (now - last).total_seconds() > timeout_minutes * 60:
            stale.append(sid)
    for sid in stale:
        del active_sessions[sid]


def admin_required(f):
    """Decorator to require admin login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('user_type') != 'admin':
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/')
def index():
    track_session()
    return render_template('index.html')


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Admin login page"""
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['user_type'] = 'admin'
            session['admin_logged_in'] = True
            if 'session_id' in session:
                sid = session['session_id']
                if sid in active_sessions:
                    active_sessions[sid]['user_type'] = 'admin'
            return redirect(url_for('admin_dashboard'))
        else:
            error = 'Invalid username or password'

    return render_template('admin_login.html', error=error)


@app.route('/admin/logout')
def admin_logout():
    """Admin logout"""
    session['user_type'] = 'user'
    session.pop('admin_logged_in', None)
    if 'session_id' in session:
        sid = session['session_id']
        if sid in active_sessions:
            active_sessions[sid]['user_type'] = 'user'
    return redirect(url_for('index'))


@app.route('/admin')
@admin_required
def admin_dashboard():
    """Admin dashboard showing active sessions"""
    track_session()
    cleanup_stale_sessions()
    return render_template('admin_dashboard.html')


@app.route('/api/admin/sessions')
@admin_required
def api_admin_sessions():
    """API endpoint to get active sessions"""
    cleanup_stale_sessions()

    sessions_list = []
    for sid, data in active_sessions.items():
        sessions_list.append({
            'session_id': sid[:8] + '...',  # Truncate for display
            'user_type': data['user_type'],
            'ip': data['ip'],
            'user_agent': data['user_agent'],
            'started': data['started'],
            'last_activity': data['last_activity'],
            'pages_viewed': data['pages_viewed']
        })

    # Sort by last activity (most recent first)
    sessions_list.sort(key=lambda x: x['last_activity'], reverse=True)

    return jsonify({
        'total_sessions': len(sessions_list),
        'admin_sessions': sum(1 for s in sessions_list if s['user_type'] == 'admin'),
        'user_sessions': sum(1 for s in sessions_list if s['user_type'] == 'user'),
        'sessions': sessions_list
    })


@app.route('/api/makers')
def api_makers():
    conn = get_db()
    cursor = conn.cursor()

    # Get makers sorted by total EV registrations
    cursor.execute('''
        SELECT maker, SUM(daily_value) as total
        FROM daily_registrations
        WHERE metric = 'EV_Total'
        GROUP BY maker
        ORDER BY total DESC
    ''')

    makers = [row['maker'] for row in cursor.fetchall()]
    conn.close()
    return jsonify(makers)


@app.route('/api/columns')
def api_columns():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('SELECT DISTINCT metric FROM daily_registrations ORDER BY metric')
    columns = [row['metric'] for row in cursor.fetchall()]
    conn.close()

    # Put EV_Total first
    if 'EV_Total' in columns:
        columns.remove('EV_Total')
        columns.insert(0, 'EV_Total')

    return jsonify(columns)


@app.route('/api/vehicle-classes')
def api_vehicle_classes():
    """Get distinct vehicle classes sorted by total registrations"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT vehicle_class, SUM(registrations) as total
        FROM maker_vehicle_class
        GROUP BY vehicle_class
        ORDER BY total DESC
    ''')
    classes = [row['vehicle_class'] for row in cursor.fetchall()]
    conn.close()
    return jsonify(classes)


@app.route('/api/growth')
def api_growth():
    maker = request.args.get('maker', '')
    column = request.args.get('column', 'EV_Total')

    if not maker:
        return jsonify({'error': 'Maker is required'}), 400

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT date, daily_value, cumulative_value
        FROM daily_registrations
        WHERE maker = ? AND metric = ?
        ORDER BY date DESC
        LIMIT 60
    ''', (maker, column))

    rows = cursor.fetchall()
    conn.close()

    if len(rows) < 2:
        return jsonify({'error': 'Insufficient data'}), 400

    today = rows[0]
    yesterday = rows[1] if len(rows) > 1 else None
    week_ago = rows[7] if len(rows) > 7 else None
    month_ago = rows[30] if len(rows) > 30 else None

    def calc_growth(current, previous):
        if not previous or not previous['daily_value'] or previous['daily_value'] == 0:
            return None
        return round((current['daily_value'] - previous['daily_value']) / previous['daily_value'] * 100, 2)

    ma_7 = sum(r['daily_value'] for r in rows[:7]) / min(7, len(rows))
    ma_30 = sum(r['daily_value'] for r in rows[:30]) / min(30, len(rows))

    return jsonify({
        'maker': maker,
        'latest_date': today['date'],
        'latest_value': today['daily_value'],
        'dod_growth': calc_growth(today, yesterday),
        'wow_growth': calc_growth(today, week_ago),
        'mom_growth': calc_growth(today, month_ago),
        'ma_7': round(ma_7),
        'ma_30': round(ma_30)
    })


@app.route('/api/data')
def api_data():
    maker = request.args.get('maker', '')
    column = request.args.get('column', 'EV_Total')
    data_type = request.args.get('type', 'daily')  # 'daily' or 'cumulative'
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')

    if not maker:
        return jsonify({'error': 'Maker is required'}), 400

    conn = get_db()
    cursor = conn.cursor()

    if data_type == 'monthly':
        query = '''
            SELECT strftime('%Y-%m', date) as month, SUM(daily_value) as value
            FROM daily_registrations
            WHERE maker = ? AND metric = ?
        '''
        params = [maker, column]

        if start_date:
            query += ' AND date >= ?'
            params.append(start_date)
        if end_date:
            query += ' AND date <= ?'
            params.append(end_date)

        query += ' GROUP BY month ORDER BY month'
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return jsonify({'error': f'No data found for {maker}'}), 404

        return jsonify({
            'labels': [row['month'] for row in rows],
            'values': [row['value'] for row in rows],
            'interpolated': [False for _ in rows],
            'maker': maker,
            'column': column,
            'type': data_type
        })

    value_col = 'daily_value' if data_type == 'daily' else 'cumulative_value'

    # Build query with optional date filters
    query = f'''
        SELECT date, {value_col} as value, is_interpolated
        FROM daily_registrations
        WHERE maker = ? AND metric = ?
    '''
    params = [maker, column]

    if start_date:
        query += ' AND date >= ?'
        params.append(start_date)
    if end_date:
        query += ' AND date <= ?'
        params.append(end_date)

    query += ' ORDER BY date'

    cursor.execute(query, params)

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return jsonify({'error': f'No data found for {maker}'}), 404

    return jsonify({
        'labels': [row['date'] for row in rows],
        'values': [row['value'] for row in rows],
        'interpolated': [bool(row['is_interpolated']) for row in rows],
        'maker': maker,
        'column': column,
        'type': data_type
    })


@app.route('/api/compare')
def api_compare():
    makers = request.args.getlist('makers')
    column = request.args.get('column', 'EV_Total')
    data_type = request.args.get('type', 'daily')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')

    if len(makers) < 2 or len(makers) > 5:
        return jsonify({'error': 'Select between 2 and 5 makers'}), 400

    conn = get_db()
    cursor = conn.cursor()

    result = {}
    for maker in makers:
        if data_type == 'monthly':
            query = '''
                SELECT strftime('%Y-%m', date) as month, SUM(daily_value) as value
                FROM daily_registrations
                WHERE maker = ? AND metric = ?
            '''
            params = [maker, column]

            if start_date:
                query += ' AND date >= ?'
                params.append(start_date)
            if end_date:
                query += ' AND date <= ?'
                params.append(end_date)

            query += ' GROUP BY month ORDER BY month'
            cursor.execute(query, params)
            rows = cursor.fetchall()

            result[maker] = {
                'labels': [row['month'] for row in rows],
                'values': [row['value'] for row in rows],
            }
        else:
            value_col = 'daily_value' if data_type == 'daily' else 'cumulative_value'
            query = f'''
                SELECT date, {value_col} as value
                FROM daily_registrations
                WHERE maker = ? AND metric = ?
            '''
            params = [maker, column]

            if start_date:
                query += ' AND date >= ?'
                params.append(start_date)
            if end_date:
                query += ' AND date <= ?'
                params.append(end_date)

            query += ' ORDER BY date'
            cursor.execute(query, params)
            rows = cursor.fetchall()

            result[maker] = {
                'labels': [row['date'] for row in rows],
                'values': [row['value'] for row in rows],
            }

    conn.close()
    return jsonify(result)


@app.route('/api/date-range')
def api_date_range():
    """Get min and max dates in the database"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('SELECT MIN(date) as min_date, MAX(date) as max_date FROM daily_registrations')
    row = cursor.fetchone()
    conn.close()

    return jsonify({
        'min_date': row['min_date'],
        'max_date': row['max_date']
    })


def _compute_standard_market_share(cursor, column, period, month, date):
    """Compute market share from daily_registrations (no vehicle class filter)."""
    if period == 'monthly' and month:
        cursor.execute('''
            SELECT maker, SUM(daily_value) as value
            FROM daily_registrations
            WHERE strftime('%Y-%m', date) = ? AND metric = ?
            GROUP BY maker
            ORDER BY value DESC
        ''', (month, column))
    elif period == 'daily':
        if not date:
            cursor.execute('SELECT MAX(date) FROM daily_registrations')
            date = cursor.fetchone()[0]
        cursor.execute('''
            SELECT maker, daily_value as value
            FROM daily_registrations
            WHERE date = ? AND metric = ?
            ORDER BY value DESC
        ''', (date, column))
    else:
        if not date:
            cursor.execute('SELECT MAX(date) FROM daily_registrations')
            date = cursor.fetchone()[0]
        cursor.execute('''
            SELECT maker, cumulative_value as value
            FROM daily_registrations
            WHERE date = ? AND metric = ?
            ORDER BY value DESC
        ''', (date, column))

    rows = cursor.fetchall()
    return [{'maker': row['maker'], 'value': row['value']} for row in rows], date


def _estimate_for_month(cursor, column, vehicle_class, year, month_num):
    """Estimate maker registrations for a single month using the approximation formula.

    For each maker: estimated = round(fuel_sum / total_sum * vc_registrations)
    """
    month_str = f"{year}-{month_num:02d}"

    # Fuel-specific registrations by maker for this month
    cursor.execute('''
        SELECT maker, SUM(daily_value) as fuel_sum
        FROM daily_registrations
        WHERE strftime('%Y-%m', date) = ? AND metric = ?
        GROUP BY maker
    ''', (month_str, column))
    fuel_by_maker = {row['maker']: row['fuel_sum'] for row in cursor.fetchall() if row['fuel_sum']}

    # Total registrations by maker for this month
    cursor.execute('''
        SELECT maker, SUM(daily_value) as total_sum
        FROM daily_registrations
        WHERE strftime('%Y-%m', date) = ? AND metric = 'Total'
        GROUP BY maker
    ''', (month_str,))
    total_by_maker = {row['maker']: row['total_sum'] for row in cursor.fetchall() if row['total_sum']}

    # Vehicle class registrations by maker for this month
    cursor.execute('''
        SELECT maker, registrations
        FROM maker_vehicle_class
        WHERE year = ? AND month = ? AND vehicle_class = ?
    ''', (year, month_num, vehicle_class))
    vc_by_maker = {row['maker']: row['registrations'] for row in cursor.fetchall() if row['registrations']}

    # Intersect makers across all 3 and compute estimates
    common_makers = set(fuel_by_maker) & set(total_by_maker) & set(vc_by_maker)
    estimates = {}
    for maker in common_makers:
        total = total_by_maker[maker]
        if total == 0:
            continue
        ratio = fuel_by_maker[maker] / total
        estimated = round(ratio * vc_by_maker[maker])
        if estimated > 0:
            estimates[maker] = estimated
    return estimates


def _compute_vehicle_class_market_share(cursor, column, vehicle_class, period, month):
    """Compute approximate market share with vehicle class filter."""
    if period == 'monthly' and month:
        # Single month
        year, month_num = int(month[:4]), int(month[5:7])
        estimates = _estimate_for_month(cursor, column, vehicle_class, year, month_num)
    else:
        # Cumulative: find all months present in BOTH tables
        cursor.execute('''
            SELECT DISTINCT strftime('%Y', date) as y, strftime('%m', date) as m
            FROM daily_registrations
        ''')
        dr_months = {(int(row['y']), int(row['m'])) for row in cursor.fetchall()}

        cursor.execute('SELECT DISTINCT year, month FROM maker_vehicle_class')
        mvc_months = {(row['year'], row['month']) for row in cursor.fetchall()}

        common_months = sorted(dr_months & mvc_months)

        # Accumulate across months
        estimates = {}
        for year, month_num in common_months:
            month_est = _estimate_for_month(cursor, column, vehicle_class, year, month_num)
            for maker, val in month_est.items():
                estimates[maker] = estimates.get(maker, 0) + val

    # Convert to sorted list
    result = [{'maker': m, 'value': v} for m, v in estimates.items()]
    result.sort(key=lambda x: x['value'], reverse=True)
    return result


@app.route('/api/market-share')
def api_market_share():
    """Get market share data for pie/donut chart"""
    date = request.args.get('date', '')
    column = request.args.get('column', 'EV_Total')
    top_n = request.args.get('top', 10, type=int)
    period = request.args.get('period', 'cumulative')  # 'cumulative', 'monthly', 'daily'
    month = request.args.get('month', '')  # For monthly period, format: YYYY-MM
    vehicle_class = request.args.get('vehicle_class', 'All')

    conn = get_db()
    cursor = conn.cursor()

    if vehicle_class != 'All':
        rows = _compute_vehicle_class_market_share(cursor, column, vehicle_class, period, month)
    else:
        rows, date = _compute_standard_market_share(cursor, column, period, month, date)

    conn.close()

    total = sum(r['value'] for r in rows if r['value'])

    if total == 0:
        return jsonify({'error': 'No data found'}), 404

    top_makers = rows[:top_n]
    others_total = sum(r['value'] for r in rows[top_n:] if r['value'])

    result = [{
        'maker': r['maker'],
        'value': r['value'],
        'percentage': round(r['value'] / total * 100, 2) if r['value'] else 0
    } for r in top_makers]

    if others_total > 0:
        result.append({
            'maker': 'Others',
            'value': others_total,
            'percentage': round(others_total / total * 100, 2)
        })

    return jsonify({
        'date': date,
        'month': month,
        'period': period,
        'column': column,
        'vehicle_class': vehicle_class,
        'total': total,
        'data': result
    })


@app.route('/api/summary')
def api_summary():
    """Get summary statistics"""
    conn = get_db()
    cursor = conn.cursor()

    # Top 10 makers by EV_Total
    cursor.execute('''
        SELECT maker, SUM(daily_value) as total
        FROM daily_registrations
        WHERE metric = 'EV_Total'
        GROUP BY maker
        ORDER BY total DESC
        LIMIT 10
    ''')
    top_makers = [{'maker': row['maker'], 'total': row['total']} for row in cursor.fetchall()]

    # Monthly totals
    cursor.execute('''
        SELECT strftime('%Y-%m', date) as month, SUM(daily_value) as total
        FROM daily_registrations
        WHERE metric = 'EV_Total'
        GROUP BY month
        ORDER BY month
    ''')
    monthly = [{'month': row['month'], 'total': row['total']} for row in cursor.fetchall()]

    conn.close()

    return jsonify({
        'top_makers': top_makers,
        'monthly_totals': monthly
    })


if __name__ == '__main__':
    app.run(debug=True, port=5000)
