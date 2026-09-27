from django.db import migrations

# Transaction.save() and delete() only guard single instances. This trigger also stops bulk queryset
# calls and raw SQL. Row-level triggers do not fire on TRUNCATE, which the test runner uses to flush.
CREATE_TRIGGER = """
CREATE FUNCTION wallets_transaction_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'Transactions are immutable: % is not allowed.', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER wallets_transaction_immutable
    BEFORE UPDATE OR DELETE ON wallets_transaction
    FOR EACH ROW EXECUTE FUNCTION wallets_transaction_immutable();
"""

DROP_TRIGGER = """
DROP TRIGGER wallets_transaction_immutable ON wallets_transaction;
DROP FUNCTION wallets_transaction_immutable();
"""


class Migration(migrations.Migration):

    dependencies = [
        ('wallets', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(CREATE_TRIGGER, reverse_sql=DROP_TRIGGER),
    ]
