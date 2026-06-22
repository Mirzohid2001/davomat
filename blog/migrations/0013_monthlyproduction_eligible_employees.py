from django.db import migrations, models


def migrate_global_eligible_to_monthly(apps, schema_editor):
  MonthlyProduction = apps.get_model('blog', 'MonthlyProduction')
  Employee = apps.get_model('blog', 'Employee')
  eligible_ids = list(
      Employee.objects.filter(production_bonus_eligible=True, is_active=True).values_list('pk', flat=True)
  )
  if not eligible_ids:
      return
  for record in MonthlyProduction.objects.all():
      record.eligible_employees.set(eligible_ids)


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0012_salarypayment'),
    ]

    operations = [
        migrations.AddField(
            model_name='monthlyproduction',
            name='eligible_employees',
            field=models.ManyToManyField(
                blank=True,
                help_text='Faqat shu oy uchun ishlab chiqarish premiyasi oladigan xodimlar.',
                related_name='production_bonus_months',
                to='blog.employee',
                verbose_name='Premiya oluvchi xodimlar',
            ),
        ),
        migrations.RunPython(migrate_global_eligible_to_monthly, migrations.RunPython.noop),
    ]
