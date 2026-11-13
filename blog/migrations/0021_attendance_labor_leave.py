from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('blog', '0020_activity_log'),
    ]

    operations = [
        migrations.AlterField(
            model_name='attendance',
            name='status',
            field=models.CharField(
                choices=[
                    ('present', 'Keldi'),
                    ('absent', 'Kelmagan'),
                    ('late', 'Kechikdi'),
                    ('vacation', "Ta'til"),
                    ('labor_leave', "Mehnat ta'tili"),
                    ('business', 'Ish safarida'),
                    ('offday', 'Ish kuni emas'),
                ],
                max_length=16,
                verbose_name='Davomat holati',
            ),
        ),
    ]
