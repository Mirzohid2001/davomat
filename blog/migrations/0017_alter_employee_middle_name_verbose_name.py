from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0016_employee_middle_name'),
    ]

    operations = [
        migrations.AlterField(
            model_name='employee',
            name='middle_name',
            field=models.CharField(blank=True, default='', max_length=64, verbose_name='Otchestvasi'),
        ),
    ]
