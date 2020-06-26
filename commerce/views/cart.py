from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.contenttypes.models import ContentType
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import ugettext_lazy as _
from django.views import View

from commerce.models import Cart


class AddToCartView(LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        content_type = get_object_or_404(ContentType, id=kwargs['content_type_id'])
        product = get_object_or_404(content_type.model_class(), id=kwargs['object_id'])
        cart = Cart.get_for_user(request.user)

        # TODO: check if product can be added multiple times into cart
        # TODO: max items in cart
        ALLOW_MULTIPLE_SAME_ITEMS = False
        if ALLOW_MULTIPLE_SAME_ITEMS or not cart.has_item(product):
            cart.add_item(product)
            messages.info(request, _(f'{product} was added into cart'))
        else:
            messages.warning(request, _(f'{product} is already in cart'))

        back_url = request.GET.get('back_url', product.get_absolute_url())
        return redirect(back_url)

# from django.contrib import messages
# from django.core.exceptions import ObjectDoesNotExist
# from django.shortcuts import get_object_or_404, redirect
# from django.utils.translation import ugettext_lazy as _
# from django.views.generic.base import View, TemplateResponseMixin
#
# from commerce.utils.cart import get_cart, CART_IDENTIFIER
#
#
# PRODUCT_IDENTIFIER = 'product'
#
#
# class CartView(View, TemplateResponseMixin):
#     template_name = 'commerce/cart/index.html'
#
#     def get(self, request):
#         return self.render_to_response({
#             'cart': get_cart(request),
#         })
#
#
# class BuyView(View):
#     def dispatch(self, request, *args, **kwargs):
#         self.product = get_object_or_404(Product, pk=kwargs.get('pk', None))
#         return super(BuyView, self).dispatch(request, *args, **kwargs)
#
#     def get(self, request, pk):
#         cart = get_cart(request)
#         try:
#             cart.add(self.product, int(request.GET.get('quantity', 1)))
#             request.session[CART_IDENTIFIER] = cart
#             messages.success(
#                 request, _(u'Product successfully added into cart.'))
#         except ValueError:
#             messages.error(request, _(u'Illegal value.'))
#
#         try:
#             return redirect(request.META['HTTP_REFERER'])
#         except KeyError:
#             return redirect('commerce_cart')
#
#
# class EmptyView(View):
#     def get(self, request):
#         cart = request.session[CART_IDENTIFIER]
#         cart.clean()
#         request.session[CART_IDENTIFIER] = cart
#
#         messages.success(request, _(u'Your cart successfully emptied.'))
#         try:
#             return redirect(request.META['HTTP_REFERER'])
#         except KeyError:
#             return redirect('commerce_cart')
#
#
# class RemoveView(View):
#     def dispatch(self, request, *args, **kwargs):
#         self.product = get_object_or_404(Product, pk=kwargs.get('pk', None))
#         return super(RemoveView, self).dispatch(request, *args, **kwargs)
#
#     def get(self, request, pk):
#         cart = request.session[CART_IDENTIFIER]
#         cart.remove(self.product)
#         request.session[CART_IDENTIFIER] = cart
#
#         messages.success(request, _(u'Item successfully removed from cart.'))
#         try:
#             return redirect(request.META['HTTP_REFERER'])
#         except KeyError:
#             return redirect('commerce_cart')
#
#
# class UpdateView(View):
#     def post(self, request):
#         products = self._get_parsed_products(request.POST)
#
#         cart = request.session[CART_IDENTIFIER]
#         for key, value in products.items():
#             try:
#                 product = Product.objects.get(pk=key)
#                 cart.add(product, value, hard_quantity=True)
#             except ObjectDoesNotExist:
#                 continue
#         request.session[CART_IDENTIFIER] = cart
#
#         messages.success(request, _(u'Cart successfully updated.'))
#         try:
#             return redirect(request.META['HTTP_REFERER'])
#         except KeyError:
#             return redirect('commerce_cart')
#
#     def _get_parsed_products(self, post):
#         results = {}
#
#         for key, value in post.items():
#             values = key.split('-')
#             if values[0] == PRODUCT_IDENTIFIER:
#                 results[int(values[1])] = int(value)
#
#         return results
