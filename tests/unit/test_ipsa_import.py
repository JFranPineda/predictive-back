"""V3-37: IPSA's 47 workbooks, read the way the analyst wrote them."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from modules.assets.domain.ipsa import (
    Book,
    Column,
    ValueRow,
    book_number,
    borrow_dates,
    component_name,
    group_code,
    kind_for,
    limit_of,
    line_speed,
    load_condition,
    order_code,
    parse_label,
    point_of,
    state_of,
    text_date,
)
from modules.core.management.commands.import_ipsa import _image_kind

FOLDER = Path(__file__).resolve().parents[3] / "predictive-docs/docs/v3/EQUIPOS PLANTA IPSA - SEPTIEMBRE"
needs_books = pytest.mark.skipif(
    not FOLDER.exists(), reason="predictive-docs is not checked out beside the repo"
)


@pytest.mark.parametrize(
    ("raw", "state"),
    [
        ("NORMAL", "normal"),
        ("ACEPTABLE", "normal"),
        ("apagado", "off"),
        ("PARDA", "shutdown"),
        ("OBSERVACIÓN", "observation"),
        ("SIN ACCESO", "no_access"),
        ("NOVIEMBRE", None),
    ],
)
def test_the_states_as_the_books_spell_them(raw, state):
    assert state_of(raw) == state


@pytest.mark.parametrize(
    ("raw", "day"),
    [
        ("'10-Sep-25'", date(2025, 9, 10)),
        ("14-Dic.24", date(2024, 12, 14)),
        ("14--DIC-2024", date(2024, 12, 14)),
        ("412 m/s", None),
    ],
)
def test_dates_typed_as_text(raw, day):
    assert text_date(raw) == day


def test_book_029_wrote_line_speeds_where_the_dates_go():
    assert line_speed("412 m/s") == Decimal("412")
    assert line_speed("10-Sep-25") is None


def test_a_row_label_says_magnitude_axis_and_point():
    assert parse_label("HV-1") == ("vel_rms", "H", 1)
    assert parse_label("AV-12") == ("vel_rms", "A", 12)
    assert parse_label("EE-4") == ("env_accel", None, 4)
    assert parse_label("Parada") is None


def test_the_presses_housings_are_read_below_and_above():
    assert point_of(3) == (3, "custom")
    assert point_of("7\nINFERIOR") == (7, "lower")
    assert point_of("8\nSUPERIOR") == (8, "upper")


def test_a_digit_glued_to_the_component_is_a_typo():
    assert component_name("MOTOR1") == "MOTOR"
    assert component_name("CHUMACERA LADO MANDO") == "CHUMACERA LADO MANDO"


def test_the_customers_number_is_the_trains_code():
    assert book_number("Equipo # 010._ REFINADOR PILAO.xlsx") == "10"
    assert book_number("Equipo FDR #02. MOTOR CAMA 1.xlsx") == "FDR02"
    assert group_code("10") == "eq-10"
    assert group_code("FDR02") == "fdr-02"


def test_the_train_kind_follows_its_machines():
    assert kind_for(["motor", "pump"]) == "motor_pump"
    assert kind_for(["motor", "gearbox"]) == "motor_gearbox"
    assert kind_for(["motor", "gearbox", "bearing_housing", "bearing_housing"]) == "motor_gearbox_bearings"
    assert kind_for(["bearing_housing", "gearbox"]) == "bearing_gearbox"
    assert kind_for(["roller"]) == "standalone"


def test_the_limit_tables_by_their_titles():
    assert limit_of("Limites permisibles ... Según ISO 20816 - 3 (mm/seg. RMS)") == ("vel_rms", "iso_20816_3")
    assert limit_of("Limites ... para Bombas, Según Technical Associates of Charlotte") == (
        "vel_rms",
        "technical_associates",
    )
    assert limit_of("Limites ... Según Adaptación de Diseño.") == ("vel_rms", "design")
    assert limit_of("Limites permisibles de Envolvente de aceleración ( Gs Pico-).") == ("env_accel", None)


def test_a_second_take_of_the_same_day_is_its_own_order():
    assert order_code("vibration", date(2025, 9, 18), 1) == "IPSA-AV-20250918"
    assert order_code("vibration", date(2025, 9, 18), 3) == "IPSA-AV-20250918-3"


def test_the_take_names_the_load():
    assert load_condition("TOMA 10 CARGA 100%") == "CARGA 100 %"
    assert load_condition("TOMA 09 VACÍO") == "VACÍO"
    assert load_condition("T2 - TOMA 01") is None
    assert load_condition("SETIEMBRE") is None


def test_undated_columns_borrow_the_dates_of_a_sibling_with_the_same_months():
    def book(name, days):
        result = Book(
            filename=name,
            number="1",
            area="SECADORES",
            header_name="",
            header_state=None,
            inspection_day=None,
            analyst="",
            field_inspector="",
            instrument="",
        )
        for index, (take, day) in enumerate(days):
            result.columns.append(
                Column(index=index, day=day, source="", take=take, state=None, raw_state="")
            )
        result.rows.append(
            ValueRow(
                "REDUCTOR",
                1,
                "custom",
                "vel_rms",
                "H",
                "HV-1",
                {index: Decimal("1") for index in range(len(days))},
            )
        )
        return result

    dated = book("028", [("MARZO", date(2025, 3, 10)), ("MARZO", date(2025, 3, 21))])
    undated = book("029", [("MARZO", None), ("MARZO", None)])
    borrow_dates(undated, [dated, undated])
    assert [c.day for c in undated.columns] == [date(2025, 3, 10), date(2025, 3, 21)]
    assert "028" in undated.warnings[0]


def test_the_pictures_by_where_they_sit():
    assert _image_kind(1, thermography=False) == (None, "")
    assert _image_kind(7, thermography=True)[0] == "schematic"
    assert _image_kind(84, thermography=False)[0] == "spectrum_image"
    assert _image_kind(19, thermography=True)[0] == "thermogram"


@pytest.fixture(scope="module")
def books():
    from modules.assets.infrastructure.importers.ipsa_excel import read_book

    read = [read_book(path) for path in sorted(FOLDER.glob("Equipo*.xlsx"))]
    for item in read:
        borrow_dates(item, read)
    return {item.number: item for item in read}


@needs_books
def test_47_trains_one_per_book(books):
    # AC-01
    assert len(books) == 47
    assert len({item.code for item in books.values()}) == 47


@needs_books
def test_pulper_04_point_3h_on_28_sep_is_14_14(books):
    # AC-02: the last take, "TOMA 10 CARGA 100%".
    pulper = books["1"]
    column = pulper.columns[-1]
    assert column.day == date(2025, 9, 28)
    assert load_condition(column.take) == "CARGA 100 %"
    row = next(r for r in pulper.rows if r.point == 3 and r.axis == "H" and r.magnitude == "vel_rms")
    assert row.values[column.index] == Decimal("14.14")


@needs_books
def test_pulper_04_point_5_stays_point_5_and_is_reported(books):
    # AC-03
    pulper = books["1"]
    assert {r.point for r in pulper.rows if r.component == "REDUCTOR"} == {3, 4, 5}
    assert any("punto 5 rotulado HV-4" in warning for warning in pulper.warnings)


@needs_books
def test_every_measured_column_ends_up_dated(books):
    undated = [
        (item.filename, c.take) for item in books.values() for c in item.measured_columns() if c.day is None
    ]
    assert undated == []


@needs_books
def test_the_summary_pareto_adds_up_to_its_total():
    from modules.assets.infrastructure.importers.ipsa_excel import read_summary

    trains, pareto = read_summary(FOLDER / "EQUIPOS - CONCLUSIONES.xlsx")
    assert len(trains) == 47
    assert pareto["ESTADO"] == {"normal": 19, "alarm": 3, "shutdown": 5, "off": 20}
