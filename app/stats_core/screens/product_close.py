from stats_core.services.product import PRODUCT_LABEL, PRODUCT_MODE


class ProductCloseScreen:
    key = PRODUCT_MODE
    label = PRODUCT_LABEL

    def __init__(self, products):
        self.products = products

    def render(self, _context=None, **_kwargs):
        product = self.products.current_payload()
        return {
            "mode": self.key, "mode_label": self.label,
            "metrics": [], "rows": product["rows"], "teams": [],
            "product_market": product["market"],
            "product_start": product["start"], "product_end": product["end"],
            "product_icons": product["icons"],
            "product_temporary": product["temporary"],
            "product_seconds_left": product["seconds_left"],
        }
