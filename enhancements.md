# Vahan EV Dashboard - Enhancement Proposals

## Priority 1: Multi-Maker Comparison Mode

### Overview
Allow users to select and compare multiple makers (2-5) on the same chart, enabling competitive analysis and market trend identification.

### Why This Matters
- Single maker view limits competitive analysis
- Investors and analysts need to compare brands (e.g., Ola vs Ather, Tata vs MG)
- Market dynamics are only visible when viewing multiple players together
- Enables identification of market share shifts over time

### Implementation

#### Backend Changes (app.py)

Add new API endpoint `/api/compare`:

```python
@app.route('/api/compare')
def api_compare():
    makers = request.args.getlist('makers')  # Multiple makers
    column = request.args.get('column', 'EV_Total')
    data_type = request.args.get('type', 'daily')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')

    if not makers or len(makers) < 2:
        return jsonify({'error': 'At least 2 makers required'}), 400

    if len(makers) > 5:
        return jsonify({'error': 'Maximum 5 makers allowed'}), 400

    conn = get_db()
    cursor = conn.cursor()

    value_col = 'daily_value' if data_type == 'daily' else 'cumulative_value'

    results = {}
    for maker in makers:
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

        results[maker] = {
            'labels': [row['date'] for row in rows],
            'values': [row['value'] for row in rows],
            'interpolated': [bool(row['is_interpolated']) for row in rows]
        }

    conn.close()

    return jsonify({
        'makers': makers,
        'data': results,
        'column': column,
        'type': data_type
    })
```

#### Frontend Changes (index.html)

1. **Add multi-select for makers:**
```html
<div class="control-group">
    <label>Compare Makers (max 5)</label>
    <select id="maker-compare" multiple class="multi-select">
        <!-- Populated dynamically -->
    </select>
</div>
```

2. **Add comparison toggle:**
```html
<div class="control-group">
    <label>Mode</label>
    <div class="toggle-group">
        <button class="toggle-btn active" data-mode="single">Single</button>
        <button class="toggle-btn" data-mode="compare">Compare</button>
    </div>
</div>
```

3. **Update chart rendering for multiple datasets:**
```javascript
function renderComparisonChart(data) {
    const colors = [
        'rgba(0, 212, 255, 0.8)',   // Cyan
        'rgba(255, 99, 132, 0.8)',   // Red
        'rgba(75, 192, 192, 0.8)',   // Teal
        'rgba(255, 206, 86, 0.8)',   // Yellow
        'rgba(153, 102, 255, 0.8)'   // Purple
    ];

    const datasets = data.makers.map((maker, i) => ({
        label: maker,
        data: data.data[maker].values,
        borderColor: colors[i],
        backgroundColor: colors[i].replace('0.8', '0.2'),
        borderWidth: 2,
        tension: 0.1
    }));

    chart = new Chart(ctx, {
        type: 'line',  // Line chart better for comparison
        data: {
            labels: data.data[data.makers[0]].labels,
            datasets: datasets
        },
        options: {
            responsive: true,
            interaction: {
                mode: 'index',
                intersect: false
            },
            plugins: {
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return `${context.dataset.label}: ${context.parsed.y.toLocaleString()}`;
                        }
                    }
                }
            }
        }
    });
}
```

---

## Priority 2: Market Share Analysis

### Overview
Show percentage market share instead of absolute numbers, with pie/donut charts for snapshot views.

### Implementation

Add endpoint `/api/market-share`:
```python
@app.route('/api/market-share')
def api_market_share():
    date = request.args.get('date', '')  # Specific date or latest
    column = request.args.get('column', 'EV_Total')
    top_n = request.args.get('top', 10, type=int)

    conn = get_db()
    cursor = conn.cursor()

    if not date:
        cursor.execute('SELECT MAX(date) FROM daily_registrations')
        date = cursor.fetchone()[0]

    cursor.execute('''
        SELECT maker, cumulative_value as value
        FROM daily_registrations
        WHERE date = ? AND metric = ?
        ORDER BY cumulative_value DESC
    ''', (date, column))

    rows = cursor.fetchall()
    total = sum(row['value'] for row in rows)

    top_makers = rows[:top_n]
    others_total = sum(row['value'] for row in rows[top_n:])

    result = [{
        'maker': row['maker'],
        'value': row['value'],
        'percentage': round(row['value'] / total * 100, 2)
    } for row in top_makers]

    if others_total > 0:
        result.append({
            'maker': 'Others',
            'value': others_total,
            'percentage': round(others_total / total * 100, 2)
        })

    return jsonify({
        'date': date,
        'column': column,
        'total': total,
        'data': result
    })
```

### Visualization
- Donut chart showing market share
- Table with rank, maker, value, percentage
- Trend sparklines showing share change over time

---

## Priority 3: Growth Rate & Trends

