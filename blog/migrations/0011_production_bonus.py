from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0010_employee_hire_date'),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='production_bonus_eligible',
            field=models.BooleanField(
                default=False,
                help_text="Belgilangan xodimlarga oylik benzin ishlab chiqarish bo'yicha avtomatik premiya beriladi.",
                verbose_name='Ishlab chiqarish premiyasiga mos',
            ),
        ),
        migrations.AddField(
            model_name='monthlyemployeestat',
            name='bonus_override',
            field=models.BooleanField(
                default=False,
                help_text="True bo'lsa, ishlab chiqarish premiyasi avtomatik yozilmaydi.",
                verbose_name="Mukofot qo'lda o'rnatilgan",
            ),
        ),
        migrations.CreateModel(
            name='MonthlyProduction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('year', models.PositiveIntegerField(verbose_name='Yil')),
                ('month', models.PositiveIntegerField(verbose_name='Oy')),
                ('production_tons', models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='Ishlab chiqarish (tonna)')),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Oylik ishlab chiqarish',
                'verbose_name_plural': 'Oylik ishlab chiqarish',
                'ordering': ['-year', '-month'],
                'unique_together': {('year', 'month')},
            },
        ),
    ]
