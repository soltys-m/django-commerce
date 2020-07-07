from decimal import Decimal

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.core.exceptions import ObjectDoesNotExist
from django.core.validators import MinValueValidator, EMPTY_VALUES, MaxValueValidator
from django.db import models, transaction
from django.urls import reverse
from django.utils import translation
from django.utils.module_loading import import_string
from django.utils.safestring import mark_safe
from django.utils.timezone import now
from django.utils.translation import ugettext_lazy as _, ugettext, override
from internationalflavor.countries import CountryField
from internationalflavor.vat_number import VATNumberField
from modeltrans.fields import TranslationField

from commerce import settings as commerce_settings
from commerce.querysets import OrderQuerySet, DiscountCodeQuerySet
from invoicing.models import Invoice, Item as InvoiceItem
from pragmatic.mixins import SlugMixin


class AbstractProduct(models.Model):
    in_stock = models.SmallIntegerField(_('in stock'), help_text=_('empty value means infinite availability'), validators=[MinValueValidator(0)], blank=True, null=True, default=None)
    price = models.DecimalField(_('price'), help_text=commerce_settings.CURRENCY, max_digits=10, decimal_places=2, db_index=True, validators=[MinValueValidator(0)],
                                blank=True, null=True, default=None)
    # discount = models.DecimalField(_(u'discount (%)'), max_digits=4, decimal_places=1, default=0)
    awaiting = models.BooleanField(_('awaiting'), default=False)
    options = models.ManyToManyField('commerce.Option', verbose_name=_('options'), blank=True)

    # WARNING! don't use generic relation in parent classes. Add them into child classes instead
    # cart_items = GenericRelation('commerce.Item', related_query_name='product')

    class Meta:
        abstract = True

    def get_add_to_cart_url(self):
        content_type = ContentType.objects.get_for_model(self)
        return reverse('commerce:add_to_cart', args=(content_type.id, self.id))


class Shipping(models.Model):
    title = models.CharField(_('title'), max_length=50)
    fee = models.DecimalField(_('fee'), help_text=commerce_settings.CURRENCY, max_digits=10, decimal_places=2, db_index=True, validators=[MinValueValidator(0)])
    countries = ArrayField(verbose_name=_('countries'),
                           base_field=CountryField(verbose_name=_('country')), size=50,
                           blank=True, default=list)
    i18n = TranslationField(fields=('title',))

    class Meta:
        verbose_name = _('shipping option')
        verbose_name_plural = _('shipping options')
        ordering = ('fee',)
        indexes = [GinIndex(fields=["i18n"]), ]

    def __str__(self):
        return self.title_i18n

    def get_fee_display(self):
        return f'{self.fee} {commerce_settings.CURRENCY}'


class Payment(models.Model):
    METHOD_CASH_ON_DELIVERY = 'CASH_ON_DELIVERY'
    METHOD_WIRE_TRANSFER = 'WIRE_TRANSFER'
    METHOD_ONLINE_PAYMENT = 'ONLINE_PAYMENT'
    METHOD_PAYPAL = 'PAYPAL'
    METHODS = [
        (METHOD_CASH_ON_DELIVERY, _('cash on delivery')),
        (METHOD_WIRE_TRANSFER, _('wire transfer')),
        (METHOD_ONLINE_PAYMENT, _('online payment')),
        (METHOD_PAYPAL, 'PayPal'),
    ]

    title = models.CharField(_('title'), max_length=50)
    method = models.CharField(_('method'), choices=METHODS, max_length=16)
    fee = models.DecimalField(_('fee'), help_text=commerce_settings.CURRENCY, max_digits=10, decimal_places=2, db_index=True, validators=[MinValueValidator(0)])
    shippings = models.ManyToManyField(Shipping)
    i18n = TranslationField(fields=('title',))

    class Meta:
        verbose_name = _('payment method')
        verbose_name_plural = _('payment methods')
        ordering = ('fee',)
        indexes = [GinIndex(fields=["i18n"]), ]

    def __str__(self):
        return self.title_i18n

    def get_fee_display(self):
        return f'{self.fee} {commerce_settings.CURRENCY}'


