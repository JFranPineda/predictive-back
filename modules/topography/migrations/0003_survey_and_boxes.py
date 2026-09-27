"""Q11: a topography service reads like the client's sheet — a survey frame
per visit, and per roller the four boxes (parallelism and level, drive and
transmission side) with their photos and the displacements."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def mm(**kwargs):
    return models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, **kwargs)


def photo():
    return models.ForeignKey(
        blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="media.mediaasset"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("topography", "0002_seed_technique"),
        ("media", "0007_signature_and_survey_kinds"),
        ("services", "0006_order_standard"),
        ("assets", "0011_alter_equipment_equipment_type"),
        ("core", "0002_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RenameField("topographyelementreading", "parallel_h", "parallel_drive_mm"),
        migrations.RenameField("topographyelementreading", "parallel_v", "parallel_transmission_mm"),
        migrations.RenameField("topographyelementreading", "level_h", "level_drive_mm"),
        migrations.RenameField("topographyelementreading", "level_v", "level_transmission_mm"),
        migrations.AlterField("topographyelementreading", "parallel_drive_mm", mm()),
        migrations.AlterField("topographyelementreading", "parallel_transmission_mm", mm()),
        migrations.AlterField("topographyelementreading", "level_drive_mm", mm()),
        migrations.AlterField("topographyelementreading", "level_transmission_mm", mm()),
        migrations.AddField(
            "topographyelementreading", "reference_label",
            models.CharField(blank=True, help_text="Contra qué se mide; vacío = el componente principal", max_length=80),
        ),
        migrations.AddField(
            "topographyelementreading", "horizontal_displacement_mm",
            models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True),
        ),
        migrations.AddField(
            "topographyelementreading", "vertical_displacement_mm",
            models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True),
        ),
        migrations.AddField("topographyelementreading", "parallel_drive_photo", photo()),
        migrations.AddField("topographyelementreading", "parallel_transmission_photo", photo()),
        migrations.AddField("topographyelementreading", "level_drive_photo", photo()),
        migrations.AddField("topographyelementreading", "level_transmission_photo", photo()),
        migrations.AlterField(
            "topographyelementreading", "element_label",
            models.CharField(help_text="El polín medido, p. ej. 'Rodillo N°5'", max_length=40),
        ),
        migrations.AlterModelOptions("topographyelementreading", {"ordering": ["created_at", "id"]}),
        migrations.CreateModel(
            name="TopographySurvey",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("title", models.CharField(blank=True, help_text="p. ej. 'Alineamiento y nivelación prensa 1'", max_length=200)),
                ("survey_date", models.DateField(blank=True, help_text="Fecha del servicio", null=True)),
                ("reference_label", models.CharField(blank=True, help_text="Componente principal de referencia, p. ej. 'Prensa 1'", max_length=80)),
                ("plan_number", models.CharField(blank=True, max_length=60)),
                ("instrument", models.CharField(blank=True, max_length=120)),
                ("notes", models.TextField(blank=True)),
                ("plan_notes", models.TextField(blank=True)),
                ("asset_group", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="assets.assetgroup")),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to="core.company")),
                ("created_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("plan_image", photo()),
                ("schema_image", photo()),
                ("service_visit", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="topography_survey", to="services.servicevisit")),
            ],
            options={"abstract": False},
        ),
    ]
