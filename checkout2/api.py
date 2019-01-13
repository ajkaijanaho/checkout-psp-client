import hmac
import logging
import json
from secrets import token_urlsafe
from urllib.parse import urljoin, urlparse, urlencode
from requests import Session, Request
from datetime import datetime, timezone

class Error(Exception):
    pass

class ResponseSignatureError(Error):
    pass

class ProviderError(Error):
    def __init__(self, response):
        self.response = response

def query_url(base, **kwargs):
    """Returns an URL where the kwargs have been converted into a query string"""

    return urlparse(base)._replace(query=urlencode(kwargs)).geturl()


def signature_payload(headers, body = None):
    """Converts a message into a payload to be fed to the signature algorithm.

    The Checkout API requires every request and response to be signed.
    The first step in the signature process is to convert the request or
    response into a payload string.  This function does that.

    Args:
      headers: A dictionary of headers in the message (must include all checkout- headers, others optional)
      body: (optional) A bytes object containing the body to be sent

    Returns:
      A string object ready for signature computation.
    """

    hs = []
    for hn, hd in headers.items():
        hn = hn.lower()
        if hn.startswith("checkout-"):
            hs.append((hn, hd))
    return b"\n".join([ hn.encode() + b":" + hd.encode()
                       for hn, hd in sorted(hs, key=lambda x: x[0])] +
                      ([body] if body is not None else [b""]))


class CheckoutResponse:
    """A successful Checkout API response

    Attributes:
        request_id: A request ID that Checkout Finland recommends be stored
            or logged.
        data: A list/dict soup parsed from the JSON body of the response
    """

    def __init__(self, resp):
        self.request_id = resp.headers["cof-request-id"]
        self.data = resp.json()

    def __str__(self):
        return "CheckoutResponse:\n\tcof-request-id: {}\n\tjson: {}\n"\
            .format(self.request_id,
                    self.data)

class PaymentRequest:
    """A payment request to be submitted to the payment service"""

    def __init__(self,
                 reference,
                 redirect_success,
                 redirect_cancel,
                 email,
                 first_name = None,
                 last_name = None,
                 phone = None,
                 vat_id = None,
                 language = "FI"):
        """Creates a payment request.

        Args:
            reference: The merchant's reference for this order (string)
            redirect_success: URL to redirect to on success (string)
            redirect_cancel: URL to redirect to on cancellation (string)
            email: Customer email address (string)
            first_name: Customer first name (string, optional)
            last_name: Customer last name (string, optional)
            phone: Customer phone number (string, optional)
            vat_id: Customer's EU VAT number (string, optional)
            language: Payment language, one of FI, SV, or EN (string)
        """

        self._items = []
        self._total_amount = 0
        customer = { "email": email }
        if first_name is not None:
            customer["firstName"] = first_name
        if last_name is not None:
            customer["lastName"] = last_name
        if phone is not None:
            customer["phone"] = phone
        if vat_id is not None:
            customer["vatId"] = vat_id
        self._obj = { "reference": reference,
                      "stamp": "{}@{}".format(reference,
                                              datetime.now().timestamp()),
                      "currency": "EUR",
                      "language": language,
                      "customer": customer,
                      "redirectUrls": { "success": redirect_success,
                                        "cancel": redirect_cancel } }

    def add_callback_urls(success, cancel):
        self._obj["callbackUrls"] = { "success": success,
                                      "cancel": cancel }

    @property
    def jsonable(self):
        self._obj["items"] = self._items
        self._obj["amount"] = self._total_amount
        return self._obj

    def add_item(self,
                 product_code,
                 delivery_date,
                 unit_price,
                 unit_count,
                 vat_rate,
                 description = None,
                 category = None):
        """Adds an item to this payment request.

        IMPORTANT: The unit price is an integer number of eurocents.
        Thus, a unit price of 15 euros would be represented as 1500.

        Args:
            product_code: A merchant specific product code (string)
            delivery_date: Estimated delivery date (datetime.date)
            unit_price: Unit price **in eurocents** (integer)
            unit_count: Number of units included in order (integer)
            vat_rate: VAT rate for this product (integer)
            description: Product description (string, optional)
            category: Product category (string, optional)
        """

        item = { "productCode": product_code,
                 "deliveryDate": delivery_date.isoformat(),
                 "unitPrice": unit_price,
                 "units": unit_count,
                 "vatPercentage": vat_rate }
        if description is not None:
            item["description"] = description
        if category is not None:
            item["category"] = category
        self._items.append(item)
        self._total_amount += unit_price * unit_count