class Discount(models.Model):
    USAGE_ONE_TIME = 'ONE_TIME'
    USAGE_INFINITE = 'INFINITE'
    USAGES = [
        (USAGE_ONE_TIME, _('one-time only')),
        (USAGE_INFINITE, _('infinite')),
    ]
    code = models.CharField(_('code'), max_length=10, unique=True)
    amount = models.PositiveSmallIntegerField(verbose_name=_('amount'), help_text='%', validators=[MinValueValidator(0), MaxValueValidator(100)])
    usage = models.CharField(_('usage'), choices=USAGES, max_length=8)
    description = models.CharField(_('description'), max_length=100)
    valid_until = models.DateTimeField(_('valid until'), db_index=True)
    promoted = models.BooleanField(_('promoted'), default=False, help_text=_('show in topbar'))
    add_to_cart = models.BooleanField(_('add to cart'), default=False, help_text=_('automatically'))
    content_types = models.ManyToManyField(ContentType, verbose_name=_('content types'))
    i18n = TranslationField(fields=('description',))
    objects = DiscountCodeQuerySet.as_manager()

    class Meta:
        verbose_name = _('discount')
        verbose_name_plural = _('discounts')
        ordering = ('valid_until', )
        indexes = [GinIndex(fields=["i18n"]), ]

    def __str__(self):
        return str(self.code)

    def get_amount_display(self):
        return f'-{self.amount}%'

    @property
    def is_valid(self):
        return self.valid_until > now()

    @property
    def is_used(self):
        if self.usage == self.USAGE_INFINITE:
            return False

        in_cart = Cart.objects.filter(discount=self).exists()

        if in_cart:
            return True

        in_order = Order.objects.filter(discount=self).exists()

        return in_order


