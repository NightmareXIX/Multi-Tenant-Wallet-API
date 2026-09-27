from django.db.models import Sum

from wallets.models import Wallet


class LedgerAssertions:
    """Test-case mixin: the ledger, not the cached balance, is the source of truth."""

    def assertLedgerMatches(self):
        """Every wallet's cached balance equals its incoming minus its outgoing transactions."""
        for wallet in Wallet.objects.all():
            incoming = wallet.incoming_transactions.aggregate(total=Sum('amount'))['total'] or 0
            outgoing = wallet.outgoing_transactions.aggregate(total=Sum('amount'))['total'] or 0
            self.assertEqual(wallet.balance, incoming - outgoing, f'{wallet} disagrees with its ledger')