class CheckoutAPI:
    """Wraps the Checkout Finland Payment Service API.

    Each object is specific to a merchant."""

    def __init__(self, merchant_id, secret_key,
                 api_endpoint = "https://api.checkout.fi"):
        """Initializes the API wrapper.

        Args:
          merchant_id: A merchant ID recognized by the service.
          secret_key: The shared secret key associated with this merchant.
          api_endpoint: The URL at which the API is accessed.
        """

        self.merchant_id = merchant_id
        self.secret_key = secret_key
        self.api_endpoint = api_endpoint
        self.algorithm = "sha512"

    @property
    def logger(self):
        """The logger used by this object."""

        return logging.getLogger(__name__)

    def sign_request(self, algorithm, headers, body=None):
        """Computes the request signature for this message.

        The message object given as an argument must contain the following
        properties:
          - headers: a dict-like object containing the request or response
             headers
          - body: a bytes object containing the request or response body
        If body is missing, content is tried in its stead.

        Note that the message is not modified by this method.

        Args:
            algorithm: The name of the signature algorithm to be used
            headers: A dictionary of headers in the message (must include all checkout- headers, others optional)
            body: (optional) A bytes object containing the body to be sent            msg: The message (request or response) to be signed

        Returns:
            The HMAC signature computed.
        """

        return hmac.new(self.secret_key.encode(),
                        signature_payload(headers, body),
                        algorithm)\
                .hexdigest()


    def is_response_ok(self, parameters, body):
        """Checks if the response has a correct signature.

        Args:
            parameters: A dict-like object containing response parameters
                (HTTP headers or derived from a query string)
            body: A bytes object containing the body, or None

        Returns:
            A boolean result: true if the signature was correct.
        """

        return (parameters["signature"]
                ==
                self.sign_request(parameters["checkout-algorithm"],
                                  parameters,
                                  body))

    def send_request(self,
                     path,
                     data,
                     method="POST",
                     transaction_id = None,
                     response_factory = None):
        """Sends a request to the Checkout Finland payment service API.

        Args:
            path: A string object containing a relative URL naming the
                  API object to be called
            data: An object that can be passed to json.dumps for use as
                  the request body
            method: The HTTP method to be used
            transaction_id: (optional) The transaction ID this request is
                  associated with.
            response_factory: (optional) A callable object that takes one
                  argument (the raw requests.Response object)

        Returns:
            The return value of the response_factory; by default, a
            CheckoutResponse object

        Raises:
            ProviderError: The request failed with a 4xx or 5xx error code
            ResponseSignatureError: The request appeared to succeed
                but contained an invalid signature.

        """

        headers = { "content-type": "application/json; charset=utf-8",
                    "checkout-account": self.merchant_id,
                    "checkout-algorithm": self.algorithm,
                    "checkout-method": method,
                    "checkout-nonce": token_urlsafe(),
                    "checkout-timestamp":
                    datetime.now(timezone.utc).isoformat() }
        if transaction_id is not None:
            headers["checkout-transaction-id"] = transaction_id

        with Session() as s:
            req = Request(method,
                          urljoin(self.api_endpoint, path),
                          headers = headers,
                          data = (json.dumps(data).encode()
                                  if data is not None
                                  else None))
            req = s.prepare_request(req)
            sig = self.sign_request(self.algorithm, headers, req.body)
            req.headers["signature"] = sig
            self.logger.info("Sending:\n%s\n%s\n%s\n%s",
                             req,
                             req.url,
                             req.headers,
                             req.body)
            resp = s.send(req)

        if not resp.ok:
            raise ProviderError(resp)
        if not self.is_response_ok(resp.headers, resp.content):
            raise ResponseSignatureError()
        return CheckoutResponse(resp) \
            if response_factory is None \
            else response_factory(resp)

    def list_providers(self, amount = None):
        """Requests from the service a list of available payment providers.

        Args:
            amount: (optional) An integer specifying the purchase value
                 in euros.

        Returns:
            A CheckoutResponse object

        Raises:
            ProviderError: The request failed with a 4xx or 5xx error code
            ResponseSignatureError: The request appeared to succeed
                but contained an invalid signature.
        """
        return self.send_request(query_url("/merchants/payment-providers",
                                           amount=("%d".format(amount)
                                                   if amount is not None
                                                   else None)),
                                 data = None,
                                 method = "GET")

    def create_payment(self, payment_request):
        return self.send_request("/payments",
                                 data = payment_request.jsonable,
                                 method = "POST")