class Cart(models.Model):
    user = models.OneToOneField(get_user_model(), on_delete=models.CASCADE)

    # delivery information
    delivery_name = models.CharField(_('full name or company name'), max_length=30, db_index=True)
    delivery_street = models.CharField(_('street and number'), max_length=200)
    delivery_postcode = models.CharField(_('postcode'), max_length=30)
    delivery_city = models.CharField(_('city'), max_length=50)
    delivery_country = CountryField(verbose_name=_('country'), db_index=True)

    # billing address
    billing_name = models.CharField(_('full name or company name'), max_length=100)
    billing_street = models.CharField(_('street and number'), max_length=200)
    billing_postcode = models.CharField(_('postcode'), max_length=30)
    billing_city = models.CharField(_('city'), max_length=50)
    billing_country = CountryField(verbose_name=_('country'), db_index=True)

    # billing company details
    reg_id = models.CharField(_('Company Registration No.'), max_length=30, blank=True)
    tax_id = models.CharField(verbose_name=_('TAX ID'), max_length=30, blank=True)
    vat_id = VATNumberField(verbose_name=_('VAT ID'), blank=True)

    # Contact details
    email = models.EmailField(_('email'))
    phone = models.CharField(_('phone'), max_length=30)

    # Shipping and Payment
    shipping_option = models.ForeignKey(Shipping, verbose_name=_('shipping option'), on_delete=models.PROTECT, null=True, default=None)
    payment_method = models.ForeignKey(Payment, verbose_name=_('payment method'), on_delete=models.PROTECT, null=True, default=None)

    # Discount
    discount = models.ForeignKey(Discount, verbose_name=_('discount'), on_delete=models.PROTECT, blank=True, null=True, default=None)

    # Datetimes
    created = models.DateTimeField(_('created'), auto_now_add=True, db_index=True)
    modified = models.DateTimeField(_('modified'), auto_now=True)

    class Meta:
        verbose_name = _('shopping cart')
        verbose_name_plural = _('shopping carts')

    def __str__(self):
        return ugettext(f'Shopping cart of {self.user}')

    def get_absolute_url(self):
        return reverse('commerce:cart')

    @classmethod
    def get_for_user(cls, user):
        return cls.objects.get_or_create(user=user)[0]

    @property
    def shipping_fee(self):
        return self.shipping_option.fee if self.shipping_option else 0

    def get_subtotal_display(self):
        return f'{self.subtotal} {commerce_settings.CURRENCY}'

    def get_shipping_fee_display(self):
        return f'{self.shipping_fee} {commerce_settings.CURRENCY}'

    @property
    def payment_fee(self):
        return self.payment_method.fee if self.payment_method else 0

    def get_payment_fee_display(self):
        return f'{self.payment_fee} {commerce_settings.CURRENCY}'

    @property
    def subtotal(self):
        return sum([item.subtotal for item in self.item_set.all()])

    def get_subtotal_display(self):
        return f'{self.subtotal} {commerce_settings.CURRENCY}'

    @property
    def total(self):
        total = self.subtotal
        total += self.shipping_fee
        total += self.payment_fee
        # TODO - discount
        return total

    def get_total_display(self):
        return f'{self.total} {commerce_settings.CURRENCY}'

    @property
    def open(self):
        return now() - self.created
    
    @property
    def items_quantity(self):
        return sum([item.quantity for item in self.item_set.all()])

    def is_empty(self):
        return self.items_quantity <= 0

    def can_be_finished(self):
        # TODO: check if all fields are set

        if not self.shipping_option or not self.payment_method:
            return None

        return not self.is_empty()
    
    def has_item(self, product, option=None):
        return self.item_set.filter(
            content_type=ContentType.objects.get_for_model(product),
            object_id=product.id,
            option=option
        ).exists()

    def add_item(self, product, option=None):
        item, created = Item.objects.get_or_create(
            cart=self,
            content_type=ContentType.objects.get_for_model(product),
            object_id=product.id,
            option=option
        )

        if not created:
            item.quantity += 1
            item.save(update_fields=['quantity'])

        return item

    def to_order(self, status):
        if not self.can_be_finished():
            return None

        # create order with cart data
        order = Order.objects.create(
            user=self.user,
            status=status,
            delivery_name=self.delivery_name,
            delivery_street=self.delivery_street,
            delivery_postcode=self.delivery_postcode,
            delivery_city=self.delivery_city,
            delivery_country=self.delivery_country,
            billing_name=self.billing_name,
            billing_street=self.billing_street,
            billing_postcode=self.billing_postcode,
            billing_city=self.billing_city,
            billing_country=self.billing_country,
            reg_id=self.reg_id,
            tax_id=self.tax_id,
            vat_id=self.vat_id,
            email=self.email,
            phone=self.phone,
            shipping_option=self.shipping_option,
            shipping_fee=self.shipping_fee,
            payment_method=self.payment_method,
            payment_fee=self.payment_fee,
            discount=self.discount
        )

        for item in self.item_set.all():
            PurchasedItem.objects.create(
                order=order,
                content_type=item.content_type,
                object_id=item.object_id,
                quantity=item.quantity,
                price=item.price,
                option=item.option
            )

        if order:
            # delete not useful cart anymore
            self.delete()

        # return order
        return order


class Option(SlugMixin, models.Model):
    title = models.CharField(_('title'), max_length=100, unique=True)
    slug = models.SlugField(unique=True, max_length=150, blank=True, db_index=True)
    content_type = models.ForeignKey(
        ContentType, verbose_name=_('content type'), on_delete=models.SET_NULL,
        blank=True, null=True, default=None)  # or many to many?
    i18n = TranslationField(fields=('title', 'slug'))

    class Meta:
        verbose_name = _('option')
        verbose_name_plural = _('options')
        ordering = ('title',)
        indexes = [GinIndex(fields=["i18n"]), ]

    def __str__(self):
        return self.title_i18n


