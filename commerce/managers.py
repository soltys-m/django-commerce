class PaymentManager(object):
    def __init__(self, order):
        self.order = order

    def render_payment_button(self):
        raise NotImplementedError()
