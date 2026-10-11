"""Reading year/make/model out of a pasted listing URL, before anything is fetched."""

import pytest

from api import url_import


@pytest.mark.parametrize(
    "url, year, make, model, variant",
    [
        ("https://www.2cheapcars.co.nz/car/121007/2015-mitsubishi-delica-d2-hatchback",
         2015, "Mitsubishi", "Delica", "d2 hatchback"),
        ("https://www.booran.com.au/cars/used-white-2022-hyundai-santa-fe-s209713",
         2022, "Hyundai", "Santa Fe", None),
        ("https://example.com/vehicles/new-2023-mercedes-benz-c200",
         2023, "Mercedes-Benz", "C200", None),
        ("https://example.com/stock/2020-land-rover-defender-110",
         2020, "Land Rover", "Defender 110", None),
    ],
)
def test_slug_guess(url, year, make, model, variant):
    guess = url_import.guess_vehicle_from_url(url)
    assert guess is not None
    assert (guess.year, guess.make, guess.model, guess.variant) == (year, make, model, variant)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/listing/abc",
        "https://example.com/cars/2022-unknownmake-thing",
        "https://example.com/about-us-since-1993",
    ],
)
def test_no_guess_rather_than_a_wrong_one(url):
    assert url_import.guess_vehicle_from_url(url) is None


@pytest.mark.parametrize(
    "title, make, model, year, variant",
    [
        ("Used 2018 Grey Peugeot 5008 GT Line Wagon For Sale - Drive", "Peugeot", "5008", 2018, "GT Line Wagon"),
        ("2019 Toyota 86 GTS Coupe for sale", "Toyota", "86", 2019, "GTS Coupe"),
        ("2020 Mazda CX-5 Maxx Sport", "Mazda", "CX-5", 2020, "Maxx Sport"),
    ],
)
def test_page_titles_with_numbered_models(title, make, model, year, variant):
    d = url_import.extract_vehicle_details(f"<html><head><title>{title}</title></head></html>")
    assert (d.make, d.model, d.year, d.variant) == (make, model, year, variant)

