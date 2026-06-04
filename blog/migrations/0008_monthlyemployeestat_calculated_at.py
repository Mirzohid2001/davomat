from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0007_nalivshikshiftoverride'),
    ]

    operations = [
        migrations.AddField(
            model_name='monthlyemployeestat',
            name='calculated_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Oxirgi hisoblash vaqti'),
        ),
    ]
