# Generated by Django 2.2.4 on 2020-08-26 19:53

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('globalpayments', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='status',
            field=models.CharField(choices=[('PROCESSING', 'processing'), ('APPROVED', 'approved'), ('PAID', 'paid'), ('PARTIAL', 'partial'), ('CANCELED', 'canceled'), ('UNPAID', 'unpaid'), ('RETURNED', 'returned')], db_index=True, default='PROCESSING', max_length=10, verbose_name='status'),
        ),
        migrations.AlterField(
            model_name='order',
            name='order',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='commerce.Order', verbose_name='order'),
        ),
    ]
