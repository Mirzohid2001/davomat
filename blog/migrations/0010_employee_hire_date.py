from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0009_monthlyemployeestat_paid_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='hire_date',
            field=models.DateField(blank=True, null=True, verbose_name='Ishga kirgan sana'),
        ),
    ]
