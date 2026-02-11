# Generated migration for adding opening_balance_side field to Party model

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('barkat', '0038_add_cancellation_password'),
    ]

    operations = [
        migrations.AddField(
            model_name='party',
            name='opening_balance_side',
            field=models.CharField(
                choices=[('Dr', 'Debit (They owe us)'), ('Cr', 'Credit (We owe them)')],
                default='Dr',
                max_length=2,
                help_text='Specify whether the opening balance is Debit or Credit'
            ),
        ),
        # Set default values for existing records based on party type
        # Customers with opening balance -> Dr (they owe us)
        # Suppliers with opening balance -> Cr (we owe them)
        migrations.RunSQL(
            sql="""
                UPDATE barkat_party 
                SET opening_balance_side = CASE 
                    WHEN type IN ('VENDOR', 'BOTH') AND opening_balance > 0 THEN 'Cr'
                    ELSE 'Dr'
                END;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
