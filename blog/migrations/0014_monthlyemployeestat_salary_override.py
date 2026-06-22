from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0013_monthlyproduction_eligible_employees'),
    ]

    operations = [
        migrations.AddField(
            model_name='monthlyemployeestat',
            name='salary_override',
            field=models.BooleanField(
                default=False,
                help_text="True bo'lsa, oylik avvalgi oydan avtomatik o'zgarmaydi.",
                verbose_name="Oylik qo'lda o'rnatilgan",
            ),
        ),
    ]
