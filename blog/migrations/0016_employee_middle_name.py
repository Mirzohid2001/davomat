from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0015_alter_employee_role_choices'),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='middle_name',
            field=models.CharField(blank=True, default='', max_length=64, verbose_name='Otasining ismi'),
        ),
    ]
