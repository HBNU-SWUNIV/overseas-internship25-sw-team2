# Generated by Django 5.1.6 on 2025-02-26 09:01

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0003_rename_clinic_resourceroom_etc_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='assigntable',
            name='ResourceCode',
            field=models.CharField(max_length=100),
        ),
    ]
