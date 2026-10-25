"""HTTP API.

Every endpoint validates its input, returns a predictable shape, and converts
an internal failure into a message a dashboard can display rather than a stack
trace. Nothing here ever returns the NASA key or echoes it into an error.
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from app.config import settings
from app.schemas import (
    ClassifiedEvent,
    ClassifyRequest,
    EventsResponse,
    Facility,
    HealthResponse,
    HotspotEvent,
)
from app.api.provenance import build_sources
from app.services import events as events_service
from app.services import incidents as incidents_service
from app.services import firms as firms_service
from app.services import landcover as landcover_service
from app.services import osm as osm_service
from app.services import pipeline, replay as replay_service, snapshot as snapshot_service
from app.services import verdict as verdict_service
from app.services.classifier import DISCLAIMER, get_classifier
from app.services.geo import GridPoint, SpatialGrid, bbox_around, haversine_km, parse_bbox
from app.services.labeling import policy_summary
from app.services.priority import compute_priority, formula_description
from app.services.recurrence import HistoryIndex
from app.schemas import Evidence
from app.store.db import get_store
from app.taxonomy import (
    ALL_CLASSES,
    CLASS_CODES,
    CLASS_COLORS,
    CLASS_DESCRIPTIONS,
    CLASS_LABELS,
    DISPLAY_STATUSES,
    FACILITY_LABELS,
    LAND_COVER_LABELS,
    STATUS_COLORS,
    STATUS_LABELS,
    STATUS_MEANINGS,
    STATUS_RANK,
    TRAINED_CLASSES,
)

log = logging.getLogger("firetrace.api")
router = APIRouter()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@router.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    classifier = get_classifier()
    store = get_store()
    snap_ok = snapshot_service.snapshot_available()

    # The service is "ok" as long as it can still do its job from SOMETHING:
    # a model plus either live data or the snapshot.
    degraded = (not classifier.loaded) or (not snap_ok and not settings.has_firms_key)

    return HealthResponse(
        status="degraded" if degraded else "ok",
        app=settings.app_name,
        version=settings.app_version,
        model_loaded=classifier.loaded,
        firms_key_configured=settings.has_firms_key,
        store_ready=store.ready,
        snapshot_available=snap_ok,
        checks={
            "model": classifier.status_note,
            "store_events": store.event_count(),
            "store_facilities": store.facility_count(),
            "store_error": store.error,
            "snapshot": (
                snapshot_service.load_snapshot().summary()
                if snap_ok and snapshot_service.load_snapshot()
                else "not present"
            ),
            "last_ingest": store.last_ingest(),
        },
    )


# ---------------------------------------------------------------------------
# Reference data for the dashboard
# ---------------------------------------------------------------------------
@router.get("/api/meta", tags=["system"])
def meta() -> dict:
    """Vocabularies, colours and thresholds, so the UI never hardcodes them."""
    return {
        "classes": [
            {
                "id": c,
                "label": CLASS_LABELS[c],
                "code": CLASS_CODES[c],
                "color": CLASS_COLORS[c],
                "description": CLASS_DESCRIPTIONS[c],
                "trained": c in TRAINED_CLASSES,
            }
            for c in ALL_CLASSES
        ],
        "land_cover": [{"id": k, "label": v} for k, v in LAND_COVER_LABELS.items()],
        "facility_categories": [{"id": k, "label": v} for k, v in FACILITY_LABELS.items()],
        "confidence_thresholds": {
            "high": settings.confidence_high_threshold,
            "medium": settings.confidence_medium_threshold,
            "abstention": settings.unknown_abstention_threshold,
        },
        "priority": formula_description(),
        "feature_config": {
            "facility_search_radius_km": settings.facility_search_radius_km,
            "facility_onsite_km": settings.facility_onsite_km,
            "recurrence_radius_km": settings.recurrence_radius_km,
            "recurrence_lookback_days": settings.recurrence_lookback_days,
            "density_radius_km": settings.density_radius_km,
        },
        "default_bbox": settings.firms_default_bbox,
        "max_day_range": settings.firms_max_day_range,
        "disclaimer": DISCLAIMER,
    }


@router.get("/api/sources", tags=["system"])
def sources() -> dict:
    """Data provenance, read from the live store and files at request time."""
    return build_sources()


@router.get("/api/model/info", tags=["model"])
def model_info() -> dict:
    classifier = get_classifier()
    info = classifier.info().model_dump()
    info["metrics"] = classifier.metadata.get("metrics", {})
    info["training_summary"] = classifier.metadata.get("training_summary", {})
    info["hyperparameters"] = classifier.metadata.get("hyperparameters", {})
    info["label_policy"] = policy_summary()
    info["abstention"] = {
        "threshold": settings.unknown_abstention_threshold,
        "low_evidence_threshold": settings.low_evidence_abstention_threshold,
        "note": (
            "UNKNOWN is not a trained class. It is applied when the model's top "
            "probability falls below this threshold, so the system abstains instead "
            "of forcing a weak guess."
        ),
        "evidence_gate": (
            "The bar rises when the discriminating evidence was unavailable. Two of "
            "the model's strongest features are proximity to a mapped industrial "
            "facility and land cover; when a detection has neither, the forest is "
            "voting mostly on position and radiative power and will still return a "
            "confident-looking number. On a live India-wide query in September — "
            "outside any crop-residue burning season — the ungated model called 810 "
            "of 900 detections agricultural burning at a median confidence of 0.66, "
            "of which 800 had no land cover and 804 had no facility within 12 km. "
            "With the gate applied that falls to 164, and the rest are reported as "
            "unclassified with the reason stated."
        ),
    }
    info["top_features"] = classifier.metadata.get("top_features", [])
    return info


# ---------------------------------------------------------------------------
# Hotspots
# ---------------------------------------------------------------------------
@router.get("/api/hotspots", response_model=EventsResponse, tags=["hotspots"])
def hotspots(
    bbox: str | None = Query(None, description="west,south,east,north"),
    days: int = Query(settings.firms_default_day_range, ge=1, le=5),
    mode: str = Query("auto", pattern="^(auto|live|demo)$"),
    classification: str | None = Query(None, description="Comma-separated class ids"),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    priority: str | None = Query(None, description="Comma-separated HIGH,MEDIUM,LOW"),
    max_facility_km: float | None = Query(None, ge=0, le=500),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    persistent_only: bool = Query(False),
    limit: int = Query(500, ge=1, le=2000),
    refresh: bool = Query(False),
) -> EventsResponse:
    """Classified thermal events for an area, with filters applied server-side."""
    try:
        result = pipeline.run_analysis(bbox, days=days, mode=mode, force_refresh=refresh)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("[API] analysis failed")
        raise HTTPException(
            status_code=503,
            detail=f"Analysis could not be completed ({type(exc).__name__}). Try demo mode.",
        ) from exc

    filtered = _apply_filters(
        result.events,
        classification=classification,
        min_confidence=min_confidence,
        priority=priority,
        max_facility_km=max_facility_km,
        date_from=date_from,
        date_to=date_to,
        persistent_only=persistent_only,
    )

    return EventsResponse(
        status=result.status,  # type: ignore[arg-type]
        summary=pipeline.summarise(filtered),
        events=filtered[:limit],
        returned=min(len(filtered), limit),
        total_matching=len(filtered),
    )


@router.get("/api/hotspots/{event_id}", response_model=ClassifiedEvent, tags=["hotspots"])
def hotspot_detail(
    event_id: str,
    bbox: str | None = Query(None),
    days: int = Query(settings.firms_default_day_range, ge=1, le=5),
    mode: str = Query("auto", pattern="^(auto|live|demo)$"),
) -> ClassifiedEvent:
    """One event, with its explanation computed if it was not already."""
    try:
        result = pipeline.run_analysis(bbox, days=days, mode=mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    for item in result.events:
        if item.event.event_id == event_id:
            if not item.factors:
                item.factors = get_classifier().explain_one(
                    item.event,
                    item.evidence.nearest_facility,
                    item.evidence.land_cover,
                    item.evidence.recurrence,
                    item.classification.top_trained_label,
                    item.classification.abstained,
                )
            return item

    raise HTTPException(status_code=404, detail=f"No event with id {event_id} in the current view.")


@router.get("/api/events", tags=["events"])
def fire_events(
    bbox: str | None = Query(None),
    days: int = Query(settings.firms_default_day_range, ge=1, le=5),
    mode: str = Query("auto", pattern="^(auto|live|demo)$"),
    priority: str | None = Query(None, description="Comma-separated HIGH,MEDIUM,LOW"),
    limit: int = Query(200, ge=1, le=1000),
) -> dict:
    """Detections grouped into fire events.

    A satellite sees hot pixels, not fires. One fire across three overpasses is a
    dozen FIRMS rows; this endpoint returns the incident, not the pixels.
    """
    import time as _time

    started = _time.perf_counter()
    try:
        result = pipeline.run_analysis(bbox, days=days, mode=mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    analysis_ms = (_time.perf_counter() - started) * 1000
    cluster_started = _time.perf_counter()
    grouped = events_service.cluster(result.events)
    cluster_ms = (_time.perf_counter() - cluster_started) * 1000

    # Raising an alert is a side effect of seeing the event, not a separate
    # button someone has to remember to press. Existing incidents keep their
    # status and assignee.
    alert_started = _time.perf_counter()
    synced = incidents_service.sync(grouped)
    alert_ms = (_time.perf_counter() - alert_started) * 1000

    wanted = (
        {p.strip().upper() for p in priority.split(",") if p.strip()} if priority else None
    )
    if wanted:
        grouped = [e for e in grouped if e.priority_level in wanted]

    by_priority: dict[str, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    by_class: dict[str, int] = {}
    for e in grouped:
        by_priority[e.priority_level] = by_priority.get(e.priority_level, 0) + 1
        by_class[e.label] = by_class.get(e.label, 0) + 1

    multi = [e for e in grouped if e.detection_count > 1]

    return {
        "status": result.status.model_dump() if result.status else None,
        "config": events_service.config_summary(),
        "summary": {
            "detections": len(result.events),
            "events": len(grouped),
            "multi_detection_events": len(multi),
            "largest_event_detections": max((e.detection_count for e in grouped), default=0),
            "by_priority": by_priority,
            "by_class": by_class,
            "compression": (
                round(len(result.events) / len(grouped), 2) if grouped else None
            ),
        },
        "alerts": {
            **synced,
            "rule": incidents_service.alert_rule_summary(),
            "open_incidents": incidents_service.counts().get("open", 0),
        },
        "timing_ms": {
            "analysis": round(analysis_ms, 1),
            "clustering": round(cluster_ms, 1),
            "alerting": round(alert_ms, 1),
            "total": round(analysis_ms + cluster_ms + alert_ms, 1),
        },
        "events": [
            {
                **{k: v for k, v in e.__dict__.items() if k != "detection_ids"},
                "first_detected": e.first_detected.isoformat(),
                "last_detected": e.last_detected.isoformat(),
                "detection_ids": e.detection_ids[:60],
            }
            for e in grouped[:limit]
        ],
    }


@router.get("/api/events/{event_id}", tags=["events"])
def fire_event_detail(
    event_id: str,
    bbox: str | None = Query(None),
    days: int = Query(settings.firms_default_day_range, ge=1, le=5),
    mode: str = Query("auto", pattern="^(auto|live|demo)$"),
) -> dict:
    """One fire event with every detection that composes it."""
    try:
        result = pipeline.run_analysis(bbox, days=days, mode=mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    grouped = events_service.cluster(result.events)
    match = next((e for e in grouped if e.event_id == event_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"No fire event {event_id} in the current view.")

    by_id = {c.event.event_id: c for c in result.events}
    detections = [by_id[d] for d in match.detection_ids if d in by_id]
    detections.sort(key=lambda c: c.event.acquired_at)

    lead = by_id.get(match.lead_detection_id)
    if lead is not None and not lead.factors:
        lead.factors = get_classifier().explain_one(
            lead.event,
            lead.evidence.nearest_facility,
            lead.evidence.land_cover,
            lead.evidence.recurrence,
            lead.classification.top_trained_label,
            lead.classification.abstained,
        )

    return {
        "event": {
            **{k: v for k, v in match.__dict__.items()},
            "first_detected": match.first_detected.isoformat(),
            "last_detected": match.last_detected.isoformat(),
        },
        "config": events_service.config_summary(),
        "lead_detection": lead.model_dump() if lead else None,
        "detections": [d.model_dump() for d in detections],
        "timeline": [
            {
                "detection_id": d.event.event_id,
                "acquired_at": d.event.acquired_at.isoformat(),
                "satellite": d.event.satellite,
                "product": d.event.source_product,
                "frp_mw": d.event.frp_mw,
                "brightness_k": d.event.brightness_k,
                "confidence": d.event.firms_confidence_level,
                "classification": d.classification.label,
                "model_confidence": d.classification.confidence,
                "latitude": d.event.latitude,
                "longitude": d.event.longitude,
            }
            for d in detections
        ],
    }


class IncidentAction(BaseModel):
    """An operator action on an incident.

    `actor` is a name typed at the console. There is no authentication in this
    prototype, so it is recorded for traceability, not as proof of identity.
    """

    action: str
    actor: str = "operator"
    note: str | None = None


# ---------------------------------------------------------------------------
# Map — the single screen
# ---------------------------------------------------------------------------
# One request serves the whole main screen. It returns grouped sites rather
# than raw pixels, the four-word display status for each, and a provenance
# block that names exactly which of the five data states the screen is in.
#
# Deliberately lean: `model` and `disclaimer` are identical on every event, so
# they are hoisted to the envelope instead of repeated per site (that
# duplication alone was ~320 KB of the old 1.46 MB /api/hotspots payload).


def _provenance(requested_mode: str, status, n_events: int) -> dict:
    """Name the data state. Never ambiguous, never flattering.

    Five states, matching what the UI chip can render:
      live        — fetched from NASA now, detections present
      live_empty  — fetched from NASA now, genuinely nothing in the window
      offline     — a live attempt failed, so saved data is on screen
      replay      — the frozen historical archive, chosen deliberately
      unavailable — nothing to show at all
    """
    if status is None:
        return {
            "state": "unavailable",
            "label": "No data",
            "detail": "The analysis returned no status block.",
            "is_live": False,
        }

    resolved = status.mode
    firms = status.firms_status

    if resolved == "live":
        if firms == "ok" and n_events > 0:
            state, label = "live", "Live · NASA FIRMS"
        elif firms == "no_data":
            state, label = "live_empty", "Live · no detections in window"
        else:
            state, label = "unavailable", "Live feed unavailable"
    elif resolved == "cached":
        # Real NASA data, but not fetched now. Never shown as live.
        state, label = "offline", "Offline · showing saved data"
    else:
        if requested_mode == "demo":
            state, label = "replay", "Replay · real historical detections"
        elif firms in ("unavailable", "not_configured", "cached") or not status.firms_products_used:
            state, label = "offline", "Offline · showing saved data"
        else:
            state, label = "replay", "Replay · real historical detections"

    return {
        "state": state,
        "label": label,
        "detail": status.firms_message,
        "is_live": state == "live",
        "source": "NASA FIRMS",
        "products": status.firms_products_used,
        "geographic_context": status.osm_message,
        # Observation time and retrieval time are different facts and are kept
        # apart everywhere. `retrieved_at` is when FIRETRACE asked; the per-site
        # `observed_at` is when the satellite saw it.
        "retrieved_at": status.last_updated.isoformat() if status.last_updated else None,
        "archive_note": status.snapshot_note,
    }


# Facility "names" that are really category labels, so a site titled with one of
# them is an unnamed OSM feature rather than an identified plant.
_GENERIC_FACILITY_LABELS = set(FACILITY_LABELS.values())


def _coord_title(lat: float, lon: float) -> str:
    """A readable, unique identity for a site with no mapped facility."""
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{abs(lat):.3f}°{ns}, {abs(lon):.3f}°{ew}"


def _title(e, facility: str | None, near: bool) -> str:
    """A name an operator can tell apart from the one above it in the queue.

    Many OpenStreetMap industrial features have no `name` tag, so the context
    layer falls back to the category label. Three unnamed gas/oil features then
    produced three rows all reading "Gas / oil infrastructure", which is useless
    as a work list. When the name is a generic category label rather than a real
    one, the position is appended to disambiguate.
    """
    if not (facility and near):
        return _coord_title(e.latitude, e.longitude)
    if facility in _GENERIC_FACILITY_LABELS:
        return f"{facility} · {_coord_title(e.latitude, e.longitude)}"
    return facility


def _subtitle(e, facility: str | None, near: bool) -> str:
    """Where this is, relative to mapped industry. Never implies causation."""
    if facility and near:
        if e.nearest_facility_km is not None and e.nearest_facility_km > 0.75:
            return f"{e.nearest_facility_km:.2f} km from {facility}"
        return f"On the {facility} site"
    if e.nearest_facility_km is not None:
        return f"{e.label_display} · {e.nearest_facility_km:.1f} km from {facility or 'mapped industry'}"
    return f"{e.label_display} · no mapped facility within range"


def _site(e) -> dict:
    """One grouped site, trimmed to what the main screen actually renders."""
    status_key = verdict_service.display_status(e)
    facility = e.nearest_facility_name
    near = e.nearest_facility_km is not None and e.nearest_facility_km <= 3.0

    return {
        "id": e.event_id,
        "lat": e.latitude,
        "lon": e.longitude,
        "status": status_key,
        "status_label": STATUS_LABELS[status_key],
        # No reverse geocoding is available, so a site is named after the mapped
        # facility when there is one and after its position when there is not.
        # Nothing here invents a place name. Naming the unnamed ones after their
        # class produced 150 identical "Unclassified" rows in the queue, which
        # told the operator nothing; coordinates at least identify the site.
        "title": _title(e, facility, near),
        "subtitle": _subtitle(e, facility, near),
        "verdict": verdict_service.verdict_sentence(e),
        "why": verdict_service.why_bullets(e),
        "missing": verdict_service.missing_evidence(e),
        "evidence_completeness": verdict_service.evidence_completeness(e),
        # Classification and score stay separate and separately labelled.
        "predicted_class": e.label,
        "predicted_class_display": e.label_display,
        "model_score": e.label_confidence,
        "abstained": e.label == "UNKNOWN",
        "operational_priority": e.priority_level,
        "priority_score": e.priority_score,
        "abnormality_score": e.abnormality_score,
        "abnormality_status": e.abnormality_status,
        "detection_count": e.detection_count,
        "distinct_passes": e.distinct_passes,
        "distinct_days": e.distinct_days,
        "history_available": e.history_available,
        "persistent": e.persistent,
        "frp_max_mw": e.frp_max_mw,
        "frp_total_mw": e.frp_total_mw,
        "brightness_max_k": e.brightness_max_k,
        "nearest_facility_name": facility,
        "nearest_facility_km": e.nearest_facility_km,
        "land_cover": e.land_cover,
        "observed_at": e.last_detected.isoformat(),
        "first_observed_at": e.first_detected.isoformat(),
        "products": e.products,
        "lead_detection_id": e.lead_detection_id,
    }


@router.get("/api/map", tags=["map"])
def map_view(
    bbox: str | None = Query(None),
    days: int = Query(settings.firms_default_day_range, ge=1, le=5),
    mode: str = Query("auto", pattern="^(auto|live|demo)$"),
    limit: int = Query(1000, ge=1, le=2000),
) -> dict:
    """Everything the main screen needs, in one request."""
    try:
        result = pipeline.run_analysis(bbox, days=days, mode=mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    grouped = events_service.cluster(result.events)
    sites = [_site(e) for e in grouped]

    counts = {key: 0 for key in DISPLAY_STATUSES}
    for s in sites:
        counts[s["status"]] += 1

    # Triage order: needs attention first, then unresolved, then by priority.
    sites.sort(key=lambda s: (STATUS_RANK[s["status"]], -s["priority_score"]))

    model = get_classifier().info()
    return {
        "provenance": _provenance(mode, result.status, len(result.events)),
        "counts": {**counts, "sites": len(sites), "detections": len(result.events)},
        "status_vocabulary": [
            {
                "key": k,
                "label": STATUS_LABELS[k],
                "meaning": STATUS_MEANINGS[k],
                "color": STATUS_COLORS[k],
            }
            for k in DISPLAY_STATUSES
        ],
        "window": {
            "days_requested": days,
            "observed_from": min((s["first_observed_at"] for s in sites), default=None),
            "observed_to": max((s["observed_at"] for s in sites), default=None),
        },
        "model": {
            "model_version": model.model_version,
            "algorithm": model.algorithm,
            "n_features": model.n_features,
            "loaded": model.loaded,
            "score_note": (
                "model_score is an uncalibrated Random Forest vote share for the "
                "leading trained class. It is not a probability of correctness."
            ),
        },
        "disclaimer": DISCLAIMER,
        "sites": sites[:limit],
        "truncated": max(0, len(sites) - limit),
    }


@router.get("/api/map/search", tags=["map"])
def map_search(
    q: str = Query(..., min_length=2, max_length=80),
    bbox: str | None = Query(None),
    days: int = Query(settings.firms_default_day_range, ge=1, le=5),
    mode: str = Query("auto", pattern="^(auto|live|demo)$"),
    limit: int = Query(6, ge=1, le=20),
) -> dict:
    """Search mapped industrial facilities and the sites currently on screen.

    Scope is deliberately narrow and stated in the UI placeholder: this searches
    real OpenStreetMap facility names and the current sites. It is not a
    geocoder — there is no place-name database behind it, and offering one
    would mean most Indian city names returning nothing.
    """
    needle = q.strip().lower()
    try:
        result = pipeline.run_analysis(bbox, days=days, mode=mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    hits: list[dict] = []
    seen: set[str] = set()

    # Sites first: a match the user can act on immediately beats a bare facility.
    for e in events_service.cluster(result.events):
        name = e.nearest_facility_name or ""
        if needle not in name.lower() and needle not in e.label_display.lower():
            continue
        key = f"site:{e.event_id}"
        if key in seen:
            continue
        seen.add(key)
        status_key = verdict_service.display_status(e)
        hits.append({
            "kind": "site",
            "id": e.event_id,
            "name": name or e.label_display,
            "detail": STATUS_LABELS[status_key],
            "status": status_key,
            "lat": e.latitude,
            "lon": e.longitude,
        })

    # Then mapped facilities with no current detection. Being explicit that
    # there is no activity is useful information, not an empty result.
    for f in result.facilities:
        if not f.name or needle not in f.name.lower():
            continue
        key = f"fac:{f.facility_id}"
        if key in seen:
            continue
        seen.add(key)
        hits.append({
            "kind": "facility",
            "id": f.facility_id,
            "name": f.name,
            "detail": f"{f.category_label} · no detection in this window",
            "status": None,
            "lat": f.latitude,
            "lon": f.longitude,
        })

    hits.sort(key=lambda h: (h["kind"] != "site", len(h["name"])))
    return {"query": q, "results": hits[:limit], "total_matches": len(hits)}


@router.get("/api/incidents", tags=["incidents"])
def list_incidents(
    status: str | None = Query(None, description="open | closed | a specific status"),
    limit: int = Query(200, ge=1, le=1000),
) -> dict:
    """The incident queue: fire events that crossed the alert rule."""
    return {
        "counts": incidents_service.counts(),
        "lifecycle": incidents_service.lifecycle_summary(),
        "alert_rule": incidents_service.alert_rule_summary(),
        "incidents": incidents_service.list_incidents(status=status, limit=limit),
    }


@router.get("/api/incidents/{event_id}", tags=["incidents"])
def incident_detail(event_id: str) -> dict:
    """One incident with its full action log."""
    incident = incidents_service.get_incident(event_id)
    if incident is None:
        raise HTTPException(status_code=404, detail=f"No incident {event_id}.")
    return incident


@router.post("/api/incidents/{event_id}/action", tags=["incidents"])
def incident_action(event_id: str, body: IncidentAction) -> dict:
    """Acknowledge, dispatch, monitor, resolve, dismiss, reopen, assign or note.

    Illegal transitions are rejected rather than silently applied, so the audit
    log cannot contain an impossible sequence.
    """
    try:
        return incidents_service.act(
            event_id, action=body.action, actor=body.actor, note=body.note
        )
    except incidents_service.IncidentError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/dashboard/summary", tags=["hotspots"])
def dashboard_summary(
    bbox: str | None = Query(None),
    days: int = Query(settings.firms_default_day_range, ge=1, le=5),
    mode: str = Query("auto", pattern="^(auto|live|demo)$"),
) -> dict:
    """Headline counts plus small distributions for the dashboard charts."""
    try:
        result = pipeline.run_analysis(bbox, days=days, mode=mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    summary = pipeline.summarise(result.events)
    by_day: dict[str, int] = {}
    frp_by_class: dict[str, float] = {}
    for item in result.events:
        key = item.event.acquisition_date.isoformat()
        by_day[key] = by_day.get(key, 0) + 1
        label = item.classification.label
        frp_by_class[label] = round(frp_by_class.get(label, 0.0) + (item.event.frp_mw or 0.0), 2)

    return {
        "status": result.status.model_dump() if result.status else None,
        "summary": summary.model_dump(),
        "timeline": [{"date": k, "count": by_day[k]} for k in sorted(by_day)],
        "frp_by_class": frp_by_class,
        "facilities_in_view": len(result.facilities),
    }


# ---------------------------------------------------------------------------
# Facilities
# ---------------------------------------------------------------------------
@router.get("/api/facilities/nearby", tags=["facilities"])
def facilities_nearby(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(10.0, gt=0, le=100),
    limit: int = Query(25, ge=1, le=200),
) -> dict:
    """Industrial features around a point, nearest first."""
    store = get_store()
    box = bbox_around(lat, lon, radius_km)
    facilities = store.load_facilities(box)
    source = "local cache"

    if not facilities:
        try:
            facilities, status = osm_service.fetch_facilities(box)
            if facilities:
                store.upsert_facilities(facilities)
                source = f"OpenStreetMap ({status})"
        except Exception as exc:  # noqa: BLE001
            log.warning("[API] nearby facility lookup failed: %s", type(exc).__name__)

    if not facilities:
        snap = snapshot_service.load_snapshot()
        if snap:
            facilities = snap.facilities
            source = "frozen snapshot"

    hits = []
    for f in facilities:
        d = haversine_km(lat, lon, f.latitude, f.longitude)
        if d <= radius_km:
            hits.append({**f.model_dump(), "distance_km": round(d, 3)})
    hits.sort(key=lambda h: h["distance_km"])

    return {
        "query": {"latitude": lat, "longitude": lon, "radius_km": radius_km},
        "source": source,
        "count": len(hits),
        "facilities": hits[:limit],
    }


@router.get("/api/facilities", tags=["facilities"])
def facilities_in_view(
    bbox: str | None = Query(None),
    days: int = Query(settings.firms_default_day_range, ge=1, le=5),
    mode: str = Query("auto", pattern="^(auto|live|demo)$"),
    limit: int = Query(600, ge=1, le=3000),
) -> dict:
    """Facility layer for the map."""
    try:
        result = pipeline.run_analysis(bbox, days=days, mode=mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "count": len(result.facilities),
        "returned": min(len(result.facilities), limit),
        "facilities": [f.model_dump() for f in result.facilities[:limit]],
    }


# ---------------------------------------------------------------------------
# Ad-hoc classification
# ---------------------------------------------------------------------------
@router.post("/api/classify", response_model=ClassifiedEvent, tags=["model"])
def classify_point(request: ClassifyRequest) -> ClassifiedEvent:
    """Classify an arbitrary coordinate.

    Used by the "what would FIRETRACE say about this spot?" tool in the
    dashboard. Geographic and historical context is gathered for the point the
    same way it is for a real detection.
    """
    acq_date = request.acquisition_date or datetime.now(timezone.utc).date()
    raw_time = (request.acquisition_time or "12:00").replace(":", "")
    acq_time = firms_service._normalize_time(raw_time)
    hh, mm = (int(x) for x in acq_time.split(":"))

    conf_raw, conf_level = firms_service.normalize_confidence(request.firms_confidence, None)

    unavailable = []
    if request.brightness_k is None:
        unavailable.append("brightness_k")
    if request.frp_mw is None:
        unavailable.append("frp_mw")

    event = HotspotEvent(
        event_id=firms_service.make_event_id(
            request.latitude, request.longitude, acq_date.isoformat(), acq_time, "MANUAL"
        ),
        latitude=request.latitude,
        longitude=request.longitude,
        acquisition_date=acq_date,
        acquisition_time=acq_time,
        acquired_at=datetime(acq_date.year, acq_date.month, acq_date.day, hh, mm, tzinfo=timezone.utc),
        brightness_k=request.brightness_k,
        brightness_secondary_k=None,
        frp_mw=request.frp_mw,
        firms_confidence_raw=conf_raw,
        firms_confidence_level=conf_level,  # type: ignore[arg-type]
        satellite=None,
        instrument=None,
        day_night=request.day_night,
        source_product="MANUAL_INPUT",
        source_mode="snapshot",
        raw_source_reference="User-supplied coordinate via /api/classify",
        ingested_at=datetime.now(timezone.utc),
        unavailable_fields=unavailable,
    )

    store = get_store()
    box = bbox_around(request.latitude, request.longitude, settings.facility_search_radius_km)

    facilities = store.load_facilities(box)
    if not facilities:
        try:
            facilities, _ = osm_service.fetch_facilities(box)
            if facilities:
                store.upsert_facilities(facilities)
        except Exception:  # noqa: BLE001
            facilities = []
    if not facilities:
        snap = snapshot_service.load_snapshot()
        facilities = snap.facilities if snap else []

    grid = SpatialGrid(
        (GridPoint(lat=f.latitude, lon=f.longitude, payload=f) for f in facilities),
        cell_degrees=0.1,
    )
    nearest = pipeline._nearest_facility(grid, event)

    snap = snapshot_service.load_snapshot()
    provider, _ = landcover_service.build_provider(
        [(request.latitude, request.longitude)],
        snapshot_polygons=snap.landuse if snap else None,
        allow_network=True,
    )
    land_cover = provider.lookup(request.latitude, request.longitude)

    history = store.load_events(bbox=bbox_around(request.latitude, request.longitude, 5.0))
    if not history and snap:
        history = snap.events
    recurrence = HistoryIndex(history).compute(event)

    classifier = get_classifier()
    classification, probabilities, factors = classifier.predict(
        event, nearest, land_cover, recurrence
    )
    priority = compute_priority(event, classification, nearest, recurrence)

    return ClassifiedEvent(
        event=event,
        classification=classification,
        probabilities=probabilities,
        evidence=Evidence(
            distance_to_nearest_facility_km=round(nearest.distance_km, 3) if nearest else None,
            nearest_facility=nearest,
            land_cover=land_cover,
            recurrence=recurrence,
            thermal_intensity_k=event.brightness_k,
            frp_mw=event.frp_mw,
            firms_confidence=event.firms_confidence_level,
            day_night=event.day_night,
        ),
        factors=factors,
        priority=priority,
        model=classifier.info(),
        disclaimer=DISCLAIMER,
    )


# ---------------------------------------------------------------------------
# Demo replay
# ---------------------------------------------------------------------------
@router.get("/api/replay/catalogue", tags=["replay"])
def replay_catalogue(refresh: bool = Query(False)) -> dict:
    """Replayable historical cases, each pointing at a real FIRMS detection.

    Cases are derived by running the real pipeline over the snapshot and
    selecting detections that genuinely satisfy each scenario predicate, so a
    scenario the data does not support simply does not appear.
    """
    return replay_service.build_catalogue(force=refresh)


@router.get("/api/replay/case/{case_id:path}", tags=["replay"])
def replay_case(case_id: str) -> dict:
    """The source record for one case, before anything has been run on it."""
    case = replay_service.get_case(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"No replay case {case_id}.")
    return case


@router.post("/api/replay/run/{case_id:path}", tags=["replay"])
def replay_run(
    case_id: str,
    persist: bool = Query(True, description="Write detections and incidents to the store."),
) -> dict:
    """Execute the real pipeline on one historical case and report every stage.

    This runs the same functions the live dashboard runs. It does not insert a
    precomputed result, and the alert level comes from evaluating the alert rule
    on the clustered event, not from a stored flag.
    """
    try:
        return replay_service.replay(case_id, persist=persist)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"No replay case {case_id}.") from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("[REPLAY] run failed for %s", case_id)
        raise HTTPException(
            status_code=500, detail=f"Replay failed ({type(exc).__name__}): {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Demo scenarios
# ---------------------------------------------------------------------------
@router.get("/api/scenarios", tags=["demo"])
def scenarios() -> dict:
    """Curated demo scenarios, each pointing at a real detection in the snapshot."""
    snap = snapshot_service.load_snapshot()
    if snap is None:
        return {"available": False, "scenarios": [], "note": "No snapshot present."}
    return {
        "available": True,
        "snapshot": snap.summary(),
        "scenarios": snap.scenarios,
    }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
@router.get("/api/export/json", tags=["export"])
def export_json(
    bbox: str | None = Query(None),
    days: int = Query(settings.firms_default_day_range, ge=1, le=5),
    mode: str = Query("auto", pattern="^(auto|live|demo)$"),
) -> dict:
    """Export the canonical classified-event representation as JSON.

    Unlike a presentation-oriented CSV, this preserves nested evidence,
    provenance and model fields so another analysis tool can reproduce what an
    operator saw. It deliberately exports the evaluated query only; no source
    credentials or hidden configuration are included.
    """
    result = pipeline.run_analysis(bbox, days=days, mode=mode)
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "query": {"bbox": bbox, "days": days, "mode": mode},
        "status": result.status.model_dump(mode="json") if result.status else None,
        "record_count": len(result.events),
        "events": [item.model_dump(mode="json") for item in result.events],
        "provenance": {
            "source": "NASA FIRMS and OpenStreetMap context",
            "data_mode": result.status.mode if result.status else "unknown",
            "disclaimer": DISCLAIMER,
        },
    }


@router.get("/api/export/geojson", tags=["export"])
def export_geojson(
    bbox: str | None = Query(None),
    days: int = Query(settings.firms_default_day_range, ge=1, le=5),
    mode: str = Query("auto", pattern="^(auto|live|demo)$"),
) -> dict:
    result = pipeline.run_analysis(bbox, days=days, mode=mode)
    features = []
    for item in result.events:
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [item.event.longitude, item.event.latitude],
                },
                "properties": {
                    "event_id": item.event.event_id,
                    "acquired_at": item.event.acquired_at.isoformat(),
                    "classification": item.classification.label,
                    "classification_display": item.classification.label_display,
                    "model_confidence": item.classification.confidence,
                    "confidence_level": item.classification.confidence_level,
                    "priority_score": item.priority.score,
                    "priority_level": item.priority.level,
                    "frp_mw": item.event.frp_mw,
                    "brightness_k": item.event.brightness_k,
                    "distance_to_facility_km": item.evidence.distance_to_nearest_facility_km,
                    "nearest_facility": (
                        item.evidence.nearest_facility.name
                        if item.evidence.nearest_facility
                        else None
                    ),
                    "land_cover": item.evidence.land_cover.category,
                    "distinct_days": item.evidence.recurrence.distinct_days,
                    "source_product": item.event.source_product,
                    "data_mode": item.event.source_mode,
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data_mode": result.status.mode if result.status else "unknown",
            "disclaimer": DISCLAIMER,
        },
    }


@router.get("/api/export/csv", tags=["export"])
def export_csv(
    bbox: str | None = Query(None),
    days: int = Query(settings.firms_default_day_range, ge=1, le=5),
    mode: str = Query("auto", pattern="^(auto|live|demo)$"),
) -> Response:
    result = pipeline.run_analysis(bbox, days=days, mode=mode)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "event_id",
            "acquired_at_utc",
            "latitude",
            "longitude",
            "classification",
            "model_confidence",
            "confidence_level",
            "priority_score",
            "priority_level",
            "frp_mw",
            "brightness_k",
            "distance_to_facility_km",
            "nearest_facility",
            "facility_category",
            "land_cover",
            "distinct_days",
            "source_product",
            "data_mode",
        ]
    )
    for item in result.events:
        nf = item.evidence.nearest_facility
        writer.writerow(
            [
                item.event.event_id,
                item.event.acquired_at.isoformat(),
                item.event.latitude,
                item.event.longitude,
                item.classification.label,
                item.classification.confidence,
                item.classification.confidence_level,
                item.priority.score,
                item.priority.level,
                item.event.frp_mw if item.event.frp_mw is not None else "",
                item.event.brightness_k if item.event.brightness_k is not None else "",
                item.evidence.distance_to_nearest_facility_km
                if item.evidence.distance_to_nearest_facility_km is not None
                else "",
                nf.name if nf else "",
                nf.category if nf else "",
                item.evidence.land_cover.category,
                item.evidence.recurrence.distinct_days,
                item.event.source_product,
                item.event.source_mode,
            ]
        )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=firetrace_events.csv"},
    )


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------
class RefreshResponse(BaseModel):
    refreshed: bool
    message: str
    firms_key_status: dict


@router.post("/api/refresh", response_model=RefreshResponse, tags=["system"])
def refresh() -> RefreshResponse:
    """Drop the analysis cache so the next request re-queries FIRMS."""
    pipeline.clear_cache()
    status = firms_service.FirmsClient().map_key_status()
    return RefreshResponse(
        refreshed=True,
        message="Analysis cache cleared. The next request will re-query the data sources.",
        firms_key_status=status,
    )


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------
def _apply_filters(
    events: list[ClassifiedEvent],
    classification: str | None,
    min_confidence: float,
    priority: str | None,
    max_facility_km: float | None,
    date_from: date | None,
    date_to: date | None,
    persistent_only: bool,
) -> list[ClassifiedEvent]:
    wanted_classes = (
        {c.strip().upper() for c in classification.split(",") if c.strip()}
        if classification
        else None
    )
    wanted_priority = (
        {p.strip().upper() for p in priority.split(",") if p.strip()} if priority else None
    )

    out: list[ClassifiedEvent] = []
    for item in events:
        if wanted_classes and item.classification.label not in wanted_classes:
            continue
        if item.classification.confidence < min_confidence:
            continue
        if wanted_priority and item.priority.level not in wanted_priority:
            continue
        if max_facility_km is not None:
            d = item.evidence.distance_to_nearest_facility_km
            if d is None or d > max_facility_km:
                continue
        if date_from and item.event.acquisition_date < date_from:
            continue
        if date_to and item.event.acquisition_date > date_to:
            continue
        if persistent_only and not item.evidence.recurrence.is_persistent:
            continue
        out.append(item)
    return out
