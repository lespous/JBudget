import pytest

from jbudget.normalize import fold, merchant_from_ing, merchant_from_visa, parse_amount


@pytest.mark.parametrize("label, expected", [
    ("Paiement Bancontact 02/01/26 - 9h12 - PHARMACIE CENTRALE 1000 - BRUXELLES - BEL Numéro de carte 1234 56XX XXXX 0000",
     "PHARMACIE CENTRALE"),
    ("Paiement Bancontact 03/01/26 - 14h41 - LES DELICES 1348 - OTTIGNIES-LOU - BEL Numéro de carte 1234 56XX XXXX 0000",
     "LES DELICES"),
    ("Paiement Debit Mastercard 11/01/26 - 12h05 - INT*AIR-serv Belgium 2300 - Turnhout - BEL Numéro de carte 1234",
     "INT*AIR-SERV BELGIUM"),
    ("Paiement carburant Bancontact 08/01/26 - 15h26 - ESSO NAMUR 5000 - NAMUR - BEL 49,67 litres", "ESSO NAMUR"),
    ("P2P Mobile - Transfert Bancontact 05/02/26 - 11h23 - Dupont Marie Numéro de carte 1234 56XX XXXX 0000",
     "DUPONT MARIE"),
    ("Virement instantané en euros: ING app Vers: M JEAN DUPONT - BE71096123456769 Instantané le 05/01",
     "M JEAN DUPONT"),
    ("Domiciliation en euros (SEPA) GREENPEACE BELGIUM Avis en annexe", "GREENPEACE BELGIUM"),
    ("Paiement ING : VISA    REF 361 21971670-03/273 R.621971670878", "ING VISA"),
    ("CREDIT HYPOTHECAIRE 240809 ECHEANCE   : DECEMBRE", "CREDIT HYPOTHECAIRE"),
])
def test_merchant_from_ing(label, expected):
    assert merchant_from_ing(label) == expected


def test_merchant_from_visa_drops_references():
    assert merchant_from_visa("AMAZON.BE WJ2QM71D5 LUXEMBOURG") == "AMAZON.BE LUXEMBOURG"
    assert merchant_from_visa("PAYPAL SPOTIFY P4655583B 35314369001") == "PAYPAL SPOTIFY"


def test_parse_amount():
    assert parse_amount("-39,10") == -3910
    assert parse_amount("2.078,15") == 207815
    assert parse_amount("3262,07") == 326207


def test_fold_ignores_accents_and_case():
    assert fold("  Médecins  sans FRONTIÈRES ") == "medecins sans frontieres"
