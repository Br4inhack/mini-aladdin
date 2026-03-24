# Generated manually for data_ingestion initial model.

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='FIIDIIData',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(unique=True)),
                ('fii_net_value', models.DecimalField(decimal_places=2, max_digits=16)),
                ('dii_net_value', models.DecimalField(decimal_places=2, max_digits=16)),
                ('source', models.CharField(default='nse_bhavcopy', max_length=50)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'FII/DII Data',
                'verbose_name_plural': 'FII/DII Data',
                'ordering': ['-date'],
                'indexes': [
                    models.Index(fields=['date'], name='data_ingest_date_889a20_idx'),
                    models.Index(fields=['source'], name='data_ingest_source_8f59e8_idx'),
                ],
            },
        ),
    ]