class Item(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    product = GenericForeignKey('content_type', 'object_id')
    option = models.ForeignKey(Option, on_delete=models.PROTECT, blank=True, null=True, default=None)
    quantity = models.PositiveSmallIntegerField(verbose_name=_('quantity'), default=1)
    created = models.DateTimeField(_('created'), auto_now_add=True, db_index=True)
    modified = models.DateTimeField(_('modified'), auto_now=True)

    class Meta:
        verbose_name = _('item')
        verbose_name_plural = _('items')

    def __str__(self):
        return str(self.product)

    def get_absolute_url(self):
        return self.product.get_absolute_url()

    @property
    def regular_price(self):
        return self.product.price

    def get_regular_price_display(self):
        return f'{self.regular_price} {commerce_settings.CURRENCY}'

    @property
    def price(self):
        product = self.product
        discount = self.cart.discount

        if discount:
            ct = ContentType.objects.get_for_model(product)
            if ct in discount.content_types.all():
                from commerce.templatetags.commerce import discount_price
                return Decimal(discount_price(product.price, discount.amount))
        return self.regular_price

    def get_price_display(self):
        return f'{self.price} {commerce_settings.CURRENCY}'

    @property
    def subtotal(self):
        return self.quantity * self.price

    def get_subtotal_display(self):
        return f'{self.subtotal} {commerce_settings.CURRENCY}'


class Order(models.Model):
    # STATUS_PENDING = 'PENDING'                              # Customer started the checkout process but did not complete it. Incomplete orders are assigned a "Pending" status
    STATUS_AWAITING_PAYMENT = 'AWAITING_PAYMENT'            # Customer has completed the checkout process, but payment has yet to be confirmed. Authorize only transactions that are not yet captured have this status.
    STATUS_AWAITING_FULFILLMENT = 'AWAITING_FULFILLMENT'    # Customer has completed the checkout process and payment has been confirmed.
    STATUS_AWAITING_SHIPMENT = 'AWAITING_SHIPMENT'          # Order has been pulled and packaged and is awaiting collection from a shipping provider.
    STATUS_AWAITING_PICKUP = 'AWAITING_PICKUP'              # Order has been packaged and is awaiting customer pickup from a seller-specified location.
    STATUS_PARTIALLY_SHIPPED = 'PARTIALLY_SHIPPED'          # Only some items in the order have been shipped, due to some products being pre-order only or other reasons.
    STATUS_SHIPPED = 'SHIPPED'                              # Order has been shipped, but receipt has not been confirmed; seller has used the Ship Items action.
    STATUS_COMPLETED = 'COMPLETED'                          # Order has been shipped/picked up, and receipt is confirmed; client has paid for their digital product, and their file(s) are available for download.
    STATUS_CANCELLED = 'CANCELLED'                          # Seller has cancelled an order, due to a stock inconsistency or other reasons. Stock levels will automatically update depending on your Inventory Settings. Cancelling an order will not refund the order.
    STATUS_DECLINED = 'DECLINED'                            # Seller has marked the order as declined for lack of manual payment, or other reasons
    STATUS_REFUNDED = 'REFUNDED'                            # Seller has used the Refund action.
    STATUS_PARTIALLY_REFUNDED = 'PARTIALLY_REFUNDED'        # Seller has partially refunded the order.
    STATUS_DISPUTED = 'DISPUTED'                            # Customer has initiated a dispute resolution process for the transaction that paid for the order.
    STATUS_ON_HOLD = 'ON_HOLD'                              # Order on hold while some aspect (e.g. tax-exempt documentation) needs to be manually confirmed. Orders with this status must be updated manually. Capturing funds or other order actions will not automatically update the status of an order.

    STATUSES = [
        # (STATUS_PENDING, _('Pending')),
        (STATUS_AWAITING_PAYMENT, _('Awaiting Payment')),
        (STATUS_AWAITING_FULFILLMENT, _('Awaiting Fulfillment')),
        (STATUS_AWAITING_SHIPMENT, _('Awaiting Shipment')),
        (STATUS_AWAITING_PICKUP, _('Awaiting Pickup')),
        (STATUS_PARTIALLY_SHIPPED, _('Partially Shipped')),
        (STATUS_SHIPPED, _('Shipped')),
        (STATUS_COMPLETED, _('Completed')),
        (STATUS_CANCELLED, _('Cancelled')),
        (STATUS_DECLINED, _('Declined')),
        (STATUS_REFUNDED, _('Refunded')),
        (STATUS_PARTIALLY_REFUNDED, _('Partially Refunded')),
        (STATUS_DISPUTED, _('Disputed')),
        (STATUS_ON_HOLD, _('On hold')),
    ]

    user = models.ForeignKey(get_user_model(), on_delete=models.SET_NULL, null=True)
    status = models.CharField(_('status'), choices=STATUSES, max_length=20)
    number = models.PositiveSmallIntegerField(verbose_name=_('number'), db_index=True, unique=True)

    # delivery information
    delivery_name = models.CharField(_('full name or company name'), max_length=30, db_index=True)
    delivery_street = models.CharField(_('street and number'), max_length=200)
    delivery_postcode = models.CharField(_('postcode'), max_length=30)
    delivery_city = models.CharField(_('city'), max_length=50)
    delivery_country = CountryField(verbose_name=_('country'), db_index=True)

    # billing details
    billing_name = models.CharField(_('full name or company name'), max_length=100)
    billing_street = models.CharField(_('street'), max_length=200)
    billing_postcode = models.CharField(_('postcode'), max_length=30)
    billing_city = models.CharField(_('city'), max_length=50)
    billing_country = CountryField(verbose_name=_('country'), db_index=True)

    reg_id = models.CharField(_('Company Registration No.'), max_length=30, blank=True)
    tax_id = models.CharField(verbose_name=_('TAX ID'), max_length=30, blank=True)
    vat_id = VATNumberField(verbose_name=_('VAT ID'), blank=True)

    # Contact details
    email = models.EmailField(_('email'))
    phone = models.CharField(_('phone'), max_length=30)

    # Shipping
    shipping_option = models.ForeignKey(Shipping, on_delete=models.PROTECT, null=True, default=None)
    shipping_fee = models.DecimalField(_('shipping fee'), help_text=commerce_settings.CURRENCY, max_digits=10, decimal_places=2, db_index=True, validators=[MinValueValidator(0)])

    # Payment method
    payment_method = models.ForeignKey(Payment, on_delete=models.PROTECT, null=True, default=None)
    payment_fee = models.DecimalField(_('payment fee'), help_text=commerce_settings.CURRENCY, max_digits=10, decimal_places=2, db_index=True, validators=[MinValueValidator(0)])

    # Invoices
    invoices = models.ManyToManyField(to='invoicing.Invoice', verbose_name=_('invoices'), blank=True, related_name='orders')

    # Discount
    discount = models.ForeignKey(Discount, verbose_name=_('discount'), on_delete=models.PROTECT, blank=True, null=True, default=None)

    created = models.DateTimeField(_('created'), auto_now_add=True, db_index=True)
    modified = models.DateTimeField(_('modified'), auto_now=True)

    objects = OrderQuerySet.as_manager()

    class Meta:
        verbose_name = _('order')
        verbose_name_plural = _('orders')
        ordering = ('created', )

    def __str__(self):
        return str(self.number)

    def get_absolute_url(self):
        # return '#'
        # TODO
        # return reverse('commerce:order_detail', args=(self.number,))
        return reverse('commerce:orders')

    def get_payment_url(self):
        return reverse('commerce:order_payment', args=(self.number,))

    def render_payment_button(self):
        manager_class = import_string(commerce_settings.PAYMENT_MANAGER)
        manager = manager_class(self)
        return manager.render_payment_button()

    @property
    def total(self):
        total = 0

        for item in self.purchaseditem_set.all():
            total += item.subtotal

        total += self.shipping_fee
        total += self.payment_fee
        # TODO - discount
        return total

    def get_total_display(self):
        return f'{self.total} {commerce_settings.CURRENCY}'

    @staticmethod
    def get_next_number():
        with transaction.atomic():
            Order.objects.lock()

            last_order = Order.objects.all().order_by('number').last()

            next_number = last_order.number + 1 if last_order else int(commerce_settings.ORDER_NUMBER_STARTS_FROM)

            # order number has to be unique
            while Order.objects.filter(number=next_number).exists():
                next_number += 1

            return next_number

    @transaction.atomic
    def save(self, *args, **kwargs):
        if self.number in EMPTY_VALUES:
            self.number = Order.get_next_number()

        return super().save(*args, **kwargs)

    def create_invoice(self, type=Invoice.TYPE.INVOICE, status=Invoice.STATUS.SENT):
        if self.total == 0:
            return

        language = self.user.preferred_language

        translation.activate(language)

        with override(language):
            issue_date = now().date()
            invoice = Invoice.objects.create(
                type=type,
                status=status,
                language=language,
                date_issue=issue_date,
                date_tax_point=issue_date,
                date_due=issue_date+relativedelta(days=7),
                currency=commerce_settings.CURRENCY,
                # credit=
                # already_paid=
                # payment_method=Invoice.PAYMENT_METHOD.BANK_TRANSFER,
                # payment_method=Invoice.PAYMENT_METHOD.BANK_TRANSFER if self.payment_method.method == Payment.METHOD_WIRE_TRANSFER
                # constant_symbol=
                variable_symbol=self.number,
                bank_name=settings.INVOICING_BANK['name'],
                bank_iban=settings.INVOICING_BANK['iban'],
                bank_swift_bic=settings.INVOICING_BANK['swift_bic'],
                supplier_name=settings.INVOICING_SUPPLIER['name'],
                supplier_street=settings.INVOICING_SUPPLIER['street'],
                supplier_zip=settings.INVOICING_SUPPLIER['zip'],
                supplier_city=settings.INVOICING_SUPPLIER['city'],
                supplier_country=settings.INVOICING_SUPPLIER['country_code'],
                supplier_registration_id=settings.INVOICING_SUPPLIER['registration_id'],
                supplier_tax_id=settings.INVOICING_SUPPLIER['tax_id'],
                supplier_vat_id=settings.INVOICING_SUPPLIER['vat_id'],
                # issuer_name
                issuer_email=settings.CONTACT_EMAIL,
                # issuer_phone
                customer_name=self.billing_name,
                customer_street=self.billing_street,
                customer_zip=self.billing_postcode,
                customer_city=self.billing_city,
                customer_country=self.billing_country,
                customer_registration_id=self.reg_id,
                customer_tax_id=self.tax_id,
                customer_vat_id=self.vat_id,
                customer_email=self.user.email,
                customer_phone=self.user.phone,
                shipping_name=self.delivery_name,
                shipping_street=self.delivery_street,
                shipping_zip=self.delivery_postcode,
                shipping_city=self.delivery_city,
                shipping_country=self.delivery_country,
                # delivery_method=Invoice.DELIVERY_METHOD.
            )

            for purchaseditem in self.purchaseditem_set.all():
                item = InvoiceItem.objects.create(
                    invoice=invoice,
                    title=purchaseditem.title_with_option,
                    quantity=purchaseditem.quantity,
                    # unit=UNIT_PIECES
                    unit_price=purchaseditem.price,
                    # discount=self.discount,  # TODO
                    # tax_rate=#TODO: settings: is price with VAT already?
                )

            self.invoices.add(invoice)


class PurchasedItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.PositiveIntegerField()
    product = GenericForeignKey('content_type', 'object_id')
    option = models.ForeignKey(Option, on_delete=models.PROTECT, blank=True, null=True, default=None)
    quantity = models.PositiveSmallIntegerField(verbose_name=_('quantity'))
    price = models.DecimalField(_('price'), help_text=commerce_settings.CURRENCY, max_digits=10, decimal_places=2, db_index=True, validators=[MinValueValidator(0)])
    created = models.DateTimeField(_('created'), auto_now_add=True, db_index=True)
    modified = models.DateTimeField(_('modified'), auto_now=True)

    class Meta:
        verbose_name = _('purchased item')
        verbose_name_plural = _('purchased items')

    def __str__(self):
        return str(self.product)

    @property
    def title_with_option(self):
        return f'{self.product} ({self.option})' if self.option else str(self.product)

    @property
    def subtotal(self):
        return self.quantity * self.price

    def get_absolute_url(self):
        return self.product.get_absolute_url()


from .signals import *
