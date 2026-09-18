"""
PDF quote generation via WeasyPrint.
Renders quote_pdf.html to PDF with full A4 layout.
"""
import logging
from flask import render_template_string

logger = logging.getLogger(__name__)

# Inline PDF template — self-contained so WeasyPrint needs no external assets
_PDF_TEMPLATE = r"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  @page {
    size: A4;
    margin: 18mm 16mm 20mm 16mm;
    @bottom-center {
      content: "{{ quote.quote_number }} · Page " counter(page) " of " counter(pages);
      font-family: Arial, sans-serif;
      font-size: 9pt;
      color: #8A93A6;
    }
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: Arial, Helvetica, sans-serif;
    font-size: 10pt;
    color: #1B2430;
    line-height: 1.45;
  }

  /* ---- Letterhead ---- */
  .letterhead {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    border-bottom: 2.5pt solid #C97B3D;
    padding-bottom: 10pt;
    margin-bottom: 18pt;
  }
  .company-name {
    font-size: 20pt;
    font-weight: 700;
    color: #1B2430;
    letter-spacing: -0.5pt;
  }
  .company-meta {
    font-size: 8.5pt;
    color: #8A93A6;
    margin-top: 3pt;
    line-height: 1.6;
  }
  .quote-meta {
    text-align: right;
    font-size: 9pt;
    color: #566;
    line-height: 1.7;
  }
  .quote-number {
    font-size: 13pt;
    font-weight: 700;
    color: #C97B3D;
    font-family: 'Courier New', monospace;
  }

  /* ---- Customer block ---- */
  .customer-block {
    background: #F6F3EC;
    border-left: 3pt solid #C97B3D;
    padding: 9pt 12pt;
    margin-bottom: 18pt;
    border-radius: 2pt;
  }
  .customer-block .label {
    font-size: 7.5pt;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: #8A93A6;
    font-weight: 700;
    margin-bottom: 3pt;
  }
  .customer-block .name {
    font-size: 12pt;
    font-weight: 700;
  }
  .customer-block .address {
    font-size: 9pt;
    color: #566;
    margin-top: 2pt;
  }

  /* ---- Section title ---- */
  .section-title {
    font-size: 7.5pt;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #8A93A6;
    font-weight: 700;
    border-bottom: 1pt solid #E2DDD0;
    padding-bottom: 4pt;
    margin-bottom: 10pt;
    margin-top: 16pt;
  }

  /* ---- Window table ---- */
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 9.5pt;
    margin-bottom: 14pt;
  }
  th {
    background: #1B2430;
    color: #F6F3EC;
    font-size: 7.5pt;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 5pt 7pt;
    text-align: left;
  }
  td {
    padding: 6pt 7pt;
    border-bottom: 0.5pt solid #E2DDD0;
    vertical-align: top;
  }
  tr:nth-child(even) td { background: #FAFAF8; }
  .td-right { text-align: right; white-space: nowrap; }
  .td-mono  { font-family: 'Courier New', monospace; font-size: 9pt; }
  .pane-detail {
    font-size: 8pt;
    color: #8A93A6;
    margin-top: 2pt;
  }

  /* ---- Totals ---- */
  .totals-block {
    width: 230pt;
    margin-left: auto;
    margin-top: 10pt;
  }
  .totals-row {
    display: flex;
    justify-content: space-between;
    padding: 4pt 0;
    border-bottom: 0.5pt solid #E2DDD0;
    font-size: 9.5pt;
    color: #566;
  }
  .totals-row.total-line {
    border-bottom: none;
    border-top: 2pt solid #1B2430;
    margin-top: 4pt;
    padding-top: 6pt;
    font-size: 13pt;
    font-weight: 700;
    color: #1B2430;
  }
  .totals-row .amount { font-family: 'Courier New', monospace; }

  /* ---- Materials summary ---- */
  .mat-tag {
    display: inline-block;
    background: #1B2430;
    color: #F6F3EC;
    font-size: 7.5pt;
    padding: 2pt 6pt;
    border-radius: 10pt;
    margin: 2pt 3pt 2pt 0;
  }

  /* ---- Footer note ---- */
  .footer-note {
    margin-top: 24pt;
    padding-top: 10pt;
    border-top: 0.5pt solid #E2DDD0;
    font-size: 8pt;
    color: #AAA;
    text-align: center;
  }
</style>
</head>
<body>

<!-- Letterhead -->
<div class="letterhead">
  <div>
    <div class="company-name">{{ tenant.name }}</div>
    <div class="company-meta">{{ tenant.contact_email }}</div>
  </div>
  <div class="quote-meta">
    <div class="quote-number">{{ quote.quote_number }}</div>
    <div>{{ quote.issued_date.strftime('%d %B %Y') }}</div>
    <div style="margin-top:3pt;font-size:8pt;">
      Valid for 30 days
    </div>
  </div>
</div>

<!-- Customer -->
<div class="customer-block">
  <div class="label">Prepared for</div>
  <div class="name">{{ project.customer_name }}</div>
  {% if project.address %}
  <div class="address">{{ project.address }}</div>
  {% endif %}
</div>

<!-- Specification table -->
<div class="section-title">Specification</div>
<table>
  <thead>
    <tr>
      <th style="width:30%">Item</th>
      <th style="width:22%">Dimensions</th>
      <th style="width:18%">Material</th>
      <th style="width:16%">Glazing</th>
      <th style="width:14%;text-align:right;">Price</th>
    </tr>
  </thead>
  <tbody>
    {% for line in window_lines %}
    <tr>
      <td>
        <strong>{{ line.window.label }}</strong>
        {% if line.panes %}
        <div class="pane-detail">
          {% for p in line.panes %}
            {{ p.opener_type }}{% if not loop.last %}, {% endif %}
          {% endfor %}
        </div>
        {% endif %}
      </td>
      <td class="td-mono">{{ line.window.width_mm }} × {{ line.window.height_mm }} mm</td>
      <td>{{ line.window.material }}</td>
      <td>
        {% if line.panes %}{{ line.panes[0].glazing_type }}{% else %}—{% endif %}
      </td>
      <td class="td-right td-mono">£{{ '%.2f'|format(line.price.total) }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>

<!-- Totals -->
<div class="totals-block">
  <div class="totals-row">
    <span>Subtotal</span>
    <span class="amount">£{{ '%.2f'|format(quote.subtotal) }}</span>
  </div>
  <div class="totals-row">
    <span>VAT ({{ (quote.vat_rate * 100)|int }}%)</span>
    <span class="amount">£{{ '%.2f'|format(vat_amt) }}</span>
  </div>
  <div class="totals-row total-line">
    <span>Total</span>
    <span class="amount">£{{ '%.2f'|format(quote.total) }}</span>
  </div>
</div>

<!-- Materials summary -->
<div class="section-title">Materials specified</div>
{% set materials = window_lines | map(attribute='window') | map(attribute='material') | unique | list %}
{% set glazings  = window_lines | map(attribute='panes') | sum(start=[]) | map(attribute='glazing_type') | unique | list %}
<div>
  {% for m in materials %}
  <span class="mat-tag">{{ m }}</span>
  {% endfor %}
  {% for g in glazings %}
  <span class="mat-tag" style="background:#3D6B5C;">{{ g }}</span>
  {% endfor %}
</div>

<!-- Footer -->
<div class="footer-note">
  This quotation is valid for 30 days from the date of issue.
  Prices include supply and installation unless otherwise stated.
  Generated by Quoting Studio.
</div>

</body>
</html>
"""


def generate_quote_pdf(quote, project, tenant, window_lines, vat_amt) -> bytes:
    """
    Render the quote as PDF using WeasyPrint.
    Returns raw PDF bytes.
    Raises on failure (caller handles logging + fallback).
    """
    try:
        from weasyprint import HTML
        from jinja2 import Environment

        # Render the template string with Jinja2
        env = Environment()
        # add unique filter
        env.filters['unique'] = lambda it: list(dict.fromkeys(it))
        tmpl = env.from_string(_PDF_TEMPLATE)
        html_str = tmpl.render(
            quote=quote,
            project=project,
            tenant=tenant,
            window_lines=window_lines,
            vat_amt=vat_amt,
        )

        pdf_bytes = HTML(string=html_str).write_pdf()
        logger.info('PDF rendered: quote=%s size=%d bytes', quote.quote_number, len(pdf_bytes))
        return pdf_bytes

    except ImportError:
        logger.error('WeasyPrint not installed — cannot generate PDF')
        raise
    except Exception as exc:
        logger.exception('PDF generation error for quote %s: %s', quote.quote_number, exc)
        raise
