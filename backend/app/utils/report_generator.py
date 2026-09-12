import io
from app.schemas import SpillAnalysisResponse
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors

def generate_forensic_pdf(analysis: SpillAnalysisResponse) -> io.BytesIO:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=18)
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'TitleStyle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=14,
        spaceAfter=14,
        alignment=1 # Center
    )
    
    header_style = ParagraphStyle(
        'HeaderStyle',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=12,
        spaceAfter=10,
        spaceBefore=10
    )

    body_style = styles['Normal']
    
    elements = []
    
    # Header
    elements.append(Paragraph("INDIAN COAST GUARD / NOS-DCP", title_style))
    elements.append(Paragraph("OFFICIAL SATELLITE RADAR FORENSIC ATTRIBUTION DOSSIER", title_style))
    elements.append(Spacer(1, 20))
    
    # Chain of Custody
    import hashlib
    content_hash = hashlib.sha256(analysis.json().encode('utf-8')).hexdigest()
    
    elements.append(Paragraph("CHAIN OF CUSTODY", header_style))
    elements.append(Paragraph(f"<b>Incident Reference ID:</b> {analysis.spill_id}", body_style))
    elements.append(Paragraph(f"<b>Detection Timestamp:</b> {analysis.detection_timestamp.isoformat()}", body_style))
    elements.append(Paragraph(f"<b>SHA-256 Integrity Hash:</b> {content_hash}", body_style))
    elements.append(Spacer(1, 15))
    
    # Section 1: Radar Geometry
    elements.append(Paragraph("SECTION 1: RADAR GEOMETRY & MODEL 2 VERIFICATION", header_style))
    elements.append(Paragraph(f"<b>Centroid:</b> {analysis.geometry.centroid.lat} N, {analysis.geometry.centroid.lon} E", body_style))
    elements.append(Paragraph(f"<b>Area:</b> {analysis.geometry.area_km2} sq km", body_style))
    elements.append(Paragraph(f"<b>Status:</b> {analysis.status_message}", body_style))
    elements.append(Spacer(1, 15))
    
    # Section 2: Lagrangian Leeway Drift Hindcast
    elements.append(Paragraph("SECTION 2: LAGRANGIAN LEEWAY DRIFT HINDCAST", header_style))
    origin = analysis.drift.hindcast_origin
    elements.append(Paragraph(f"<b>Probable Origin (P0):</b> {origin.centroid.lat} N, {origin.centroid.lon} E", body_style))
    elements.append(Paragraph(f"<b>Time Window:</b> {origin.time_window_start.isoformat()} to {origin.time_window_end.isoformat()}", body_style))
    elements.append(Paragraph(f"<b>Uncertainty Buffer Radius:</b> {origin.uncertainty_radius_km} km", body_style))
    elements.append(Spacer(1, 15))
    
    # Section 3: Ranked AIS Vessel Matrix
    elements.append(Paragraph("SECTION 3: RANKED AIS VESSEL MATRIX", header_style))
    if analysis.ranked_vessels:
        data = [["Rank", "Vessel Name", "MMSI", "Score", "CPA (km)", "Anomaly"]]
        for idx, v in enumerate(analysis.ranked_vessels):
            anomaly = "YES (Speed Drop)" if v.evidence.speed_anomaly_detected else "NO"
            data.append([
                str(idx + 1),
                v.vessel_name,
                v.mmsi,
                f"{v.attribution_score:.2f}",
                f"{v.evidence.cpa_distance_km:.2f}",
                anomaly
            ])
            
        table = Table(data)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.grey),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0,0), (-1,0), 12),
            ('BACKGROUND', (0,1), (-1,-1), colors.beige),
            ('GRID', (0,0), (-1,-1), 1, colors.black)
        ]))
        elements.append(table)
    else:
        elements.append(Paragraph("No vessels attributed in the vicinity or AIS unavailable.", body_style))
    
    elements.append(Spacer(1, 40))
    
    # Section 4: Signature
    elements.append(Paragraph("SECTION 4: LEGAL DISCLAIMER & SIGNATURE", header_style))
    elements.append(Paragraph("This document is generated autonomously via the OASIS framework. It is intended for preliminary investigative purposes by the Indian Coast Guard.", body_style))
    elements.append(Spacer(1, 40))
    elements.append(Paragraph("___________________________________________________", body_style))
    elements.append(Paragraph("Investigating Officer Signature / Stamp", body_style))
    
    doc.build(elements)
    buffer.seek(0)
    return buffer
