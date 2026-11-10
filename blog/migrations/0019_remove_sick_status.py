from django.db import migrations, models
from django.utils.translation import gettext_lazy as _


def migrate_sick_to_present(apps, schema_editor):
    """Eski 'sick' yozuvlar ishlangan kun sifatida hisoblangan — present ga o'tkaziladi."""
    Attendance = apps.get_model("blog", "Attendance")
    Attendance.objects.filter(status="sick").update(status="present")


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("blog", "0018_advance_loans"),
    ]

    operations = [
        migrations.RunPython(migrate_sick_to_present, noop_reverse),
        migrations.AlterField(
            model_name="attendance",
            name="status",
            field=models.CharField(
                choices=[
                    ("present", _("Keldi")),
                    ("absent", _("Kelmagan")),
                    ("late", _("Kechikdi")),
                    ("vacation", _("Ta'til")),
                    ("business", _("Ish safarida")),
                    ("offday", _("Ish kuni emas")),
                ],
                max_length=16,
                verbose_name="Davomat holati",
            ),
        ),
    ]
