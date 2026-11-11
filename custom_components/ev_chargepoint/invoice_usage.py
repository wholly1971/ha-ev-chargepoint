"""Daily invoice evidence and a vector bar chart, without history backfilling."""

from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import InvalidOperation

from .billing import decimal


def daily_usage(invoice):
    """Keep missing, measured zero and incomplete days distinct."""
    if invoice.get('period_start'):
        start = datetime.fromisoformat(invoice['period_start'])
        end = datetime.fromisoformat(invoice['period_end'])
        first = start.date()
        last = (end - timedelta(microseconds=1)).date()
        stamps = [first + timedelta(days=day) for day in range(max(1, (last - first).days + 1))]
    else:
        year, month = map(int, invoice['period'].split('-'))
        stamps = [date(year, month, day) for day in range(1, monthrange(year, month)[1] + 1)]
    rows = []
    for stamp in stamps:
        bucket = invoice.get('days', {}).get(stamp.isoformat())
        value, partial = None, False
        if bucket is not None:
            try:
                value = decimal(bucket['kwh'])
                if value < 0:
                    value = None
                partial = decimal(bucket.get('gap_seconds', 0)) > 0
            except (ValueError, InvalidOperation, TypeError, KeyError):
                value = None
        rows.append({'date': stamp, 'kwh': value, 'partial': partial})
    known = [row for row in rows if row['kwh'] is not None]
    if invoice.get('partial') and known:
        known[0]['partial'] = True
    return rows


def usage_chart(rows, width):
    """A print-sharp vector chart with every calendar day on a common scale."""
    from reportlab.graphics.shapes import Drawing, Line, Rect, String
    from reportlab.lib.colors import HexColor

    drawing = Drawing(width, 270)
    navy, teal, coral, grey = map(HexColor, ('#152a4a', '#0b9c9b', '#cf655c', '#9aa5b1'))
    left, bottom, height = 42, 46, 190
    plot_width = width - left - 10
    slot = plot_width / len(rows)
    maximum = max((float(row['kwh']) for row in rows if row['kwh'] is not None), default=0)
    # A nonzero scale makes an all-zero month legible without inventing usage.
    ceiling = maximum * 1.15 if maximum else 1
    drawing.add(String(0, 253, 'Recorded billable energy (kWh)', fontName='Helvetica', fontSize=9, fillColor=navy))
    for tick in range(5):
        y = bottom + height * tick / 4
        value = ceiling * tick / 4
        drawing.add(Line(left, y, width - 10, y, strokeColor=HexColor('#e4e9ef'), strokeWidth=.5))
        drawing.add(String(left - 7, y - 3, f'{value:.2f}', textAnchor='end', fontName='Helvetica', fontSize=7, fillColor=navy))
    for index, row in enumerate(rows):
        x = left + slot * index + slot / 2
        colour = coral if row['partial'] else teal
        if row['kwh'] is None:
            drawing.add(Line(x - 2, bottom + 2, x + 2, bottom + 6, strokeColor=grey))
            drawing.add(Line(x - 2, bottom + 6, x + 2, bottom + 2, strokeColor=grey))
        elif row['kwh'] == 0:
            drawing.add(Line(x - 3, bottom, x + 3, bottom, strokeColor=colour, strokeWidth=2))
            drawing.add(String(x, bottom + 6, '0', textAnchor='middle', fontSize=6, fillColor=colour))
        else:
            bar_height = float(row['kwh']) / ceiling * height
            drawing.add(Rect(x - slot * .32, bottom, slot * .64, bar_height, fillColor=colour, strokeColor=None))
        drawing.add(String(x, bottom - 13, str(row['date'].day), textAnchor='middle', fontName='Helvetica', fontSize=7, fillColor=navy))
        drawing.add(String(x, bottom - 24, row['date'].strftime('%a'), textAnchor='middle', fontName='Helvetica', fontSize=5.5, fillColor=grey))
    for x, label, colour in ((left, 'Recorded', teal), (left + 110, 'Incomplete day', coral), (left + 250, 'x  No daily record', grey)):
        drawing.add(Rect(x, 2, 7, 7, fillColor=colour, strokeColor=None))
        drawing.add(String(x + 12, 2, label, fontName='Helvetica', fontSize=8, fillColor=navy))
    return drawing
