# Generated migration for adding opening_balance_date field to Party model

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('barkat', '0039_add_opening_balance_side'),
    ]

    operations = [
        migrations.AddField(
            model_name='party',
            name='opening_balance_date',
            field=models.DateField(
                blank=True,
                null=True,
                help_text='Date when the opening balance was set (defaults to party creation date)'
            ),
        ),
        # Set opening_balance_date to created_at for existing parties with opening balance
        migrations.RunSQL(
            sql="""
                UPDATE barkat_party 
                SET opening_balance_date = DATE(created_at)
                WHERE opening_balance > 0 AND opening_balance_date IS NULL;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]

