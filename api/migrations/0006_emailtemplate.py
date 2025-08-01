# Generated by Django 4.2.10 on 2025-07-27 18:55

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0005_alter_referral_current_status'),
    ]

    operations = [
        migrations.CreateModel(
            name='EmailTemplate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('purpose', models.CharField(choices=[('CV_TO_SBU', 'CV Referral (to SBU)'), ('CV_APPROVED_SBU', 'CV Referral Approved [By SBU]'), ('CV_REJECTED_SBU', 'CV Referral Disapproved [By SBU]'), ('CV_TO_HR', 'CV Referral to HR'), ('CV_APPROVED_HR', 'CV Referral Approved [By HR]'), ('CV_REJECTED_HR', 'CV Referral Disapproved [By HR]')], max_length=50, unique=True)),
                ('subject', models.CharField(max_length=255)),
                ('html_body', models.TextField()),
            ],
        ),
    ]
