"""V3-15: telling an image from a data file."""

from modules.media.domain.formats import format_of, is_image


def test_a_png_export_is_an_image():
    assert is_image("Reductor 3HV cascada.PNG")
    assert format_of("capture.jpeg") == "jpeg"


def test_a_csv_is_not():
    assert not is_image("espectro.csv")
    assert format_of("espectro.csv") is None


def test_a_pdf_is_a_document_not_an_image():
    assert format_of("laboratorio.pdf") == "document"
    assert not is_image("laboratorio.pdf")
