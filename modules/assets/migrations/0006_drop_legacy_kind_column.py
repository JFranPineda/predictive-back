"""Drops the old string column and promotes the relation to its name.

Hand-written: autodetect wanted to remove `kind_ref` and cast `kind` in place,
which would have thrown away everything the data migration just moved.
"""

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("assets", "0005_migrate_group_kinds")]

    operations = [
        migrations.RemoveField(model_name="assetgroup", name="kind"),
        migrations.RenameField(model_name="assetgroup", old_name="kind_ref", new_name="kind"),
        migrations.AlterField(
            model_name="assetgroup",
            name="kind",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="groups",
                to="assets.assetgroupkind",
            ),
        ),
    ]
