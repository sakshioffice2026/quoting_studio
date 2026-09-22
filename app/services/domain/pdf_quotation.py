"""
PDF generation for Quotation (Section 7) via WeasyPrint.
Renders the quotation — line items + installation/transport/AMC/warranty
charge rows + summary totals — to a single A4 PDF.
"""
import logging

logger = logging.getLogger(__name__)

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
      content: "{{ quotation.quotation_number }} · Page " counter(page) " of " counter(pages);
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

  .letterhead {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    border-bottom: 2.5pt solid #C97B3D;
    padding-bottom: 10pt;
    margin-bottom: 18pt;
  }
  .company-name { font-size: 20pt; font-weight: 700; color: #1B2430; letter-spacing: -0.5pt; }
  .company-meta { font-size: 8.5pt; color: #8A93A6; margin-top: 3pt; line-height: 1.6; }
  .quote-meta { text-align: right; font-size: 9pt; color: #566; line-height: 1.7; }
  .quote-number {
    font-size: 13pt; font-weight: 700; color: #C97B3D;
    font-family: 'Courier New', monospace;
  }

  .customer-block {
    background: #F6F3EC;
    border-left: 3pt solid #C97B3D;
    padding: 9pt 12pt;
    margin-bottom: 18pt;
    border-radius: 2pt;
  }
  .customer-block .label {
    font-size: 7.5pt; text-transform: uppercase; letter-spacing: 0.06em;
    color: #8A93A6; font-weight: 700; margin-bottom: 3pt;
  }
  .customer-block .name { font-size: 12pt; font-weight: 700; }
  .customer-block .address { font-size: 9pt; color: #566; margin-top: 2pt; }

  .section-title {
    font-size: 7.5pt; text-transform: uppercase; letter-spacing: 0.08em;
    color: #8A93A6; font-weight: 700;
    border-bottom: 1pt solid #E2DDD0;
    padding-bottom: 4pt; margin-bottom: 10pt; margin-top: 16pt;
  }

  table { width: 100%; border-collapse: collapse; font-size: 9.5pt; margin-bottom: 14pt; }
  th {
    background: #1B2430; color: #F6F3EC; font-size: 7.5pt; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.05em; padding: 5pt 7pt; text-align: left;
  }
  td { padding: 6pt 7pt; border-bottom: 0.5pt solid #E2DDD0; vertical-align: top; }
  tr:nth-child(even) td { background: #FAFAF8; }
  .td-right { text-align: right; white-space: nowrap; }
  .td-mono  { font-family: 'Courier New', monospace; font-size: 9pt; }
  .row-note { font-size: 8pt; color: #8A93A6; }

  .totals-block { width: 260pt; margin-left: auto; margin-top: 10pt; }
  .totals-row {
    display: flex; justify-content: space-between; padding: 4pt 0;
    border-bottom: 0.5pt solid #E2DDD0; font-size: 9.5pt; color: #566;
  }
  .totals-row.total-line {
    border-bottom: none; border-top: 2pt solid #1B2430; margin-top: 4pt;
    padding-top: 6pt; font-size: 13pt; font-weight: 700; color: #1B2430;
  }
  .totals-row .amount { font-family: 'Courier New', monospace; }

  .footer-note {
    margin-top: 24pt; padding-top: 10pt; border-top: 0.5pt solid #E2DDD0;
    font-size: 8pt; color: #AAA; text-align: center;
  }
</style>
</head>
<body>

<div class="letterhead">
  <div>
    <div class="company-name">{{ tenant.name }}</div>
    <div class="company-meta">{{ tenant.contact_email }}</div>
  </div>
  <div class="quote-meta">
    <div class="quote-number">{{ quotation.quotation_number }} · v{{ quotation.quotation_version }}</div>
    <div>{{ quotation.created_at.strftime('%d %B %Y') if quotation.created_at else '' }}</div>
    {% if quotation.validity_date %}
    <div style="margin-top:3pt;font-size:8pt;">Valid until {{ quotation.validity_date.strftime('%d %B %Y') }}</div>
    {% endif %}
  </div>
</div>

<div class="customer-block">
  <div class="label">Prepared for</div>
  <div class="name">{{ project.customer_name }}</div>
  {% if project.address %}
  <div class="address">{{ project.address }}</div>
  {% endif %}
</div>

<div class="section-title">Specification</div>
<table>
  <thead>
    <tr>
      <th style="width:40%">Item</th>
      <th style="width:20%">Material</th>
      <th style="width:12%">Qty</th>
      <th style="width:28%;text-align:right;">Amount</th>
    </tr>
  </thead>
  <tbody>
    {% for item in quotation.line_items %}
    <tr>
      <td><strong>{{ item.label or item.get('label', 'Item') }}</strong></td>
      <td>{{ item.material or '—' }}</td>
      <td>{{ item.qty or 1 }}</td>
      <td class="td-right td-mono">₹{{ '%.2f'|format(item.amount or 0) }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>

{% if quotation.installation_charge or quotation.transport_charge or quotation.other_charges or quotation.amc_offered or quotation.warranty_months %}
<div class="section-title">Installation, Transport, AMC &amp; Warranty</div>
<table>
  <thead>
    <tr>
      <th style="width:35%">Item</th>
      <th style="width:40%">Details</th>
      <th style="width:25%;text-align:right;">Amount</th>
    </tr>
  </thead>
  <tbody>
    {% if quotation.installation_charge %}
    <tr>
      <td><strong>Installation Charges</strong></td>
      <td class="row-note">Fitting &amp; on-site installation</td>
      <td class="td-right td-mono">₹{{ '%.2f'|format(quotation.installation_charge) }}</td>
    </tr>
    {% endif %}
    {% if quotation.transport_charge %}
    <tr>
      <td><strong>Transport Charges</strong></td>
      <td class="row-note">Delivery to site</td>
      <td class="td-right td-mono">₹{{ '%.2f'|format(quotation.transport_charge) }}</td>
    </tr>
    {% endif %}
    {% for charge in quotation.other_charges %}
    <tr>
      <td><strong>{{ charge.label }}</strong></td>
      <td class="row-note">—</td>
      <td class="td-right td-mono">₹{{ '%.2f'|format(charge.amount) }}</td>
    </tr>
    {% endfor %}
    {% if quotation.amc_offered %}
    <tr>
      <td><strong>AMC — {{ quotation.amc_offer_tier or '—' }}</strong></td>
      <td class="row-note">Annual maintenance contract</td>
      <td class="td-right td-mono">{{ '₹%.2f'|format(quotation.amc_price) if quotation.amc_price else '—' }}</td>
    </tr>
    {% endif %}
    {% if quotation.warranty_months %}
    <tr>
      <td><strong>Warranty</strong></td>
      <td class="row-note">{{ quotation.warranty_terms_text or (quotation.warranty_months ~ ' months standard warranty') }}</td>
      <td class="td-right">Included</td>
    </tr>
    {% endif %}
  </tbody>
</table>
{% endif %}

<div class="totals-block">
  <div class="totals-row">
    <span>Subtotal</span>
    <span class="amount">₹{{ '%.2f'|format(quotation.subtotal or 0) }}</span>
  </div>
  {% if quotation.discount_amount %}
  <div class="totals-row">
    <span>Discount ({{ quotation.discount_pct or 0 }}%)</span>
    <span class="amount">− ₹{{ '%.2f'|format(quotation.discount_amount) }}</span>
  </div>
  {% endif %}
  <div class="totals-row">
    <span>Tax ({{ ((quotation.tax_rate or 0) * 100)|int }}%)</span>
    <span class="amount">₹{{ '%.2f'|format(quotation.tax_amount or 0) }}</span>
  </div>
  <div class="totals-row total-line">
    <span>Grand Total</span>
    <span class="amount">₹{{ '%.2f'|format(quotation.grand_total or 0) }}</span>
  </div>
</div>

{% if quotation.payment_terms_template %}
<div class="section-title">Payment Terms</div>
<div style="font-size:9.5pt;color:#566;">{{ quotation.payment_terms_template }}</div>
{% endif %}

<div class="footer-note">
  This quotation is valid until {{ quotation.validity_date.strftime('%d %B %Y') if quotation.validity_date else 'the date stated above' }}.
  Generated by Quoting Studio.
</div>

</body>
</html>
"""


def _generate_with_reportlab(quotation, project, tenant) -> bytes:
    """
    Pure-Python fallback PDF generator — no native GTK/Pango libraries
    required. Used automatically when WeasyPrint's native dependencies
    (gobject-2.0-0, pango, etc.) are not installed on the host, which is
    common on Windows dev machines.
    """
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=18 * mm, bottomMargin=20 * mm,
        leftMargin=16 * mm, rightMargin=16 * mm,
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle('h1', parent=styles['Heading1'], fontSize=18, spaceAfter=2)
    meta = ParagraphStyle('meta', parent=styles['Normal'], fontSize=9, textColor=colors.HexColor('#566'))
    section = ParagraphStyle('section', parent=styles['Heading3'], fontSize=10,
                              textColor=colors.HexColor('#8A93A6'), spaceBefore=14, spaceAfter=6)

    story = []
    story.append(Paragraph(tenant.name if tenant else 'Quoting Studio', h1))
    if tenant and getattr(tenant, 'contact_email', None):
        story.append(Paragraph(tenant.contact_email, meta))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        f"<b>{quotation.quotation_number}</b> &middot; v{quotation.quotation_version}", meta))
    if quotation.validity_date:
        story.append(Paragraph(f"Valid until {quotation.validity_date.strftime('%d %B %Y')}", meta))
    story.append(Spacer(1, 10))

    story.append(Paragraph(f"<b>{project.customer_name}</b>", styles['Heading2']))
    if getattr(project, 'address', None):
        story.append(Paragraph(project.address, meta))

    # ---- Specification ----
    story.append(Paragraph('SPECIFICATION', section))
    spec_rows = [['Item', 'Material', 'Qty', 'Amount']]
    for item in quotation.line_items:
        label = item.get('label', 'Item') if isinstance(item, dict) else getattr(item, 'label', 'Item')
        material = item.get('material') if isinstance(item, dict) else getattr(item, 'material', None)
        qty = item.get('qty', 1) if isinstance(item, dict) else getattr(item, 'qty', 1)
        amount = item.get('amount', 0) if isinstance(item, dict) else getattr(item, 'amount', 0)
        spec_rows.append([label, material or '—', str(qty or 1), f"Rs. {float(amount or 0):,.2f}"])
    spec_table = Table(spec_rows, colWidths=[70 * mm, 40 * mm, 20 * mm, 40 * mm])
    spec_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1B2430')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2DDD0')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#FAFAF8')]),
    ]))
    story.append(spec_table)

    # ---- Installation / transport / AMC / warranty ----
    extra_rows = [['Item', 'Details', 'Amount']]
    if quotation.installation_charge:
        extra_rows.append(['Installation Charges', 'Fitting & on-site installation',
                            f"Rs. {float(quotation.installation_charge):,.2f}"])
    if quotation.transport_charge:
        extra_rows.append(['Transport Charges', 'Delivery to site',
                            f"Rs. {float(quotation.transport_charge):,.2f}"])
    for charge in quotation.other_charges:
        label = charge.get('label') if isinstance(charge, dict) else getattr(charge, 'label', '')
        amount = charge.get('amount') if isinstance(charge, dict) else getattr(charge, 'amount', 0)
        extra_rows.append([label, '—', f"Rs. {float(amount or 0):,.2f}"])
    if quotation.amc_offered:
        amc_amt = f"Rs. {float(quotation.amc_price):,.2f}" if quotation.amc_price else '—'
        extra_rows.append([f"AMC — {quotation.amc_offer_tier or '—'}", 'Annual maintenance contract', amc_amt])
    if quotation.warranty_months:
        wtext = quotation.warranty_terms_text or f"{quotation.warranty_months} months standard warranty"
        extra_rows.append(['Warranty', wtext, 'Included'])

    if len(extra_rows) > 1:
        story.append(Paragraph('INSTALLATION, TRANSPORT, AMC &amp; WARRANTY', section))
        extra_table = Table(extra_rows, colWidths=[55 * mm, 75 * mm, 40 * mm])
        extra_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1B2430')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2DDD0')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#FAFAF8')]),
        ]))
        story.append(extra_table)

    # ---- Totals ----
    story.append(Spacer(1, 10))
    totals_rows = [['Subtotal', f"Rs. {float(quotation.subtotal or 0):,.2f}"]]
    if quotation.discount_amount:
        totals_rows.append([f"Discount ({quotation.discount_pct or 0}%)",
                             f"- Rs. {float(quotation.discount_amount):,.2f}"])
    totals_rows.append([f"Tax ({int(float(quotation.tax_rate or 0) * 100)}%)",
                         f"Rs. {float(quotation.tax_amount or 0):,.2f}"])
    totals_rows.append(['Grand Total', f"Rs. {float(quotation.grand_total or 0):,.2f}"])
    totals_table = Table(totals_rows, colWidths=[110 * mm, 40 * mm], hAlign='RIGHT')
    totals_table.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('LINEBELOW', (0, 0), (-1, -2), 0.5, colors.HexColor('#E2DDD0')),
        ('LINEABOVE', (0, -1), (-1, -1), 1.5, colors.HexColor('#1B2430')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, -1), (-1, -1), 12),
        ('TOPPADDING', (0, -1), (-1, -1), 6),
    ]))
    story.append(totals_table)

    if quotation.payment_terms_template:
        story.append(Paragraph('PAYMENT TERMS', section))
        story.append(Paragraph(quotation.payment_terms_template, styles['Normal']))

    story.append(Spacer(1, 20))
    story.append(Paragraph(
        f"This quotation is valid until "
        f"{quotation.validity_date.strftime('%d %B %Y') if quotation.validity_date else 'the date stated above'}. "
        f"Generated by Quoting Studio.",
        meta,
    ))

    doc.build(story)
    return buf.getvalue()


def generate_quotation_pdf(quotation, project, tenant) -> bytes:
    """
    Render a Quotation as PDF.
    Tries WeasyPrint first (matches the on-screen HTML layout exactly).
    Falls back to a pure-Python reportlab renderer when WeasyPrint's native
    GTK/Pango libraries aren't installed on the host (common on Windows) —
    no system-level install required for the fallback path.
    Returns raw PDF bytes. Raises only if both paths fail.
    """
    try:
        from weasyprint import HTML
        from jinja2 import Environment

        env = Environment()
        tmpl = env.from_string(_PDF_TEMPLATE)
        html_str = tmpl.render(
            quotation=quotation,
            project=project,
            tenant=tenant,
        )

        pdf_bytes = HTML(string=html_str).write_pdf()
        logger.info('Quotation PDF rendered (WeasyPrint): %s size=%d bytes',
                    quotation.quotation_number, len(pdf_bytes))
        return pdf_bytes

    except (ImportError, OSError) as exc:
        logger.warning(
            'WeasyPrint unavailable (%s) — falling back to reportlab for quotation %s',
            exc, quotation.quotation_number,
        )
        try:
            pdf_bytes = _generate_with_reportlab(quotation, project, tenant)
            logger.info('Quotation PDF rendered (reportlab fallback): %s size=%d bytes',
                        quotation.quotation_number, len(pdf_bytes))
            return pdf_bytes
        except Exception as fallback_exc:
            logger.exception('reportlab fallback also failed for quotation %s: %s',
                              quotation.quotation_number, fallback_exc)
            raise
    except Exception as exc:
        logger.exception('PDF generation error for quotation %s: %s',
                          quotation.quotation_number, exc)
        raise
