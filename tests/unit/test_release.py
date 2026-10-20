"""Shipping PREDICTIVE as a closed product (v4 Phase 5): the build label the
PDFs carry, which source files are compiled to native vs bytecode, and the
signed integrity manifest the program checks at startup."""

import hashlib
from pathlib import Path

import pytest

from modules.licensing.domain.build import BuildStamp, Compilation, source_class
from modules.licensing.domain.integrity import (
    IntegrityError,
    build_manifest,
    read_manifest,
    verify_tree,
)
from modules.licensing.domain.signing import (
    SigningKeyError,
    generate_signing_key,
    public_key_text,
    sign_blob,
    verify_blob,
)

KEY = generate_signing_key()
PUBLIC = public_key_text(KEY)


class TestBlobSignature:
    def test_a_blob_verifies_with_the_public_key(self):
        data = b"the integrity manifest, byte for byte"
        verify_blob(PUBLIC, data, sign_blob(KEY, data))

    def test_a_changed_blob_does_not_verify(self):
        signature = sign_blob(KEY, b"original")
        with pytest.raises(SigningKeyError):
            verify_blob(PUBLIC, b"original (altered)", signature)

    def test_another_key_cannot_sign(self):
        with pytest.raises(SigningKeyError):
            verify_blob(PUBLIC, b"data", sign_blob(generate_signing_key(), b"data"))

    def test_no_public_key_verifies_nothing(self):
        with pytest.raises(SigningKeyError):
            verify_blob("", b"data", sign_blob(KEY, b"data"))


class TestBuildStamp:
    def test_the_label_names_the_owner_tenant_and_version(self):
        stamp = BuildStamp(tenant="ipsa", version="1.0.3", build_id="20261020-abcdef")
        assert stamp.pdf_author == "Industrie Ampel — PREDICTIVE · ipsa · 1.0.3"
        assert stamp.pdf_creator == "PREDICTIVE 1.0.3 (20261020-abcdef)"

    def test_an_unstamped_build_is_marked_as_development(self):
        # A checkout with no build args still produces readable, honest metadata.
        stamp = BuildStamp(tenant="", version="", build_id="")
        assert "desarrollo" in stamp.pdf_author.lower()
        assert stamp.build_id == "desarrollo"


class TestSourceClass:
    @pytest.mark.parametrize("path", [
        "modules/measurements/domain/spectra.py",
        "modules/licensing/application/renewal.py",
    ])
    def test_the_value_is_compiled_to_native(self, path):
        assert source_class(Path(path)) is Compilation.NATIVE

    @pytest.mark.parametrize("path", [
        "modules/licensing/migrations/0001_initial.py",
        "modules/licensing/interfaces/views.py",
        "modules/licensing/infrastructure/models.py",
        "config/settings/base.py",
        "manage.py",
    ])
    def test_the_glue_is_bytecode(self, path):
        assert source_class(Path(path)) is Compilation.BYTECODE

    def test_migrations_are_never_native_even_under_domain(self):
        # A path with 'domain' in a migration name must still be bytecode:
        # Django reads migrations as a package tree.
        assert source_class(Path("modules/x/domain/migrations/0002_fields.py")) is Compilation.BYTECODE

    def test_a_package_init_stays_bytecode_even_under_domain(self):
        # A package __init__ compiled to a native module does not import as a
        # package; keep it bytecode.
        assert source_class(Path("modules/x/domain/__init__.py")) is Compilation.BYTECODE

    def test_a_non_python_file_is_shipped_as_is(self):
        assert source_class(Path("modules/reports/templates/reports/base.html")) is Compilation.ASSET
        assert source_class(Path("modules/licensing/locales/es.json")) is Compilation.ASSET


class TestIntegrityManifest:
    def _tree(self, root: Path) -> None:
        (root / "modules").mkdir(parents=True)
        (root / "modules" / "a.so").write_bytes(b"native code")
        (root / "modules" / "b.pyc").write_bytes(b"bytecode")
        (root / "config").mkdir()
        (root / "config" / "base.pyc").write_bytes(b"settings")

    def test_a_clean_tree_verifies(self, tmp_path):
        self._tree(tmp_path)
        manifest = build_manifest(tmp_path, ("*.so", "*.pyc"))
        verify_tree(tmp_path, manifest, sign_blob(KEY, manifest), PUBLIC)

    def test_the_manifest_is_deterministic(self, tmp_path):
        self._tree(tmp_path)
        assert build_manifest(tmp_path, ("*.so", "*.pyc")) == build_manifest(tmp_path, ("*.so", "*.pyc"))

    def test_an_altered_file_is_named(self, tmp_path):
        self._tree(tmp_path)
        manifest = build_manifest(tmp_path, ("*.so", "*.pyc"))
        signature = sign_blob(KEY, manifest)
        (tmp_path / "modules" / "a.so").write_bytes(b"tampered native code")
        with pytest.raises(IntegrityError, match=r"modules/a\.so"):
            verify_tree(tmp_path, manifest, signature, PUBLIC)

    def test_a_missing_file_is_named(self, tmp_path):
        self._tree(tmp_path)
        manifest = build_manifest(tmp_path, ("*.so", "*.pyc"))
        signature = sign_blob(KEY, manifest)
        (tmp_path / "config" / "base.pyc").unlink()
        with pytest.raises(IntegrityError, match=r"config/base\.pyc"):
            verify_tree(tmp_path, manifest, signature, PUBLIC)

    def test_a_forged_manifest_is_refused_before_any_file_is_read(self, tmp_path):
        self._tree(tmp_path)
        manifest = build_manifest(tmp_path, ("*.so", "*.pyc"))
        forged = manifest.replace(b"modules/a.so", b"modules/a.sox")  # a path the sig no longer covers
        with pytest.raises(IntegrityError, match="firma"):
            verify_tree(tmp_path, forged, sign_blob(KEY, manifest), PUBLIC)

    def test_read_manifest_lists_every_file_with_its_digest(self, tmp_path):
        self._tree(tmp_path)
        entries = read_manifest(build_manifest(tmp_path, ("*.so", "*.pyc")))
        assert entries["modules/a.so"] == hashlib.sha256(b"native code").hexdigest()
        assert set(entries) == {"modules/a.so", "modules/b.pyc", "config/base.pyc"}


class TestPdfStamp:
    def test_the_report_context_carries_the_build_label(self, settings):
        from modules.reports.infrastructure.render import _build_stamp

        settings.BUILD_TENANT, settings.BUILD_VERSION, settings.BUILD_ID = "ipsa", "1.0.0", "b1"
        stamp = _build_stamp()
        assert stamp["build_author"] == "Industrie Ampel — PREDICTIVE · ipsa · 1.0.0"
        assert stamp["build_creator"] == "PREDICTIVE 1.0.0 (b1)"

    def test_the_report_head_writes_the_pdf_metadata_tags(self):
        # WeasyPrint reads <meta name=author/generator> into the PDF metadata.
        from django.template.loader import render_to_string

        html = render_to_string("reports/base.html", {
            "title": "Informe", "build_author": "Industrie Ampel — PREDICTIVE · ipsa · 1.0.0",
            "build_creator": "PREDICTIVE 1.0.0 (b1)",
        })
        assert '<meta name="author" content="Industrie Ampel — PREDICTIVE · ipsa · 1.0.0">' in html
        assert '<meta name="generator" content="PREDICTIVE 1.0.0 (b1)">' in html
