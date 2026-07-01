from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0014_monthlyemployeestat_salary_override'),
    ]

    operations = [
        migrations.AlterField(
            model_name='employee',
            name='role',
            field=models.CharField(
                choices=[
                    ('production', 'Ishlab chiqarish xodimlari'),
                    ('boshqarma', 'Boshqarma xodimlari'),
                    ('nalivshik', 'Nalivshik'),
                    ('other', 'Boshqa'),
                ],
                default='other',
                max_length=32,
                verbose_name='Lavozim turi',
            ),
        ),
    ]
