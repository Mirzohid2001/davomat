from datetime import date

from django.db import migrations, models
import django.db.models.deletion


def migrate_existing_paid_to_payments(apps, schema_editor):
    MonthlyEmployeeStat = apps.get_model('blog', 'MonthlyEmployeeStat')
    SalaryPayment = apps.get_model('blog', 'SalaryPayment')
    for stat in MonthlyEmployeeStat.objects.filter(paid__gt=0):
        SalaryPayment.objects.get_or_create(
            stat=stat,
            paid_at=stat.paid_at or date(stat.year, stat.month, 1),
            defaults={'amount': stat.paid},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0011_production_bonus'),
    ]

    operations = [
        migrations.CreateModel(
            name='SalaryPayment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=12, verbose_name='Summa')),
                ('paid_at', models.DateField(verbose_name="To'lov sanasi")),
                ('note', models.CharField(blank=True, default='', max_length=255, verbose_name='Izoh')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('stat', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='salary_payments', to='blog.monthlyemployeestat', verbose_name='Oylik statistika')),
            ],
            options={
                'verbose_name': "Oylik to'lovi",
                'verbose_name_plural': "Oylik to'lovlari",
                'ordering': ['paid_at', 'pk'],
            },
        ),
        migrations.RunPython(migrate_existing_paid_to_payments, migrations.RunPython.noop),
    ]
