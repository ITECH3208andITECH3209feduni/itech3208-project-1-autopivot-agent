# Tests for the best-effort vehicle-details reader in api/url_import.py.
#
# All pure functions over already-fetched HTML — nothing here makes a network
# request, so this needs none of the ML environment and runs in the light
# test tier alongside test_compositing.py.
#
#     pytest tests/test_url_import.py -v

from api import url_import


def html_page(title="", og_title=None, og_description=None, json_ld=None):
    head = [f"<title>{title}</title>"]
    if og_title is not None:
        head.append(f'<meta property="og:title" content="{og_title}">')
    if og_description is not None:
        head.append(f'<meta property="og:description" content="{og_description}">')
    if json_ld is not None:
        head.append(f'<script type="application/ld+json">{json_ld}</script>')
    return f"<html><head>{''.join(head)}</head><body></body></html>"


# ── The real-world case this was built against ──────────────────────────────
# Confirmed by hand against https://www.sbtjapan.com/used-cars/DBE6495.

def test_sbt_japan_style_title_is_parsed():
    page = html_page(
        title="2006/4 HONDA ACCORD 165554 | SBT Japan | Stock Id:DBE6495",
        og_title="SBT",
        og_description=(
            "2006/4 HONDA ACCORD 165554 Stock Id:DBE6495 . SBT Is a Trusted "
            "Global Used Cars Dealer in Japan since 1993. | SBT Japan"
        ),
    )
    details = url_import.extract_vehicle_details(page)
    assert details is not None
    assert details.make == "Honda"
    assert details.model == "ACCORD"
    assert details.year == 2006
    assert details.stock_number == "DBE6495"


def test_an_unrelated_year_in_boilerplate_does_not_win():
    """"...since 1993" sits later in the combined text than the listing's own
    2006 model year, and reading order — not "first 4-digit number found" —
    is what has to prefer 2006."""
    page = html_page(
        title="2006/4 HONDA ACCORD 165554",
        og_description="A trusted dealer since 1993.",
    )
    details = url_import.extract_vehicle_details(page)
    assert details is not None
    assert details.year == 2006


# ── Structured data ──────────────────────────────────────────────────────────

def test_json_ld_vehicle_is_preferred_over_title_text():
    page = html_page(
        title="Great deal on a car! Click here",
        json_ld="""
        {
          "@context": "https://schema.org",
          "@type": "Car",
          "name": "2021 Mazda CX-5 GT",
          "brand": {"@type": "Brand", "name": "Mazda"},
          "model": "CX-5",
          "vehicleModelDate": "2021",
          "sku": "4471"
        }
        """,
    )
    details = url_import.extract_vehicle_details(page)
    assert details is not None
    assert details.make == "Mazda"
    assert details.model == "CX-5"
    assert details.year == 2021
    assert details.stock_number == "4471"


def test_json_ld_graph_wrapper_is_unwrapped():
    page = html_page(
        title="",
        json_ld="""
        {"@context": "https://schema.org", "@graph": [
          {"@type": "WebPage", "name": "irrelevant"},
          {"@type": "Vehicle", "brand": "Toyota", "model": "Corolla",
           "productionDate": "2019"}
        ]}
        """,
    )
    details = url_import.extract_vehicle_details(page)
    assert details is not None
    assert details.make == "Toyota"
    assert details.model == "Corolla"
    assert details.year == 2019


def test_malformed_json_ld_falls_back_to_title_text_rather_than_raising():
    page = html_page(
        title="2015 Toyota Corolla",
        json_ld="{not valid json",
    )
    details = url_import.extract_vehicle_details(page)
    assert details is not None
    assert details.make == "Toyota"
    assert details.year == 2015


def test_json_ld_of_the_wrong_type_is_ignored():
    """A page can carry JSON-LD for its own navigation or organisation without
    it being about the vehicle at all; that must not be mistaken for one."""
    page = html_page(
        title="2015 Toyota Corolla",
        json_ld="""
        {"@context": "https://schema.org", "@type": "BreadcrumbList",
         "itemListElement": []}
        """,
    )
    details = url_import.extract_vehicle_details(page)
    assert details is not None
    assert details.make == "Toyota"  # fell through to the title, not the breadcrumb


# ── Make/model matching ───────────────────────────────────────────────────────

def test_multi_word_make_is_matched_before_a_shorter_false_match():
    """"Land Rover" must win outright rather than being missed in favour of
    nothing, or split oddly."""
    make, model = url_import._make_and_model_from_text("2018 Land Rover Discovery Sport 45000km")
    assert make == "Land Rover"
    assert model == "Discovery Sport"


def test_hyphenated_make_is_recognised():
    make, model = url_import._make_and_model_from_text("2020 Mercedes-Benz C200 32000km")
    assert make == "Mercedes-Benz"
    assert model == "C200"


def test_no_known_make_in_text_yields_nothing():
    make, model = url_import._make_and_model_from_text("A great little runabout, low kms")
    assert make is None
    assert model is None


# ── Year ───────────────────────────────────────────────────────────────────────

def test_year_outside_plausible_range_is_rejected():
    # 1650 (a plate number, a price, anything) is not a model year.
    assert url_import._year_from_text("Item 1650, phone 0800 123 456") is None


def test_year_one_model_year_ahead_of_today_is_accepted():
    from datetime import date
    next_year = date.today().year + 1
    assert url_import._year_from_text(f"{next_year} release, order now") == next_year


def test_year_two_model_years_ahead_is_rejected():
    from datetime import date
    too_far = date.today().year + 2
    assert url_import._year_from_text(f"{too_far} concept preview") is None


# ── Stock number ───────────────────────────────────────────────────────────────

def test_stock_number_variants_are_all_recognised():
    for text in (
        "Stock Id:DBE6495", "Stock No. DBE6495", "Stock #DBE6495",
        "Stock Number: DBE6495", "stock dbe6495",
    ):
        assert url_import._stock_number_from_text(text) == "DBE6495", text


def test_no_stock_number_present_yields_none():
    assert url_import._stock_number_from_text("A lovely used car for sale") is None


# ── Overall shape ──────────────────────────────────────────────────────────────

def test_a_page_with_nothing_readable_returns_none_not_an_empty_object():
    page = html_page(title="Welcome to our dealership")
    assert url_import.extract_vehicle_details(page) is None


def test_vehicle_details_is_empty_reports_correctly():
    assert url_import.VehicleDetails().is_empty()
    assert not url_import.VehicleDetails(make="Honda").is_empty()
    assert not url_import.VehicleDetails(year=2020).is_empty()
