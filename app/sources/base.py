from abc import ABC, abstractmethod

class LeaderboardSource(ABC):
    @abstractmethod
    def fetch(self):
        """
        Return a list of normalized rep dictionaries.

        Required:
          rep_key
          rep_name
          team

        Supported metrics:
          home_branch, title, hire_date,
          issued_leads, pitched_leads, pitched_rate,
          sold_leads, close_rate,
          gross_split, pending_split, net_split,
          dpl, sales_retention,
          avg_gross_sale, avg_net_sale

        TableauSource will implement this later.
        """
        raise NotImplementedError
