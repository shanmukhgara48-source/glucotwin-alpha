"""A consultation evidence export, not treatment instructions."""
from __future__ import annotations

from html import escape
from io import BytesIO
from math import isfinite

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle


def consultation_pdf(evidence: dict, user: dict) -> bytes:
    buffer = BytesIO()
    styles = getSampleStyleSheet()
    styles["Title"].textColor = colors.HexColor("#102C43")
    styles["Heading2"].textColor = colors.HexColor("#0F766E")
    styles["Heading2"].spaceBefore = 8
    styles["Heading2"].spaceAfter = 5
    safe = lambda value: escape(str(value if value is not None else "Not recorded"))
    paragraph = lambda value: Paragraph(safe(value), styles["BodyText"])
    def number(value):
        try:
            value = float(value)
            return f"{value:.1f}".rstrip("0").rstrip(".") if isfinite(value) else "Not recorded"
        except (TypeError, ValueError):
            return "Not recorded"
    story = [Paragraph("GlucoTwin · Consultation evidence", styles["Title"]), Spacer(1, 5 * mm),
             paragraph(f"Patient: {evidence['patient']['id']} | Evidence cutoff: {evidence['at']}"),
             paragraph(f"Exported by: {user['name']} | Clinic: {user['clinic_id']}"),
             paragraph("Research prototype. Doctor workflow review pending. No medication or treatment recommendation."),
             paragraph("Recorded-data and wall-clock review timestamps are labeled separately. Clinical validation and prospective benefit are not established."), Spacer(1, 3 * mm)]
    profile = evidence["patient"]
    story.extend([Paragraph("Historical context and provenance", styles["Heading2"]),
                  paragraph(f"Source: {profile.get('source', 'ShanghaiT2DM public research dataset')}. {profile.get('provenance', 'Matched historical summary; exact availability dates unavailable. Untimed labs and medications excluded.')}"),
                  paragraph(f"Age: {number(profile.get('age'))} | Sex: {profile.get('sex') or 'Not recorded'} | BMI: {number(profile.get('bmi'))} | Diabetes duration: {number(profile.get('diabetes_duration_years'))} years")])
    observations = [row for row in evidence["events"] if row["type"] == "observation"]
    story.extend([Paragraph("Observed glucose and data coverage", styles["Heading2"]),
                  paragraph(f"Displayed evidence window: latest {len(observations)} available readings. No readings are interpolated.")])
    story.append(paragraph(f"Reading status at cutoff: {evidence['quality']['status']}. {evidence['quality']['message']} Scenario: {evidence['scenario']}."))
    if observations:
        values = [float(row["value"]) for row in observations]
        story.append(paragraph(f"Observed range: {min(values):.1f}–{max(values):.1f} mg/dL; arithmetic mean: {sum(values)/len(values):.1f} mg/dL."))
        from backend.clinic import time_key
        ordered = sorted(observations, key=lambda row: time_key(row["timestamp"]))
        gaps = sum((time_key(b["timestamp"]) - time_key(a["timestamp"])).total_seconds() > 17 * 60 for a, b in zip(ordered, ordered[1:]))
        story.append(paragraph(f"Gaps over 17 minutes in this window: {gaps}. Reading count is not a claim of complete sensor coverage."))
    story.append(Paragraph("Issued forecasts and observable outcomes", styles["Heading2"]))
    forecasts = [row for row in evidence["events"] if row["type"] == "forecast"][:12]
    rows = [[paragraph("Issue time"), paragraph("Horizon"), paragraph("Forecast / actual (mg/dL)")]]
    for event in forecasts:
        for outcome in event["outcomes"]:
            actual = f"{outcome['actual']:.1f}" if outcome["actual"] is not None else "Not yet observed / unavailable"
            rows.append([paragraph(event["timestamp"]), paragraph(f"{outcome['horizon_minutes']} min"), paragraph(f"{outcome['predicted']:.1f} / {actual}")])
    if len(rows) > 1:
        table = Table(rows, colWidths=[66 * mm, 22 * mm, 82 * mm], repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E7F4F1")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("LINEBELOW", (0, 0), (-1, -1), .3, colors.HexColor("#D8E1E8"))]))
        story.append(table)
    else:
        story.append(paragraph("No forecasts have been explicitly captured for this patient."))
    story.append(Paragraph("Unresolved reviews", styles["Heading2"]))
    open_reviews = [row for row in evidence["reviews"] if row["status"] != "closed"]
    if not open_reviews:
        story.append(paragraph("No unresolved review episodes recorded."))
    for row in open_reviews:
        story.append(paragraph(f"#{row['id']} | {row['type']} | {row['status']} | Reviewer: {row['assigned_reviewer']} | Next review: {row['next_review_at']}"))
        story.append(paragraph(row["message"]))
    story.append(Paragraph("Care-team notes and context", styles["Heading2"]))
    notes = [row for row in evidence["events"] if row["type"] in {"context", "review_action"}]
    for row in notes[:30]:
        content = f"{row.get('status', row.get('kind'))}: {row.get('reason', row.get('value'))}. {row.get('note', '')}"
        story.append(paragraph(f"{row['timestamp']} [{row['provenance']}] {content}"))
        story.append(Spacer(1, 2 * mm))
    if not notes:
        story.append(paragraph("No notes/context recorded."))
    story.append(Paragraph("Monitoring responsibility", styles["Heading2"]))
    config = evidence["monitoring"]
    story.append(paragraph(f"{config['start_hour']:02d}:00–{config['end_hour']:02d}:00 {config['timezone']}; responsible reviewer: {config['reviewer_id']}. {config['message']}"))
    def footer(canvas, document):
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#536777"))
        canvas.drawString(20 * mm, 12 * mm, "GlucoTwin | Anonymized / synthetic research evidence")
        canvas.drawRightString(190 * mm, 12 * mm, str(document.page))
    SimpleDocTemplate(buffer, pagesize=A4, rightMargin=20 * mm, leftMargin=20 * mm, topMargin=18 * mm, bottomMargin=20 * mm,
                      title="GlucoTwin consultation evidence", author="GlucoTwin").build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
