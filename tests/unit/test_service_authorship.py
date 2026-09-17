"""T1 of the second round: the "who performed this service" view."""

from datetime import date, datetime

from modules.services.domain.participation import (
    AuthoredEntry,
    EntryType,
    Participant,
    ParticipantRole,
    ServiceAuthorship,
)


def authorship(participants, entries=()):
    return ServiceAuthorship(
        visit_id=1,
        equipment_id=228,
        equipment_name="EB 228 MOTOR",
        technique_code="vibration",
        visited_at=datetime(2013, 12, 17, 9, 30),
        participants=tuple(participants),
        entries=tuple(entries),
        reading_count=20,
        media_count=6,
        is_closed=False,
        report_issued=False,
    )


HENRY = Participant(user_id=7, full_name="Henry Tejada", initials="HT",
                    role=ParticipantRole.LEAD_ANALYST, is_external=True)
CARLOS = Participant(user_id=1, full_name="Carlos Balta", initials="CT",
                     role=ParticipantRole.SUPERVISOR)
ALEX = Participant(user_id=8, full_name="Alex J.", initials="AJ",
                   role=ParticipantRole.ASSISTANT, is_external=True)


class TestWhoDidIt:
    def test_names_the_lead_analyst_and_the_supervisor(self):
        view = authorship([HENRY, CARLOS])
        assert view.lead is HENRY
        assert view.supervisor is CARLOS

    def test_signature_reproduces_the_trend_sheet_cell(self):
        # `TABLA DE TENDENCIAS.xls` signs a round "HT / AJ".
        assert authorship([HENRY, ALEX]).signature == "HT / AJ"

    def test_knows_whether_a_given_user_worked_the_visit(self):
        view = authorship([HENRY, ALEX])
        assert view.authored_by(8)
        assert not view.authored_by(42)

    def test_a_visit_with_no_supervisor_says_so(self):
        assert authorship([HENRY]).supervisor is None


class TestNotesAndConclusions:
    entries = [
        AuthoredEntry(1, EntryType.OBSERVATION, date(2013, 12, 17),
                      "Tapa de acople con juego radial", 7, "Henry Tejada", 1),
        AuthoredEntry(2, EntryType.CONCLUSION, date(2013, 12, 17),
                      "Desalineamiento de conjunto Motor-Bomba", 7, "Henry Tejada", 1),
        AuthoredEntry(3, EntryType.RECOMMENDATION, date(2013, 12, 17),
                      "Realizar nivelación de SKID", 1, "Carlos Balta", 1),
    ]

    def test_entries_are_filtered_by_type(self):
        view = authorship([HENRY, CARLOS], self.entries)
        assert len(view.entries_of(EntryType.CONCLUSION)) == 1
        assert view.entries_of(EntryType.RECOMMENDATION)[0].author_name == "Carlos Balta"

    def test_every_line_keeps_its_own_author(self):
        # Two people wrote this visit; a single "author" field on the report
        # would attribute the supervisor's recommendation to the inspector.
        view = authorship([HENRY, CARLOS], self.entries)
        assert {entry.author_id for entry in view.entries} == {1, 7}

    def test_entries_keep_their_own_date(self):
        # Background from an earlier visit can sit in the same view.
        older = AuthoredEntry(4, EntryType.BACKGROUND, date(2013, 11, 16),
                              "Se instala electrobomba nueva", 7, "Henry Tejada", None)
        view = authorship([HENRY], [*self.entries, older])
        assert view.entries_of(EntryType.BACKGROUND)[0].entry_date == date(2013, 11, 16)
