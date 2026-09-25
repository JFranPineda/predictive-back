"""V3-03: a template names its own mistakes, and the rows that cause them."""

from modules.assets.domain.template_rules import (
    DeclaredComponent,
    TemplateRowSpec,
    check_template,
)

MOTOR = DeclaredComponent("MOTOR", 2)
PUMP = DeclaredComponent("BOMBA", 2)


def full(number, component):
    return [TemplateRowSpec(number, axis, "custom", component) for axis in ("H", "V", "A")]


def train():
    return full(1, "MOTOR") + full(2, "MOTOR") + full(3, "BOMBA") + full(4, "BOMBA")


def test_a_consistent_template_has_no_problems():
    assert check_template(train(), [MOTOR, PUMP]) == []


def test_a_repeated_point_names_both_rows_and_its_component():
    rows = [*train(), TemplateRowSpec(1, "H", "custom", "MOTOR")]
    [problem] = check_template(rows, [MOTOR, PUMP])
    assert problem.message == "El punto 1H está repetido (en MOTOR)"
    assert problem.rows == (0, 12)


def test_a_component_whose_template_drifted_from_its_count_is_rejected():
    rows = train() + full(5, "BOMBA") + full(6, "BOMBA")
    [problem] = check_template(rows, [MOTOR, PUMP])
    assert problem.message == "BOMBA declara 2 puntos y la plantilla tiene 4"
    assert problem.rows == tuple(range(6, 18))


def test_a_component_with_no_rows_is_reported_without_rows():
    [problem] = check_template(full(1, "MOTOR") + full(2, "MOTOR"), [MOTOR, PUMP])
    assert problem.message == "BOMBA declara 2 puntos y la plantilla tiene 0"
    assert problem.rows == ()


def test_rows_of_the_whole_train_are_not_counted_against_a_machine():
    rows = [*train(), TemplateRowSpec(9, "N", "custom", "")]
    assert check_template(rows, [MOTOR, PUMP]) == []


def test_bad_values_point_at_their_row():
    rows = [TemplateRowSpec(0, "Q", "sideways", "NADA")]
    messages = [p.message for p in check_template(rows, [])]
    assert messages == [
        "El número de punto debe ser 1 o mayor",
        "Eje desconocido: Q",
        "Lado desconocido: sideways",
        "El componente NADA no existe en el tipo",
    ]


def test_an_unknown_component_is_one_problem_listing_all_its_rows():
    rows = full(1, "MOTOR") + full(2, "MOTOR") + full(3, "BOMBA")
    problems = check_template(rows, [MOTOR])
    assert problems[0].message == "El componente BOMBA no existe en el tipo"
    assert problems[0].rows == (6, 7, 8)
