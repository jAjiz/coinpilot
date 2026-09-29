import pytest

from exchange.signing import encode_body, sign

# Kraken's own worked example, from the Spot REST Authentication guide. It is the whole
# reason this module can be trusted without ever making a request. The secret is public:
# it is printed in Kraken's documentation, and it is allowed past the scanner on this one
# line because it looks exactly like a real key.
VECTOR_SECRET = "kQH5HW/8p1uGOVjbgWA7FunAmGO8lsSUXNsu3eow76sz84Q18fWxnyRzBHCd3pd5nE9qa99HAZtuZuj6F1huXg=="  # noqa: E501  # gitleaks:allow
VECTOR_NONCE = "1616492376594"
VECTOR_BODY = "nonce=1616492376594&ordertype=limit&pair=XBTUSD&price=37500&type=buy&volume=1.25"
VECTOR_PATH = "/0/private/AddOrder"
VECTOR_SIGNATURE = "4/dpxb3iT4tp/ZCVEwSnEsLxx0bqyhLpdfOpc6fn7OR8+UClSV5n9E6aSS8MPtnRfp32bAb0nmbRn6H8ndwLUQ=="


def test_the_signature_matches_krakens_published_example():
    assert sign(VECTOR_PATH, VECTOR_NONCE, VECTOR_BODY, VECTOR_SECRET) == VECTOR_SIGNATURE


def test_the_path_is_part_of_the_signature():
    """A signature valid for one endpoint must not be valid for another."""
    other = sign("/0/private/Balance", VECTOR_NONCE, VECTOR_BODY, VECTOR_SECRET)

    assert other != VECTOR_SIGNATURE


def test_the_nonce_is_part_of_the_signature():
    other = sign(VECTOR_PATH, "1616492376595", VECTOR_BODY, VECTOR_SECRET)

    assert other != VECTOR_SIGNATURE


def test_a_secret_that_is_not_base64_raises_rather_than_signing_nonsense():
    """A mistyped secret must fail here, not produce a signature Kraken silently rejects."""
    with pytest.raises(ValueError):
        sign(VECTOR_PATH, VECTOR_NONCE, VECTOR_BODY, "not base64 at all!!")


def test_the_body_encoding_keeps_the_order_it_was_given():
    """The signed bytes and the sent bytes must be identical, so the order cannot drift."""
    body = encode_body({"nonce": "1", "pair": "XBTEUR", "type": "buy"})

    assert body == "nonce=1&pair=XBTEUR&type=buy"


def test_the_body_encoding_escapes_what_a_url_cannot_carry():
    body = encode_body({"nonce": "1", "cl_ord_id": "a b/c"})

    assert body == "nonce=1&cl_ord_id=a+b%2Fc"


def test_encoding_the_vector_payload_reproduces_the_vector_body():
    """Proof that `encode_body` is what produced the string the signature test pins."""
    body = encode_body(
        {
            "nonce": "1616492376594",
            "ordertype": "limit",
            "pair": "XBTUSD",
            "price": "37500",
            "type": "buy",
            "volume": "1.25",
        }
    )

    assert body == VECTOR_BODY
