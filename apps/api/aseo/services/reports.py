"""Branded PDF reports (agency/client workspaces). Only real data is included; demo data is
labelled; health is described as an internal diagnostic."""

from __future__ import annotations

import io
import uuid
from datetime import timedelta
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aseo.models import ChangeSet, ClientWorkspace, ExecutionRun, Report, SearchMetric, SeoFinding, Site, Tenant
from aseo.models.base import utcnow
from aseo.services import audit
from aseo.services.storage import get_storage


def _safe_color(value: Any, default: str) -> colors.Color:
    try:
        v = str(value or default)
        return colors.HexColor(v if v.startswith("#") and len(v) in (4, 7) else default)
    except Exception:  # noqa: BLE001
        return colors.HexColor(default)


def _collect(db: Session, site: Site, period_days: int) -> dict[str, Any]:
    since = utcnow() - timedelta(days=period_days)
    sev = dict(db.execute(select(SeoFinding.severity, func.count()).where(SeoFinding.site_id == site.id, SeoFinding.status == "open")
                          .group_by(SeoFinding.severity)).all())
    top = db.execute(select(SeoFinding).where(SeoFinding.site_id == site.id, SeoFinding.status == "open")
                     .order_by(SeoFinding.affected_count.desc()).limit(10)).scalars().all()
    done = db.execute(select(ChangeSet, ExecutionRun).join(ExecutionRun, ExecutionRun.change_set_id == ChangeSet.id)
                      .where(ChangeSet.site_id == site.id, ExecutionRun.created_at >= since, ExecutionRun.kind == "apply")
                      .order_by(ExecutionRun.created_at.desc()).limit(20)).all()
    metrics = db.execute(select(func.sum(SearchMetric.clicks), func.sum(SearchMetric.impressions), func.min(SearchMetric.source))
                         .where(SearchMetric.site_id == site.id, SearchMetric.date >= since.date(), SearchMetric.query == "")).one()
    return {"severity": sev, "top": top, "changes": done, "clicks": metrics[0], "impressions": metrics[1], "metric_source": metrics[2]}


def _render(tenant: Tenant, ws: ClientWorkspace | None, site: Site, title: str, period_days: int, data: dict[str, Any]) -> bytes:
    branding = {**(tenant.branding or {}), **((ws.branding if ws else None) or {})}
    primary = _safe_color(branding.get("primary_color"), "#4F46E5")
    agency = branding.get("agency_name") or tenant.name
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=title, author=agency)
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=primary, alignment=0, fontSize=22)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=colors.HexColor("#1F2937"))
    small = ParagraphStyle("small", parent=ss["BodyText"], fontSize=8, textColor=colors.HexColor("#6B7280"))
    body = ss["BodyText"]
    el: list[Any] = [Paragraph(f"{agency}", small), Paragraph(title, h1),
                     Paragraph(f"{site.name} · {site.domain} · last {period_days} days · generated {utcnow():%Y-%m-%d}", small), Spacer(1, 8)]
    if site.is_demo:
        el.append(Paragraph("<b>DEMO DATA</b> — this report was generated from labelled fixture data.", body))
    el += [Paragraph("Site health (internal diagnostic)", h2),
           Paragraph(f"Score: <b>{site.health_score if site.health_score is not None else 'n/a'}</b> / 100. "
                     "This is Lodestar's internal diagnostic score, not a Google metric and not a ranking prediction.", body)]
    sev = data["severity"]
    el.append(Paragraph("Open issues by severity: " + ", ".join(f"{k}: {sev.get(k, 0)}" for k in ("critical", "high", "medium", "low", "info")), body))
    el.append(Paragraph("Top open issues", h2))
    rows = [["Issue", "Severity", "Type", "Affected"]] + [[Paragraph(f.title, body), f.severity, f.kind, str(f.affected_count)] for f in data["top"]]
    t = Table(rows, colWidths=[95 * mm, 25 * mm, 28 * mm, 20 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), primary), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                           ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E7EB")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("FONTSIZE", (0, 0), (-1, -1), 8)]))
    el += [t, Paragraph("Changes executed", h2)]
    if data["changes"]:
        crow = [["Change", "Status", "Verified", "When"]] + [
            [Paragraph(c.title, body), e.status, "yes" if e.status == "succeeded" else "no", e.created_at.strftime("%Y-%m-%d")]
            for c, e in data["changes"]]
        ct = Table(crow, colWidths=[95 * mm, 25 * mm, 20 * mm, 28 * mm])
        ct.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E7EB")), ("FONTSIZE", (0, 0), (-1, -1), 8),
                                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6"))]))
        el.append(ct)
    else:
        el.append(Paragraph("No changes were executed in this period.", body))
    el.append(Paragraph("Search performance", h2))
    if data["clicks"] is None:
        el.append(Paragraph("Search Console is not connected for this site, so no search performance is reported.", body))
    else:
        label = " (DEMO fixture data)" if data["metric_source"] == "demo_fixture" else ""
        el.append(Paragraph(f"Clicks: <b>{int(data['clicks'] or 0):,}</b> · Impressions: <b>{int(data['impressions'] or 0):,}</b>{label}", body))
    el += [Spacer(1, 10), Paragraph("Notes: Search Console data is delayed and sampled. Changes in search performance can have many causes; "
                                    "this report does not attribute ranking changes to individual fixes and does not guarantee outcomes.", small)]
    doc.build(el)
    return buf.getvalue()


def generate(db: Session, tenant: Tenant, site: Site, ws: ClientWorkspace | None, *, title: str | None, period_days: int,
             created_by: uuid.UUID | None) -> Report:
    title = title or f"SEO report — {site.name}"
    r = Report(tenant_id=tenant.id, workspace_id=ws.id if ws else None, site_id=site.id, title=title, status="generating",
               period_start=(utcnow() - timedelta(days=period_days)).date(), period_end=utcnow().date(),
               branding={**(tenant.branding or {}), **((ws.branding if ws else None) or {})}, created_by=created_by)
    db.add(r)
    db.flush()
    pdf = _render(tenant, ws, site, title, period_days, _collect(db, site, period_days))
    r.storage_key = get_storage().put(f"{tenant.id}/reports/{r.id}.pdf", pdf)
    r.status = "ready"
    r.generated_at = utcnow()
    audit.record(db, tenant_id=tenant.id, action="report.generated", actor_id=created_by, target_type="report", target_id=r.id,
                 site_id=site.id, data={"title": title})
    return r


def load_pdf(r: Report) -> bytes | None:
    return get_storage().get(r.storage_key) if r.storage_key else None
