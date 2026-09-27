"""Topografía (Q11): the client's sheet, per visit.

A survey frames it — date, the main component everything is measured from,
the notes, the train's schema and the plan of the whole analysis with its
notes. Each roller read against that component is a row: its separation in
mm on the four boxes of the sheet (parallelism and level, drive and
transmission side), the photo behind each box, and the horizontal and
vertical displacement it needs, signed (+3 mm, -1 mm).

No verdict: the client asked for the values and the images, not a
tolerance.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modules.security.application.access import build_actor
from modules.security.domain.policies import can_edit_visit
from modules.services.infrastructure.visit_refs import visit_ref
from modules.topography.infrastructure.models import BOXES
from modules.topography.models import TopographyElementReading, TopographySurvey

FIELDS = (
    "parallel_drive_mm",
    "parallel_transmission_mm",
    "horizontal_displacement_mm",
    "level_drive_mm",
    "level_transmission_mm",
    "vertical_displacement_mm",
)
SURVEY_TEXT = ("title", "reference_label", "plan_number", "instrument", "notes", "plan_notes")
SURVEY_IMAGES = {"schema": "topography_schema", "plan": "topography_plan"}


class TopographySurveyView(APIView):
    """`GET|PATCH topography-visits/<visit_id>/survey/` — the sheet's frame.
    Read before anything was written, it answers the defaults the visit
    already knows (its train and date)."""

    permission_classes = (IsAuthenticated,)

    def get(self, request, visit_id: int):
        _require_view(request)
        visit = _visit(request, visit_id)
        survey = TopographySurvey.objects.for_company(request.company_id).filter(service_visit=visit).first()
        return Response(_survey_payload(survey, visit))

    def patch(self, request, visit_id: int):
        visit = _writable_visit(request, visit_id)
        survey = _survey(request, visit)
        for field in SURVEY_TEXT:
            if field in request.data:
                setattr(survey, field, (request.data.get(field) or "").strip())
        if "survey_date" in request.data:
            raw = request.data.get("survey_date")
            survey.survey_date = parse_date(raw) if raw else None
            if raw and survey.survey_date is None:
                raise ValidationError("Fecha no válida: usa AAAA-MM-DD")
        survey.save()
        return Response(_survey_payload(survey, visit))


class TopographySurveyImageView(APIView):
    """`POST topography-visits/<visit_id>/survey/images/` with `role`
    (schema, plan) and `file` — replaces that image. `DELETE …/<role>/`."""

    permission_classes = (IsAuthenticated,)
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, visit_id: int):
        visit = _writable_visit(request, visit_id)
        survey = _survey(request, visit)
        role = request.data.get("role")
        if role not in SURVEY_IMAGES:
            raise ValidationError("La imagen es el esquema del conjunto o el plano del análisis")
        asset = _store(request, SURVEY_IMAGES[role], "topography_survey", survey.id)
        setattr(survey, f"{role}_image", asset)
        survey.save(update_fields=[f"{role}_image"])
        return Response(_survey_payload(survey, visit), status=201)

    def delete(self, request, visit_id: int, role: str):
        visit = _writable_visit(request, visit_id)
        survey = _survey(request, visit)
        if role not in SURVEY_IMAGES:
            raise ValidationError("Imagen desconocida")
        setattr(survey, f"{role}_image", None)
        survey.save(update_fields=[f"{role}_image"])
        return Response(_survey_payload(survey, visit))


class TopographyElementListView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        _require_view(request)
        visit_id = request.query_params.get("visit")
        if not visit_id:
            raise ValidationError("Falta el parámetro 'visit'")
        rows = (
            TopographyElementReading.objects.for_company(request.company_id)
            .filter(service_visit_id=visit_id)
            .select_related(*[f"{box}_photo" for box in BOXES])
        )
        return Response([_payload(row) for row in rows])

    def post(self, request):
        visit = _writable_visit(request, request.data.get("service_visit"))
        label = (request.data.get("element_label") or "").strip()
        if not label:
            raise ValidationError("Indica el polín medido, p. ej. 'Rodillo N°5'")
        row = TopographyElementReading.objects.create(
            company_id=request.company_id,
            asset_group_id=visit.equipment.asset_group_id,
            service_visit=visit,
            element_label=label[:40],
            reference_label=(request.data.get("reference_label") or "").strip()[:80],
            observation=(request.data.get("observation") or "").strip(),
            created_by=request.user,
            **{field: _decimal(request.data.get(field)) for field in FIELDS if field in request.data},
        )
        return Response(_payload(row), status=201)


class TopographyElementDetailView(APIView):
    permission_classes = (IsAuthenticated,)

    def patch(self, request, reading_id: int):
        row = _writable_row(request, reading_id)
        if "element_label" in request.data:
            label = (request.data["element_label"] or "").strip()
            if not label:
                raise ValidationError("Indica el polín medido, p. ej. 'Rodillo N°5'")
            row.element_label = label[:40]
        for field in ("reference_label", "observation"):
            if field in request.data:
                setattr(row, field, (request.data[field] or "").strip())
        for field in FIELDS:
            if field in request.data:
                setattr(row, field, _decimal(request.data[field]))
        row.save()
        return Response(_payload(row))

    def delete(self, request, reading_id: int):
        row = _writable_row(request, reading_id)
        row.delete()
        return Response(status=204)


class TopographyBoxPhotoView(APIView):
    """`POST topography-elements/<id>/photos/` with `box` and `file` — the
    photo of one of the four boxes, replacing the one before. `DELETE
    …/photos/<box>/`."""

    permission_classes = (IsAuthenticated,)
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def post(self, request, reading_id: int):
        row = _writable_row(request, reading_id)
        box = _box(request.data.get("box"))
        setattr(row, f"{box}_photo", _store(request, "topography_box", "topography_element", row.id))
        row.save(update_fields=[f"{box}_photo"])
        return Response(_payload(row), status=201)

    def delete(self, request, reading_id: int, box: str):
        row = _writable_row(request, reading_id)
        setattr(row, f"{_box(box)}_photo", None)
        row.save(update_fields=[f"{box}_photo"])
        return Response(_payload(row))


class TopographyHistoryView(APIView):
    """A roller's trend across visits (AC-02): every reading it ever got on
    this train, dated, regardless of which visit wrote it."""

    permission_classes = (IsAuthenticated,)

    def get(self, request):
        _require_view(request)
        group_id = request.query_params.get("group")
        element = (request.query_params.get("element") or "").strip()
        if not group_id or not element:
            raise ValidationError("Faltan los parámetros 'group' y 'element'")

        rows = (
            TopographyElementReading.objects.for_company(request.company_id)
            .filter(asset_group_id=group_id, element_label=element)
            .select_related("service_visit")
            .order_by("service_visit__visited_at")
        )
        return Response(
            [{**_payload(row), "visited_at": row.service_visit.visited_at.isoformat()} for row in rows]
        )


# ---------------------------------------------------------------- helpers


def _require_view(request) -> None:
    actor = build_actor(request.user, request.company_id)
    if not actor.has("topography.view"):
        raise PermissionDenied("Falta el permiso topography.view")


def _visit(request, visit_id):
    from modules.services.infrastructure.models import ServiceVisit

    visit = (
        ServiceVisit.objects.for_company(request.company_id)
        .select_related("equipment__asset_group")
        .filter(id=visit_id)
        .first()
    )
    if visit is None:
        raise ValidationError("Esa visita no existe")
    return visit


def _writable_visit(request, visit_id):
    visit = _visit(request, visit_id)
    actor = build_actor(request.user, request.company_id)
    if not can_edit_visit(actor, visit_ref(visit)):
        raise PermissionDenied("Esta visita no es tuya o ya está cerrada")
    return visit


def _survey(request, visit) -> TopographySurvey:
    survey, _ = TopographySurvey.objects.get_or_create(
        company_id=request.company_id,
        service_visit=visit,
        defaults={
            "asset_group_id": visit.equipment.asset_group_id,
            "survey_date": _local_day(visit) if visit.visited_at else None,
            "created_by": request.user,
        },
    )
    return survey


def _writable_row(request, reading_id: int) -> TopographyElementReading:
    row = (
        TopographyElementReading.objects.for_company(request.company_id)
        .select_related("service_visit", *[f"{box}_photo" for box in BOXES])
        .filter(id=reading_id)
        .first()
    )
    if row is None:
        raise ValidationError("Ese polín no existe en el levantamiento")
    actor = build_actor(request.user, request.company_id)
    if not can_edit_visit(actor, visit_ref(row.service_visit)):
        raise PermissionDenied("Esta visita no es tuya o ya está cerrada")
    return row


def _local_day(visit):
    """The plant's calendar day of the visit, not UTC's."""
    return timezone.localtime(visit.visited_at).date()


def _box(raw) -> str:
    if raw not in BOXES:
        raise ValidationError("Cuadro desconocido: paralelismo o nivelación, lado mando o transmisión")
    return raw


def _store(request, kind: str, owner_type: str, owner_id: int):
    from modules.media.infrastructure.uploads import UploadRejectedError, store_upload

    try:
        asset, _ = store_upload(
            company_id=request.company_id,
            upload=request.FILES.get("file"),
            kind=kind,
            owner_type=owner_type,
            owner_id=owner_id,
            caption=(request.data.get("caption") or "").strip(),
            user=request.user,
        )
    except UploadRejectedError as cause:
        raise ValidationError(str(cause)) from cause
    return asset


def _image(asset) -> dict | None:
    if asset is None:
        return None
    from modules.media.infrastructure.local_store import store

    backend = store()
    thumb = (asset.derivatives or {}).get("thumb", {}).get("key")
    return {
        "id": asset.id,
        "url": backend.url(asset.original_key),
        "thumb_url": backend.url(thumb) if thumb else None,
    }


def _survey_payload(survey: TopographySurvey | None, visit) -> dict:
    if survey is None:
        return {
            "id": None,
            "service_visit_id": visit.id,
            "title": "",
            "reference_label": "",
            "plan_number": "",
            "instrument": "",
            "notes": "",
            "plan_notes": "",
            "survey_date": _local_day(visit).isoformat() if visit.visited_at else None,
            "schema_image": None,
            "plan_image": None,
        }
    return {
        "id": survey.id,
        "service_visit_id": survey.service_visit_id,
        **{field: getattr(survey, field) for field in SURVEY_TEXT},
        "survey_date": survey.survey_date.isoformat() if survey.survey_date else None,
        "schema_image": _image(survey.schema_image),
        "plan_image": _image(survey.plan_image),
    }


def _payload(row: TopographyElementReading) -> dict:
    return {
        "id": row.id,
        "service_visit_id": row.service_visit_id,
        "element_label": row.element_label,
        "reference_label": row.reference_label,
        **{field: _plain(getattr(row, field)) for field in FIELDS},
        "photos": {box: _image(getattr(row, f"{box}_photo")) for box in BOXES},
        "observation": row.observation,
    }


def _plain(value) -> str | None:
    return None if value is None else format(value.normalize(), "f")


def _decimal(raw) -> Decimal | None:
    if raw in (None, ""):
        return None
    try:
        return Decimal(str(raw).replace(",", ".").replace("+", "").strip())
    except InvalidOperation as cause:
        raise ValidationError(f"'{raw}' no es un número") from cause