### Overview
Calculate and display growth metrics:
- Day-over-day (DoD) growth
- Week-over-week (WoW) growth
- Month-over-month (MoM) growth
- 7-day and 30-day moving averages

### Implementation

Add endpoint `/api/growth`:
```python
@app.route('/api/growth')
def api_growth():
    maker = request.args.get('maker', '')
    column = request.args.get('column', 'EV_Total')

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

    if len(rows) < 2:
        return jsonify({'error': 'Insufficient data'}), 400

    today = rows[0]
    yesterday = rows[1] if len(rows) > 1 else None
    week_ago = rows[7] if len(rows) > 7 else None
    month_ago = rows[30] if len(rows) > 30 else None

    def calc_growth(current, previous):
        if not previous or previous['daily_value'] == 0:
            return None
        return round((current['daily_value'] - previous['daily_value']) / previous['daily_value'] * 100, 2)

    # 7-day moving average
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
```

### Dashboard Display
- Growth indicators with color coding (green for positive, red for negative)
- Moving average overlay on the main chart
- Trend arrows next to current values

---

## Priority 4: Data Export

### Overview
Allow users to export filtered data in CSV/Excel format.

### Implementation

```python
from flask import Response
import csv
import io

@app.route('/api/export')
def api_export():
    maker = request.args.get('maker', '')
    column = request.args.get('column', 'EV_Total')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    format = request.args.get('format', 'csv')

    conn = get_db()
    cursor = conn.cursor()

    query = '''
        SELECT date, daily_value, cumulative_value, is_interpolated
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

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Daily Registrations', 'Cumulative', 'Is Estimated'])

    for row in rows:
        writer.writerow([row['date'], row['daily_value'], row['cumulative_value'],
                        'Yes' if row['is_interpolated'] else 'No'])

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={maker}_{column}.csv'}
    )
```

### Frontend
- Add "Export CSV" button next to the chart
- Include current filters in the export

---

## Priority 5: Alerts & Notifications

### Overview
Set up automated alerts for significant events:
- New daily high for a maker
- Unusual spike or drop (>50% change)
- Market share shifts

### Implementation

Create `alerts.py`:
```python
import sqlite3
import smtplib
from email.mime.text import MIMEText

def check_alerts():
    conn = sqlite3.connect('vahan_data.db')
    cursor = conn.cursor()

    # Check for unusual spikes (>50% day-over-day change)
    cursor.execute('''
        WITH daily_changes AS (
            SELECT
                date, maker, daily_value,
                LAG(daily_value) OVER (PARTITION BY maker ORDER BY date) as prev_value
            FROM daily_registrations
            WHERE metric = 'EV_Total'
        )
        SELECT date, maker, daily_value, prev_value,
               (daily_value - prev_value) * 100.0 / prev_value as pct_change
        FROM daily_changes
        WHERE date = (SELECT MAX(date) FROM daily_registrations)
          AND prev_value > 0
          AND ABS((daily_value - prev_value) * 100.0 / prev_value) > 50
    ''')

    alerts = cursor.fetchall()
    conn.close()

    if alerts:
        send_alert_email(alerts)

def send_alert_email(alerts):
    # Configure with your email settings
    pass
```

Add to cron job to run after data refresh.

---

## Quick Wins (Low Effort, High Value)

### 1. Shareable URLs
Encode current filters in URL parameters so users can share specific views.

```javascript
function updateURL() {
    const params = new URLSearchParams({
        maker: document.getElementById('maker').value,
        column: document.getElementById('column').value,
        type: currentType,
        start: dateRange.startDate,
        end: dateRange.endDate
    });
    history.replaceState(null, '', '?' + params.toString());
}

function loadFromURL() {
    const params = new URLSearchParams(window.location.search);
    if (params.get('maker')) {
        // Set filters from URL params
    }
}
```

### 2. Keyboard Shortcuts
- `←` / `→` - Navigate date range
- `d` / `c` - Toggle daily/cumulative
- `/` - Focus search/maker dropdown

### 3. Loading Skeleton
Show animated placeholder while data loads for better perceived performance.

### 4. Tooltips with More Context
Show additional info on hover:
- Rank among all makers
- Percentage of total market
- Change from previous day

---

## Implementation Priority

| Enhancement | Effort | Impact | Priority |
|-------------|--------|--------|----------|
| Multi-Maker Comparison | Medium | High | 1 |
| Market Share Analysis | Medium | High | 2 |
| Growth Rate & Trends | Low | Medium | 3 |
| Data Export | Low | Medium | 4 |
| Shareable URLs | Low | Medium | 5 |
| Alerts & Notifications | High | Medium | 6 |

---

## Getting Started

To implement Priority 1 (Multi-Maker Comparison):

1. Add the `/api/compare` endpoint to `app.py`
2. Add multi-select dropdown using a library like Choices.js or Select2
3. Add comparison mode toggle
4. Create new chart rendering function for multiple datasets
5. Update stats section to show comparison table

Estimated effort: 2-3 hours
