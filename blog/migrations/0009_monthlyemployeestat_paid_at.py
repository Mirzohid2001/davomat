from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0008_monthlyemployeestat_calculated_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='monthlyemployeestat',
            name='paid_at',
            field=models.DateField(blank=True, null=True, verbose_name="To'lov sanasi"),
        ),
    ]
