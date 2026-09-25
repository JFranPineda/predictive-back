"""The orders already in the ledger were executed by 1A-MIG, the provider of
the service. Seeding it keeps the new "Empresa" column from opening blank."""

from django.db import migrations

PROVIDER = "1A-MIG"


def seed_provider(apps, schema_editor):
    alias = schema_editor.connection.alias
    Order = apps.get_model("services", "ServiceOrder")
    Provider = apps.get_model("services", "ServiceProvider")
    for company_id in Order.objects.using(alias).values_list("company_id", flat=True).distinct():
        provider, _ = Provider.objects.using(alias).get_or_create(company_id=company_id, name=PROVIDER)
        Order.objects.using(alias).filter(company_id=company_id, provider__isnull=True).update(
            provider=provider
        )


class Migration(migrations.Migration):
    dependencies = [("services", "0003_service_provider")]

    operations = [migrations.RunPython(seed_provider, migrations.RunPython.noop)]
